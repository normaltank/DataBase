"""Public HTTP/browser regression for #153. Fresh synthetic data, no external I/O."""
import argparse
import base64
import hashlib
import io
import json
import logging
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_app.web import create_app
from portable.demo_seed import login, call, seed, txt
from werkzeug.serving import make_server


def capture(page, path, native_zoom=False):
    """Capture the actual viewport; older Chromium full-page capture changes layout."""
    page.evaluate('scrollTo(0,0)')
    page.wait_for_timeout(300)
    cdp = page.context.new_cdp_session(page)
    metrics = cdp.send('Page.getLayoutMetrics')
    options = {'format': 'png', 'fromSurface': True, 'captureBeyondViewport': False}
    path.write_bytes(base64.b64decode(cdp.send('Page.captureScreenshot', options)['data']))
    path.with_suffix('.metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    cdp.detach()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--red', action='store_true')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--fixture', type=Path, help='Reuse an existing isolated synthetic fixture without reseeding')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    fixture_root = args.fixture or args.out
    app = create_app(fixture_root / 'data', testing=True, embedded_worker=False)
    if not (fixture_root / 'fixture.json').exists():
        seed(app)
        client = login(app, 'researcher')
        name = '演示｜长题名国际社会与区域研究评论 International Review of Fictional Regional Studies'
        journal = call(client, '/api/sources', {'name': name, 'kind': 'journal'})
        from PIL import Image
        picture = io.BytesIO()
        Image.new('RGB', (120, 160), '#29487a').save(picture, format='PNG')
        uploaded = call(client, '/api/journals/' + journal['id'] + '/covers', file=('synthetic-cover.png', picture.getvalue()))
        call(client, '/api/journals/' + journal['id'] + '/profile', {'version': 0, 'cover': {
            'file_id': uploaded['id'], 'evidence': 'Program-created fictional cover for bookshelf regression.',
            'illustrative': True, 'note': 'Synthetic image; not an original issue or result.'}}, method='PUT')
        results = []
        content = txt('虚构成果.txt', '完全虚构的书架验收原件；不是研究材料。')
        for i, (year, issue) in enumerate([(2026, '第1—2期'), (2025, '特刊：青年与地方文化'), (2026, '第3期')]):
            results.append(call(client, '/api/journal-results', {'journal_name': name, 'journal_id': journal['id'], 'year': year, 'issue': issue, 'request_id': f'shelf-result-{i}'}, file=content))
        fixture = {'journal': journal['id'], 'results': [r['id'] for r in results], 'sha256': hashlib.sha256(content[1]).hexdigest()}
        (fixture_root / 'fixture.json').write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
    server = make_server('127.0.0.1', 0, app, threaded=True)
    base = f'http://127.0.0.1:{server.server_port}'
    print(json.dumps({'url': base, 'synthetic': True}), flush=True)
    if args.serve:
        server.serve_forever()
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    from playwright.sync_api import sync_playwright, expect
    errors = []
    report = {'synthetic': True, 'external_requests': [], 'checks': []}
    try:
        with sync_playwright() as p:
            extension = args.out / 'zoom-extension'
            extension.mkdir(exist_ok=True)
            (extension / 'manifest.json').write_text(json.dumps({'manifest_version': 3, 'name': 'Synthetic bookshelf zoom', 'version': '1.0', 'permissions': ['tabs'], 'background': {'service_worker': 'worker.js'}}))
            (extension / 'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
            browser = p.chromium.launch_persistent_context(str(args.out / 'browser-profile'), executable_path=p.chromium.executable_path, headless=False, ignore_default_args=['--disable-extensions'], args=['--headless=new', f'--disable-extensions-except={extension}', f'--load-extension={extension}'], viewport={'width': 1366, 'height': 768}, has_touch=True)
            page = browser.pages[0]
            browser.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base) else (report['external_requests'].append(route.request.url), route.abort())[-1])
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base)
            page.get_by_label('账号', exact=True).fill('researcher')
            page.get_by_label('密码', exact=True).fill('LocalDemo2026!')
            page.get_by_role('button', name='查看资料', exact=True).click()
            fixture = json.loads((fixture_root / 'fixture.json').read_text(encoding='utf-8'))
            selected_hash = '/#journal-results?shelf_journal=id:' + fixture['journal']
            page.goto(base + selected_hash)
            expect(page.get_by_role('heading', name='期刊成果', exact=True)).to_be_visible()
            if args.red:
                capture(page, args.out / 'before.png')
            expect(page.get_by_role('button', name='书架', exact=True)).to_be_visible()
            expect(page.locator('[data-bookshelf-view="shelf"]')).to_be_visible()
            shelf = page.locator('[data-bookshelf-view="shelf"] [data-book-id]').evaluate_all('(els)=>els.map(e=>e.dataset.bookId).sort()')
            page.get_by_role('button', name='列表', exact=True).click()
            expect(page.locator('[data-bookshelf-view="list"]')).to_be_visible()
            rows = page.locator('[data-jr-list] [data-jr-row]').evaluate_all('(els)=>els.map(e=>e.dataset.jrRow).sort()')
            assert shelf == rows and len(rows) == 2, (shelf, rows)
            page.reload()
            expect(page.locator('[data-bookshelf-view="list"]')).to_be_visible()
            page.get_by_role('button', name='书架', exact=True).click()
            page.wait_for_timeout(300)
            capture(page, args.out / 'journal-1366.png')
            for width in (390, 320):
                page.set_viewport_size({'width': width, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1')
                capture(page, args.out / f'journal-{width}.png')
            page.set_viewport_size({'width': 1366, 'height': 768})
            page.goto(base + '/#compilations')
            expect(page.locator('[data-bookshelf="center"]')).to_be_visible()
            capture(page, args.out / 'center-1366.png')
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1'), 'center phone overflow'
            capture(page, args.out / 'center-390.png')
            page.goto(base + '/#sources?group=journal')
            expect(page.locator('[data-bookshelf="sources"]')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1'), 'sources phone overflow'
            capture(page, args.out / 'sources-390.png')
            first_source=page.locator('[data-bookshelf-view="shelf"] [data-book-id]').first.bounding_box()
            assert first_source['y']+first_source['height'] <= 844, first_source
            report['source_first_viewport']=first_source
            page.set_viewport_size({'width':320,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1')
            capture(page,args.out / 'sources-320.png')
            page.set_viewport_size({'width': 1366, 'height': 768})
            capture(page, args.out / 'sources-1366.png')
            page.set_viewport_size({'width':390,'height':844})
            page.get_by_label('刊名分区', exact=True).select_option('other')
            expect(page.get_by_label('刊名分区', exact=True)).to_have_value('other')
            page.set_viewport_size({'width':1366,'height':768})
            page.locator('[data-bookshelf-select="letters"][data-value="other"]').click()
            expect(page.locator('[data-bookshelf-select="letters"][data-value="other"]')).to_have_attribute('aria-pressed','true')
            source_ids = page.locator('[data-bookshelf-view="shelf"] [data-book-id]').evaluate_all('(els)=>els.map(e=>e.dataset.bookId).sort()')
            page.get_by_role('button', name='列表', exact=True).click()
            assert source_ids == page.locator('[data-bookshelf-view="list"] [data-object-id]').evaluate_all('(els)=>els.map(e=>e.dataset.objectId).sort()')
            page.reload()
            expect(page.locator('[data-bookshelf-select="letters"][data-value="other"]')).to_have_attribute('aria-pressed','true')
            page.locator('.source-search input[name="q"]').fill('演示')
            page.get_by_role('button', name='查找来源', exact=True).click()
            expect(page.locator('[data-bookshelf-view="list"] [data-object-id]')).to_have_count(2)
            assert 'shelf_letters' not in page.url
            page.get_by_role('button', name='书架', exact=True).click()
            covered = page.locator(f'[data-book-id="{fixture["journal"]}"]')
            expect(covered.locator('[data-bookshelf-cover-image]')).to_be_visible()
            expect(covered).to_contain_text('示意图，不代表本期')
            cover_url = covered.locator('img').get_attribute('src')
            assert page.request.get(base + cover_url).status == 200
            covered.locator('a').click()
            expect(page.locator('[data-ja-source]')).to_be_visible()
            page.get_by_role('link', name='返回期刊目录', exact=True).click()
            expect(page.locator('[data-bookshelf="sources"]')).to_be_visible()
            expect(page.locator('.source-search input[name="q"]')).to_have_value('演示')
            # A saved local image must degrade to a labeled text cover on failure.
            page.route('**/api/journals/*/covers/*', lambda route: route.abort())
            page.reload()
            page.locator(f'[data-book-id="{fixture["journal"]}"] .bookshelf-open').scroll_into_view_if_needed()
            expect(page.locator(f'[data-book-id="{fixture["journal"]}"] [data-bookshelf-cover-image]')).to_have_count(0)
            expect(page.locator(f'[data-book-id="{fixture["journal"]}"]')).to_contain_text('文字封面 · 图片暂不可用')
            page.unroute('**/api/journals/*/covers/*')
            report['checks'].append('evidence-backed archive image, explicit illustrative use, image-failure text cover')
            report['checks'].append('source alphabet partitions use recorded title, list same subset, global search exits partition, real archive return and refresh')
            # Distinct domain objects: institutions never become journal books.
            page.goto(base + '/#sources?group=institution')
            expect(page.locator('[data-bookshelf="sources"]')).to_be_visible()
            expect(page.locator('[data-book-id]')).to_have_count(0)
            assert page.locator('[data-bookshelf-view="shelf"] .workbench-source-row').count() > 0
            report['checks'].append('institutions remain directory rows')
            # Shelf and list change in place, retaining unfinished search and nodes.
            page.goto(base + selected_hash)
            expect(page.locator('[data-bookshelf="journal-results"]')).to_be_visible()
            page.get_by_text('查找刊物与期次', exact=True).click()
            search = page.get_by_label('刊名、期次或文件名', exact=True)
            search.fill('尚未提交的查找条件')
            page.evaluate('window.testShelfInput=document.querySelector("[data-jr-search] input")')
            for name in ('列表', '书架', '列表', '书架'):
                page.get_by_role('button', name=name, exact=True).click()
            expect(search).to_have_value('尚未提交的查找条件')
            assert page.evaluate('window.testShelfInput===document.querySelector("[data-jr-search] input")')
            assert page.evaluate('localStorage.getItem("research-bookshelf-view")') == 'shelf'
            report['checks'].append('same query, same search node, unfinished conditions, quick toggles and preference')
            fixture = json.loads((fixture_root / 'fixture.json').read_text(encoding='utf-8'))
            book = page.locator(f'[data-book-id="{fixture["results"][0]}"] .bookshelf-open')
            book.focus()
            page.evaluate('scrollTo(0,280)')
            before_y = page.evaluate('scrollY')
            book.press('Enter')
            expect(page.locator('[data-jr-detail]')).to_be_visible()
            # The actual original URL and bytes are the same from either mode.
            with page.expect_download() as download:
                page.get_by_role('link', name='下载', exact=True).click()
            digest = hashlib.sha256(Path(download.value.path()).read_bytes()).hexdigest()
            assert digest == fixture['sha256']
            page.get_by_role('link', name='← 返回期刊成果', exact=True).click()
            expect(page.locator('[data-bookshelf="journal-results"]')).to_be_visible()
            expect(search).to_have_value('尚未提交的查找条件')
            after_y = page.evaluate('scrollY')
            assert abs(after_y - before_y) < 3, {'before': before_y, 'after': after_y}
            assert page.evaluate('document.activeElement.closest("[data-book-id]")?.dataset.bookId') == fixture['results'][0]
            page.get_by_role('button', name='列表', exact=True).tap()
            page.locator(f'[data-jr-row="{fixture["results"][0]}"] a').click()
            expect(page.locator('[data-jr-detail]')).to_be_visible()
            response = page.request.get(base + page.get_by_role('link', name='下载', exact=True).get_attribute('href'))
            assert hashlib.sha256(response.body()).hexdigest() == fixture['sha256']
            report['checks'].append('keyboard open, touch switch, exact original bytes in both views, explicit return scroll/focus/search')
            page.goto(base + selected_hash + '&shelf_year=2025')
            expect(page.locator('[data-jr-row]')).to_have_count(1)
            page.get_by_role('button', name='书架', exact=True).click()
            expect(page.locator('[data-book-id]')).to_have_count(1)
            page.goto(base + '/#journal-results?q=no-such-fictional-result')
            expect(page.locator('[data-book-id]')).to_have_count(0)
            expect(page.get_by_text('尚无匹配成果。可退出搜索或保存一期成果。', exact=True)).to_be_visible()
            report['checks'].append('year filter and zero results in both modes')
            # A fully authorized delayed response from an old route cannot repaint.
            stale = page.request.get(base + '/api/journal-results?year=2025').json()
            held = []
            pattern = '**/api/journal-results?year=2025'
            page.route(pattern, lambda route: held.append(route))
            page.evaluate('location.hash="#journal-results?year=2025"')
            page.wait_for_timeout(150)
            assert held
            page.evaluate('location.hash="#sources?group=institution"')
            expect(page.locator('[data-bookshelf="sources"]')).to_be_visible()
            held.pop().fulfill(status=200, content_type='application/json', body=json.dumps(stale))
            page.wait_for_timeout(200)
            expect(page.locator('[data-jr-row]')).to_have_count(0)
            page.unroute(pattern)
            report['checks'].append('late response isolated after route change')
            page.goto(base + '/#compilations')
            expect(page.locator('[data-bookshelf="center"]')).to_be_visible()
            expect(page.locator('[data-bookshelf-select="section"][data-value="journal"]')).to_have_attribute('aria-pressed','true')
            expect(page.locator('[data-book-id]')).to_have_count(0)
            page.locator('[data-bookshelf-select="journal"][data-value="id:' + fixture['journal'] + '"]').click()
            expect(page.locator('[data-book-id]')).to_have_count(2)
            capture(page, args.out / 'center-journal-selected-1366.png')
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1')
            capture(page, args.out / 'center-journal-selected-390.png')
            first_result=page.locator('[data-bookshelf-view="shelf"] [data-book-id]').first.bounding_box()
            assert first_result['y']+first_result['height'] <= 844, first_result
            report['center_first_viewport']=first_result
            page.set_viewport_size({'width':320,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1')
            capture(page,args.out / 'center-journal-selected-320.png')
            page.set_viewport_size({'width':1366,'height':768})
            shelf_ids = page.locator('[data-bookshelf-view="shelf"] [data-book-id]').evaluate_all('(els)=>els.map(e=>e.dataset.bookId).sort()')
            page.get_by_role('button', name='列表', exact=True).click()
            list_ids = page.locator('[data-jr-row]').evaluate_all('(els)=>els.map(e=>e.dataset.jrRow).sort()')
            assert shelf_ids == list_ids
            page.locator('[data-bookshelf-select="year"][data-value="2025"]').click()
            expect(page.locator('[data-jr-row]')).to_have_count(1)
            page.reload()
            expect(page.locator('[data-jr-row]')).to_have_count(1)
            page.locator('[data-bookshelf-select="section"][data-value="topic"]').click()
            expect(page.locator('.bookshelf-topics')).to_be_visible()
            expect(page.locator('[data-jr-row]')).to_have_count(0)
            page.get_by_role('button', name='书架', exact=True).click()
            topic = page.locator('.bookshelf-topics [data-business="topic"]').first
            topic_id = topic.get_attribute('data-id')
            topic.click()
            expect(page.locator(f'[data-collaboration-topic="{topic_id}"]')).to_be_visible()
            page.get_by_role('button', name='返回中心成果', exact=False).click()
            expect(page.locator('.bookshelf-topics')).to_be_visible()
            report['checks'].append('real business/journal/year partitions, same subset, refresh and topic return')
            page.locator('[data-bookshelf-search] input[name="q"]').fill('公共空间')
            page.get_by_role('button', name='搜索全部分区', exact=True).click()
            expect(page.locator('[data-bookshelf-select="section"][data-value="journal"]')).to_contain_text('0')
            expect(page.locator('[data-bookshelf-select="section"][data-value="topic"]')).to_contain_text('1')
            page.locator('[data-bookshelf-select="section"][data-value="topic"]').click()
            expect(page.locator('[data-book-id]')).to_have_count(1)
            page.get_by_role('button', name='退出搜索', exact=True).click()
            expect(page.locator('[data-bookshelf-select="section"][data-value="journal"]')).to_have_attribute('aria-pressed','true')
            report['checks'].append('center global query searches both business partitions and explicit search exit resets grouping')
            page.locator('[data-bookshelf-select="journal"][data-value="id:' + fixture['journal'] + '"]').click()
            expect(page.locator('[data-book-id]')).to_have_count(2)
            # Native browser 200% zoom, not CSS or device-scale emulation.
            zoom = browser.service_workers[0] if browser.service_workers else browser.wait_for_event('serviceworker')
            zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,2)}', base)
            actual = zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));return chrome.tabs.getZoom(t.id)}', base)
            assert actual == 2
            assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1')
            capture(page, args.out / 'center-native200.png', native_zoom=True)
            report['native_zoom'] = actual
            page.goto(base + '/#sources?group=journal')
            expect(page.locator('[data-bookshelf="sources"]')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1')
            capture(page,args.out / 'sources-native200.png', native_zoom=True)
            page.goto(base + selected_hash)
            expect(page.locator('[data-bookshelf="journal-results"]')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1')
            capture(page,args.out / 'journal-native200.png', native_zoom=True)
            page.goto(base + '/#compilations?shelf_journal=id:' + fixture['journal'])
            expect(page.locator('[data-bookshelf="center"]')).to_be_visible()
            zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,1)}', base)
            page.emulate_media(reduced_motion='reduce')
            page.get_by_role('button', name='列表', exact=True).click()
            assert page.locator('[data-bookshelf-view="list"]').first.is_visible()
            assert page.locator('[data-bookshelf-view="list"]').first.get_attribute('style') in (None, '')
            report['checks'].append('reduced motion direct final state')
            browser.set_offline(True)
            page.get_by_role('button', name='书架', exact=True).click()
            page.get_by_role('button', name='列表', exact=True).click()
            browser.set_offline(False)
            report['checks'].append('offline local view switching remains usable')
            # The local code bundle may fail: all native content and actions work.
            page.route('**/static/vendor/visual/desk-motion.js*', lambda route: route.abort())
            page.reload()
            expect(page.locator('[data-bookshelf="center"]')).to_be_visible()
            page.get_by_role('button', name='书架', exact=True).click()
            assert page.locator('[data-bookshelf-view="shelf"]').first.is_visible()
            report['checks'].append('motion module failure leaves shelf, list and real links usable')
            session = page.request.get(base + '/api/session').json()
            page.request.post(base + '/api/logout', data={}, headers={'X-CSRF-Token': session['csrf']})
            page.evaluate('location.hash="#journal-results"')
            expect(page.get_by_role('heading', name='登录', exact=True)).to_be_visible()
            expect(page.locator('[data-book-id]')).to_have_count(0)
            assert page.request.get(base + '/api/journal-results').status == 401
            assert page.request.get(base + '/api/journal-results/' + fixture['results'][0]).status == 401
            report['checks'].append('session access loss clears shelf and HTTP denies both collection and object')
            assert not errors, errors
            assert not report['external_requests'], report['external_requests']
            report['page_errors'] = errors
            report['ok'] = True
            (args.out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            browser.close()
    except Exception as exc:
        report['ok'] = False
        report['failure'] = str(exc)
        try:
            report['overflow'] = page.locator('body *').evaluate_all('(els)=>els.filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right})).slice(0,20)')
            capture(page, args.out / 'failure.png')
        except Exception:
            pass
        (args.out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        raise
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
