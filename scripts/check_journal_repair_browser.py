"""Focused late-response, conflict and history-recovery checks on synthetic HTTP."""
import argparse
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler
from tests.test_journal_archives import JournalArchiveTests
from scripts.browser_camera import capture


class Quiet(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    fixture = JournalArchiveTests()
    fixture.setUp()
    server = make_server('127.0.0.1', 0, fixture.app, threaded=True, request_handler=Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    report = {'synthetic': True, 'external_requests': [], 'errors': [], 'checks': []}
    try:
        a = fixture.journal
        b = fixture.call('/api/sources', {'name': 'B Visible Journal', 'kind': 'journal'}).json['id']
        old_a = fixture.get('/api/journals/' + a)
        issue = fixture.issue()
        record = fixture.compilation()
        original = fixture.get('/api/records/' + fixture.call('/api/records', {'title': 'Frozen basis', 'kind': 'report', 'abstract': 'Original abstract'}).json['id'])
        path = fixture.base + '/compilations/' + record['id']
        first = fixture.call(path, {'version': 0, 'record_version': record['version'], 'issue_ids': [issue['id']], 'selections': [fixture.selected(issue, original)]}, 'PUT').json
        fixture.call(path, {**first, 'selections': []}, 'PUT')
        fixture.call(fixture.base + '/issues/' + issue['id'], {**issue, 'sections': []}, 'PUT')
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1366, 'height': 900}, reduced_motion='reduce')
            context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(base) else (report['external_requests'].append(r.request.url), r.abort())[-1])
            page = context.new_page()
            page.on('pageerror', lambda e: report['errors'].append(str(e)))
            page.goto(base)
            page.get_by_label('账号', exact=True).fill('researcher')
            page.get_by_label('密码', exact=True).fill('LocalDemo2026!')
            page.get_by_role('button', name='查看资料', exact=True).click()
            page.wait_for_selector('[data-action="nav"][data-id="collaboration"]')
            held = []
            pattern = '**/api/journals/' + a
            page.route(pattern, lambda r: held.append(r))
            page.evaluate('(v)=>location.hash=v', '#sources?id=' + a + '&ja_edit=profile')
            page.wait_for_timeout(200)
            assert held
            page.evaluate('(v)=>location.hash=v', '#sources?id=' + b + '&ja_edit=profile')
            page.wait_for_selector(f'[data-ja-source="{b}"] [data-ja-form="profile"]')
            field = page.get_by_label('创刊时间（保留实际精度）', exact=True)
            field.fill('B-only-1988')
            page.evaluate('scrollTo(0,200)')
            before = page.evaluate('scrollY')
            held.pop().fulfill(json=old_a)
            page.wait_for_timeout(300)
            expect(field).to_have_value('B-only-1988')
            assert page.evaluate('scrollY') == before
            assert page.locator('[data-ja-source]').get_attribute('data-ja-source') == b
            # Another member saves while this input remains untouched.
            assert fixture.call('/api/journals/' + b + '/profile', {'version': 0, 'founded': 'Other member'}, 'PUT', 'colleague').status_code == 200
            page.get_by_role('button', name='保存期刊信息', exact=True).click()
            expect(page.locator('.form-error')).to_contain_text('新版本')
            expect(field).to_have_value('B-only-1988')
            page.get_by_role('button', name='读取最新版本并对照，保留当前输入', exact=True).click()
            page.get_by_role('button', name='我已对照，继续编辑当前输入', exact=True).click()
            expect(field).to_have_value('B-only-1988')
            page.get_by_role('button', name='保存期刊信息', exact=True).click()
            page.wait_for_selector(f'[data-ja-source="{b}"] .ja-heading')
            assert fixture.get('/api/journals/' + a)['profile']['version'] == 0
            assert fixture.get('/api/journals/' + b)['profile']['founded'] == 'B-only-1988'
            page.unroute(pattern)
            report['checks'].append('late A cannot change B target, input or scroll; 409 retains B input and comparison saves B')
            # Preserve a local form draft while restoring public history.
            page.goto(base + '/#sources?id=' + b + '&ja_edit=profile')
            page.get_by_label('创刊时间（保留实际精度）', exact=True).fill('Unsaved local draft')
            page.get_by_role('link', name='返回期刊档案', exact=True).click()
            page.get_by_role('link', name='信息与指标历史', exact=True).click()
            old = page.locator('.ja-history').last
            old.locator('summary').first.click()
            # Stale restore must not replace a concurrent version.
            assert fixture.call('/api/journals/' + b + '/profile', {'version': 2, 'founded': 'Concurrent latest'}, 'PUT', 'colleague').status_code == 200
            old.get_by_role('button', name='恢复此版期刊信息与指标', exact=True).click()
            expect(page.locator('[data-ja-restore-status]')).to_contain_text('新版本')
            assert fixture.get('/api/journals/' + b)['profile']['founded'] == 'Concurrent latest'
            page.get_by_role('button', name='读取最新历史后重新对照', exact=True).click()
            old = page.locator('.ja-history').last
            old.locator('summary').first.click()
            old.get_by_role('button', name='恢复此版期刊信息与指标', exact=True).click()
            expect(page.locator('.ja-history')).to_have_count(4)
            assert fixture.get('/api/journals/' + b)['profile']['founded'] == 'Other member'
            capture(page, args.out / 'profile-restored.png')
            page.get_by_role('link', name='返回期刊档案', exact=True).click()
            page.get_by_role('link', name='维护期刊信息与指标', exact=True).click()
            page.get_by_role('button', name='恢复本机草稿', exact=True).click()
            expect(page.get_by_label('创刊时间（保留实际精度）', exact=True)).to_have_value('Unsaved local draft')
            report['checks'].append('profile restore appends revision, concurrent restore rejected, pre-existing local draft retained')
            for width, kind, query, button, api in [
                (390, 'issue', '&ja_issue=' + issue['id'], '恢复此版卷期与目次', fixture.base + '/issues/' + issue['id']),
                (1366, 'compilation', '&ja_compilation=' + record['id'], '恢复此版选编与依据', path),
            ]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.goto(base + '/#sources?id=' + a + query + '&ja_history=' + kind)
                old = page.locator('.ja-history').last
                old.locator('summary').first.click()
                old.get_by_role('button', name=button, exact=True).click()
                expect(page.locator('.ja-history')).to_have_count(3)
                assert fixture.get(api)['version'] == 3
                assert fixture.get(api)['sections' if kind == 'issue' else 'selections']
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                capture(page, args.out / f'{kind}-restored-{width}.png')
                report['checks'].append(f'{kind} history restored through actual {width}px button, old revisions retained')
            assert not report['errors'], report['errors']
            assert not report['external_requests'], report['external_requests']
            report['browser_version'] = browser.version
            report['ok'] = True
            browser.close()
    finally:
        server.shutdown()
        fixture.doCleanups()
        (args.out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
