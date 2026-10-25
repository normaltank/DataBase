"""Synthetic #16 acceptance through an independent browser and port 8863.

Run explicitly: python scripts/check_bulk_browser.py
Evidence and synthetic library remain in the printed temporary directory.
"""
import csv
import io
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
URL = "http://127.0.0.1:8863"


class BulkBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = Path(tempfile.mkdtemp(prefix="database-bulk-browser-"))
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 8863)) == 0:
                raise RuntimeError("8863 occupied; refusing to reuse another service")
        cls.output = (cls.evidence / "server.log").open("w", encoding="utf-8")
        cls.server = subprocess.Popen([sys.executable, str(ROOT / "app.py"), "--no-import", "--port", "8863", "--data-dir", str(cls.evidence / "data")], cwd=ROOT, stdout=cls.output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        for _ in range(100):
            try:
                urllib.request.urlopen(URL + "/health", timeout=1).close()
                break
            except OSError:
                time.sleep(.1)
        else:
            cls.server.terminate()
            raise RuntimeError("Synthetic test service did not start")
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()
        request = cls.playwright.request.new_context(base_url=URL)
        token = request.get("/api/session").json()["csrf"]
        response = request.post("/api/login", data={"username": "researcher", "password": "LocalDemo2026!"}, headers={"X-CSRF-Token": token})
        token = response.json()["csrf"]
        cls.ids = []
        for number in range(14):
            response = request.post("/api/records", data={"kind": "report", "title": f"批量试验 {number:02d} · 中文长题名与研究资料整理", "body_html": "<p>仅用于批量操作验收的合成正文。</p>"}, headers={"X-CSRF-Token": token})
            assert response.status == 201, response.text()
            cls.ids.append(response.json()["id"])
        response = request.post("/api/collections", data={"name": "批量验收专题", "visibility": "shared"}, headers={"X-CSRF-Token": token})
        cls.cid = response.json()["id"]
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
        self.context = self.browser.new_context(viewport={"width": 1366, "height": 900})
        self.page = self.context.new_page()
        self.page.set_default_timeout(5000)
        self.page.goto(URL)
        self.page.get_by_role("button", name="研究员", exact=True).click()
        self.page.get_by_title("资料库", exact=True).click()
        expect(self.page.get_by_role("heading", name="资料库", exact=True)).to_be_visible()

    def tearDown(self):
        self.context.close()

    def test_desktop_and_narrow_batch_workflow(self):
        page = self.page
        page.get_by_role("button", name="选择当前页", exact=True).click()
        expect(page.locator('[data-library-selection-count]')).to_have_text("已选 12 条")
        page.get_by_role("button", name="下一页", exact=True).click()
        page.locator('[data-library-select]').first.check()
        expect(page.locator('[data-library-selection-count]')).to_have_text("已选 13 条")
        page.get_by_role("button", name="收藏选中", exact=True).click()
        expect(page.locator('[data-library-batch-status]')).to_contain_text("13 条")
        page.get_by_role("button", name="加入专题", exact=True).click()
        page.get_by_label("目标专题").select_option(self.cid)
        page.get_by_role("button", name="确认加入", exact=True).click()
        expect(page.locator('[data-library-batch-status]')).to_contain_text("专题")
        with page.expect_download() as downloaded:
            page.get_by_role("button", name="导出选中 CSV", exact=True).click()
        rows = list(csv.DictReader(io.StringIO(Path(downloaded.value.path()).read_text(encoding="utf-8-sig"))))
        self.assertEqual(len(rows), 13)
        self.assertEqual(len({r["稳定编号"] for r in rows}), 13)
        page.screenshot(path=str(self.evidence / "desktop-bulk.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("button", name="收藏选中", exact=True).click()
        expect(page.locator('[data-library-batch-status]')).to_contain_text("原已收藏 13 条")
        page.get_by_role("button", name="加入专题", exact=True).click()
        page.get_by_label("目标专题").select_option(self.cid)
        page.screenshot(path=str(self.evidence / "narrow-bulk-dialog.png"), full_page=True)
        page.get_by_role("button", name="确认加入", exact=True).click()
        expect(page.locator('[data-library-batch-status]')).to_contain_text("原已存在 13 条")
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        page.screenshot(path=str(self.evidence / "narrow-bulk-result.png"), full_page=True)

    def test_failure_preserves_selection_and_conflict_can_be_reloaded(self):
        page = self.page
        page.locator('[data-library-select]').first.check()
        page.route('**/api/library/bulk/favorites', lambda route: route.fulfill(status=404, json={"error": "选中资料不存在或已无访问权限，请重新核对选择。"}))
        page.get_by_role('button', name='收藏选中', exact=True).click()
        expect(page.locator('[data-library-batch-status]')).to_contain_text('未完成，已保留选择')
        expect(page.locator('[data-library-selection-count]')).to_have_text('已选 1 条')
        expect(page.locator('[data-library-select]').first).to_be_checked()
        page.screenshot(path=str(self.evidence / 'batch-failure-preserved.png'), full_page=True)
        page.unroute('**/api/library/bulk/favorites')
        page.get_by_role('button', name='加入专题', exact=True).click()
        page.get_by_label('目标专题').select_option(self.cid)
        # Another member changes the public collection after this modal read it.
        request = self.playwright.request.new_context(base_url=URL)
        token = request.get('/api/session').json()['csrf']
        login = request.post('/api/login', data={'username': 'colleague', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': token})
        version = request.get('/api/collections/' + self.cid).json()['version']
        changed = request.put('/api/collections/' + self.cid, data={'version': version, 'description': '另一成员的合成修改'}, headers={'X-CSRF-Token': login.json()['csrf']})
        self.assertTrue(changed.ok, changed.text())
        request.dispose()
        page.get_by_role('button', name='确认加入', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('本次未加入任何资料，已保留选择')
        expect(page.get_by_role('alert')).to_contain_text('重新读取专题')
        expect(page.get_by_label('目标专题')).to_have_value(self.cid)
        page.get_by_role('button', name='重新读取专题', exact=True).click()
        expect(page.get_by_label('目标专题')).to_have_value(self.cid)
        page.get_by_role('button', name='确认加入', exact=True).click()
        expect(page.locator('[data-library-batch-status]')).to_contain_text('已处理 1 条')
        expect(page.locator('[data-library-selection-count]')).to_have_text('已选 1 条')

    def test_delayed_bulk_responses_do_not_survive_account_or_route_changes(self):
        page = self.page
        page.locator('[data-library-select]').first.check()
        waiting = []
        page.route('**/api/library/bulk/favorites', lambda route: waiting.append(route))
        page.get_by_role('button', name='收藏选中', exact=True).click()
        expect(page.locator('[data-library-batch-status]')).to_contain_text('正在收藏')
        page.get_by_title('专题资料夹', exact=True).click()
        expect(page.get_by_role('heading', name='专题资料夹', exact=True)).to_be_visible()
        self.assertEqual(len(waiting), 1)
        waiting.pop().fulfill(json={'selected': 1, 'added': 1, 'existing': 0})
        page.get_by_title('资料库', exact=True).click()
        expect(page.locator('[data-library-selection-count]')).to_have_text('已选 0 条')
        expect(page.locator('[data-library-batch-status]')).to_have_text('')
        page.locator('[data-library-select]').first.check()
        page.get_by_role('button', name='收藏选中', exact=True).click()
        expect(page.locator('[data-library-batch-status]')).to_contain_text('正在收藏')
        page.get_by_role('button', name='退出登录', exact=True).first.click()
        page.get_by_role('button', name='协作同事', exact=True).click()
        expect(page.get_by_role('heading', name='资料库', exact=True)).to_be_visible()
        self.assertEqual(len(waiting), 1)
        waiting.pop().fulfill(json={'selected': 1, 'added': 1, 'existing': 0})
        expect(page.locator('[data-library-selection-count]')).to_have_text('已选 0 条')
        expect(page.locator('[data-library-batch-status]')).to_have_text('')

    def test_closing_pending_collection_dialog_keeps_result_feedback(self):
        page = self.page
        page.locator('[data-library-select]').first.check()
        page.get_by_role('button', name='加入专题', exact=True).click()
        page.get_by_label('目标专题').select_option(self.cid)
        waiting = []
        page.route('**/api/library/bulk/collections/*', lambda route: waiting.append(route))
        page.get_by_role('button', name='确认加入', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('正在加入专题')
        page.get_by_role('button', name='关闭', exact=True).click()
        self.assertEqual(len(waiting), 1)
        waiting.pop().fulfill(json={'selected': 1, 'added': 1, 'existing': 0, 'version': 2})
        expect(page.locator('[data-library-batch-status]')).to_contain_text('已处理 1 条')
        expect(page.locator('[data-library-selection-count]')).to_have_text('已选 1 条')


if __name__ == "__main__":
    unittest.main(verbosity=2)
