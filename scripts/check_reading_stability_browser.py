"""Public HTTP and browser acceptance for empty visits and stable batch queries.

Only a new synthetic directory and an owned local port are used. No provider calls.
"""
import csv
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get('DATABASE_BROWSER_PORT', '8904'))
URL = f'http://127.0.0.1:{PORT}'


class ReadingStabilityBrowserTests(unittest.TestCase):
    def test_empty_refresh_translation_paging_and_expired_confirmation(self):
        evidence = Path(tempfile.mkdtemp(prefix='database-reading-stability-'))
        print('Reading stability evidence:', evidence, flush=True)
        with socket.socket() as probe:
            self.assertNotEqual(probe.connect_ex(('127.0.0.1', PORT)), 0, 'Owned test port is occupied')
        with (evidence/'server.log').open('w', encoding='utf-8') as log:
            server = subprocess.Popen([sys.executable, str(ROOT/'app.py'), '--no-import', '--port', str(PORT),
                '--data-dir', str(evidence/'data')], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                with sync_playwright() as p:
                    request = p.request.new_context(base_url=URL)
                    try:
                        for _ in range(100):
                            try:
                                if request.get('/health').ok:
                                    break
                            except Exception:
                                time.sleep(.1)
                        else:
                            self.fail('Synthetic service did not start')
                        browser = p.chromium.launch(channel=os.environ.get('DATABASE_BROWSER_CHANNEL') or None)
                        try:
                            context = browser.new_context(viewport={'width':1366,'height':900})
                            page = context.new_page()
                            errors=[]
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            page.set_default_timeout(8000)
                            def write(client, path, data=None, method='POST'):
                                csrf=client.get(URL+'/api/session').json()['csrf']
                                result=client.fetch(URL+path, method=method, data=data or {}, headers={'X-CSRF-Token':csrf})
                                self.assertTrue(result.ok, result.text())
                                return result.json()
                            def relogin(label):
                                write(page.request, '/api/logout')
                                page.reload()
                                page.get_by_role('button', name=label, exact=True).click()
                                expect(page.get_by_role('heading',name='资料',exact=True)).to_be_visible()
                            def finish(count):
                                page.get_by_role('button',name='结束本次浏览',exact=True).click()
                                with page.expect_response(lambda r: '/finish' in r.url and r.request.method=='POST') as response:
                                    page.get_by_role('button',name=f'确认这 {count} 条已浏览',exact=True).click()
                                self.assertEqual(response.value.json()['confirmed'], count)
                            page.goto(URL)
                            page.get_by_role('button',name='研究员',exact=True).click()
                            expect(page.get_by_role('heading',name='资料',exact=True)).to_be_visible()
                            expect(page.locator('.library-row')).to_have_count(0)
                            z=write(page.request, '/api/records', {'title':'Z after empty visit','kind':'report'})
                            page.reload()
                            expect(page.locator('.library-row')).to_have_count(1)
                            page.screenshot(path=str(evidence/'empty-then-arrival-1366.png'))
                            relogin('研究员')
                            expect(page.locator('.library-row')).to_have_count(1)
                            finish(1)
                            expect(page.locator('.library-row')).to_have_count(0)
                            for number in range(4):
                                write(page.request, '/api/records', {'title':'Synthetic seed '+str(number),'kind':'report'})
                            # Label the real public batch order. HTTP creation may
                            # cross a clock second; the fixture must not assume it
                            # shares an insertion timestamp.
                            initial=write(page.request,'/api/reading-batches')
                            ordered=page.request.get(URL+'/api/records',params={'batch':initial['id'],'batch_scope':'all','size':100}).json()['items']
                            self.assertEqual(len(ordered),4)
                            articles=dict(zip(['A','B','C','D'],ordered))
                            for title, article in articles.items():
                                write(page.request,'/api/records/'+article['id'],{'version':1,'title':title,
                                    'chinese_title':'' if title=='B' else '窗口词 '+title},'PUT')
                            page.goto(URL+'#library?feed=new&batch_scope=all&q=窗口词&size=2')
                            expect(page.locator('.record-title button')).to_have_text(['窗口词 A','窗口词 C'])
                            write(page.request, '/api/records/'+articles['B']['id'], {'version':2,'chinese_title':'窗口词 B'}, 'PUT')
                            page.get_by_role('button',name='下一页',exact=True).click()
                            expect(page.locator('.record-title button')).to_have_text(['窗口词 D'])
                            expect(page.locator('.results-head')).to_contain_text('3')
                            page.screenshot(path=str(evidence/'stable-page-two-1366.png'))
                            page.get_by_role('button',name='结束本次浏览',exact=True).click()
                            page.screenshot(path=str(evidence/'exact-three-confirmation-1366.png'))
                            with page.expect_response(lambda r: '/finish' in r.url and r.request.method=='POST') as response:
                                page.get_by_role('button',name='确认这 3 条已浏览',exact=True).click()
                            self.assertEqual(response.value.json()['confirmed'],3)
                            expect(page.locator('.record-title button')).to_have_text(['窗口词 B'])
                            relogin('协作同事')
                            batch=write(page.request, '/api/reading-batches')
                            zero_setup={'batch':batch['id'],'batch_scope':'all','q':'Z after empty visit'}
                            shown=page.request.get(URL+'/api/records',params=zero_setup).json()
                            write(page.request, '/api/reading-batches/'+batch['id']+'/finish',
                                  {'conditions':zero_setup,'confirmation':shown['reading_confirmation']})
                            page.goto(URL+'#library?feed=new&batch_scope=all&q=后补独立词')
                            expect(page.locator('.library-row')).to_have_count(0)
                            write(request, '/api/login', {'username':'researcher','password':'LocalDemo2026!'})
                            write(request, '/api/records/'+articles['C']['id'], {'version':2,'chinese_title':'窗口词 C 后补独立词'}, 'PUT')
                            page.reload()
                            expect(page.locator('.library-row')).to_have_count(0)
                            page.get_by_role('button',name='结束本次浏览',exact=True).click()
                            expect(page.locator('#modal-root')).to_contain_text('全部未浏览资料继续保留')
                            page.screenshot(path=str(evidence/'explicit-zero-confirmation-1366.png'))
                            with page.expect_response(lambda r: '/finish' in r.url and r.request.method=='POST') as response:
                                page.get_by_role('button',name='确认 0 条并重新查找',exact=True).click()
                            self.assertEqual(response.value.json()['confirmed'],0)
                            expect(page.locator('.record-title button')).to_have_text(['窗口词 C 后补独立词'])
                            expect(page.get_by_role('textbox',name='资料关键词',exact=True)).to_have_value('后补独立词')
                            self.assertEqual(write(page.request,'/api/reading-batches')['pending_total'],4)
                            page.screenshot(path=str(evidence/'zero-confirmation-preserved-query-1366.png'))
                            page.goto(URL+'#library?feed=new&batch_scope=all&q=窗口词')
                            expect(page.locator('.library-row')).to_have_count(4)
                            page.get_by_role('button',name='结束本次浏览',exact=True).click()
                            write(request, '/api/login', {'username':'researcher','password':'LocalDemo2026!'})
                            write(request, '/api/records/'+articles['A']['id'], {'version':2,'visibility':'restricted'}, 'PUT')
                            with page.expect_response(lambda r: '/finish' in r.url and r.request.method=='POST') as response:
                                page.get_by_role('button',name='确认这 4 条已浏览',exact=True).click()
                            self.assertEqual(response.value.status,409)
                            expect(page.get_by_role('button',name='保留条件，重新读取',exact=True)).to_be_visible()
                            expect(page.get_by_role('textbox',name='资料关键词',exact=True)).to_have_value('窗口词')
                            for width, zoom in [(1366,1),(390,1),(1366,2)]:
                                page.set_viewport_size({'width':width,'height':900})
                                page.evaluate('(z)=>document.documentElement.style.zoom=z',zoom)
                                page.screenshot(path=str(evidence/f'expired-confirmation-{width}-zoom{zoom}.png'))
                                expect(page.get_by_role('button',name='保留条件，重新读取',exact=True)).to_be_visible()
                            page.evaluate('document.documentElement.style.zoom=1')
                            page.set_viewport_size({'width':1366,'height':900})
                            page.get_by_role('button',name='保留条件，重新读取',exact=True).click()
                            expect(page.locator('.library-row')).to_have_count(3)
                            expect(page.get_by_role('textbox',name='资料关键词',exact=True)).to_have_value('窗口词')
                            query=page.evaluate('Object.fromEntries(recordQuery())')
                            exported=page.request.get(URL+'/api/export',params=query)
                            rows=list(csv.DictReader(io.StringIO(exported.body().decode('utf-8-sig'))))
                            self.assertEqual([r['稳定编号'] for r in rows],[articles[k]['id'] for k in ['B','C','D']])
                            finish(3)
                            expect(page.locator('.library-row')).to_have_count(0)
                            self.assertEqual(errors,[])
                            (evidence/'result.json').write_text(json.dumps({'empty_refresh_and_relogin':True,
                                'page_two':['D'],'confirmed_after_translation':3,'permission_conflict':409,
                                'confirmed_after_reread':3,'explicit_zero_preserved_pending':4,
                                'remaining_for_colleague':[], 'javascript_errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
                        finally:
                            browser.close()
                    finally:
                        request.dispose()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)


if __name__=='__main__':
    unittest.main()
