"""Chrome detail feedback, failure drafts and native zoom; synthetic resources only."""
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
from tests.test_maintenance_feedback import MaintenanceFeedbackTests
from platform_app.maintenance_agent import run_pending


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    root=Path('D:/Agent Workspace/DataBase-tests/maintenance131');root.mkdir(parents=True,exist_ok=True)
    os.environ['DATABASE_TEST_TMP']=str(root)
    evidence=Path(tempfile.mkdtemp(prefix='browser-',dir=root))
    fixture=MaintenanceFeedbackTests();fixture.setUp()
    wrong,correct=fixture.prepare_wrong_identity()
    text='此文作者是研究波罗的海的讲师，不是物理学家；标签和简介也错了。'
    fixture.provider.side_effect=fixture.correction_provider(correct,text)
    sid=fixture.source('Synthetic Baltic Review','journal')
    server=make_server('127.0.0.1',0,fixture.app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    extension=evidence/'zoom-extension';extension.mkdir()
    (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Synthetic feedback zoom','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
    (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
    results=[];errors=[]
    try:
        with sync_playwright() as p:
            context=p.chromium.launch_persistent_context(str(evidence/'profile'),executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE','C:/Program Files/Google/Chrome/Application/chrome.exe'),headless=False,
                ignore_default_args=['--disable-extensions'],args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}'],viewport={'width':1366,'height':900})
            try:
                zoom=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                page=context.pages[0];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base+'/#library?q=Baltic')
                page.get_by_role('button',name='研究员',exact=True).click()
                page.get_by_role('button',name='Baltic cooperation',exact=True).first.click()
                panel=page.locator('.maintenance-feedback').last
                summary=panel.locator(':scope > summary');summary.focus();summary.press('Enter')
                input=panel.get_by_label('问题说明');input.fill(text)
                page.route('**/api/maintenance/jobs',lambda route:route.fulfill(status=503,content_type='application/json',body=json.dumps({'error':'合成提交失败，请重试。'})))
                panel.get_by_role('button',name='提交问题',exact=True).click()
                expect(panel.locator('.form-error')).to_contain_text('合成提交失败')
                expect(input).to_have_value(text)
                page.unroute('**/api/maintenance/jobs')
                panel.get_by_role('button',name='提交问题',exact=True).click()
                expect(panel.locator('[data-feedback-status]')).to_contain_text('等待处理')
                expect(input).to_have_value('')
                run_pending(fixture.data_dir)
                panel.get_by_role('button',name='刷新结果',exact=True).click()
                expect(panel.locator('[data-feedback-status]')).to_contain_text('已完成')
                panel.locator('.feedback-history>summary').click()
                panel.locator('.feedback-job>summary').first.click()
                expect(panel.locator('[data-feedback-history]')).to_contain_text('波罗的海合作')
                for width,height,factor in [(1366,900,1),(390,844,1),(320,780,1),(1366,900,2)]:
                    page.set_viewport_size({'width':width,'height':height})
                    zoom.evaluate('async ({url,factor})=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));await chrome.tabs.setZoom(t.id,factor);}',{'url':base,'factor':factor})
                    actual=zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));return chrome.tabs.getZoom(t.id);}',base)
                    if actual!=factor:raise AssertionError('Native zoom mismatch')
                    summary.scroll_into_view_if_needed();page.wait_for_timeout(150)
                    overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth+2')
                    panel_overflow=panel.evaluate('e=>e.scrollWidth>e.clientWidth+2')
                    if overflow or panel_overflow:raise AssertionError(f'Overflow {width}/{factor}')
                    controls=panel.locator('button:visible,summary:visible').evaluate_all('(els)=>els.map(e=>({text:e.textContent,height:e.getBoundingClientRect().height}))')
                    if (width<=390 or factor==2) and any(c['height']<44 for c in controls):raise AssertionError(controls)
                    shot=evidence/f'feedback-{width}-{factor}.png';page.screenshot(path=str(shot))
                    results.append({'width':width,'zoom':actual,'overflow':False,'screenshot':str(shot)})
                zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));await chrome.tabs.setZoom(t.id,1);}',base)
                page.set_viewport_size({'width':1366,'height':900})
                page.goto(base+'/#people?id='+correct)
                expect(page.locator('.maintenance-feedback>summary')).to_contain_text('指出问题')
                page.locator('.maintenance-feedback>summary').click()
                page.get_by_label('问题说明').fill('人物简介仍需补充。')
                page.get_by_role('button',name='提交问题',exact=True).click()
                expect(page.locator('[data-feedback-status]')).to_contain_text('等待处理')
                page.goto(base+'/#sources?id='+sid)
                expect(page.locator('.maintenance-feedback>summary')).to_contain_text('指出问题')
                page.locator('.maintenance-feedback>summary').click()
                page.get_by_label('问题说明').fill('刊物简介需要纠正。')
                page.get_by_role('button',name='提交问题',exact=True).click()
                expect(page.locator('[data-feedback-status]')).to_contain_text('等待处理')
                page.reload()
                expect(page.locator('.maintenance-feedback>summary')).to_contain_text('等待处理')
                if errors:raise AssertionError(errors)
            finally:context.close()
        (evidence/'result.json').write_text(json.dumps({'results':results,'page_errors':errors,'provider':'synthetic, zero paid requests'},indent=2))
        print(json.dumps({'evidence':str(evidence),'results':results,'page_errors':errors}))
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5);fixture.doCleanups()


if __name__=='__main__':main()
