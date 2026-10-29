"""Focused reassignment proof at 1366/390px and actual Chromium 200% zoom."""
import hashlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from platform_app.web import create_app
from scripts.check_collaboration_browser import login, no_overflow
from scripts.check_collaboration_recovery import login as account
from scripts.check_topic_finals_browser import call, serve


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    evidence = Path(tempfile.mkdtemp(prefix='database-reassignment-browser-'))
    (Path(tempfile.gettempdir()) / 'database-reassignment-browser-latest.txt').write_text(str(evidence), encoding='utf-8')
    print(json.dumps({'evidence': str(evidence)}), flush=True)
    app = create_app(evidence / 'data', testing=True)
    lead, author, admin = [account(app, n) for n in ('researcher', 'colleague', 'admin')]
    response = admin.put('/api/collaboration/qualifications/researcher', json={'version': 0, 'enabled': True}, headers={'X-CSRF-Token': admin.get('/api/session').json['csrf']})
    assert response.status_code == 200
    extension = evidence / 'zoom-extension'
    extension.mkdir()
    (extension / 'manifest.json').write_text(json.dumps({'manifest_version': 3, 'name': 'Reassignment zoom verifier', 'version': '1.0', 'permissions': ['tabs'], 'background': {'service_worker': 'worker.js'}}), encoding='utf-8')
    (extension / 'worker.js').write_text('chrome.runtime.onInstalled.addListener(() => {});', encoding='utf-8')
    server, thread, base = serve(app)
    results, errors = [], []
    try:
        with sync_playwright() as p:
            executable = os.environ.get('DATABASE_BROWSER_EXECUTABLE')
            context = p.chromium.launch_persistent_context(str(evidence / 'profile'), headless=False,
                **({'executable_path': executable} if executable else {}), ignore_default_args=['--disable-extensions'],
                args=['--headless=new', f'--disable-extensions-except={extension}', f'--load-extension={extension}'],
                viewport={'width': 1366, 'height': 900}, accept_downloads=True)
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page = context.pages[0]
            page.on('pageerror', lambda error: errors.append(str(error)))
            for width, zoom in ((1366, 1), (390, 1), (1366, 2)):
                tid = call(lead, '/api/collaboration/topics', {'theme': f'改派稿件核对 {width}/{zoom}', 'participant_ids': ['colleague']})['id']
                root = f'/api/collaboration/topics/{tid}'
                call(lead, root + '/meetings', {'topic_version': 1, 'version': 0, 'request_id': f'initial-meeting-{width}-{zoom}', 'assignments': [{'title': '保持文章身份的改派演示', 'author_id': 'colleague'}]})
                a = lead.get(root + '/workflow').json['assignments'][0]
                aid = a['id']
                sid = call(author, root + f'/assignments/{aid}/submissions', {'topic_version': 1, 'meeting_version': 1, 'version': 0, 'request_id': f'initial-draft-{width}-{zoom}'}, b'previous author exact original')['id']
                fid = call(lead, root + f'/assignments/{aid}/finals', {'topic_version': 1, 'meeting_version': 1, 'submission_id': sid, 'version': 1, 'status': 'pending', 'request_id': f'initial-final-{width}-{zoom}'})['id']
                call(lead, root + '/summaries', {'topic_version': 1, 'version': 0, 'author_id': 'colleague', 'final_ids': [fid], 'request_id': f'old-summary-{width}-{zoom}'}, b'old issue adopts previous author')
                rows = lead.get(root + '/workflow').json['meetings'][0]['assignments']
                rows[0]['author_id'] = 'researcher'
                call(lead, root + '/meetings', {'topic_version': 1, 'version': 1, 'request_id': f'reassign-meeting-{width}-{zoom}', 'assignments': rows})
                page.set_viewport_size({'width': width, 'height': 900})
                page.goto(base)
                worker.evaluate("async ({url,zoom})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,zoom)}", {'url': base, 'zoom': zoom})
                actual_zoom = worker.evaluate("async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));return chrome.tabs.getZoom(t.id)}", base)
                assert actual_zoom == zoom
                login(page, base, 'researcher')
                page.get_by_role('button', name=f'改派稿件核对 {width}/{zoom}', exact=True).click()
                card = page.locator(f'[data-assignment-card="{aid}"]')
                expect(card.get_by_text('待交稿', exact=True)).to_be_visible()
                expect(card.get_by_text('当前编译者尚未提交编译稿。', exact=True)).to_be_visible()
                assert card.get_by_role('button', name='确认当前稿件定稿', exact=True).count() == 0
                card.get_by_text('此前 1 版稿件及退回意见', exact=True).click()
                expect(card.get_by_role('heading', name='定稿 v1', exact=False)).to_be_visible()
                summary = page.locator('[data-summary-card]').first
                summary.get_by_text('核对采用的 1 篇具体定稿版本', exact=True).click()
                with page.expect_download() as download:
                    summary.get_by_role('link', name='下载所采用的定稿 v1', exact=True).click()
                raw = Path(download.value.path()).read_bytes()
                assert raw == b'previous author exact original'
                card.scroll_into_view_if_needed()
                no_overflow(page)
                page.screenshot(path=str(evidence / f'awaiting-{width}-{zoom}.png'), full_page=True)
                card.get_by_text('提交我的编译稿 · 新版本 2', exact=True).click()
                card.get_by_label('编译稿文件', exact=False).set_input_files({'name': '新作者稿件.txt', 'mimeType': 'text/plain', 'buffer': b'current author new manuscript'})
                card.get_by_role('button', name='提交编译稿 v2', exact=True).click()
                expect(card.get_by_text('待审', exact=True)).to_be_visible()
                card.get_by_text('退回修改 · 针对版本 2', exact=True).click()
                card.get_by_label('退回意见', exact=True).fill('核对新作者的第二版')
                card.get_by_role('button', name='退回版本 2', exact=True).click()
                expect(card.get_by_text('返修', exact=True)).to_be_visible()
                card.get_by_text('提交我的编译稿 · 新版本 3', exact=True).click()
                card.get_by_label('编译稿文件', exact=False).set_input_files({'name': '新作者修改稿.txt', 'mimeType': 'text/plain', 'buffer': b'current author revised manuscript'})
                card.get_by_role('button', name='提交编译稿 v3', exact=True).click()
                expect(card.get_by_text('待审', exact=True)).to_be_visible()
                card.get_by_role('button', name='确认当前稿件定稿', exact=True).click()
                page.get_by_role('dialog').get_by_role('button', name='确认稿件 v3 为定稿', exact=True).click()
                expect(card.get_by_text('已定稿', exact=True)).to_be_visible()
                layout = no_overflow(page)
                card.scroll_into_view_if_needed()
                page.screenshot(path=str(evidence / f'final-{width}-{zoom}.png'), full_page=True)
                current = lead.get(root + '/workflow').json
                assert current['summaries'][0]['adoptions'][0]['submission_id'] == sid
                results.append({'width': width, 'actual_browser_zoom': actual_zoom, 'awaiting_after_reassignment': True, 'new_author_return_and_final': True, 'old_summary_adoption_retained': True, 'download_sha256': hashlib.sha256(raw).hexdigest(), 'layout': layout})
                if width == 1366 and zoom == 1:
                    # Leave a real final form open while another page changes responsibility.
                    conflict_tid = call(lead, '/api/collaboration/topics', {'theme': '改派后旧表单保留输入', 'participant_ids': ['colleague']})['id']
                    conflict_root = f'/api/collaboration/topics/{conflict_tid}'
                    call(lead, conflict_root + '/meetings', {'topic_version': 1, 'version': 0, 'request_id': 'conflict-first-meeting', 'assignments': [{'title': '待审原作者稿件', 'author_id': 'colleague'}]})
                    old_assignment = lead.get(conflict_root + '/workflow').json['assignments'][0]
                    call(author, conflict_root + f'/assignments/{old_assignment["id"]}/submissions', {'topic_version': 1, 'meeting_version': 1, 'version': 0, 'request_id': 'conflict-first-draft'}, b'old author pending original')
                    page.goto(base + '/#collaboration?id=' + conflict_tid)
                    expect(page.get_by_role('heading', name='改派后旧表单保留输入', exact=True)).to_be_visible()
                    page.get_by_role('button', name='确认当前稿件定稿', exact=True).click()
                    dialog = page.get_by_role('dialog')
                    dialog.get_by_label('定稿依据', exact=False).fill('旧表单的审稿依据仍保留')
                    rows = lead.get(conflict_root + '/workflow').json['meetings'][0]['assignments']
                    rows[0]['author_id'] = 'researcher'
                    call(lead, conflict_root + '/meetings', {'topic_version': 1, 'version': 1, 'request_id': 'conflict-reassigned-meeting', 'assignments': rows})
                    dialog.get_by_role('button', name='确认稿件 v1 为定稿', exact=True).click()
                    conflict = dialog.locator('[data-topic-finals-conflict]')
                    expect(conflict.get_by_text('当前编译者尚未提交编译稿。此前稿件保留在工作历史中。', exact=True)).to_be_visible()
                    assert conflict.get_by_role('link').count() == 0
                    expect(dialog.get_by_label('定稿依据', exact=False)).to_have_value('旧表单的审稿依据仍保留')
                    page.screenshot(path=str(evidence / 'reassigned-stale-final-conflict.png'), full_page=True)
                    dialog.get_by_role('button', name='关闭', exact=True).click()
                    results[-1]['stale_final_conflict_awaiting_and_input_retained'] = True
                page.get_by_role('button', name='退出登录', exact=True).click()
            assert not errors, errors
            context.close()
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()
        (evidence / 'results.json').write_text(json.dumps({'results': results, 'page_errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'evidence': str(evidence), 'results': results, 'page_errors': errors}, ensure_ascii=False))


if __name__ == '__main__':
    main()
