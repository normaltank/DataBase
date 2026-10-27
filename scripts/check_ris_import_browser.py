"""Actual RIS form journey, synthetic Temp database, isolated port 8861."""
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

PORT = int(os.environ.get('DATABASE_BROWSER_PORT', '8861'))
URL = 'http://127.0.0.1:' + str(PORT)
SAMPLE = b'TY  - JOUR\nTI  - Browser first\nAU  - Synthetic, Person\nPY  - 2024/05/\nER  -\nTY  - WEB\nTI  - Browser second\nER  -\nTY  - BOOK\nTI  - Unsupported book\nER  -\n'


class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


class RisBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix='ris-browser-'))
        cls.server = make_server('127.0.0.1', PORT, create_app(cls.out / 'data', testing=True), threaded=True, request_handler=QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None)
        print('Evidence:', cls.out, flush=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.thread.join()

    def test_journey_at_both_widths(self):
        for width in [1366, 390]:
            with self.subTest(width=width):
                context = self.browser.new_context(viewport={'width': width, 'height': 900})
                self.addCleanup(context.close)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(URL + '/#library')
                page.get_by_role('button', name='研究员', exact=True).click()
                expect(page.get_by_role('button',name='退出登录',exact=True)).to_be_visible()
                csrf=context.request.get(URL+'/api/session').json()['csrf']
                person=context.request.post(URL+'/api/people',data={'name':'Synthetic, Person','change_note':'Synthetic browser identity'},headers={'X-CSRF-Token':csrf}).json()['id']
                page.get_by_role('button', name='导入 RIS 文件', exact=True).click()
                sample = SAMPLE.replace(b'Unsupported book', ('Unsupported book ' + str(width)).encode())
                page.locator('[data-ris-file]').set_input_files({'name': 'browser.ris', 'mimeType': 'application/x-research-info-systems', 'buffer': sample})
                page.locator('[data-ris-preview]').click()
                page.locator('[data-ris-edit="0"]').click()
                form = page.locator('form[data-form=record]')
                expect(form.locator('[name=title]')).to_have_value('Browser first')
                form.locator('[name=title]').fill('Edited first ' + str(width))
                form.locator('[data-intake-review] summary').click()
                form.locator('[data-intake-target]').select_option('person:'+person)
                form.locator('[data-intake-confirm]').check()
                form.locator('[data-intake-evidence]').fill('Synthetic homepage checked manually')
                form.locator('[data-intake-apply]').click()
                expect(form.locator('[data-intake-detach]')).to_have_count(0)
                page.locator('[data-ris-edit="1"]').click()
                page.locator('[data-ris-edit="0"]').click()
                expect(form.locator('[name=title]')).to_have_value('Edited first ' + str(width))
                expect(form.locator('[data-intake-target]')).to_have_value('person:'+person)
                expect(form.locator('[data-intake-confirm]')).to_be_checked()
                form.locator('[name=title]').scroll_into_view_if_needed()
                page.screenshot(path=str(self.out/('editor-'+str(width)+'.png')),full_page=True)
                page.get_by_role('button', name='关闭并保留草稿', exact=True).click()
                page.get_by_role('button', name='导入 RIS 文件', exact=True).click()
                page.locator('[data-ris-edit="0"]').click()
                expect(form.locator('[name=title]')).to_have_value('Edited first ' + str(width))
                form.get_by_role('button', name='保存本条并接续', exact=True).click()
                expect(page.locator('[data-ris-queue]')).to_contain_text('已保存')
                expect(form.locator('[name=title]')).to_have_value('Browser second')
                records=context.request.get(URL+'/api/records',params={'q':'Edited first '+str(width)}).json()
                bylines=context.request.get(URL+'/api/records/'+records['items'][0]['id']+'/bylines').json()['items']
                self.assertEqual(bylines[0]['status'],'confirmed')
                self.assertEqual(bylines[0]['target_id'],person)
                form.get_by_role('button', name='保存本条并接续', exact=True).click()
                expect(page.locator('[data-ris-queue]')).to_contain_text('已保存', timeout=10000)
                expect(page.locator('[data-ris-queue]')).to_contain_text('未支持')
                page.screenshot(path=str(self.out / ('journey-' + str(width) + '.png')), full_page=True)
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                self.assertEqual(errors, [])

    def test_multiple_related_sources_survive_switch_close_restore_and_save(self):
        for width in [1366, 390]:
            with self.subTest(width=width):
                context = self.browser.new_context(viewport={'width':width,'height':900})
                self.addCleanup(context.close)
                page = context.new_page()
                page.goto(URL+'/#library')
                page.get_by_role('button',name='研究员',exact=True).click()
                expect(page.get_by_role('button',name='退出登录',exact=True)).to_be_visible()
                csrf = context.request.get(URL+'/api/session').json()['csrf']
                ids = []
                for name in ['First related journal ', 'Second related journal ']:
                    result = context.request.post(URL+'/api/sources',data={'name':name+str(width),'kind':'journal'},headers={'X-CSRF-Token':csrf})
                    self.assertEqual(result.status,201,result.text())
                    ids.append(result.json()['id'])
                page.reload()
                page.get_by_role('button',name='导入 RIS 文件',exact=True).click()
                sample = ('TY  - GEN\nTI  - Multiple sources '+str(width)+'\nER  -\nTY  - GEN\nTI  - Next item\nER  -\n').encode()
                page.locator('[data-ris-file]').set_input_files({'name':'multiple-sources.ris','mimeType':'text/plain','buffer':sample})
                page.locator('[data-ris-preview]').click()
                page.locator('[data-ris-edit="0"]').click()
                form = page.locator('form[data-form=record]')
                form.locator('[data-record-more] > summary').click()
                picker = form.locator('[data-source-select]').filter(has=page.locator('[name=related_source_ids]'))
                picker.locator('[data-source-disclosure] > summary').click()
                for sid in ids:
                    picker.locator('[data-source-option="'+sid+'"]').check()
                self.assertEqual(form.locator('[name=related_source_ids]').evaluate('(el)=>Array.from(el.selectedOptions,o=>o.value)'),ids)
                picker.locator('[data-source-selected]').scroll_into_view_if_needed()
                page.screenshot(path=str(self.out/('multiple-selected-'+str(width)+'.png')),full_page=True)
                page.locator('[data-ris-edit="1"]').click()
                page.locator('[data-ris-edit="0"]').click()
                selected = form.locator('[name=related_source_ids]').evaluate('(el)=>Array.from(el.selectedOptions,o=>o.value)')
                print('Related sources after switching:',width,selected,'expected:',ids,flush=True)
                form.locator('[data-record-more] > summary').click()
                picker.locator('[data-source-selected]').scroll_into_view_if_needed()
                page.screenshot(path=str(self.out/('multiple-switched-'+str(width)+'.png')),full_page=True)
                self.assertEqual(selected,ids)
                page.get_by_role('button',name='关闭并保留草稿',exact=True).click()
                page.get_by_role('button',name='导入 RIS 文件',exact=True).click()
                page.locator('[data-ris-edit="0"]').click()
                expect(form.get_by_role('button',name='保存本条并接续',exact=True)).to_be_enabled()
                self.assertEqual(form.locator('[name=related_source_ids]').evaluate('(el)=>Array.from(el.selectedOptions,o=>o.value)'),ids)
                if width == 1366:
                    # A previous release stored the first selected source as a string.
                    page.get_by_role('button',name='关闭并保留草稿',exact=True).click()
                    page.evaluate('''sid=>{for(const key of Object.keys(localStorage)){
                        if(!key.endsWith(':ris:queue'))continue;
                        const draft=JSON.parse(localStorage.getItem(key));
                        const queue=JSON.parse(draft.values.ris_queue_json);
                        queue.items[0].edit.related_source_ids=sid;
                        draft.values.ris_queue_json=JSON.stringify(queue);
                        localStorage.setItem(key,JSON.stringify(draft));
                    }}''',ids[0])
                    page.get_by_role('button',name='导入 RIS 文件',exact=True).click()
                    page.locator('[data-ris-edit="0"]').click()
                    self.assertEqual(form.locator('[name=related_source_ids]').evaluate('(el)=>Array.from(el.selectedOptions,o=>o.value)'),[ids[0]])
                    form.locator('[data-record-more] > summary').click()
                    picker.locator('[data-source-disclosure] > summary').click()
                    picker.locator('[data-source-option="'+ids[1]+'"]').check()
                    print('Legacy string source draft restored and second source reselected',flush=True)
                form.get_by_role('button',name='保存本条并接续',exact=True).click()
                expect(page.locator('[data-ris-queue]')).to_contain_text('已保存')
                records = context.request.get(URL+'/api/records',params={'q':'Multiple sources '+str(width)}).json()['items']
                self.assertEqual(len(records),1)
                detail = context.request.get(URL+'/api/records/'+records[0]['id']).json()
                self.assertEqual(set(detail['related_source_ids']),set(ids))
                print('Related sources after saved detail:',width,detail['related_source_ids'],flush=True)
                page.screenshot(path=str(self.out/('multiple-saved-'+str(width)+'.png')),full_page=True)

    def test_editor_body_and_failed_response_keep_entire_queue_and_recover_saved_result(self):
        context = self.browser.new_context(viewport={'width':1366,'height':900})
        self.addCleanup(context.close)
        page = context.new_page()
        page.goto(URL+'/#library')
        page.get_by_role('button',name='研究员',exact=True).click()
        page.get_by_role('button',name='导入 RIS 文件',exact=True).click()
        page.locator('[data-ris-file]').set_input_files({'name':'recovery.ris','mimeType':'text/plain','buffer':SAMPLE.replace(b'Browser first',b'Recovery first')})
        page.locator('[data-ris-preview]').click()
        page.locator('[data-ris-edit="0"]').click()
        form = page.locator('form[data-form=record]')
        form.locator('[data-record-body] summary').click()
        form.locator('[data-rich-input]').fill('Human synthetic body must survive switching')
        form.locator('[name=file]').set_input_files({'name':'human.txt','mimeType':'text/plain','buffer':b'Human synthetic attachment'})
        form.locator('[data-record-attachments] summary').click()
        form.locator('[name=sharing_confirmed]').check()
        page.locator('[data-ris-edit="1"]').click()
        page.locator('[data-ris-edit="0"]').click()
        expect(form.locator('[data-rich-input]')).to_have_text('Human synthetic body must survive switching')
        expect(form.locator('[data-file-status]')).to_contain_text('human.txt')
        # The real server commits; its response is deliberately lost at the network seam.
        def lose_response(route):
            response = route.fetch()
            self.assertEqual(response.status,201,response.text())
            route.abort('failed')
        page.route('**/api/records',lose_response,times=1)
        form.get_by_role('button',name='保存本条并接续',exact=True).click()
        expect(form.locator('.form-error')).not_to_be_empty()
        expect(form.locator('[name=title]')).to_have_value('Recovery first')
        page.locator('[data-ris-recheck]').click()
        expect(page.locator('[data-ris-queue]')).to_contain_text('已保存')
        page.locator('[data-ris-edit="1"]').click()
        expect(form.locator('[name=title]')).to_have_value('Browser second')

    def test_account_switch_closes_old_queue_while_save_response_is_pending(self):
        context=self.browser.new_context(viewport={'width':1366,'height':900})
        self.addCleanup(context.close)
        page=context.new_page()
        page.goto(URL+'/#library')
        page.get_by_role('button',name='研究员',exact=True).click()
        page.get_by_role('button',name='导入 RIS 文件',exact=True).click()
        page.locator('[data-ris-file]').set_input_files({'name':'account.ris','mimeType':'text/plain','buffer':b'TY  - GEN\nTI  - Account protected input\nER  -\n'})
        page.locator('[data-ris-preview]').click()
        page.locator('[data-ris-edit="0"]').click()
        pending=[]
        def hold_response(route):
            response=route.fetch()
            self.assertEqual(response.status,201,response.text())
            pending.append((route,response))
        page.route('**/api/records',hold_response,times=1)
        page.get_by_role('button',name='保存本条并接续',exact=True).click()
        expect(page.locator('[data-form=record]')).to_have_attribute('inert','')
        other=context.new_page()
        other.goto(URL+'/#library')
        other.get_by_role('button',name='退出登录',exact=True).click()
        other.get_by_role('button',name='协作同事',exact=True).click()
        expect(page.locator('#modal-root [role=dialog]')).to_have_count(0)
        for route,response in pending:
            route.fulfill(response=response)
        expect(page.locator('#modal-root [role=dialog]')).to_have_count(0)
        page.get_by_role('button',name='导入 RIS 文件',exact=True).click()
        expect(page.locator('[data-ris-queue]')).to_have_count(0)

    def test_late_preview_cannot_replace_new_file_or_closed_account(self):
        context=self.browser.new_context(viewport={'width':1366,'height':900})
        self.addCleanup(context.close)
        page=context.new_page()
        page.goto(URL+'/#library')
        page.get_by_role('button',name='研究员',exact=True).click()
        page.get_by_role('button',name='导入 RIS 文件',exact=True).click()
        pending=[]
        def hold_preview(route):
            pending.append((route,route.fetch()))
        page.route('**/api/ris/preview',hold_preview,times=1)
        page.locator('[data-ris-file]').set_input_files({'name':'old.ris','mimeType':'text/plain','buffer':b'TY  - GEN\nTI  - Old delayed title\nER  -\n'})
        page.locator('[data-ris-preview]').click()
        expect(page.locator('[data-ris-status]')).to_contain_text('正在预览')
        page.locator('[data-ris-file]').set_input_files({'name':'new.ris','mimeType':'text/plain','buffer':b'TY  - GEN\nTI  - New selected title\nER  -\n'})
        for route,response in pending:
            route.fulfill(response=response)
        expect(page.locator('[data-ris-queue]')).to_have_count(0)
        page.locator('[data-ris-preview]').click()
        expect(page.locator('[data-ris-queue]')).to_contain_text('New selected title')
        page.locator('[data-ris-edit="0"]').click()
        page.locator('[name=title]').fill('Protected queue draft')
        page.get_by_role('button',name='关闭并保留草稿',exact=True).click()
        page.get_by_role('button',name='导入 RIS 文件',exact=True).click()
        page.locator('[data-ris-file]').set_input_files({'name':'replace.ris','mimeType':'text/plain','buffer':b'TY  - GEN\nTI  - Replacement delayed\nER  -\n'})
        page.locator('[data-ris-preview]').click()
        page.route('**/api/ris/preview',hold_preview,times=1)
        page.locator('[data-replace-confirmed]').click()
        page.get_by_role('button',name='关闭并保留草稿',exact=True).click()
        page.get_by_role('button',name='退出登录',exact=True).click()
        page.get_by_role('button',name='协作同事',exact=True).click()
        route,response=pending[-1]
        route.fulfill(response=response)
        expect(page.locator('#modal-root [role=dialog]')).to_have_count(0)
        page.get_by_role('button',name='导入 RIS 文件',exact=True).click()
        expect(page.locator('[data-ris-queue]')).to_have_count(0)
        page.get_by_role('button',name='关闭并保留草稿',exact=True).click()
        page.get_by_role('button',name='退出登录',exact=True).click()
        page.get_by_role('button',name='研究员',exact=True).click()
        page.get_by_role('button',name='导入 RIS 文件',exact=True).click()
        expect(page.locator('[data-ris-queue]')).to_contain_text('Protected queue draft')


if __name__ == '__main__':
    unittest.main(verbosity=2)
