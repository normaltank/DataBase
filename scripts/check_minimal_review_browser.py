"""#146 review regressions: isolated synthetic HTTP server and real Chromium."""
import argparse
import json
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from platform_app.web import create_app


class Quiet(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--case', choices=['s1', 'p1', 'p2', 'p3', 'all'], default='all')
    args = parser.parse_args()
    out = args.evidence.resolve()
    out.mkdir(parents=True, exist_ok=False)
    app = create_app(out/'synthetic-data', testing=True, embedded_worker=False)
    client = app.test_client()

    def post(path, data):
        response = client.post(path, json=data, headers={'X-CSRF-Token': client.get('/api/session').json['csrf']})
        assert response.status_code in (200, 201), response.json
        return response.json

    post('/api/login', {'username': 'admin', 'password': 'LocalDemo2026!'})
    source = post('/api/sources', {'name': '合成审查来源', 'kind': 'institution'})['id']
    ids = []
    for title, country in [('甲', 'Latvia'), ('乙', 'Germany')]:
        ids.append(post('/api/records', {'title': title, 'kind': 'report', 'source_id': source,
                                       'countries': country, 'body_html': '<p>合成正文。</p>'*30})['id'])
    post('/api/records', {'title': '其他来源', 'kind': 'report', 'countries': 'Germany'})
    server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
    assert server.server_port != 6430
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}/'
    result = {'base': base, 'worker': False, 'paid_calls': 0, 'checks': []}
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 960}, reduced_motion='reduce')
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base+'#library?feed=all')
            page.get_by_role('button', name='研究员', exact=True).click()
            expect(page.locator('.library-row')).to_have_count(3)

            if args.case in ('s1', 'all'):
                page.set_viewport_size({'width': 390, 'height': 844})
                button = page.locator('.library-row .title-button').filter(has_text='甲')
                expect(button).to_have_text('甲')
                result['short_title_height'] = button.bounding_box()['height']
                button.scroll_into_view_if_needed()
                page.screenshot(path=str(out/'short-title-390.png'))
                assert result['short_title_height'] >= 44, result
                button.click()
                expect(page.locator('.library-reader .detail-title')).to_have_text('甲')
                page.get_by_role('button', name='返回探索与结果', exact=True).click()
                result['checks'].append('S1: one-character title has >=44px target and opens the reader at 390px')
                page.set_viewport_size({'width': 1440, 'height': 960})

            if args.case in ('p1', 'all'):
                csrf = page.request.get(base+'api/session').json()['csrf']
                response = page.request.post(base+'api/saved-searches', data={'name': '合成竞态', 'conditions':
                    {'q': '合成正文', 'source': source, 'sort': 'title', 'feed': 'all'}},
                    headers={'X-CSRF-Token': csrf})
                assert response.status == 201, response.json()
                saved = response.json()
                page.goto(base+'#library?saved_search='+saved['id'])
                panel = page.locator('.material-discovery')
                expect(panel.locator('[data-material-globe] canvas')).to_be_visible()
                panel.locator('.material-country-list [data-material-country=LV]').click()
                expect(page.locator('.library-row')).to_have_count(1)
                held = []
                page.route('**/api/saved-searches/'+saved['id'], lambda route: held.append(route))
                page.go_back()
                expect(page).to_have_url(base+'#library?saved_search='+saved['id'])
                page.wait_for_function('true')
                assert held, 'Saved query request was not delayed'
                panel.locator('.material-country-list [data-material-country=DE]').click()
                query = parse_qs(urlsplit(page.url).fragment.split('?', 1)[1])
                result['race_url'] = page.url
                for route in held:
                    route.fulfill(response=route.fetch())
                page.unroute('**/api/saved-searches/'+saved['id'])
                assert query.get('q') == ['合成正文'] and query.get('source') == [source] and query.get('sort') == ['title'] and query.get('country') == ['DE'], query
                expect(page.locator('.library-row')).to_contain_text('乙')
                expect(page.locator('.library-row')).to_have_count(1)
                result['checks'].append('P1: country click during delayed saved resolution retains original source/sort, updates URL/results, and ignores late read')

            if args.case in ('p2', 'all'):
                page.goto(base+'#library?feed=new')
                panel = page.locator('.material-discovery')
                expect(panel.locator('[data-material-globe] canvas')).to_be_visible()
                canvas = panel.locator('[data-material-globe] canvas').element_handle()
                panel.locator('[data-material-scene=time]').click()
                expect(panel.locator('[data-material-timeline] canvas')).to_be_visible()
                panel.locator('[data-material-from]').fill('2018')
                panel.locator('[data-material-scene=country]').click()
                expect(panel.locator('[data-material-globe] canvas')).to_be_visible()
                canvas = panel.locator('[data-material-globe] canvas').element_handle()
                panel.locator('.material-country-list [data-material-country=LV]').click()
                expect(page.locator('.library-row')).to_have_count(1)
                batch_query = parse_qs(urlsplit(page.url).fragment.split('?', 1)[1])
                page.go_back()
                expect(page).to_have_url(base+'#library?feed=new')
                expect(page.locator('.library-row')).to_have_count(3)
                assert canvas.evaluate('(element)=>element.isConnected'), 'P2: new-feed history replaced the original canvas'
                expect(panel.locator('[data-material-from]')).to_have_value('2018')
                page.go_forward()
                expect(page.locator('.library-row')).to_have_count(1)
                assert canvas.evaluate('(element)=>element.isConnected')
                page.get_by_role('button', name='确认当前结果已浏览', exact=True).click()
                with page.expect_response('**/api/reading-batches/*/finish') as finished:
                    page.get_by_role('button', name='确认这 1 条已浏览', exact=True).click()
                response = finished.value
                assert response.status == 200 and response.json()['confirmed'] == 1, response.text()
                request = response.request.post_data_json
                assert request['conditions']['batch'] == batch_query['batch'][0], request
                assert request['conditions']['country'] == 'LV', request
                expect(page.locator('.library-row')).to_have_count(2)
                result['checks'].append('P2: new-feed back/forward retain canvas/year draft/batch; confirmation affects only LV and leaves excluded new records pending')

            if args.case in ('p3', 'all'):
                page.goto(base+'#library?feed=all')
                expect(page.locator('.library-row')).to_have_count(3)
                panel = page.locator('.material-discovery')
                expect(panel.locator('[data-material-globe] canvas')).to_be_visible()
                canvas = panel.locator('[data-material-globe] canvas').element_handle()
                page.goto(base+'#library?feed=all&country=Latvia')
                expect(page.locator('.library-row')).to_have_count(1)
                expect(panel.locator('.material-country-list [data-material-country=LV]')).to_have_attribute('aria-pressed', 'true')
                assert canvas.evaluate('(element)=>element.isConnected')
                parent=page.locator('.desk-progressive').filter(has=page.locator('[data-reading-filters]'))
                if parent.get_attribute('open') is None: parent.get_by_text('查找与筛选资料',exact=True).click()
                page.locator('.reading-more>summary').click()
                checkbox = page.locator('[data-reading-filters] input[name=country][value=LV]')
                expect(checkbox).to_be_checked()
                page.locator('[data-reading-filters]').get_by_role('button', name='查找', exact=True).click()
                expect(page.locator('.library-row')).to_have_count(1)
                expect(page.locator('.library-row')).to_contain_text('甲')
                query = parse_qs(urlsplit(page.url).fragment.split('?', 1)[1])
                assert query['country'] == ['LV'], query
                result['checks'].append('P3: legacy Latvia deep link updates LV checkbox in place; reapply preserves result and canonical country URL')

            assert not errors, errors
            browser.close()
    finally:
        result['page_errors'] = errors
        (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        server.shutdown()
        server.server_close()
        thread.join(5)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
