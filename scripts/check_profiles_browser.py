"""#21: source/person workflows through real browser and public HTTP only.

Runs an owned service on 8872, with synthetic data in the system temp directory.
DATABASE_PROFILE_EVIDENCE preserves the same fixture for before/after captures.
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
URL = "http://127.0.0.1:8872"
BASELINE = "--baseline" in sys.argv
if BASELINE:
    sys.argv.remove("--baseline")


class ProfileBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = Path(os.environ.get("DATABASE_PROFILE_EVIDENCE") or tempfile.mkdtemp(prefix="database-ui-profiles-"))
        cls.evidence.mkdir(parents=True, exist_ok=True)
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 8872)) == 0:
                raise RuntimeError("8872 occupied; refusing to reuse an unknown service")
        cls.output = (cls.evidence / "server.log").open("a", encoding="utf-8")
        cls.server = subprocess.Popen([sys.executable, str(ROOT / "app.py"), "--no-import", "--port", "8872", "--data-dir", str(cls.evidence / "data")], cwd=ROOT, stdout=cls.output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            try:
                urllib.request.urlopen(URL + "/health", timeout=1).close()
                break
            except OSError:
                time.sleep(.1)
        else:
            cls.server.terminate()
            raise RuntimeError("Synthetic service did not start")
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="msedge")
        request = cls.playwright.request.new_context(base_url=URL)
        cls.sign_in(request)
        saved = cls.evidence / "sample.json"
        if saved.exists():
            cls.sample = json.loads(saved.read_text(encoding="utf-8"))
        else:
            long_url = "https://example.org/" + "synthetic-long-evidence-reference-" * 7
            table = "<table><tr>" + "<th>合成比较维度</th>" * 8 + "</tr><tr>" + "<td>LongLatinReferenceWithoutSpacesForOverflowInspection</td>" * 8 + "</tr></table>"
            body = "<p>合成介绍：保留原文、出处及共同维护的责任。</p>" * 18 + table
            source = cls.call(request, "POST", "/api/sources", {"kind": "institution", "name": "合成研究中心｜机构与跨语言研究资料的持续积累" + "长题名" * 6, "original_name": "Synthetic Centre for Cross-language Regional Research Documentation", "institution_types": ["think_tank", "research_institute", "faculty"], "country": "拉脱维亚", "country_evidence": "合成地址 " + long_url, "scope_status": "active", "introduction_html": body, "aliases": "合成研究中心\nSynthetic Centre"})["id"]
            parent = cls.call(request, "POST", "/api/sources", {"kind": "institution", "name": "合成大学", "institution_types": ["university"], "country": "爱沙尼亚", "country_evidence": "合成地址"})["id"]
            cls.call(request, "PUT", "/api/sources/" + source, {"version": 1, "relationships": [{"type": "established_by", "target_id": parent, "evidence": "合成设立说明 " + long_url, "checked_on": "2026-10-20"}]})
            journal = cls.call(request, "POST", "/api/sources", {"kind": "journal", "name": "合成学刊｜语言政策与跨区域研究", "host_id": source + " | " + parent, "host_evidence": "双方共同主办的合成声明", "publisher_id": parent, "international_status": "yes", "international_evidence": "合成国际办刊宗旨", "introduction_html": "<p>合成期刊介绍。</p>", "scope_status": "active"})["id"]
            cls.call(request, "POST", "/api/sources", {"kind": "journal", "name": "合成国别待确认期刊", "international_status": "unknown"})
            person = cls.call(request, "POST", "/api/people", {"name": "合成人物｜亚历山大·跨语言与政策研究者", "original_name": "Aleksandrs Synthetic-Longsurname", "aliases": "合成研究员甲\nA. Synthetic", "introduction_html": body, "sources": "合成人物主页 " + long_url, "change_note": "合成身份依据"})["id"]
            other = cls.call(request, "POST", "/api/people", {"name": "合成人物乙", "change_note": "无头像空态合成样本"})["id"]
            cls.call(request, "PUT", "/api/people/" + person + "/employments", {"version": 0, "change_note": "合成履历", "items": [{"institution_id": source, "role": "研究员" + "跨语言研究" * 8, "start_date": "2020", "evidence": "合成任职依据 " + long_url}]})
            record = cls.call(request, "POST", "/api/records", {"kind": "report", "title": "合成已确认作品｜跨语言资料与出处", "source_id": source, "body_html": "<p>合成作品正文。</p>"})["id"]
            bylines = request.get(URL + "/api/records/" + record + "/bylines").json()
            cls.call(request, "PUT", "/api/records/" + record + "/bylines", {"version": bylines["version"], "record_version": bylines["record_version"], "change_note": "合成署名依据", "items": [{"raw_name": "合成人物", "target_type": "person", "target_id": person, "status": "confirmed", "evidence": "合成作品作者主页"}]})
            cls.call(request, "POST", "/api/records", {"kind": "directory_translation", "title": "合成目录译稿｜2024—2026卷期", "authors": "合成编译者", "coverage": "2024—2026，第1—6期", "related_source_ids": [source, journal], "body_html": table})
            note = cls.call(request, "POST", "/api/records", {"kind": "research_note", "title": "合成研究笔记｜多对象比较", "author_id": "researcher", "body_html": "<p>合成研究对象笔记。</p>", "research_subjects": [{"subject_type": kind, "subject_id": sid} for kind, sid in [("person", person), ("institution", source), ("journal", journal)]]})["id"]
            cls.sample = dict(source=source, parent=parent, journal=journal, person=person, other=other, record=record, note=note)
            saved.write_text(json.dumps(cls.sample, ensure_ascii=False, indent=2), encoding="utf-8")
        request.dispose()
        print("Profile evidence:", cls.evidence, flush=True)

    @staticmethod
    def call(request, method, path, data):
        token = request.get(URL + "/api/session").json()["csrf"]
        response = request.fetch(URL + path, method=method, data=data, headers={"X-CSRF-Token": token})
        assert response.ok, response.text()
        return response.json()

    @classmethod
    def sign_in(cls, request, username="researcher"):
        return cls.call(request, "POST", "/api/login", {"username": username, "password": "LocalDemo2026!"})

    @classmethod
    def stop_server(cls):
        if hasattr(cls, "browser"):
            cls.browser.close()
        if hasattr(cls, "playwright"):
            cls.playwright.stop()
        if cls.server.poll() is None:
            cls.server.terminate()
            cls.server.wait(timeout=10)
        cls.output.close()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 960})
        self.sign_in(self.context.request)
        self.page = self.context.new_page()
        self.page.set_default_timeout(5000)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def capture(self, name):
        self.page.screenshot(path=str(self.evidence / (("before-" if BASELINE else "after-") + name + ".png")), full_page=True)

    def test_01_person_chapters_preserve_route_and_query_return(self):
        page = self.page
        page.goto(URL + "/#people?q=合成人物")
        page.get_by_role("link", name="合成人物｜亚历山大·跨语言与政策研究者", exact=True).click()
        expect(page.get_by_role("heading", name="人物介绍", exact=True)).to_be_visible()
        self.capture("person-1440")
        if BASELINE:
            return
        before = page.url
        nav = page.get_by_role("navigation", name="人物章节", exact=True)
        for label in ["任职经历", "已确认作品", "研究笔记", "依据与档案信息"]:
            button = nav.get_by_role("button", name=label, exact=True)
            button.focus()
            page.keyboard.press("Enter")
            expect(page.get_by_role("heading", name=label, exact=True)).to_be_focused()
            self.assertEqual(page.url, before)
        page.get_by_role("link", name="← 返回作者目录", exact=True).click()
        expect(page.get_by_role("searchbox", name="搜索作者", exact=True)).to_have_value("合成人物")


if __name__ == "__main__":
    unittest.main(verbosity=2)
