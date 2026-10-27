"""Synthetic RIS selection/download and stale-response checks in a real browser."""
import json
import os
import subprocess
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


class RisExportBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('DATABASE_BROWSER_EVIDENCE') or tempfile.mkdtemp(prefix='ris-export-browser-'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.app = create_app(cls.out / 'data', testing=True)
        cls.server = make_server('127.0.0.1', 8862, cls.app, threaded=True, request_handler=QuietHandler)
        cls.url = 'http://127.0.0.1:8862'
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None)
        print('Evidence:', cls.out, flush=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.thread.join()

    def login(self, request, username):
        token = request.get(self.url + '/api/session').json()['csrf']
        response = request.post(self.url + '/api/login', data={'username':username, 'password':'LocalDemo2026!'}, headers={'X-CSRF-Token':token})
        self.assertEqual(response.status, 200)
        return response.json()['csrf']

    def test_selected_download_and_atomic_failure(self):
        for width in (1366, 390):
            with self.subTest(width=width):
                context = self.browser.new_context(viewport={'width':width, 'height':900}, accept_downloads=True)
                self.addCleanup(context.close)
                request = context.request
                csrf = self.login(request, 'researcher')
                title = 'RIS browser ' + str(width)
                response = request.post(self.url + '/api/records', data={'kind':'report', 'title':title, 'authors':'合成署名, Unit A'}, headers={'X-CSRF-Token':csrf})
                self.assertEqual(response.status, 201, response.text())
                rid = response.json()['id']
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.url + '/#library?q=' + title)
                expect(page.locator('.library-workspace')).to_be_visible()
                page.locator('[data-library-select]').first.check()
                button = page.get_by_role('button', name='导出选中 RIS', exact=True)
                expect(button).to_be_visible()
                with page.expect_download() as pending:
                    button.click()
                download = pending.value
                self.assertEqual(download.suggested_filename, 'research-selected-records.ris')
                output = self.out / ('selected-' + str(width) + '.ris')
                download.save_as(output)
                self.assertIn(('TI  - ' + title + '\r\n').encode(), output.read_bytes())
                self.assertTrue(page.locator('[data-library-select]').first.is_checked())
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                page.screenshot(path=str(self.out / ('download-' + str(width) + '.png')), full_page=True)
                # A mixed selection fails without silently downloading just the report.
                note = request.post(self.url + '/api/records', data={'kind':'research_note', 'title':title+' note'}, headers={'X-CSRF-Token':csrf})
                self.assertEqual(note.status, 201, note.text())
                page.reload()
                page.locator('[data-library-select="'+rid+'"]').check()
                page.locator('[data-library-select="'+note.json()['id']+'"]').check()
                downloads = []
                page.on('download', lambda download: downloads.append(download.suggested_filename))
                button.click()
                expect(page.locator('[data-library-batch-status]')).to_contain_text('不支持 RIS')
                self.assertEqual(page.locator('[data-library-select]:checked').count(), 2)
                self.assertEqual(downloads, [])
                page.screenshot(path=str(self.out / ('mixed-' + str(width) + '.png')), full_page=True)
                owner = self.browser.new_context()
                self.addCleanup(owner.close)
                owner_csrf = self.login(owner.request, 'researcher')
                page.get_by_role('button', name='退出登录', exact=True).click()
                page.get_by_role('button', name='协作同事', exact=True).click()
                expect(page.locator('.library-workspace')).to_be_visible()
                page.locator('[data-library-select="'+rid+'"]').check()
                changed = owner.request.put(self.url+'/api/records/'+rid, data={'version':1, 'visibility':'restricted'}, headers={'X-CSRF-Token':owner_csrf})
                self.assertEqual(changed.status, 200, changed.text())
                button.click()
                expect(page.locator('[data-library-batch-status]')).to_contain_text('已无访问权限')
                self.assertTrue(page.locator('[data-library-select="'+rid+'"]').is_checked())
                self.assertEqual(downloads, [])
                page.screenshot(path=str(self.out / ('permission-' + str(width) + '.png')), full_page=True)
                changed = owner.request.put(self.url+'/api/records/'+rid, data={'version':2, 'visibility':'shared'}, headers={'X-CSRF-Token':owner_csrf})
                self.assertEqual(changed.status, 200)
                held = []
                def hold(route):
                    response = route.fetch()
                    self.assertEqual(response.status, 200)
                    held.append((route,response))
                page.route('**/api/library/bulk/export-ris', hold, times=1)
                button.click()
                expect(button).to_be_disabled()
                page.wait_for_function('document.querySelector("[data-library-batch-status]").textContent.includes("正在生成")')
                # Another tab announces an account change while the download is late.
                other = context.new_page()
                other.goto(self.url+'/#library')
                other.get_by_role('button', name='退出登录', exact=True).click()
                other.get_by_role('button', name='研究员', exact=True).click()
                expect(page.locator('[data-library-select]:checked')).to_have_count(0)
                self.assertEqual(len(held), 1)
                page.bring_to_front()
                with page.expect_response('**/api/library/bulk/export-ris'):
                    route,response = held[0]
                    route.fulfill(response=response)
                page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                self.assertEqual(downloads, [])
                expect(page.locator('[data-library-select]:checked')).to_have_count(0)
                page.screenshot(path=str(self.out / ('account-' + str(width) + '.png')), full_page=True)
                self.assertEqual(errors, [])

    def test_core_selected_download_passes_independent_fixed_expectations(self):
        context = self.browser.new_context(accept_downloads=True)
        self.addCleanup(context.close)
        csrf = self.login(context.request, 'researcher')
        fixture = ROOT/'tests/fixtures/ris_independent'
        preview = context.request.post(self.url+'/api/ris/preview', multipart={'file':{'name':'core.ris', 'mimeType':'text/plain', 'buffer':(fixture/'01_core_utf8_lf.ris').read_bytes()}}, headers={'X-CSRF-Token':csrf})
        self.assertEqual(preview.status, 200, preview.text())
        ids = []
        for item in preview.json()['items']:
            saved = context.request.post(self.url+'/api/records', data=dict(**item['fields'], ris_token=item['token']), headers={'X-CSRF-Token':csrf})
            self.assertEqual(saved.status, 201, saved.text())
            ids.append(saved.json()['id'])
        for width in (1366,390):
            page = context.new_page()
            page.set_viewport_size({'width':width,'height':900})
            page.goto(self.url+'/#library?q=Synthetic')
            for rid in ids:
                page.locator('[data-library-select="'+rid+'"]').check()
            with page.expect_download() as pending:
                page.get_by_role('button',name='导出选中 RIS',exact=True).click()
            output = self.out/('core-'+str(width)+'.ris')
            pending.value.save_as(output)
            result = subprocess.run([sys.executable,str(fixture/'verify_independent.py'),str(output)],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            with page.expect_download() as csv_download:
                page.get_by_role('button',name='导出选中 CSV',exact=True).click()
            csv_download.value.save_as(self.out/('core-'+str(width)+'.csv'))
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            page.screenshot(path=str(self.out/('core-'+str(width)+'.png')),full_page=True)
            page.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
