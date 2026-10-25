"""#20: real browser checks using a synthetic library on an owned local port.

DATABASE_LAYOUT_EVIDENCE preserves the same sample across before/after runs.
Run with --baseline to retain before screenshots without running assertions.
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
PORT = int(os.environ.get("DATABASE_BROWSER_PORT", "8871"))
URL = f"http://127.0.0.1:{PORT}"
BASELINE = "--baseline" in sys.argv
if BASELINE:
    sys.argv.remove("--baseline")


class LayoutBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = Path(os.environ.get("DATABASE_LAYOUT_EVIDENCE") or tempfile.mkdtemp(prefix="database-ui-shell-"))
        cls.evidence.mkdir(parents=True, exist_ok=True)
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", PORT)) == 0:
                raise RuntimeError(f"{PORT} occupied; refusing to reuse an unknown service")
        cls.output = (cls.evidence / "server.log").open("a", encoding="utf-8")
        cls.server = subprocess.Popen([sys.executable, str(ROOT / "app.py"), "--no-import", "--port", str(PORT), "--data-dir", str(cls.evidence / "data")], cwd=ROOT, stdout=cls.output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
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
        cls.browser = cls.playwright.chromium.launch(channel=os.environ.get("DATABASE_BROWSER_CHANNEL") or None)
        request = cls.playwright.request.new_context(base_url=URL)
        token = request.get("/api/session").json()["csrf"]
        response = request.post("/api/login", data={"username": "researcher", "password": "LocalDemo2026!"}, headers={"X-CSRF-Token": token})
        token = response.json()["csrf"]
        def post(path, data):
            response = request.post(path, data=data, headers={"X-CSRF-Token": token})
            assert response.ok, response.text()
            return response.json()
        sample = cls.evidence / "sample.json"
        if sample.exists():
            cls.sample = json.loads(sample.read_text(encoding="utf-8"))
        else:
            source = post("/api/sources", {"name": "合成研究中心 · 语言与社会", "kind": "institution", "country": "拉脱维亚", "institution_types": ["research_institute"], "original_name": "Synthetic Centre for Language and Society", "introduction_html": "<p>用于布局验收的合成机构介绍。</p>", "country_evidence": "合成官网 https://example.org/centre", "website": "https://example.org/centre"})
            person = post("/api/people", {"name": "合成人物 · 研究者甲", "original_name": "Synthetic Researcher", "change_note": "合成身份依据", "introduction_html": "<p>合成简介，供人物页面排版验收。</p>"})
            ids = []
            for number in range(15):
                record = post("/api/records", {"title": f"布局验收资料 {number:02d}：语言政策、研究出处与可持续资料积累" + ("长标题及原名验证" * 4 if number == 14 else ""), "kind": "report", "authors": "合成作者甲；Synthetic Author", "published_on": f"2026-10-{number+1:02d}", "language": "zh", "source_id": source["id"], "countries": "拉脱维亚", "abstract": "合成摘要：资料用于测试排版、连续阅读及检索，不包含研究材料。", "url": "https://example.org/" + "long-path-" * 25, "body_html": "<p>合成正文首段：成员从题名进入资料并继续阅读。</p>" + "<p>带出处的研究阅读内容。清楚区分资料与研究员解释。</p>" * 8 + "<table><tr>" + "<th>长表格的合成标题</th>" * 8 + "</tr><tr>" + "<td>可核查的合成数据</td>" * 8 + "</tr></table>"})
                ids.append(record["id"])
            cls.sample = {"source": source["id"], "person": person["id"], "records": ids}
            sample.write_text(json.dumps(cls.sample), encoding="utf-8")
        request.dispose()
        print("Layout evidence:", cls.evidence, flush=True)

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
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.set_default_timeout(5000)
        self.page.goto(URL)
        self.page.get_by_role("button", name="研究员", exact=True).click()
        expect(self.page.get_by_role("heading", name="查找研究资料", exact=True)).to_be_visible()

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def navigate(self, title):
        toggle = self.page.get_by_role("button", name="打开导航", exact=True)
        if toggle.is_visible():
            toggle.click()
        self.page.get_by_title(title, exact=True).click()
        if title != "工作台":
            expect(self.page.get_by_role("heading", name=title, exact=True)).to_be_visible()

    def test_menu_supports_keyboard_escape_navigation_and_resize(self):
        page = self.page
        if BASELINE:
            for title, file in [("工作台", "dashboard"), ("资料库", "library"), ("来源目录", "sources"), ("作者目录", "people")]:
                page.get_by_title(title, exact=True).click()
                page.wait_for_load_state("networkidle")
                page.screenshot(path=str(self.evidence / ("before-" + file + ".png")), full_page=True)
            page.goto(URL + "#people?id=" + self.sample["person"])
            expect(page.locator(".person-page")).to_be_visible()
            page.screenshot(path=str(self.evidence / "before-person.png"), full_page=True)
            page.goto(URL + "#sources")
            page.locator('[data-action="source-detail"]').first.click()
            expect(page.get_by_role("dialog")).to_be_visible()
            page.screenshot(path=str(self.evidence / "before-source-detail.png"))
            page.get_by_role("button", name="关闭", exact=True).click()
            page.goto(URL + "#library")
            page.locator(".record-title button").first.click()
            expect(page.get_by_role("region", name="连续阅读")).to_be_visible()
            page.screenshot(path=str(self.evidence / "before-reading.png"))
            page.get_by_role("button", name="返回列表", exact=True).click()
            page.get_by_role("button", name="提交资料", exact=True).click()
            page.screenshot(path=str(self.evidence / "before-editor.png"))
            page.get_by_role("button", name="关闭并保留草稿", exact=True).click()
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(self.evidence / "before-library-390.png"))
            return
        page.set_viewport_size({"width": 390, "height": 844})
        toggle = page.get_by_role("button", name="打开导航", exact=True)
        expect(toggle).to_be_visible()
        expect(page.get_by_title("资料库", exact=True)).not_to_be_visible()
        toggle.focus()
        page.keyboard.press("Enter")
        menu = page.get_by_role("dialog", name="平台导航")
        expect(menu).to_be_visible()
        expect(menu.get_by_role("button", name="工作台", exact=True)).to_have_attribute("aria-current", "page")
        page.keyboard.press("Shift+Tab")
        expect(menu.get_by_role("button", name="关闭导航", exact=True)).to_be_focused()
        page.keyboard.press("Shift+Tab")
        expect(menu.get_by_title("数据与维护", exact=True)).to_be_focused()
        page.keyboard.press("Tab")
        expect(menu.get_by_role("button", name="关闭导航", exact=True)).to_be_focused()
        page.keyboard.press("Escape")
        expect(menu).not_to_be_visible()
        expect(toggle).to_be_focused()
        toggle.click()
        menu.get_by_title("资料库", exact=True).click()
        expect(page.get_by_role("heading", name="资料库", exact=True)).to_be_focused()
        expect(page.get_by_role("dialog", name="平台导航")).not_to_be_visible()
        page.get_by_role("button", name="打开导航", exact=True).click()
        page.set_viewport_size({"width": 1366, "height": 900})
        expect(page.get_by_role("dialog", name="平台导航")).to_have_count(0)
        expect(page.get_by_title("资料库", exact=True)).to_be_visible()
        self.assertEqual(page.evaluate("document.body.style.overflow"), "")

    def test_filters_are_optional_keep_visible_conditions_and_fixed_ranges(self):
        if BASELINE:
            return
        page = self.page
        self.navigate("资料库")
        expect(page.get_by_label("资料类型", exact=True)).not_to_be_visible()
        expect(page.get_by_role("button", name="收藏选中", exact=True)).not_to_be_visible()
        page.get_by_text("筛选条件", exact=True).click()
        page.get_by_label("资料语言", exact=True).select_option("zh")
        page.get_by_role("button", name="应用筛选", exact=True).click()
        expect(page.get_by_label("资料类型", exact=True)).not_to_be_visible()
        expect(page.get_by_role("button", name="清除语言：中文", exact=True)).to_be_visible()
        page.locator('[data-library-select]').first.check()
        expect(page.get_by_role("button", name="收藏选中", exact=True)).to_be_visible()
        page.get_by_role("button", name="清空选择", exact=True).click()
        expect(page.get_by_role("button", name="收藏选中", exact=True)).not_to_be_visible()
        page.get_by_role("button", name="清除语言：中文", exact=True).click()
        expect(page.locator(".record-list .record-title")).to_have_count(12)
        self.navigate("编译成果")
        page.get_by_text("筛选条件", exact=True).click()
        expect(page.get_by_label("资料类型", exact=True)).to_have_value("compilation")
        expect(page.get_by_label("资料类型", exact=True)).to_be_disabled()
        page.get_by_role("button", name="重置", exact=True).click()
        expect(page.get_by_role("heading", name="编译成果", exact=True)).to_be_visible()
        page.get_by_text("筛选条件", exact=True).click()
        expect(page.get_by_label("资料类型", exact=True)).to_have_value("compilation")

    def test_review_scope_and_keyboard_filtering_survive_reset(self):
        if BASELINE:
            return
        page = self.page
        page.get_by_role("button", name="退出登录", exact=True).click()
        page.get_by_role("button", name="资料管理员", exact=True).click()
        self.navigate("待核对")
        summary = page.get_by_text("筛选条件", exact=True)
        summary.focus()
        page.keyboard.press("Enter")
        expect(page.get_by_label("核对状态", exact=True)).to_have_value("pending")
        expect(page.get_by_label("核对状态", exact=True)).to_be_disabled()
        page.get_by_role("button", name="重置", exact=True).click()
        expect(page.get_by_role("heading", name="待核对", exact=True)).to_be_visible()
        expect(page.get_by_text("“已核对”表示基本信息已检查，不代表认可研究结论。", exact=True)).to_be_visible()
        page.get_by_text("筛选条件", exact=True).click()
        expect(page.get_by_label("核对状态", exact=True)).to_have_value("pending")

    def test_shared_windows_and_reflow_keep_text_and_controls_accessible(self):
        if BASELINE:
            return
        page = self.page
        findings = []
        # Runtime observations, not snapshots of CSS implementation details.
        def audit(label):
            result = page.evaluate("""() => {
              const fonts=[],contrast=[];
              const rgb=s=>[...s.matchAll(/[\\d.]+/g)].map(x=>+x[0]);
              const lum=c=>c.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
              for(const el of document.querySelectorAll('body *')){
                if(!el.checkVisibility()||['SCRIPT','STYLE','SVG','PATH'].includes(el.tagName))continue;
                const text=[...el.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim();
                if(!text)continue;
                const style=getComputedStyle(el),size=parseFloat(style.fontSize);
                if(size<14)fonts.push({text:text.slice(0,60),size});
                let bg=el;
                while(bg&&rgb(getComputedStyle(bg).backgroundColor)[3]===0)bg=bg.parentElement;
                const front=rgb(style.color),back=bg?rgb(getComputedStyle(bg).backgroundColor):[255,255,255];
                const a=lum(front),b=lum(back),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
                if(ratio<4.5)contrast.push({text:text.slice(0,60),ratio,color:style.color,background:back});
              }
              return {fonts,contrast,width:document.documentElement.scrollWidth,viewport:innerWidth};
            }""")
            findings.append({"page": label, **result})
            if result["width"] > result["viewport"]:
                page.screenshot(path=str(self.evidence / f"overflow-{label}.png"),full_page=True)
                print("Viewport:",page.evaluate("""() => ({x:scrollX,width:innerWidth,overlay:document.querySelector('.overlay')?.getBoundingClientRect().toJSON(),drawer:document.querySelector('.drawer')?.getBoundingClientRect().toJSON()})"""),flush=True)
                print("Overflow:",label,page.evaluate("""() => [...document.querySelectorAll('body *')].filter(e=>e.checkVisibility()&&e.getBoundingClientRect().right>innerWidth+1).slice(0,40).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width,text:e.textContent.slice(0,50)}))"""),flush=True)
            self.assertEqual(result["fonts"], [], label)
            self.assertEqual(result["contrast"], [], label)
            self.assertLessEqual(result["width"], result["viewport"], label)

        for width in [1366, 390, 320]:
            page.set_viewport_size({"width": width, "height": 900 if width == 1366 else 844})
            for title, name in [("工作台","dashboard"),("资料库","library"),("来源目录","sources"),("作者目录","people"),("编译成果","compilations"),("专题资料夹","collections"),("我的收藏","favorites"),("我的草稿","drafts"),("数据与维护","system")]:
                self.navigate(title)
                if title == "工作台":
                    expect(page.get_by_role("heading", name="查找研究资料", exact=True)).to_be_visible()
                audit(f"{name}-{width}")
                page.screenshot(path=str(self.evidence / f"after-{name}-{width}.png"), full_page=True)
            self.navigate("资料库")
            page.get_by_text("筛选条件", exact=True).click()
            audit(f"filters-{width}")
            page.screenshot(path=str(self.evidence / f"after-filters-{width}.png"))
            page.get_by_text("筛选条件", exact=True).click()
            page.get_by_role("button", name="提交资料", exact=True).click()
            expect(page.get_by_label("题名 *", exact=True)).to_be_visible()
            audit(f"editor-{width}")
            page.screenshot(path=str(self.evidence / f"after-editor-{width}.png"))
            page.get_by_role("button", name="关闭并保留草稿", exact=True).click()
            page.goto(URL + "#people?id=" + self.sample["person"])
            expect(page.locator(".person-page")).to_be_visible()
            audit(f"person-{width}")
            page.screenshot(path=str(self.evidence / f"after-person-{width}.png"),full_page=True)
            page.goto(URL + "#sources")
            page.locator('[data-action="source-detail"]').first.click()
            expect(page.get_by_role("dialog")).to_be_visible()
            audit(f"source-detail-{width}")
            page.screenshot(path=str(self.evidence / f"after-source-detail-{width}.png"))
            page.get_by_role("button",name="关闭",exact=True).click()
            self.navigate("资料库")
            page.locator(".record-title button").first.click()
            reader=page.get_by_role("region" if width>=1200 else "dialog",name="连续阅读")
            reader.locator(".ux-maintenance summary").click()
            reader.get_by_role("button",name="修改历史",exact=True).click()
            expect(page.get_by_role("heading",name="修改历史",exact=True)).to_be_visible()
            page.get_by_role("button",name="查看内容",exact=True).first.click()
            audit(f"history-{width}")
            page.screenshot(path=str(self.evidence / f"after-history-{width}.png"))
            page.get_by_role("button",name="关闭",exact=True).click()
            reader.get_by_role("button",name="返回列表",exact=True).click()
            page.get_by_text("整理与导出",exact=True).click()
            page.get_by_role("button",name="整理重复",exact=True).click()
            page.get_by_label("保留的主记录",exact=True).select_option(self.sample["records"][14])
            page.get_by_label("待合并记录",exact=True).select_option(self.sample["records"][13])
            page.get_by_role("button",name="比较与查看影响",exact=True).click()
            expect(page.get_by_role("heading",name="合并前比较",exact=True)).to_be_visible()
            audit(f"comparison-{width}")
            page.screenshot(path=str(self.evidence / f"after-comparison-{width}.png"))
            page.get_by_role("button",name="关闭",exact=True).click()
        # Equivalent reflow viewport for a 1440x900 display enlarged to 200%.
        # Native browser chrome zoom is unavailable in headless Edge.
        zoom = self.browser.new_context(viewport={"width":720,"height":450},device_scale_factor=2)
        zpage = zoom.new_page()
        zpage.goto(URL)
        zpage.get_by_role("button", name="研究员", exact=True).click()
        zpage.get_by_role("button", name="打开导航", exact=True).click()
        zpage.get_by_title("资料库", exact=True).click()
        expect(zpage.locator(".record-title button").first).to_be_visible()
        self.assertLess(zpage.locator(".record-title button").first.bounding_box()["y"],450)
        zpage.screenshot(path=str(self.evidence / "after-reflow-200-percent.png"))
        zpage.locator(".record-title button").first.click()
        expect(zpage.get_by_role("dialog",name="连续阅读")).to_be_visible()
        zpage.get_by_role("button",name="返回列表",exact=True).click()
        zoom.close()
        (self.evidence / "text-audit.json").write_text(json.dumps(findings,ensure_ascii=False,indent=2),encoding="utf-8")

    def test_reading_matches_available_space_and_returns_to_query(self):
        if BASELINE:
            return
        page = self.page
        self.navigate("资料库")
        for width in [1440, 1366, 1024, 901, 768, 503, 390, 320]:
            page.set_viewport_size({"width": width, "height": 900 if width > 768 else 844})
            origin = page.locator(".record-list .record-title button").first
            expect(origin).to_be_visible()
            origin.click()
            reader = page.get_by_role("region" if width >= 1200 else "dialog", name="连续阅读")
            expect(reader).to_be_visible()
            expect(reader.locator("#ux-body")).to_be_visible()
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            self.assertGreater(reader.bounding_box()["width"], 600 if width >= 1200 else width - 2)
            reader.get_by_role("button", name="下一条", exact=True).click()
            expect(reader.get_by_text("本页第 2 / 12 条", exact=True)).to_be_visible()
            if width == 1366:
                # Cross both shell and reader breakpoints while reading.
                for resized in [1024, 901, 1440]:
                    page.set_viewport_size({"width":resized,"height":900})
                    current=page.get_by_role("region" if resized>=1200 else "dialog",name="连续阅读")
                    expect(current).to_be_visible()
                    if resized<1200:
                        expect(page.get_by_role("navigation",name="主导航")).to_have_count(0)
                        current.get_by_role("button",name="返回列表",exact=True).focus()
                        page.keyboard.press("Shift+Tab")
                        self.assertTrue(current.locator(":focus").count())
                page.set_viewport_size({"width":width,"height":900})
            page.screenshot(path=str(self.evidence / f"after-reader-{width}.png"))
            if width < 1200:
                reader.get_by_role("button", name="返回列表", exact=True).click()
            else:
                page.keyboard.press("Escape")
            expect(reader).not_to_be_visible()
            expect(origin).to_be_focused()
            page.screenshot(path=str(self.evidence / f"after-list-{width}.png"))
            if width in [503, 390, 320]:
                self.assertLess(origin.bounding_box()["y"], 700)


if __name__ == "__main__":
    unittest.main(verbosity=2)
