"""Synthetic browser acceptance for #28; --serve keeps the 8874 fixture available."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
URL = 'http://127.0.0.1:8874'


class LibrarySourcesBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = Path(tempfile.mkdtemp(prefix='library-source-browser-'))
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', 8874)) == 0:
                raise RuntimeError('8874 occupied; refusing to reuse an unknown service')
        cls.output = (cls.evidence / 'server.log').open('w', encoding='utf-8')
        cls.server = subprocess.Popen([sys.executable, str(ROOT/'app.py'), '--no-import', '--port', '8874', '--data-dir', str(cls.evidence/'data')], cwd=ROOT, stdout=cls.output, stderr=subprocess.STDOUT,
                                      creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        for _ in range(100):
            try:
                urllib.request.urlopen(URL+'/health', timeout=1).close()
                break
            except OSError:
                time.sleep(.1)
        else:
            cls.server.terminate()
            cls.server.wait(timeout=10)
            cls.output.close()
            raise RuntimeError('Isolated 8874 service did not start')
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(channel=os.environ.get('DATABASE_BROWSER_CHANNEL') or None,
                                                       executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None)
        except Exception:
            cls.playwright.stop()
            cls.server.terminate()
            cls.server.wait(timeout=10)
            cls.output.close()
            raise
        request = cls.playwright.request.new_context(base_url=URL)
        csrf = request.get('/api/session').json()['csrf']
        response = request.post('/api/login', data=dict(username='researcher', password='LocalDemo2026!'), headers={'X-CSRF-Token':csrf})
        cls.token = response.json()['csrf']
        def create(path, **values):
            result = request.post(path, data=values, headers={'X-CSRF-Token':cls.token})
            assert result.ok, result.text()
            return result.json()['id']
        cls.lv = create('/api/sources', name='拉脱维亚合成机构', original_name='Latvian Synthetic Institute', aliases='Baltic Alias', kind='institution', country='拉脱维亚', country_evidence='合成地址')
        cls.ee = create('/api/sources', name='爱沙尼亚合成机构', kind='institution', country='爱沙尼亚', country_evidence='合成地址')
        cls.old = create('/api/sources', name='旧合成机构', kind='institution')
        response = request.post('/api/login', data=dict(username='admin', password='LocalDemo2026!'), headers={'X-CSRF-Token':cls.token})
        cls.token=response.json()['csrf']
        merged=request.post('/api/merge', data=dict(type='source',keep_id=cls.lv,duplicate_id=cls.old,keep_version=1,duplicate_version=1,confirmed=True), headers={'X-CSRF-Token':cls.token})
        assert merged.ok, merged.text()
        response=request.post('/api/login',data=dict(username='researcher',password='LocalDemo2026!'),headers={'X-CSRF-Token':cls.token})
        cls.token=response.json()['csrf']
        cls.journal = create('/api/sources', name='多国合成期刊', kind='journal', host_id=cls.lv+' | '+cls.ee, host_evidence='合成主办声明', international_status='yes', international_evidence='合成办刊声明')
        for n in range(25):
            create('/api/sources', name=f'候选机构 {n:02d} '+('长名称保护窄屏内容和按钮 ' * 3), kind='institution', country='法国')
        cls.records = [create('/api/records', title=f'合成期刊资料 {n:02d}', kind='report', serial_id=cls.journal, countries='法国') for n in range(14)]
        create('/api/records', title='合成机构资料', kind='report', source_id=cls.lv)
        cls.collection = create('/api/collections', name='合成查询专题', visibility='shared')
        for rid in cls.records:
            request.post('/api/collections/'+cls.collection+'/items', data={'record_id':rid}, headers={'X-CSRF-Token':cls.token})
        request.dispose()
        print('Browser fixture:', cls.evidence, flush=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.output.close()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width':1366, 'height':900})
        self.page = self.context.new_page()
        self.page.on('pageerror', lambda error: print('Browser error:', error, flush=True))
        self.page.set_default_timeout(5000)
        self.page.goto(URL)
        self.page.get_by_role('button', name='研究员', exact=True).click()
        self.page.goto(URL+'/#library')
        expect(self.page.get_by_role('heading', name='资料库', exact=True)).to_be_visible()

    def tearDown(self):
        self.context.close()

    def test_source_scope_query_and_context(self):
        page = self.page
        page.goto(URL+'/#library?q=合成期刊资料')
        page.locator('.ux-filters > summary').click()
        page.get_by_label('来源类型', exact=True).select_option('journal')
        page.get_by_label('来源国别', exact=True).select_option('拉脱维亚')
        page.get_by_label('国际办刊定位', exact=True).select_option('yes')
        page.get_by_role('button', name='应用筛选', exact=True).click()
        expect(page.locator('.results-head')).to_contain_text('14')
        expect(page).to_have_url(__import__('re').compile('source_group=journal'))
        page.locator('[data-library-select]').first.check()
        page.get_by_role('button', name='下一页', exact=True).click()
        expect(page.get_by_text('第 2 / 2 页', exact=True)).to_be_visible()
        page.reload()
        expect(page.get_by_text('第 2 / 2 页', exact=True)).to_be_visible()
        page.get_by_role('button', name='清除来源国别：拉脱维亚', exact=True).click()
        expect(page.locator('[data-library-selection-count]')).to_have_text('已选 0 条')
        expect(page.get_by_text('第 1 / 2 页', exact=True)).to_be_visible()
        page.go_back()
        expect(page.get_by_text('第 2 / 2 页', exact=True)).to_be_visible()
        page.goto(URL+'/#library?collection='+self.collection+'&source='+self.journal+'&source_section=published&source_group=journal')
        expect(page.get_by_role('heading', name='合成查询专题', exact=True)).to_be_visible()
        page.get_by_role('button', name='清除筛选', exact=True).click()
        expect(page).to_have_url(URL+'/#library?collection='+self.collection)
        expect(page.locator('.results-head')).to_contain_text('14')

        expect(page.get_by_role('button',name='清除筛选',exact=True)).not_to_be_visible()

    def test_specific_source_scope_and_old_identity(self):
        page=self.page
        page.goto(URL+'/#library?source='+self.old+'&source_section=published')
        expect(page.get_by_role('button',name='清除来源：拉脱维亚合成机构',exact=True)).to_be_visible()
        page.locator('.ux-filters > summary').click()
        expect(page.locator('[name=source]')).to_have_value(self.lv)
        page.get_by_text('选择或调整具体来源（可选）',exact=True).click()
        page.get_by_label('搜索具体来源（可选）',exact=True).fill('多国合成')
        page.locator('[data-source-option]').check()
        page.get_by_label('来源类型',exact=True).select_option('institution')
        expect(page.locator('[data-source-range-notice]')).to_contain_text('已清除不符合新来源范围')
        expect(page.locator('[name=source]')).to_have_value('')
        expect(page.get_by_label('国际办刊定位',exact=True)).to_be_disabled()
        page.get_by_role('button',name='应用筛选',exact=True).click()
        expect(page).to_have_url(URL+'/#library?source_group=institution')

    def test_search_single_multi_draft_and_save(self):
        page = self.page
        page.get_by_role('button', name='提交资料', exact=True).click()
        form = page.locator('form[data-form=record]')
        expect(form).not_to_have_attribute('inert')
        form.get_by_label('题名 *', exact=True).fill('来源选择保存试验')
        serial=form.locator('[data-source-select]').filter(has=page.get_by_label('搜索所属期刊 / 连续出版物',exact=True))
        serial.locator('summary').click()
        self.assertEqual(serial.locator('[data-source-group] option').all_text_contents(),['全部类型','期刊','其他出版物'])
        related = form.locator('[data-source-select]').filter(has=page.get_by_label('搜索关联来源（可多选）', exact=True))
        related.locator('summary').click()
        self.assertEqual(related.locator('[data-source-option]').count(), 8)
        related.get_by_role('button',name='下一组',exact=True).click()
        expect(related.locator('[data-source-count]')).to_contain_text('第 2 /')
        related.get_by_label('搜索关联来源（可多选）', exact=True).fill('Baltic Alias')
        related.locator('[data-source-option]').check()
        related.get_by_label('搜索关联来源（可多选）', exact=True).fill('多国合成期刊')
        related.locator('[data-source-option]').check()
        expect(related.locator('[data-source-selected]')).to_contain_text('拉脱维亚合成机构')
        expect(related.locator('[data-source-selected]')).to_contain_text('多国合成期刊')
        form.get_by_text('选择或调整发布机构',exact=True).click()
        form.get_by_label('搜索发布机构', exact=True).fill('Latvian Synthetic')
        form.get_by_label('搜索发布机构', exact=True).press('ArrowDown')
        page.keyboard.press('Space')
        expect(form.locator('[data-source-values][name=source_id]')).to_have_value(self.lv)

        form.get_by_role('button', name='关闭并保留草稿', exact=True).click()
        page.get_by_role('button', name='提交资料', exact=True).click()
        form = page.locator('form[data-form=record]')
        expect(form).not_to_have_attribute('inert')
        expect(form.get_by_role('button', name='恢复草稿', exact=True)).to_be_visible()

        form.get_by_role('button', name='恢复草稿', exact=True).click()

        expect(form.get_by_label('题名 *', exact=True)).to_have_value('来源选择保存试验')
        expect(form.locator('[data-source-values][name=source_id]')).to_have_value(self.lv)
        self.assertEqual(set(form.locator('[name=related_source_ids]').evaluate('(s)=>[...s.selectedOptions].map(o=>o.value)')),{self.lv,self.journal})
        expect(form.locator('[data-source-selected]').first).to_contain_text('多国合成期刊')
        form.get_by_role('button', name='保存内容', exact=True).click()
        expect(form).not_to_be_visible()
        result = self.context.request.get(URL+'/api/records?q=来源选择保存试验').json()['items']
        self.assertEqual(len(result), 1)
        detail = self.context.request.get(URL+'/api/records/'+result[0]['id']).json()
        self.assertEqual(detail['source_id'],self.lv)
        self.assertEqual(set(detail['related_source_ids']),{self.lv,self.journal})

    def test_merged_sources_in_draft_restore_current_single_and_multiple_identities(self):
        page = self.page
        token = self.context.request.get(URL+'/api/session').json()['csrf']
        def create_source(name, kind):
            response = self.context.request.post(URL+'/api/sources', data=dict(name=name, kind=kind), headers={'X-CSRF-Token':token})
            self.assertTrue(response.ok, response.text())
            return response.json()['id']
        old_institution = create_source('草稿旧机构', 'institution')
        keep_institution = create_source('草稿现机构', 'institution')
        old_journal = create_source('草稿旧期刊', 'journal')
        keep_journal = create_source('草稿现期刊', 'journal')
        # Refresh the real form's source lookup before selecting the old identities.
        page.reload()
        page.get_by_role('button', name='提交资料', exact=True).click()
        form = page.locator('form[data-form=record]')
        expect(form).not_to_have_attribute('inert')
        form.get_by_label('题名 *', exact=True).fill('合并后恢复来源草稿')
        form.locator('[data-rich-field=body_html] [data-rich-input]').fill('保持这份合成正文。')
        for label, query in [('发布机构','草稿旧机构'),('所属期刊 / 连续出版物','草稿旧期刊'),('关联来源（可多选）','草稿旧')]:
            picker = form.locator('[data-source-select]').filter(has=page.get_by_label('搜索'+label, exact=True))
            picker.locator('summary').click()
            picker.get_by_label('搜索'+label, exact=True).fill(query)
            for candidate in picker.locator('[data-source-option]').all():
                candidate.check()
        form.get_by_role('button', name='关闭并保留草稿', exact=True).click()
        admin = self.playwright.request.new_context(base_url=URL)
        try:
            csrf = admin.get('/api/session').json()['csrf']
            response = admin.post('/api/login', data=dict(username='admin', password='LocalDemo2026!'), headers={'X-CSRF-Token':csrf})
            self.assertTrue(response.ok, response.text())
            csrf = response.json()['csrf']
            for keep, old in [(keep_institution,old_institution),(keep_journal,old_journal)]:
                response = admin.post('/api/merge', data=dict(type='source',keep_id=keep,duplicate_id=old,keep_version=1,duplicate_version=1,confirmed=True), headers={'X-CSRF-Token':csrf})
                self.assertTrue(response.ok, response.text())
        finally:
            admin.dispose()
        page.reload()
        page.get_by_role('button', name='提交资料', exact=True).click()
        expect(form).not_to_have_attribute('inert')
        form.get_by_role('button', name='恢复草稿', exact=True).click()
        expect(form.get_by_label('题名 *', exact=True)).to_have_value('合并后恢复来源草稿')
        expect(form.locator('[name=source_id]')).to_have_value(keep_institution)
        expect(form.locator('[name=serial_id]')).to_have_value(keep_journal)
        self.assertEqual(set(form.locator('[name=related_source_ids]').evaluate('(s)=>[...s.selectedOptions].map(o=>o.value)')), {keep_institution,keep_journal})
        expect(form.locator('[data-source-selected]').first).to_contain_text('草稿现机构')
        expect(form.locator('[data-source-selected]').first).to_contain_text('草稿现期刊')
        form.get_by_role('button', name='保存内容', exact=True).click()
        expect(form).not_to_be_visible()
        result = self.context.request.get(URL+'/api/records?q=合并后恢复来源草稿').json()['items']
        self.assertEqual(len(result),1)
        detail = self.context.request.get(URL+'/api/records/'+result[0]['id']).json()
        self.assertEqual((detail['source_id'],detail['serial_id']), (keep_institution,keep_journal))
        self.assertEqual(set(detail['related_source_ids']), {keep_institution,keep_journal})
        self.assertIn('保持这份合成正文。', detail['body_html'])
        self.assertEqual(detail['visibility'],'shared')

    def test_source_maintenance_multi_and_relation(self):
        page = self.page
        token=self.context.request.get(URL+'/api/session').json()['csrf']
        journal=self.context.request.post(URL+'/api/sources',data=dict(name='维护测试独立期刊',kind='journal',host_id=self.lv+' | '+self.ee,host_evidence='合成主办声明'),headers={'X-CSRF-Token':token}).json()['id']
        page.goto(URL+'/#sources?id='+journal)
        page.get_by_role('button', name='编辑来源', exact=True).click()
        form = page.locator('form[data-form=source]')
        host = form.locator('[data-source-select]').filter(has=page.get_by_label('搜索主办机构（可多选）', exact=True))
        expect(host.locator('[data-source-selected]')).to_contain_text('爱沙尼亚合成机构')
        host.locator('summary').click()
        host.get_by_label('搜索主办机构（可多选）', exact=True).fill('候选机构 24')
        host.locator('[data-source-option]').check()
        expect(host.locator('[data-source-selected]')).to_contain_text('拉脱维亚合成机构')
        form.get_by_label('主办关系依据', exact=True).fill('更新后的合成主办声明')
        publisher=form.locator('[data-source-select]').filter(has=page.get_by_label('搜索出版机构（可多选）',exact=True))
        publisher.locator('summary').click()
        publisher.get_by_label('搜索出版机构（可多选）',exact=True).fill('爱沙尼亚')
        publisher.locator('[data-source-option]').check()
        form.get_by_role('button',name='关闭并保留草稿',exact=True).click()
        page.get_by_role('button',name='编辑来源',exact=True).click()
        form.get_by_role('button',name='恢复草稿',exact=True).click()
        expect(form.locator('[data-source-selected]').first).to_contain_text('候选机构 24')
        expect(form.locator('[name=publisher_id]')).to_have_values([self.ee])
        updated=self.context.request.put(URL+'/api/sources/'+journal,data=dict(version=1,notes='并发修订'),headers={'X-CSRF-Token':token})
        self.assertTrue(updated.ok,updated.text())
        form.get_by_role('button',name='保存修订',exact=True).click()
        expect(form.locator('[data-conflict-panel]')).to_be_visible()
        expect(form.locator('[data-source-selected]').first).to_contain_text('候选机构 24')
        form.get_by_role('button',name='我已对照，以新版本继续编辑',exact=True).click()
        form.get_by_role('button', name='保存修订', exact=True).click()
        expect(form).not_to_be_visible()
        detail=self.context.request.get(URL+'/api/sources/'+journal).json()
        self.assertEqual(len(detail['host_id'].split(' | ')),3)
        page.goto(URL+'/#sources?id='+self.lv)
        page.get_by_role('button', name='编辑来源', exact=True).click()
        form=page.locator('form[data-form=source]')
        form.get_by_role('button',name='添加机构关系',exact=True).click()
        form.get_by_label('关系依据（必填）',exact=True).fill('合成关系声明')
        form.get_by_role('button',name='保存修订',exact=True).click()
        expect(form.locator('[data-source-error]')).to_have_text('请选择已登记的关联机构。')
        expect(form.get_by_label('搜索关联机构',exact=True)).to_be_focused()
        form.get_by_label('搜索关联机构',exact=True).fill('爱沙尼亚')
        form.locator('[data-rel=target_id]').locator('..').locator('[data-source-option]').check()
        form.get_by_label('关系依据（必填）',exact=True).fill('合成关系声明')
        form.get_by_role('button',name='保存修订',exact=True).click()
        expect(form).not_to_be_visible()
        detail=self.context.request.get(URL+'/api/sources/'+self.lv).json()
        self.assertEqual(detail['relationships'][0]['target_id'], self.ee)

    def test_narrow_picker_and_empty_feedback(self):
        page=self.page
        page.set_viewport_size({'width':390,'height':844})
        page.get_by_role('button',name='提交资料',exact=True).click()
        form=page.locator('form[data-form=record]')
        search=form.get_by_label('搜索关联来源（可多选）',exact=True)
        form.locator('[data-source-select]').first.locator('summary').click()
        search.fill('没有这样的来源')
        expect(form.get_by_text('没有匹配来源，请调整名称或候选条件。',exact=True)).to_be_visible()
        search.fill('候选机构 24')
        form.locator('[data-source-select]').first.locator('[data-source-option]').check()
        self.assertLessEqual(page.locator('body').evaluate('(el)=>el.scrollWidth'),390)
        page.screenshot(path=str(self.evidence/'narrow-picker.png'),full_page=True)


if __name__ == '__main__':
    if '--serve' in sys.argv:
        LibrarySourcesBrowserTests.setUpClass()
        try:
            print('Fixture ready on '+URL, flush=True)
            while True:
                time.sleep(1)
        finally:
            LibrarySourcesBrowserTests.tearDownClass()
    else:
        unittest.main()
