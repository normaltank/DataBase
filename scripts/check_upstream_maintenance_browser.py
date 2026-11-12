"""Issue 66: two real synthetic HTTP sources, browser and new-directory recovery.

No production library, paid provider, local 8848 service or research inputs are
used. Public peers are routed only to the independent loopback fixture below.
"""
import json
import logging
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from platform_app.web import create_app
from platform_app.ingestion import run_pending
from platform_app.maintenance import restore_backup
from tests.test_journal_collection import work


class Source(BaseHTTPRequestHandler):
    phase=0
    stop=threading.Event()
    interrupt=False
    requests=[]
    def do_GET(self):
        type(self).requests.append(dict(path=self.path,phase=self.phase))
        path=urlsplit(self.path).path
        item={**work(),'ISSN':['1406-099X','2334-4385'],'container-title':['Baltic Journal of Economics']}
        if self.phase:
            item['title']=['Changed upstream title']
        status=200
        if path.startswith('/journals/'):
            body=json.dumps(dict(status='ok',message={'items':[item] if self.phase==0 else [],'total-results':1 if self.phase==0 else 0})).encode()
            content_type='application/json'
            if self.interrupt:self.stop.set()
        elif path.startswith('/works/'):
            assert unquote(path.removeprefix('/works/'))==item['DOI']
            body=json.dumps(dict(status='ok',message=item)).encode();content_type='application/json'
        elif path=='/works':
            notice={'DOI':'10.5555/retraction-notice','update-to':[{'DOI':item['DOI'],'type':'retraction','updated':{'date-parts':[[2026,11,12]]}}]}
            body=json.dumps(dict(status='ok',message={'items':[notice],'total-results':1})).encode();content_type='application/json'
        elif path.endswith('/rss.xml'):
            body=(b'<rss version="2.0"><channel><title>Synthetic Opinions</title>'+(
                b'<item><title>Synthetic source description</title><link>https://liia.lv/en/opinions/synthetic-66</link><guid>issue66</guid><pubDate>Tue, 03 Nov 2026 12:00:00 +0000</pubDate><description>Public original description.</description></item>' if self.phase==0 else b'')+b'</channel></rss>')
            content_type='application/xml'
        elif path=='/en/opinions/synthetic-66':
            body=('<div class="article"><p>'+('Changed public source description.' if self.phase else 'First public source description.')+'</p><script>window.POISONED=true</script></div><p class="author">Ada Example</p>').encode()
            content_type='text/html'
            if self.phase==2:status=404
        else:
            status=404;body=b'unknown fixture path';content_type='text/plain'
        self.send_response(status);self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass


