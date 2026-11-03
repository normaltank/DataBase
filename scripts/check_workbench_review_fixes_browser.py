"""Focused workbench regressions with fresh synthetic data and real Chromium.

Run --reproduce on the reviewed baseline to record the missing final and small
touch targets. Normal mode verifies final downloads, immutable adoptions, record
permissions and actual 390px/200% layout. No ingestion or AI worker is started.
"""
import argparse
import json
import logging
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from platform_app.web import create_app
from scripts.check_collaboration_browser import login, no_overflow
from scripts.check_collaboration_recovery import login as account
from scripts.check_topic_finals_browser import call, serve


def target(locator):
    expect(locator).to_be_visible()
    result = locator.evaluate("el=>{const r=el.getBoundingClientRect();return {label:el.textContent.trim()||el.ariaLabel||el.placeholder,width:r.width,height:r.height,left:r.left,right:r.right,viewport:document.documentElement.clientWidth}}")
    assert result['left'] >= -1 and result['right'] <= result['viewport'] + 1, result
    return result


def download(page, locator, raw):
    with page.expect_download() as event:
        locator.click()
    assert Path(event.value.path()).read_bytes() == raw


def main():
    expect.set_options(timeout=15000)
    parser = argparse.ArgumentParser()
    parser.add_argument('--reproduce', action='store_true')
    parser.add_argument('--evidence', type=Path, default=Path('/tmp/zhihui-independent-fix-evidence'))
    args = parser.parse_args()
    evidence = args.evidence
    evidence.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='baseline-' if args.reproduce else 'verified-', dir=evidence))
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app = create_app(run / 'data', testing=True)
    lead, author, admin = [account(app, name) for name in ('researcher', 'colleague', 'admin')]
    response = admin.put('/api/collaboration/qualifications/researcher', json={'version': 0, 'enabled': True}, headers={'X-CSRF-Token': admin.get('/api/session').json['csrf']})
    assert response.status_code == 200
    observer = call(admin, '/api/members', {'username': 'observer', 'name': '合成只读同伴', 'password': 'LocalDemo2026!', 'role': 'researcher'})
    tid = call(lead, '/api/collaboration/topics', {'theme': '独立返修验收 · 单篇成果与汇总', 'participant_ids': ['colleague', observer['id']]})['id']
    basepath = f'/api/collaboration/topics/{tid}'
    title = '能源研究与区域合作：' + '跨国政策资料与译稿' * 7
    call(lead, basepath + '/meetings', {'version': 0, 'topic_version': 1, 'request_id': 'review-fix-meeting', 'assignments': [{'title': title, 'author_id': 'colleague', 'country': '拉脱维亚'}]})
    call(lead, basepath + '/enter-compilation', {'topic_version': 1, 'stage_version': 1, 'meeting_version': 1, 'request_id': 'review-fix-enter'})
    aid = author.get(basepath + '/workflow').json['assignments'][0]['id']
    originals = [b'synthetic confirmed manuscript v1', b'synthetic confirmed manuscript v2', b'synthetic pending manuscript v3']

    def draft(version):
        return call(author, basepath + f'/assignments/{aid}/submissions', {'version': version - 1, 'topic_version': 1, 'meeting_version': 1, 'request_id': f'review-fix-draft-{version}'}, originals[version - 1])['id']

    def final(version):
        return call(lead, basepath + f'/assignments/{aid}/finals', {'version': version, 'submission_id': draft(version), 'topic_version': 1, 'meeting_version': 1, 'request_id': f'review-fix-final-{version}', 'status': 'pending', 'note': '已核对具体原件'})

    final(1)
    f1 = author.get(basepath + '/workflow').json['assignments'][0]['finals'][0]
    for index in range(2):
        call(author, '/api/records', {'kind': 'report', 'title': f'合成阅读资料 {index + 1}', 'body_html': '<p>可核对的合成正文。</p>', 'visibility': 'shared', 'sharing_confirmed': True})
    extension = run / 'zoom-extension'
    extension.mkdir()
    (extension / 'manifest.json').write_text(json.dumps({'manifest_version': 3, 'name': 'Local zoom check', 'version': '1.0', 'permissions': ['tabs'], 'background': {'service_worker': 'worker.js'}}))
    (extension / 'worker.js').write_text('chrome.runtime.onInstalled.addListener(() => {});')
    server, thread, base = serve(app)
    result = {'run': str(run), 'targets': [], 'layouts': [], 'page_errors': []}
    try:
        with sync_playwright() as p:
            executable = os.environ.get('DATABASE_BROWSER_EXECUTABLE')
            context = p.chromium.launch_persistent_context(str(run / 'profile'), headless=False,
                **({'executable_path': executable} if executable else {}), ignore_default_args=['--disable-extensions'],
                args=['--headless=new', f'--disable-extensions-except={extension}', f'--load-extension={extension}'],
                viewport={'width': 1366, 'height': 900}, accept_downloads=True)
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page = context.pages[0]
            page.on('pageerror', lambda error: result['page_errors'].append(str(error)))
            login(page, base, 'researcher')

            def products():
                page.goto(base + f'/#collaboration?id={tid}&tab=products')
                expect(page.get_by_role('heading', name='整期汇总与采用版本', exact=True)).to_be_visible()

            def snapshot(name):
                page.evaluate('window.scrollTo({top:0,left:0,behavior:"instant"})')
                page.wait_for_function('scrollY === 0')
                result['layouts'].append({'name': name, **no_overflow(page)})
                page.screenshot(path=str(evidence / (name + '.png')), full_page=True)

            products()
            if args.reproduce:
                result['missing_single_final'] = page.get_by_role('heading', name=title, exact=True).count() == 0
                assert result['missing_single_final'], 'Expected baseline to lack the final title'
                expect(page.get_by_text('尚未提交整期汇总；已确认的各篇定稿仍可独立查阅。', exact=True)).to_be_visible()
                snapshot('before-products-desktop')
            else:
                single = page.locator('[data-topic-single-finals]')
                expect(single.get_by_role('heading', name=title, exact=True)).to_be_visible()
                expect(single.get_by_text('负责作者：', exact=False)).to_contain_text(f1['author_name'])
                expect(single.get_by_role('heading', name='定稿 v1', exact=False)).to_be_visible()
                download(page, single.get_by_role('link', name='下载定稿 v1', exact=True), originals[0])
                single.get_by_role('button', name='查看成果', exact=False).click()
                expect(page.get_by_role('dialog').get_by_role('heading', name='编译工作与成果原件', exact=True)).to_be_visible()
                page.keyboard.press('Escape')
                snapshot('products-only-single-desktop')

            page.set_viewport_size({'width': 390, 'height': 844})
            products()
            result['targets'].append(target(page.locator('[data-action="workbench-back"]')))
            snapshot('before-products-phone' if args.reproduce else 'products-only-single-phone')
            page.goto(base + '/#collaboration')
            expect(page.get_by_role('heading', name='编译协作', exact=True)).to_be_visible()
            for selector in ['.navigation-toggle', '.workbench-account [data-action="logout"]', '.workbench-new>summary', '.workbench-search input', '.workbench-search .button', '[data-workbench-business]']:
                result['targets'].append(target(page.locator(selector)))
            snapshot('before-work-phone' if args.reproduce else 'work-phone')
            if not args.reproduce:
                menu = page.locator('.workbench-new')
                menu.locator('summary').click()
                gap = menu.evaluate('el=>el.querySelector(".stack").getBoundingClientRect().top-el.querySelector("summary").getBoundingClientRect().bottom')
                assert gap >= 4, gap
                for button in menu.locator('.stack .button').all():
                    result['targets'].append(target(button))
                snapshot('work-actions-phone')
                menu.locator('summary').click()
            page.get_by_role('button', name='打开导航', exact=True).click()
            result['targets'].append(target(page.get_by_role('button', name='关闭导航', exact=True)))
            snapshot('before-navigation-phone' if args.reproduce else 'navigation-phone')
            page.get_by_role('button', name='关闭导航', exact=True).click()
            page.goto(base + '/#library?feed=all')
            page.locator('.record-title button').first.click()
            reader = page.locator('.library-reader')
            expect(reader.locator('.library-reader-body')).not_to_be_empty()
            for action in ['close', 'prev', 'next']:
                result['targets'].append(target(reader.locator(f'[data-action="library-reader-{action}"]')))
            snapshot('before-reading-phone' if args.reproduce else 'reading-phone')
            if args.reproduce:
                result['undersized_targets'] = [r for r in result['targets'] if min(r['width'], r['height']) < 44]
                assert len(result['undersized_targets']) >= 7, result['targets']
            else:
                assert all(min(r['width'], r['height']) >= 44 for r in result['targets']), result['targets']
                # A newer confirmed final and a subsequent unconfirmed draft must
                # not rewrite the existing summary's chosen v1 or enter products.
                call(author, basepath + '/summaries', {'request_id': 'review-fix-summary', 'topic_version': 1, 'version': 0, 'author_id': 'colleague', 'final_ids': [f1['id']]}, b'synthetic summary adopting v1')
                final(2)
                draft(3)
                for width, zoom in [(1366, 1), (390, 1), (1366, 2)]:
                    page.set_viewport_size({'width': width, 'height': 900})
                    worker.evaluate("async ({url,zoom})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,zoom)}", {'url': base, 'zoom': zoom})
                    assert worker.evaluate("async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));return chrome.tabs.getZoom(t.id)}", base) == zoom
                    products()
                    single = page.locator('[data-topic-single-finals]')
                    expect(single.get_by_role('heading', name='定稿 v2', exact=False)).to_be_visible()
                    assert single.get_by_role('heading', name='定稿 v3', exact=False).count() == 0
                    download(page, single.get_by_role('link', name='下载定稿 v2', exact=True), originals[1])
                    old = single.locator('details')
                    old.locator('summary').click()
                    download(page, old.get_by_role('link', name='下载定稿 v1', exact=True), originals[0])
                    adopted = page.locator('[data-summary-card]')
                    expect(adopted.get_by_role('heading', name='整期汇总 v1', exact=True)).to_be_visible()
                    adopted.get_by_text('核对采用的 1 篇具体定稿版本', exact=True).click()
                    expect(adopted.get_by_role('heading', name=title + ' · 定稿 v1', exact=True)).to_be_visible()
                    download(page, adopted.get_by_role('link', name='下载所采用的定稿 v1', exact=True), originals[0])
                    snapshot(f'products-with-summary-{width}-zoom{zoom}')
                # A fellow participant may inspect work originals but receives no private
                # record projection; the UI must preserve that distinction.
                worker.evaluate("async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,1)}", base)
                page.get_by_role('button', name='退出登录', exact=True).click()
                page.get_by_label('账号', exact=True).fill('observer')
                page.get_by_label('密码', exact=True).fill('LocalDemo2026!')
                page.get_by_role('button', name='查看资料', exact=True).click()
                page.goto(base + f'/#collaboration?id={tid}&tab=products')
                single = page.locator('[data-topic-single-finals]')
                expect(single).to_be_visible()
                assert single.get_by_role('button', name='查看成果', exact=False).count() == 0
                expect(single.get_by_text('成果正文依原有授权查看；工作原件可在本期下载。', exact=True).first).to_be_visible()
                download(page, single.get_by_role('link', name='下载定稿 v2', exact=True), originals[1])
                result['verified'] = ['single final without summary', 'readable record entry', 'exact final downloads', 'pending draft excluded', 'old final retained', 'summary still adopts v1', 'private record permissions', '390px touch targets', 'real 200% browser zoom']
            assert not result['page_errors'], result['page_errors']
            context.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        (evidence / ('reproduction.json' if args.reproduce else 'verification.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
