"""Delayed topic restoration must not open old material after navigating away."""
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ['TEMP'])/'database-continuity-race-browser'
OUT.mkdir(exist_ok=True)
URL='http://127.0.0.1:8854'
results={}
server=None
try:
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1',8854)) != 0, 'Test port is occupied'
    log=(OUT/'server.log').open('w',encoding='utf-8')
    server=subprocess.Popen([r'C:\Python312\python.exe',str(ROOT/'app.py'),'--no-import','--port','8854','--data-dir',str(OUT/('data-'+str(time.time_ns())))],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    with sync_playwright() as pw:
        api=pw.request.new_context(base_url=URL)
        for _ in range(100):
            try:
                if api.get('/health',timeout=500).ok:break
            except Exception:time.sleep(.1)
        def post(path,data):
            token=api.get('/api/session').json()['csrf']
            response=api.post(path,data=data,headers={'X-CSRF-Token':token})
            assert response.ok,(path,response.text())
            return response.json()
        post('/api/login',dict(username='researcher',password='LocalDemo2026!'))
        old=post('/api/records',dict(title='Old restoration material',kind='report'))['id']
        current=post('/api/records',dict(title='Current working material',kind='report'))['id']
        topic=post('/api/collections',dict(name='Race topic',visibility='shared'))['id']
        post('/api/collections/'+topic+'/items',dict(record_id=old))
        browser=pw.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE',r'C:\Users\27451\AppData\Local\ms-playwright\chromium-1187\chrome-win\chrome.exe'))
        context=browser.new_context(storage_state=api.storage_state(),viewport={'width':1366,'height':900})
        page=context.new_page();page.set_default_timeout(5000)
        pending=[]
        def hold(request):pending.append(request)
        def prepare_restore():
            page.goto(URL+'/#collections')
            page.locator('[data-action="open-collection"][data-id="'+topic+'"]').click()
            page.locator('.topic-record [data-action=detail]').click()
            expect(page.locator('#modal-root .detail-title')).to_have_text('Old restoration material')
            page.goto(URL+'/#library?q=Current')
            expect(page.locator('.library-workspace')).to_contain_text('Current working material')
            page.route('**/api/collections/'+topic,hold)
            page.go_back()
            page.wait_for_timeout(200)
            assert pending
        prepare_restore()
        page.goto(URL+'/#library?q=Current')
        expect(page.locator('.library-workspace')).to_contain_text('Current working material')
        page.locator('[data-library-record="'+current+'"] [data-action=detail]').first.click()
        expect(page.locator('.library-reader .detail-title')).to_have_text('Current working material')
        page.goto(URL+'/#sources');expect(page.locator('#content')).to_contain_text('来源目录')
        page.go_back();expect(page.locator('.library-reader .detail-title')).to_have_text('Current working material')
        pending.pop().continue_();page.wait_for_timeout(500)
        expect(page.locator('#modal-root .overlay')).to_have_count(0)
        page.reload()
        expect(page.locator('.library-reader .detail-title')).to_have_text('Current working material')
        page.screenshot(path=str(OUT/'changed-route.png'))
        results['changed_route_and_new_position']=True
        page.unroute('**/api/collections/'+topic,hold)
        prepare_restore()
        page.get_by_role('button',name='退出登录',exact=True).click()
        expect(page.locator('[data-form=login]')).to_have_count(1)
        page.locator('[data-action=demo-login][data-id=colleague]').click()
        expect(page.locator('#content')).to_contain_text('专题资料夹')
        page.goto(URL+'/#library?q=Current')
        expect(page.locator('.library-workspace')).to_contain_text('Current working material')
        pending.pop().continue_();page.wait_for_timeout(500)
        expect(page.locator('#modal-root .overlay')).to_have_count(0)
        expect(page.locator('.library-workspace')).to_contain_text('Current working material')
        page.locator('[data-library-record="'+current+'"] [data-action=detail]').first.click()
        expect(page.locator('.library-reader .detail-title')).to_have_text('Current working material')
        page.reload()
        expect(page.locator('.library-reader .detail-title')).to_have_text('Current working material')
        page.screenshot(path=str(OUT/'changed-account.png'))
        results['changed_account_and_new_position']=True
        results['passed']=True
        browser.close();api.dispose()
except Exception as error:
    results['error']=str(error)
    raise
finally:
    if server:
        server.terminate();server.wait(timeout=5)
    (OUT/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(OUT)
