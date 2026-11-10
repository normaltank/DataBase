"""#144 public HTTP + ordinary Chromium, isolated synthetic data and no providers."""
import argparse
from email import message_from_bytes
import json
import logging
from pathlib import Path
import shutil
import sys
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from platform_app.web import create_app
from tests.test_topic_handoffs import HandoffTests
from live_flow_browser_policy import install as strict_policy, verify as verify_policy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    evidence = Path(args.evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    data = evidence / 'synthetic-data'
    captures, errors, checks = [], [], {}
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    # No test action can reach a paid or real external provider.
    with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Unexpected external provider')):
        fixture = HandoffTests()
        fixture.app = create_app(data, testing=True, embedded_worker=False)
        fixture.clients = {name: fixture.login(name) for name in ('researcher', 'colleague', 'admin')}
        tid = fixture.topic(theme='合成 · 区域政策编译协作与材料交接')
        material_id = fixture.upload(tid, who='colleague', title='合成 · 长题名政策研究材料与来源依据').json['material_ref']
        sid = fixture.call('/api/sources', {'name': '合成 · Baltic Policy Research Institute 区域政策研究所', 'kind': 'institution', 'country': 'Latvia'}).json['id']
        fixture.call('/api/people', {'name': 'Alexandra Synthetic · 亚历山德拉合成作者', 'original_name': 'Alexandra Synthetic', 'change_note': '合成浏览器验收'})
        for index in range(4):
            result = fixture.call('/api/records', {'title': f'合成对象资料 {index+1} · 区域政策与可追溯研究证据', 'kind': 'report', 'source_id': sid, 'body_html': '<p>完全合成的研究材料。<a href="https://example.org/basis">原文依据链接</a></p>', 'published_on': '2026-10-01'})
            assert result.status_code == 201, result.json
        server = make_server('127.0.0.1', 0, fixture.app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={'width': 1366, 'height': 900}, reduced_motion='reduce')
                    strict_policy(page)
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base + '/#library?feed=all&q=合成对象资料')
                    page.get_by_role('button', name='研究员', exact=True).click()
                    rows = page.locator('.library-row')
                    expect(rows).to_have_count(4)
                    more = rows.first.get_by_role('button', name='更多资料操作', exact=True)
                    more.focus();page.keyboard.press('Shift+F10')
                    menu = page.get_by_role('menu', name='对象操作')
                    expect(menu).to_be_visible()
                    expect(menu.get_by_role('menuitem', name='阅读资料', exact=True)).to_be_focused()
                    page.keyboard.press('ArrowDown')
                    expect(menu.get_by_role('menuitem', name='收藏资料', exact=True)).to_be_focused()
                    page.keyboard.press('Escape');expect(more).to_be_focused()
                    rows.first.locator('.library-row-source').click(button='right')
                    expect(menu).to_be_visible()
                    menu.get_by_role('menuitem', name='收藏资料', exact=True).click()
                    expect(page.locator('#toast')).to_contain_text('已加入我的收藏')
                    more.click();expect(menu.get_by_role('menuitem', name='取消收藏', exact=True)).to_be_visible()
                    menu.get_by_role('menuitem', name='选择用于比较', exact=True).click()
                    rows.nth(1).get_by_role('button', name='更多资料操作').click()
                    menu.get_by_role('menuitem', name='选择用于比较', exact=True).click()
                    more.click();menu.get_by_role('menuitem', name='比较已选 2 篇', exact=True).click()
                    expect(page.get_by_role('region', name='资料比较', exact=True)).to_be_visible()
                    page.get_by_role('button', name='关闭比较', exact=True).click()
                    checks['record_keyboard_favorite_comparison'] = True
                    page.goto(base + '/#sources?q=合成')
                    source = page.locator('.workbench-source-row').first
                    expect(source).to_be_visible()
                    assert not page.evaluate('clientHasDraft()'), 'Applied search is not an unsaved draft'
                    source.locator('h2 a').click(button='right');expect(menu).to_have_count(0)
                    source.locator('.workbench-source-meta span').first.evaluate('e=>{const range=document.createRange();range.selectNodeContents(e);const s=getSelection();s.removeAllRanges();s.addRange(range)}')
                    source.locator('.workbench-source-meta span').first.click(button='right');expect(menu).to_have_count(0)
                    page.evaluate('getSelection().removeAllRanges()')
                    checks['native_links_and_selected_text'] = True
                    for width in [1366, 1280, 515, 390, 320]:
                        page.set_viewport_size({'width': width, 'height': 900 if width > 700 else 844})
                        page.evaluate('scrollTo(0,0)')
                        button = source.get_by_role('button', name='更多来源操作')
                        button.click()
                        box = menu.bounding_box()
                        assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1, box
                        assert box['y'] >= 0 and box['y'] + box['height'] <= page.viewport_size['height'] + 1, box
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
                        expect(page.locator('#toast')).to_have_css('opacity','0',timeout=7000)
                        page.screenshot(path=str(evidence / f'sources-menu-{width}.png'))
                        captures.append(f'sources-menu-{width}.png')
                        page.keyboard.press('Escape')
                    checks['five_widths_menu_edges'] = True
                    page.set_viewport_size({'width': 1366, 'height': 900})
                    source.locator('h2 a').click()
                    page.get_by_text('编辑与历史', exact=True).click()
                    page.get_by_role('button', name='编辑来源', exact=True).click()
                    expect(page.locator('[data-form=source] [name=name]')).not_to_have_value('')
                    assert not page.evaluate('clientHasDraft()'), 'Loaded nonempty source fields are unchanged'
                    page.get_by_role('button',name='关闭',exact=True).first.click()
                    checks['unchanged_nonempty_fields_not_dirty'] = True
                    page.goto(base + f'/#collaboration?id={tid}&tab=selection')
                    material = page.locator(f'[data-material-ref="{material_id}"]')
                    node = material.locator('.react-flow__node').filter(has_text='当前版 1')
                    expect(node.get_by_role('button', name='通过', exact=True)).to_be_visible()
                    expect(page.locator('.workbench-detail-meta')).to_contain_text('当前身份：负责人 · 负责人：')
                    for width in [1366,1280,515,390,320]:
                        page.set_viewport_size({'width':width,'height':900 if width>700 else 844})
                        node.get_by_role('button',name='更多节点操作').click()
                        expect(menu).to_be_visible()
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                        page.screenshot(path=str(evidence/f'material-menu-{width}.png'));captures.append(f'material-menu-{width}.png')
                        page.keyboard.press('Escape')
                    page.set_viewport_size({'width':1366,'height':900})
                    node.get_by_role('button', name='更多节点操作').click()
                    menu.get_by_role('menuitem', name='意见/附件', exact=True).click()
                    form = material.locator('[data-form=handoff-review]')
                    expect(form.locator('[name=note]')).to_be_focused()
                    form.locator('[name=note]').fill('必须保留的原版本意见')
                    form.locator('[name=file]').set_input_files({'name': 'evidence.txt', 'mimeType': 'text/plain', 'buffer': b'SYNTHETIC FILE'})
                    # The external revision detector offers once and never auto-refreshes.
                    page.route('**/api/client-revision', lambda route: route.fulfill(json={'revision': 'new-synthetic-version'}))
                    page.evaluate('dispatchEvent(new Event("focus"))')
                    update = page.get_by_role('button', name='更新页面', exact=True)
                    expect(update).to_be_visible()
                    update.click()
                    expect(page.locator('#toast')).to_contain_text('未提交')
                    expect(form.locator('[name=note]')).to_have_value('必须保留的原版本意见')
                    assert form.locator('[name=file]').evaluate('e=>e.files[0].name') == 'evidence.txt'
                    checks['update_keeps_file_and_note'] = True
                    attempts = []
                    def unknown(route):
                        req = route.request
                        message = message_from_bytes(('Content-Type: ' + req.headers['content-type'] + '\r\n\r\n').encode() + req.post_data_buffer)
                        attempts.append([(part.get_param('name', header='content-disposition'), part.get_filename(), part.get_payload(decode=True)) for part in message.walk() if part.get_content_disposition() == 'form-data'])
                        if len(attempts) == 1:
                            response = route.fetch();assert response.status == 201
                            route.abort('failed')
                        else:
                            route.continue_()
                    page.route('**/handoff-reviews', unknown)
                    node.get_by_role('button', name='更多节点操作').click()
                    menu.get_by_role('menuitem', name='退回', exact=True).click()
                    expect(form.locator('.form-error')).to_contain_text('重试')
                    node.get_by_role('button', name='更多节点操作').click()
                    expect(menu.get_by_role('menuitem', name='通过此版')).to_have_attribute('aria-disabled', 'true')
                    menu.get_by_role('menuitem', name='退回', exact=True).click()
                    expect(material.locator(':scope>.between>.badge')).to_have_text('当前版 1 · 退回')
                    assert len(attempts) == 2 and attempts[0] == attempts[1]
                    checks['menu_unknown_original_request'] = True
                    expect(node.get_by_role('button', name='通过', exact=True)).to_have_count(0)
                    page.route('**/handoffs', lambda route: route.fulfill(status=403, json={'error':'合成撤权'}))
                    node.get_by_role('button', name='更多节点操作').click();expect(menu).to_be_visible()
                    material.get_by_role('button', name='刷新材料状态').click();expect(menu).to_have_count(0)
                    checks['revocation_closes_menu'] = True
                    checks['policy'] = verify_policy(page)
                    fallback=browser.new_page(viewport={'width':1280,'height':900})
                    strict_policy(fallback)
                    held=[]
                    fallback.route('**/static/vendor/visual/flow.js*',lambda route:held.append(route))
                    fallback.route('**/api/client-revision',lambda route:route.fulfill(json={'revision':'synthetic-next-version'}))
                    fallback.goto(base+f'/#collaboration?id={tid}&tab=selection')
                    fallback.get_by_role('button',name='研究员',exact=True).click()
                    upload=fallback.locator('.handoff-materials>.handoff-upload')
                    upload.locator('summary').click()
                    upload.locator('[name=note]').fill('模块更新失败仍保留输入')
                    upload.locator('[name=file]').set_input_files({'name':'pending.txt','mimeType':'text/plain','buffer':b'KEEP ORIGINAL FILE'})
                    expect(fallback.locator('[data-flow-status]')).to_contain_text('正在')
                    assert held
                    held.pop().fulfill(status=409,json={'error':'页面版本已更新'})
                    expect(fallback.locator('[data-flow-status]')).to_contain_text('未能加载')
                    fallback.get_by_role('button',name='更新页面',exact=True).click()
                    expect(upload.locator('[name=note]')).to_have_value('模块更新失败仍保留输入')
                    assert upload.locator('[name=file]').evaluate('e=>e.files[0].name')=='pending.txt'
                    checks['old_revision_lazy_failure_visible_update_keeps_file']=True
                    fallback.close()
                    assert not errors, errors
                finally:
                    browser.close()
                # Separate portable browser verifies authenticated identity return.
                portable_app = create_app(evidence / 'portable-synthetic', testing=True, embedded_worker=False, portable_trial=True)
                portable_server = make_server('127.0.0.1', 0, portable_app, threaded=True)
                portable_thread = threading.Thread(target=portable_server.serve_forever, daemon=True);portable_thread.start()
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={'width':1280,'height':900})
                    page.goto(f'http://127.0.0.1:{portable_server.server_port}/#library?feed=all&q=原位置')
                    expect(page.locator('.workbench-account-link')).to_be_visible()
                    identity = page.request.get(f'http://127.0.0.1:{portable_server.server_port}/api/session').json()['user']['id']
                    page.goto(f'http://127.0.0.1:{portable_server.server_port}/#collaboration')
                    page.get_by_role('button', name='主机本机维护', exact=True).click()
                    expect(page.locator('.workbench-account-link[data-id=personal]')).to_have_text('本机维护')
                    page.screenshot(path=str(evidence/'portable-return-1280.png'));captures.append('portable-return-1280.png')
                    page.set_viewport_size({'width':320,'height':844})
                    page.get_by_role('button',name='打开导航',exact=True).click()
                    page.screenshot(path=str(evidence/'portable-return-320.png'));captures.append('portable-return-320.png')
                    page.get_by_role('button', name='返回研究身份', exact=True).click()
                    expect(page.locator('.workbench-account-link[data-id=personal]')).to_contain_text('临时研究员')
                    assert page.request.get(f'http://127.0.0.1:{portable_server.server_port}/api/session').json()['user']['id'] == identity
                    assert '#collaboration' in page.url
                    checks['portable_same_identity_route'] = True
                finally:
                    browser.close();portable_server.shutdown();portable_server.server_close();portable_thread.join(5)
        finally:
            server.shutdown();server.server_close();thread.join(5)
            (evidence / 'result.json').write_text(json.dumps({'checks': checks, 'captures':captures, 'errors':errors, 'worker_enabled':False, 'paid_calls':0, 'base':base}, ensure_ascii=False, indent=2), encoding='utf-8')
            assert data.parent == evidence and data.name == 'synthetic-data'
            if data.exists():shutil.rmtree(data)


if __name__ == '__main__':
    main()
