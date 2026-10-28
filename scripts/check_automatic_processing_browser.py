"""Isolated actual browser, independent synthetic source/provider HTTP, export and recovery."""
import io
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler
from platform_app import store
from platform_app.web import create_app
from platform_app.ingestion import run_pending as ingest
from platform_app.automatic_processing import run_pending
from platform_app.maintenance import restore_backup
from tests.synthetic_ai import ENV
from tests.test_discovery import FEED
from scripts.check_ingestion_browser import RoutedSocket

BODY='Latvia studies energy security.'
PAGE='<div class="article"><p>Public description, not an original abstract or work body.</p></div>'
OUT=Path(tempfile.mkdtemp(prefix='ai63-full-browser-'))

class Source(BaseHTTPRequestHandler):
    def do_GET(self):
        raw=FEED.encode() if self.path.endswith('/rss.xml') else PAGE.encode()
        self.send_response(200);self.send_header('Content-Type','application/xml' if self.path.endswith('/rss.xml') else 'text/html');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def log_message(self,*args):pass

class Provider(BaseHTTPRequestHandler):
    mode='truncated'
    requests=[]
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        type(self).requests.append(payload)
        instruction=payload['messages'][0]['content'];value=json.loads(payload['messages'][1]['content'])
        if 'Classify' in instruction:
            output={'countries':[{'value':'拉脱维亚','field':'body','quote':BODY,'certainty':'supported'}] if value.get('body') else [],'topics':[],'type':None}
        elif 'Summarize' in instruction:
            output={'summary':'有据机器概述：拉脱维亚能源安全。','citations':[{'quote':BODY,'start':0,'end':31}]}
        else: output={'title':'合成中文能源题名 '+value['title'],'abstract':'实际原摘要的中文译文' if value['abstract'] else ''}
        raw=json.dumps({'model':'deepseek-flash','usage':{'prompt_tokens':23,'completion_tokens':7,'total_tokens':30},'choices':[{'finish_reason':'length' if self.mode=='truncated' else 'stop','message':{'content':json.dumps(output)}}]}).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def log_message(self,*args):pass

class Quiet(WSGIRequestHandler):
    def log(self,*args,**kwargs):pass

def login(app,name):
    client=app.test_client();csrf=client.get('/api/session').json['csrf']
    assert client.post('/api/login',json={'username':name,'password':'LocalDemo2026!'},headers={'X-CSRF-Token':csrf}).status_code==200
    return client

def call(client,path,data):
    return client.post(path,json=data,headers={'X-CSRF-Token':client.get('/api/session').json['csrf']})

def wait_state(client,predicate):
    for unused in range(150):
        value=client.get('/api/admin/ai').json
        if predicate(value):return value
        time.sleep(.1)
    raise AssertionError(value)

