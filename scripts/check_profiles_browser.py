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
import uuid
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
        self.page.screenshot(path=str(self.evidence / (("before-" if BASELINE else "after-") + name + ".png")), full_page=self.page.get_by_role("dialog").count() == 0)

    def audit(self, name):
        metrics = self.page.evaluate("""() => {
          const shown=e=>e&&e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
          const small=[],walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;
          while(n=walker.nextNode()){if(!n.textContent.trim()||!shown(n.parentElement)||n.parentElement.closest('script,style'))continue;
            const size=parseFloat(getComputedStyle(n.parentElement).fontSize);if(size<14)small.push({text:n.textContent.trim().slice(0,50),size});}
          return {width:innerWidth,scrollWidth:document.documentElement.scrollWidth,small,
            tables:[...document.querySelectorAll('.reading-table')].filter(shown).map(e=>({client:e.clientWidth,scroll:e.scrollWidth}))};
        }""")
        (self.evidence / (name + ".json")).write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        self.assertLessEqual(metrics["scrollWidth"], metrics["width"] + 1, name)
        self.assertEqual(metrics["small"], [], name)
        self.capture(name)

    def test_00_source_direct_route(self):
        self.page.goto(URL + "/#sources?id=" + self.sample["source"])
        expect(self.page.get_by_role("heading", name="来源介绍", exact=True)).to_be_visible()
        self.assertEqual(self.page.get_by_role("dialog").count(), 0)
        self.assertIn("id=" + self.sample["source"], self.page.url)
        self.capture("source-page-direct")

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

    def test_02_source_filters_remain_visible_and_keep_distinct_dimensions(self):
        page = self.page
        page.goto(URL + "/#sources?group=journal")
        expect(page.get_by_role("heading", name="来源目录", exact=True)).to_be_visible()
        self.capture("sources-1440")
        if BASELINE:
            return
        page.get_by_text("筛选条件", exact=True).click()
        page.get_by_label("期刊主办国别", exact=True).select_option("拉脱维亚")
        page.get_by_label("国际定位", exact=True).select_option("yes")
        page.get_by_role("button", name="应用筛选", exact=True).click()
        expect(page.get_by_role("button", name="移除筛选：期刊主办国别：拉脱维亚", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="移除筛选：国际定位：是 · 有依据", exact=True)).to_be_visible()
        expect(page.get_by_role("link", name="合成学刊｜语言政策与跨区域研究", exact=True)).to_be_visible()
        expect(page.get_by_label("期刊主办国别", exact=True)).not_to_be_visible()
        page.get_by_role("button", name="移除筛选：国际定位：是 · 有依据", exact=True).click()
        self.assertIn("country=", page.url)
        self.assertNotIn("international=", page.url)
        page.get_by_role("button", name="机构", exact=True).click()
        self.assertNotIn("country=", page.url)
        page.get_by_text("筛选条件", exact=True).click()
        page.get_by_label("机构类型", exact=True).select_option("think_tank")
        page.get_by_role("button", name="应用筛选", exact=True).click()
        expect(page.get_by_role("button", name="移除筛选：机构类型：智库", exact=True)).to_be_visible()

    def test_03_source_chapters_keep_front_content_evidence_and_route(self):
        page = self.page
        page.goto(URL + "/#sources?group=institution")
        page.locator('[data-action="source-preview"][data-id="' + self.sample["source"] + '"]').first.click()
        dialog = page.get_by_role("dialog", name="来源快速预览", exact=True)
        expect(dialog.get_by_role("heading", name="来源介绍", exact=True)).to_be_visible()
        self.capture("source-detail-1440")
        if BASELINE:
            return
        before = page.url
        nav = dialog.get_by_role("navigation", name="来源章节", exact=True)
        for label in ["来源内容", "来源信息", "关系与作品", "研究笔记", "依据与核查"]:
            button = nav.get_by_role("button", name=label, exact=True)
            button.focus()
            page.keyboard.press("Enter")
            expect(dialog.get_by_role("heading", name=label, exact=True)).to_be_focused()
            self.assertEqual(page.url, before)
        expect(dialog.get_by_text("合成目录译稿｜2024—2026卷期", exact=True)).to_be_visible()
        page.keyboard.press("Escape")
        page.goto(URL + "/#sources?group=journal")
        page.locator('[data-action="source-preview"][data-id="' + self.sample["journal"] + '"]').first.click()
        dialog = page.get_by_role("dialog", name="来源快速预览", exact=True)
        dialog.get_by_role("navigation", name="来源章节", exact=True).get_by_role("button", name="依据与核查", exact=True).click()
        expect(dialog.get_by_text("主办国别的依据", exact=True)).to_be_visible()
        expect(dialog.get_by_text("国际定位依据", exact=True)).to_be_visible()

    def test_03b_directory_profile_preview_refresh_and_cross_object_paths(self):
        page = self.page
        page.goto(URL + "/#sources?group=institution&q=合成研究中心")
        expect(page.get_by_role("heading", name="来源目录", exact=True)).to_be_visible()
        before = page.url
        preview = page.locator('[data-action="source-preview"][data-id="' + self.sample["source"] + '"]')
        preview.click()
        dialog = page.get_by_role("dialog", name="来源快速预览", exact=True)
        expect(dialog.get_by_role("heading", name="机构发布资料", exact=True)).to_be_visible()
        self.assertEqual(page.url, before)
        dialog.get_by_role("button", name="编辑来源", exact=True).click()
        form = page.locator('form[data-form="source"]')
        form.locator('[name="research_scope"]').fill("合成预览维护范围")
        form.get_by_role("button", name="保存修订", exact=True).click()
        expect(page.get_by_role("dialog", name="来源快速预览", exact=True)).to_contain_text("合成预览维护范围")
        self.assertEqual(page.url, before)
        page.keyboard.press("Escape")
        expect(page.get_by_role("searchbox", name="来源关键词")).to_have_value("合成研究中心")
        page.locator('.source-card h2 a').click()
        expect(page.locator('.source-page h1')).to_be_visible()
        self.assertIn("id=" + self.sample["source"], page.url)
        page.reload()
        expect(page.locator('.source-page h1')).to_be_visible()
        self.assertEqual(page.get_by_role("dialog").count(), 0)
        nav = page.get_by_role("navigation", name="来源章节", exact=True)
        for label in ["来源信息", "关系与作品", "来源内容", "研究笔记", "依据与核查"]:
            nav.get_by_role("button", name=label, exact=True).focus()
            page.keyboard.press("Enter")
            expect(page.get_by_role("heading", name=label, exact=True)).to_be_focused()
        self.assertEqual(page.locator('.source-page').get_by_text("ISSN", exact=True).count(), 0)
        page.get_by_role("link", name="← 返回来源目录", exact=True).click()
        expect(page.get_by_role("searchbox", name="来源关键词")).to_have_value("合成研究中心")
        page.goto(URL + "/#sources?id=" + self.sample["journal"])
        expect(page.get_by_role("heading", name="刊物刊载资料", exact=True)).to_be_visible()
        expect(page.locator('.source-page').get_by_text("ISSN", exact=True)).to_be_visible()
        page.locator('.source-page').get_by_role("button", name="合成大学", exact=True).first.click()
        expect(page.locator('.source-page h1')).to_have_text("合成大学")
        page.go_back()
        expect(page.get_by_role("heading", name="刊物刊载资料", exact=True)).to_be_visible()
        page.get_by_role("button", name="合成目录译稿｜2024—2026卷期", exact=True).click()
        expect(page.get_by_role("dialog")).to_contain_text("合成目录译稿｜2024—2026卷期")
        page.keyboard.press("Escape")
        expect(page.get_by_role("heading", name="刊物刊载资料", exact=True)).to_be_visible()
        page.goto(URL + "/#sources?id=missing-synthetic-source")
        expect(page.get_by_role("heading", name="无法打开来源档案", exact=True)).to_be_visible()

    def test_03c_direct_profiles_reflow(self):
        page = self.page
        for width in [1440, 1024, 390, 320]:
            page.set_viewport_size({"width":width,"height":900})
            page.goto(URL + "/#sources?id=" + self.sample["source"])
            expect(page.locator('.source-page h1')).to_be_visible()
            self.audit("source-page-" + str(width))
            table = page.get_by_role("region", name="内容表格 1，可横向滚动", exact=True).first
            table.focus()
            page.keyboard.press("ArrowRight")
            self.assertGreater(table.evaluate("e=>e.scrollWidth"), table.evaluate("e=>e.clientWidth"))
            page.get_by_role("navigation", name="来源章节").get_by_role("button", name="来源内容", exact=True).click()
            expect(page.get_by_role("heading", name="来源内容", exact=True)).to_be_focused()
            self.audit("source-page-content-" + str(width))
            page.goto(URL + "/#sources?id=" + self.sample["journal"])
            expect(page.locator('.source-page h1')).to_be_visible()
            self.audit("journal-page-" + str(width))

    def test_03d_standalone_edits_history_translations_notes_and_old_ids(self):
        page = self.page
        source_name = "合成独立维护机构-" + uuid.uuid4().hex[:6]
        source = self.call(self.context.request, "POST", "/api/sources", {"kind":"institution", "name":source_name})["id"]
        page.goto(URL + "/#sources?id=" + source)
        page.get_by_role("button", name="编辑来源", exact=True).click()
        form = page.locator('form[data-form="source"]')
        form.locator('[name="name"]').fill(source_name + "修订")
        form.locator('[data-rich-input]').fill("合成档案的背景沿革正文。")
        page.get_by_role("button", name="关闭并保留草稿", exact=True).click()
        expect(page.locator('.source-page h1')).to_have_text(source_name)
        page.get_by_role("button", name="编辑来源", exact=True).click()
        page.get_by_role("button", name="恢复草稿", exact=True).click()
        expect(form.locator('[name="name"]')).to_have_value(source_name + "修订")
        form.get_by_role("button", name="保存修订", exact=True).click()
        expect(page.locator('.source-page h1')).to_have_text(source_name + "修订")
        expect(page.get_by_text("合成档案的背景沿革正文。", exact=True)).to_be_visible()
        page.get_by_role("button", name="新建目录译稿", exact=True).click()
        form = page.locator('form[data-form="record"]')
        expect(form).not_to_have_attribute("inert", "")
        form.locator('[name="title"]').fill("合成维护目录译稿")
        form.locator('[name="authors"]').fill("合成编译者")
        form.locator('[name="coverage"]').fill("2026年第1期")
        form.get_by_role("button", name="保存内容", exact=True).click()
        expect(page.get_by_role("dialog")).to_contain_text("合成维护目录译稿")
        page.keyboard.press("Escape")
        expect(page.locator('[data-source-content="translations"]')).to_contain_text("合成维护目录译稿")
        page.get_by_role("button", name="写研究笔记", exact=True).click()
        form = page.locator('form[data-form="record"]')
        expect(form).not_to_have_attribute("inert", "")
        form.locator('[name="title"]').fill("合成明确研究对象笔记")
        form.get_by_role("button", name="保存内容", exact=True).click()
        expect(page.get_by_role("dialog")).to_contain_text("合成明确研究对象笔记")
        page.keyboard.press("Escape")
        expect(page.locator('.note-subject-profile')).to_contain_text("合成明确研究对象笔记")
        self.sign_in(self.context.request, "admin")
        page.reload()
        expect(page.locator('.source-page h1')).to_be_visible()
        page.get_by_text("历史与维护", exact=True).click()
        # Closing a record reader must leave the source version as the review target.
        page.get_by_role("button", name="合成维护目录译稿", exact=True).click()
        expect(page.get_by_role("dialog")).to_contain_text("合成维护目录译稿")
        page.keyboard.press("Escape")
        page.get_by_role("button", name="标记已核对", exact=True).click()
        expect(page.locator('.source-profile-heading').get_by_text("已核对", exact=True)).to_be_visible()
        page.get_by_text("历史与维护", exact=True).click()
        page.get_by_role("button", name="修改历史", exact=True).click()
        page.get_by_role("button", name="恢复此版本", exact=True).last.click()
        expect(page.locator('.source-page h1')).to_have_text(source_name)
        duplicate = self.call(self.context.request, "POST", "/api/sources", {"name":"合成旧编号-" + uuid.uuid4().hex[:6], "kind":"institution"})["id"]
        latest = self.context.request.get(URL + "/api/sources/" + source).json()
        self.call(self.context.request, "POST", "/api/merge", {"type":"source", "keep_id":source, "duplicate_id":duplicate, "keep_version":latest["version"], "duplicate_version":1, "confirmed":True})
        page.goto(URL + "/#sources?id=" + duplicate)
        expect(page.locator('.source-page h1')).to_have_text(source_name)
        expect(page.locator('.source-page .notice').first).to_contain_text("旧编号")
        self.capture("source-old-id")

    def test_03e_direct_login_publication_and_portal(self):
        publication_name = "合成其他出版物-" + uuid.uuid4().hex[:6]
        portal_name = "合成采集入口-" + uuid.uuid4().hex[:6]
        publication = self.call(self.context.request, "POST", "/api/sources", {"name":publication_name, "kind":"serial"})["id"]
        portal = self.call(self.context.request, "POST", "/api/sources", {"name":portal_name, "kind":"portal"})["id"]
        self.page.goto(URL + "/#sources?id=" + publication)
        expect(self.page.locator('.source-page h1')).to_have_text(publication_name)
        expect(self.page.get_by_role("heading", name="刊物刊载资料", exact=True)).to_be_visible()
        self.page.goto(URL + "/#sources?group=maintenance")
        self.page.get_by_role("button", name=portal_name, exact=True).last.click()
        expect(self.page.get_by_role("dialog", name="来源快速预览", exact=True)).to_contain_text(portal_name)
        self.assertNotIn("id=" + portal, self.page.url)
        fresh = self.browser.new_context()
        try:
            page = fresh.new_page()
            page.goto(URL + "/#sources?id=" + publication)
            expect(page.get_by_role("heading", name="登录知汇", exact=True)).to_be_visible()
            page.get_by_role("button", name="研究员", exact=True).click()
            expect(page.locator('.source-page h1')).to_have_text(publication_name)
            self.assertIn("id=" + publication, page.url)
        finally:
            fresh.close()

    def test_03f_visible_counts_and_pagination_in_page_and_preview(self):
        page = self.page
        request = self.context.request
        source = self.call(request, "POST", "/api/sources", {"name":"合成分页研究所-" + uuid.uuid4().hex[:6], "kind":"institution"})["id"]
        for index in range(15):
            self.call(request, "POST", "/api/records", {"kind":"report", "title":"合成分页资料-%02d" % index, "source_id":source})
        self.call(request, "POST", "/api/records", {"kind":"report", "title":"合成不可读资料", "source_id":source, "visibility":"restricted"})
        for index in range(14):
            self.call(request, "POST", "/api/records", {"kind":"research_note", "title":"合成分页对象笔记-%02d" % index, "author_id":"researcher", "research_subjects":[{"subject_type":"institution","subject_id":source}]})
        self.call(request, "POST", "/api/records", {"kind":"research_note", "title":"合成不可读对象笔记", "author_id":"researcher", "visibility":"restricted", "research_subjects":[{"subject_type":"institution","subject_id":source}]})
        self.sign_in(request, "colleague")
        page.goto(URL + "/#sources?id=" + source)
        records = page.locator('[data-source-content="published"]')
        expect(records).to_contain_text("当前可阅读 15 份")
        self.assertEqual(records.locator('.source-content-list article').count(), 12)
        records.get_by_role("button", name="下一页", exact=True).click()
        expect(records).to_contain_text("第 2 / 2 页")
        self.assertEqual(records.locator('.source-content-list article').count(), 3)
        notes = page.locator('.note-subject-profile')
        expect(notes).to_contain_text("14 份")
        notes.get_by_role("button", name="下一页", exact=True).click()
        expect(notes).to_contain_text("第 2 / 2 页")
        self.assertEqual(notes.locator('.note-subject-card').count(), 2)
        self.assertNotIn("合成不可读", page.locator('.source-page').inner_text())
        page.get_by_role("link", name="← 返回来源目录", exact=True).click()
        page.locator('[data-action="source-preview"][data-id="' + source + '"]').click()
        dialog = page.get_by_role("dialog", name="来源快速预览", exact=True)
        preview_records = dialog.locator('[data-source-content="published"]')
        expect(preview_records).to_contain_text("当前可阅读 15 份")
        preview_records.get_by_role("button", name="下一页", exact=True).click()
        expect(preview_records).to_contain_text("第 2 / 2 页")
        preview_notes = dialog.locator('.note-subject-profile')
        preview_notes.get_by_role("button", name="下一页", exact=True).click()
        expect(preview_notes).to_contain_text("第 2 / 2 页")
        self.assertEqual(page.get_by_role("heading", name="来源目录", exact=True).count(), 1)
        self.capture("source-preview-pagination")

    def test_04_person_maintenance_remains_reachable_and_works_chapter_survives_search(self):
        page = self.page
        page.goto(URL + "/#people?id=" + self.sample["person"])
        expect(page.get_by_role("heading", name="人物介绍", exact=True)).to_be_visible()
        page.get_by_text("历史与身份整理", exact=True).click()
        page.get_by_role("button", name="修改历史", exact=True).click()
        expect(page.get_by_role("dialog")).to_contain_text("恢复会形成新版本")
        page.keyboard.press("Escape")
        page.get_by_role("button", name="比较合并", exact=True).click()
        expect(page.get_by_role("dialog")).to_contain_text("合成人物乙")
        page.keyboard.press("Escape")
        page.get_by_role("navigation", name="人物章节", exact=True).get_by_role("button", name="已确认作品", exact=True).click()
        page.get_by_role("searchbox", name="搜索已确认作品", exact=True).fill("没有匹配")
        page.get_by_role("searchbox", name="搜索已确认作品", exact=True).press("Enter")
        expect(page.get_by_text("没有符合条件的已确认作品。", exact=True)).to_be_visible()
        page.get_by_role("navigation", name="人物章节", exact=True).get_by_role("button", name="已确认作品", exact=True).click()
        expect(page.get_by_role("heading", name="已确认作品", exact=True)).to_be_focused()

    def test_05_responsive_profiles_tables_and_maintenance(self):
        page = self.page
        for width in [1440, 1024, 390, 320]:
            page.set_viewport_size({"width": width, "height": 900})
            page.goto(URL + "/#sources")
            expect(page.get_by_role("heading", name="来源目录", exact=True)).to_be_visible()
            self.audit(f"sources-{width}")
            page.locator('[data-action="source-preview"][data-id="' + self.sample["source"] + '"]').first.click()
            dialog = page.get_by_role("dialog", name="来源快速预览", exact=True)
            expect(dialog.get_by_role("navigation", name="来源章节", exact=True)).to_be_visible()
            self.audit(f"source-detail-{width}")
            table = dialog.get_by_role("region", name="内容表格 1，可横向滚动", exact=True).first
            table.focus()
            page.keyboard.press("ArrowRight")
            self.assertGreater(table.evaluate("e=>e.scrollWidth"), table.evaluate("e=>e.clientWidth"))
            dialog.get_by_role("navigation", name="来源章节", exact=True).get_by_role("button", name="关系与作品", exact=True).click()
            expect(dialog.get_by_role("heading", name="关系与作品", exact=True)).to_be_focused()
            self.assertGreaterEqual(dialog.get_by_role("heading", name="关系与作品", exact=True).bounding_box()["y"], 60)
            self.audit(f"source-relations-{width}")
            dialog.get_by_role("button", name="编辑来源", exact=True).click()
            expect(page.get_by_role("dialog", name="修订公共来源", exact=True)).to_be_visible()
            self.audit(f"source-edit-{width}")
            page.keyboard.press("Escape")
            page.goto(URL + "/#people?q=合成人物")
            expect(page.get_by_role("heading", name="作者目录", exact=True)).to_be_visible()
            self.audit(f"people-{width}")
            page.get_by_role("link", name="合成人物｜亚历山大·跨语言与政策研究者", exact=True).click()
            expect(page.get_by_role("navigation", name="人物章节", exact=True)).to_be_visible()
            self.audit(f"person-{width}")
            page.get_by_role("button", name="编辑档案", exact=True).click()
            expect(page.get_by_role("dialog", name="编辑人物档案", exact=True)).to_be_visible()
            self.audit(f"person-edit-{width}")
            page.keyboard.press("Escape")
            page.get_by_text("历史与身份整理", exact=True).click()
            page.get_by_role("button", name="修改历史", exact=True).click()
            expect(page.get_by_role("dialog")).to_contain_text("恢复会形成新版本")
            self.audit(f"person-history-{width}")
            page.keyboard.press("Escape")
            page.get_by_role("button", name="比较合并", exact=True).click()
            expect(page.get_by_role("dialog")).to_contain_text("合成人物乙")
            self.audit(f"person-compare-picker-{width}")
            page.get_by_role("dialog").get_by_role("button", name="比较此人物", exact=True).click()
            expect(page.get_by_role("dialog")).to_contain_text("选择合并后当前显示的信息")
            self.audit(f"person-compare-{width}")
            page.keyboard.press("Escape")
        # CSS reflow equivalent, not native browser-toolbar zoom.
        page.set_viewport_size({"width": 720, "height": 450})
        page.goto(URL + "/#people?id=" + self.sample["person"])
        expect(page.get_by_role("navigation", name="人物章节", exact=True)).to_be_visible()
        self.audit("person-200-equivalent-reflow")

    def test_06_two_members_conflict_preserves_source_and_person_drafts(self):
        page = self.page
        colleague = self.playwright.request.new_context(base_url=URL)
        self.sign_in(colleague, "colleague")
        try:
            for kind, rid in [("sources", self.sample["source"]), ("people", self.sample["person"])]:
                if kind == "sources":
                    page.goto(URL + "/#sources?group=institution&id=" + rid)
                    page.get_by_role("button", name="编辑来源", exact=True).click()
                else:
                    page.goto(URL + "/#people?id=" + rid)
                    page.get_by_role("button", name="编辑档案", exact=True).click()
                form = page.locator('form[data-form="' + ("source" if kind == "sources" else "person") + '"]')
                draft_name = "合成编辑者输入仍保留｜" + kind
                form.locator('[name="name"]').fill(draft_name)
                if kind == "people":
                    form.locator('[name="change_note"]').fill("合成编辑维护依据")
                latest = colleague.get(URL + "/api/" + kind + "/" + rid).json()
                self.call(colleague, "PUT", "/api/" + kind + "/" + rid, {"version": latest["version"], "change_note": "另一成员合成修改", "research_scope": "另一成员的合成范围"} if kind == "sources" else {"version": latest["version"], "sources": "另一成员合成参考出处", "change_note": "另一成员合成修改"})
                form.get_by_role("button", name="保存修订" if kind == "sources" else "保存人物档案", exact=True).click()
                expect(form.locator('[data-conflict-panel]')).to_contain_text("输入")
                expect(form.locator('[name="name"]')).to_have_value(draft_name)
                page.set_viewport_size({"width": 320, "height": 900})
                self.audit("conflict-" + kind + "-320")
                page.get_by_role("button", name="关闭并保留草稿", exact=True).click()
                page.goto(URL + "/#drafts")
                expect(page.get_by_text(draft_name, exact=True)).to_be_visible()
                page.locator("article").filter(has=page.get_by_role("heading", name=draft_name, exact=True)).get_by_role("button", name="继续编辑", exact=True).click()
                page.get_by_role("button", name="恢复草稿", exact=True).click()
                resumed = page.locator('form[data-form="' + ("source" if kind == "sources" else "person") + '"]')
                expect(resumed.locator('[name="name"]')).to_have_value(draft_name)
                expect(resumed.locator('[data-conflict-panel]')).to_contain_text("输入")
                page.get_by_role("button", name="关闭并保留草稿", exact=True).click()
        finally:
            colleague.dispose()


if __name__ == "__main__":
    unittest.main(verbosity=2)
