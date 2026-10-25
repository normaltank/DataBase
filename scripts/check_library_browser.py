"""Synthetic browser acceptance for #15. Requires local Playwright Chromium.

Run explicitly: python scripts/check_library_browser.py
Creates a temporary library, starts only 127.0.0.1:8861, and keeps screenshots
and its evidence report in the system temporary directory.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8861"


class LibraryBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = Path(tempfile.mkdtemp(prefix="database-reader-browser-"))
        cls.output = (cls.evidence / "server.log").open("w", encoding="utf-8")
        # Refuse an occupied test port; never reuse an unknown running library.
        import socket
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 8861)) == 0:
                raise RuntimeError("8861 is occupied; stop the identified test service first")
        cls.server = subprocess.Popen(
            [sys.executable, str(ROOT / "app.py"), "--no-import", "--port", "8861", "--data-dir", str(cls.evidence / "data")],
            cwd=ROOT, stdout=cls.output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        for _ in range(100):
            try:
                urllib.request.urlopen(URL + "/health", timeout=1).close()
                break
            except OSError:
                time.sleep(.1)
        else:
            cls.server.terminate()
            raise RuntimeError("Test service did not start")
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel=os.environ.get("DATABASE_BROWSER_CHANNEL") or None)
        request = cls.playwright.request.new_context(base_url=URL)
        token = request.get("/api/session").json()["csrf"]
        response = request.post("/api/login", data={"username": "researcher", "password": "LocalDemo2026!"}, headers={"X-CSRF-Token": token})
        assert response.ok, response.text()
        token = response.json()["csrf"]
        for number in range(15):
            response = request.post("/api/records", data={
                "kind": "report", "title": f"试验资料 {number:02d} · 长题名：资料平台如何保留出处与研究上下文" + "连续阅读与公开核对" * 3,
                "authors": "合成作者甲；合成作者乙", "published_on": f"2026-10-{number + 1:02d}",
                "publication_title": "合成研究来源", "body_html": f"<p>第 {number:02d} 份资料的合成正文，供阅读验证。</p>",
                "abstract": "仅用于临时库的合成资料。",
            }, headers={"X-CSRF-Token": token})
            assert response.status == 201, response.text()
        request.dispose()
        print("Browser evidence:", cls.evidence, flush=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.output.close()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1366, "height": 900}, has_touch=True)
        self.page = self.context.new_page()
        self.page.set_default_timeout(5000)
        self.page.goto(URL)
        self.page.get_by_role("button", name="研究员", exact=True).click()
        self.page.get_by_title("资料库", exact=True).click()
        expect(self.page.get_by_role("heading", name="资料库", exact=True)).to_be_visible()

    def tearDown(self):
        self.context.close()

    def test_views_keep_query_order_page_and_results(self):
        page = self.page
        page.get_by_label("排序方式").select_option("title")
        page.get_by_role("button", name="下一页", exact=True).click()
        expect(page.get_by_text("第 2 / 2 页", exact=True)).to_be_visible()
        titles = page.locator(".record-list .record-title").all_text_contents()
        page.get_by_role("button", name="卡片视图", exact=True).click()
        self.assertEqual(page.locator(".record-list .record-title").all_text_contents(), titles)
        expect(page.get_by_label("排序方式")).to_have_value("title")
        expect(page.get_by_text("第 2 / 2 页", exact=True)).to_be_visible()
        page.get_by_role("button", name="紧凑列表", exact=True).click()
        self.assertEqual(page.locator(".record-list .record-title").all_text_contents(), titles)
        page.screenshot(path=str(self.evidence / "desktop-list.png"), full_page=True)

    def test_favorite_changes_survive_views_and_match_reader_and_server(self):
        page = self.page
        page.get_by_role('button', name='卡片视图', exact=True).click()
        first = page.locator('[data-library-record]').first
        rid = first.get_attribute('data-library-record')
        star = first.locator('[data-action="favorite"]')
        star.click()
        expect(star).to_have_attribute('data-saved', 'true')
        self.assertTrue(self.context.request.get(URL + '/api/records/' + rid).json()['favorite'])
        page.get_by_role('button', name='紧凑列表', exact=True).click()
        page.get_by_role('button', name='卡片视图', exact=True).click()
        expect(star).to_have_attribute('data-saved', 'true')
        expect(star).to_have_attribute('aria-pressed', 'true')
        star.click()
        expect(star).to_have_attribute('data-saved', 'false')
        self.assertFalse(self.context.request.get(URL + '/api/records/' + rid).json()['favorite'])
        first.locator('.record-title button').click()
        reader = page.get_by_role('region', name='连续阅读')
        reader.locator('.ux-maintenance summary').click()
        reader_star = reader.locator('[data-action="favorite"]')
        expect(reader_star).to_have_attribute('data-saved', 'false')
        first.locator('[data-library-select]').check()
        page.get_by_role('button', name='收藏选中', exact=True).click()
        expect(page.locator('[data-library-batch-status]')).to_contain_text('已处理 1 条')
        expect(reader_star).to_have_attribute('data-saved', 'true')
        page.get_by_role('button', name='紧凑列表', exact=True).click()
        page.get_by_role('button', name='卡片视图', exact=True).click()
        expect(star).to_have_attribute('data-saved', 'true')
        reader_star.click()
        expect(reader_star).to_have_attribute('data-saved', 'false')
        page.get_by_role('button', name='紧凑列表', exact=True).click()
        page.get_by_role('button', name='卡片视图', exact=True).click()
        expect(star).to_have_attribute('data-saved', 'false')
        self.assertFalse(self.context.request.get(URL + '/api/records/' + rid).json()['favorite'])
        page.screenshot(path=str(self.evidence / 'favorite-view-reader-consistency.png'), full_page=True)

    def test_narrow_loading_reader_has_touch_return_and_ignores_late_response(self):
        page = self.page
        page.set_viewport_size({'width': 390, 'height': 844})
        origin = page.locator('.record-list .record-title button').first
        rid = origin.get_attribute('data-id')
        waiting = []
        def hold_detail(route):
            waiting.append((route, route.fetch()))
        page.route('**/api/records/' + rid, hold_detail)
        origin.click()
        reader = page.get_by_role('dialog', name='连续阅读')
        expect(reader.get_by_text('正在读取资料…', exact=True)).to_be_visible()
        back = reader.get_by_role('button', name='返回列表', exact=True)
        expect(back).to_be_visible()
        page.screenshot(path=str(self.evidence / 'narrow-loading-return.png'))
        back.tap()
        expect(reader).not_to_be_visible()
        expect(origin).to_be_focused()
        self.assertEqual(len(waiting), 1)
        route, response = waiting.pop()
        route.fulfill(response=response)
        page.wait_for_load_state('networkidle')
        expect(reader).not_to_be_visible()
        expect(origin).to_be_enabled()
        self.assertIsNone(page.locator('.record-list').get_attribute('inert'))
        page.screenshot(path=str(self.evidence / 'narrow-return-after-late-detail.png'))

    def test_first_desktop_read_reveals_body_and_return_restores_list_position(self):
        page = self.page
        page.set_viewport_size({'width': 1440, 'height': 960})
        origin = page.locator('.record-list .record-title button').first
        before = page.evaluate('window.scrollY')
        origin.click()
        reader = page.get_by_role('region', name='连续阅读')
        paragraph = reader.locator('#ux-body p').first
        expect(paragraph).to_be_visible()
        box = paragraph.bounding_box()
        self.assertGreaterEqual(box['y'], 0)
        self.assertLess(box['y'] + box['height'], 960)
        reading_scroll = page.evaluate('window.scrollY')
        page.screenshot(path=str(self.evidence / 'desktop-first-reader-viewport.png'))
        reader.get_by_role('button', name='下一条', exact=True).click()
        expect(reader.get_by_text('本页第 2 / 12 条', exact=True)).to_be_visible()
        self.assertAlmostEqual(page.evaluate('window.scrollY'), reading_scroll, delta=2)
        reader.get_by_role('button', name='返回列表', exact=True).click()
        self.assertAlmostEqual(page.evaluate('window.scrollY'), before, delta=2)
        expect(origin).to_be_focused()

    def test_continuous_reader_returns_to_list_on_desktop_and_narrow_screen(self):
        page = self.page
        title = page.locator('.record-list .record-title button').nth(1)
        text = title.inner_text()
        title.click()
        reader = page.get_by_role('region', name='连续阅读')
        expect(reader).to_be_visible()
        expect(reader.get_by_role('heading', name=text, exact=True)).to_be_visible()
        expect(page.locator('.record-list')).to_be_visible()
        reader.get_by_role('button', name='下一条', exact=True).click()
        expect(reader.get_by_role('heading', name=text, exact=True)).not_to_be_visible()
        expect(reader.get_by_text('本页第 3 / 12 条', exact=True)).to_be_visible()
        reader.scroll_into_view_if_needed()
        expect(reader.locator('#ux-body .rich-prose')).to_be_in_viewport()
        page.screenshot(path=str(self.evidence / 'desktop-reader.png'))
        reader.get_by_role('button', name='返回列表', exact=True).click()
        expect(reader).not_to_be_visible()
        expect(title).to_be_focused()
        page.set_viewport_size({'width': 390, 'height': 844})
        title.click()
        dialog = page.get_by_role('dialog', name='连续阅读')
        expect(dialog).to_be_visible()
        self.assertEqual(dialog.bounding_box()['y'], 0)
        self.assertEqual(dialog.bounding_box()['height'], 844)
        page.screenshot(path=str(self.evidence / 'narrow-reader.png'))
        page.keyboard.press('Escape')
        expect(dialog).not_to_be_visible()
        expect(title).to_be_focused()
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
        page.screenshot(path=str(self.evidence / 'narrow-list-viewport.png'))
        page.screenshot(path=str(self.evidence / 'narrow-list.png'), full_page=True)

    def test_selection_is_explicit_crosses_pages_and_clears_with_context(self):
        page = self.page
        page.get_by_role('button', name='选择当前页', exact=True).click()
        expect(page.get_by_text('已选 12 条', exact=True)).to_be_visible()
        page.get_by_role('button', name='下一页', exact=True).click()
        expect(page.get_by_text('已选 12 条', exact=True)).to_be_visible()
        checks = page.get_by_role('checkbox', name='选择资料：')
        expect(checks).to_have_count(3)
        checks.first.check()
        expect(page.get_by_text('已选 13 条', exact=True)).to_be_visible()
        page.get_by_role('button', name='上一页', exact=True).click()
        expect(page.get_by_role('checkbox', name='选择资料：').first).to_be_checked()
        page.get_by_role('checkbox', name='选择资料：').first.uncheck()
        expect(page.get_by_text('已选 12 条', exact=True)).to_be_visible()
        page.get_by_role('button', name='卡片视图', exact=True).click()
        expect(page.get_by_text('已选 12 条', exact=True)).to_be_visible()
        page.get_by_label('排序方式').select_option('title')
        expect(page.get_by_text('已选 0 条', exact=True)).to_be_visible()

        expect(page.locator('#toast')).to_contain_text('已清空选择')
        page.get_by_role('button', name='选择当前页', exact=True).click()
        page.get_by_title('来源目录', exact=True).click()
        page.get_by_title('资料库', exact=True).click()
        expect(page.get_by_text('已选 0 条', exact=True)).to_be_visible()
        page.get_by_role('checkbox', name='选择资料：').first.check()
        page.get_by_role('button', name='退出登录', exact=True).last.click()
        page.get_by_role('button', name='协作同事', exact=True).click()
        expect(page.get_by_text('已选 0 条', exact=True)).to_be_visible()
        expect(page.locator('.library-reader')).not_to_be_visible()
        page.reload()
        expect(page.get_by_text('已选 0 条', exact=True)).to_be_visible()

    def test_lost_permission_removes_selection_and_reading_on_return(self):
        page = self.page
        page.get_by_role('button', name='退出登录', exact=True).last.click()
        page.get_by_role('button', name='协作同事', exact=True).click()
        first = page.locator('.record-list .record-title button').first
        title = first.inner_text()
        page.get_by_role('checkbox', name='选择资料：').first.check()
        first.click()
        expect(page.get_by_role('region', name='连续阅读')).to_be_visible()
        request = self.playwright.request.new_context(base_url=URL)
        csrf = request.get('/api/session').json()['csrf']
        result = request.post('/api/login', data={'username': 'researcher', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf})
        csrf = result.json()['csrf']
        records = request.get('/api/records?sort=date').json()['items']
        record = next(record for record in records if record['title'] == title)
        response = request.put('/api/records/' + record['id'], data={'version': record['version'], 'visibility': 'restricted'}, headers={'X-CSRF-Token': csrf})
        self.assertTrue(response.ok, response.text())
        try:
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(page.get_by_text('已选 0 条', exact=True)).to_be_visible()
            expect(page.get_by_role('region', name='连续阅读')).not_to_be_visible()
            expect(page.get_by_role('button', name=title, exact=True)).not_to_be_visible()
        finally:
            response = request.put('/api/records/' + record['id'], data={'version': record['version'] + 1, 'visibility': 'shared'}, headers={'X-CSRF-Token': csrf})
            self.assertTrue(response.ok, response.text())
            request.dispose()

    def test_z_existing_reading_actions_remain_available(self):
        page = self.page
        page.locator('.record-list .record-title button').first.click()
        reader = page.get_by_role('region', name='连续阅读')
        reader.get_by_text('作品署名与文章单位', exact=True).click()
        reader.get_by_role('button', name='整理署名', exact=True).click()
        expect(page.get_by_role('dialog')).to_be_visible()
        page.get_by_role('button', name='关闭', exact=True).click()
        reader.locator('.ux-maintenance summary').click()
        reader.get_by_role('button', name='编辑内容', exact=True).click()
        expect(page.get_by_label('题名 *', exact=True)).to_be_visible()
        page.get_by_role('button', name='关闭并保留草稿', exact=True).click()
        reader.get_by_role('button', name='复制出处', exact=True).click()
        reader.get_by_role('button', name='写阅读说明', exact=True).click()
        note = page.locator('form.ux-reading-form')
        note.locator('[data-rich-input]').fill('这是一段保留原资料关联的合成阅读说明。')
        note.get_by_role('button', name='保存内容', exact=True).click()
        expect(note).not_to_be_visible()
        expect(page.locator('[data-reading-note]').last).to_be_visible()



if __name__ == "__main__":
    unittest.main(verbosity=2)
