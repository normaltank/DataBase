"""#142 public HTTP fixtures and isolated browser tasks; no live data or paid work."""
import argparse
import json
import logging
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from email import message_from_bytes

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from platform_app.web import create_app
from tests.test_topic_handoffs import HandoffTests
from tests.test_maintenance_agent import MaintenanceAgentTests
from live_flow_browser_policy import install as strict_policy,verify as verify_policy


CAPTURES=[]

def capture(page,path):
    # Wait for the real feedback to finish; never hide it for a screenshot.
    expect(page.locator('#toast')).to_have_css('opacity','0',timeout=7000)
    page.wait_for_function("[...document.querySelectorAll('[data-flow-status],[data-material-globe-status],[data-material-time-status],[data-network-status]')].every(e=>!e.getClientRects().length||!/^正在(?:加载|读取|排列)/.test(e.textContent))")
    page.screenshot(path=str(path))
    CAPTURES.append({'file':Path(path).name,'viewport':page.viewport_size,
        'position':page.evaluate('({scrollY,readerY:document.querySelector(".library-reader")?.scrollTop||0})'),
        'kind':'entry viewport' if '-entry-' in Path(path).name else 'task viewport after explicit selection or navigation'})


def globe_latvia(page):
    canvas=page.locator('[data-material-globe] canvas');expect(canvas).to_be_visible()
    box=canvas.bounding_box()
    lon,lat,view_lon,view_lat=map(math.radians,(24,57,22,45))
    point=[2.5*math.cos(lat)*math.sin(lon),2.5*math.sin(lat),2.5*math.cos(lat)*math.cos(lon)]
    dot=lambda a,b:sum(x*y for x,y in zip(a,b))
    right=[math.cos(view_lon),0,-math.sin(view_lon)]
    up=[-math.sin(view_lat)*math.sin(view_lon),math.cos(view_lat),-math.sin(view_lat)*math.cos(view_lon)]
    forward=[math.cos(view_lat)*math.sin(view_lon),math.sin(view_lat),math.cos(view_lat)*math.cos(view_lon)]
    scale=box['height']/2/math.tan(math.radians(20))/(8.6-dot(point,forward))
    page.mouse.click(box['x']+box['width']/2+dot(point,right)*scale,box['y']+box['height']/2-dot(point,up)*scale)


def check_fallback(playwright,evidence,base,fixture,tid):
    pending=fixture.upload(tid,who='researcher',title='合成 · 降级材料').json['material_ref']
    browser=playwright.chromium.launch(headless=True,args=['--disable-webgl'])
    try:
        page=browser.new_page(viewport={'width':1366,'height':900},reduced_motion='reduce')
        page.goto(base+'/#library?feed=all&q=合成工作台')
        page.get_by_role('button',name='研究员',exact=True).click()
        expect(page.locator('[data-material-globe-status]')).to_contain_text('地球未加载')
        page.locator('.material-country-list [data-material-country=LV]').click()
        expect(page.locator('.library-row')).to_have_count(6)
        capture(page,evidence/'no-webgl-desktop.png')
        page.route('**/static/vendor/visual/flow.js*',lambda route:route.abort('failed'))
        page.goto(base+f'/#collaboration?id={tid}&tab=selection')
        material=page.locator(f'[data-material-ref="{pending}"]')
        expect(material.locator('[data-flow-status]')).to_contain_text('未能加载')
        expect(material.get_by_role('button',name='查看版本 1',exact=True)).to_be_visible()
        material.locator('[data-form=handoff-review]').get_by_role('button',name='通过此版',exact=True).click()
        expect(material.locator(':scope > .between > .badge')).to_have_text('当前版 1 · 通过')
        material.locator(':scope > .between > h2').evaluate('e=>e.scrollIntoView({block:"start"})')
        capture(page,evidence/'no-module-handoff.png')
    finally:browser.close()


