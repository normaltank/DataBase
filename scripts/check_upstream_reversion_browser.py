"""Current original after A/B/A, through synthetic public transport and Chromium."""
import argparse
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler
from tests.test_source_adapters import SourceAdapterTests, GSSC_LIST, GSSC_PAGE
from platform_app.automatic_processing import run_pending
from scripts.browser_camera import capture


class Quiet(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    fixture = SourceAdapterTests()
    fixture.setUp()
    report = {'synthetic': True, 'observations': [], 'errors': [], 'external_requests': []}
    server = None
    try:
        root = 'https://www.gssc.lt/en/'
        sid = fixture.source(root, 'institution')
        path = '/api/sources/' + sid + '/ingestion'
        fixture.call(path, {'enabled': True}, user='admin', method='PUT')
        for n, body in enumerate([GSSC_PAGE, GSSC_PAGE.replace('Actual synthetic policy body.', 'INTERMEDIATE B policy body.'), GSSC_PAGE]):
            if n:
                fixture.call(path + '/run', {}, user='admin')
            result, requests = fixture.worker(root, xml=GSSC_LIST, page=body, stamp=f'2026-11-{3+n*8:02}T12:00:00+00:00')
            run_pending(fixture.app.config['DATA_DIR'], limit=0)
            rid = fixture.clients['researcher'].get('/api/records').json['items'][0]['id']
            detail = fixture.clients['researcher'].get('/api/records/' + rid).json
            report['observations'].append({'worker': result, 'requests': requests,
                'latest': detail['automatic_acquisition']['upstream']['latest_snapshot_id'],
                'fulltext': detail['fulltext']['original']['text']})
        server = make_server('127.0.0.1', 0, fixture.app, threaded=True, request_handler=Quiet)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1366, 'height': 900}, reduced_motion='reduce')
            context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(base) else (report['external_requests'].append(r.request.url), r.abort())[-1])
            page = context.new_page()
            page.on('pageerror', lambda error: report['errors'].append(str(error)))
            page.goto(base)
            page.get_by_label('账号', exact=True).fill('researcher')
            page.get_by_label('密码', exact=True).fill('LocalDemo2026!')
            page.get_by_role('button', name='查看资料', exact=True).click()
            page.goto(base + '/#library?feed=all')
            page.locator(f'[data-action="detail"][data-id="{rid}"]').first.click()
            page.locator('.ux-acquisition > summary').click()
            snapshots = page.locator('.acquisition-reading > details[open]')
            expect(snapshots).to_have_count(1)
            snapshots.locator('.reading-content').scroll_into_view_if_needed()
            report['opened_original'] = snapshots.locator('.reading-content').inner_text()
            # Preserve the red frame before asserting its current version.
            capture(page, args.out / 'current-original.png', top=False)
            assert 'Actual synthetic policy body.' in report['opened_original'], report['opened_original']
            assert 'INTERMEDIATE B' not in report['opened_original'], report['opened_original']
            expect(page.locator('.acquisition-reading > details')).to_have_count(3)
            assert not report['errors'], report['errors']
            assert not report['external_requests'], report['external_requests']
            report['browser_version'] = browser.version
            report['ok'] = True
            browser.close()
    finally:
        if server:
            server.shutdown()
        fixture.doCleanups()
        (args.out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'opened_original': report['opened_original']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
