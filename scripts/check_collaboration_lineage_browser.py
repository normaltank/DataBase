"""#136 material lineage: public HTTP fixtures and real isolated Chrome interaction."""
import argparse
import base64
import json
import logging
import os
import subprocess
from pathlib import Path
import sys
import threading
import uuid
from live_flow_browser_policy import install as strict_policy, verify as verify_policy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from platform_app.web import create_app
from tests.test_topic_handoffs import HandoffTests


def return_current(material):
    button=material.get_by_role('button',name='回当前版',exact=True)
    if button.is_visible():button.click()
    else:material.get_by_label('选择材料版本',exact=True).select_option(index=0)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--baseline-flow', action='store_true')
    args = parser.parse_args()
    root = Path(args.evidence).resolve()
    root.mkdir(parents=True, exist_ok=False)
    extension = root/'zoom-extension'
    extension.mkdir()
    (extension/'manifest.json').write_text(json.dumps({'manifest_version':3, 'name':'Synthetic lineage zoom', 'version':'1.0', 'permissions':['tabs'], 'background':{'service_worker':'worker.js'}}))
    (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    fixture = HandoffTests()
    fixture.data_dir = root/'synthetic-data'
    fixture.app = create_app(fixture.data_dir, testing=True, embedded_worker=False)
    fixture.clients = {name: fixture.login(name) for name in ('researcher', 'colleague', 'admin')}
    tid = fixture.topic(theme='合成 · 拉脱维亚研究材料交接')
    ref = None
    versions = []
    for number in range(1, 4):
        data = dict(stage='selection', token=fixture.board(tid)['token'], request_id=uuid.uuid4().hex,
                    title='合成 · 拉脱维亚政党研究', note=f'第{number}版独立说明')
        if ref:
            data['material_ref'] = ref
        result = fixture.call(f'/api/collaboration/topics/{tid}/handoffs', data,
                              file=(f'研究原件-v{number}.txt', f'SYNTHETIC ORIGINAL VERSION {number}'.encode()))
        assert result.status_code == 201, result.json
        ref = result.json['material_ref']
        version = next(m for m in fixture.board(tid)['materials'] if m['ref'] == ref)['versions'][0]
        versions.append(version)
        if number < 3:
            review = fixture.call(f'/api/collaboration/topics/{tid}/handoff-reviews', dict(
                token=fixture.board(tid)['token'], request_id=uuid.uuid4().hex, version_ref=version['ref'],
                decision='returned' if number == 1 else 'approved', note='请补充政策依据' if number == 1 else '依据已核对，可接续'),
                file=(f'审阅-v{number}.txt', f'SYNTHETIC REVIEW {number}'.encode()))
            assert review.status_code == 201, review.json
    second = fixture.call(f'/api/collaboration/topics/{tid}/handoffs', dict(
        stage='selection', token=fixture.board(tid)['token'], request_id=uuid.uuid4().hex,
        title='合成 · 第二份独立材料', note='第二材料说明'), file=('第二材料.txt', b'SYNTHETIC SECOND MATERIAL'))
    assert second.status_code == 201
    initial_board = fixture.board(tid)
    (root/'fixture.json').write_text(json.dumps({'topic_id':tid, 'material_ref':ref,
        'second_material_ref':second.json['material_ref'], 'versions':versions,
        'data_dir':str(fixture.data_dir), 'worker_enabled':False}, ensure_ascii=False, indent=2), encoding='utf-8')
    server = make_server('127.0.0.1', 0, fixture.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(str(root/'profile'), executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE', p.chromium.executable_path), headless=False,
                ignore_default_args=['--disable-extensions'], args=['--headless=new', f'--disable-extensions-except={extension}', f'--load-extension={extension}'], viewport={'width':1366,'height':1000})
            try:
                zoom = browser.service_workers[0] if browser.service_workers else browser.wait_for_event('serviceworker')
                page = browser.pages[0]
                strict_policy(page,args.baseline_flow)
                workers=[]
                page.on('worker',lambda worker:workers.append(worker.url))
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(base+f'/#collaboration?id={tid}&tab=selection')
                page.get_by_role('button', name='研究员', exact=True).click()
                material = page.locator(f'[data-material-ref="{ref}"]')
                page.locator('[data-desk-material="'+ref+'"]').click()
                expect(material).to_be_visible()
                material.scroll_into_view_if_needed()
                material.locator('.handoff-graph>summary').click()
                material.locator('.desk-refresh>summary').click()
                material.locator('.handoff-track-details>summary').click()
                expect(material.get_by_role('button', name='查看版本 1', exact=True)).to_be_visible()
                reading = material.locator('[data-handoff-reading]')
                expect(material.locator('.react-flow__node')).to_have_count(5)
                expect(material.locator('[data-flow-status]')).to_have_text('')
                page.wait_for_timeout(600)
                expect(material.locator('[data-flow-status]')).to_have_text('')
                # Full-document capture temporarily renders at 1x1 in this
                # Chromium, which starts responsive graph layout mid-capture.
                # Use a real full-content CSS viewport and wait for that layout.
                initial_height=page.evaluate('document.documentElement.scrollHeight')
                page.set_viewport_size({'width':1366,'height':initial_height})
                expect(material.locator('.react-flow__node')).to_have_count(5)
                expect(material.locator('[data-flow-status]')).to_have_text('')
                page.evaluate('scrollTo(0,0);new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                page.screenshot(path=str(root/'initial-desktop.png'))
                assert material.locator('[data-flow-status]').inner_text()==''
                (root/'initial-desktop-metrics.json').write_text(json.dumps({'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'nodeCount':5,'flowStatus':'','viewport':page.evaluate('({innerWidth,innerHeight,scrollY,documentHeight:document.documentElement.scrollHeight,deviceScale:devicePixelRatio})'),'method':'normal screenshot of actual full-content CSS viewport'},indent=2),encoding='utf-8')
                page.set_viewport_size({'width':1366,'height':1000})
                expect(material.locator('[data-flow-status]')).to_have_text('')
                material.locator('.handoff-graph>summary').click()
                material.locator('.handoff-track-details').scroll_into_view_if_needed()
                page.screenshot(path=str(root/'timeline-primary-desktop.png'))
                page.set_viewport_size({'width':390,'height':844})
                material.locator('.handoff-track-details').scroll_into_view_if_needed()
                page.screenshot(path=str(root/'timeline-primary-390.png'))
                page.set_viewport_size({'width':1366,'height':1000})
                material.locator('.handoff-graph>summary').click()
                assert material.locator('[data-flow-slot]').evaluate('(slot)=>{const b=slot.getBoundingClientRect();return [...slot.querySelectorAll(".react-flow__node")].every(node=>{const r=node.getBoundingClientRect();return r.left>=b.left-2&&r.right<=b.right+2&&r.top>=b.top-2&&r.bottom<=b.bottom+2;});}'),'The short material lineage must fit by default on desktop'
                material.locator('.actual-flow').scroll_into_view_if_needed()
                page.screenshot(path=str(root/'lineage-default-desktop.png'))
                material.get_by_role('button',name='显示全图',exact=True).click()
                graph=material.locator('.react-flow__node').filter(has_text='版本 1').filter(has_text='退回').first
                graph.click()
                expect(reading).to_contain_text('历史版 1 · 退回')
                groups=material.locator('.actual-flow').evaluate('e=>e._actualFlow.snapshot.groups')
                assert [len(g['nodes']) for g in groups]==[2,2,1],groups
                assert [g['nodes'][0] for g in groups]==['version:'+v['ref'] for v in versions]
                assert material.locator('.react-flow__node button').count()==0,'Material nodes remain read-only'
                return_current(material)
                expect(reading).to_contain_text('原件与意见')
                for number, decision, note in [(1, '退回', '请补充政策依据'), (2, '通过', '依据已核对，可接续')]:
                    material.get_by_role('button', name=f'查看版本 {number}', exact=True).click()
                    expect(reading).to_contain_text(f'历史版 {number} · {decision}')
                    expect(reading).to_contain_text(f'第{number}版独立说明')
                    expect(reading).to_contain_text(note)
                    expect(reading.locator('[data-reading-version]')).to_have_attribute('data-reading-version', versions[number-1]['ref'])
                    with page.expect_download() as saved:
                        reading.get_by_role('link', name='下载原件', exact=True).click()
                    assert Path(saved.value.path()).read_bytes() == f'SYNTHETIC ORIGINAL VERSION {number}'.encode()
                    with page.expect_download() as attached:
                        reading.get_by_role('link', name=f'审阅附件：审阅-v{number}.txt', exact=True).click()
                    assert Path(attached.value.path()).read_bytes() == f'SYNTHETIC REVIEW {number}'.encode()
                    reading.get_by_role('button', name='查看内容', exact=True).click()
                    expect(material.locator('[data-desk-preview]')).to_contain_text(f'SYNTHETIC ORIGINAL VERSION {number}')
                    material.get_by_role('button', name=f'查看版本 {number} 的{decision}审阅', exact=True).click()
                    expect(reading.locator('[data-reading-review].is-selected')).to_have_count(1)
                    expect(material.locator('.handoff-lineage-row.is-selected .handoff-review-link[aria-pressed=true]')).to_have_count(1)
                return_current(material)
                expect(reading).to_contain_text('原件与意见')
                expect(reading.locator('[data-reading-review]')).to_have_count(0)
                expect(material.locator('[data-action=handoff-select][data-version="'+versions[2]['ref']+'"][data-review]:not([data-review=""])')).to_have_count(0)
                second_material = page.locator(f'[data-material-ref="{second.json["material_ref"]}"]')
                expect(second_material.locator('[data-handoff-reading]')).to_contain_text('第二材料说明')
                page.locator('[data-desk-material="'+second.json['material_ref']+'"]').click()
                second_material.locator('.handoff-track-details>summary').click()
                page.locator('[data-desk-material="'+ref+'"]').click()
                upload = material.locator('[data-form=handoff-upload]')
                review_form = material.locator('[data-form=handoff-review][data-version="'+versions[2]['ref']+'"]')
                upload.locator('xpath=..').locator('summary').click()
                upload.locator('[name=file]').set_input_files({'name':'draft.txt','mimeType':'text/plain','buffer':b'RETAIN UPLOAD DRAFT'})
                upload.locator('[name=note]').fill('保留上传草稿')
                review_form.locator('summary').click()
                review_form.locator('[name=file]').set_input_files({'name':'review-draft.txt','mimeType':'text/plain','buffer':b'RETAIN REVIEW DRAFT'})
                review_form.locator('[name=note]').fill('保留审阅草稿')
                upload.evaluate('(e)=>window.originalUpload=e')
                review_form.evaluate('(e)=>window.originalReview=e')
                material.get_by_role('button', name='查看版本 1', exact=True).click()
                page.locator('[data-desk-material="'+second.json['material_ref']+'"]').click()
                second_material.get_by_role('button', name='查看版本 1', exact=True).click()
                page.locator('[data-desk-material="'+ref+'"]').click()
                expect(upload.locator('[name=note]')).to_have_value('保留上传草稿')
                expect(review_form.locator('[name=note]')).to_have_value('保留审阅草稿')
                assert upload.locator('[name=file]').evaluate('e=>e.files[0].name') == 'draft.txt'
                assert review_form.locator('[name=file]').evaluate('e=>e.files[0].name') == 'review-draft.txt'
                assert page.evaluate('originalUpload.isConnected && originalReview.isConnected')
                expect(review_form).to_have_attribute('data-version', versions[2]['ref'])
                material.get_by_role('button', name='刷新材料状态', exact=True).click()
                expect(material.locator('[data-lineage-status]')).to_contain_text('已更新')
                assert page.evaluate('originalUpload.isConnected && originalReview.isConnected')
                assert upload.locator('[name=file]').evaluate('e=>e.files[0].name') == 'draft.txt'
                expect(review_form.locator('[name=note]')).to_have_value('保留审阅草稿')
                # No-change reread preserves the actual focused/read DOM as well as forms.
                reading.evaluate('e=>window.originalReading=e.firstElementChild')
                material.get_by_role('button', name='刷新材料状态', exact=True).click()
                expect(material.locator('[data-lineage-status]')).to_contain_text('已更新')
                assert page.evaluate('originalReading.isConnected')
                # Stable read selection, keyboard focus and actual native zoom.
                material.get_by_role('button', name='查看版本 2 的通过审阅', exact=True).focus()
                page.keyboard.press('Enter')
                expect(reading).to_contain_text('历史版 2 · 通过')
                expect(material.get_by_role('button', name='查看版本 2 的通过审阅', exact=True)).to_be_focused()
                captures = []
                for width, height, factor in [(1366,1000,1),(390,844,1),(320,780,1),(1366,1000,2)]:
                    page.set_viewport_size({'width':width,'height':height})
                    zoom.evaluate('async ({url,factor})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,factor)}', {'url':base, 'factor':factor})
                    actual = zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));return chrome.tabs.getZoom(t.id)}', base)
                    assert actual == factor
                    return_current(material)
                    expect(reading).to_contain_text('原件与意见')
                    if width < 700 or factor == 2:
                        material.get_by_label('选择材料版本', exact=True).select_option(versions[0]['ref'])
                        expect(reading).to_contain_text('历史版 1 · 退回')
                    else:
                        material.get_by_role('button', name='查看版本 1 的退回审阅', exact=True).click()
                    material.locator('.handoff-lineage').scroll_into_view_if_needed()
                    page.wait_for_timeout(250)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                    if width < 700 or factor == 2:
                        controls = material.locator('.handoff-lineage button:visible,.handoff-lineage select:visible').evaluate_all('els=>els.map(e=>({text:e.textContent,h:e.getBoundingClientRect().height}))')
                        assert all(c['h'] >= 43.99 for c in controls), controls
                        picker=material.get_by_label('选择材料版本',exact=True)
                        picker.focus();picker.select_option(versions[0]['ref'])
                        expect(picker).to_be_focused()
                        jump=material.get_by_role('button',name='查看所选版本 1 的原件与意见',exact=True)
                        expect(jump).to_be_visible()
                        assert jump.evaluate('e=>{const r=e.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight}'),jump.bounding_box()
                        before=root/f'lineage-{width}-zoom{factor}-selected.png'
                        if factor==2:
                            capture=browser.new_cdp_session(page)
                            before.write_bytes(base64.b64decode(capture.send('Page.captureScreenshot',{'format':'png','fromSurface':True,'captureBeyondViewport':False})['data']))
                            capture.detach()
                        else:page.screenshot(path=str(before))
                        captures.append(str(before))
                        jump.focus();page.keyboard.press('Enter')
                        expect(jump).to_be_focused()
                        expect(reading.locator('[data-reading-version]')).to_have_attribute('data-reading-version',versions[0]['ref'])
                        assert reading.evaluate('e=>{const r=e.getBoundingClientRect();return r.top>=0&&r.top<innerHeight-100}'),reading.bounding_box()
                        expect(upload.locator('[name=note]')).to_have_value('保留上传草稿')
                        expect(review_form.locator('[name=note]')).to_have_value('保留审阅草稿')
                        assert upload.locator('[name=file]').evaluate('e=>e.files[0].name')=='draft.txt'
                        assert review_form.locator('[name=file]').evaluate('e=>e.files[0].name')=='review-draft.txt'
                        expect(review_form).to_have_attribute('data-version',versions[2]['ref'])
                    shot = root/f'lineage-{width}-zoom{factor}.png'
                    if factor == 2:
                        # Native zoom changes CSS viewport dimensions; compositor capture
                        # avoids Playwright's CSS-sized viewport clip producing a blank image.
                        capture = browser.new_cdp_session(page)
                        shot.write_bytes(base64.b64decode(capture.send('Page.captureScreenshot',{'format':'png','fromSurface':True,'captureBeyondViewport':False})['data']))
                        (root/'native-zoom-metrics.json').write_text(json.dumps(capture.send('Page.getLayoutMetrics'),indent=2),encoding='utf-8')
                        capture.detach()
                    else:
                        page.screenshot(path=str(shot))
                    captures.append(str(shot))
                    material.get_by_role('button',name='定位所选节点',exact=True).click()
                    material.locator('.actual-flow').scroll_into_view_if_needed();page.wait_for_timeout(150)
                    graph_shot=root/f'lineage-flow-{width}-zoom{factor}.png'
                    if factor==2:
                        compositor=browser.new_cdp_session(page)
                        graph_shot.write_bytes(base64.b64decode(compositor.send('Page.captureScreenshot',{'format':'png','fromSurface':True,'captureBeyondViewport':False})['data']))
                        compositor.detach()
                    else:page.screenshot(path=str(graph_shot))
                    captures.append(str(graph_shot))
                    if width<700:
                        page.evaluate('scrollTo(0,0)')
                        full=root/f'lineage-{width}-fullpage.png';page.screenshot(path=str(full),full_page=True)
                        captures.append(str(full))
                    if width<700 or factor==2:
                        review_node=material.get_by_role('button',name='查看版本 1 的退回审阅',exact=True)
                        review_node.focus();page.keyboard.press('Enter');expect(review_node).to_be_focused()
                        jump.focus();page.keyboard.press('Enter');expect(jump).to_be_focused()
                        expect(reading.locator('[data-reading-review].is-selected')).to_have_count(1)
                        expect(reading.locator('[data-reading-review].is-selected')).to_have_count(1)
                zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,1)}', base)
                page.set_viewport_size({'width':1366,'height':1000})
                return_current(material)
                material.locator('.handoff-lineage').scroll_into_view_if_needed()
                page.wait_for_timeout(250)
                page.screenshot(path=str(root/'lineage-current-desktop.png'), full_page=True)
                captures.append(str(root/'lineage-current-desktop.png'))
                # Both progressive-enhancement fallbacks complete the same operation.
                page.emulate_media(reduced_motion='reduce')
                material.get_by_role('button', name='查看版本 2', exact=True).click()
                expect(reading).to_contain_text('历史版 2 · 通过')
                page.set_viewport_size({'width':390,'height':844})
                reduced_jump=material.get_by_role('button',name='查看所选版本 2 的原件与意见',exact=True)
                reduced_jump.focus();page.keyboard.press('Enter');expect(reduced_jump).to_be_focused()
                assert reading.evaluate('e=>{const r=e.getBoundingClientRect();return r.top>=0&&r.top<innerHeight-100}')
                page.evaluate('Element.prototype.animate=undefined;document.startViewTransition=undefined')
                page.emulate_media(reduced_motion='no-preference')
                return_current(material)
                expect(reading).to_contain_text('原件与意见')
                page.set_viewport_size({'width':1366,'height':1000})
                # Failed state reads keep last readable content, and no parallel chain accumulates.
                page.route('**/handoffs', lambda route: route.fulfill(status=503, json={'error':'合成读取失败'}))
                material.get_by_role('button', name='刷新材料状态', exact=True).click()
                expect(material.locator('[data-lineage-status]')).to_contain_text('合成读取失败')
                expect(reading).to_contain_text('原件与意见')
                page.unroute('**/handoffs')
                # A failed write leaves the selected real files and typed drafts in place.
                page.route('**/handoff-reviews', lambda route: route.fulfill(status=503, json={'error':'合成保存失败'}))
                review_form.get_by_role('button', name='通过此版', exact=True).click()
                expect(review_form.locator('.form-error')).to_contain_text('合成保存失败')
                page.unroute('**/handoff-reviews')
                expect(review_form.locator('[name=note]')).to_have_value('保留审阅草稿')
                assert review_form.locator('[name=file]').evaluate('e=>e.files[0].name') == 'review-draft.txt'
                # A concurrent actual version makes the bound old review conflict, never retargets it.
                new = fixture.call(f'/api/collaboration/topics/{tid}/handoffs', dict(stage='selection',token=fixture.board(tid)['token'],request_id=uuid.uuid4().hex,material_ref=ref,note='真实并发第四版'), file=('v4.txt',b'SYNTHETIC CONCURRENT FOURTH'))
                assert new.status_code == 201
                review_form.get_by_role('button', name='通过此版', exact=True).click()
                expect(review_form.locator('.form-error')).to_contain_text('已更新')
                expect(review_form.locator('[name=note]')).to_have_value('保留审阅草稿')
                material.get_by_role('button', name='刷新材料状态', exact=True).click()
                expect(material.locator('[data-lineage-status]')).to_contain_text('已更新')
                expect(review_form.locator('[name=note]')).to_have_value('保留审阅草稿')
                expect(review_form).to_have_attribute('data-version',versions[2]['ref'])
                expect(review_form.locator('[type=submit][value=approved]')).to_be_disabled()
                assert upload.locator('[name=file]').evaluate('e=>e.files[0].name') == 'draft.txt'
                expect(upload.locator('[name=note]')).to_have_value('保留上传草稿')
                # Independent material reads may finish in reverse order: older state
                # must not replace a newer board and break its already rendered v4.
                older_reads = []
                def reorder(route):
                    if not older_reads:
                        older_reads.append(route)
                    else:
                        route.continue_()
                page.route('**/handoffs', reorder)
                material.get_by_role('button', name='刷新材料状态',exact=True).click()
                expect(material.locator('[data-lineage-status]')).to_contain_text('正在读取')
                page.locator('[data-desk-material="'+second.json['material_ref']+'"]').click()
                second_material.locator('.desk-refresh>summary').click()
                second_material.get_by_role('button',name='刷新材料状态',exact=True).click()
                expect(second_material.locator('[data-lineage-status]')).to_contain_text('已更新')
                page.locator('[data-desk-material="'+ref+'"]').click()
                older_reads[0].fulfill(status=200,json=initial_board)
                expect(material.locator('[data-lineage-status]')).not_to_contain_text('正在读取')
                return_current(material)
                expect(reading).to_contain_text('原件与意见')
                page.unroute('**/handoffs')
                # Closed periods deny the existing bound upload without discarding either file.
                preview = fixture.clients['researcher'].get(f'/api/collaboration/topics/{tid}/closure-preview').json
                ended = fixture.call(f'/api/collaboration/topics/{tid}/end', dict(request_id=uuid.uuid4().hex, confirm=True, **{k:preview[k] for k in ('basis_token','lifecycle_version')}))
                assert ended.status_code == 201
                material.get_by_role('button', name='刷新材料状态', exact=True).click()
                expect(upload.get_by_role('button', name='保存新版本',exact=True)).to_be_disabled()
                expect(upload.locator('[name=note]')).to_have_value('保留上传草稿')
                assert upload.locator('[name=file]').evaluate('e=>e.files[0].name') == 'draft.txt'
                closed = fixture.board(tid)
                assert fixture.call(f'/api/collaboration/topics/{tid}/reopen',dict(request_id=uuid.uuid4().hex,lifecycle_version=closed['lifecycle_version'])).status_code == 201
                material.get_by_role('button', name='刷新材料状态', exact=True).click()
                expect(upload.get_by_role('button', name='保存新版本',exact=True)).to_be_enabled()
                # Authoritative unreadable response removes every cached series, preserving own drafts.
                page.route('**/handoffs',lambda route:route.fulfill(status=403,json={'error':'合成材料失权'}))
                material.get_by_role('button', name='刷新材料状态',exact=True).click()
                expect(material.locator('[data-lineage-status]')).to_contain_text('合成材料失权')
                expect(page.locator('[data-reading-version]')).to_have_count(0)
                expect(page.locator('[data-action=handoff-select]')).to_have_count(0)
                expect(page.locator('.react-flow__node')).to_have_count(0)
                expect(upload.locator('[name=note]')).to_have_value('保留上传草稿')
                assert upload.locator('[name=file]').evaluate('e=>e.files[0].name') == 'draft.txt'
                page.unroute('**/handoffs')
                material.get_by_role('button', name='刷新材料状态',exact=True).click()
                expect(material.locator('[data-lineage-status]')).to_contain_text('已更新')
                expect(reading).to_contain_text('原件与意见')
                expect(material.locator('.react-flow__node')).to_have_count(6)
                # Late reads may not resurrect a departed page.
                held = []
                page.route('**/handoffs', lambda route: held.append(route))
                material.get_by_role('button', name='刷新材料状态', exact=True).click()
                expect(material.locator('[data-lineage-status]')).to_contain_text('正在读取')
                page.get_by_role('button',name='资料与档案',exact=True).click()
                page.locator('#desk-resources [data-id="library"]').click()
                for route in held:
                    route.fulfill(status=200,json=fixture.board(tid))
                page.unroute('**/handoffs')
                expect(page.locator('[data-handoff-reading]')).to_have_count(0)
                policy_violations=verify_policy(page)
                assert not errors, errors
                result={'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'ok': True, 'url': base, 'evidence': str(root), 'errors': errors, 'screenshots': captures, 'native_zoom':2,'original_and_review_bytes':True,'draft_files_and_nodes_retained':True,'concurrent_review_target_retained':True,'narrow_keyboard_location_preserves_selection_focus_and_drafts':True}
                result.update(material_layout='fixed-version-groups',actual_event_nodes=5,material_elk_worker=False,policy_violations=policy_violations)
                (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(result, ensure_ascii=False))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


if __name__ == '__main__':
    main()
