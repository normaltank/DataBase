"""Real Chromium final/summary handoffs, actual browser zoom and fresh restore."""
import hashlib
import io
import json
import logging
import os
import sqlite3
import sys
import tempfile
import threading
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server
from platform_app.web import create_app
from platform_app.maintenance import create_backup, restore_backup
from scripts.check_collaboration_browser import login, no_overflow
from scripts.check_collaboration_recovery import login as account


def call(client, path, data, raw=None):
    options = {'headers': {'X-CSRF-Token': client.get('/api/session').json['csrf']}}
    if raw is None:
        options['json'] = data
    else:
        options['data'] = {'data': json.dumps(data), 'file': (io.BytesIO(raw), '独立原件.txt')}
    response = client.post(path, **options)
    response.request.close()
    assert response.status_code in (200, 201), (path, response.status_code, response.json)
    return response.json


def serve(app):
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f'http://127.0.0.1:{server.server_port}'


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    evidence = Path(tempfile.mkdtemp(prefix='database-topic-finals-browser-'))
    print(json.dumps({'evidence': str(evidence)}), flush=True)
    (Path(tempfile.gettempdir()) / 'database-topic-finals-browser-latest.txt').write_text(str(evidence), encoding='utf-8')
    data = evidence / 'data'
    app = create_app(data, testing=True)
    lead, author, admin = [account(app, name) for name in ('researcher', 'colleague', 'admin')]
    response = admin.put('/api/collaboration/qualifications/researcher', json={'version': 0, 'enabled': True}, headers={'X-CSRF-Token': admin.get('/api/session').json['csrf']})
    assert response.status_code == 200
    extension = evidence / 'zoom-extension'
    extension.mkdir()
    (extension / 'manifest.json').write_text(json.dumps({'manifest_version': 3, 'name': 'Local actual zoom verifier', 'version': '1.0', 'permissions': ['tabs'], 'background': {'service_worker': 'worker.js'}}), encoding='utf-8')
    (extension / 'worker.js').write_text('chrome.runtime.onInstalled.addListener(() => {});', encoding='utf-8')
    server, thread, base = serve(app)
    results, errors = [], []
    restored_server = None
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
            last_tid = None
            for width, zoom in ((1366, 1), (390, 1), (1366, 2)):
                tid = call(lead, '/api/collaboration/topics', {'theme': f'定稿与采用 {width}/{zoom}', 'participant_ids': ['colleague']})['id']
                call(lead, f'/api/collaboration/topics/{tid}/meetings', {'version': 0, 'topic_version': 1, 'request_id': f'meeting-{width}-{zoom}', 'note': '本期采用', 'assignments': [
                    {'title': '跨国独立文章甲_' + '长题名与研究原件' * 9, 'author_id': 'colleague', 'country': '拉脱维亚、波兰'},
                    {'title': '同一作者另一篇文章乙', 'author_id': 'colleague', 'country': '拉脱维亚'}]})
                assignments = author.get(f'/api/collaboration/topics/{tid}/workflow').json['assignments']
                for index, a in enumerate(assignments):
                    call(author, f'/api/collaboration/topics/{tid}/assignments/{a["id"]}/submissions', {'version': 0, 'topic_version': 1, 'meeting_version': 1, 'request_id': f'draft-{index}-{width}-{zoom}'}, b'independently authored draft ' + str(index).encode())
                page.set_viewport_size({'width': width, 'height': 900})
                page.goto(base)
                worker.evaluate("async ({url,zoom})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,zoom)}", {'url': base, 'zoom': zoom})
                actual_zoom = worker.evaluate("async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));return chrome.tabs.getZoom(t.id)}", base)
                assert actual_zoom == zoom
                login(page, base, 'researcher')
                page.get_by_role('button', name=f'定稿与采用 {width}/{zoom}', exact=True).click()
                for index, a in enumerate(assignments):
                    card = page.locator('[data-assignment-card="' + a['id'] + '"]')
                    button = card.get_by_role('button', name='确认当前稿件定稿', exact=True)
                    button.focus()
                    page.keyboard.press('Enter')
                    form = page.get_by_role('dialog')
                    form.get_by_label('定稿依据', exact=False).fill('逐版核对原件与出处')
                    form.get_by_role('button', name='确认稿件 v1 为定稿', exact=True).click()
                    expect(card.get_by_text('已定稿', exact=True)).to_be_visible()
                # Current work and record identity are traversable without gaining body edit rights.
                page.locator('[data-assignment-card]').first.get_by_role('button', name='查看成果 · 待作者确认', exact=True).click()
                dialog = page.get_by_role('dialog')
                expect(dialog.get_by_role('heading', name='编译工作与成果原件', exact=True)).to_be_visible()
                dialog.get_by_role('button', name='返回所属主题工作', exact=True).click()
                expect(page.get_by_role('heading', name=f'定稿与采用 {width}/{zoom}', exact=True)).to_be_visible()
                page.get_by_role('button', name='提交整期汇总', exact=True).click()
                dialog = page.get_by_role('dialog')
                dialog.get_by_label('汇总负责作者', exact=False).select_option('colleague')
                for checkbox in dialog.get_by_role('checkbox').all():
                    checkbox.check()
                long_name = '整期汇总_' + '跨国研究成果' * 19 + '.txt'
                dialog.get_by_label('整期汇总文件', exact=False).set_input_files({'name': long_name, 'mimeType': 'text/plain', 'buffer': b'actual local assembled issue'})
                dialog.get_by_label('汇总说明', exact=False).fill('保留的合稿说明')
                with closing(sqlite3.connect(data / 'platform.sqlite3')) as db, db:
                    db.execute("CREATE TRIGGER synthetic_summary_failure BEFORE INSERT ON topic_summaries BEGIN SELECT RAISE(ABORT,'synthetic final write failure'); END")
                dialog.get_by_role('button', name='保存整期汇总 v1', exact=True).click()
                expect(dialog.locator('.form-error')).not_to_be_empty()
                assert dialog.get_by_label('整期汇总文件', exact=False).evaluate('el=>el.files[0].name') == long_name
                expect(dialog.get_by_label('汇总说明', exact=False)).to_have_value('保留的合稿说明')
                with closing(sqlite3.connect(data / 'platform.sqlite3')) as db, db:
                    db.execute('DROP TRIGGER synthetic_summary_failure')
                # Another page saves a real earlier summary; the form must preserve its chosen originals.
                current = author.get(f'/api/collaboration/topics/{tid}/workflow').json
                final_ids = [a['finals'][0]['id'] for a in current['assignments']]
                call(author, f'/api/collaboration/topics/{tid}/summaries', {'request_id': f'parallel-summary-{width}-{zoom}', 'topic_version': 1, 'version': 0, 'author_id': 'colleague', 'final_ids': final_ids, 'note': '另一页先保存'}, b'parallel existing issue')
                dialog.get_by_role('button', name='保存整期汇总 v1', exact=True).click()
                expect(dialog.get_by_role('heading', name='请核对最新定稿与汇总状态', exact=True)).to_be_visible()
                assert dialog.get_by_label('整期汇总文件', exact=False).evaluate('el=>el.files[0].name') == long_name
                assert dialog.get_by_role('checkbox', checked=True).count() == 2
                dialog.get_by_role('button', name='已核对，保留输入继续', exact=True).click()
                dialog.get_by_role('button', name='保存整期汇总 v2', exact=True).click()
                expect(page.get_by_role('heading', name='整期汇总 v2', exact=True)).to_be_visible()
                assert page.locator('[data-form="topic-finals-summary"]').count() == 0
                layout = no_overflow(page)
                if zoom == 1:
                    page.screenshot(path=str(evidence / f'finals-{width}-{zoom}.png'), full_page=True)
                page.evaluate('window.scrollTo({top:0,left:0,behavior:"instant"})')
                page.wait_for_function('scrollY === 0')
                page.screenshot(path=str(evidence / f'viewport-{width}-{zoom}.png'), full_page=False)
                boundaries = page.evaluate("[...document.querySelectorAll('.collaboration-workspace h1,.collaboration-workspace h3,.collaboration-file,.topic-assignment,.page-heading')].filter(el=>el.getClientRects().length).map(el=>({tag:el.tagName,left:el.getBoundingClientRect().left,right:el.getBoundingClientRect().right})).filter(r=>r.left < -1 || r.right > innerWidth+1)")
                assert not boundaries, boundaries
                page.get_by_role('button', name='退出登录', exact=True).click()
                login(page, base, 'colleague')
                page.get_by_role('button', name=f'定稿与采用 {width}/{zoom}', exact=True).click()
                card = page.locator('[data-assignment-card="' + assignments[0]['id'] + '"]')
                card.get_by_text('提交我的编译稿 · 新版本 2', exact=True).click()
                card.get_by_label('编译稿文件', exact=False).set_input_files({'name': '后续替换稿.txt', 'mimeType': 'text/plain', 'buffer': b'later changed individual manuscript'})
                card.get_by_role('button', name='提交编译稿 v2', exact=True).click()
                expect(card.get_by_text('待审', exact=True)).to_be_visible()
                summary = page.locator('[data-summary-card]').first
                summary.get_by_text('核对采用的 2 篇具体定稿版本', exact=True).click()
                assert summary.get_by_role('heading', name='定稿 v2', exact=False).count() == 0
                with page.expect_download() as download:
                    summary.get_by_role('link', name='下载所采用的定稿 v1', exact=True).first.click()
                downloaded = Path(download.value.path()).read_bytes()
                assert downloaded == b'independently authored draft 0'
                if zoom == 1:
                    page.screenshot(path=str(evidence / f'adoptions-{width}-{zoom}.png'), full_page=True)
                if zoom == 1:
                    summary.scroll_into_view_if_needed()
                    page.screenshot(path=str(evidence / f'adoptions-viewport-{width}-{zoom}.png'), full_page=False)
                no_overflow(page)
                page.get_by_role('button', name='退出登录', exact=True).click()
                login(page, base, 'admin')
                page.get_by_role('button', name='维护查阅', exact=True).click()
                page.get_by_role('button', name=f'定稿与采用 {width}/{zoom}', exact=True).click()
                assert page.get_by_role('button', name='确认当前稿件定稿', exact=True).count() == 0
                assert page.get_by_role('button', name='提交整期汇总', exact=True).count() == 0
                assert page.get_by_label('编译稿文件', exact=False).count() == 0
                page.get_by_role('button', name='退出登录', exact=True).click()
                results.append({'width': width, 'actual_browser_zoom': actual_zoom, 'layout': layout, 'two_articles_multicountry': True, 'keyboard_final': True, 'failed_summary_preserved_file_and_note': True, 'conflict_preserved_selection': True, 'work_record_roundtrip': True, 'old_summary_keeps_v1_after_replacement': True, 'adopted_original_sha256': hashlib.sha256(downloaded).hexdigest()})
                last_tid = tid
            backup = create_backup(data)
            restored = evidence / 'restored-new-directory'
            restore_backup(backup, restored)
            restored_server, restored_thread, restored_base = serve(create_app(restored, testing=True))
            page.set_viewport_size({'width': 390, 'height': 900})
            page.goto(restored_base)
            worker.evaluate("async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,1)}", restored_base)
            login(page, restored_base, 'colleague')
            page.goto(restored_base + '/#collaboration?id=' + last_tid)
            expect(page.get_by_role('heading', name='整期汇总 v2', exact=True)).to_be_visible()
            summary = page.locator('[data-summary-card]').first
            summary.get_by_text('核对采用的 2 篇具体定稿版本', exact=True).click()
            with page.expect_download() as download:
                summary.get_by_role('link', name='下载所采用的定稿 v1', exact=True).first.click()
            assert Path(download.value.path()).read_bytes() == b'independently authored draft 0'
            no_overflow(page)
            page.screenshot(path=str(evidence / 'restored-390.png'), full_page=True)
            assert not errors, errors
            context.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        if restored_server:
            restored_server.shutdown()
            restored_thread.join(timeout=5)
            restored_server.server_close()
        (evidence / 'results.json').write_text(json.dumps({'results': results, 'page_errors': errors, 'restored_browser_checked': bool(restored_server)}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'evidence': str(evidence), 'results': results, 'restored_browser_checked': True, 'page_errors': errors}, ensure_ascii=False))


if __name__ == '__main__':
    main()
