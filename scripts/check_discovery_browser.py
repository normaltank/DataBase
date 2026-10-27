"""Actual fixed-source journey, synthetic RSS/socket and Temp database, port 8871."""
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from platform_app.web import create_app
from tests.test_assisted_intake import PublicSocket
from tests.test_discovery import FEED

PORT=8871
URL='http://127.0.0.1:'+str(PORT)


class QuietHandler(WSGIRequestHandler):
    def log(self,*args,**kwargs):
        pass


class DiscoveryBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_id=None
        cls.out=Path(tempfile.mkdtemp(prefix='liia-discovery-browser-'))
        cls.server=make_server('127.0.0.1',PORT,create_app(cls.out/'data',testing=True),threaded=True,request_handler=QuietHandler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.playwright=sync_playwright().start()
        cls.browser=cls.playwright.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None)
        print('Evidence:',cls.out,flush=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.playwright.stop();cls.server.shutdown();cls.thread.join()

    def test_two_entry_journey_drafts_failures_duplicates_and_accounts(self):
        sid = type(self).source_id
        for width in [1366,390]:
            with self.subTest(width=width):
                context=self.browser.new_context(viewport={'width':width,'height':900})
                self.addCleanup(context.close)
                page=context.new_page();errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(URL+'/#sources')
                page.get_by_role('button',name='研究员',exact=True).click()
                expect(page.get_by_role('button',name='退出登录',exact=True)).to_be_visible()
                csrf=context.request.get(URL+'/api/session').json()['csrf']
                if sid is None:
                    result=context.request.post(URL+'/api/sources',data=dict(name='Synthetic LIIA',kind='think_tank',website='https://liia.lv/en/'),headers={'X-CSRF-Token':csrf})
                    self.assertEqual(result.status,201,result.text());sid=result.json()['id'];type(self).source_id=sid
                # Each width gets unique synthetic article links, through the same adapter.
                xml=FEED.replace('synthetic-101','browser-'+str(width)+'-101').replace('synthetic-102','browser-'+str(width)+'-102')
                xml=xml.replace('Policy briefing','Policy briefing '+('long synthetic title '*12))
                original_dns=socket.getaddrinfo;original_connect=socket.create_connection
                def dns(host,*args,**kwargs):
                    return [(2,1,6,'',('93.184.216.34',443))] if host in {'liia.lv','www.liia.lv'} else original_dns(host,*args,**kwargs)
                def connect(address,*args,**kwargs):
                    return PublicSocket(xml.encode(),'application/xml') if address[0]=='93.184.216.34' else original_connect(address,*args,**kwargs)
                with patch('socket.getaddrinfo',side_effect=dns),patch('socket.create_connection',side_effect=connect),patch('ssl.SSLContext.wrap_socket',side_effect=lambda sock,**k:sock),patch('platform_app.store.now',return_value='2026-10-27T12:00:00+00:00'):
                    page.goto(URL+'/#sources?id='+sid)
                    page.get_by_role('button',name='发现近期资料',exact=True).click()
                    page.get_by_role('button',name='手动取得最近 30 天',exact=True).click()
                    expect(page.locator('[data-ris-queue]')).to_contain_text('2026-09-28 至 2026-10-27')
                    expect(page.locator('[data-ris-queue]')).to_contain_text('不代表栏目全部覆盖')
                    page.locator('[data-ris-edit="0"]').click()
                    form=page.locator('form[data-form=record]')
                    expect(form.locator('[name=kind]')).to_have_value('other')
                    expect(form.locator('[name=authors]')).to_have_value('')
                    expect(form.locator('[name=abstract]')).to_have_value('')
                    expect(form).to_contain_text('Series introduction only')
                    form.locator('[data-intake-review] > summary').click()
                    expect(form.locator('[data-intake-review]')).to_contain_text('RSS item.title')
                    form.locator('[data-intake-review] > summary').click()
                    form.locator('[name=title]').fill('Edited first '+str(width))
                    page.locator('[data-ris-edit="1"]').click()
                    expect(form).to_contain_text('未提供有效公开描述')
                    form.locator('[name=title]').fill('Edited second '+str(width))
                    page.locator('[data-ris-edit="0"]').click()
                    expect(form.locator('[name=title]')).to_have_value('Edited first '+str(width))
                    # New acquisition fails, preserving the already edited queue.
                    page.get_by_role('button',name='手动取得最近 30 天',exact=True).click()
                    with patch('socket.create_connection',side_effect=lambda address,*a,**k:PublicSocket(b'','application/xml','406 Not Acceptable') if address[0]=='93.184.216.34' else original_connect(address,*a,**k)):
                        page.get_by_role('button',name='确认重新取得并替换本次队列',exact=True).click()
                        expect(form.locator('.form-error')).to_contain_text('406')
                        expect(form.locator('[name=title]')).to_have_value('Edited first '+str(width))
                    page.get_by_role('button',name='关闭并保留草稿',exact=True).click()
                    page.reload()
                    page.get_by_role('button',name='发现近期资料',exact=True).click()
                    page.locator('[data-ris-edit="1"]').click()
                    expect(form.locator('[name=title]')).to_have_value('Edited second '+str(width))
                    # A public save failure (invalid calendar date) must keep input.
                    form.locator('[name=published_on]').fill('2026-02-30')
                    form.get_by_role('button',name='保存本条并接续',exact=True).click()
                    expect(form.locator('.form-error')).to_contain_text('日期不存在')
                    expect(form.locator('[name=title]')).to_have_value('Edited second '+str(width))
                    expect(form.locator('.form-error')).to_be_in_viewport()
                    page.screenshot(path=str(self.out/('failure-'+str(width)+'.png')))
                    form.locator('[name=published_on]').fill('2026-09-28')
                    form.get_by_role('button',name='保存本条并接续',exact=True).click()
                    expect(form.locator('[name=title]')).to_have_value('Edited first '+str(width))
                    form.get_by_role('button',name='保存本条并接续',exact=True).click()
                    expect(page.locator('[data-ris-queue]')).to_contain_text('已保存')
                    expect(page.locator('[data-ris-open]')).to_have_count(2)
                    page.locator('.drawer-body').evaluate('(el)=>el.scrollTop=0')
                    page.screenshot(path=str(self.out/('queue-'+str(width)+'.png')))
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                    page.locator('[data-ris-open]').first.click()
                    expect(page.locator('.drawer-body')).to_contain_text('Edited first '+str(width))
                    expect(page.locator('.drawer-body')).to_contain_text('来源发现依据')
                    page.screenshot(path=str(self.out/('record-'+str(width)+'.png')))
                    page.get_by_role('button',name='关闭',exact=True).click()
                    page.get_by_role('button',name='发现近期资料',exact=True).click()
                    expect(page.locator('[data-ris-queue]')).to_contain_text('已保存')
                    # A fresh preview does not create or overwrite any record.
                    page.get_by_role('button',name='手动取得最近 30 天',exact=True).click()
                    page.get_by_role('button',name='确认重新取得并替换本次队列',exact=True).click()
                    expect(page.locator('[data-ris-open]')).to_have_count(2)
                    page.get_by_role('button',name='关闭并保留草稿',exact=True).click()
                    page.get_by_role('button',name='退出登录',exact=True).click()
                    page.get_by_role('button',name='协作同事',exact=True).click()
                    page.goto(URL+'/#sources?id='+sid)
                    page.get_by_role('button',name='发现近期资料',exact=True).click()
                    expect(page.locator('[data-ris-queue]')).to_contain_text('0 条候选')
                    self.assertEqual(errors,[])

    def test_late_queue_editor_cannot_reopen_or_overwrite_unrelated_manual_record(self):
        for format in ('discovery', 'ris'):
            with self.subTest(format=format):
                context=self.browser.new_context(viewport={'width':1366,'height':900})
                self.addCleanup(context.close)
                page=context.new_page();errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(URL+'/#library')
                page.get_by_role('button',name='研究员',exact=True).click()
                expect(page.get_by_role('button',name='退出登录',exact=True)).to_be_visible()
                csrf=context.request.get(URL+'/api/session').json()['csrf']
                article='https://liia.lv/en/opinions/late-editor-'+format
                if format=='discovery':
                    sid=type(self).source_id
                    if sid is None:
                        source=context.request.post(URL+'/api/sources',data=dict(name='Synthetic race LIIA',kind='think_tank',website='https://liia.lv/en/'),headers={'X-CSRF-Token':csrf})
                        self.assertEqual(source.status,201,source.text());sid=source.json()['id'];type(self).source_id=sid
                    page.goto(URL+'/#sources?id='+sid)
                    page.get_by_role('button',name='发现近期资料',exact=True).click()
                    xml=('<rss><channel><item><title>Original synthetic candidate</title><link>'+article+'</link><pubDate>Tue, 27 Oct 2026 00:30:00 +0300</pubDate><description>.</description></item></channel></rss>').encode()
                    with patch('platform_app.intake.fetch_document',return_value={'bytes':xml}),patch('platform_app.store.now',return_value='2026-10-27T12:00:00+00:00'):
                        page.get_by_role('button',name='手动取得最近 30 天',exact=True).click()
                        expect(page.locator('[data-ris-edit="0"]')).to_be_visible()
                else:
                    page.get_by_role('button',name='导入 RIS 文件',exact=True).click()
                    sample=('TY  - GEN\nTI  - Original synthetic candidate\nUR  - '+article+'\nER  -\n').encode()
                    page.locator('[data-ris-file]').set_input_files({'name':'late-editor.ris','mimeType':'text/plain','buffer':sample})
                    page.locator('[data-ris-preview]').click()
                page.locator('[data-ris-edit="0"]').click()
                form=page.locator('form[data-form=record]')
                expect(form.get_by_role('button',name='保存本条并接续',exact=True)).to_be_enabled()
                form.locator('[name=title]').fill('Previously edited candidate '+format)
                page.locator('.drawer-head [data-action=close]').click()
                def reopen():
                    if format=='discovery':
                        page.goto(URL+'/#sources?id='+sid)
                        page.get_by_role('button',name='发现近期资料',exact=True).click()
                    else:
                        page.goto(URL+'/#library')
                        page.get_by_role('button',name='导入 RIS 文件',exact=True).click()
                    expect(page.locator('[data-ris-edit="0"]')).to_be_enabled()
                # An old preparation must neither reopen a closed drawer nor attach
                # its signed candidate to a new manual record in the same account.
                for replacement in (False,True):
                    reopen();pending=[]
                    def hold_preparation(route):
                        pending.append(route)
                    page.route('**/api/records?kind=research_note**',hold_preparation,times=1)
                    with page.expect_request('**/api/records?kind=research_note**'):
                        page.locator('[data-ris-edit="0"]').click()
                    expect(page.get_by_text('正在准备编辑与草稿保护…',exact=True)).to_be_visible()
                    self.assertEqual(len(pending),1)
                    page.locator('.drawer-head [data-action=close]').click()
                    if replacement:
                        page.locator('[data-action=nav][data-id=dashboard]').click()
                        page.locator('[data-action=new-record]').first.click()
                        expect(form.get_by_role('button',name='保存内容',exact=True)).to_be_enabled()
                        form.locator('[name=title]').fill('Unrelated manual draft '+format)
                        form.locator('[name=url]').fill('https://example.org/manual-'+format)
                    for route in pending:
                        route.continue_()
                    page.wait_for_load_state('networkidle')
                    if not replacement:
                        expect(page.locator('#modal-root [role=dialog]')).to_have_count(0)
                        continue
                    page.screenshot(path=str(self.out/('late-editor-'+format+'.png')))
                    expect(form.locator('[name=title]')).to_have_value('Unrelated manual draft '+format)
                    expect(form.locator('[name=url]')).to_have_value('https://example.org/manual-'+format)
                    expect(form.locator('[name=discovery_token],[name=ris_token],[data-ris-queue]')).to_have_count(0)
                    with page.expect_response(lambda response:response.url==URL+'/api/records' and response.request.method=='POST') as saved:
                        form.get_by_role('button',name='保存内容',exact=True).click()
                    self.assertEqual(saved.value.status,201,saved.value.text())
                    rid=saved.value.json()['id']
                    detail=context.request.get(URL+'/api/records/'+rid).json()
                    self.assertEqual(detail['title'],'Unrelated manual draft '+format)
                    self.assertEqual(detail['url'],'https://example.org/manual-'+format)
                    self.assertFalse(detail.get('discovery_evidence'))
                    self.assertFalse(detail.get('ris_evidence'))
                    expect(page.locator('.drawer-body')).to_contain_text('Unrelated manual draft '+format)
                    page.locator('.drawer-head [data-action=close]').click()
                reopen();page.locator('[data-ris-edit="0"]').click()
                expect(form.get_by_role('button',name='保存本条并接续',exact=True)).to_be_enabled()
                expect(form.locator('[name=title]')).to_have_value('Previously edited candidate '+format)
                expect(form.locator('[name=url]')).to_have_value(article)
                form.get_by_role('button',name='保存本条并接续',exact=True).click()
                expect(page.locator('[data-ris-open]')).to_have_count(1)
                rid=page.locator('[data-ris-open]').get_attribute('data-ris-open')
                detail=context.request.get(URL+'/api/records/'+rid).json()
                self.assertEqual(detail['title'],'Previously edited candidate '+format)
                self.assertEqual(detail['url'],article)
                self.assertEqual(detail[format+'_evidence'][0]['saved_fields']['title'],'Previously edited candidate '+format)
                self.assertEqual(errors,[])


if __name__=='__main__':
    unittest.main(verbosity=2)
