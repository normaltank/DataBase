"""#140 public HTTP + real Chrome acceptance. Synthetic provider, random port, no paid traffic."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import threading
import logging
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.test_maintenance_agent import MaintenanceAgentTests
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
while True:
    with socket.socket() as free:
        free.bind(('127.0.0.1', 0))
        PORT = free.getsockname()[1]
    if PORT not in {6430,3435,3436}:break
URL = f'http://127.0.0.1:{PORT}'


def run():
    evidence = ROOT / 'tests' / 'artifacts' / ('network-' + str(PORT))
    evidence.mkdir(parents=True, exist_ok=True)
    print('Evidence:', evidence, flush=True)
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', PORT)) != 0, 'Test port occupied'
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    fixture=MaintenanceAgentTests();fixture.setUp()
    server=make_server('127.0.0.1',PORT,fixture.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as pw:
            api = pw.request.new_context(base_url=URL)
            for _ in range(100):
                try:
                    if api.get('/health', timeout=500).ok:
                        break
                except Exception:
                    time.sleep(.1)
            def call(path, data, method='POST', client=api):
                token = client.get('/api/session').json()['csrf']
                response = client.fetch(path, method=method, data=data,
                    headers={'X-CSRF-Token': token})
                assert response.ok, (path, response.status, response.text())
                return response.json()
            call('/api/login', {'username': 'researcher', 'password': 'LocalDemo2026!'})
            publisher = call('/api/sources', {'name':'合成发布机构', 'kind':'institution'})['id']
            journal = call('/api/sources', {'name':'合成刊载期刊', 'kind':'journal'})['id']
            unit = call('/api/sources', {'name':'合成同名作者', 'kind':'institution'})['id']
            person = call('/api/people', {'name':'合成同名作者', 'change_note':'合成测试'})['id']
            rid = call('/api/records', {'title':'Explore 研究原文', 'kind':'report',
                'authors':'合成同名作者; 同名未确认', 'source_id':publisher, 'serial_id':journal,
                'abstract':'原始摘要用于验证阅读入口。', 'body_html':'<p>合成正文，用于测试阅读位置。</p>'*30})['id']
            by = api.get(f'/api/records/{rid}/bylines').json()
            call(f'/api/records/{rid}/bylines', {'version':by['version'],
                'record_version':by['record_version'], 'change_note':'合成人工确认', 'items':[
                {'raw_name':'合成同名作者', 'target_type':'person', 'target_id':person,
                    'status':'confirmed', 'evidence':'https://example.org/identity'},
                {'raw_name':'合成同名作者（同名未确认）', 'target_type':'person','target_id':person,'status':'pending'}]}, 'PUT')
            af = api.get(f'/api/records/{rid}/affiliations').json()
            call(f'/api/records/{rid}/affiliations', {'version':af['version'],
                'record_version':af['record_version'], 'byline_version':af['byline_version'],
                'change_note':'合成文章单位', 'items':[{'byline_id':af['bylines'][0]['id'],
                    'institution_id':unit, 'evidence':'https://example.org/article'}]}, 'PUT')
            outcome = call('/api/records', {'title':'可见中心成果', 'kind':'compilation',
                'author_id':'researcher', 'linked_ids':[rid], 'body_html':'<p>合成编译</p>'})['id']
            other = pw.request.new_context(base_url=URL)
            call('/api/login', {'username':'colleague', 'password':'LocalDemo2026!'}, client=other)
            hidden = call('/api/records', {'title':'不可泄露的隐藏成果', 'kind':'compilation',
                'author_id':'colleague', 'visibility':'restricted', 'linked_ids':[rid],
                'body_html':'<p>隐藏</p>'}, client=other)['id']
            revocable = call('/api/records', {'title':'稍后撤权的成果', 'kind':'compilation',
                'author_id':'colleague', 'linked_ids':[rid], 'body_html':'<p>合成成果</p>'}, client=other)['id']
            empty = call('/api/records', {'title':'Empty 无关系', 'kind':'report'})['id']
            for n in range(25):
                call('/api/records', {'title':f'Explore {n:02d}', 'kind':'report'})
            assert {r['id'] for r in api.get(f'/api/records/{rid}').json()['cited_by']} == {outcome, revocable}
            assert api.get(f'/api/records/{hidden}').status in (403,404)
            extension=evidence/'zoom-extension';extension.mkdir()
            (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Network acceptance zoom','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
            (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
            context=pw.chromium.launch_persistent_context(str(evidence/'profile'),headless=False,
                ignore_default_args=['--disable-extensions'],args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}'],base_url=URL,viewport={'width':1366,'height':900})
            context.add_cookies(api.storage_state()['cookies'])
            zoom=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page = context.pages[0]
            page.set_default_timeout(6000)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            strict="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'"
            prefix="""window.networkViolations=[];document.addEventListener('securitypolicyviolation',e=>window.networkViolations.push({directive:e.effectiveDirective,source:e.sourceFile,blocked:e.blockedURI}));
