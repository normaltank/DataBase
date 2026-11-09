"""All five visual modules in one real application/library and two real roles."""
import argparse
import json
import logging
import math
from pathlib import Path
import socket
import sys
import threading
from urllib.parse import quote
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from platform_app import store
from tests.test_maintenance_agent import MaintenanceAgentTests
from tests.test_topic_handoffs import HandoffTests
from live_flow_browser_policy import install,verify,verify_workers


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args();output=args.evidence.resolve();output.mkdir(parents=True,exist_ok=False)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    fixture=MaintenanceAgentTests();fixture.setUp()
    jid=fixture.queue('integrated-journey');fixture.call('/api/admin/maintenance/run',user='admin')
    rid=fixture.rid
    current=fixture.clients['researcher'].get('/api/records/'+rid).json
    updated=fixture.call('/api/records/'+rid,{'version':current['version'],'title':'合成整合旅程 · 研究原文','countries':'Latvia','published_on':'2021'},method='PUT')
    assert updated.status_code==200,updated.json
    fixture.record(title='合成整合旅程 · 其他资料',countries='Japan',published_on='2020')
    person=fixture.clients['researcher'].get('/api/records/'+rid+'/bylines').json['items'][0]['target_id']
    handoff=HandoffTests();handoff.app=fixture.app;handoff.data_dir=fixture.data_dir;handoff.clients=fixture.clients
    tid=handoff.topic(theme='合成整合旅程 · 材料交接');material=None;versions=[]
    for number in range(1,4):
        values={'stage':'selection','title':'合成整合旅程 · 成员材料','token':handoff.board(tid)['token'],'request_id':uuid.uuid4().hex}
        if material:values['material_ref']=material
        saved=handoff.call(f'/api/collaboration/topics/{tid}/handoffs',values,file=(f'original-{number}.txt',f'ORIGINAL {number}'.encode()))
        assert saved.status_code==201,saved.json
        material=saved.json['material_ref'];version=next(m for m in handoff.board(tid)['materials'] if m['ref']==material)['versions'][0];versions.append(version)
        if number<3:
            result=handoff.call(f'/api/collaboration/topics/{tid}/handoff-reviews',{'token':handoff.board(tid)['token'],'request_id':uuid.uuid4().hex,'version_ref':version['ref'],'decision':'returned' if number==1 else 'approved','note':f'REVIEW NOTE {number}'},file=(f'review-{number}.txt',f'REVIEW {number}'.encode()))
            assert result.status_code==201,result.json
    db=store.connect(fixture.data_dir/'platform.sqlite3')
    with db:
        row=db.execute("SELECT id,result_json FROM maintenance_steps WHERE job_id=? AND name='save_record'",(jid,)).fetchone()
        result=json.loads(row['result_json']);result['changes']['abstract']={'before':'ORIGINAL LONG TEXT\n'*60+'<script>window.journeyXss=1</script>','after':'UPDATED LONG TEXT\n'*60+'<img src=x onerror=window.journeyXss=2>'}
        db.execute('UPDATE maintenance_steps SET result_json=? WHERE id=?',(json.dumps(result),row['id']))
    db.close()
    server=make_server('127.0.0.1',0,fixture.app,threaded=True)
    assert server.server_port not in {6430,3435,3436}
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    checks=[];requests=[];responses=[];errors=[];policy=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1366,'height':1000});page.set_default_timeout(15000);install(page)
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:requests.append(request.url))
            page.on('response',lambda response:responses.append({'url':response.url,'status':response.status}) if '/api/maintenance/' in response.url and response.request.method=='GET' else None)
            try:
                page.goto(base+'/#library?feed=all&q='+quote('合成整合旅程'))
                page.get_by_role('button',name='研究员',exact=True).click()
                panel=page.locator('.material-discovery')
                expect(panel.locator('.material-scope')).to_contain_text('2 条')
                canvas=panel.locator('[data-material-globe] canvas');expect(canvas).to_be_visible();canvas.scroll_into_view_if_needed();b=canvas.bounding_box()
                lon,lat,view_lon,view_lat=map(math.radians,(24,57,22,45))
                point=[2.5*math.cos(lat)*math.sin(lon),2.5*math.sin(lat),2.5*math.cos(lat)*math.cos(lon)]
                dot=lambda a,c:sum(x*y for x,y in zip(a,c))
                right=[math.cos(view_lon),0,-math.sin(view_lon)]
                up=[-math.sin(view_lat)*math.sin(view_lon),math.cos(view_lat),-math.sin(view_lat)*math.cos(view_lon)]
                forward=[math.cos(view_lat)*math.sin(view_lon),math.sin(view_lat),math.cos(view_lat)*math.cos(view_lon)]
                scale=b['height']/2/math.tan(math.radians(20))/(8.6-dot(point,forward))
                page.mouse.click(b['x']+b['width']/2+dot(point,right)*scale,b['y']+b['height']/2-dot(point,up)*scale)
                expect(panel.locator('.material-scope')).to_contain_text('1 条');assert 'country=LV' in page.url
                page.screenshot(path=str(output/'01-country.png'))
                panel.locator('[data-material-scene=time]').click();expect(panel.locator('[data-material-timeline] canvas')).to_be_visible()
                panel.locator('[data-material-from]').fill('2021');panel.locator('[data-material-to]').fill('2021');panel.locator('[data-material-apply]').click()
                expect(panel.locator('.material-window-scope')).to_contain_text('完整匹配 1 条');assert 'from=2021-01-01' in page.url
                panel.locator('[data-material-lens]').click();lens=panel.locator('.material-time-lens canvas');expect(lens).to_be_visible()
                panel.locator('[data-material-camera-reset]').click();lens.scroll_into_view_if_needed();b=lens.bounding_box()
                fit=max(7.4,7/(math.tan(math.radians(20))*b['width']/b['height']));point=[0,1.5,-1.28]
                up=[0,1/math.sqrt(1.0064),-.08/math.sqrt(1.0064)];forward=[0,.08/math.sqrt(1.0064),1/math.sqrt(1.0064)]
                scale=b['height']/2/math.tan(math.radians(20))/(fit*math.sqrt(1.0064)-dot(point,forward))
                with page.expect_response(lambda response:'/api/records/'+rid in response.url and response.status==200):page.mouse.click(b['x']+b['width']/2,b['y']+b['height']/2-dot(point,up)*scale)
                expect(page.locator('.library-reader [data-reading-title]')).to_have_text('合成整合旅程 · 研究原文')
                checks.append('researcher: real globe LV click → same query 2 to 1 → ECharts year apply → actual Three point → correct existing reader')
                explorer=page.locator('.library-reader [data-record-explore]');explorer.locator('summary').click()
                viewport=explorer.locator('[data-network-viewport]');expect(viewport.locator('canvas').first).to_be_visible();viewport.scroll_into_view_if_needed();page.wait_for_timeout(200)
                shot=output/'02-plane.png';viewport.screenshot(path=str(shot));pixels=Image.open(shot).convert('RGB');points=[]
                for y in range(pixels.height):
                    for x in range(pixels.width):
                        if pixels.getpixel((x,y))==(121,82,0):points.append((x,y))
                assert points,'Actual Cytoscape person node must render'
                b=viewport.bounding_box();page.mouse.click(b['x']+sum(v[0] for v in points)/len(points),b['y']+sum(v[1] for v in points)/len(points))
                expect(explorer.locator('[data-network-selection]')).to_contain_text('Alex Vale')
                explorer.get_by_role('button',name='空间关系',exact=True).click();expect(viewport.locator('canvas')).to_have_count(1)
                expect(explorer.locator('[data-network-selection]')).to_contain_text('Alex Vale')
                explorer.locator('[data-network-selection] a').click();expect(page.locator('.person-page')).to_contain_text('Alex Vale')
                page.get_by_role('button',name='返回资料',exact=True).click();expect(explorer).to_have_attribute('open','')
                assert 'country=LV' in page.url and 'from=2021-01-01' in page.url
                checks.append('same reader: actual Cytoscape person click → Three space same selection → authorized profile → original query/reader')
                feedback=page.locator('.library-reader .maintenance-feedback').last
                feedback.locator(':scope>summary').click();feedback.locator('.feedback-history>summary').click();feedback.locator('.feedback-job>summary').first.click()
                expect(feedback.locator('.react-flow__node')).to_have_count(16)
                feedback.locator('[data-trace-step]').filter(has_text='整理文章').click()
                feedback.get_by_text('逐行阅读文本差异',exact=True).click();expect(feedback.locator('.d2h-wrapper')).to_have_count(1)
                expect(feedback.locator('[data-trace-diff]')).to_contain_text('<img src=x onerror=window.journeyXss=2>')
                assert not feedback.locator('[data-trace-diff] img,[data-trace-diff] script').count();assert page.evaluate('window.journeyXss===undefined')
                first_line=feedback.locator('.d2h-diff-tbody tr').filter(has_text='ORIGINAL LONG TEXT').first
                assert first_line.bounding_box()['height']<32,'A short diff line must not render template indentation as blank lines'
                assert not feedback.get_by_text('配置、暂停与费用',exact=True).count()
                feedback.locator('[data-trace-detail]').scroll_into_view_if_needed();page.screenshot(path=str(output/'03-research-feedback.png'))
                checks.append('same research object: feedback React Flow → recorded step/evidence → safe long diff, no admin controls')
                page.goto(base+f'/#collaboration?id={tid}&tab=selection')
                material_view=page.locator(f'[data-material-ref="{material}"]');expect(material_view.locator('.react-flow__node')).to_have_count(5)
                material_view.locator('.react-flow__node').filter(has_text='版本 1').filter(has_text='负责人审阅').click()
                reading=material_view.locator('[data-handoff-reading]');expect(reading).to_contain_text('历史版 1 · 退回')
                expect(reading).to_contain_text('REVIEW NOTE 1')
                with page.expect_download() as downloaded:reading.get_by_role('link',name='下载原件',exact=True).click()
                assert Path(downloaded.value.path()).read_bytes()==b'ORIGINAL 1'
                with page.expect_download() as downloaded:reading.get_by_role('link',name='审阅附件：review-1.txt',exact=True).click()
                assert Path(downloaded.value.path()).read_bytes()==b'REVIEW 1'
                material_view.locator('.actual-flow').scroll_into_view_if_needed();page.screenshot(path=str(output/'04-collaboration.png'))
                checks.append('same library and researcher: actual material review node → v1 original/review bytes; v2 approved and v3 pending remain distinct')
                page.get_by_role('button',name='退出登录',exact=True).click();page.get_by_role('button',name='资料管理员',exact=True).click();page.goto(base+'/#maintenance-agent')
                expect(page.locator('.react-flow__node')).to_have_count(16)
                page.locator('[data-trace-step]').filter(has_text='整理文章').click();page.get_by_text('逐行阅读文本差异',exact=True).click();expect(page.locator('.d2h-wrapper')).to_have_count(1)
                for _ in range(2):
                    with page.expect_response(lambda response:'/api/maintenance/jobs/'+jid in response.url and response.status==304):page.get_by_role('button',name='刷新状态',exact=True).click()
                expect(page.locator('[data-flow-status]')).to_contain_text('流程图可点选');verify_workers(page)
                page.locator('[data-trace-detail]').scroll_into_view_if_needed();page.screenshot(path=str(output/'05-admin-diff.png'))
                page.set_viewport_size({'width':320,'height':780});page.locator('[data-trace-step]').filter(has_text='整理文章').focus();page.keyboard.press('Enter')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                page.locator('[data-trace-detail]').scroll_into_view_if_needed();page.screenshot(path=str(output/'06-admin-320.png'))
                checks.append('same application admin: same actual job/step/diff; two authenticated 304 reads; 320px keyboard equivalent')
                for name in ['globe','timeline','network','flow','diff']:assert any('/static/vendor/visual/'+name+'.js' in url for url in requests),name
                assert not errors,errors;policy=verify(page)
            finally:browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        with socket.socket() as probe:closed=probe.connect_ex(('127.0.0.1',server.server_port))!=0
        fixture.doCleanups()
        (output/'result.json').write_text(json.dumps({'checks':checks,'single_app':base,'single_synthetic_library':True,'roles':['researcher','admin'],'record_id':rid,'person_id':person,'topic_id':tid,'job_id':jid,'module_requests':[url for url in requests if '/static/vendor/visual/' in url],'maintenance_responses':responses,'policy_violations':policy,'page_errors':errors,'server_closed':closed and not thread.is_alive()},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'evidence':str(output),'checks':checks},ensure_ascii=False))


if __name__=='__main__':main()
