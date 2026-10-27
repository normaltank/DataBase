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
        sid = None
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
                    self.assertEqual(result.status,201,result.text());sid=result.json()['id']
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


if __name__=='__main__':
    unittest.main(verbosity=2)
