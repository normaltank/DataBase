"""Real browser and independent synthetic HTTP source; isolated data, UI 8903."""
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from platform_app.web import create_app
from platform_app.ingestion import run_pending
from platform_app import store
from tests.test_discovery import FEED

PORT=int(os.environ.get('DATABASE_BROWSER_PORT','8903'))
URL=f'http://127.0.0.1:{PORT}'
PAGE='<div class="article"><p>Public episode description. No transcript has been acquired.</p><script>window.SOURCE_SCRIPT_EXECUTED=true</script></div><p class="author"><span>Author</span><strong>Ada Example</strong></p>'


class SourceHandler(BaseHTTPRequestHandler):
    fail=True
    requests=[]
    def do_GET(self):
        type(self).requests.append(self.path)
        feed=self.path.endswith('/rss.xml')
        self.send_response(200 if feed or not self.fail else 503)
        body=FEED.encode() if feed else PAGE.encode()
        self.send_header('Content-Type','application/xml' if feed else 'text/html')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)
    def log_message(self,*args):
        pass


class RoutedSocket:
    """Test transport routes a public peer to a separate local HTTP fixture."""
    def __init__(self,sock):self.sock=sock
    def __getattr__(self,key):return getattr(self.sock,key)
    def getpeername(self):return ('93.184.216.34',443)


class Quiet(WSGIRequestHandler):
    def log(self,*args,**kwargs):pass


