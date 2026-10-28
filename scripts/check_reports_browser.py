"""#61 public HTTP and actual browser acceptance. Synthetic files, owned port 8902."""
import json
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
import urllib.request
import zipfile

os.environ.setdefault('DATABASE_BROWSER_PORT', '8902')
import check_layout_browser as layout
from playwright.sync_api import expect

URL = layout.URL


class ReportsBrowserTests(unittest.TestCase):
    setUpClass = classmethod(layout.LayoutBrowserTests.setUpClass.__func__)
    stop_server = staticmethod(layout.LayoutBrowserTests.stop_server)
    def tearDown(self):
        self.assertEqual(self.errors, [])
        self.page.wait_for_load_state('networkidle')

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1366, 'height': 900})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.set_default_timeout(7000)
        self.page.goto(URL)
        self.page.get_by_role('button', name='研究员', exact=True).click()
        expect(self.page.get_by_role('heading', name='资料', exact=True)).to_be_visible()

    def api(self, path, values=None, method='POST', status=200, request=None):
        request = request or self.page.request
        token = request.get(URL+'/api/session').json()['csrf']
        response = request.fetch(URL+path, method=method, data=values or {}, headers={'X-CSRF-Token':token})
        self.assertEqual(response.status, status, response.text())
        return response.json()

    def open_record(self, rid):
        self.page.goto(URL+'#library?feed=all&q='+rid)
        self.page.locator('[data-library-record="'+rid+'"] .record-title button').click()
        expect(self.page.locator('.library-reader .detail-title')).to_be_visible()

    def edit_record(self, rid):
        self.open_record(rid)
        self.page.locator('.library-reader .ux-maintenance>summary').click()
        self.page.get_by_role('button',name='编辑内容',exact=True).click()
        expect(self.page.locator('[data-form=record]')).to_be_visible()

    def test_legacy_excerpt_draft_retains_quote_position_and_original(self):
        page = self.page
        rid = self.sample['records'][0]
        account = page.request.get(URL+'/api/session').json()['user']['id']
        draft = {'user_id':account,'type':'record','id':'','kind':'research_note','context':'excerpt-'+rid,
                 'version':None,'title':'旧摘录草稿','values':{'kind':'research_note','title':'旧摘录草稿',
                 'body_html':'<p>未提交的旧说明</p>','quote':'固定的合成原句','locator':'第12段',
                 'evidence_record_id':rid,'visibility':'shared','editors':[]},'links':[],
                 'updated_at':'2026-10-27T12:00:00Z'}
        key='zhihui:draft:v1:'+account+':record:new-research_note-excerpt-'+rid
        page.evaluate('([key,value])=>localStorage.setItem(key,JSON.stringify(value))',[key,draft])
        page.goto(URL+'#drafts')
        page.get_by_role('button',name='继续编辑',exact=True).click()
        page.get_by_role('button',name='恢复草稿',exact=True).click()
        form=page.locator('[data-form=record]')
        expect(form.locator('[name=quote]')).to_have_value('固定的合成原句')
        expect(form.locator('[name=locator]')).to_have_value('第12段')
        expect(form.locator('[name=evidence_record_id]')).to_have_value(rid)
        form.get_by_role('button',name='保存内容',exact=True).click()
        expect(page.locator('.drawer .detail-title')).to_have_text('旧摘录草稿')
        expect(page.locator('.drawer')).to_contain_text('固定的合成原句')

    def test_simple_folder_preserves_legacy_content(self):
        page = self.page
        page.goto(URL + '#collections')
        page.get_by_role('button', name='新建资料夹', exact=True).click()
        form = page.locator('[data-form=research-collection]')
        expect(form.locator('[name=research_question]')).to_have_count(0)
        expect(form.locator('[name=comparison_html]')).to_have_count(0)
        form.locator('[name=name]').fill('成品与原文')
        form.locator('[name=description]').fill('简单备注')
        form.get_by_role('button', name='保存资料夹', exact=True).click()
        expect(page.locator('.workspace-topic')).to_contain_text('简单备注')
        expect(page.get_by_role('button', name='编写报告', exact=True)).to_have_count(0)
        expect(page.locator('.workspace-topic')).not_to_contain_text('研究问题')
        cid=page.locator('.workspace-topic').get_attribute('data-collection')
        rid=self.sample['records'][2]
        page.get_by_text('添加已有资料或成果',exact=True).click()
        page.get_by_label('查找已有资料或成果',exact=True).fill(rid)
        page.get_by_role('button',name='查找并添加',exact=True).click()
        page.locator('[data-action=topic-add][data-id="'+rid+'"]').click()
        expect(page.locator('.topic-record')).to_have_count(1)
        for width,zoom in [(1366,1),(390,1),(1366,2)]:
            page.set_viewport_size({'width':width,'height':900})
            page.evaluate('(zoom)=>document.documentElement.style.zoom=zoom',zoom)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),page.evaluate('window.innerWidth')+2)
            page.screenshot(path=str(self.evidence/f'folder-{width}-zoom{zoom}.png'),full_page=True)
        page.evaluate('document.documentElement.style.zoom=1')
        page.get_by_role('button',name='移出资料夹',exact=True).click()
        expect(page.locator('.topic-record')).to_have_count(0)
        self.assertEqual(page.request.get(URL+'/api/records/'+rid).status,200)
        self.assertEqual(page.request.get(URL+'/api/collections/'+cid).json()['items'],[])

    def test_finished_report_import_has_no_empty_writing_components(self):
        page = self.page
        page.goto(URL + '#compilations')
        page.get_by_role('button', name='导入成品', exact=True).click()
        form = page.locator('[data-form=record]')
        expect(form.locator('[data-evidence-editor],[data-evidence-picker],[data-note-subject-picker]')).to_have_count(0)
        self.assertEqual(set(form.locator('[name=kind] option').evaluate_all('(els)=>els.map(el=>el.value)')),
                         {'compilation', 'research_report', 'directory_translation'})
        expect(form.locator('[name=file]')).to_be_visible()
        for width in [1366,390]:
            page.set_viewport_size({'width':width,'height':900})
            page.screenshot(path=str(self.evidence/f'finished-import-{width}.png'),full_page=True)
        page.set_viewport_size({'width':1366,'height':900})
        form.locator('[name=kind]').select_option('research_report')
        form.locator('[name=title]').fill('已完成的合成报告')
        form.locator('[name=authors]').fill('合成编者')
        if not form.locator('[name=file]').is_visible():
            form.locator('[data-record-attachments]>summary').click()
        form.locator('[name=file]').set_input_files({'name':'原报告.txt','mimeType':'text/plain','buffer':b'Finished report original bytes'})
        form.locator('[name=sharing_confirmed]').check()
        form.get_by_role('button', name='保存成品', exact=True).click()
        expect(page.locator('.drawer .detail-title')).to_have_text('已完成的合成报告')
        link = page.locator('.drawer a[href^="/api/attachments/"]').first
        self.assertEqual(page.request.get(URL+link.get_attribute('href')).body(), b'Finished report original bytes')
        page.get_by_role('button', name='关闭', exact=True).click()
        expect(page.locator('.record-title button').filter(has_text='已完成的合成报告')).to_be_visible()

    def test_reading_profiles_and_personal_have_no_empty_writing_workflow(self):
        page = self.page
        page.goto(URL+'#library?feed=all&q=布局验收资料 00')
        page.locator('.record-title button').first.click()
        expect(page.locator('.library-reader .detail-title')).to_be_visible()
        expect(page.locator('[data-reading-notes]')).to_have_count(0)
        expect(page.locator('[data-action=new-excerpt],[data-action=ux-reading-note]')).to_have_count(0)
        source=self.api('/api/sources',{'name':'空研究区测试来源','kind':'institution'},status=201)['id']
        person=self.api('/api/people',{'name':'空研究区测试人物','change_note':'合成依据'},status=201)['id']
        for route, container in [('sources?id='+source, '.source-page'),
                                 ('people?id='+person, '.person-page'),
                                 ('personal', '#content'), ('dashboard', '#content')]:
            page.goto(URL+'#'+route)
            expect(page.locator(container)).to_be_visible()
            expect(page.locator('[data-action=new-subject-note]')).to_have_count(0)
            expect(page.locator('.note-subject-profile')).to_have_count(0)
            expect(page.locator('[data-action=new-topic-report],[data-action=ux-reading-note]')).to_have_count(0)

    def test_legacy_report_revision_conflict_export_and_permissions(self):
        page=self.page
        original=self.sample['records'][1]
        note=self.api('/api/records',{'kind':'research_note','title':'已有证据笔记',
            'evidence_record_id':original,'quote':'旧采用原句','locator':'第3段',
            'research_subjects':[{'subject_type':'person','subject_id':self.sample['person']}],
            'body_html':'<p>采用时的说明</p>'},status=201)['id']
        report=self.api('/api/records',{'kind':'research_report','title':'成品报告：保留旧采用依据',
            'authors':'合成责任作者','body_html':'<p>站外完成的报告正文</p>',
            'linked_ids':[original],'related_source_ids':[self.sample['source']],
            'evidence_citations':[{'excerpt_id':note,'stance':'qualifies','claim_note':'原判断的限定'}]},status=201)['id']
        self.api('/api/records/'+note,{'version':1,'quote':'当前已修订原句','body_html':'<p>当前新说明</p>'},'PUT')
        self.edit_record(report)
        form=page.locator('[data-form=record]')
        form.locator('[name=title]').fill('成品报告：必要修订后仍保留原依据')
        other=self.playwright.request.new_context(base_url=URL)
        try:
            self.api('/api/login',{'username':'researcher','password':'LocalDemo2026!'},request=other)
            self.api('/api/records/'+report,{'version':1,'abstract':'另一窗口的必要信息'},'PUT',request=other)
        finally:
            other.dispose()
        form.get_by_role('button',name='保存修订',exact=True).click()
        expect(form.locator('[data-conflict-panel]')).to_be_visible()
        expect(form.locator('[name=title]')).to_have_value('成品报告：必要修订后仍保留原依据')
        page.screenshot(path=str(self.evidence/'report-conflict-1366.png'),full_page=True)
        form.get_by_role('button',name='我已对照，以新版本继续编辑',exact=True).click()
        if not form.locator('[data-rich-field=body_html] .rich-editor').is_visible():
            form.locator('[data-record-body]>summary').click()
        form.locator('[data-rich-field=body_html] .rich-editor').fill('网页正文的独立修订')
        form.get_by_role('button',name='保存修订',exact=True).click()
        expect(page.locator('.drawer .detail-title')).to_contain_text('必要修订')
        expect(page.locator('.drawer .reading-language,.drawer .reading-translation-history')).to_have_count(0)
        detail=page.request.get(URL+'/api/records/'+report).json()
        self.assertEqual([row['id'] for row in detail['linked_records']],[original])
        self.assertEqual(detail['related_source_ids'],[self.sample['source']])
        citation=detail['evidence_citations'][0]
        self.assertEqual((citation['excerpt_version'],citation['snapshot']['quote'],citation['stance'],citation['claim_note']),
                         (1,'旧采用原句','qualifies','原判断的限定'))
        for width,zoom in [(1366,1),(390,1),(1366,2)]:
            page.set_viewport_size({'width':width,'height':900})
            page.evaluate('(zoom)=>document.documentElement.style.zoom=zoom',zoom)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),page.evaluate('window.innerWidth')+2)
            page.screenshot(path=str(self.evidence/f'report-reader-{width}-zoom{zoom}.png'),full_page=True)
        page.evaluate('document.documentElement.style.zoom=1')
        page.set_viewport_size({'width':1366,'height':900})
        page.get_by_role('button',name='关闭',exact=True).click()
        page.goto(URL+'#compilations?q='+report)
        page.locator('.reading-tools>summary').click()
        with page.expect_download() as download:
            page.get_by_role('button',name='导出完整内容',exact=True).click()
        path=self.evidence/'report-readable.zip'
        download.value.save_as(path)
        with zipfile.ZipFile(path) as archive:
            payload=json.loads(archive.read('content.json'))
            self.assertEqual(payload['selected_ids'],[report])
            exported=next(row for row in payload['records'] if row['id']==report)
            self.assertEqual(exported['evidence_citations'][0]['snapshot']['quote'],'旧采用原句')
        for user in ['colleague','admin']:
            self.api('/api/login',{'username':user,'password':'LocalDemo2026!'})
            self.api('/api/records/'+report,{'version':detail['version'],'body_html':'<p>越权正文</p>'},'PUT',403)
            current=page.request.get(URL+'/api/records/'+note).json()
            self.api('/api/records/'+note,{'version':current['version'],'body_html':'<p>可读成员共编笔记</p>'},'PUT')
            changed=page.request.get(URL+'/api/records/'+note).json()
            self.api('/api/records/'+note,{'version':changed['version'],'visibility':'restricted'},'PUT',403 if user=='colleague' else 403)

    def test_attachment_hit_reads_location_without_excerpt_creation(self):
        page=self.page
        token=page.request.get(URL+'/api/session').json()['csrf']
        content=b'Independent AttachmentProbe at the original first line.'
        response=page.request.post(URL+'/api/records',multipart={'data':json.dumps({'kind':'report','title':'附件核对原文','sharing_confirmed':True}),
            'file':{'name':'original.txt','mimeType':'text/plain','buffer':content}},headers={'X-CSRF-Token':token})
        self.assertEqual(response.status,201,response.text())
        page.goto(URL+'#library?feed=all&q=AttachmentProbe')
        page.locator('[data-action=attachment-segment]').first.click()
        expect(page.locator('#attachment-segment')).to_have_value(content.decode())
        expect(page.locator('[data-action=attachment-use-selection],[data-form=record]')).to_have_count(0)
        self.assertEqual(page.request.get(URL+page.get_by_role('link',name='下载原文件',exact=True).get_attribute('href')).body(),content)
        page.screenshot(path=str(self.evidence/'attachment-location-1366.png'))

    def test_proxy_author_file_versions_and_directory_import_on_mobile(self):
        page=self.page
        page.set_viewport_size({'width':390,'height':900})
        page.goto(URL+'#compilations')
        page.get_by_role('button',name='导入成品',exact=True).click()
        form=page.locator('[data-form=record]')
        form.locator('[name=title]').fill('代交成品原文件')
        form.locator('[name=author_id]').select_option('colleague')
        form.locator('[name=file]').set_input_files({'name':'成品初版.txt','mimeType':'text/plain','buffer':b'Original completed file v1'})
        form.locator('[name=sharing_confirmed]').check()
        form.get_by_role('button',name='保存成品',exact=True).click()
        expect(page.get_by_role('heading',name='等待负责作者确认',exact=True)).to_be_visible()
        expect(page.locator('.drawer [data-action=edit-record]')).to_have_count(0)
        rid=page.request.get(URL+'/api/records?q=代交成品原文件').json()['items'][0]['id']
        page.get_by_role('button',name='关闭',exact=True).click()
        page.get_by_role('button',name='退出登录',exact=True).click()
        page.get_by_role('button',name='协作同事',exact=True).click()
        self.open_record(rid)
        page.get_by_role('button',name='确认本人为负责作者',exact=True).click()
        expect(page.locator('.drawer [data-action=edit-record]')).to_have_count(1)
        page.locator('.drawer .ux-maintenance>summary').click()
        page.get_by_role('button',name='编辑内容',exact=True).click()
        form=page.locator('[data-form=record]')
        form.locator('[data-record-body]>summary').click()
        form.locator('[data-rich-field=body_html] .rich-editor').fill('网页修订与原文件分别保存')
        form.locator('[name=editors][value=researcher]').check()
        form.locator('[name=file]').set_input_files({'name':'成品新版.txt','mimeType':'text/plain','buffer':b'Independent completed file v2'})
        form.locator('[name=sharing_confirmed]').check()
        form.get_by_role('button',name='保存修订',exact=True).click()
        expect(page.locator('.drawer .ux-main-body')).to_contain_text('网页修订与原文件分别保存')
        current=page.request.get(URL+'/api/records/'+rid).json()
        self.assertEqual(len(current['attachments']),2)
        for file,content in zip(current['attachments'],[b'Original completed file v1',b'Independent completed file v2']):
            self.assertEqual(page.request.get(URL+'/api/attachments/'+file['id']).body(),content)
        page.locator('.drawer .ux-maintenance>summary').click()
        page.get_by_role('button',name='修改历史',exact=True).click()
        page.locator('[data-action=restore]').last.click()
        expect(page.locator('.drawer .detail-title')).to_have_text('代交成品原文件')
        restored=page.request.get(URL+'/api/records/'+rid).json()
        self.assertEqual(len(restored['attachments']),1)
        self.assertEqual((restored['author_id'],restored['author_confirmed'],restored['editors']),('colleague',True,['researcher']))
        self.assertEqual(page.request.get(URL+'/api/attachments/'+restored['attachments'][0]['id']).body(),b'Original completed file v1')
        page.screenshot(path=str(self.evidence/'author-file-history-390.png'),full_page=True)
        page.get_by_role('button',name='关闭',exact=True).click()
        page.goto(URL+'#compilations')
        page.get_by_role('button',name='导入成品',exact=True).click()
        form=page.locator('[data-form=record]')
        form.locator('[name=kind]').select_option('directory_translation')
        form.locator('[name=title]').fill('已完成目录译稿')
        form.locator('[name=authors]').fill('合成编译者')
        form.locator('[name=coverage]').fill('2026年第1期')
        form.locator('[data-record-more]>summary').click()
        field=form.locator('[data-source-select]').filter(has=page.locator('[name=related_source_ids]'))
        field.locator('summary').click()
        field.locator('[data-source-candidates] input').first.check()
        form.get_by_role('button',name='保存成品',exact=True).click()
        expect(page.locator('.drawer .detail-title')).to_have_text('已完成目录译稿')
        expect(page.locator('.drawer .reading-language,.drawer .reading-translation-history')).to_have_count(0)

    def test_z_legacy_folder_files_and_new_directory_restore(self):
        page=self.page
        rid=self.sample['records'][3]
        legacy={'name':'旧专题的兼容资料夹','description':'原备注','visibility':'shared','research_question':'旧研究问题',
                'comparison_html':'<p>旧比较依据</p>','stage_judgment':'旧阶段判断',
                'scope_log':[{'source':'合成目录','query':'旧检索词','searched_on':'2026-10-27','outcome':'zero_results'}]}
        cid=self.api('/api/collections',legacy,status=201)['id']
        self.api('/api/collections/'+cid+'/items',{'record_id':rid})
        self.api('/api/collections/'+cid+'/items',{'record_id':self.sample['records'][4],'version':2,'disposition':'excluded','rationale':'旧排除理由'})
        old=page.request.get(URL+'/api/collections/'+cid).json()
        # The normal partial-update contract must preserve undisplayed legacy fields.
        self.api('/api/collections/'+cid,{'version':old['version'],'description':'只修订备注'},'PUT')
        current=page.request.get(URL+'/api/collections/'+cid).json()
        for field in ['research_question','comparison_html','stage_judgment','scope_log','excluded_items','items']:
            self.assertEqual(current[field],old[field])
        page.goto(URL+'#collections')
        page.locator('[data-action=open-collection][data-id="'+cid+'"]').click()
        page.get_by_text('已有研究内容',exact=True).click()
        expect(page.locator('.workspace-topic')).to_contain_text('旧排除理由')
        page.get_by_role('button',name='编辑资料夹',exact=True).click()
        form=page.locator('[data-form=research-collection]')
        form.locator('[name=description]').fill('本地未丢的备注')
        self.api('/api/collections/'+cid,{'version':current['version'],'description':'另一窗口的新备注'},'PUT')
        form.get_by_role('button',name='保存资料夹',exact=True).click()
        expect(form.locator('[data-conflict-panel]')).to_be_visible()
        expect(form.locator('[name=description]')).to_have_value('本地未丢的备注')
        form.get_by_role('button',name='我已对照，以新版本继续编辑',exact=True).click()
        form.get_by_role('button',name='保存资料夹',exact=True).click()
        expect(page.locator('.workspace-topic')).to_contain_text('本地未丢的备注')
        page.get_by_role('button',name='修改历史',exact=True).click()
        page.locator('[data-action=restore-topic]').last.click()
        expect(page.locator('.workspace-topic .detail-title')).to_have_text('旧专题的兼容资料夹')
        expect(page.locator('.workspace-topic')).to_contain_text('原备注')
        page.get_by_role('button',name='关闭',exact=True).click()
        admin=self.playwright.request.new_context(base_url=URL)
        try:
            self.api('/api/login',{'username':'admin','password':'LocalDemo2026!'},request=admin)
            token=admin.get(URL+'/api/session').json()['csrf']
            backup=admin.post(URL+'/api/backup',data={},headers={'X-CSRF-Token':token})
            self.assertTrue(backup.ok,backup.text() if not backup.ok else '')
            archive=self.evidence/'complete-backup.zip'
            archive.write_bytes(backup.body())
        finally:
            admin.dispose()
        target=self.evidence/'restored-new-directory'
        root=Path(__file__).resolve().parents[1]
        subprocess.run([sys.executable,'-c','from platform_app.maintenance import restore_backup; import sys; restore_backup(sys.argv[1],sys.argv[2])',str(archive),str(target)],cwd=root,check=True)
        port=int(os.environ.get('DATABASE_REPORT_RESTORE_PORT','8903'))
        with socket.socket() as probe:
            self.assertNotEqual(probe.connect_ex(('127.0.0.1',port)),0,'restore port occupied')
        restored_url='http://127.0.0.1:'+str(port)
        with (self.evidence/'restore-server.log').open('w',encoding='utf-8') as log:
            server=subprocess.Popen([sys.executable,str(root/'app.py'),'--no-import','--port',str(port),'--data-dir',str(target)],cwd=root,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                for _ in range(100):
                    try:
                        urllib.request.urlopen(restored_url+'/health',timeout=.5).close();break
                    except OSError:
                        time.sleep(.1)
                else:
                    self.fail('restored synthetic service did not start')
                for user in ['researcher','colleague','admin']:
                    before=self.playwright.request.new_context();after=self.playwright.request.new_context()
                    try:
                        for client,base in [(before,URL),(after,restored_url)]:
                            token=client.get(base+'/api/session').json()['csrf']
                            response=client.post(base+'/api/login',data={'username':user,'password':'LocalDemo2026!'},headers={'X-CSRF-Token':token})
                            self.assertTrue(response.ok,response.text())
                        rows=before.get(URL+'/api/records?size=100').json()['items']
                        for row in rows:
                            path='/api/records/'+row['id']
                            expected=before.get(URL+path).json()
                            actual=after.get(restored_url+path).json()
                            for value in [expected,actual]:
                                for attachment in value['attachments']:attachment.pop('index',None)
                            self.assertEqual(actual,expected)
                            path='/api/history/record/'+row['id']
                            self.assertEqual(after.get(restored_url+path).json(),before.get(URL+path).json())
                            for file in expected['attachments']:
                                path='/api/attachments/'+file['id']
                                self.assertEqual(after.get(restored_url+path).body(),before.get(URL+path).body())
                        self.assertEqual(after.get(restored_url+'/api/collections').json(),before.get(URL+'/api/collections').json())
                    finally:
                        before.dispose();after.dispose()
                with self.browser.new_context(viewport={'width':390,'height':900}) as context:
                    restored=context.new_page();restored.goto(restored_url)
                    restored.get_by_role('button',name='研究员',exact=True).click()
                    restored.goto(restored_url+'#collections')
                    restored.locator('[data-action=open-collection][data-id="'+cid+'"]').click()
                    restored.get_by_role('button',name='编辑资料夹',exact=True).click()
                    restored.locator('[data-form=research-collection] [name=description]').fill('新目录恢复后继续维护')
                    restored.get_by_role('button',name='保存资料夹',exact=True).click()
                    expect(restored.locator('.workspace-topic')).to_contain_text('新目录恢复后继续维护')
                    restored.screenshot(path=str(self.evidence/'restored-folder-390.png'),full_page=True)
            finally:
                layout.LayoutBrowserTests.stop_server(server)


if __name__ == '__main__':
    unittest.main(verbosity=2)
