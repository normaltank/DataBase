"""Fresh signed-out pages and logout refresh remain usable with no saved position."""
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ['TEMP'])/'database-continuity-login-browser'
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
        browser=pw.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE',r'C:\Users\27451\AppData\Local\ms-playwright\chromium-1187\chrome-win\chrome.exe'))
        context=browser.new_context(viewport={'width':1366,'height':900})
        page=context.new_page();page.set_default_timeout(5000)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(URL)
        expect(page.locator('#username')).to_be_visible()
        expect(page.locator('#password')).to_be_visible()
        page.screenshot(path=str(OUT/'fresh-signed-out.png'))
        results['fresh_signed_out']=True
        page.locator('[data-action=demo-login][data-id=researcher]').click()
        expect(page.get_by_role('heading',name='查找研究资料',exact=True)).to_be_visible()
        page.goto(URL+'/#library')
        page.get_by_role('button',name='卡片视图',exact=True).click()
        page.get_by_role('button',name='退出登录',exact=True).click()
        expect(page.locator('#username')).to_be_visible()
        page.reload()
        expect(page.locator('#username')).to_be_visible()
        expect(page.locator('#password')).to_be_visible()
        page.screenshot(path=str(OUT/'logout-refreshed.png'))
        results['logout_refresh']=True
        page.locator('[data-action=demo-login][data-id=colleague]').click()
        expect(page.locator('.library-workspace')).to_be_visible()
        results['login_after_refresh']=True
        results['page_errors']=errors
        assert not errors,errors
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

