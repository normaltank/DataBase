"""#37 actual-form regression, isolated port 8853 and synthetic external metadata.

The app, browser, save transaction and read APIs are real. Only the external
provider document is controlled; this does not test provider/network coverage.
Set DATABASE_BROWSER_EXECUTABLE and optionally DATABASE_BROWSER_EVIDENCE.
"""
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
from platform_app import intake

URL = 'http://127.0.0.1:8853'


class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


class IntakeFormBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('DATABASE_BROWSER_EVIDENCE') or tempfile.mkdtemp(prefix='intake-form-browser-'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.original_fetch = intake.fetch_document
        def fetch(url, deadline):
            if cls.failure:
                raise intake.AcquisitionError('Synthetic external provider unavailable')
            return dict(url=url, content_type='application/json', text=json.dumps({'message': {
                'DOI': cls.doi, 'title': [cls.title],
                'author': [{'given': 'Ada', 'family': 'Form'}],
                'container-title': ['Synthetic Form Journal'], 'language': cls.language,
                'published': {'date-parts': [[2026, 10, 26]]},
                'resource': {'primary': {'URL': 'https://example.org/'+cls.doi.split('/')[-1]}}, 'abstract': 'Synthetic form abstract'}}))
        intake.fetch_document = fetch
        cls.server = make_server('127.0.0.1', 8853, create_app(Path(tempfile.mkdtemp(prefix='run-', dir=cls.out)) / 'data', testing=True), threaded=True, request_handler=QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None)
        print('Evidence:', cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.thread.join()
        intake.fetch_document = cls.original_fetch

    def setUp(self):
        type(self).doi = '10.5555/form-primary'
        type(self).title = 'Synthetic form article'
        type(self).failure = False
        type(self).language = 'en'
        self.context = self.browser.new_context(viewport={'width': 1366, 'height': 900})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.goto(URL)
        self.page.get_by_role('button', name='研究员', exact=True).click()
        expect(self.page.get_by_role('button', name='退出登录', exact=True)).to_be_visible()
        self.page.locator('[data-action=new-record]').first.click()
        self.form = self.page.locator('form[data-form=record]')
        expect(self.form).not_to_have_attribute('inert')

    def tearDown(self):
        self.page.screenshot(path=str(self.out / (self._testMethodName + '.png')), full_page=True)
        self.assertEqual(self.errors, [])

    def fetch(self, value='10.5555/form-primary'):
        self.form.locator('[name=intake_input]').fill(value)
        self.form.locator('[data-intake-fetch]').click()
        expect(self.form.locator('[data-intake-status]')).not_to_contain_text('正在', timeout=10000)

    def create_person(self):
        token = self.context.request.get(URL+'/api/session').json()['csrf']
        response = self.context.request.post(URL+'/api/people', data={'name': 'Ada Form', 'change_note': 'Synthetic browser identity'}, headers={'X-CSRF-Token': token})
        self.assertTrue(response.ok, response.text())
        return response.json()['id']

    def test_identify_fills_the_real_form_and_saves_pending_authors_and_evidence(self):
        self.fetch()
        expect(self.form.locator('[name=title]')).to_have_value('Synthetic form article')
        for field, expected in {'authors': 'Ada Form', 'published_on': '2026-10-26',
                                'doi': '10.5555/form-primary', 'publication_title': 'Synthetic Form Journal',
                                'url': 'https://example.org/form-primary', 'language': 'en'}.items():
            expect(self.form.locator('[name='+field+']')).to_have_value(expected)
        self.form.get_by_role('button', name='保存内容', exact=True).click()
        expect(self.form).to_have_count(0)
        records = self.context.request.get(URL+'/api/records?q=Synthetic%20form%20article').json()
        self.assertEqual(records['total'], 1)
        record = self.context.request.get(URL+'/api/records/'+records['items'][0]['id']).json()
        self.assertEqual(record['title'], 'Synthetic form article')
        self.assertEqual(record['doi'], '10.5555/form-primary')
        self.assertEqual(record['intake_evidence'][0]['fields']['title'], 'Synthetic form article')
        bylines = self.context.request.get(URL+'/api/records/'+record['id']+'/bylines').json()['items']
        self.assertEqual([(item['raw_name'], item['status']) for item in bylines], [('Ada Form', 'pending')])

    def test_changed_result_updates_previous_automatic_fields_only_after_explicit_choice(self):
        self.form.locator('[name=title]').fill('My own title')
        self.fetch()
        expect(self.form.locator('[name=title]')).to_have_value('My own title')
        self.form.locator('[name=published_on]').fill('2025')
        self.fetch()
        expect(self.form.locator('[name=published_on]')).to_have_value('2025')
        type(self).doi = '10.5555/form-second'
        type(self).title = 'Second external article'
        self.fetch('10.5555/form-second')
        expect(self.form.locator('[data-intake-new-result]')).to_be_visible()
        expect(self.form.locator('[name=doi]')).to_have_value('10.5555/form-primary')
        self.form.locator('[data-intake-new-result]').click()
        expect(self.form.locator('[name=doi]')).to_have_value('10.5555/form-second')
        expect(self.form.locator('[name=title]')).to_have_value('My own title')
        expect(self.form.locator('[name=published_on]')).to_have_value('2025')

    def test_optional_identity_error_is_near_the_selection_and_keeps_basic_fields(self):
        self.create_person()
        type(self).doi = '10.5555/form-identity'
        self.fetch('10.5555/form-identity')
        review = self.form.locator('[data-intake-review]')
        if review.count():
            review.locator('summary').first.click()
        author = self.form.locator('[data-intake-author]').first
        author.locator('[data-intake-confirm]').check()
        self.form.locator('[data-intake-apply]').click()
        expect(self.form.locator('[name=title]')).to_have_value('Synthetic form article')
        error = author.locator('[data-intake-row-error]')
        expect(error).to_contain_text('选择对应身份')
        self.assertGreaterEqual(error.bounding_box()['y'], 0)
        self.assertLess(error.bounding_box()['y'], 900)
        expect(error).to_be_focused()
        author.locator('[data-intake-target]').select_option(index=1)
        self.form.locator('[data-intake-apply]').click()
        expect(error).to_contain_text('可核查的依据')
        author.locator('[data-intake-evidence]').fill('Checked against synthetic author page')
        self.form.locator('[data-intake-apply]').click()
        expect(self.form.locator('[data-intake-apply-status]')).to_contain_text('已应用')
        with self.page.expect_response(lambda response: response.url==URL+'/api/records' and response.request.method=='POST') as saved_response:
            self.form.get_by_role('button', name='保存内容', exact=True).click()
        expect(self.form).to_have_count(0)
        saved = saved_response.value.json()
        bylines = self.context.request.get(URL+'/api/records/'+saved['id']+'/bylines').json()['items']
        self.assertEqual(bylines[0]['status'], 'confirmed')
        self.assertEqual(bylines[0]['evidence'], 'Checked against synthetic author page')

    def test_common_fields_and_optional_information_work_at_desktop_and_phone_width(self):
        more = self.form.locator('[data-record-more]')
        expect(more).not_to_have_attribute('open')
        expect(self.form.locator('[name=doi]')).to_be_visible()
        expect(self.form.locator('[name=keywords]')).not_to_be_visible()
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.form.locator('[name=intake_input]').fill('10.5555/form-primary')
        self.form.locator('[name=intake_input]').press('Enter')
        expect(self.form.locator('[name=title]')).to_have_value('Synthetic form article')
        self.assertTrue(self.page.locator('html').evaluate('(el)=>el.scrollWidth<=innerWidth'))
        expect(self.form.locator('[name=title]')).to_be_in_viewport()
        self.page.screenshot(path=str(self.out / 'phone-filled.png'), full_page=True)
        more.locator('summary').first.click()
        self.form.locator('[name=keywords]').fill('Optional retained keyword')
        more.locator('summary').first.click()
        expect(self.form.locator('[name=keywords]')).to_have_value('Optional retained keyword')
        self.form.locator('[name=kind]').select_option('research_note')
        expect(self.form.locator('[name=doi]')).not_to_be_visible()
        more.locator('summary').first.click()
        expect(self.form.locator('[name=doi]')).to_have_value('10.5555/form-primary')

    def test_failure_late_response_and_draft_restore_keep_the_selected_article(self):
        type(self).doi = '10.5555/form-draft'
        self.fetch('10.5555/form-draft')
        self.form.locator('[name=title]').fill('My draft title')
        self.form.locator('[data-action=close]').click()
        self.page.locator('[data-action=new-record]').first.click()
        expect(self.form).not_to_have_attribute('inert')
        self.form.locator('[data-action=restore-draft]').click()
        expect(self.form.locator('[name=title]')).to_have_value('My draft title')
        expect(self.form.locator('[name=doi]')).to_have_value('10.5555/form-draft')
        def late_response(route):
            response = route.fetch()
            self.form.locator('[name=intake_input]').fill('10.5555/changed-while-loading')
            route.fulfill(response=response)
        self.page.route('**/api/intake/preview', late_response, times=1)
        self.form.locator('[data-intake-fetch]').click()
        expect(self.form.locator('[data-intake-status]')).to_contain_text('旧请求不会应用')
        expect(self.form.locator('[name=title]')).to_have_value('My draft title')
        expect(self.form.locator('[name=doi]')).to_have_value('10.5555/form-draft')
        type(self).failure = True
        self.fetch('https://example.org/unavailable')
        expect(self.form.locator('[data-intake-status]')).to_contain_text('已有输入保留')
        expect(self.form.locator('[name=title]')).to_have_value('My draft title')
        expect(self.form.locator('[name=doi]')).to_have_value('10.5555/form-draft')
        self.form.get_by_role('button', name='保存内容', exact=True).click()
        expect(self.form).to_have_count(0)
        records = self.context.request.get(URL+'/api/records?q=My%20draft%20title').json()
        self.assertEqual(records['total'], 1)
        record = self.context.request.get(URL+'/api/records/'+records['items'][0]['id']).json()
        self.assertEqual(record['intake_evidence'][0]['input'], '10.5555/form-draft')

    def test_title_only_manual_save_and_duplicate_save_keep_input(self):
        self.form.locator('[name=title]').fill('Only a manually entered title')
        self.form.get_by_role('button', name='保存内容', exact=True).click()
        expect(self.form).to_have_count(0)
        self.page.locator('#modal-root [data-action=close]').first.click()
        self.page.locator('[data-action=new-record]').first.click()
        expect(self.form).not_to_have_attribute('inert')
        type(self).doi = '10.5555/form-duplicate'
        token = self.context.request.get(URL+'/api/session').json()['csrf']
        created = self.context.request.post(URL+'/api/records', data={'kind': 'report', 'title': 'Existing DOI fixture', 'doi': '10.5555/form-duplicate'}, headers={'X-CSRF-Token': token})
        self.assertEqual(created.status, 201, created.text())
        self.fetch('10.5555/form-duplicate')
        self.form.get_by_role('button', name='保存内容', exact=True).click()
        expect(self.form.locator('.form-error')).to_contain_text('重复')
        expect(self.form.locator('[name=title]')).to_have_value('Synthetic form article')

    def test_switch_to_research_content_requires_explicit_detach_and_preserves_fields(self):
        type(self).doi = '10.5555/form-research'
        self.fetch('10.5555/form-research')
        self.form.locator('[name=kind]').select_option('research_note')
        expect(self.form.locator('[data-intake-kind-warning]')).to_be_visible()
        self.form.locator('[data-intake-detach]').click()
        expect(self.form.locator('[name=title]')).to_have_value('Synthetic form article')
        expect(self.form.locator('[data-intake-editor]')).not_to_be_visible()
        self.form.get_by_role('button', name='保存内容', exact=True).click()
        expect(self.form).to_have_count(0)

    def test_switch_kind_during_request_does_not_attach_a_hidden_result(self):
        def late_response(route):
            response = route.fetch()
            self.form.locator('[name=kind]').select_option('research_note')
            self.form.locator('[name=title]').fill('Research note while request is pending')
            route.fulfill(response=response)
        self.page.route('**/api/intake/preview', late_response, times=1)
        self.fetch()
        expect(self.form.locator('[name=doi]')).to_have_value('')
        self.form.get_by_role('button', name='保存内容', exact=True).click()
        expect(self.form).to_have_count(0)

    def test_nonpreset_language_survives_draft_restore_and_saved_record_edit(self):
        type(self).doi = '10.5555/form-language-draft'
        type(self).title = 'Synthetic Spanish language draft'
        type(self).language = 'es'
        self.fetch('10.5555/form-language-draft')
        self.form.locator('[data-record-more]>summary').click()
        expect(self.form.locator('[name=language]')).to_have_value('es')
        self.form.locator('[data-action=close]').click()
        self.page.locator('[data-action=new-record]').first.click()
        expect(self.form).not_to_have_attribute('inert')
        self.form.locator('[data-action=restore-draft]').click()
        self.form.locator('[data-record-more]>summary').click()
        expect(self.form.locator('[name=language]')).to_be_visible()
        expect(self.form.locator('[name=language]')).to_have_value('es')
        with self.page.expect_response(lambda response: response.url==URL+'/api/records' and response.request.method=='POST') as saved_response:
            self.form.get_by_role('button', name='保存内容', exact=True).click()
        expect(self.form).to_have_count(0)
        saved = saved_response.value.json()
        detail = self.context.request.get(URL+'/api/records/'+saved['id']).json()
        self.assertEqual(detail['language'], 'es')
        self.page.locator('.ux-maintenance>summary').click()
        self.page.locator('[data-action=edit-record][data-id="'+saved['id']+'"]').click()
        expect(self.form).not_to_have_attribute('inert')
        self.form.locator('[data-record-more]>summary').click()
        expect(self.form.locator('[name=language]')).to_have_value('es')
        self.form.locator('[name=title]').fill('Spanish article with unrelated title edit')
        self.form.get_by_role('button', name='保存修订', exact=True).click()
        expect(self.form).to_have_count(0)
        edited = self.context.request.get(URL+'/api/records/'+saved['id']).json()
        self.assertEqual(edited['language'], 'es')
        self.assertEqual(edited['title'], 'Spanish article with unrelated title edit')


if __name__ == '__main__':
    unittest.main()