class RoutedSocket:
    def __init__(self,sock):self.sock=sock
    def __getattr__(self,key):return getattr(self.sock,key)
    def getpeername(self):return ('93.184.216.34',443)


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    out=Path(tempfile.mkdtemp(prefix='database-upstream66-browser-'))
    data=out/'data';app=create_app(data,testing=True,embedded_worker=False)
    server=make_server('127.0.0.1',0,app,threaded=True)
    source=ThreadingHTTPServer(('127.0.0.1',0),Source)
    for target in (server.serve_forever,source.serve_forever):threading.Thread(target=target,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}'
    clock=['2026-11-04T12:00:00+00:00']
    original_dns,original_connect,original_wrap=socket.getaddrinfo,socket.create_connection,ssl.SSLContext.wrap_socket
    def dns(host,*args,**kwargs):
        return [(2,1,6,'',('93.184.216.34',443))] if host in {'api.crossref.org','liia.lv','www.liia.lv'} else original_dns(host,*args,**kwargs)
    def connect(address,*args,**kwargs):
        if address[0]=='93.184.216.34':return RoutedSocket(original_connect(('127.0.0.1',source.server_port),*args,**kwargs))
        return original_connect(address,*args,**kwargs)
    def wrap(context,sock,*args,**kwargs):
        return sock if isinstance(sock,RoutedSocket) else original_wrap(context,sock,*args,**kwargs)
    results=[];errors=[]
    def endpoint(context,path,body=None,method='post'):
        csrf=context.request.get(base+'/api/session').json()['csrf']
        response=getattr(context.request,method)(base+path,data=body or {},headers={'X-CSRF-Token':csrf})
        assert response.ok,(path,response.status,response.text())
        return response.json()
    def login(page,name):
        page.goto(base+'/#system');page.get_by_role('button',name=name,exact=True).click()
        expect(page.locator('#content')).not_to_be_empty()
    try:
        with patch('socket.getaddrinfo',side_effect=dns),patch('socket.create_connection',side_effect=connect),patch('ssl.SSLContext.wrap_socket',wrap),patch('platform_app.store.now',side_effect=lambda:clock[0]),patch('platform_app.record_revisions.now',side_effect=lambda:clock[0]):
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None)
                context=browser.new_context(viewport={'width':1366,'height':900});page=context.new_page()
                page.on('pageerror',lambda e:errors.append(str(e)))
                login(page,'资料管理员')
                sid=endpoint(context,'/api/sources',dict(name='Baltic Journal of Economics',kind='journal',website='https://www.sseriga.edu/centres/biceps/bje',issn='1406-099X; 2334-4385'))['id']
                liia=endpoint(context,'/api/sources',dict(name='Synthetic LIIA',kind='think_tank',website='https://liia.lv/en/'))['id']
                page.goto(base+'/#maintenance-ingestion')
                for source_id in (sid,liia):
                    form=page.locator('[data-form="ingestion-config"][data-id="'+source_id+'"]')
                    form.locator('[name="enabled"]').check()
                    form.get_by_role('button',name='保存此来源设置',exact=True).click()
                    expect(form.locator('[data-ingestion-draft]')).to_contain_text('设置已保存')
                # Stop after durable feed acquisition; no entry has been saved.
                Source.interrupt=True
                assert run_pending(data,limit=1,source_ids=[sid],stopping=Source.stop.is_set)['saved']==0
                before=context.request.get(base+'/api/sources/'+sid+'/ingestion').json()
                assert before['runs'][0]['stage']=='entries' and before['runs'][0]['status']=='queued',before
                archive=out/'interrupted.zip'
                backup=context.request.post(base+'/api/backup',data={},headers={'X-CSRF-Token':context.request.get(base+'/api/session').json()['csrf']})
                assert backup.ok,(backup.status,backup.text())
                archive.write_bytes(backup.body())
                context.close();server.shutdown();server.server_close()
                data=out/'restored';restore_backup(archive,data)
                app=create_app(data,testing=True,embedded_worker=False)
                server=make_server('127.0.0.1',0,app,threaded=True)
                threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
                Source.interrupt=False;Source.stop.clear()
                assert run_pending(data,limit=2,source_ids=[sid,liia])['saved']==2
                assert sum('/journals/' in r['path'] for r in Source.requests)==1,Source.requests
                context=browser.new_context(viewport={'width':1366,'height':900});page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                login(page,'资料管理员')
                records=context.request.get(base+'/api/records').json()['items']
                bje=next(r['id'] for r in records if r['serial_id']==sid)
                original=next(r['id'] for r in records if r['source_id']==liia)
                current=context.request.get(base+'/api/records/'+bje).json()
                endpoint(context,'/api/records/'+bje,dict(version=current['version'],title='Human corrected title',chinese_title='人工校订题名'),method='put')
                note=endpoint(context,'/api/records',dict(kind='research_note',title='Fixed adopted quotation',evidence_record_id=bje,quote='Original adopted quotation',locator='metadata title'))['id']
                report=endpoint(context,'/api/records',dict(kind='research_report',title='Fixed report',evidence_ids=[note],body_html='<p>Fixed authored report.</p>'))['id']
                adopted=context.request.get(base+'/api/records/'+report).json()['evidence_citations'][0]['snapshot']
                Source.phase=1;clock[0]='2026-11-12T12:00:00+00:00'
                for source_id in (sid,liia):endpoint(context,'/api/sources/'+source_id+'/ingestion/run')
                update=run_pending(data,limit=2,source_ids=[sid,liia]);assert update['saved']==2,update
                bje_detail=context.request.get(base+'/api/records/'+bje).json()
                assert bje_detail['title']=='Human corrected title' and bje_detail['chinese_title']=='人工校订题名'
                assert len(bje_detail['automatic_acquisition']['snapshots'])==2
                assert context.request.get(base+'/api/records/'+report).json()['evidence_citations'][0]['snapshot']==adopted
                assert len(context.request.get(base+'/api/records/'+original).json()['automatic_acquisition']['snapshots'])==2
                page.goto(base+'/#maintenance-ingestion')
                expect(page.locator('[data-upstream-exceptions]')).to_contain_text('上游登记撤回')
                page.screenshot(path=str(out/'exceptions-1366.png'),full_page=True)
                page.locator('[data-upstream-exceptions] article').filter(has_text='上游登记撤回').get_by_role('button',name='已核看此项',exact=True).click()
                expect(page.locator('[data-upstream-exceptions]')).not_to_contain_text('上游登记撤回')
                assert context.request.get(base+'/api/records/'+bje).json()['automatic_acquisition']['upstream']['notices']
                endpoint(context,'/api/logout');page.reload();login(page,'研究员')
                page.goto(base+'/#library?q=Human%20corrected%20title')
                page.locator('.library-row .record-title button').first.click()
                expect(page.locator('[data-upstream-warning]')).to_contain_text('上游登记撤回')
                expect(page.locator('[data-reading-title]')).to_contain_text('人工校订题名')
                feedback=page.locator('.maintenance-feedback');feedback.locator('summary').first.click()
                feedback.locator('textarea').fill('Synthetic feedback: please check the registered upstream notice.')
                feedback.get_by_role('button',name='提交问题',exact=True).click()
                expect(feedback.locator('[data-feedback-status]')).to_contain_text('等待处理')
                assert context.request.get(base+'/api/records/'+bje).json()['title']=='Human corrected title'
                assert not page.evaluate('!!window.POISONED')
                for width in (1366,390):
                    page.set_viewport_size({'width':width,'height':900})
                    page.locator('[data-upstream-warning]').scroll_into_view_if_needed()
                    expect(page.locator('[data-upstream-warning]')).to_be_visible()
                    layout=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
                    assert layout['scroll']<=layout['width']+1,layout
                    page.screenshot(path=str(out/f'retraction-{width}.png'),full_page=False)
                    results.append(dict(width=width,layout=layout))
                # A source disappearing does not remove its old content or
                # advance that source's successful acquisition watermark.
                endpoint(context,'/api/logout');page.reload();login(page,'资料管理员')
                previous=context.request.get(base+'/api/sources/'+liia+'/ingestion').json()
                Source.phase=2;clock[0]='2026-11-20T12:00:00+00:00'
                endpoint(context,'/api/sources/'+liia+'/ingestion/run')
                failure=run_pending(data,limit=1,source_ids=[liia]);assert failure['failed']==1,failure
                after=context.request.get(base+'/api/sources/'+liia+'/ingestion').json()
                assert after['last_success']==previous['last_success'] and after['cursor']==previous['cursor']
                failed=context.request.get(base+'/api/records/'+original).json()
                assert failed['automatic_acquisition']['upstream']['status']=='removed'
                assert len(failed['automatic_acquisition']['snapshots'])==2
                assert context.request.get(base+'/api/admin/ai').json()['attempts']==[]
                page.set_viewport_size({'width':1366,'height':900})
                page.goto(base+'/#library?q=Synthetic%20source%20description')
                page.locator('.library-row .record-title button').first.click()
                expect(page.locator('[data-upstream-warning]')).to_contain_text('上游入口失效待复核')
                page.locator('[data-upstream-warning]').scroll_into_view_if_needed()
                page.screenshot(path=str(out/'unavailable-1366.png'))
                # Resume the same failed entry after the source comes back.
                Source.phase=1
                endpoint(context,'/api/ingestion/runs/'+after['runs'][0]['id']+'/retry')
                assert run_pending(data,limit=1,source_ids=[liia])['saved']==1
                recovered=context.request.get(base+'/api/records/'+original).json()
                assert recovered['automatic_acquisition']['upstream']['status']=='available'
                assert len(recovered['automatic_acquisition']['snapshots'])==2
                extension=out/'zoom-extension';extension.mkdir()
                (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Synthetic upstream zoom check','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}),encoding='utf-8')
                (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});',encoding='utf-8')
                zoom=p.chromium.launch_persistent_context(str(out/'zoom-profile'),headless=False,
                    executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None,
                    ignore_default_args=['--disable-extensions'],args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}'],
                    viewport={'width':1366,'height':900})
                try:
                    zoom_page=zoom.pages[0];login(zoom_page,'研究员')
                    zoom_page.goto(base+'/#library?q=Human%20corrected%20title')
                    zoom_page.locator('.library-row .record-title button').first.click()
                    worker=zoom.service_workers[0] if zoom.service_workers else zoom.wait_for_event('serviceworker')
                    worker.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,2);}',base)
                    actual=worker.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));return chrome.tabs.getZoom(t.id);}',base)
                    assert actual==2,actual
                    zoom_page.locator('[data-upstream-warning]').scroll_into_view_if_needed()
                    expect(zoom_page.locator('[data-upstream-warning]')).to_be_visible()
                    layout=zoom_page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})');assert layout['scroll']<=layout['width']+1,layout
                    zoom_page.screenshot(path=str(out/'retraction-native-200.png'))
                    results.append(dict(width=1366,native_zoom=actual,layout=layout))
                finally:zoom.close()
                assert errors==[],errors
                context.close();browser.close()
    finally:
        server.shutdown();server.server_close();source.shutdown();source.server_close()
    (out/'results.json').write_text(json.dumps(dict(results=results,requests=Source.requests,errors=errors,paid_calls=0,
        new_directory_restored=True,interrupted_run=before['runs'][0]['id']),indent=2),encoding='utf-8')
    print(out)


if __name__=='__main__':main()
