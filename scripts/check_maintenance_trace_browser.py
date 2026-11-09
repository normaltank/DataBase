"""Real Chrome acceptance of the maintenance trace; isolated synthetic library."""
import json
import logging
import os
from pathlib import Path
import sys
import threading
import shutil
import base64
import argparse
from live_flow_browser_policy import install as strict_policy, verify as verify_policy,verify_workers

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from tests.test_maintenance_agent import MaintenanceAgentTests
from platform_app import store


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence',type=Path,default=Path('tests/artifacts/live-flow-maintenance'))
    parser.add_argument('--baseline-flow',action='store_true')
    args=parser.parse_args()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    evidence=args.evidence.resolve()
    evidence.mkdir(parents=True,exist_ok=True)
    fixture=MaintenanceAgentTests();fixture.setUp()
    jid=fixture.queue('trace-browser')
    fixture.call('/api/admin/maintenance/run',user='admin')
    db=store.connect(fixture.data_dir/'platform.sqlite3')
    with db:
        row=db.execute("SELECT id,result_json FROM maintenance_steps WHERE job_id=? AND name='save_record'",(jid,)).fetchone()
        change=json.loads(row['result_json'])
        change['changes']['abstract']={'before':'SYNTHETIC ORIGINAL LINE\n'*80+'<img src=x onerror=window.flowXss=1>', 'after':'SYNTHETIC UPDATED LINE\n'*80+'<img src=x onerror=window.flowXss=2>'}
        db.execute('UPDATE maintenance_steps SET result_json=? WHERE id=?',(json.dumps(change),row['id']))
        template=dict(db.execute('SELECT * FROM maintenance_jobs WHERE id=?',(jid,)).fetchone())
        for key,status,reason in [('queued','queued',''),('pending','running','正在等待下一项工具执行。'),('empty','completed','已查证，现有内容保持。'),('paused','paused','费用未知，等待核实；本任务尚未完成。')]:
            row={**template,'id':'synthetic-'+key,'request_id':key,'status':status,'reason':reason,'created_at':'2026-10-01T00:00:00+00:00','messages_json':'[]','turns':0}
            db.execute(f"INSERT INTO maintenance_jobs ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",list(row.values()))
        for pos,name,status,result in [(1,'fetch','completed',{'error':'合成网页读取失败，未取得正文。'}),(2,'save_record','pending',{})]:
            db.execute('INSERT INTO maintenance_steps VALUES(?,?,?,?,?,?,?,?,?,?,?)',(f'pending-step-{pos}','synthetic-pending',pos,'call-'+str(pos),name,'{}',status,json.dumps(result),'{}',store.now(),''))
        db.execute("UPDATE maintenance_evidence SET text=text||? WHERE job_id=?",('\n合成原文保留：'+('Evidence for scrolling.\n'*160),jid))
    db.close()
    server=make_server('127.0.0.1',0,fixture.app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    errors=[];checks=[];captures=[]
    try:
        with sync_playwright() as p:
            extension=evidence/'zoom-extension';extension.mkdir(exist_ok=True)
            (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Synthetic trace zoom','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
            (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
            browser=p.chromium.launch_persistent_context(str(evidence/'chromium-profile'),executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE',p.chromium.executable_path),headless=False,
                ignore_default_args=['--disable-extensions'],args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}'],viewport={'width':1366,'height':900},record_video_dir=str(evidence/'video'),record_video_size={'width':1366,'height':900})
            try:
                page=browser.pages[0]
                strict_policy(page,args.baseline_flow)
                workers=[]
                page.on('worker',lambda worker:workers.append(worker.url))
                cdp=browser.new_cdp_session(page)
                def capture(name):
                    # Raw browser pixels, no crop, rescale or CSS zoom.
                    shot=cdp.send('Page.captureScreenshot',{'format':'png','fromSurface':True,'captureBeyondViewport':False})
                    (evidence/name).write_bytes(base64.b64decode(shot['data']))
                    captures.append({'file':name,'method':'CDP Page.captureScreenshot fromSurface=true captureBeyondViewport=false','metrics':page.evaluate('({innerWidth,innerHeight,dpr:devicePixelRatio,scrollY})'),'zoom':zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));return chrome.tabs.getZoom(t.id);}',base)})
                zoom=browser.service_workers[0] if browser.service_workers else browser.wait_for_event('serviceworker')
                page.on('pageerror',lambda e:errors.append(str(e)))
                reads=[];conditional_status=[]
                page.on('request',lambda req:reads.append(req.url) if '/api/maintenance/jobs' in req.url and req.method=='GET' else None)
                page.on('response',lambda response:conditional_status.append(response.status) if '/api/maintenance/jobs' in response.url and response.request.method=='GET' else None)
                page.goto(base+'/#system')
                page.get_by_role('button',name='资料管理员',exact=True).click()
                page.goto(base+'/#maintenance-agent')
                expect(page.locator('[data-maintenance-select]')).to_have_count(5)
                page.locator(f'[data-maintenance-select="{jid}"]').click()
                expect(page.locator('[data-trace-step]')).to_have_count(14)
                page.locator('[data-trace-step]').filter(has_text='整理文章').click()
                expect(page.locator('.react-flow__node')).to_have_count(16)
                page.get_by_role('button',name='显示全图',exact=True).click()
                page.locator('.react-flow__node').filter(has_text='整理文章').click()
                expect(page.locator('[data-trace-step][aria-pressed=true]')).to_contain_text('整理文章')
                page.get_by_text('逐行阅读文本差异',exact=True).click()
                expect(page.locator('[data-trace-diff] .d2h-wrapper')).to_have_count(1)
                expect(page.locator('[data-trace-diff]')).to_contain_text('<img src=x onerror=window.flowXss=2>')
                assert page.locator('[data-trace-diff] img').count()==0
                assert page.evaluate('window.flowXss===undefined')
                assert any('/static/vendor/visual/elk-worker.min.js' in url for url in workers),workers
                checks.append('actual React Flow + same-origin ELK Worker + escaped diff2html long text')
                expect(page.locator('[data-trace-detail]')).to_contain_text('原值')
                expect(page.locator('[data-trace-detail]')).to_contain_text('old label')
                expect(page.locator('[data-trace-detail]')).to_contain_text('Baltic cooperation')
                expect(page.locator('[data-trace-detail]')).to_contain_text('实际取得的材料')
                checks.append('real step → explicit evidence → before/after')
                # Native evidence open state, actual scroll, focus, draft and DOM
                # identity survive two real five-second polling intervals.
                disclosure=page.locator('[data-evidence-id]').first
                disclosure.locator('summary').click()
                evidence_text=disclosure.locator('.trace-evidence-text')
                evidence_text.evaluate('(e)=>{e.scrollTop=180;window.traceEvidence=e;window.traceDetail=document.querySelector("[data-trace-detail]");window.traceSelected=document.querySelector("[data-trace-step][aria-pressed=true]");}')
                page.locator('.maintenance-single>summary').click()
                query=page.get_by_label('查找文章',exact=True);query.fill('未提交的查找输入');query.focus()
                viewport_before=page.locator('.react-flow__viewport').get_attribute('style')
                before_reads=len(reads);page.wait_for_timeout(10800)
                assert len(reads)>=before_reads+4,reads
                assert 304 in conditional_status,conditional_status
                assert page.locator('.react-flow__viewport').get_attribute('style')==viewport_before
                expect(page.locator('[data-flow-status]')).to_contain_text('流程图可点选')
                assert page.evaluate('traceEvidence===document.querySelector(".trace-evidence-text")&&traceDetail===document.querySelector("[data-trace-detail]")&&traceSelected===document.querySelector("[data-trace-step][aria-pressed=true]")')
                assert evidence_text.evaluate('(e)=>e.scrollTop')==180
                assert disclosure.get_attribute('open') is not None
                expect(query).to_be_focused();expect(query).to_have_value('未提交的查找输入')
                checks.append('two real polls preserve DOM/open/scroll/focus/input/step')
                db=store.connect(fixture.data_dir/'platform.sqlite3')
                with db:db.execute('INSERT INTO maintenance_steps VALUES(?,?,15,?,?,?,?,?,?,?,?)',('new-observation',jid,'new-call','read','{}','completed','{}','{}',store.now(),store.now()))
                db.close()
                page.get_by_role('button',name='刷新状态',exact=True).click()
                expect(page.locator('[data-trace-step]')).to_have_count(15)
                expect(page.locator('[data-flow-status]')).to_contain_text('流程图可点选',timeout=12000)
                assert page.evaluate('traceSelected===document.querySelector("[data-trace-step][aria-pressed=true]")')
                checks.append('new step does not steal selection')
                # A focused task row may move as a newly recent task arrives.
                # Reconciliation must retain keyboard focus and list scroll.
                focused_row=page.locator('[data-maintenance-select="synthetic-paused"]')
                focused_row.focus()
                db=store.connect(fixture.data_dir/'platform.sqlite3')
                with db:db.execute("UPDATE maintenance_jobs SET created_at=? WHERE id='synthetic-paused'",(store.now(),))
                db.close()
                page.wait_for_timeout(5400)
                expect(focused_row).to_be_focused()
                checks.append('focused task row survives keyed reorder during automatic refresh')
                page.locator('.maintenance-single>summary').click()
                page.locator('#maintenance-agent-heading').scroll_into_view_if_needed()
                page.locator('[data-trace-detail]').evaluate('(e)=>e.scrollTop=0')
                page.wait_for_timeout(220)
                page.screenshot(path=str(evidence/'maintenance-1366.png'),full_page=True)
                page.evaluate('window.scrollTo(0,0)');page.wait_for_timeout(150);capture('maintenance-desktop-raw.png')
                # Reverse evidence lookup uses its persisted originating step.
                page.locator('.trace-material-index>summary').click()
                page.locator('[data-trace-evidence]').nth(1).click()
                expect(page.locator('[data-trace-step][aria-pressed=true]')).to_contain_text('读取公开网页')
                expect(page.locator('[data-evidence-id][open]')).to_have_count(1)
                checks.append('evidence index selects the persisted originating step')
                # Zero, waiting/error and completed without changes are distinct.
                page.locator('[data-maintenance-select="synthetic-queued"]').click()
                expect(page.locator('[data-trace-detail]')).to_contain_text('尚无执行步骤')
                page.locator('[data-maintenance-select="synthetic-pending"]').click()
                expect(page.locator('[data-trace-detail]')).to_contain_text('合成网页读取失败')
                page.locator('[data-trace-step]').nth(1).click()
                expect(page.locator('[data-trace-detail]')).to_contain_text('等待执行，尚无执行结果')
                page.locator('[data-maintenance-select="synthetic-empty"]').click()
                expect(page.locator('[data-trace-summary]')).to_contain_text('已查证，现有内容保持')
                page.locator('[data-maintenance-select="synthetic-paused"]').click()
                expect(page.locator('[data-trace-summary]')).to_contain_text('费用未知')
                checks.append('queued zero / pending / error / no-change complete / unknown cost')
                page.locator(f'[data-maintenance-select="{jid}"]').click()
                expect(page.locator('[data-trace-step]')).to_have_count(15)
                # Failed reads keep authorized content; explicit denial clears it.
                page.route('**/api/maintenance/jobs?view=summary',lambda route:route.fulfill(status=503,content_type='application/json',body=json.dumps({'error':'合成断网'})))
                page.get_by_role('button',name='刷新状态',exact=True).click()
                expect(page.locator('[data-maintenance-error]')).to_contain_text('合成断网')
                expect(page.locator('[data-trace-step]')).to_have_count(15)
                page.unroute('**/api/maintenance/jobs?view=summary')
                page.get_by_role('button',name='刷新状态',exact=True).click()
                expect(page.locator('[data-maintenance-error]')).to_be_empty()
                page.route('**/api/maintenance/jobs/'+jid,lambda route:route.fulfill(status=404,content_type='application/json',body=json.dumps({'error':'合成材料失权'})))
                page.get_by_role('button',name='刷新状态',exact=True).click()
                expect(page.locator('[data-maintenance-detail]')).to_contain_text('已清除详情')
                expect(page.locator('[data-trace-step]')).to_have_count(0)
                page.unroute('**/api/maintenance/jobs/'+jid)
                page.get_by_role('button',name='刷新状态',exact=True).click()
                expect(page.locator('[data-trace-step]')).to_have_count(15)
                checks.append('offline retains content / recovery / explicit 404 clears cache')
                def outside_window(route):
                    headers={key:value for key,value in route.request.headers.items() if key.lower()!='if-none-match'}
                    data=route.fetch(headers=headers).json();data['items']=[item for item in data['items'] if item['id']!=jid];data['window']['loaded']=len(data['items']);data['window']['has_more']=True
                    route.fulfill(json=data)
                page.route('**/api/maintenance/jobs?view=summary',outside_window)
                page.get_by_role('button',name='刷新状态',exact=True).click()
                expect(page.locator('[data-maintenance-selection-note]')).to_contain_text('暂不在近期窗口')
                expect(page.locator('[data-trace-step]')).to_have_count(15)
                page.unroute('**/api/maintenance/jobs?view=summary')
                checks.append('outside authorized window keeps reauthenticated selected detail')
                # Keep a real detail response pending, select a newer task, then
                # release the older response. It must never overwrite selection.
                page.locator('[data-maintenance-select="synthetic-pending"]').click()
                expect(page.locator('[data-trace-step]')).to_have_count(2)
                held=[]
                page.route('**/api/maintenance/jobs/'+jid,lambda route:held.append(route))
                page.locator(f'[data-maintenance-select="{jid}"]').click()
                for _ in range(20):
                    if held:break
                    page.wait_for_timeout(50)
                assert held
                page.locator('[data-maintenance-select="synthetic-queued"]').click()
                expect(page.locator('[data-trace-detail]')).to_contain_text('尚无执行步骤')
                held.pop().fulfill(status=200,json=fixture.clients['researcher'].get('/api/maintenance/jobs/'+jid).json)
                page.unroute('**/api/maintenance/jobs/'+jid)
                expect(page.locator('[data-maintenance-select="synthetic-queued"]')).to_have_attribute('aria-pressed','true')
                expect(page.locator('[data-trace-step]')).to_have_count(0)
                page.locator(f'[data-maintenance-select="{jid}"]').click()
                expect(page.locator('[data-trace-step]')).to_have_count(15)
                # A real server-side target revocation wins over cached detail.
                db=store.connect(fixture.data_dir/'platform.sqlite3')
                with db:db.execute("UPDATE records SET visibility='restricted' WHERE id=?",(fixture.rid,))
                db.close()
                page.get_by_role('button',name='刷新状态',exact=True).click()
                expect(page.locator('[data-maintenance-detail]')).to_contain_text('已清除详情')
                db=store.connect(fixture.data_dir/'platform.sqlite3')
                with db:db.execute("UPDATE records SET visibility='shared' WHERE id=?",(fixture.rid,))
                db.close()
                page.get_by_role('button',name='刷新状态',exact=True).click()
                expect(page.locator('[data-trace-step]')).to_have_count(15)
                checks.append('held late detail cannot overwrite rapid selection / actual server revocation clears')
                for width,height,factor in [(1366,900,1),(390,844,1),(320,780,1),(1366,900,2)]:
                    page.set_viewport_size({'width':width,'height':height})
                    zoom.evaluate('async ({url,factor})=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));await chrome.tabs.setZoom(t.id,factor);}',{'url':base,'factor':factor})
                    actual=zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));return chrome.tabs.getZoom(t.id);}',base)
                    assert actual==factor
                    page.locator('[data-trace-step]').filter(has_text='整理文章').focus();page.keyboard.press('Enter')
                    expect(page.locator('[data-trace-detail]')).to_contain_text('原值')
                    expect(page.locator('[data-flow-status]')).to_contain_text('流程图可点选',timeout=12000)
                    verify_workers(page)
                    page.get_by_role('button',name='定位所选节点',exact=True).click()
                    page.locator('.actual-flow').scroll_into_view_if_needed();page.wait_for_timeout(100)
                    capture(f'maintenance-flow-{width}-{factor}-raw.png')
                    page.locator('[data-trace-detail]').scroll_into_view_if_needed();page.wait_for_timeout(220)
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+2'),(width,factor)
                    assert not page.locator('.trace-connector').evaluate_all('(els)=>els.some(e=>e.outerHTML.includes("NaN")||e.outerHTML.includes("Infinity"))')
                    if width<=390 or factor==2:
                        assert page.locator('.maintenance-agent button:visible,.maintenance-agent summary:visible').evaluate_all('(els)=>els.every(e=>e.getBoundingClientRect().height>=44)')
                    page.screenshot(path=str(evidence/f'maintenance-{width}-{factor}.png'),full_page=True)
                    capture(f'maintenance-{width}-{factor}-raw.png')
                checks.append('1366 / 390 / 320 / native 200% keyboard, 44px, finite SVG, no overflow')
                zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));await chrome.tabs.setZoom(t.id,1);}',base)
                page.set_viewport_size({'width':1366,'height':900});page.emulate_media(reduced_motion='reduce')
                page.evaluate('Element.prototype.animate=undefined')
                page.locator('[data-trace-step]').filter(has_text='关联作者').click()
                expect(page.locator('[data-trace-detail]')).to_contain_text('作者归属')
                checks.append('reduced-motion and animation API unavailable remain operable')
                # Same component in a researcher's object feedback history.
                page.goto(base+'/#library?q=Baltic')
                page.get_by_role('button',name='退出登录',exact=True).click()
                page.get_by_role('button',name='研究员',exact=True).click()
                page.get_by_role('button',name='Baltic cooperation',exact=True).first.click()
                panel=page.locator('.maintenance-feedback').last
                panel.locator(':scope>summary').click();panel.locator('.feedback-history>summary').click()
                feedback_job=panel.locator('[data-key="feedback-job-'+jid+'"]')
                feedback_job.locator(':scope>summary').click()
                expect(feedback_job.locator('[data-trace-step]')).to_have_count(15)
                feedback_job.locator('[data-trace-step]').filter(has_text='整理文章').click()
                expect(feedback_job.locator('[data-trace-detail]')).to_contain_text('old label')
                assert not panel.get_by_role('link',name='配置、暂停与费用').count()
                feedback=panel.get_by_label('问题说明');feedback.fill('合成未提交的问题说明')
                feedback_job.locator('[data-evidence-id]>summary').first.click()
                panel.get_by_role('button',name='刷新结果',exact=True).click()
                expect(feedback).to_have_value('合成未提交的问题说明')
                expect(feedback_job.locator('[data-evidence-id][open]')).to_have_count(1)
                expect(feedback_job.locator('[data-trace-step][aria-pressed=true]')).to_contain_text('整理文章')
                feedback_job.locator('[data-trace-detail]').scroll_into_view_if_needed()
                page.screenshot(path=str(evidence/'feedback-1366.png'),full_page=True)
                capture('feedback-desktop-raw.png')
                checks.append('researcher feedback reuses trace and preserves draft/step/evidence')
                # Lost POST response retries the same durable request; a failed
                # post-submit history read still reports successful submission.
                submitted=[]
                page.on('request',lambda req:submitted.append(req.post_data_json) if req.method=='POST' and req.url.endswith('/api/maintenance/jobs') else None)
                def lost_post(route):
                    response=route.fetch();assert response.status==201
                    route.fulfill(status=503,json={'error':'合成提交响应丢失'})
                page.route('**/api/maintenance/jobs',lost_post)
                panel.get_by_role('button',name='提交问题',exact=True).click()
                expect(panel.locator('form .form-error')).to_contain_text('合成提交响应丢失')
                expect(feedback).to_have_value('合成未提交的问题说明')
                page.unroute('**/api/maintenance/jobs')
                history_url='**/api/maintenance/targets/record/'+fixture.rid
                page.route(history_url,lambda route:route.fulfill(status=503,json={'error':'合成结果读取失败'}))
                panel.get_by_role('button',name='提交问题',exact=True).click()
                expect(feedback).to_have_value('')
                expect(panel.locator('form .form-error')).to_contain_text('问题已提交')
                assert submitted[-1]['request_id']==submitted[-2]['request_id']
                page.unroute(history_url)
                panel.get_by_role('button',name='刷新结果',exact=True).click()
                expect(panel.locator('.feedback-job')).to_have_count(6)
                checks.append('feedback lost POST retry idempotent / saved submission survives failed result read')
                for width in [390,320]:
                    page.set_viewport_size({'width':width,'height':844})
                    feedback_job.locator('[data-trace-step]').filter(has_text='整理文章').focus();page.keyboard.press('Enter')
                    feedback_job.locator('[data-trace-detail]').scroll_into_view_if_needed()
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+2')
                    assert panel.locator('button:visible,summary:visible').evaluate_all('(els)=>els.every(e=>e.getBoundingClientRect().height>=44)')
                    page.screenshot(path=str(evidence/f'feedback-{width}.png'),full_page=True)
                    capture(f'feedback-{width}-raw.png')
                page.set_viewport_size({'width':1366,'height':900})
                zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));await chrome.tabs.setZoom(t.id,2);}',base)
                assert zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));return chrome.tabs.getZoom(t.id);}',base)==2
                feedback_job.locator('[data-trace-step]').filter(has_text='整理文章').focus();page.keyboard.press('Enter')
                feedback_job.locator('[data-trace-detail]').scroll_into_view_if_needed()
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+2')
                page.screenshot(path=str(evidence/'feedback-200.png'),full_page=True)
                capture('feedback-200-raw.png')
                checks.append('researcher feedback 390 / 320 / native 200% equivalent actions')
                zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));await chrome.tabs.setZoom(t.id,1);}',base)
                # Leave while a history read is pending, change the account,
                # then release it. Old identity data never reappears.
                held_history=[]
                page.route(history_url,lambda route:held_history.append(route))
                panel.get_by_role('button',name='刷新结果',exact=True).click()
                for _ in range(20):
                    if held_history:break
                    page.wait_for_timeout(50)
                assert held_history
                page.get_by_role('button',name='退出登录',exact=True).click()
                held_history.pop().fulfill(status=200,json=fixture.clients['researcher'].get('/api/maintenance/targets/record/'+fixture.rid).json)
                page.unroute(history_url)
                expect(page.locator('[data-maintenance-trace]')).to_have_count(0)
                page.get_by_role('button',name='协作同事',exact=True).click()
                expect(page.locator('[data-maintenance-trace]')).to_have_count(0)
                checks.append('late history after leaving/account switch cannot restore old identity cache')
                policy_violations=verify_policy(page)
                if errors:raise AssertionError(errors)
            finally:browser.close()
        (evidence/'result.json').write_text(json.dumps({'checks':checks,'captures':captures,'page_errors':errors,'synthetic':True,'conditional_status':conditional_status,'policy_violations':policy_violations},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'evidence':str(evidence),'checks':checks},ensure_ascii=False))
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        preview=evidence/'preview-data'
        if preview.exists():
            # Fixed QA target, only replace this script's own earlier synthetic copy.
            if preview.resolve().parent!=evidence.resolve():raise AssertionError('Invalid preview path')
            shutil.rmtree(preview)
        shutil.copytree(fixture.data_dir,preview)
        fixture.doCleanups()


if __name__=='__main__':main()