def check_maintenance(playwright,evidence):
    fixture=MaintenanceAgentTests()
    fixture.setUp()  # The fixture intercepts every provider request before running.
    server=None
    try:
        jid=fixture.queue('modern-workbench-browser')
        assert fixture.call('/api/admin/maintenance/run',user='admin').status_code==200
        server=make_server('127.0.0.1',0,fixture.app,threaded=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        browser=playwright.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport={'width':1366,'height':900},reduced_motion='reduce')
            page.goto(f'http://127.0.0.1:{server.server_port}/#maintenance-agent')
            page.get_by_role('button',name='资料管理员',exact=True).click()
            page.locator(f'[data-maintenance-select="{jid}"]').click()
            expect(page.locator('[data-trace-step]')).to_have_count(14)
            page.evaluate('window.scrollTo(0,0)');capture(page,evidence/'maintenance-entry-desktop.png')
            page.get_by_role('button',name='有改动',exact=True).click()
            assert 0<page.locator('[data-trace-step]:visible').count()<14
            page.locator('[data-trace-step]').filter(has_text='关联作者').click()
            detail=page.locator('[data-trace-detail]')
            expect(detail).to_contain_text('Alex Vale')
            assert 'manual_revision' not in detail.inner_text()
            detail.get_by_text('完整关系记录',exact=True).last.click()
            expect(detail).to_contain_text('manual_revision')
            detail.get_by_text('完整关系记录',exact=True).last.click()
            detail.evaluate('e=>e.scrollTop=0')
            page.locator('[data-maintenance-trace]').evaluate('e=>{e.scrollIntoView({block:"start"});window.scrollBy(0,-76)}')
            capture(page,evidence/'maintenance-desktop.png')
            page.set_viewport_size({'width':390,'height':844})
            page.evaluate('window.scrollTo(0,0)');capture(page,evidence/'maintenance-entry-390.png')
            page.get_by_role('button',name='查看修改与依据',exact=True).click()
            assert 56<=detail.bounding_box()['y']<200,detail.bounding_box()
            capture(page,evidence/'maintenance-mobile.png')
            page.set_viewport_size({'width':320,'height':780});page.evaluate('window.scrollTo(0,0)');capture(page,evidence/'maintenance-entry-320.png');page.get_by_role('button',name='查看修改与依据',exact=True).click()
            capture(page,evidence/'maintenance-320.png')
            page.get_by_role('button',name='执行问题',exact=True).click()
            expect(page.locator('[data-trace-step]:visible')).to_have_count(0)
            expect(page.locator('[data-trace-filter-status]')).to_contain_text('当前步骤在筛选外')
        finally:browser.close()
    finally:
        if server:server.shutdown();server.server_close();thread.join(5)
        fixture.doCleanups()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    evidence = Path(args.evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    data = evidence / 'synthetic-data'
    fixture = HandoffTests()
    fixture.app = create_app(data, testing=True, embedded_worker=False)
    fixture.clients = {name: fixture.login(name) for name in ('researcher', 'colleague', 'admin')}
    tid = fixture.topic(theme='合成 · 现代研究工作台')
    first = fixture.upload(tid, who='researcher', title='合成 · 第一份材料').json['material_ref']
    second = fixture.upload(tid, who='researcher', title='合成 · 第二份材料').json['material_ref']
    third = fixture.upload(tid, who='researcher', title='合成 · 并发材料').json['material_ref']
    fourth = fixture.upload(tid, who='researcher', title='合成 · 权限材料').json['material_ref']
    records=[]
    source=fixture.call('/api/sources', {'name':'合成 · 政策研究所','kind':'institution'}).json['id']
    for i in range(12):
        saved=fixture.call('/api/records', {'title':f'合成工作台资料 {i+1:02} · 区域政策与研究证据','kind':'report',
            'source_id':source,'countries':'Latvia' if i%2==0 else 'Estonia','published_on':f'{2020+i%4}-03-15',
            'abstract':'完全合成的摘要。','body_html':'<h2>研究材料</h2>'+('<p>完全合成的界面验证正文，保留来源与实际证据。</p>'*30)})
        assert saved.status_code==201,saved.json
        records.append(saved.json['id'])
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server = make_server('127.0.0.1', 0, fixture.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    errors = []
    result = {'base': base, 'worker_enabled': False, 'paid_calls': 0, 'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=Path(__file__).resolve().parents[1]).strip()}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE', p.chromium.executable_path), headless=True)
            try:
                page = browser.new_page(viewport={'width':1366, 'height':900}, reduced_motion='reduce')
                strict_policy(page)
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base + f'/#collaboration?id={tid}&tab=selection')
                page.get_by_role('button', name='研究员', exact=True).click()
                material = page.locator(f'[data-material-ref="{first}"]')
                other = page.locator(f'[data-material-ref="{second}"]')
                draft = other.locator('[data-form=handoff-review]')
                expect(material).to_be_visible();page.evaluate('window.scrollTo(0,0)');capture(page,evidence/'handoff-entry-desktop.png')
                other.locator('.react-flow__node').get_by_role('button',name='意见/附件',exact=True).press('Space')
                expect(draft.locator('[name=note]')).to_be_focused()
                draft.locator('[name=note]').fill('另一份材料的草稿保留')
                draft.locator('[name=file]').set_input_files({'name':'other.txt','mimeType':'text/plain','buffer':b'OTHER DRAFT'})
                node = material.locator('.react-flow__node').filter(has_text='当前版 1')
                approve = node.get_by_role('button', name='通过', exact=True)
                expect(approve).to_be_visible()
                cdp=page.context.new_cdp_session(page);cdp.send('DOM.enable');cdp.send('CSS.enable')
                document_node=cdp.send('DOM.getDocument')['root']['nodeId']
                text_node=cdp.send('DOM.querySelector',{'nodeId':document_node,'selector':'.react-flow__node span'})['nodeId']
                result['graph_fonts']=cdp.send('CSS.getPlatformFontsForNode',{'nodeId':text_node})['fonts'];cdp.detach()
                approve.scroll_into_view_if_needed()
                capture(page,evidence/'handoff-pending-desktop.png')
                result['approval_action']=approve.bounding_box()
                writes=[]
                page.on('request',lambda request:writes.append(request.url) if request.method=='POST' and request.url.endswith('/handoff-reviews') else None)
                approve.dblclick()
                expect(material.locator(':scope > .between > .badge')).to_have_text('当前版 1 · 通过')
                assert len(writes)==1,writes
                expect(draft.locator('[name=note]')).to_have_value('另一份材料的草稿保留')
                assert draft.locator('[name=file]').evaluate('e=>e.files[0].name') == 'other.txt'
                board = fixture.board(tid)
                saved = next(m for m in board['materials'] if m['ref'] == first)
                assert len(saved['versions'][0]['reviews']) == 1
                assert saved['status'] == 'approved'
                expect(node.get_by_role('button', name='通过', exact=True)).to_have_count(0)
                material.scroll_into_view_if_needed()
                capture(page,evidence/'handoff-desktop.png')
                result['node_review_and_other_draft'] = 'passed'
                attempts=[]
                def unknown(route):
                    request=route.request
                    message=message_from_bytes(('Content-Type: '+request.headers['content-type']+'\r\n\r\n').encode()+request.post_data_buffer)
                    attempts.append([(part.get_param('name',header='content-disposition'),part.get_filename(),part.get_payload(decode=True)) for part in message.walk() if part.get_content_disposition()=='form-data'])
                    if len(attempts)==1:
                        response=route.fetch();assert response.status==201
                        route.abort('failed')
                    else:route.continue_()
                page.route('**/handoff-reviews',unknown)
                returned=other.locator('.react-flow__node').filter(has_text='当前版 1').get_by_role('button',name='退回',exact=True)
                returned.click()
                expect(draft.locator('.form-error')).to_contain_text('重试')
                expect(other.locator('.react-flow__node').get_by_role('button',name='通过',exact=True)).to_be_disabled()
                returned.click()
                expect(other.locator(':scope > .between > .badge')).to_have_text('当前版 1 · 退回')
                assert attempts[0]==attempts[1],attempts
                page.unroute('**/handoff-reviews',unknown)
                saved=next(m for m in fixture.board(tid)['materials'] if m['ref']==second)['versions'][0]
                assert len(saved['reviews'])==1 and saved['reviews'][0]['note']=='另一份材料的草稿保留'
                assert fixture.clients['researcher'].get(saved['reviews'][0]['file_url']).data==b'OTHER DRAFT'
                result['unknown_retry_same_body_decision_file']='passed'
                concurrent=page.locator(f'[data-material-ref="{third}"]')
                old=concurrent.locator('[data-form=handoff-review]')
                old.locator('summary').click();old.locator('[name=note]').fill('版本1草稿不能移至版本2')
                old_ref=old.get_attribute('data-version')
                old=concurrent.locator(f'[data-form=handoff-review][data-version="{old_ref}"]')
                assert fixture.upload(tid,who='researcher',material_ref=third).status_code==201
                concurrent.locator('.react-flow__node').get_by_role('button',name='通过',exact=True).click()
                expect(old.locator('[data-handoff-conflict]')).to_be_visible()
                old.get_by_role('button',name='刷新状态，保留输入',exact=True).click()
                expect(old.locator('[name=note]')).to_have_value('版本1草稿不能移至版本2')
                expect(old).to_have_attribute('data-version',old_ref)
                concurrent.get_by_role('button',name='刷新材料状态',exact=True).click()
                expect(concurrent.locator(':scope > .between > .badge')).to_have_text('当前版 2 · 待审')
                expect(old.locator('[name=note]')).to_have_value('版本1草稿不能移至版本2')
                concurrent.get_by_text('保留的旧版审阅草稿',exact=True).click()
                expect(old.get_by_role('button',name='通过此版',exact=True)).to_be_disabled()
                concurrent.get_by_text('保留的旧版审阅草稿',exact=True).click()
                result['conflict_preserves_original_version_draft']='passed'
                for width,height in [(390,844),(320,780)]:
                    page.set_viewport_size({'width':width,'height':height})
                    page.evaluate('window.scrollTo(0,0)');capture(page,evidence/f'handoff-entry-{width}.png')
                    concurrent.get_by_label('选择材料版本',exact=True).select_option(old_ref)
                    concurrent.get_by_role('button',name='回当前版',exact=True).click()
                    current=concurrent.locator('.react-flow__node').filter(has_text='当前版 2')
                    current.get_by_role('button',name='通过',exact=True).scroll_into_view_if_needed()
                    capture(page,evidence/f'handoff-position-{width}.png')
                    assert current.evaluate('e=>{const a=e.getBoundingClientRect(),b=e.closest("[data-flow-slot]").getBoundingClientRect();return a.left>=b.left-2&&a.right<=b.right+2&&a.top>=b.top-2&&a.bottom<=b.bottom+2;}'),current.evaluate('e=>[e.getBoundingClientRect().toJSON(),e.closest("[data-flow-slot]").getBoundingClientRect().toJSON()]')
                    concurrent.locator(':scope > .between > h2').evaluate('e=>e.scrollIntoView({block:"start"})')
                    capture(page,evidence/f'handoff-pending-{width}.png')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                page.set_viewport_size({'width':1366,'height':900})
                latest=next(m for m in fixture.board(tid)['materials'] if m['ref']==third)['versions'][0]['ref']
                current_form=concurrent.locator(f'[data-form=handoff-review][data-version="{latest}"]')
                current_form.locator('summary').click()
                current_form.locator('[name=note]').fill('跨路由保存原版本草稿')
                current_form.locator('[name=file]').set_input_files({'name':'route.txt','mimeType':'text/plain','buffer':b'ROUTE DRAFT'})
                held=[]
                page.route('**/handoff-reviews',lambda route:held.append(route))
                concurrent.locator('.react-flow__node').filter(has_text='当前版 2').get_by_role('button',name='通过',exact=True).click()
                expect(current_form.locator('[name=note]')).to_be_disabled()
                page.locator('.sidebar [data-id=library]').click()
                expect(page.locator('.reading-library')).to_be_visible()
                response=held[0].fetch();held[0].fulfill(response=response)
                page.unroute('**/handoff-reviews')
                expect(page.locator('[data-handoff-reading]')).to_have_count(0)
                page.goto(base+f'/#collaboration?id={tid}&tab=selection')
                retained=page.locator(f'[data-material-ref="{third}"] [data-form=handoff-review][data-version="{latest}"]')
                expect(retained.locator('[name=note]')).to_have_value('跨路由保存原版本草稿')
                assert retained.locator('[name=file]').evaluate('e=>e.files[0].name')=='route.txt'
                result['late_route_keeps_version_draft']='passed'
                permissions=page.locator(f'[data-material-ref="{fourth}"]')
                protected=permissions.locator('[data-form=handoff-review]')
                protected.locator('summary').click();protected.locator('[name=note]').fill('资格变化保留草稿')
                qualification=next(q for q in fixture.clients['admin'].get('/api/collaboration/qualifications').json['items'] if q['id']=='researcher')
                assert fixture.call('/api/collaboration/qualifications/researcher',{'version':qualification['version'],'enabled':False},'admin','PUT').status_code==200
                button=permissions.locator('.react-flow__node').get_by_role('button',name='通过',exact=True)
                button.focus();page.keyboard.press('Enter')
                expect(protected.locator('[name=note]')).to_have_value('资格变化保留草稿')
                expect(protected.locator('[value=approved]')).to_be_disabled()
                expect(permissions.locator('.react-flow__node').get_by_role('button',name='通过',exact=True)).to_have_count(0)
                qualification=next(q for q in fixture.clients['admin'].get('/api/collaboration/qualifications').json['items'] if q['id']=='researcher')
                assert fixture.call('/api/collaboration/qualifications/researcher',{'version':qualification['version'],'enabled':True},'admin','PUT').status_code==200
                permissions.get_by_role('button',name='刷新材料状态',exact=True).click()
                expect(protected.locator('[value=approved]')).to_be_enabled()
                new_upload=page.locator('.handoff-materials > .handoff-upload');new_upload.locator('summary').click();new_upload.locator('[name=note]').fill('只属于研究员的未提交说明')
                held=[];page.route('**/handoff-reviews',lambda route:held.append(route))
                permissions.locator('.react-flow__node').get_by_role('button',name='退回',exact=True).click()
                capture(page,evidence/'late-account-before.png')
                result['late_account_pending']={'held':len(held),'form':protected.get_attribute('data-saving'),'error':protected.locator('.form-error').inner_text(),'allowed':protected.get_attribute('data-allowed')}
                expect(protected.locator('[name=note]')).to_be_disabled()
                page.get_by_role('button',name='退出登录',exact=True).click()
                page.get_by_role('button',name='协作同事',exact=True).click()
                response=held[0].fetch();held[0].fulfill(response=response);page.unroute('**/handoff-reviews')
                expect(page.locator('.workbench-account-link')).to_have_text('研究员 · 周')
                expect(page.locator('[data-form=handoff-review]')).to_have_count(0)
                expect(page.locator('.handoff-materials > .handoff-upload [name=note]')).to_have_value('')
                page.get_by_role('button',name='退出登录',exact=True).click()
                page.get_by_role('button',name='研究员',exact=True).click()
                expect(page.locator('.handoff-materials > .handoff-upload [name=note]')).to_have_value('只属于研究员的未提交说明')
                result['qualification_and_late_account']='passed'
                page.route('**/handoffs',lambda route:route.fulfill(status=401,json={'error':'合成会话失效'}))
                permissions.get_by_role('button',name='刷新材料状态',exact=True).click()
                expect(page.get_by_role('button',name='研究员',exact=True)).to_be_visible()
                expect(page.locator('[data-handoff-reading]')).to_have_count(0)
                page.unroute('**/handoffs')
                page.get_by_role('button',name='研究员',exact=True).click()
                expect(page.locator('.handoff-materials > .handoff-upload [name=note]')).to_have_value('只属于研究员的未提交说明')
                result['http_401_clears_reading_keeps_own_draft']='passed'
                page.goto(base+'/#library?feed=all&q=合成工作台')
                expect(page.locator('.library-row')).to_have_count(12)
                row=page.locator('.record-title button').first
                result['first_result_y']=row.bounding_box()['y']
                assert 54 <= row.bounding_box()['y'] < 700,row.bounding_box()
                expect(page.locator('[data-material-globe] canvas')).to_be_visible()
                capture(page,evidence/'discovery-desktop.png')
                globe_latvia(page)
                expect(page.locator('.library-row')).to_have_count(6)
                assert page.locator('.record-title button').first.bounding_box()['y']<700
                page.locator('[data-material-scene=time]').click()
                expect(page.locator('[data-material-timeline] canvas')).to_be_visible()
                page.locator('[data-material-from]').fill('2020');page.locator('[data-material-to]').fill('2020')
                page.locator('[data-material-apply]').click()
                expect(page.locator('.library-row')).to_have_count(3)
                result['real_globe_and_time_filter']='passed'
                capture(page,evidence/'time-desktop.png')
                row.click()
                expect(page.locator('.library-reader [data-reading-title]')).to_be_visible()
                head=page.locator('.library-reader-head')
                assert head.bounding_box()['y']>=54,head.bounding_box()
                expect(page.get_by_role('separator',name='调整清单与阅读宽度')).to_be_visible()
                divider=page.get_by_role('separator',name='调整清单与阅读宽度')
                divider.focus();page.keyboard.press('End');expect(divider).to_have_attribute('aria-valuenow','45');narrow_width=page.locator('.library-reader').bounding_box()['width']
                page.keyboard.press('Home');expect(divider).to_have_attribute('aria-valuenow','22');assert page.locator('.library-reader').bounding_box()['width']>narrow_width+50
                result['desktop_reader_width']=page.locator('.library-reader').bounding_box()['width']
                result['desktop_body_first_y']=page.locator('.library-reader #ux-body .rich-prose p').first.bounding_box()['y']
                capture(page,evidence/'reader-desktop.png')
                add=page.locator('.library-reader').get_by_role('button',name='加入比较',exact=True)
                expect(add).to_be_visible()
                add.click()
                page.locator('.library-reader').get_by_role('button',name='下一条',exact=True).click()
                page.locator('.library-reader').get_by_role('button',name='加入比较',exact=True).click()
                page.locator('.library-reader').get_by_role('button',name='比较 2 篇',exact=True).click()
                expect(page.get_by_role('region',name='资料比较',exact=True)).to_be_visible()
                capture(page,evidence/'compare-desktop.png')
                page.get_by_role('button',name='关闭比较',exact=True).click()
                expect(page.locator('.library-reader [data-reading-title]')).to_be_visible()
                paragraph=page.locator('.library-reader #ux-body')
                before=paragraph.bounding_box()['y']
                explorer=page.locator('.library-reader [data-record-explore]')
                explorer.locator(':scope > summary').click()
                expect(explorer.locator('[data-network-selection]')).to_be_visible()
                assert abs(paragraph.bounding_box()['y']-before)<2,(before,paragraph.bounding_box())
                explorer.get_by_text('关系文字列表',exact=True).click()
                explorer.locator('[data-explore-select]').first.click()
                explorer.get_by_role('button',name='空间关系',exact=True).click()
                explorer.locator('[data-network-selection] [data-explore-target]').click()
                expect(page.locator('.source-page')).to_be_visible()
                page.get_by_role('button',name='返回资料',exact=True).click()
                expect(page.locator('[data-network-selection]')).to_contain_text('合成 · 政策研究所')
                expect(page.locator('[data-explore-mode=space]')).to_have_attribute('aria-pressed','true')
                capture(page,evidence/'reader-relations-desktop.png')
                page.get_by_role('button',name='关闭关联',exact=True).click()
                for width,height in [(390,844),(320,780)]:
                    page.set_viewport_size({'width':width,'height':height})
                    page.goto(base+'/#library?feed=all&q=合成工作台');page.reload()
                    expect(page.locator('.library-row')).to_have_count(12)
                    row=page.locator('.record-title button').first
                    result[f'first_result_y_{width}']=row.bounding_box()['y']
                    assert row.bounding_box()['y']<height-80,row.bounding_box()
                    capture(page,evidence/f'discovery-{width}.png')
                    row.click()
                    expect(page.locator('.library-reader [data-reading-title]')).to_be_visible()
                    capture(page,evidence/f'reader-{width}.png')
                    relation=page.locator('[data-record-explore]');relation.locator(':scope > summary').click()
                    relation.get_by_text('关系文字列表',exact=True).click();relation.locator('[data-explore-select]').first.click()
                    relation.locator('[data-explore-locate]').click()
                    capture(page,evidence/f'reader-relations-{width}.png')
                    relation.get_by_role('button',name='关闭关联',exact=True).click()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                result['stable_discovery_reader']='passed'
                result['policy_violations']=verify_policy(page)
                assert not errors, errors
            finally:
                browser.close()
            check_maintenance(p,evidence)
            result['maintenance_changes_filters']='passed'
            check_fallback(p,evidence,base,fixture,tid)
            result['no_webgl_and_no_module']='passed'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        # Only this invocation's fresh, checked child directory is removed.
        assert data.parent == evidence and data.name == 'synthetic-data'
        if data.exists():
            shutil.rmtree(data)
        result.update(server_closed=not thread.is_alive(), synthetic_removed=not data.exists(), errors=errors,captures=CAPTURES)
        (evidence/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