const meta=document.createElement('meta');meta.httpEquiv='Content-Security-Policy';meta.content=POLICY;document.head.append(meta);
const sentinel=document.createElement('i');sentinel.setAttribute('style','color:rgb(1, 2, 3)');document.body.append(sentinel);window.networkStyleSentinel=getComputedStyle(sentinel).color!=='rgb(1, 2, 3)';sentinel.remove();
try{Function('return 1')();window.networkEvalSentinel=false;}catch(e){window.networkEvalSentinel=true;}
""".replace('POLICY',json.dumps(strict))
            original=(ROOT/'static/visual-loader.js').read_text(encoding='utf-8')
            context.route('**/static/visual-loader.js',lambda route:route.fulfill(content_type='text/javascript',body=prefix+original))
            def open_reader(record=rid, query='Explore'):
                page.goto(URL+'/#library?q='+query+'&sort=title'+('&page=2' if record==rid else ''))
                page.locator(f'[data-library-record="{record}"] [data-action="detail"]').first.click()
                expect(page.locator('.library-reader [data-reading-title]')).to_be_visible()
            open_reader()
            # Tracer bullet: discover confirmed authors and real source roles before prose.
            explorer = page.locator('.library-reader [data-record-explore]')
            expect(explorer.locator('summary')).to_have_text('关联探索')
            assert explorer.evaluate('(e)=>!!(e.compareDocumentPosition(document.querySelector("#ux-body")) & Node.DOCUMENT_POSITION_FOLLOWING)')
            explorer.locator('summary').focus()
            page.keyboard.press('Enter')
            expect(explorer.get_by_role('button', name='空间关系', exact=True)).to_be_visible()
            expect(explorer).to_contain_text('已确认作者')
            expect(explorer).to_contain_text('合成同名作者')
            expect(explorer).to_contain_text('发布机构')
            expect(explorer).to_contain_text('刊载期刊')
            expect(explorer).to_contain_text('文章署名单位')
            expect(explorer).to_contain_text('同名未确认')
            expect(explorer.locator('.record-explore-edges [data-explore-target]')).to_have_count(6)
            assert '不可泄露' not in explorer.inner_text()
            expect(explorer.locator('[data-network-viewport] canvas').first).to_be_visible()
            assert page.evaluate('window.networkStyleSentinel && window.networkEvalSentinel')
            # Find the real person node by its rendered palette, not renderer internals.
            def click_person_node(label):
                viewport=explorer.locator('[data-network-viewport]');viewport.scroll_into_view_if_needed()
                page.wait_for_timeout(250)
                shot=evidence/(label+'.png');viewport.screenshot(path=str(shot))
                image=Image.open(shot).convert('RGB');points=[]
                for y in range(image.height):
                    for x in range(image.width):
                        if image.getpixel((x,y))==(121,82,0):points.append((x,y))
                assert points, label
                # The solid gold person sphere/circle is the only such node.
                x=sum(p[0] for p in points)/len(points);y=sum(p[1] for p in points)/len(points)
                box=viewport.bounding_box();page.mouse.click(box['x']+x,box['y']+y)
                expect(explorer.locator('[data-network-selection]')).to_contain_text('人物')
                expect(explorer.locator('[data-network-selection]')).to_contain_text(person)
                expect(explorer.locator('[data-network-selection]')).to_contain_text('https://example.org/identity')
            click_person_node('plane-node')
            explorer.get_by_role('button',name='空间关系',exact=True).click()
            expect(explorer.locator('[data-network-viewport] canvas')).to_have_count(1)
            expect(explorer.locator('[data-network-selection]')).to_contain_text(person)
            expect(explorer.locator('[data-network-label]')).to_have_count(7)
            explorer.locator(f'[data-explore-select="source:{unit}"]').click()
            expect(explorer.locator('[data-network-selection]')).to_contain_text('来源档案')
            expect(explorer.locator('[data-network-selection]')).to_contain_text(unit)
            explorer.locator(f'[data-explore-select="person:{person}"]').click()
            # Return to the centre by its keyboard equivalent, leaving person unselected for palette picking.
            explorer.get_by_role('button',name='刷新关联',exact=True).click()
            expect(explorer.locator('[data-network-viewport] canvas')).to_have_count(1)
            # Current selected person remains selected across refresh and both modes.
            expect(explorer.locator('[data-network-selection]')).to_contain_text(person)
            explorer.locator('[data-explore-select]').filter(has_text='合成发布机构').click()
            box=explorer.locator('[data-network-viewport]').bounding_box()
            page.mouse.move(box['x']+30,box['y']+30);page.mouse.down();page.mouse.move(box['x']+80,box['y']+50,steps=8);page.mouse.up()
            click_person_node('space-rotated-node')
            explorer.locator('[data-network-selection] a').click()
            expect(page.locator('.person-page')).to_contain_text('合成同名作者')
            page.get_by_role('button', name='返回资料', exact=True).click()
            expect(explorer).to_have_attribute('open', '')
            explorer.get_by_role('button',name='平面关系',exact=True).click()
            # Real destinations and both explicit return and browser back retain context.
            explorer.locator(f'.record-explore-edges [data-explore-target][data-id="{person}"]').click()
            expect(page.locator('.person-page')).to_be_visible()
            page.get_by_role('button', name='返回资料', exact=True).click()
            expect(explorer).to_be_visible()
            expect(explorer).to_have_attribute('open', '')
            assert 'q=Explore' in page.url and 'sort=title' in page.url
            explorer.locator(f'.record-explore-edges [data-explore-target][data-id="{publisher}"]').click()
            expect(page.locator('.source-profile')).to_be_visible()
            page.go_back()
            expect(explorer).to_be_visible()
            explorer.locator(f'.record-explore-edges [data-explore-target][data-id="{outcome}"]').click()
            expect(page.locator('.library-reader [data-reading-title]')).to_have_text('可见中心成果')
            outcome_explorer=page.locator('.library-reader [data-record-explore]')
            outcome_explorer.locator('summary').click()
            expect(outcome_explorer).to_contain_text('本篇引用的原始资料')
            expect(outcome_explorer.locator(f'.record-explore-edges [data-explore-target][data-id="{rid}"]')).to_have_text('Explore 研究原文')
            page.get_by_role('button',name='返回前一篇：Explore 研究原文',exact=True).click()
            expect(page.locator('.library-reader [data-reading-title]')).to_have_text('Explore 研究原文')
            expect(explorer).to_have_attribute('open', '')
            assert 'q=Explore' in page.url
            assert 'page=2' in page.url
            # Permission changes affect the visible relationship projection immediately.
            version = other.get(f'/api/records/{revocable}').json()['version']
            call(f'/api/records/{revocable}', {'version':version,'visibility':'restricted'}, 'PUT', client=other)
            explorer.get_by_role('button',name='刷新关联',exact=True).click()
            expect(explorer.locator('.record-explore-edges [data-explore-target]')).to_have_count(5)
            expect(explorer).not_to_contain_text('稍后撤权')
            # A public HTTP failure is local to exploration and provides a retry.
            page.route(f'**/api/records/{rid}/bylines',lambda route:route.fulfill(status=503,json={'error':'Synthetic unavailable'}))
            explorer.get_by_role('button',name='刷新关联',exact=True).click()
            expect(explorer.get_by_role('alert')).to_contain_text('关联读取失败')
            expect(page.locator('#ux-body')).to_contain_text('合成正文')
            page.unroute(f'**/api/records/{rid}/bylines')
            explorer.get_by_role('button',name='重试读取关联',exact=True).click()
            expect(explorer.locator('.record-explore-edges [data-explore-target]')).to_have_count(5)
            expect(explorer.locator('.record-explore-content')).not_to_have_attribute('aria-busy','true')
            # Real browser native zoom, narrow viewports and keyboard equivalents.
            for name,width,scale in [('desktop',1366,1),('mobile',390,1),('small',320,1),('zoom-200',1366,2)]:
                page.set_viewport_size({'width':width,'height':900})
                zoom.evaluate('async ({url,factor})=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));await chrome.tabs.setZoom(t.id,factor);}',{'url':URL,'factor':scale})
                actual=zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));return chrome.tabs.getZoom(t.id);}',URL)
                assert actual==scale
                explorer.locator('summary').focus();page.keyboard.press('Tab')
                expect(explorer.get_by_role('button',name='平面关系',exact=True)).to_be_focused()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'), name
                explorer.locator('[data-network-viewport]').scroll_into_view_if_needed()
                page.wait_for_timeout(350)
                def capture_view(path):
                    if scale==2:
                        page.evaluate('window.scrollTo(0,0)')
                        page.wait_for_timeout(350)
                    page.screenshot(path=str(path))
                capture_view(evidence/(name+'.png'))
                explorer.get_by_role('button',name='空间关系',exact=True).click()
                expect(explorer.locator('[data-network-viewport] canvas')).to_have_count(1)
                explorer.locator('[data-network-viewport]').scroll_into_view_if_needed()
                page.wait_for_timeout(350)
                capture_view(evidence/(name+'-space.png'))
                png=Image.open(evidence/(name+'-space.png')).convert('RGB')
                assert sum(1 for r,g,b in png.get_flattened_data() if b>r+15)>100, 'Blank native screenshot: '+name
                explorer.get_by_role('button',name='平面关系',exact=True).click()
                controls=explorer.locator('button:visible').evaluate_all('(els)=>els.map(e=>({text:e.textContent,height:e.getBoundingClientRect().height,min:getComputedStyle(e).minHeight}))')
                assert all(c['height']>=43.9 for c in controls), (name,controls)
            zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));await chrome.tabs.setZoom(t.id,1);}',URL)
            page.emulate_media(reduced_motion='reduce')
            # Late responses cannot replace a newly opened article.
            page.set_viewport_size({'width':1366,'height':900})
            pending=[]
            page.route(f'**/api/records/{rid}/bylines',lambda route:pending.append(route))
            explorer.get_by_role('button',name='刷新关联',exact=True).click()
            page.wait_for_timeout(150)
            assert pending
            open_reader(empty,'Empty')
            new_explorer=page.locator('.library-reader [data-record-explore]')
            new_explorer.locator('summary').click()
            expect(new_explorer).to_contain_text('尚未登记可查看的关联')
            pending.pop().continue_()
            expect(new_explorer).not_to_contain_text('合成同名作者')
            page.unroute(f'**/api/records/{rid}/bylines')
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(evidence/'empty.png'),full_page=False)
            # Real bounded worker writes a formal AI relation via the synthetic provider.
            admin=pw.request.new_context(base_url=URL)
            call('/api/login',{'username':'admin','password':'LocalDemo2026!'},client=admin)
            call('/api/admin/maintenance/run',{},client=admin)
            ai=api.get(f'/api/records/{fixture.rid}/bylines').json()['items'][0]
            assert ai['machine'] and ai['status']=='confirmed' and not ai['human_checked'], ai
            open_reader(fixture.rid,'Baltic cooperation')
            explorer.locator('summary').click()
            expect(explorer).to_contain_text('AI 关联作者')
            expect(explorer).to_contain_text('AI 正式关联 · 尚未人工核对')
            explorer.locator(f'[data-explore-select="person:{ai["target_id"]}"]').click()
            expect(explorer.locator('[data-network-selection]')).to_contain_text('Alex Vale')
            explorer.get_by_role('button',name='空间关系',exact=True).click()
            expect(explorer.locator('[data-network-viewport] canvas')).to_have_count(1)
            explorer.get_by_role('button',name='查看所选关系',exact=True).click()
            expect(explorer.locator('[data-network-selection]')).to_be_focused()
            page.screenshot(path=str(evidence/'ai-formal-selection.png'))
            # Normal loading under strict CSP emits only our intentional sentinels.
            policy=page.evaluate('window.networkViolations')
            assert policy and all(v['source'].endswith('/static/visual-loader.js') for v in policy),policy
            # A real failed same-origin module retains semantic text and can retry.
            fallback=context.new_page()
            fallback.route('**/static/vendor/visual/network.js*',lambda route:route.abort())
            fallback.goto(URL+'/#library?q='+rid)
            fallback.locator(f'[data-library-record="{rid}"] [data-action="detail"]').first.click()
            fb=fallback.locator('[data-record-explore]');fb.locator('summary').click()
            expect(fb.locator('[data-network-status]')).to_contain_text('图形未能加载')
            expect(fb.locator(f'[data-explore-select="person:{person}"]')).to_be_visible()
            fallback.unroute('**/static/vendor/visual/network.js*')
            fb.get_by_role('button',name='重试图形',exact=True).click()
            expect(fb.locator('[data-network-viewport] canvas').first).to_be_visible()
            fallback.close()
            # Browser without WebGL can still use actual Cytoscape and text destinations.
            no_gl=pw.chromium.launch(args=['--disable-webgl'])
            no_context=no_gl.new_context(base_url=URL,storage_state=api.storage_state())
            no_page=no_context.new_page();no_page.goto(URL+'/#library?q='+rid)
            no_page.locator(f'[data-library-record="{rid}"] [data-action="detail"]').first.click()
            ng=no_page.locator('[data-record-explore]');ng.locator('summary').click()
            expect(ng.locator('[data-network-viewport] canvas').first).to_be_visible()
            ng.get_by_role('button',name='空间关系',exact=True).click()
            expect(ng.locator('[data-network-status]')).to_contain_text('图形未能加载')
            ng.get_by_role('button',name='平面关系',exact=True).click()
            expect(ng.locator('[data-network-viewport] canvas').first).to_be_visible()
            ng.locator(f'.record-explore-edges [data-explore-target][data-id="{person}"]').click()
            expect(no_page.locator('.person-page')).to_contain_text('合成同名作者')
            no_gl.close()
            # Change the actual browser session while a relationship response waits.
            open_reader()
            explorer.locator('summary').click()
            expect(explorer.locator('.record-explore-edges [data-explore-target]')).to_have_count(5)
            page.route(f'**/api/records/{rid}/bylines',lambda route:pending.append(route))
            explorer.get_by_role('button',name='刷新关联',exact=True).click()
            page.wait_for_timeout(150)
            assert pending
            call('/api/login', {'username':'colleague','password':'LocalDemo2026!'},client=context.request)
            pending.pop().continue_()
            expect(explorer.get_by_role('alert')).to_contain_text('关联读取失败')
            expect(explorer.locator('.record-explore-edges [data-explore-target]')).to_have_count(0)
            page.unroute(f'**/api/records/{rid}/bylines')
            page.reload()
            expect(page.locator('.topbar')).to_contain_text('研究员 · 周')
            (evidence / 'result.json').write_text(json.dumps({'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'confirmed_identity_and_roles':True,
                'query_page_and_reader_return':True,'restricted_target_omission_and_revocation':True,
                'failure_retry_empty_late_response_account_switch':True,
                'viewports':['1366','390','320','native chrome.tabs 200%'],'strict_policy':strict,'sentinel_only_violations':policy,'plane_and_space_real_node_picking':True,'AI_formal_manual_separate':True,'module_retry_no_webgl':True,'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
            assert not errors, errors
            context.close()
    finally:
        server.shutdown();server.server_close();fixture.doCleanups()


if __name__ == '__main__':
    run()
