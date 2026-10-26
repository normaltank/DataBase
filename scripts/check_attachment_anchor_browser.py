"""Synthetic attachment-hit → selected excerpt → fixed report, desktop/mobile."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from platform_app.web import create_app


class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


class AttachmentAnchorBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('DATABASE_BROWSER_EVIDENCE') or tempfile.mkdtemp(prefix='attachment-anchor-browser-'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.app = create_app(Path(tempfile.mkdtemp(prefix='app-', dir=cls.out)) / 'data', testing=True)
        cls.server = make_server('127.0.0.1', 0, cls.app, threaded=True, request_handler=QuietHandler)
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None, args=['--no-sandbox'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.thread.join()

    def test_actual_hit_selection_save_and_fixed_report(self):
        for width in [1366, 390]:
            with self.subTest(width=width):
                context = self.browser.new_context(viewport={'width': width, 'height': 900})
                self.addCleanup(context.close)
                request = context.request
                token = request.get(self.url + '/api/session').json()['csrf']
                token = request.post(self.url + '/api/login', data={'username': 'researcher', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': token}).json()['csrf']
                phrase = 'SyntheticAnchor' + str(width)
                content = 'Prefix ' * 40 + phrase + ' selected quotation ending' + ' suffix' * 40
                response = request.post(self.url + '/api/records', multipart={'data': json.dumps({'kind': 'report', 'title': 'Browser original ' + str(width), 'sharing_confirmed': True}), 'file': {'name': 'browser.txt', 'mimeType': 'text/plain', 'buffer': content.encode()}}, headers={'X-CSRF-Token': token})
                assert response.status == 201, response.text()
                rid = response.json()['id']
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.url + '/#library?q=' + phrase)
                button = page.locator('[data-action=attachment-excerpt]').first
                expect(button).to_be_visible()
                button.click()
                segment = page.locator('[data-attachment-segment]')
                expect(segment).to_have_value(content)
                selected = phrase + ' selected quotation'
                segment.evaluate('(el, text) => { const start = el.value.indexOf(text); el.focus(); el.setSelectionRange(start, start + text.length); }', selected)
                page.get_by_role('button', name='将选中文字作为摘录', exact=True).click()
                form = page.locator('form[data-form=record]')
                expect(form).not_to_have_attribute('inert')
                expect(form.locator('[name=quote]')).to_have_value(selected)
                expect(form.locator('[name=locator]')).to_have_value('第 1 行')
                expect(form.locator('[name=evidence_record_id]')).to_have_value(rid)
                form.locator('[name=title]').fill('Browser excerpt ' + str(width))
                form.locator('[type=submit]').click()
                expect(page.get_by_text('已在指定位置的提取文字中匹配', exact=False).first).to_be_visible()
                page.screenshot(path=str(self.out / ('saved-' + str(width) + '.png')), full_page=True)
                found = request.get(self.url + '/api/records?kind=research_note&q=' + phrase).json()['items']
                assert len(found) == 1, found
                nid = found[0]['id']
                result = request.post(self.url + '/api/records', data={'kind': 'research_report', 'title': 'Browser report ' + str(width), 'evidence_ids': [nid]}, headers={'X-CSRF-Token': token})
                assert result.status == 201, result.text()
                page.goto(self.url + '/#library?q=Browser%20report%20' + str(width))
                page.get_by_role('button', name='Browser report ' + str(width), exact=True).first.click()
                expect(page.get_by_text('已在指定位置的提取文字中匹配', exact=False).first).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Horizontal page overflow'
                page.screenshot(path=str(self.out / ('report-' + str(width) + '.png')), full_page=True)
                # Conflict the real excerpt editor after a second member saves.
                page.goto(self.url + '/#library?q=Browser%20excerpt%20' + str(width))
                page.get_by_role('button', name='Browser excerpt ' + str(width), exact=True).first.click()
                page.get_by_text('整理、编辑与核对', exact=True).click()
                page.get_by_role('button', name='编辑内容', exact=True).click()
                form = page.locator('form[data-form=record]')
                expect(form).not_to_have_attribute('inert')
                form.locator('[name=quote]').fill('My unsaved quotation')
                edited = request.put(self.url + '/api/records/' + nid, data={'version': 1, 'interpretation': 'Other member clarification'}, headers={'X-CSRF-Token': token})
                assert edited.ok, edited.text()
                form.locator('[type=submit]').click()
                expect(form.get_by_text('新版本已保存，你的输入仍保留', exact=True)).to_be_visible()
                expect(form.locator('[name=quote]')).to_have_value('My unsaved quotation')
                page.screenshot(path=str(self.out / ('conflict-' + str(width) + '.png')), full_page=True)
                page.get_by_role('button', name='关闭并保留草稿', exact=True).click()
                # A segment response arriving after route change must not open its modal.
                page.goto(self.url + '/#library?q=' + phrase)
                pending = []
                page.route('**/api/attachments/*/segment?*', lambda route: pending.append(route))
                page.locator('[data-action=attachment-excerpt]').first.click()
                page.wait_for_function('true')
                assert pending, 'Segment request was not intercepted'
                page.evaluate("location.hash='#dashboard'")
                expect(page.get_by_role('heading', name='最近入库', exact=True)).to_be_visible()
                pending[0].continue_()
                page.wait_for_load_state('networkidle')
                expect(page.locator('[data-attachment-segment]')).to_have_count(0)
                self.assertEqual(errors, [])
                context.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
