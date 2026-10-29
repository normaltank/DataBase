"""#60 actual browser flows; all material is synthetic, port 8901 by default.

DATABASE_LAYOUT_EVIDENCE can reuse the baseline sample for screenshot comparison.
"""
import json
import os
import unittest

os.environ.setdefault('DATABASE_BROWSER_PORT', '8901')
import check_layout_browser as layout
URL = layout.URL
from playwright.sync_api import expect


class ReadingFeedBrowserTests(unittest.TestCase):
    stop_server = staticmethod(layout.LayoutBrowserTests.stop_server)
    tearDown = layout.LayoutBrowserTests.tearDown

    @classmethod
    def setUpClass(cls):
        layout.LayoutBrowserTests.setUpClass.__func__(cls)
        request=cls.playwright.request.new_context(base_url=URL)
        try:
            csrf=request.get('/api/session').json()['csrf']
            csrf=request.post('/api/login',data={'username':'researcher','password':'LocalDemo2026!'},headers={'X-CSRF-Token':csrf}).json()['csrf']
            for rid in cls.sample['records']:
                record=request.get('/api/records/'+rid).json()
                if record['chinese_title'] or record['chinese_abstract']:
                    response=request.put('/api/records/'+rid,data={'version':record['version'],'chinese_title':'','chinese_abstract':''},headers={'X-CSRF-Token':csrf})
                    assert response.ok,response.text()
            batch=request.post('/api/reading-batches',data={},headers={'X-CSRF-Token':csrf}).json()
            conditions={'q':'no synthetic baseline matches','batch_scope':'all','batch':batch['id']}
            shown=request.get('/api/records',params=conditions).json()
            response=request.post('/api/reading-batches/'+batch['id']+'/finish',data={'conditions':conditions,'confirmation':shown['reading_confirmation']},headers={'X-CSRF-Token':csrf})
            assert response.ok,response.text()
        finally:
            request.dispose()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1366, 'height': 900})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.page.set_default_timeout(8000)
        self.page.goto(URL)
        self.page.get_by_role('button', name='研究员', exact=True).click()
        expect(self.page.get_by_role('heading', name='资料', exact=True)).to_be_visible()
        expect(self.page.locator('.library-row')).to_have_count(15)

    def test_compact_reading_chinese_filters_return_and_reflow(self):
        page = self.page
        first = page.locator('.library-row').first
        first_title = first.locator('.record-title').inner_text()
        page.screenshot(path=str(self.evidence/'after-library-1366.png'), full_page=True)
        self.assertLessEqual(first.evaluate('(row)=>row.getBoundingClientRect().top'), 320)
        self.assertGreaterEqual(page.locator('.library-row').evaluate_all('(rows)=>rows.filter(row=>row.getBoundingClientRect().bottom<900).length'), 8)
        expect(page.locator('.library-selection')).to_be_hidden()
        expect(page.locator('.library-select').first).to_be_hidden()
        page.screenshot(path=str(self.evidence/'after-library-1366.png'), full_page=True)
        rid = first.get_attribute('data-library-record')
        session = page.request.get(URL+'/api/session').json()
        detail = page.request.get(URL+'/api/records/'+rid).json()
        response = page.request.put(URL+'/api/records/'+rid, data={'version': detail['version'],
                                  'chinese_title': '合成中文译题：区域能源合作', 'chinese_abstract': '独立合成译文摘要，可由中文查找。'},
                                  headers={'X-CSRF-Token': session['csrf']})
        self.assertTrue(response.ok, response.text())
        page.get_by_role('button', name='全部资料', exact=True).click()
        page.get_by_role('textbox', name='资料关键词', exact=True).fill('合成译文摘要')
        page.get_by_role('button', name='查找', exact=True).click()
        expect(page.locator('.library-row')).to_have_count(1)
        page.locator('.record-title button').click()
        expect(page.locator('.library-reader .detail-title')).to_have_text('合成中文译题：区域能源合作')
        self.assertEqual(page.locator('.library-reader').evaluate('(panel)=>panel.scrollTop'), 0)
        self.assertGreater(page.evaluate('window.scrollY'), 0)
        for selector in ['.detail-title', '[data-reading-abstract=chinese] .prose', '#ux-body .rich-prose p:first-child', '.ux-reading-toolbar a']:
            item=page.locator('.library-reader '+selector).first
            self.assertGreaterEqual(item.evaluate('(el)=>el.getBoundingClientRect().top'), 0)
            self.assertLess(item.evaluate('(el)=>el.getBoundingClientRect().bottom'), 900)
        page.screenshot(path=str(self.evidence/'after-reader-open-1366.png'))
        page.get_by_role('button', name='原文', exact=True).click()
        expect(page.locator('.library-reader .detail-title')).to_have_text(first_title)
        page.get_by_role('button', name='中文', exact=True).click()
        page.screenshot(path=str(self.evidence/'after-reader-1366.png'), full_page=True)
        page.get_by_role('button', name='返回列表', exact=True).click()
        expect(page.get_by_role('textbox', name='资料关键词', exact=True)).to_have_value('合成译文摘要')
        expect(page.locator('.record-title button')).to_be_focused()
        page.get_by_role('button', name='重置筛选', exact=True).last.click()
        expect(page.locator('.library-row')).to_have_count(15)
        for width, zoom in [(390,1),(1366,2)]:
            page.set_viewport_size({'width':width,'height':900})
            page.evaluate('(zoom)=>document.documentElement.style.zoom=zoom',zoom)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),page.evaluate('window.innerWidth')+2)
            page.locator('.record-title button').first.click()
            expect(page.get_by_role('button',name='返回列表',exact=True)).to_be_visible()
            page.screenshot(path=str(self.evidence/f'after-reader-{width}-zoom{zoom}.png'),full_page=True)
            page.keyboard.press('Escape')
            expect(page.locator('.library-reader')).to_be_hidden()
            page.screenshot(path=str(self.evidence/f'after-library-{width}-zoom{zoom}.png'),full_page=True)
        page.evaluate('document.documentElement.style.zoom=1')

    def test_primary_navigation_menu_and_current_scope_survive_reset(self):
        page=self.page
        for width in [1366,390]:
            page.set_viewport_size({'width':width,'height':900})
            toggle=page.get_by_role('button',name='打开导航',exact=True)
            if toggle.is_visible():
                toggle.focus();page.keyboard.press('Enter')
                expect(page.get_by_role('dialog',name='平台导航')).to_be_visible()
                page.keyboard.press('Escape');expect(toggle).to_be_focused();toggle.click()
            page.get_by_title('档案',exact=True).click()
            expect(page.locator('[aria-label="档案类型"]')).to_be_visible()
            page.get_by_role('button',name='作者',exact=True).click()
            expect(page.get_by_role('heading',name='作者目录',exact=True)).to_be_visible()
            if toggle.is_visible():page.get_by_role('button',name='打开导航',exact=True).click()
            page.get_by_title('我的',exact=True).click()
            expect(page.get_by_role('heading',name='我的',exact=True)).to_be_visible()
            page.screenshot(path=str(self.evidence/f'after-personal-{width}.png'),full_page=True)
            page.goto(URL+'#library?feed=all&source='+self.sample['source'])
            expect(page.locator('.library-row')).to_have_count(15)
            page.get_by_role('textbox',name='资料关键词',exact=True).fill('no matches')
            page.get_by_role('button',name='查找',exact=True).click()
            expect(page.locator('.library-row')).to_have_count(0)
            page.get_by_role('button',name='重置筛选',exact=True).last.click()
            expect(page.locator('.library-row')).to_have_count(15)
            self.assertIn('source=',page.url)

    def test_profile_roundtrips_restore_query_selection_scroll_and_focus(self):
        page=self.page
        page.goto(URL+'#library?feed=all&q=布局验收&sort=date&size=7&page=2')
        expect(page.locator('.library-row')).to_have_count(7)
        original_url=page.url
        page.locator('.reading-tools>summary').click()
        page.get_by_role('button',name='批量整理',exact=True).click()
        chosen=page.locator('.library-row').nth(3)
        rid=chosen.get_attribute('data-library-record')
        chosen.locator('[data-library-select]').check()
        token=page.request.get(URL+'/api/session').json()['csrf']
        bylines=page.request.get(URL+'/api/records/'+rid+'/bylines').json()
        result=page.request.put(URL+'/api/records/'+rid+'/bylines',data={
            'version':bylines['version'],'record_version':bylines['record_version'],
            'items':[{'raw_name':'合成人物','target_type':'person','target_id':self.sample['person'],
                      'status':'confirmed','evidence':'合成可定位署名 https://example.org/author'}],
            'change_note':'浏览器合成关联'},headers={'X-CSRF-Token':token})
        self.assertTrue(result.ok,result.text())
        current=page.request.get(URL+'/api/records/'+rid).json()
        response=page.request.put(URL+'/api/records/'+rid,data={'version':current['version'],
            'chinese_title':'档案往返中文译题','chinese_abstract':'档案往返中文摘要'},headers={'X-CSRF-Token':token})
        self.assertTrue(response.ok,response.text())
        chosen.locator('.record-title button').focus()
        page.evaluate('window.scrollTo(0,120)')
        return_y=page.evaluate('window.scrollY')
        chosen.locator('.record-title button').click()
        expect(page.locator('.library-reader .detail-title')).to_be_visible()
        page.get_by_role('button',name='原文',exact=True).click()
        expect(page.locator('.library-reader .detail-title')).to_have_text(current['title'])
        for profile,selector in [('source','[data-action=source-detail]'),('person','[data-action=byline-target]')]:
            page.locator('.library-reader '+('.ux-metadata>summary' if profile=='source' else '.ux-identities>summary')).click()
            target=page.locator('.library-reader '+selector).first
            target.scroll_into_view_if_needed()
            panel_y=page.locator('.library-reader').evaluate('(el)=>el.scrollTop')
            self.assertGreater(panel_y,0)
            page.locator('.record-list').evaluate('(el)=>el.scrollTop=60')
            list_y=page.locator('.record-list').evaluate('(el)=>el.scrollTop')
            target.click()
            expect(page.locator('.source-page' if profile=='source' else '.person-page')).to_be_visible()
            page.get_by_role('button',name='返回资料',exact=True).click()
            expect(page.locator('.library-reader .detail-title')).to_be_visible()
            expect(page.locator('.library-reader .detail-title')).to_have_text(current['title'])
            expect(page.get_by_role('button',name='原文',exact=True)).to_have_attribute('aria-pressed','true')
            self.assertEqual(page.url,original_url)
            expect(page.locator('[data-library-select="'+rid+'"]').first).to_be_checked()
            self.assertAlmostEqual(page.locator('.library-reader').evaluate('(el)=>el.scrollTop'),panel_y,delta=2)
            self.assertAlmostEqual(page.locator('.record-list').evaluate('(el)=>el.scrollTop'),list_y,delta=2)
            page.screenshot(path=str(self.evidence/('after-'+profile+'-return.png')))
        page.get_by_role('button',name='返回列表',exact=True).click()
        expect(page.locator('[data-library-record="'+rid+'"] .record-title button')).to_be_focused()
        self.assertAlmostEqual(page.evaluate('window.scrollY'),return_y,delta=2)
        expect(page.get_by_role('textbox',name='资料关键词',exact=True)).to_have_value('布局验收')
        expect(page.locator('.pagination')).to_contain_text('第 2 / 3 页')

    def test_z_delayed_batch_cannot_replace_another_account_or_open_editor(self):
        page=self.page
        pending=[]
        def hold(route):
            if not pending:
                pending.append((route,route.fetch()))
            else:
                route.continue_()
        page.route('**/api/reading-batches',hold)
        page.get_by_role('button',name='新文章',exact=True).click()
        page.wait_for_timeout(100)
        self.assertEqual(len(pending),1)
        previous=pending[0][1].json()['id']
        page.get_by_role('button',name='退出登录',exact=True).click()
        page.get_by_role('button',name='协作同事',exact=True).click()
        expect(page.locator('.library-row')).to_have_count(15)
        page.get_by_role('button',name='补充资料',exact=True).click()
        form=page.locator('[data-form="record"]')
        expect(form).to_be_visible()
        title=form.locator('[name="title"]')
        title.fill('跨账号的新编辑草稿')
        pending[0][0].fulfill(response=pending[0][1])
        page.wait_for_timeout(200)
        expect(title).to_have_value('跨账号的新编辑草稿')
        self.assertNotIn(previous,page.url)
        page.screenshot(path=str(self.evidence/'after-account-late-response.png'),full_page=True)


if __name__=='__main__':
    unittest.main(verbosity=2)
