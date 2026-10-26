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

    def test_selected_overlaps_whitespace_and_unicode_keep_actual_context(self):
        results = []
        cases = [
            ('banana END', 3, 6, 'ana', 'ban', ' END'),
            ('  😀\u00a0 banana\t  END  ', 7, 11, 'ana', '😀 ban', ' END'),
            ('banana ana END', 7, 10, 'ana', 'banana ', ' END'),
            ('  😀\t banana  \tana\t END  ', 10, 18, 'ana', '😀 banana ', ' END'),
            ('  😀\t banana\t  END  ', 3, 18, 'banana\t  END', '😀 ', ''),
        ]
        for width in [1366, 390]:
            for index, (content, start, end, quote, prefix, suffix) in enumerate(cases):
                with self.subTest(width=width, case=index):
                    with self.browser.new_context(viewport={'width': width, 'height': 900}) as context:
                        request = context.request
                        token = request.get(self.url + '/api/session').json()['csrf']
                        token = request.post(self.url + '/api/login', data={'username': 'researcher', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': token}).json()['csrf']
                        headers = {'X-CSRF-Token': token}
                        title = f'Selection{width}Case{index}'
                        response = request.post(self.url + '/api/records', multipart={'data': json.dumps({'kind': 'report', 'title': title, 'sharing_confirmed': True}), 'file': {'name': 'selection.txt', 'mimeType': 'text/plain', 'buffer': content.encode()}}, headers=headers)
                        self.assertEqual(response.status, 201, response.text())
                        original = request.get(self.url + '/api/records/' + response.json()['id']).json()
                        page = context.new_page()
                        page.goto(self.url + '/#library?q=banana')
                        page.locator('[data-action=attachment-excerpt][data-id="' + original['attachments'][0]['id'] + '"]').click()
                        segment = page.locator('[data-attachment-segment]')
                        expect(segment).to_have_value(content.strip())
                        segment.evaluate('(el, range) => {el.focus(); el.setSelectionRange(...range);}', [start, end])
                        page.get_by_role('button', name='将选中文字作为摘录', exact=True).click()
                        form = page.locator('form[data-form=record]')
                        expect(form.locator('[name=quote]')).to_have_value(quote)
                        form.locator('[name=title]').fill(title + ' excerpt')
                        form.locator('[type=submit]').click()
                        expect(page.get_by_text('已在指定位置的提取文字中匹配', exact=False).first).to_be_visible()
                        found = request.get(self.url + '/api/records?kind=research_note&q=' + title.replace(' ', '%20')).json()['items']
                        self.assertEqual(len(found), 1)
                        anchor = request.get(self.url + '/api/records/' + found[0]['id']).json()['evidence_snapshot']['attachment_anchor']
                        self.assertEqual((anchor['context_prefix'], anchor['context_suffix']), (prefix, suffix))
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        page.locator('.attachment-anchor').screenshot(path=str(self.out / f'selection-{width}-{index}.png'))
                        results.append({'width': width, 'content': content, 'range_utf16': [start, end], 'anchor': anchor})
        (self.out / 'selection-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')

    def restore_excerpt_draft(self, page):
        page.get_by_role('button', name='保存草稿', exact=True).click()
        page.get_by_role('button', name='关闭并保留草稿', exact=True).click()
        page.goto(self.url + '/#drafts')
        page.get_by_role('button', name='继续编辑', exact=True).click()
        page.get_by_role('button', name='恢复草稿', exact=True).click()
        form = page.locator('form[data-form=record]')
        expect(form).not_to_have_attribute('inert')
        return form

    def test_selected_instance_survives_new_excerpt_draft(self):
        results = []
        for width in [1366, 390]:
            with self.subTest(width=width), self.browser.new_context(viewport={'width': width, 'height': 900}) as context:
                request = context.request
                token = request.get(self.url + '/api/session').json()['csrf']
                token = request.post(self.url + '/api/login', data={'username': 'researcher', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': token}).json()['csrf']
                response = request.post(self.url + '/api/records', multipart={'data': json.dumps({'kind': 'report', 'title': f'DraftOriginal{width}', 'sharing_confirmed': True}), 'file': {'name': 'draft.txt', 'mimeType': 'text/plain', 'buffer': b'banana END'}}, headers={'X-CSRF-Token': token})
                self.assertEqual(response.status, 201, response.text())
                original = request.get(self.url + '/api/records/' + response.json()['id']).json()
                page = context.new_page()
                page.goto(self.url + '/#library?q=banana')
                page.locator('[data-action=attachment-excerpt][data-id="' + original['attachments'][0]['id'] + '"]').click()
                segment = page.locator('[data-attachment-segment]')
                segment.evaluate('(el) => {el.focus(); el.setSelectionRange(3,6);}')
                page.get_by_role('button', name='将选中文字作为摘录', exact=True).click()
                form = page.locator('form[data-form=record]')
                expect(form.locator('[name=evidence_selection_start]')).to_have_value('3')
                title = f'DraftExcerpt{width}'
                form.locator('[name=title]').fill(title)
                form = self.restore_excerpt_draft(page)
                expect(form.locator('[name=quote]')).to_have_value('ana')
                expect(form.locator('[name=evidence_selection_start]')).to_have_value('3')
                form.locator('[type=submit]').click()
                expect(page.get_by_text('已在指定位置的提取文字中匹配', exact=False).first).to_be_visible()
                found = request.get(self.url + '/api/records?kind=research_note&q=' + title).json()['items']
                self.assertEqual(len(found), 1)
                anchor = request.get(self.url + '/api/records/' + found[0]['id']).json()['evidence_snapshot']['attachment_anchor']
                self.assertEqual((anchor['context_prefix'], anchor['context_suffix']), ('ban', ' END'))
                page.locator('.attachment-anchor').screenshot(path=str(self.out / f'draft-new-{width}.png'))
                results.append({'width': width, 'anchor': anchor})
        (self.out / 'draft-new-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')

    def open_excerpt_editor(self, page, title):
        page.goto(self.url + '/#library?q=' + title)
        page.get_by_role('button', name=title, exact=True).first.click()
        page.get_by_text('整理、编辑与核对', exact=True).click()
        page.get_by_role('button', name='编辑内容', exact=True).click()
        form = page.locator('form[data-form=record]')
        expect(form).not_to_have_attribute('inert')
        return form

    def test_saved_anchor_draft_retains_position_and_clears_it_after_reference_edits(self):
        results = []
        for width in [1366, 390]:
            for field, value, prefix, suffix in [('evidence_selection_start', 3, 'ban', ' ana END'), ('evidence_occurrence', 1, 'banana ', ' END')]:
                with self.subTest(width=width, field=field), self.browser.new_context(viewport={'width': width, 'height': 900}) as context:
                    request = context.request
                    token = request.get(self.url + '/api/session').json()['csrf']
                    token = request.post(self.url + '/api/login', data={'username': 'researcher', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': token}).json()['csrf']
                    headers = {'X-CSRF-Token': token}
                    response = request.post(self.url + '/api/records', multipart={'data': json.dumps({'kind': 'report', 'title': 'Edit draft original', 'sharing_confirmed': True}), 'file': {'name': 'edit.txt', 'mimeType': 'text/plain', 'buffer': b'banana ana END'}}, headers=headers)
                    self.assertEqual(response.status, 201, response.text())
                    original = request.get(self.url + '/api/records/' + response.json()['id']).json()
                    aid = original['attachments'][0]['id']
                    title = f'EditDraft{width}{field}'
                    response = request.post(self.url + '/api/records', data={'kind': 'research_note', 'title': title, 'evidence_record_id': original['id'], 'evidence_attachment_id': aid, 'quote': 'ana', 'locator': '第 1 行', field: value}, headers=headers)
                    self.assertEqual(response.status, 201, response.text())
                    nid = response.json()['id']
                    page = context.new_page()
                    form = self.open_excerpt_editor(page, title)
                    expect(form.locator('[name=' + field + ']')).to_have_value(str(value))
                    form.locator('[name=interpretation]').fill('Retain the selected original instance')
                    form = self.restore_excerpt_draft(page)
                    expect(form.locator('[name=' + field + ']')).to_have_value(str(value))
                    form.locator('[name=refresh_evidence]').check()
                    form.locator('[type=submit]').click()
                    expect(page.get_by_text('已在指定位置的提取文字中匹配', exact=False).first).to_be_visible()
                    anchor = request.get(self.url + '/api/records/' + nid).json()['evidence_snapshot']['attachment_anchor']
                    self.assertEqual((anchor['context_prefix'], anchor['context_suffix']), (prefix, suffix))
                    self.assertEqual(anchor['selection_start' if field == 'evidence_selection_start' else 'occurrence'], value)
                    for changed, replacement in [('quote', 'END'), ('locator', '第 2 行'), ('evidence_attachment_id', '')]:
                        form = self.open_excerpt_editor(page, title)
                        discard = page.get_by_role('button', name='舍弃这份草稿', exact=True)
                        if discard.count():
                            discard.click()
                        expect(form.locator('[name=' + field + ']')).to_have_value(str(value))
                        control = form.locator('[name=' + changed + ']')
                        if changed == 'evidence_attachment_id':
                            control.select_option(replacement)
                        else:
                            control.fill(replacement)
                        expect(form.locator('[name=' + field + ']')).to_have_count(0)
                        form = self.restore_excerpt_draft(page)
                        expect(form.locator('[name=' + changed + ']')).to_have_value(replacement)
                        expect(form.locator('[name=' + field + ']')).to_have_count(0)
                        page.get_by_role('button', name='关闭并保留草稿', exact=True).click()
                    results.append({'width': width, 'field': field, 'anchor_after_draft_refresh': anchor, 'invalidated_by': ['quote', 'locator', 'evidence_attachment_id']})
        (self.out / 'draft-edit-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    unittest.main(verbosity=2)