class IngestionBrowser(unittest.TestCase):
    def test_admin_enable_failure_retry_reader_and_responsive_evidence(self):
        out=Path(tempfile.mkdtemp(prefix='ingestion-browser-'))
        app=create_app(out/'data',testing=True)
        server=make_server('127.0.0.1',PORT,app,threaded=True,request_handler=Quiet)
        source=ThreadingHTTPServer(('127.0.0.1',0),SourceHandler)
        for target in (server.serve_forever,source.serve_forever):
            threading.Thread(target=target,daemon=True).start()
        stop=threading.Event()
        original_dns,original_connect,original_wrap=socket.getaddrinfo,socket.create_connection,ssl.SSLContext.wrap_socket
        def dns(host,*args,**kwargs):
            return [(2,1,6,'',('93.184.216.34',443))] if host in {'liia.lv','www.liia.lv'} else original_dns(host,*args,**kwargs)
        def connect(address,*args,**kwargs):
            return RoutedSocket(original_connect(('127.0.0.1',source.server_port),*args,**kwargs)) if address[0]=='93.184.216.34' else original_connect(address,*args,**kwargs)
        def wrap(context,sock,*args,**kwargs):
            return sock if isinstance(sock,RoutedSocket) else original_wrap(context,sock,*args,**kwargs)
        def worker():
            while not stop.wait(.15):
                run_pending(out/'data')
        try:
            with patch('socket.getaddrinfo',side_effect=dns),patch('socket.create_connection',side_effect=connect),patch('ssl.SSLContext.wrap_socket',wrap),patch('platform_app.store.now',return_value='2026-10-27T12:00:00+00:00'):
                worker_thread=threading.Thread(target=worker,daemon=True);worker_thread.start()
                with sync_playwright() as play:
                    browser=play.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None)
                    try:
                        for width in (1366,390):
                            context=browser.new_context(viewport={'width':width,'height':900})
                            page=context.new_page();errors=[]
                            page.on('pageerror',lambda e:errors.append(str(e)))
                            page.goto(URL+'/#system')
                            page.get_by_role('button',name='资料管理员',exact=True).click()
                            expect(page.get_by_role('heading',name='数据与维护',exact=True)).to_be_visible()
                            if width==1366:
                                csrf=context.request.get(URL+'/api/session').json()['csrf']
                                result=context.request.post(URL+'/api/sources',data={'name':'Synthetic LIIA','kind':'think_tank','website':'https://liia.lv/en/'},headers={'X-CSRF-Token':csrf})
                                self.assertEqual(result.status,201,result.text())
                                page.reload()
                                form=page.locator('[data-form="ingestion-config"]')
                                form.locator('[name=enabled]').check()
                                form.get_by_role('button',name='保存采集设置').click()
                                expect(page.locator('.ingestion-card')).to_contain_text('已启用')
                                for _ in range(50):
                                    status=context.request.get(URL+'/api/ingestion').json()['items'][0]
                                    if status['runs'] and status['runs'][0]['status']=='partial':break
                                    time.sleep(.1)
                                self.assertEqual(status['runs'][0]['status'],'partial')
                                page.get_by_role('button',name='刷新状态',exact=True).click()
                                expect(page.locator('.ingestion-card')).to_contain_text('503')
                                page.locator('.ingestion-card').screenshot(path=str(out/'failure-1366.png'))
                                SourceHandler.fail=False
                                page.get_by_role('button',name='重跑失败条目',exact=True).click()
                                for _ in range(50):
                                    status=context.request.get(URL+'/api/ingestion').json()['items'][0]
                                    if status['runs'][0]['status']=='succeeded':break
                                    time.sleep(.1)
                                self.assertEqual(status['runs'][0]['status'],'succeeded')
                            page.get_by_role('button',name='刷新状态',exact=True).click()
                            expect(page.locator('.ingestion-card')).to_contain_text('本轮已完成')
                            page.locator('.ingestion-card').scroll_into_view_if_needed()
                            page.screenshot(path=str(out/f'admin-{width}.png'),full_page=True)
                            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                            page.locator('.ingestion-run summary').first.click()
                            page.get_by_role('button',name='阅读已保存资料',exact=True).first.click()
                            expect(page.locator('.acquisition-reading')).to_contain_text('未验证所指作品全文')
                            expect(page.locator('.acquisition-reading')).to_contain_text('No transcript has been acquired.')
                            self.assertFalse(page.evaluate('!!window.SOURCE_SCRIPT_EXECUTED'))
                            page.locator('.acquisition-reading').scroll_into_view_if_needed()
                            page.screenshot(path=str(out/f'reader-{width}.png'),full_page=True)
                            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                            self.assertEqual(errors,[])
                            context.close()
                        for width in (1366,390):
                            context=browser.new_context(viewport={'width':width,'height':900})
                            page=context.new_page();errors=[]
                            page.on('pageerror',lambda e:errors.append(str(e)))
                            page.goto(URL)
                            page.get_by_role('button',name='研究员',exact=True).click()
                            expect(page.get_by_role('heading',name='资料',exact=True)).to_be_visible()
                            expect(page.get_by_role('button',name='新文章',exact=True)).to_have_attribute('aria-current','page')
                            page.locator('.library-row .record-title button').first.click()
                            reader=page.locator('.library-reader')
                            expect(reader.locator('.detail-title')).to_be_visible()
                            self.assertEqual(reader.evaluate('(el)=>el.scrollTop'),0)
                            acquisition=reader.locator('.acquisition-reading')
                            self.assertLess(acquisition.locator('.reading-content').evaluate('(el)=>el.getBoundingClientRect().top'),900)
                            page.screenshot(path=str(out/f'researcher-first-{width}.png'))
                            acquisition.scroll_into_view_if_needed()
                            expect(acquisition).to_contain_text('未取得所指作品全文')
                            expect(acquisition).to_contain_text('No transcript has been acquired.')
                            basis=acquisition.locator('details.acquisition-basis')
                            expect(basis).to_have_count(1)
                            self.assertFalse(basis.evaluate('(el)=>el.open'))
                            expect(basis.get_by_text('侧栏原署名：',exact=False)).to_be_hidden()
                            page.screenshot(path=str(out/f'researcher-snapshot-{width}.png'))
                            basis.locator('summary').click()
                            basis.scroll_into_view_if_needed()
                            expect(basis).to_contain_text('Ada Example')
                            expect(basis.get_by_role('link',name='下载原始页面字节',exact=True)).to_be_visible()
                            page.screenshot(path=str(out/f'researcher-basis-{width}.png'))
                            self.assertFalse(page.evaluate('!!window.SOURCE_SCRIPT_EXECUTED'))
                            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                            self.assertEqual(errors,[])
                            context.close()
                    finally:browser.close()
        finally:
            stop.set()
            if 'worker_thread' in locals():worker_thread.join(5)
            server.shutdown();source.shutdown();server.server_close();source.server_close()
        (out/'evidence.json').write_text(json.dumps({'ui_port':PORT,'source_port':source.server_port,'requests':SourceHandler.requests,'screenshots':[p.name for p in out.glob('*.png')]},indent=2),encoding='utf-8')
        print('Evidence:',out,flush=True)


if __name__=='__main__':unittest.main()
