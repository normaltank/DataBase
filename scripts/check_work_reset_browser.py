"""#77 work search reset: real Chrome, public HTTP, synthetic Temp data only."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from platform_app.web import create_app
from scripts.check_collaboration_recovery import login as account
from scripts.check_collaboration_library_browser import login
from scripts.check_topic_finals_browser import call, serve


def seed(app):
    lead, admin = [account(app, name) for name in ('researcher', 'admin')]
    response = admin.put('/api/collaboration/qualifications/researcher',
        json={'version': 0, 'enabled': True},
        headers={'X-CSRF-Token': admin.get('/api/session').json['csrf']})
    assert response.status_code == 200, response.json
    tid = call(lead, '/api/collaboration/topics', {'theme': '合成重置主题', 'participant_ids': ['colleague']})['id']
    call(lead, f'/api/collaboration/topics/{tid}/meetings', {
        'version': 0, 'topic_version': 1, 'request_id': 'reset-meeting',
        'assignments': [{'title': '合成重置文章', 'author_id': 'researcher', 'country': '拉脱维亚'}]})
    aid = lead.get(f'/api/collaboration/topics/{tid}/workflow').json['assignments'][0]['id']
    sid = call(lead, f'/api/collaboration/topics/{tid}/assignments/{aid}/submissions', {
        'version': 0, 'topic_version': 1, 'meeting_version': 1, 'request_id': 'reset-draft'}, b'synthetic topic original')['id']
    call(lead, f'/api/collaboration/topics/{tid}/assignments/{aid}/finals', {
        'version': 1, 'topic_version': 1, 'meeting_version': 1, 'submission_id': sid,
        'status': 'pending', 'request_id': 'reset-final', 'visibility': 'shared', 'sharing_confirmed': True})
    wid = call(lead, '/api/collaboration/journals', {
        'journal_name': '合成重置期刊', 'coverage': '2026年第1期', 'content_kind': 'compilation'})['id']
    sid = call(lead, f'/api/collaboration/journals/{wid}/submissions', {
        'version': 1, 'request_id': 'reset-journal', 'material_kind': 'product'}, b'synthetic journal original')['id']
    call(lead, f'/api/collaboration/journals/{wid}/product', {'version': 2, 'submission_id': sid})
    return tid, wid


def snapshot(page):
    return {'url': page.url,
        'business': page.get_by_role('navigation', name='编译业务').locator('[aria-pressed="true"]').inner_text(),
        'scope': page.get_by_role('navigation', name='工作范围').locator('[aria-pressed="true"]').inner_text(),
        'work_ids': page.locator('[data-work-id]').evaluate_all('(rows)=>rows.map(row=>row.dataset.workId)')}


def check_reset(page, base, evidence, result, route, params, business, scope, ids):
    filters = {'q': '合成不存在的查找', 'country': '不存在国家', 'participant': '不存在参与人',
        'from': '1900-01-01', 'to': '1900-01-02', 'page': '9'}
    page.goto(base+'/#'+route+'?'+urlencode({**params, **filters}))
    expect(page.get_by_role('heading', name='当前范围暂无成果' if route == 'compilations' else '当前范围暂无工作', exact=True)).to_be_visible()
    result['before'] = snapshot(page)
    page.screenshot(path=str(evidence/(result['name']+'-before.png')), full_page=False)
    page.get_by_role('button', name='重置查找', exact=True).click()
    expect(page.get_by_label('主题或期刊', exact=True)).to_have_value('')
    result['after'] = snapshot(page)
    page.screenshot(path=str(evidence/(result['name']+'-after.png')), full_page=False)
    expect(page.get_by_role('navigation', name='编译业务').get_by_role('button', name=business, exact=True)).to_have_attribute('aria-pressed', 'true')
    expect(page.get_by_role('navigation', name='工作范围').get_by_role('button', name=scope, exact=True)).to_have_attribute('aria-pressed', 'true')
    query = parse_qs(urlsplit(page.url).fragment.partition('?')[2])
    assert not set(filters) & query.keys(), query
    for key, value in params.items():
        assert query.get(key) == [value], query
    for label in ('国家分工', '参与人', '起始日期', '截止日期'):
        expect(page.get_by_label(label, exact=True)).to_have_value('')
    expect(page.locator('[data-work-id]')).to_have_count(len(ids))
    assert set(snapshot(page)['work_ids']) == set(ids), snapshot(page)
    result['passed'] = True


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    root = Path(__file__).resolve().parents[1]
    evidence = Path(tempfile.mkdtemp(prefix='database-work-reset-77-'))
    print(json.dumps({'evidence': str(evidence)}), flush=True)
    (Path(tempfile.gettempdir())/'database-work-reset-77-latest.txt').write_text(str(evidence), encoding='utf-8')
    result = {'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
        'source_tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=root, text=True).strip(),
        'source_status': subprocess.check_output(['git', 'status', '--short'], cwd=root, text=True).strip(),
        'cases': [], 'pageerrors': []}
    app = create_app(evidence/'data', testing=True)
    tid, wid = seed(app)
    server, thread, base = serve(app)
    try:
        with sync_playwright() as p:
            executable = os.environ.get('DATABASE_BROWSER_EXECUTABLE')
            browser = p.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
            result['browser_version'] = browser.version
            page = browser.new_page(viewport={'width': 1366, 'height': 900})
            page.on('pageerror', lambda error: result['pageerrors'].append(str(error)))
            login(page, base, 'researcher')
            cases = [
                ('journal-leading', 'collaboration', {'business': 'journal', 'scope': 'leading'}, '期刊编译', '我负责的', [wid]),
                ('topic-participating', 'collaboration', {'business': 'topic', 'scope': 'participating'}, '主题编译', '我参与的', [tid]),
                ('topic-leading', 'collaboration', {'business': 'topic', 'scope': 'leading'}, '主题编译', '我负责的', [tid]),
                ('all-readable', 'collaboration', {'business': 'all', 'scope': 'all'}, '全部业务', '全部可读', [tid, wid]),
                ('products-journal-leading', 'compilations', {'business': 'journal', 'scope': 'leading'}, '期刊编译', '我负责的', [wid]),
                ('products-topic-participating', 'compilations', {'business': 'topic', 'scope': 'participating'}, '主题编译', '我参与的', [tid]),
                ('products-all-readable', 'compilations', {'business': 'all', 'scope': 'all'}, '全部业务', '全部可读', [tid, wid]),
                ('default-works', 'collaboration', {}, '主题编译', '我参与的', [tid]),
                ('default-products', 'compilations', {}, '全部业务', '全部可读', [tid, wid]),
            ]
            for name, route, params, business, scope, ids in cases:
                case = {'name': name}
                result['cases'].append(case)
                check_reset(page, base, evidence, case, route, params, business, scope, ids)
            assert not result['pageerrors'], result['pageerrors']
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        result['service_stopped'] = not thread.is_alive()
        (evidence/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'results': str(evidence/'results.json'), 'passed': len(result['cases']),
        'pageerrors': result['pageerrors'], 'service_stopped': result['service_stopped']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
