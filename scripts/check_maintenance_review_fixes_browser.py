"""Review regressions at public HTTP and real Chrome; synthetic provider only."""
import argparse
import base64
import copy
import json
import logging
from pathlib import Path
import subprocess
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from platform_app import store
from tests.test_maintenance_agent import MaintenanceAgentTests


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('D:/Agent Workspace/DataBase-audits/visual-research-134/repair-round1/green'))
    args=parser.parse_args();out=args.output;out.mkdir(parents=True,exist_ok=True)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    fixture=MaintenanceAgentTests();fixture.setUp()
    jid=fixture.queue('review-fixes-browser')
    fixture.call('/api/admin/maintenance/run',user='admin')
    db=store.connect(fixture.data_dir/'platform.sqlite3')
    original=db.execute("SELECT * FROM maintenance_steps WHERE job_id=? AND name='set_bylines'",(jid,)).fetchone()
    payload=json.loads(original['result_json']);relation=payload['changes']['bylines']['after']
    db.close()
    server=make_server('127.0.0.1',0,fixture.app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    result={'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'synthetic':True,'base':base,'checks':[],'captures':[]}
    errors=[]

    def save_changes(changes):
        value=copy.deepcopy(payload);value['changes']=changes
        db=store.connect(fixture.data_dir/'platform.sqlite3')
        with db:db.execute('UPDATE maintenance_steps SET result_json=? WHERE id=?',(json.dumps(value),original['id']))
        db.close()

    def qualification(visibility):
        db=store.connect(fixture.data_dir/'platform.sqlite3')
        with db:db.execute('UPDATE records SET visibility=? WHERE id=?',(visibility,fixture.rid))
        db.close()

    try:
        with sync_playwright() as p:
            extension=out/'zoom-extension';extension.mkdir(exist_ok=True)
            (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Synthetic review zoom','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
            (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
            contexts=[]
            for role in ['admin','reader']:
                contexts.append(p.chromium.launch_persistent_context(str(out/(role+'-chromium-profile')),headless=False,
                    ignore_default_args=['--disable-extensions'],args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}']))
            browser,reader_browser=contexts
            try:
                admin=browser.new_page();reader=reader_browser.new_page()
                for page in [admin,reader]:page.set_viewport_size({'width':1366,'height':900})
                zooms={page:(context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')) for page,context in [(admin,browser),(reader,reader_browser)]}
                for page in [admin,reader]:page.on('pageerror',lambda error:errors.append(str(error)))
                admin.goto(base+'/#system');admin.get_by_role('button',name='资料管理员',exact=True).click()
                admin.goto(base+'/#maintenance-agent')
                admin.locator(f'[data-maintenance-select="{jid}"]').click()
                reader.goto(base+'/#library?q=Baltic');reader.get_by_role('button',name='研究员',exact=True).click()
                reader.get_by_role('button',name='Baltic cooperation',exact=True).first.click()
                panel=reader.locator('.maintenance-feedback').last
                panel.locator(':scope>summary').click();panel.locator('.feedback-history>summary').click()

                def reader_job():
                    job=panel.locator(f'[data-key="feedback-job-{jid}"]')
                    if job.get_attribute('open') is None:job.locator(':scope>summary').click()
                    job.locator('[data-trace-step]').filter(has_text='关联作者').click()
                    return job

                # Each pair differs only in the named business field. Existing
                # identities stay fixed; these are durable synthetic changes.
                basis_before=copy.deepcopy(relation);basis_after=copy.deepcopy(relation)
                basis_before['items'][0]['evidence']='SYNTHETIC old relationship basis'
                basis_after['items'][0]['evidence']='SYNTHETIC corrected relationship basis'
                cases=[('bylines',basis_before,basis_after,'SYNTHETIC old relationship basis','SYNTHETIC corrected relationship basis')]
                status_before=copy.deepcopy(relation);status_after=copy.deepcopy(relation)
                status_before['items'][0]['status']='pending';status_after['items'][0]['status']='confirmed'
                cases.append(('bylines',status_before,status_after,'待核对','已确认'))
                # Explicit persisted references, with the same institution/name.
                cases.append(('affiliations',{'items':[{'id':'synthetic-affiliation','byline_id':'synthetic-byline-A','institution_id':'synthetic-institution','evidence':'unchanged basis'}]}, {'items':[{'id':'synthetic-affiliation','byline_id':'synthetic-byline-B','institution_id':'synthetic-institution','evidence':'unchanged basis'}]},'synthetic-byline-A','synthetic-byline-B'))
                cases.append(('employments',{'items':[{'id':'synthetic-employment','role':'讲师','evidence':'旧任职依据','start_date':'2020','human_checked':False}]},{'items':[{'id':'synthetic-employment','role':'讲师','evidence':'新任职依据','start_date':'2020','human_checked':False}]},'旧任职依据','新任职依据'))
                cases.append(('employments',{'items':[{'id':'synthetic-employment','role':'讲师','evidence':'unchanged','start_date':'2020','human_checked':False}]},{'items':[{'id':'synthetic-employment','role':'教授','evidence':'unchanged','start_date':'2024','human_checked':True}]},'讲师','教授'))
                cases.append(('relationships',[{'type':'part_of','evidence':'旧机构关系依据'}],[{'type':'cooperates_with','evidence':'新机构关系依据'}],'旧机构关系依据','新机构关系依据'))
                for field,before,after,old,new in cases:
                    save_changes({field:{'before':before,'after':after}})
                    actual=reader.request.get(base+'/api/maintenance/jobs/'+jid).json()
                    actual_change=next(s for s in actual['steps'] if s['id']==original['id'])['result']['changes'][field]
                    assert actual_change=={'before':before,'after':after}
                    admin.get_by_role('button',name='刷新状态',exact=True).click()
                    admin.locator('[data-trace-step]').filter(has_text='关联作者').click()
                    panel.get_by_role('button',name='刷新结果',exact=True).click()
                    job=reader_job()
                    for root in [admin.locator('[data-trace-detail]'),job.locator('[data-trace-detail]')]:
                        expect(root.locator('.trace-diff>div').first).to_contain_text(old)
                        expect(root.locator('.trace-diff>div').last).to_contain_text(new)
                        if field=='employments' and new=='教授':
                            expect(root.locator('.trace-diff>div').first).to_contain_text('2020')
                            expect(root.locator('.trace-diff>div').last).to_contain_text('2024')
                            expect(root.locator('.trace-diff>div').first).to_contain_text('否')
                            expect(root.locator('.trace-diff>div').last).to_contain_text('是')
                    result['checks'].append('both consumers show literal before/after: '+field+' '+old+' → '+new)

                # Incidental revisions alone must not manufacture a change.
                before=copy.deepcopy(relation);after=copy.deepcopy(relation)
                after['version']+=1;after['record_version']+=1
                after['items'][0]['version']+=1;after['items'][0]['updated_at']='2099-01-01'
                save_changes({'bylines':{'before':before,'after':after}})
                panel.get_by_role('button',name='刷新结果',exact=True).click()
                expect(reader_job().locator('[data-trace-detail]')).to_contain_text('此步没有记录字段或关系改动。')
                result['checks'].append('revision-only changes remain absent')

                save_changes({'bylines':{'before':basis_before,'after':basis_after}})
                panel.get_by_role('button',name='刷新结果',exact=True).click();job=reader_job()
                textarea=panel.locator('textarea');textarea.fill('SYNTHETIC unsent feedback remains')
                old_jobs=panel.locator('.feedback-job').count()
                old_steps=job.locator('[data-trace-step]').count()
                # Network and arbitrary 400 remain recoverable failures, not ACL.
                history='**/api/maintenance/targets/record/*'
                for mode in ['network','400']:
                    def fail(route):
                        if mode=='network':route.abort('failed')
                        else:route.fulfill(status=400,content_type='application/json',body='{"error":"SYNTHETIC ordinary validation"}')
                    reader.route(history,fail)
                    panel.get_by_role('button',name='刷新结果',exact=True).click()
                    expect(panel.locator('.form-error').first).not_to_be_empty()
                    assert panel.locator('.feedback-job').count()==old_jobs
                    assert job.locator('[data-trace-step]').count()==old_steps
                    expect(textarea).to_have_value('SYNTHETIC unsent feedback remains')
                    reader.unroute(history,fail)
                result['checks'].append('network and arbitrary400 preserve history, selected details and draft')
                qualification('restricted')
                assert reader.request.get(base+'/api/records/'+fixture.rid).status==200
                with reader.expect_response(lambda r:'/api/maintenance/targets/record/' in r.url) as response:
                    panel.get_by_role('button',name='刷新结果',exact=True).click()
                assert response.value.status==404
                assert reader.request.get(base+'/api/maintenance/jobs/'+jid).status==404
                expect(panel.locator('.feedback-job')).to_have_count(0)
                expect(panel.locator('[data-trace-step]')).to_have_count(0)
                expect(panel.locator('[data-trace-detail]')).to_have_count(0)
                expect(panel.locator('[data-feedback-brief]')).to_have_text('')
                expect(textarea).to_have_value('SYNTHETIC unsent feedback remains')
                qualification('shared')
                panel.get_by_role('button',name='刷新结果',exact=True).click();job=reader_job()
                expect(job.locator('[data-trace-detail]')).to_contain_text('SYNTHETIC corrected relationship basis')
                expect(textarea).to_have_value('SYNTHETIC unsent feedback remains')
                result['checks'].append('eligibility404 clears all history/detail; restored eligibility rereads, draft survives')

                admin.get_by_role('button',name='刷新状态',exact=True).click()
                admin.locator('[data-trace-step]').filter(has_text='关联作者').click()
                for width in [1366,390,320]:
                    for name,page in [('maintenance',admin),('feedback',reader)]:
                        page.set_viewport_size({'width':width,'height':900})
                        expect(page.locator('.trace-diff').first).to_be_visible()
                        page.evaluate('scrollTo(0,0)')
                        if name=='feedback':
                            reader_root=page.locator('.library-reader:not([hidden])')
                            reader_root.evaluate('e=>e.scrollTop=0')
                        file=f'{name}-{width}-viewport.png';page.screenshot(path=str(out/file))
                        result['captures'].append({'file':file,'width':width,'method':'Playwright viewport screenshot','metrics':page.evaluate('({innerWidth,innerHeight,scrollY})')})
                        if name=='feedback':
                            for _ in range(6):
                                sizes=reader_root.evaluate('e=>({scroll:e.scrollHeight,client:e.clientHeight})')
                                if sizes['scroll']<=sizes['client']+2:break
                                height=page.viewport_size['height']+sizes['scroll']-sizes['client']+32
                                assert height<16000,height
                                page.set_viewport_size({'width':width,'height':height})
                            reader_root.evaluate('e=>e.scrollTop=0')
                            assert reader_root.evaluate('e=>e.scrollHeight<=e.clientHeight+2')
                        page.evaluate('scrollTo(0,0)')
                        file=f'{name}-{width}-fullpage.png';page.screenshot(path=str(out/file),full_page=True)
                        result['captures'].append({'file':file,'width':width,'method':'full_page; all native scroll roots at top, feedback real viewport height expanded, no CSS/image edits','metrics':page.evaluate('({innerWidth,innerHeight,scrollY})')})
                for name,page in [('maintenance',admin),('feedback',reader)]:
                    zoom=zooms[page]
                    page.set_viewport_size({'width':1366,'height':900})
                    zoom.evaluate('async url=>{const tab=(await chrome.tabs.query({})).find(t=>t.url===url);await chrome.tabs.setZoom(tab.id,2);}',page.url)
                    actual_zoom=zoom.evaluate('async url=>{const tab=(await chrome.tabs.query({})).find(t=>t.url===url);return chrome.tabs.getZoom(tab.id);}',page.url)
                    assert actual_zoom==2
                    page.locator('[data-trace-step]').filter(has_text='关联作者').click()
                    detail=page.locator('[data-trace-detail]');expect(detail).to_contain_text('SYNTHETIC corrected relationship basis')
                    cdp=page.context.new_cdp_session(page)
                    shot=cdp.send('Page.captureScreenshot',{'format':'png','fromSurface':True,'captureBeyondViewport':False})
                    file=f'{name}-native200-raw.png';(out/file).write_bytes(base64.b64decode(shot['data']))
                    result['captures'].append({'file':file,'zoom':actual_zoom,'method':'CDP raw viewport native tabs.setZoom2','metrics':page.evaluate('({innerWidth,innerHeight,scrollY})')})
                    for side,label in [(0,'before'),(1,'after')]:
                        basis=detail.locator('.trace-diff>div').nth(side).locator('[data-key="field-evidence"]')
                        basis.evaluate('e=>e.scrollIntoView({block:"center"})')
                        shot=cdp.send('Page.captureScreenshot',{'format':'png','fromSurface':True,'captureBeyondViewport':False})
                        file=f'{name}-native200-{label}-raw.png';(out/file).write_bytes(base64.b64decode(shot['data']))
                        result['captures'].append({'file':file,'zoom':actual_zoom,'method':'CDP raw viewport, '+label+' basis scrolled to center; native tabs.setZoom2','metrics':page.evaluate('({innerWidth,innerHeight,scrollY})')})
                    zoom.evaluate('async url=>{const tab=(await chrome.tabs.query({})).find(t=>t.url===url);await chrome.tabs.setZoom(tab.id,1);}',page.url)
                assert not errors,errors
                result['browser_errors']=errors
            finally:
                for context in contexts:context.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        fixture.doCleanups()
        result['cleanup']='Own browser/server closed; isolated fixture cleaned; no real provider.'
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
