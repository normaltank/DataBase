"""Synthetic #43 acceptance at the real browser and authenticated HTTP seams."""
import json
import os
import shutil
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix='collection-scope-browser-'))
EVIDENCE.mkdir(parents=True, exist_ok=True)


def main():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    offline_server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(EVIDENCE)))
    Thread(target=offline_server.serve_forever, daemon=True).start()
    offline_url = f'http://127.0.0.1:{offline_server.server_port}'
    with tempfile.TemporaryDirectory(prefix='scope-browser-data-') as temp, (EVIDENCE / 'server.log').open('w') as server_log:
        server = subprocess.Popen([sys.executable, str(ROOT / 'app.py'), '--no-import', '--port', str(port), '--data-dir', temp], cwd=ROOT, stdout=server_log, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(url + '/health', timeout=.3).close()
                    break
                except OSError:
                    if server.poll() is not None:
                        raise RuntimeError('Synthetic server exited')
                    time.sleep(.1)
            with sync_playwright() as pw:
                browser_options = {}
                if os.environ.get('DATABASE_BROWSER_CHANNEL'):
                    browser_options['channel'] = os.environ['DATABASE_BROWSER_CHANNEL']
                elif shutil.which('chromium'):
                    browser_options.update(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
                browser = pw.chromium.launch(**browser_options)
                try:
                    for width in [1366, 390]:
                        context = browser.new_context(viewport={'width': width, 'height': 1000})
                        api = context.request
                        def call(path, data, method='POST', status=200):
                            csrf = api.get(url + '/api/session').json()['csrf']
                            response = api.fetch(url + path, method=method, data=data, headers={'X-CSRF-Token': csrf})
                            assert response.status == status, response.text()
                            return response.json()
                        call('/api/login', {'username': 'researcher', 'password': 'LocalDemo2026!'})
                        rid = call('/api/records', {'kind': 'report', 'title': f'Synthetic scope material {width}'}, status=201)['id']
                        cid = call('/api/collections', {'name': f'Synthetic scope {width}', 'visibility': 'shared'}, status=201)['id']
                        call(f'/api/collections/{cid}/items', {'record_id': rid})
                        page = context.new_page()
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(url + '/#collections')
                        page.locator(f'[data-action="open-collection"][data-id="{cid}"]').click()
                        expect(page.get_by_text('未登记检索。', exact=True)).to_be_visible()
                        page.locator(f'[data-action="topic-decision"][data-id="{rid}"]').click()
                        page.locator('[name=disposition]').select_option('excluded')
                        page.locator('[name=rationale]').fill('Synthetic out-of-scope reason')
                        # Another member changes the collection while this decision stays open.
                        call(f'/api/collections/{cid}', {'version': 2, 'stage_judgment': 'Concurrent change'}, method='PUT')
                        page.get_by_role('button', name='保存条目决定', exact=True).click()
                        expect(page.locator('[name=rationale]')).to_have_value('Synthetic out-of-scope reason')
                        expect(page.get_by_text('专题已有新版本，当前输入已保留', exact=True)).to_be_visible()
                        page.screenshot(path=str(EVIDENCE / f'conflict-{width}.png'), full_page=True)
                        page.get_by_role('button', name='我已对照，继续保存决定', exact=True).click()
                        page.get_by_role('button', name='保存条目决定', exact=True).click()
                        expect(page.get_by_role('heading', name='已排查并排除', exact=True)).to_be_visible()
                        expect(page.get_by_text('Synthetic out-of-scope reason', exact=True)).to_be_visible()
                        page.get_by_role('button', name='编辑研究内容', exact=True).click()
                        page.get_by_role('button', name='添加排查记录', exact=True).click()
                        row = page.locator('[data-scope-log-row]')
                        row.locator('[data-scope-key=source]').fill('Synthetic public archive')
                        row.locator('[data-scope-key=query]').fill('policy scope')
                        row.locator('[data-scope-key=time_range]').fill('2020—2024')
                        row.locator('[data-scope-key=language]').fill('Latvian')
                        row.locator('[data-scope-key=searched_on]').fill('2026-10-26')
                        row.locator('[data-scope-key=outcome]').select_option('zero_results')
                        row.locator('[data-scope-key=notes]').fill('Synthetic zero results')
                        page.get_by_role('button', name='保存专题', exact=True).click()
                        expect(page.get_by_text('Synthetic zero results', exact=True)).to_be_visible()
                        page.get_by_role('heading', name='已排查并排除', exact=True).scroll_into_view_if_needed()
                        page.screenshot(path=str(EVIDENCE / f'detail-{width}.png'), full_page=True)
                        # The log participates in existing local drafts and version comparison.
                        page.get_by_role('button', name='编辑研究内容', exact=True).click()
                        page.locator('[data-scope-key=notes]').fill('Unsaved log draft')
                        page.get_by_role('button', name='关闭并保留草稿', exact=True).click()
                        page.locator(f'[data-action="open-collection"][data-id="{cid}"]').click()
                        page.get_by_role('button', name='编辑研究内容', exact=True).click()
                        page.get_by_role('button', name='恢复草稿', exact=True).click()
                        expect(page.locator('[data-scope-key=notes]')).to_have_value('Unsaved log draft')
                        version = api.get(url + f'/api/collections/{cid}').json()['version']
                        call(f'/api/collections/{cid}', {'version': version, 'stage_judgment': 'Another concurrent edit'}, method='PUT')
                        page.get_by_role('button', name='保存专题', exact=True).click()
                        expect(page.get_by_text('专题已有新版本，当前草稿已保留', exact=True)).to_be_visible()
                        expect(page.locator('[data-scope-key=notes]')).to_have_value('Unsaved log draft')
                        page.get_by_role('button', name='我已对照，以新版本继续编辑', exact=True).click()
                        page.get_by_role('button', name='保存专题', exact=True).click()
                        expect(page.get_by_text('Unsaved log draft', exact=True)).to_be_visible()
                        page.get_by_text('历史与导出', exact=True).click()
                        with page.expect_download() as download:
                            page.get_by_role('button', name='导出专题内容', exact=True).click()
                        exported = EVIDENCE / f'collection-{width}.zip'
                        download.value.save_as(exported)
                        verified = subprocess.run([sys.executable, str(ROOT / 'scripts/verify_content_export.py'), str(exported)], capture_output=True, text=True)
                        assert verified.returncode == 0, verified.stderr
                        (EVIDENCE / f'zip-cli-{width}.log').write_text(verified.stdout)
                        offline = EVIDENCE / f'offline-{width}'
                        with zipfile.ZipFile(exported) as archive:
                            archive.extractall(offline)
                        for filename in ['index.html', 'review.html']:
                            local = context.new_page()
                            local.goto(offline_url + f'/offline-{width}/' + filename)
                            expect(local.get_by_text('Unsaved log draft', exact=False)).to_be_visible()
                            assert local.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Offline page overflows'
                            local.screenshot(path=str(EVIDENCE / f'{filename}-{width}.png'), full_page=True)
                            local.close()
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Page overflows horizontally'
                        # A completed save arriving after navigation must not reopen the old topic.
                        page.locator(f'[data-action="topic-decision"][data-id="{rid}"]').click()
                        page.locator('[name=rationale]').fill('Late completed decision')
                        pending = []
                        def hold(route):
                            pending.append((route, route.fetch()))
                        page.route('**/api/collections/*/items', hold)
                        page.get_by_role('button', name='保存条目决定', exact=True).click()
                        expect(page.locator('[data-form=topic-decision]')).to_be_visible()
                        page.get_by_role('button', name='关闭', exact=True).click()
                        page.goto(url + '/#library')
                        expect(page.locator('#content')).to_be_visible()
                        assert pending, 'No save response was intercepted'
                        pending[0][0].fulfill(response=pending[0][1])
                        page.unroute('**/api/collections/*/items', hold)
                        page.wait_for_timeout(200)
                        expect(page.locator('[role=dialog]')).to_have_count(0)
                        assert not errors, errors
                        (EVIDENCE / f'result-{width}.json').write_text(json.dumps({'width': width, 'topic': cid, 'record': rid, 'errors': errors, 'status': 'passed'}))
                        context.close()
                finally:
                    browser.close()
        finally:
            server.terminate()
            server.wait(timeout=10)
            offline_server.shutdown()
            offline_server.server_close()
    print(str(EVIDENCE))


if __name__ == '__main__':
    main()
