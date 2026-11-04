"""Review recovery checks on fresh synthetic data and a random loopback port.

Only the local worker status is simulated; journal saves use the real HTTP
transaction. No worker, paid queue or external network is started.
"""
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from platform_app.web import create_app
from portable.public_collection import LocalPublicSettings
from scripts.check_collaboration_browser import login, no_overflow


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    evidence = Path(tempfile.mkdtemp(prefix='database-journal-review-recovery-'))
    app = create_app(evidence/'data', testing=True, embedded_worker=False)
    settings = LocalPublicSettings(evidence/'copy', storage_root=evidence/'private')
    def status():
        value = settings.status()
        return dict(value, available=True, worker_state='running' if value['enabled'] else 'stopped')
    def configure(enabled, source_ids):
        settings.configure(enabled, source_ids)
        return status()
    app.config['PUBLIC_COLLECTION_STATUS'] = status
    app.config['PUBLIC_COLLECTION_CONFIGURE'] = configure
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    errors, results = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, **({'executable_path':os.environ['DATABASE_BROWSER_EXECUTABLE']} if os.environ.get('DATABASE_BROWSER_EXECUTABLE') else {}))
            context = browser.new_context(viewport={'width':1366, 'height':900})
            context.route('**/*', lambda r:r.continue_() if r.request.url.startswith(base) else r.abort())
            page = context.new_page()
            page.on('pageerror', lambda e:errors.append(str(e)))
            login(page, base, 'admin')
            for width in (1366, 390):
                page.set_viewport_size({'width':width, 'height':900})
                page.goto(base+'/#journal-results?new=1')
                title = f'完全虚构的响应恢复期刊 {width}'
                page.get_by_label('刊名 *', exact=True).fill(title)
                page.get_by_label('年份 *', exact=True).fill('2026')
                page.get_by_label('成果期次 *', exact=True).fill('1')
                page.get_by_text('期刊档案关联与说明', exact=True).click()
                page.get_by_label('期次说明', exact=True).fill('最初说明')
                original = b'SYNTHETIC original - committed exactly once'
                page.get_by_label('首批成果文件 *', exact=True).set_input_files({'name':'synthetic.txt', 'mimeType':'text/plain', 'buffer':original})
                page.get_by_label('文件说明', exact=True).fill('首批原件说明')
                committed = []
                def lost_response(route):
                    response = route.fetch()
                    assert response.status == 201, response.text()
                    committed.append(response.json()['id'])
                    route.abort('failed')
                page.route('**/api/journal-results', lost_response)
                page.get_by_role('button', name='保存一期成果', exact=True).click()
                expect(page.locator('.form-error')).not_to_be_empty()
                page.unroute('**/api/journal-results', lost_response)
                page.get_by_label('期次说明', exact=True).fill('响应丢失后修改的说明')
                page.get_by_role('button', name='保存一期成果', exact=True).click()
                expect(page.locator('.form-error')).to_contain_text('同一保存请求的内容已改变')
                page.get_by_role('button', name='查询本次保存结果，保留当前输入', exact=True).click()
                expect(page.locator('[data-jr-latest]')).to_contain_text('本次已创建')
                expect(page.get_by_label('期次说明', exact=True)).to_have_value('响应丢失后修改的说明')
                expect(page.get_by_label('文件说明', exact=True)).to_have_value('首批原件说明')
                assert page.locator('input[type=file]').evaluate('e=>e.files[0].name') == 'synthetic.txt'
                no_overflow(page)
                page.screenshot(path=str(evidence/f'recovery-{width}.png'), full_page=True)
                page.get_by_role('button', name='接续已创建成果，仅修订期次信息', exact=True).click()
                page.get_by_role('button', name='仅保存期次信息（不重复上传文件）', exact=True).click()
                expect(page.get_by_role('heading', name=title, exact=True)).to_be_visible()
                current = context.request.get(base+'/api/journal-results/'+committed[0]).json()
                assert current['note'] == '响应丢失后修改的说明'
                assert len(current['files']) == len(current['files'][0]['versions']) == 1
                assert context.request.get(base+current['files'][0]['versions'][0]['file_url']).body() == original
                listing = context.request.get(base+'/api/journal-results?q='+str(width)).json()
                assert listing['total'] == 1
                results.append({'width':width, 'creation_response_lost_then_changed_retry':True, 'one_result_one_original':True})
            page.set_viewport_size({'width':1366, 'height':900})
            page.goto(base+'/#maintenance-ingestion')
            page.get_by_role('button', name='登记三刊公开来源', exact=True).click()
            expect(page.locator('[data-form="ingestion-config"]')).to_have_count(3)
            local = page.locator('[data-form="public-collection"]')
            local.locator('input').first.check()
            for enabled in (True, False):
                pending = []
                def delayed_read(route):
                    response = route.fetch()
                    pending.append((route, response.body()))
                page.route('**/api/ingestion', delayed_read)
                page.get_by_role('button', name='刷新状态（保留草稿）', exact=True).click()
                expect(page.get_by_role('button', name='刷新状态（保留草稿）', exact=True)).to_be_disabled()
                deadline = time.monotonic()+5
                while not pending:
                    assert time.monotonic()<deadline, 'Synthetic refresh did not reach its transport seam'
                    page.wait_for_timeout(20)
                assert len(pending) == 1
                form = page.locator('[data-form="ingestion-config"]').first
                form.locator('[name="frequency_hours"]').fill('37')
                button = '开启所选期刊公开采集' if enabled else '暂停本机公开采集'
                local.get_by_role('button', name=button, exact=True).click()
                expected = '本机已开启公开采集' if enabled else '本机公开采集已暂停'
                expect(local.locator('[role=status]')).to_contain_text(expected)
                route, body = pending.pop()
                route.fulfill(status=200, content_type='application/json', body=body)
                expect(page.get_by_role('button', name='刷新状态（保留草稿）', exact=True)).to_be_enabled()
                expect(local.locator('[role=status]')).to_contain_text(expected)
                expect(form.locator('[name="frequency_hours"]')).to_have_value('37')
                expect(local.locator('input').first).to_be_checked()
                page.unroute('**/api/ingestion', delayed_read)
                no_overflow(page)
                page.screenshot(path=str(evidence/f'late-refresh-{enabled}.png'), full_page=True)
                results.append({'local_enabled':enabled, 'late_read_preserved_save_and_drafts':True})
            context.close()
            browser.close()
        assert not errors, errors
        report = dict(synthetic=True, results=results, page_errors=errors, evidence=str(evidence))
        (evidence/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
