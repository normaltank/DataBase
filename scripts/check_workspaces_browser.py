"""Public browser/HTTP acceptance for #22; isolated synthetic data on port 8873.

Run with the configured Python and DATABASE_BROWSER_CHANNEL=msedge.
No production library is imported or copied. Evidence stays in Temp.
"""
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
PORT = 8873
URL = f"http://127.0.0.1:{PORT}"


def call(request, path, data=None, method="POST", status=200):
    csrf = request.get(URL + "/api/session").json()["csrf"]
    response = request.fetch(URL + path, method=method, data=data or {}, headers={"X-CSRF-Token": csrf})
    assert response.status == status, f"{method} {path}: {response.status} {response.text()}"
    return response.json()


def login(request, user="researcher"):
    call(request, "/api/login", {"username": user, "password": "LocalDemo2026!"})


class WorkspaceBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = Path(tempfile.mkdtemp(prefix="database-workspaces-browser-"))
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", PORT)) == 0:
                raise RuntimeError("8873 is occupied; refusing unknown service")
        cls.log = (cls.evidence / "server.log").open("w", encoding="utf-8")
        cls.server = subprocess.Popen([sys.executable, str(ROOT / "app.py"), "--no-import", "--port", str(PORT),
            "--data-dir", str(cls.evidence / "data")], cwd=ROOT, stdout=cls.log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.server.poll() is not None:
                raise RuntimeError("Owned server exited; see server.log")
            try:
                urllib.request.urlopen(URL + "/health", timeout=.5).close()
                break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError("Owned server did not start")
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = cls.pw.chromium.launch(channel=os.environ.get("DATABASE_BROWSER_CHANNEL", "msedge"))
        cls.addClassCleanup(cls.browser.close)
        request = cls.pw.request.new_context()
        login(request)
        cls.raw = call(request, "/api/records", {"kind": "report", "title": "合成原始资料｜长中文题名与LongLatinOriginalMaterialTitle", "body_html": "<p>合成原文正文，保留出处。</p>"}, status=201)["id"]
        cls.report = call(request, "/api/records", {"kind": "research_report", "title": "本人合成阶段研究报告", "author_id": "researcher", "body_html": "<p>合成研究报告。</p>", "linked_ids": [cls.raw]}, status=201)["id"]
        cls.pending = call(request, "/api/records", {"kind": "compilation", "title": "代交合成成果等待作者确认", "author_id": "colleague", "body_html": "<p>待作者本人确认。</p>"}, status=201)["id"]
        columns = "".join(f"<th>比较维度{n}</th>" for n in range(7))
        table = "<table><thead><tr>" + columns + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>合成比较材料{r}，长原文ReferenceWithoutSpacesForWrapping{c}</td>" for c in range(7)) + "</tr>" for r in range(5)) + "</tbody></table>"
        cls.body = "<h2>长篇比较笔记</h2>" + "<p>仅用于临时验收的合成研究内容，保存出处与版本。</p>" * 24 + table
        cls.topic_name = "合成专题｜跨语言政策、区域社会与资料依据的长期比较"
        cls.topic = call(request, "/api/collections", {"name": cls.topic_name, "visibility": "shared", "research_question": "不同来源如何支持可核查的比较研究？", "description": "临时合成专题", "comparison_html": cls.body, "stage_judgment": "有待继续核查。"}, status=201)["id"]
        for rid in [cls.raw, cls.report]:
            call(request, f"/api/collections/{cls.topic}/items", {"record_id": rid})
        call(request, "/api/sources", {"kind": "portal", "name": "合成检索门户", "website": "https://example.org/search"}, status=201)
        request.dispose()
        print("Workspace evidence:", cls.evidence, flush=True)

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)
        cls.log.close()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000})
        self.addCleanup(self.context.close)
        login(self.context.request)
        self.page = self.context.new_page()
        self.page.set_default_timeout(5000)
        self.navigation = 0
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def route(self, name):
        self.navigation += 1
        self.page.goto(URL + f"/?workspace-check={self.navigation}#" + name)
        self.page.locator("#content").wait_for()
        self.page.wait_for_function("() => !document.querySelector('#content .boot')")

    def open_topic(self):
        self.route("collections")
        self.page.locator(f'[data-action="open-collection"][data-id="{self.topic}"]').first.click()
        expect(self.page.get_by_role("dialog").get_by_role("heading", name=self.topic_name, exact=True)).to_be_visible()

    def shot(self, name):
        self.page.screenshot(path=str(self.evidence / (name + ".png")))

    def test_topic_chapters_reach_materials_and_reports_without_changing_route(self):
        self.open_topic()
        self.shot("topic-before-chapters")
        before = self.page.url
        nav = self.page.get_by_role("navigation", name="专题章节", exact=True)
        for label in ["资料与证据", "报告与成果", "研究内容", "研究问题"]:
            control = nav.get_by_text(label, exact=True)
            control.focus()
            control.press("Enter")
            target = self.page.get_by_role("dialog").get_by_role("heading", name=label, exact=True)
            expect(target).to_be_focused()
            expect(target).to_be_in_viewport()
            self.assertEqual(self.page.url, before)
        self.shot("topic-after-chapters")
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
