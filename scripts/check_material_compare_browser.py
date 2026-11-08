"""#125: actual browser / HTTP acceptance using only a new synthetic library.

Run: python scripts/check_material_compare_browser.py
Owned port 8896; no imports, paid services, or existing libraries.
"""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[1]
PORT = 8896
URL = f'http://127.0.0.1:{PORT}'
sys.path.insert(0, str(ROOT))
from platform_app.web import create_app
from tests.synthetic_ai import ENV


class Quiet(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


class MaterialCompareBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = Path(tempfile.mkdtemp(prefix='database-material-compare-'))
        print('Comparison evidence:', cls.evidence, flush=True)
        with socket.socket() as probe:
            assert probe.connect_ex(('127.0.0.1', PORT)) != 0, 'Owned port is occupied'
        cls.app = create_app(cls.evidence/'data', testing=True)
        cls.server = make_server('127.0.0.1', PORT, cls.app, threaded=True, request_handler=Quiet)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.p = sync_playwright().start()
        cls.client = cls.p.request.new_context(base_url=URL)
        for _ in range(100):
            try:
                if cls.client.get('/health').ok:
                    break
            except Exception:
                time.sleep(.1)
        else:
            raise RuntimeError('Synthetic server did not start')
        cls.write(cls.client, '/api/login', {'username':'researcher', 'password':'LocalDemo2026!'})
        cls.records = []
        for number in range(5):
            cls.records.append(cls.write(cls.client, '/api/records', {
                'kind':'report', 'title':f'Comparison original {number}',
                'abstract':f'Original abstract {number}.' if number != 2 else '',
                'chinese_title':f'合成比较资料 {number}' if number == 0 else '',
                'chinese_abstract':'人工中文摘要，保留原始依据。' if number == 0 else '',
                'authors':'Synthetic Author' if number != 2 else '',
                'publication_title':'Synthetic Publication',
                'published_on':'2024' if number == 0 else '2025-02' if number == 1 else '',
                'body_html':'<p>Synthetic saved body.</p>' if number == 0 else '',
                'url':'https://example.org/compare' if number == 0 else '',
            }))
        # Use the real translation HTTP contract, replacing only provider transport.
        cls.write(cls.client, '/api/login', {'username':'admin','password':'LocalDemo2026!'})
        cls.write(cls.client, '/api/admin/ai/config', {'cap':'1','currency':'USD'})
        cls.write(cls.client, '/api/login', {'username':'researcher','password':'LocalDemo2026!'})
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = 'https://api.deepseek.com/chat/completions'
        response.read.return_value = json.dumps({'model':'deepseek-flash',
            'usage':{'prompt_tokens':10,'completion_tokens':8,'total_tokens':18},
            'choices':[{'finish_reason':'stop','message':{'content':json.dumps({
                'title':'合成机器译题','abstract':'合成机器译文，与原始摘要分别保存。'})}}]}).encode()
        rid = cls.records[1]['id']
        with patch.dict(os.environ, {**ENV,'DEEPSEEK_API_KEY':'synthetic-local-test','DEEPSEEK_BASE_URL':'https://api.deepseek.com'}), patch('urllib.request.OpenerDirector.open', return_value=response) as provider:
            job = cls.write(cls.client, '/api/records/'+rid+'/translations', {'version':1,'request_id':'compare-fixture'})
            result = cls.write(cls.client, '/api/translations/'+job['id']+'/run')
            assert result['status'] == 'succeeded', result
            assert provider.call_count == 1
        cls.browser = cls.p.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None)

    @staticmethod
    def write(client, path, data=None, method='POST'):
        csrf = client.get(URL+'/api/session').json()['csrf']
        response = client.fetch(URL+path, method=method, data=data or {}, headers={'X-CSRF-Token':csrf})
        assert response.ok, response.text()
        return response.json()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.client.dispose()
        cls.p.stop()
        cls.server.shutdown()
        cls.thread.join(timeout=10)
        cls.server.server_close()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width':1366, 'height':900})
        self.page = self.context.new_page()
        self.page.set_default_timeout(5000)
        self.errors = []
        self.csp = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('console', lambda message: self.csp.append(message.text) if 'Content Security Policy' in message.text or 'style-src' in message.text else None)
        self.page.goto(URL)
        self.page.get_by_role('button', name='研究员', exact=True).click()
        self.page.goto(URL+'#library?feed=all&sort=title&size=2')
        expect(self.page.locator('.library-row')).to_have_count(2)

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.csp, [])

    def start_selection(self):
        self.page.locator('.reading-tools > summary').click()
        self.page.get_by_role('button', name='选择资料比较', exact=True).click()

    def test_two_cross_page_and_reading_return(self):
        page = self.page
        self.start_selection()
        expect(page.get_by_role('button', name='比较已选资料', exact=True)).to_be_disabled()
        page.locator('[data-library-select]').nth(0).check()
        page.get_by_role('button', name='下一页', exact=True).click()
        expect(page.locator('.pagination')).to_contain_text('第 2 / 3 页')
        page.locator('[data-library-select]').nth(0).check()
        page.get_by_role('button', name='比较已选资料', exact=True).click()
        compare = page.get_by_role('region', name='资料比较', exact=True)
        expect(compare).to_be_visible()
        expect(compare).to_contain_text('Comparison original 0')
        expect(compare).to_contain_text('Comparison original 2')
        columns = compare.locator('.material-compare-values').first.locator('.material-compare-value')
        first, second = columns.nth(0).bounding_box(), columns.nth(1).bounding_box()
        self.assertGreater(second['x'], first['x'] + first['width'])
        self.assertLess(abs(first['y'] - second['y']), 2)
        expect(compare).to_contain_text('Comparison original 0')
        expect(compare).to_contain_text('Comparison original 2')
        expect(compare).to_contain_text('人工中文摘要，保留原始依据。')
        expect(compare).to_contain_text('暂无原始摘要')
        expect(compare).to_contain_text('发表时间未知')
        expect(compare.get_by_role('link', name='打开原文', exact=True)).to_have_attribute('href','https://example.org/compare')
        page.screenshot(path=str(self.evidence/'two-cross-page-1366.png'), full_page=True)
        compare.get_by_role('button', name='阅读这篇', exact=True).first.click()
        expect(page.locator('.library-reader')).to_contain_text('Synthetic saved body.')
        expect(page.locator('.library-reader-head')).to_contain_text('比较中的资料')
        expect(page.get_by_role('button',name='返回比较',exact=True)).to_have_count(1)
        page.get_by_role('button', name='返回比较', exact=True).click()
        expect(compare).to_be_visible()
        compare.get_by_role('button', name='关闭比较', exact=True).click()
        expect(compare).not_to_be_visible()
        expect(page.locator('.pagination')).to_contain_text('第 2 / 3 页')
        expect(page.locator('[data-library-selection-count]')).to_have_text('已选 2 条')
        expect(page.get_by_role('button', name='比较已选资料', exact=True)).to_be_focused()

    def test_three_machine_original_and_quantity_guard(self):
        page = self.page
        self.start_selection()
        page.locator('[data-library-select]').nth(0).check()
        expect(page.get_by_role('button', name='比较已选资料', exact=True)).to_be_disabled()
        page.locator('[data-library-select]').nth(1).check()
        page.get_by_role('button', name='下一页', exact=True).click()
        expect(page.locator('.pagination')).to_contain_text('第 2 / 3 页')
        page.locator('[data-library-select]').nth(0).check()
        page.locator('[data-library-select]').nth(1).check()
        expect(page.get_by_role('button', name='比较已选资料', exact=True)).to_be_disabled()
        expect(page.locator('[data-material-selection-status]')).to_contain_text('已选 4 篇，请减少至 2–3 篇')
        page.locator('[data-library-select]').nth(1).uncheck()
        page.get_by_role('button', name='比较已选资料', exact=True).click()
        compare = page.get_by_role('region', name='资料比较', exact=True)
        expect(compare).to_contain_text('合成机器译文，与原始摘要分别保存。')
        expect(compare).to_contain_text('Original abstract 1.')
        expect(compare).to_contain_text('机器译题')
        expect(compare).to_contain_text('机器译文')
        columns = compare.locator('.material-compare-values').first.locator('.material-compare-value')
        expect(columns).to_have_count(3)
        boxes = [columns.nth(i).bounding_box() for i in range(3)]
        self.assertTrue(boxes[0]['x'] < boxes[1]['x'] < boxes[2]['x'])
        self.assertLess(max(b['y'] for b in boxes)-min(b['y'] for b in boxes), 2)
        page.screenshot(path=str(self.evidence/'three-machine-1366.png'), full_page=True)

    def test_narrow_and_zoom_equivalent_keyboard(self):
        page = self.page
        for width, label in [(390,'390'),(320,'320'),(683,'200-percent-effective-viewport')]:
            with self.subTest(width=width):
                page.set_viewport_size({'width':width,'height':900})
                page.goto(URL+'#library?feed=all&sort=title&size=2')
                expect(page.locator('.library-row')).to_have_count(2)
                self.start_selection()
                page.locator('[data-library-select]').nth(0).press('Space')
                page.locator('[data-library-select]').nth(1).focus()
                page.keyboard.press('Space')
                page.get_by_role('button',name='比较已选资料',exact=True).focus()
                page.keyboard.press('Enter')
                compare = page.get_by_role('region',name='资料比较',exact=True)
                expect(compare).to_contain_text('合成机器译文，与原始摘要分别保存。')
                expect(compare.get_by_role('heading',name='资料比较 · 2 篇',exact=True)).to_be_focused()
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                columns = compare.locator('.material-compare-values').first.locator('.material-compare-value')
                first, second = columns.nth(0).bounding_box(), columns.nth(1).bounding_box()
                self.assertAlmostEqual(first['x'],second['x'],delta=2)
                self.assertGreater(second['y'],first['y'])
                expect(page.locator('#toast.show')).to_have_count(0)
                page.screenshot(path=str(self.evidence/f'fields-{label}.png'),full_page=True)
                compare.get_by_role('button',name='阅读这篇',exact=True).first.focus()
                page.keyboard.press('Enter')
                expect(page.get_by_role('button',name='返回比较',exact=True)).to_be_visible()
                page.get_by_role('button',name='返回比较',exact=True).focus()
                page.keyboard.press('Enter')
                expect(compare).to_be_visible()
                compare.get_by_role('button',name='关闭比较',exact=True).focus()
                page.keyboard.press('Enter')
                expect(page.get_by_role('button',name='比较已选资料',exact=True)).to_be_focused()
                page.get_by_role('button',name='清空选择',exact=True).click()

    def test_failure_retry_close_reopen_and_late_response(self):
        page = self.page
        self.start_selection()
        page.locator('[data-library-select]').nth(0).check()
        page.locator('[data-library-select]').nth(1).check()
        rid = self.records[0]['id']
        page.route('**/api/records/'+rid, lambda route: route.fulfill(status=503,json={'error':'Synthetic failure'}))
        page.get_by_role('button',name='比较已选资料',exact=True).click()
        compare = page.get_by_role('region',name='资料比较',exact=True)
        expect(compare).to_contain_text('读取失败，请重试。')
        expect(compare).not_to_contain_text('Comparison original 0')
        page.unroute('**/api/records/'+rid)
        compare.get_by_role('button',name='重试读取',exact=True).click()
        expect(compare).to_contain_text('Comparison original 0')
        compare.get_by_role('button',name='关闭比较',exact=True).click()
        waiting = []
        def hold(route):
            waiting.append((route,route.fetch()))
        page.route('**/api/records/'+rid, hold)
        page.get_by_role('button',name='比较已选资料',exact=True).click()
        expect(compare).to_contain_text('正在读取第 1 篇')
        compare.get_by_role('button',name='关闭比较',exact=True).click()
        expect(compare).not_to_be_visible()
        page.unroute('**/api/records/'+rid)
        page.get_by_role('button',name='比较已选资料',exact=True).click()
        expect(compare).to_contain_text('Comparison original 0')
        for route,response in waiting:
            route.fulfill(response=response)
        expect(compare).to_contain_text('Comparison original 0')
        page.screenshot(path=str(self.evidence/'retry-reopen-1366.png'),full_page=True)

    def test_access_revocation_is_explicit_and_removable(self):
        page = self.page
        self.write(page.request,'/api/login',{'username':'colleague','password':'LocalDemo2026!'})
        page.reload()
        expect(page.locator('.library-row')).to_have_count(2)
        self.start_selection()
        page.locator('[data-library-select]').nth(0).check()
        page.locator('[data-library-select]').nth(1).check()
        rid = self.records[0]['id']
        detail = self.client.get('/api/records/'+rid).json()
        try:
            self.write(self.client,'/api/records/'+rid,{'version':detail['version'],'visibility':'restricted'},'PUT')
            self.assertEqual(page.request.get(URL+'/api/records/'+rid).status,404)
            page.get_by_role('button',name='比较已选资料',exact=True).click()
            compare = page.get_by_role('region',name='资料比较',exact=True)
            expect(compare).to_contain_text('资料已删除或无权访问。')
            expect(compare).not_to_contain_text('Comparison original 0')
            expect(compare).not_to_contain_text('人工中文摘要')
            page.screenshot(path=str(self.evidence/'revoked-1366.png'),full_page=True)
            compare.locator('[data-material-remove="'+rid+'"]').click()
            expect(compare).to_contain_text('比较需要 2–3 篇')
            compare.get_by_role('button',name='关闭比较',exact=True).click()
            expect(page.locator('[data-library-selection-count]')).to_have_text('已选 1 条')
        finally:
            current = self.client.get('/api/records/'+rid).json()
            self.write(self.client,'/api/records/'+rid,{'version':current['version'],'visibility':'shared'},'PUT')

    def test_route_and_account_switch_ignore_late_details(self):
        page = self.page
        for switch in ['route','account']:
            self.start_selection()
            page.locator('[data-library-select]').nth(0).check()
            page.locator('[data-library-select]').nth(1).check()
            rid = self.records[0]['id']
            waiting = []
            def hold(route):
                waiting.append((route,route.fetch()))
            page.route('**/api/records/'+rid,hold)
            page.get_by_role('button',name='比较已选资料',exact=True).click()
            expect(page.get_by_role('region',name='资料比较',exact=True)).to_contain_text('正在读取第 1 篇')
            if switch == 'route':
                page.locator('[data-action="nav"][data-id="sources"]').click()
                expect(page.locator('.library-workspace')).to_have_count(0)
            else:
                page.locator('[data-action="logout"]').click()
                page.get_by_role('button',name='协作同事',exact=True).click()
                expect(page.locator('.topbar')).to_contain_text('周')
            page.unroute('**/api/records/'+rid)
            for route,response in waiting:
                route.fulfill(response=response)
            expect(page.get_by_role('region',name='资料比较',exact=True)).to_have_count(0)
            if switch == 'route':
                page.go_back()
                expect(page.locator('.library-row')).to_have_count(2)
                expect(page.get_by_role('region',name='资料比较',exact=True)).to_have_count(0)
                page.get_by_role('button',name='清空选择',exact=True).click()
            else:
                page.goto(URL+'#library?feed=all&sort=title&size=2')
                expect(page.locator('.library-row')).to_have_count(2)
                page.locator('.reading-tools > summary').click()
                page.get_by_role('button',name='选择资料比较',exact=True).click()
                expect(page.locator('[data-library-selection-count]')).to_have_text('已选 0 条')

    def test_real_browser_zoom_200_percent(self):
        # Only a disposable browser profile/extension is used for actual zoom.
        extension = self.evidence/'zoom-extension'
        extension.mkdir(exist_ok=True)
        (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,
            'name':'Synthetic comparison zoom','version':'1.0','permissions':['tabs'],
            'background':{'service_worker':'worker.js'}}),encoding='utf-8')
        (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});',encoding='utf-8')
        zoom_context = self.p.chromium.launch_persistent_context(str(self.evidence/'zoom-profile'),
            executable_path=self.p.chromium.executable_path,headless=False,
            ignore_default_args=['--disable-extensions'],viewport={'width':1366,'height':900},
            args=['--headless=new','--disable-extensions-except='+str(extension),'--load-extension='+str(extension)])
        original_page = self.page
        try:
            worker = zoom_context.service_workers[0] if zoom_context.service_workers else zoom_context.wait_for_event('serviceworker')
            self.page = page = zoom_context.pages[0]
            page.on('pageerror',lambda error:self.errors.append(str(error)))
            page.on('console',lambda message:self.csp.append(message.text) if 'Content Security Policy' in message.text or 'style-src' in message.text else None)
            page.goto(URL)
            page.get_by_role('button',name='研究员',exact=True).click()
            page.goto(URL+'#library?feed=all&sort=title&size=2')
            expect(page.locator('.library-row')).to_have_count(2)
            actual = worker.evaluate("async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id);}",URL)
            self.assertEqual(actual,2)
            self.assertLess(page.evaluate('innerWidth'),700)
            self.assertEqual(page.evaluate('devicePixelRatio'),2)
            self.start_selection()
            page.locator('[data-library-select]').nth(0).check()
            page.locator('[data-library-select]').nth(1).check()
            page.get_by_role('button',name='比较已选资料',exact=True).focus()
            page.keyboard.press('Enter')
            compare = page.get_by_role('region',name='资料比较',exact=True)
            expect(compare).to_contain_text('合成机器译文，与原始摘要分别保存。')
            self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
            # Old Chromium clips full_page images at browser zoom. Capture the
            # real viewport at successive fields so every frame is complete.
            page.screenshot(path=str(self.evidence/'real-browser-zoom-200-percent.png'))
            compare.locator('.material-compare-field').nth(3).scroll_into_view_if_needed()
            page.screenshot(path=str(self.evidence/'real-browser-zoom-200-percent-chinese.png'))
            compare.locator('.material-compare-field').nth(7).scroll_into_view_if_needed()
            page.screenshot(path=str(self.evidence/'real-browser-zoom-200-percent-dates.png'))
            page.keyboard.press('Escape')
            expect(page.get_by_role('button',name='比较已选资料',exact=True)).to_be_focused()
        finally:
            self.page = original_page
            zoom_context.close()


if __name__ == '__main__':
    unittest.main()