def main():
    app=create_app(OUT/'data',testing=True)
    admin=login(app,'admin');reader=login(app,'researcher')
    source=ThreadingHTTPServer(('127.0.0.1',0),Source)
    provider=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
    for target in (source.serve_forever,provider.serve_forever,server.serve_forever):threading.Thread(target=target,daemon=True).start()
    dns0,connect0,wrap0=socket.getaddrinfo,socket.create_connection,ssl.SSLContext.wrap_socket
    def dns(host,*a,**k):return [(2,1,6,'',('93.184.216.34',443))] if host in {'liia.lv','www.liia.lv'} else dns0(host,*a,**k)
    def connect(address,*a,**k):return RoutedSocket(connect0(('127.0.0.1',source.server_port),*a,**k)) if address[0]=='93.184.216.34' else connect0(address,*a,**k)
    def wrap(context,sock,*a,**k):return sock if isinstance(sock,RoutedSocket) or k.get('server_hostname')=='127.0.0.1' else wrap0(context,sock,*a,**k)
    started=time.monotonic()
    def stamp():return (datetime.fromisoformat('2026-10-27T12:00:00+00:00')+timedelta(seconds=(time.monotonic()-started)*120)).isoformat(timespec='seconds')
    env={**ENV,'DEEPSEEK_API_KEY':'synthetic-only','DEEPSEEK_BASE_URL':f'https://127.0.0.1:{provider.server_port}'}
    stop=threading.Event();results={}
    def worker():
        while not stop.wait(.12):run_pending(OUT/'data',limit=5)
    try:
        with patch.dict(os.environ,env),patch('socket.getaddrinfo',side_effect=dns),patch('socket.create_connection',side_effect=connect),patch('ssl.SSLContext.wrap_socket',wrap),patch('platform_app.store.now',side_effect=stamp),patch('platform_app.ai_gateway.now',side_effect=stamp):
            sid=call(admin,'/api/sources',{'name':'Synthetic public source','kind':'think_tank','website':'https://liia.lv/en/'}).json['id']
            assert admin.put('/api/sources/'+sid+'/ingestion',json={'enabled':True},headers={'X-CSRF-Token':admin.get('/api/session').json['csrf']}).status_code==200
            acquired=ingest(OUT/'data');assert acquired['saved']==2,acquired
            # A separate synthetic future adapter fixture supplies actual text, not LIIA description.
            db=store.connect(OUT/'data'/'platform.sqlite3')
            with db:
                row=db.execute('SELECT * FROM records ORDER BY id LIMIT 1').fetchone();rid=row['id'];raw=json.loads(row['raw_json'])
                raw['automatic_acquisition']['snapshots'][-1].update(content_kind='work_body',work_body_available=True,work_body_basis='synthetic adapter exact work text',work_body={'html':'<p>'+BODY+'</p>','text':BODY})
                db.execute('UPDATE records SET raw_json=? WHERE id=?',(json.dumps(raw),rid))
            db.close()
            thread=threading.Thread(target=worker,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            with sync_playwright() as play:
                browser=play.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None)
                context=browser.new_context(viewport={'width':1366,'height':900});page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base+'/#system');page.get_by_role('button',name='资料管理员',exact=True).click()
                expect(page.get_by_role('heading',name='AI 费用',exact=True)).to_be_visible()
                form=page.locator('[data-form=ai-config]');form.locator('[name=cap]').fill('0.000001');form.locator('[name=currency]').fill('USD');form.get_by_role('button',name='保存月额度').click()
                wait_state(admin,lambda s:s['task_counts'].get('paused')==5)
                assert len(Provider.requests)==0
                page.get_by_role('button',name='刷新费用',exact=True).click();expect(page.locator('#ai-budget-heading')).to_be_focused();page.locator('.ai-budget-card').screenshot(path=str(OUT/'budget-paused-1366.png'))
                form=page.locator('[data-form=ai-config]');form.locator('[name=cap]').fill('1');form.get_by_role('button',name='保存月额度').click()
                failed=wait_state(admin,lambda s:s['task_counts'].get('failed')==5)
                assert len(Provider.requests)==15
                page.get_by_role('button',name='刷新费用',exact=True).click();expect(page.locator('#ai-budget-heading')).to_be_focused();page.locator('[data-ai-tasks]').screenshot(path=str(OUT/'truncated-exceptions-1366.png'))
                Provider.mode='ok'
                for job in failed['tasks']:
                    form=page.locator('[data-form=ai-task-retry][data-id="'+job['id']+'"]')
                    form.locator('xpath=..').locator('>summary').click()
                    form.locator('[name=basis]').fill('独立合成供应商已修复截断，批准新一轮受控调用')
                    form.get_by_role('button',name='批准受控重试',exact=True).click()
                    expect(page.locator('[data-form=ai-task-retry][data-id="'+job['id']+'"]')).to_have_count(0)
                complete=wait_state(admin,lambda s:s['task_counts'].get('succeeded')==5)
                assert len(Provider.requests)==20
                assert len([e for e in complete['events'] if e['action']=='retry_grant'])==5
                page.get_by_role('button',name='刷新费用',exact=True).click();expect(page.locator('#ai-budget-heading')).to_be_focused();page.locator('.ai-budget-card').screenshot(path=str(OUT/'recovered-1366.png'))
                assert errors==[]
                context.close()
                for width,zoom in [(1366,1),(390,1),(1366,2)]:
                    context=browser.new_context(viewport={'width':width,'height':900});page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(base);page.get_by_role('button',name='研究员',exact=True).click()
                    page.locator('[data-reading-filters] [name=q]').fill('合成中文能源');page.get_by_role('button',name='查找',exact=True).click()
                    expect(page.locator('.library-row')).to_have_count(2)
                    page.locator('[data-action=detail][data-id="'+rid+'"]').first.click()
                    expect(page.locator('.automatic-processing')).to_contain_text('有据机器概述：拉脱维亚能源安全。')
                    expect(page.locator('.automatic-processing')).to_contain_text('非原始摘要')
                    assert page.locator('.automatic-processing').evaluate('(e)=>e.getBoundingClientRect().top') < page.locator('.acquisition-reading').evaluate('(e)=>e.getBoundingClientRect().top')
                    if zoom==2:page.evaluate("document.documentElement.style.zoom='2'")
                    page.locator('.automatic-processing').scroll_into_view_if_needed()
                    overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    page.screenshot(path=str(OUT/f'reader-{width}-{zoom}x.png'),full_page=True)
                    assert not overflow,(width,zoom)
                    assert errors==[],errors
                    results[f'{width}-{zoom}x']={'horizontal_overflow':overflow,'page_errors':errors.copy(),'chinese_search':2,'summary_exact_original':True}
                    context.close()
                browser.close()
            export=reader.get('/api/export/content');assert export.status_code==200
            (OUT/'content.zip').write_bytes(export.data)
            subprocess.run([sys.executable,'scripts/verify_content_export.py',str(OUT/'content.zip')],check=True)
            with zipfile.ZipFile(io.BytesIO(export.data)) as archive:
                rows=json.loads(archive.read('content.json'))['records'];record=next(r for r in rows if r['id']==rid)
                assert record['machine_summary']['summary']=='有据机器概述：拉脱维亚能源安全。'
                assert record['machine_summary_basis']['body']==BODY
                assert record['abstract']=='' and record['display_abstract']==''
                assert b'Bearer' not in archive.read('content.json') and b'ai_policy' not in archive.read('content.json')
            stop.set();thread.join(5)
            backup=call(admin,'/api/backup',{});assert backup.status_code==200
            (OUT/'backup.zip').write_bytes(backup.data)
            restored=restore_backup(OUT/'backup.zip',OUT/'restored')
            recovered=create_app(restored,testing=True);recovered_reader=login(recovered,'researcher');recovered_admin=login(recovered,'admin')
            again=recovered_reader.get('/api/records/'+rid).json
            assert again['machine_summary']==record['machine_summary'] and again['machine_summary_basis']==record['machine_summary_basis']
            before=len(Provider.requests);run_pending(restored,limit=10);assert len(Provider.requests)==before
            assert len(recovered_admin.get('/api/admin/ai').json['attempts'])==20
            results.update(provider_requests=len(Provider.requests),paid_calls=0,restored_without_repeat=True,content_export_verified=True,body_fixture='synthetic adapter only; LIIA remains description-only')
    finally:
        stop.set()
        if 'thread' in locals():thread.join(5)
        for instance in [server,source,provider]:instance.shutdown();instance.server_close()
        (OUT/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Evidence:',OUT,flush=True)

if __name__=='__main__':main()
