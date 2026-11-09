"""Real Chrome, synthetic HTTP+worker and native tool provider; no paid traffic."""
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from tests.test_maintenance_agent import MaintenanceAgentTests


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    evidence=Path(tempfile.mkdtemp(prefix='browser-',dir='D:/Agent Workspace/DataBase-tests/maintenance129'))
    fixture=MaintenanceAgentTests();fixture.setUp()
    server=make_server('127.0.0.1',0,fixture.app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    extension=evidence/'zoom-extension';extension.mkdir()
    (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Synthetic maintenance zoom','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
    (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
    errors=[];results=[]
    try:
        with sync_playwright() as p:
            executable=os.environ.get('DATABASE_BROWSER_EXECUTABLE','C:/Program Files/Google/Chrome/Application/chrome.exe')
            context=p.chromium.launch_persistent_context(str(evidence/'profile'),executable_path=executable,headless=False,
                ignore_default_args=['--disable-extensions'],args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}'],viewport={'width':1366,'height':900})
            try:
                zoom=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                page=context.pages[0];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base+'/#system')
                page.get_by_role('button',name='资料管理员',exact=True).click()
                page.goto(base+'/#maintenance-agent')
                expect(page.get_by_role('heading',name='整理一篇文章')).to_be_visible()
                page.get_by_label('查找文章',exact=True).fill('Baltic cooperation')
                page.get_by_role('button',name='查找',exact=True).click()
                page.get_by_label('选择文章',exact=True).select_option(fixture.rid)
                page.get_by_role('button',name='开始整理',exact=True).click()
                expect(page.locator('[data-maintenance-message]')).to_contain_text('已安排')
                fixture.call('/api/admin/maintenance/run',user='admin')
                page.get_by_role('button',name='刷新状态',exact=True).click()
                expect(page.locator('.maintenance-job>summary')).to_contain_text('已完成')
                if page.locator('.maintenance-job').get_attribute('open') is None:page.locator('.maintenance-job>summary').click()
                # Structured results and real final network appear in the live UI.
                expect(page.locator('.maintenance-steps')).to_contain_text('关联作者')
                for width,height,factor in [(1366,900,1),(390,844,1),(320,780,1),(1366,900,2)]:
                    page.set_viewport_size({'width':width,'height':height})
                    zoom.evaluate('async ({url,factor})=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));await chrome.tabs.setZoom(t.id,factor);}',{'url':base,'factor':factor})
                    actual=zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));return chrome.tabs.getZoom(t.id);}',base)
                    if actual!=factor:raise AssertionError('Real browser zoom mismatch')
                    page.locator('#maintenance-agent-heading').scroll_into_view_if_needed()
                    page.wait_for_timeout(150)
                    overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth+2')
                    if overflow:raise AssertionError(f'Horizontal overflow {width}/{factor}')
                    controls=page.locator('.maintenance-agent button:visible').evaluate_all('(els)=>els.map(e=>({text:e.textContent,height:e.getBoundingClientRect().height}))')
                    if width<=390 and any(x['height']<44 for x in controls):raise AssertionError(controls)
                    shot=evidence/f'maintenance-{width}-{factor}.png';page.screenshot(path=str(shot))
                    results.append({'width':width,'zoom':actual,'overflow':overflow,'screenshot':str(shot)})
                zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));await chrome.tabs.setZoom(t.id,1);}',base)
                page.set_viewport_size({'width':1366,'height':900})
                page.get_by_role('button',name='打开资料与档案',exact=True).click()
                badge=page.get_by_text('AI 关联',exact=True)
                expect(badge).to_be_attached()
                for disclosure in page.locator('details').filter(has=badge).all():
                    if disclosure.get_attribute('open') is None:disclosure.locator(':scope > summary').click()
                expect(badge).to_be_visible()
                pid=fixture.clients['researcher'].get('/api/records/'+fixture.rid+'/bylines').json['items'][0]['target_id']
                page.goto(base+'/#people?id='+pid)
                expect(page.get_by_text('Alex Vale',exact=True).first).to_be_visible()
                expect(page.get_by_role('link',name='0000-0002-1825-0097',exact=True)).to_be_visible()
                expect(page.get_by_text('Baltic cooperation',exact=False).first).to_be_visible()
                if errors:raise AssertionError(errors)
            finally:context.close()
        (evidence/'result.json').write_text(json.dumps({'results':results,'page_errors':errors,'provider':'synthetic native tools, no paid requests'},indent=2))
        print(json.dumps({'evidence':str(evidence),'results':results,'page_errors':errors}))
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5);fixture.doCleanups()


if __name__=='__main__':main()
