"""#134: merged discovery/maintenance HTTP and browser seam, synthetic only."""
import json
import logging
import os
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from tests.test_maintenance_agent import MaintenanceAgentTests


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    root = Path(os.environ['DATABASE_FOUNDATION_QA'])
    root.mkdir(parents=True, exist_ok=False)
    os.environ['DATABASE_TEST_TMP'] = str(root)
    fixture = MaintenanceAgentTests()
    fixture.setUp()
    server = None
    errors = []
    results = []
    try:
        fixture.queue('foundation-network')
        fixture.call('/api/admin/maintenance/run', user='admin')
        bylines = fixture.clients['researcher'].get('/api/records/'+fixture.rid+'/bylines').json
        assert bylines['items'][0]['machine'] is True, bylines
        person = bylines['items'][0]['target_id']
        fixture.call('/api/records/'+fixture.rid+'/bylines', {
            'version': bylines['version'], 'record_version': bylines['record_version'],
            'change_note': 'Synthetic unresolved signature',
            'items': [bylines['items'][0], {'raw_name': 'Unknown Alex', 'status': 'pending'}],
        }, method='PUT')
        assert fixture.clients['researcher'].get('/api/records/'+fixture.rid+'/bylines').json['items'][0]['machine']
        server = make_server('127.0.0.1', 0, fixture.app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:'+str(server.server_port)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width': 1366, 'height': 900})
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base+'/#library?q=Baltic')
            page.get_by_role('button', name='研究员', exact=True).click()
            page.locator('[data-library-record="'+fixture.rid+'"] [data-action="detail"]').click()
            explorer = page.locator('.library-reader [data-record-explore]')
            explorer.locator('summary').click()
            expect(explorer).to_contain_text('AI 关联作者')
            expect(explorer.locator('[data-explore-target][data-type="person"]')).to_have_count(1)
            expect(explorer.locator('[data-explore-target][data-id="'+person+'"]')).to_have_text('Alex Vale')
            expect(explorer.locator('.record-explore-pending')).to_contain_text('Unknown Alex')
            assert 'Unknown Alex' not in explorer.locator('.record-explore-edges').inner_text()
            expect(explorer).to_contain_text('刊载期刊')
            assert '任职' not in explorer.inner_text()
            feedback = page.locator('.library-reader .maintenance-feedback')
            expect(feedback.locator(':scope > summary')).to_contain_text('指出问题')
            feedback.locator(':scope > summary').click()
            feedback.get_by_label('问题说明').fill('请核对文章署名单位，任职与署名单位应分别记录。')
            feedback.get_by_role('button', name='提交问题', exact=True).click()
            expect(feedback.locator('[data-feedback-status]')).to_contain_text('等待处理')
            for width in [1366, 390, 320]:
                page.set_viewport_size({'width': width, 'height': 900})
                explorer.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
                shot = root/('reading-'+str(width)+'.png')
                page.screenshot(path=str(shot))
                results.append({'view': 'reading', 'width': width, 'screenshot': str(shot)})
            page.set_viewport_size({'width': 1366, 'height': 900})
            explorer.locator('[data-explore-target][data-id="'+person+'"]').click()
            expect(page.locator('.person-page')).to_be_visible()
            expect(page.locator('.maintenance-feedback>summary')).to_contain_text('指出问题')
            page.get_by_role('button', name='返回资料', exact=True).click()
            expect(explorer).to_be_visible()
            expect(explorer).to_have_attribute('open', '')
            context.close()
            context = browser.new_context(viewport={'width': 1366, 'height': 900})
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base+'/#maintenance-agent')
            page.get_by_role('button', name='资料管理员', exact=True).click()
            expect(page.get_by_role('heading', name='维护状态', exact=True)).to_be_visible()
            expect(page.locator('[data-maintenance-overview]')).to_contain_text('近期修改')
            expect(page.locator('[data-maintenance-jobs]')).to_contain_text('等待处理')
            expect(page.locator('[data-maintenance-jobs]')).to_contain_text('已完成')
            for width in [1366, 390, 320]:
                page.set_viewport_size({'width': width, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
                shot = root/('maintenance-'+str(width)+'.png')
                page.screenshot(path=str(shot))
                results.append({'view': 'maintenance', 'width': width, 'screenshot': str(shot)})
            assert not errors, errors
            browser.close()
        (root/'result.json').write_text(json.dumps({'results': results, 'page_errors': errors, 'provider': 'synthetic only'}, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'evidence': str(root), 'screenshots': len(results), 'page_errors': errors}))
    finally:
        if server:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        fixture.doCleanups()


if __name__ == '__main__':
    main()
