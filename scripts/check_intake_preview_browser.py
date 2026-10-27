"""Synthetic #32 preview editing regression; isolated port 8851, no real network."""
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

PORT = int(os.environ.get('DATABASE_INTAKE_PREVIEW_PORT', '8851'))
URL = 'http://127.0.0.1:'+str(PORT)
class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


class IntakePreviewBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='intake-preview-browser-')
        cls.title = 'Synthetic preview title'
        cls.original_fetch = intake.fetch_document
        def fetch(url, deadline):
            return dict(url=url, content_type='application/json', text=json.dumps({'message':{
                'DOI':'10.5555/preview-regression', 'title':[cls.title],
                'author':[{'given':'Ada','family':'Preview'}], 'container-title':['Synthetic Journal'],
                'published':{'date-parts':[[2026,10,26]]}, 'abstract':'Synthetic abstract',
                'URL':'https://example.org/preview'}}))
        intake.fetch_document = fetch
        cls.server = make_server('127.0.0.1',PORT,create_app(cls.temp.name,testing=True),threaded=True,request_handler=QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.thread.join()
        intake.fetch_document = cls.original_fetch
        cls.temp.cleanup()

    def test_repeated_preview_preserves_manual_work_and_excludes_old_response(self):
        context = self.browser.new_context(viewport={'width':1280,'height':900})
        self.addCleanup(context.close)
        page = context.new_page()
        page.goto(URL)
        page.get_by_role('button',name='研究员',exact=True).click()
        expect(page.get_by_role('button',name='退出登录',exact=True)).to_be_visible()
        token = context.request.get(URL+'/api/session').json()['csrf']
        person = context.request.post(URL+'/api/people',data=dict(name='Ada Preview',change_note='Synthetic browser fixture'),headers={'X-CSRF-Token':token})
        self.assertTrue(person.ok,person.text())
        page.locator('[data-action=new-record]').first.click()
        form = page.locator('form[data-form=record]')
        expect(form).not_to_have_attribute('inert', '')
        form.locator('[name=title]').fill('Existing title')
        form.locator('[name=intake_input]').fill('10.5555/preview-regression')
        form.locator('[data-intake-fetch]').click()
        expect(form.locator('[name=published_on]')).to_have_value('2026-10-26')
        form.locator('[data-intake-review]>summary').click()
        expect(form.locator('[data-intake-author="0"]')).to_be_visible()
        author=form.locator('[data-intake-author="0"]')
        author.locator('[data-intake-name]').fill('Hand edited signature')
        author.locator('[data-intake-target]').select_option(index=1)
        author.locator('[data-intake-confirm]').check()
        author.locator('[data-intake-evidence]').fill('Checked against synthetic author page')
        form.locator('[data-intake-replace=title]').check()
        form.locator('[data-intake-fetch]').click()
        expect(form.locator('[data-intake-status]')).not_to_contain_text('正在')
        expect(author.locator('[data-intake-name]')).to_have_value('Hand edited signature')
        expect(author.locator('[data-intake-confirm]')).to_be_checked()
        expect(author.locator('[data-intake-evidence]')).to_have_value('Checked against synthetic author page')
        expect(author.locator('[data-intake-target]')).not_to_have_value('')
        expect(form.locator('[data-intake-replace=title]')).to_be_checked()
        self.assertEqual(form.locator('.intake-field > strong').all_text_contents(), ['题名','原始署名','刊物名称','发表日期','DOI','原文链接','摘要'])
        self.assertEqual(form.locator('[data-intake-replace]').count(),1)
        self.assertNotIn('{}',form.locator('.intake-authors').inner_text())
        # A changed provider response must wait for an explicit decision.
        type(self).title='Updated provider title'
        form.locator('[data-intake-fetch]').click()
        expect(form.locator('[data-intake-new-result]')).to_be_visible()
        expect(author.locator('[data-intake-name]')).to_have_value('Hand edited signature')
        expect(form.locator('.intake-field').first).to_contain_text('Synthetic preview title')
        form.locator('[data-intake-keep-result]').click()
        expect(author.locator('[data-intake-evidence]')).to_have_value('Checked against synthetic author page')
        # An old HTTP result cannot replace the preview after the input changes.
        def old_response(route):
            response=route.fetch()
            form.locator('[name=intake_input]').fill('10.5555/different-input')
            route.fulfill(response=response)
        page.route('**/api/intake/preview',old_response,times=1)
        form.locator('[data-intake-fetch]').click()
        expect(form.locator('[data-intake-status]')).to_contain_text('旧请求不会应用')
        expect(author.locator('[data-intake-name]')).to_have_value('Hand edited signature')
        expect(form.locator('[data-intake-new-result]')).not_to_be_visible()
        # Existing work survives closing and restoring the actual local draft.
        form.locator('[data-action=close]').click()
        page.locator('[data-action=new-record]').first.click()
        expect(form).not_to_have_attribute('inert', '')
        form.locator('[data-action=restore-draft]').click()
        form.locator('[data-intake-review]>summary').click()
        expect(author.locator('[data-intake-name]')).to_have_value('Hand edited signature')
        expect(author.locator('[data-intake-confirm]')).to_be_checked()
        form.locator('[name=intake_input]').fill('10.5555/preview-regression')
        form.locator('[data-intake-fetch]').click()
        expect(form.locator('[data-intake-new-result]')).to_be_visible()
        form.locator('[data-intake-new-result]').click()
        expect(form.locator('.intake-field').first).to_contain_text('Updated provider title')
        expect(form.locator('[name=title]')).to_have_value('Existing title')
        expect(author.locator('[data-intake-name]')).to_have_value('Ada Preview')
        page.set_viewport_size({'width':390,'height':844})
        self.assertTrue(page.locator('html').evaluate('(el)=>el.scrollWidth<=innerWidth'))
        # Closing an editor while a request returns also isolates the response.
        def closed_response(route):
            response=route.fetch()
            form.locator('[data-action=close]').click()
            page.locator('[data-action=new-record]').first.click()
            route.fulfill(response=response)
        page.route('**/api/intake/preview',closed_response,times=1)
        form.locator('[data-intake-fetch]').click()
        expect(form.locator('[data-intake-preview]')).to_be_empty()


if __name__ == '__main__':
    unittest.main()
