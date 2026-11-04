"""Actual Chrome public collection controls on new synthetic data; zero real API calls."""
import json
import logging
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server
from platform_app.web import create_app
from portable.worker import PortableWorker
from portable.public_collection import LocalPublicSettings, install_public_control
from tests.test_journal_collection import work, JOURNALS
from tests.test_assisted_intake import PublicSocket


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    evidence=Path(tempfile.mkdtemp(prefix='database-journal118-browser-'))
    state=evidence/'state'
    state.mkdir()
    app=create_app(evidence/'data',testing=True,embedded_worker=False)
    class NoAI:
        def status(self):
            return {'enabled':False,'configured':False}
    worker=PortableWorker(evidence/'data',state,NoAI(),threading.Event(),
        public_settings=LocalPublicSettings(evidence/'copy',storage_root=evidence/'private'))
    install_public_control(app,worker)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}'
    dns_original,connect_original,wrap_original=socket.getaddrinfo,socket.create_connection,ssl.SSLContext.wrap_socket
    requests=[]
    class Fixture(PublicSocket):
        def sendall(sock,data):
            path=data.split(b' ')[1].decode()
            requests.append(path)
            paper=urlsplit(path).path.split('/')[2]
            index=next(i for i,j in enumerate(JOURNALS) if j[1]==paper)
            item=work(index,**({'abstract':'Synthetic actual abstract.'} if index==2 else {}))
            sock.body=PublicSocket(json.dumps({'status':'ok','message':{'items':[item],'total-results':1}}).encode(),'application/json').body
    def dns(host,*args,**kwargs):
        return [(2,1,6,'',('93.184.216.34',443))] if host=='api.crossref.org' else dns_original(host,*args,**kwargs)
    def connect(address,*args,**kwargs):
        return Fixture(b'') if address[0]=='93.184.216.34' else connect_original(address,*args,**kwargs)
    def wrap(context,sock,*args,**kwargs):
        return sock if isinstance(sock,Fixture) else wrap_original(context,sock,*args,**kwargs)
    extension=evidence/'zoom-extension'
    extension.mkdir()
    (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Journal collection zoom check','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}),encoding='utf-8')
    (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});',encoding='utf-8')
    errors=[]
    results=[]
    try:
        with patch('socket.getaddrinfo',side_effect=dns),patch('socket.create_connection',side_effect=connect),patch('ssl.SSLContext.wrap_socket',wrap), \
             patch('platform_app.automatic_processing.run_pending',side_effect=AssertionError('Paid processing dispatched')), \
             patch('platform_app.archive_suggestions.run_pending',side_effect=AssertionError('Paid archive dispatched')):
            with sync_playwright() as p:
                context=p.chromium.launch_persistent_context(str(evidence/'browser'),headless=False,
                    **({'executable_path':os.environ['DATABASE_BROWSER_EXECUTABLE']} if os.environ.get('DATABASE_BROWSER_EXECUTABLE') else {}),
                    ignore_default_args=['--disable-extensions'],args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}'],
                    viewport={'width':1366,'height':900})
                try:
                    zoom_worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                    page=context.pages[0]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(base+'/#system')
                    page.get_by_role('button',name='资料管理员',exact=True).click()
                    page.goto(base+'/#maintenance-ingestion')
                    page.get_by_role('button',name='登记三刊公开来源',exact=True).click()
                    expect(page.locator('[data-form="ingestion-config"]')).to_have_count(3)
                    expect(page.locator('[data-ingestion-total]')).to_contain_text('全部 3 个')
                    for form in page.locator('[data-form="ingestion-config"]').all():
                        form.locator('[name="enabled"]').check()
                        form.get_by_role('button',name='保存此来源设置',exact=True).click()
                    local=page.locator('[data-form="public-collection"]')
                    for checkbox in local.locator('input').all():
                        checkbox.check()
                    local.get_by_role('button',name='开启所选期刊公开采集',exact=True).click()
                    deadline=time.monotonic()+30
                    while True:
                        status=context.request.get(base+'/api/ingestion').json()
                        if len(status['items'])==3 and all(s['runs'] and s['runs'][0]['status']=='succeeded' for s in status['items']):
                            break
                        assert time.monotonic()<deadline,status
                        page.wait_for_timeout(150)
                    page.get_by_role('button',name='刷新状态（保留草稿）',exact=True).click()
                    expect(page.locator('.ingestion-card')).to_contain_text('本轮已完成')
                    # A's archive and B's collector must share the same source ID.
                    journal_id=next(s['source_id'] for s in status['items'] if s['adapter']=='eep-crossref-v1')
                    csrf=context.request.get(base+'/api/session').json()['csrf']
                    linked=context.request.post(base+'/api/journal-results',multipart={
                        'data':json.dumps(dict(journal_id=journal_id,journal_name='东欧政治',year=2026,issue='合成关联期次',request_id='journal118-integrated-link')),
                        'files':{'name':'synthetic-result.txt','mimeType':'text/plain','buffer':b'SYNTHETIC linked journal result'}},
                        headers={'X-CSRF-Token':csrf})
                    assert linked.status==201,linked.text()
                    result_id=linked.json()['id']
                    for width,zoom in ((1366,1),(900,1),(390,1),(1366,2)):
                        page.set_viewport_size({'width':width,'height':900})
                        zoom_worker.evaluate('async ({url,zoom})=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));await chrome.tabs.setZoom(t.id,zoom);}',{'url':base,'zoom':zoom})
                        actual_zoom=zoom_worker.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));return chrome.tabs.getZoom(t.id);}',base)
                        assert actual_zoom==zoom,(actual_zoom,zoom)
                        page.evaluate('window.scrollTo(0,0)')
                        page.wait_for_timeout(100)
                        page.screenshot(path=str(evidence/f'collection-{width}-{zoom}.png'),full_page=False)
                        page.screenshot(path=str(evidence/f'collection-full-{width}-{zoom}.png'),full_page=True)
                        layout=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
                        assert layout['scroll']<=layout['width']+1,layout
                        results.append(dict(width=width,zoom=actual_zoom,layout=layout))
                    local.get_by_role('button',name='暂停本机公开采集',exact=True).click()
                    deadline=time.monotonic()+5
                    while worker.thread.is_alive():
                        assert time.monotonic()<deadline
                        page.wait_for_timeout(100)
                    page.get_by_role('button',name='刷新状态（保留草稿）',exact=True).click()
                    expect(local).to_contain_text('后台已停止')
                    local.get_by_role('button',name='开启所选期刊公开采集',exact=True).click()
                    expect(local).to_contain_text('后台运行中')
                    page.get_by_role('button',name='本刊资料',exact=True).first.click()
                    expect(page.locator('.library-row')).to_have_count(1)
                    page.locator('.library-row .record-title button').first.click()
                    expect(page.locator('.acquisition-reading')).to_contain_text('公开题录JSON')
                    page.goto(base+'/#journal-results?id='+result_id)
                    page.get_by_role('link',name='查找本刊文章',exact=True).click()
                    expect(page.locator('.library-row')).to_have_count(1)
                    page.goto(base+'/#sources?id='+journal_id)
                    expect(page.get_by_role('link',name='按本刊查找成果',exact=True)).to_have_attribute('href','#journal-results?journal_id='+journal_id)
                    page.get_by_role('link',name='东欧政治 · 2026 · 合成关联期次',exact=True).click()
                    expect(page.locator('[data-jr-detail]')).to_have_attribute('data-jr-detail',result_id)
                    assert context.request.get(base+'/api/admin/ai').json()['attempts']==[]
                    assert len(requests)==3,requests
                    assert errors==[],errors
                except Exception:
                    page.screenshot(path=str(evidence/'failed.png'),full_page=True)
                    print('Failed browser evidence:',evidence)
                    raise
                finally:
                    context.close()
    finally:
        worker.stop()
        server.shutdown()
        server.server_close()
    (evidence/'results.json').write_text(json.dumps(dict(results=results,requests=requests,errors=errors,paid_dispatch=False),indent=2),encoding='utf-8')
    print(evidence)


if __name__=='__main__':
    main()
