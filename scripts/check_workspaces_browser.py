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
        self.external_requests = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("request", lambda request: self.external_requests.append(request.url) if not request.url.startswith(URL) else None)

    def tearDown(self):
        self.assertEqual(self.external_requests, [])

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

    def navigate(self, title):
        toggle = self.page.get_by_role("button", name="打开导航", exact=True)
        if toggle.is_visible():
            toggle.click()
        self.page.get_by_title(title, exact=True).click()

    def create_draft(self):
        self.route("dashboard")
        self.page.get_by_role("button", name="新建内容", exact=True).click()
        expect(self.page.get_by_role("button", name="保存草稿", exact=True)).to_be_visible()
        self.page.get_by_label("题名 *", exact=True).fill("合成未提交草稿｜长题名与LongLatinDraftTitle")
        self.page.locator('[data-rich-field="body_html"] .rich-editor').fill("保留这段合成草稿正文与研究上下文。")
        self.page.get_by_role("button", name="关闭并保留草稿", exact=True).click()
        expect(self.page.get_by_role("heading", name="合成未提交草稿｜长题名与LongLatinDraftTitle", exact=True)).to_be_visible()

    def jump(self, label):
        control = self.page.get_by_role("navigation", name="专题章节", exact=True).get_by_text(label, exact=True)
        control.focus()
        control.press("Enter")

    def test_draft_resumes_from_dashboard_and_drafts_without_losing_text(self):
        self.create_draft()
        self.shot("dashboard-real-draft")
        self.page.get_by_role("button", name="继续草稿", exact=False).first.click()
        self.page.get_by_role("button", name="恢复草稿", exact=True).click()
        expect(self.page.get_by_label("题名 *", exact=True)).to_have_value("合成未提交草稿｜长题名与LongLatinDraftTitle")
        expect(self.page.locator('[data-rich-field="body_html"] .rich-editor')).to_contain_text("保留这段合成草稿正文")
        self.page.get_by_role("button", name="关闭并保留草稿", exact=True).click()
        self.navigate("我的草稿")
        expect(self.page.get_by_role("heading", name="我的草稿", exact=True)).to_be_visible()
        self.shot("drafts-real-content")
        self.page.get_by_role("button", name="继续编辑", exact=True).click()
        self.page.get_by_role("button", name="恢复草稿", exact=True).click()
        expect(self.page.get_by_label("题名 *", exact=True)).to_have_value("合成未提交草稿｜长题名与LongLatinDraftTitle")
        expect(self.page.locator('[data-rich-field="body_html"] .rich-editor')).to_contain_text("保留这段合成草稿正文")
        self.assertEqual(self.errors, [])

    def test_maintenance_roles_and_author_responsibility_remain_enforced(self):
        self.route("system")
        expect(self.page.get_by_role("heading", name="账号与成员", exact=True)).to_be_visible()
        expect(self.page.get_by_role("button", name="管理本机成员", exact=True)).to_have_count(0)
        expect(self.page.get_by_role("button", name="下载完整备份", exact=False)).to_have_count(0)
        expect(self.page.get_by_text("备份含所有账号的个人与受限资料", exact=False)).to_be_visible()
        with self.page.expect_download() as download:
            self.page.get_by_role("button", name="导出可见内容", exact=False).click()
        download.value.save_as(self.evidence / "member-readable-content.zip")
        self.shot("maintenance-member")
        self.route("library?q=代交合成成果")
        self.page.locator(f'[data-library-record="{self.pending}"] .record-title button').click()
        expect(self.page.get_by_role("heading", name="等待负责作者确认", exact=True)).to_be_visible()
        expect(self.page.get_by_role("button", name="编辑内容", exact=True)).to_have_count(0)
        self.shot("pending-author-responsibility")
        pending = self.context.request.get(URL + "/api/records/" + self.pending).json()
        call(self.context.request, "/api/records/" + self.pending, {"version": pending["version"], "body_html": "<p>未授权修改</p>"}, "PUT", 403)
        login(self.context.request, "admin")
        call(self.context.request, "/api/records/" + self.pending, {"version": pending["version"], "body_html": "<p>管理员也未获作者授权</p>"}, "PUT", 403)
        self.route("system")
        expect(self.page.get_by_role("button", name="管理本机成员", exact=True)).to_be_visible()
        expect(self.page.get_by_role("button", name="下载完整备份", exact=False)).to_be_visible()
        self.shot("maintenance-admin")
        self.page.get_by_role("button", name="管理本机成员", exact=True).click()
        expect(self.page.get_by_role("dialog", name="本机成员管理", exact=True)).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_topic_conflict_keeps_local_input_and_draft(self):
        self.open_topic()
        self.page.get_by_role("button", name="编辑研究内容", exact=False).click()
        self.page.get_by_label("研究问题", exact=True).fill("我的合成问题仍须保留，不由远端新版本覆盖。")
        other = self.pw.request.new_context()
        try:
            login(other, "colleague")
            current = other.get(URL + "/api/collections/" + self.topic).json()
            call(other, "/api/collections/" + self.topic, {"version": current["version"], "stage_judgment": "另一成员的合成新版本"}, "PUT")
        finally:
            other.dispose()
        self.page.get_by_role("button", name="保存专题", exact=True).click()
        expect(self.page.get_by_role("heading", name="专题已有新版本，当前草稿已保留", exact=True)).to_be_visible()
        expect(self.page.get_by_label("研究问题", exact=True)).to_have_value("我的合成问题仍须保留，不由远端新版本覆盖。")
        self.shot("topic-conflict-keeps-input")
        self.page.get_by_role("button", name="关闭并保留草稿", exact=True).click()
        self.navigate("我的草稿")
        expect(self.page.get_by_role("heading", name=self.topic_name, exact=True)).to_be_visible()
        self.page.get_by_role("button", name="继续编辑", exact=True).click()
        self.page.get_by_role("button", name="恢复草稿", exact=True).click()
        expect(self.page.get_by_role("heading", name="专题已有新版本，当前草稿已保留", exact=True)).to_be_visible()
        expect(self.page.get_by_label("研究问题", exact=True)).to_have_value("我的合成问题仍须保留，不由远端新版本覆盖。")
        self.assertEqual(self.errors, [])

    def test_topic_membership_and_history_preserve_the_original_material(self):
        extra = call(self.context.request, "/api/records", {"kind": "report", "title": "合成待加入资料", "body_html": "<p>原始资料内容。</p>"}, status=201)["id"]
        self.open_topic()
        self.jump("资料与证据")
        self.page.get_by_label("查找资料 / 笔记", exact=True).fill("合成待加入资料")
        self.page.get_by_role("button", name="查找并添加", exact=True).click()
        self.page.locator(f'[data-action="topic-add"][data-id="{extra}"]').click()
        current = self.context.request.get(URL + "/api/collections/" + self.topic).json()
        self.assertIn(extra, [r["id"] for r in current["items"]])
        self.jump("资料与证据")
        self.page.locator(".topic-record").filter(has_text="合成待加入资料").get_by_role("button", name="移出专题", exact=True).click()
        current = self.context.request.get(URL + "/api/collections/" + self.topic).json()
        self.assertNotIn(extra, [r["id"] for r in current["items"]])
        self.assertEqual(self.context.request.get(URL + "/api/records/" + extra).status, 200)
        self.page.get_by_text("历史与导出", exact=True).click()
        self.page.get_by_role("button", name="修改历史", exact=False).click()
        expect(self.page.get_by_role("heading", name="专题修改历史", exact=True)).to_be_visible()
        self.shot("topic-history")
        self.page.locator(".history-row").nth(1).get_by_role("button", name="恢复此版本", exact=True).click()
        current = self.context.request.get(URL + "/api/collections/" + self.topic).json()
        self.assertIn(extra, [r["id"] for r in current["items"]])
        self.assertEqual(current["visibility"], "shared")
        self.assertEqual(self.context.request.get(URL + "/api/records/" + extra).status, 200)
        self.assertEqual(self.errors, [])

    def test_z_visual_workspace_evidence(self):
        # Visual evidence observes rendered pages; no assertions mirror CSS implementation.
        self.create_draft()
        results = []
        metrics = r"""() => {
          const shown=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
          const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number);
          const lum=c=>c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);
          const background=e=>{const colors=[];for(let p=e;p;p=p.parentElement)colors.unshift(rgb(getComputedStyle(p).backgroundColor));return colors.reduce((base,c)=>{const a=c.length>3?c[3]:1;return base.map((v,i)=>c[i]*a+v*(1-a));},[255,255,255]);};
          const text=[],lowContrast=[],ratios=[],walker=document.createTreeWalker(document.querySelector('.drawer')||document.querySelector('#content'),NodeFilter.SHOW_TEXT);
          let node;
          while(node=walker.nextNode()){
            const e=node.parentElement,r=e.getBoundingClientRect(),s=getComputedStyle(e);
            if(!node.textContent.trim()||!shown(e)||r.top>innerHeight||r.bottom<0)continue;
            if(parseFloat(s.fontSize)<14)text.push({text:node.textContent.trim().slice(0,70),size:s.fontSize});
            const a=lum(rgb(s.color)),b=lum(background(e)),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
            ratios.push(ratio);
            const large=parseFloat(s.fontSize)>=24||(parseFloat(s.fontSize)>=18.66&&parseInt(s.fontWeight)>=700);
            if(ratio<(large?3:4.5))lowContrast.push({text:node.textContent.trim().slice(0,70),ratio,color:s.color,size:s.fontSize});
          }
          const drawer=document.querySelector('.drawer');
          let hit=null;if(drawer){const e=drawer.querySelector('[data-action=close]'),r=e.getBoundingClientRect();hit=e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}
          return {width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,
            overflow:document.documentElement.scrollWidth>innerWidth+1,under14:text,lowContrast,minContrast:Math.min(...ratios),closeReceivesPointer:hit,
            localTables:[...document.querySelectorAll('.reading-table')].filter(shown).map(e=>({clientWidth:e.clientWidth,scrollWidth:e.scrollWidth}))};
        }"""
        for width,height,label in [(1440,1000,'1440'),(1024,900,'1024'),(390,844,'390'),(320,780,'320'),(720,500,'200pct-reflow-720')]:
            self.page.set_viewport_size({'width':width,'height':height})
            for route in ['dashboard','collections','drafts','system']:
                self.route(route)
                self.shot(label+'-'+route)
                result=self.page.evaluate(metrics);result.update(page=route,viewport=label)
                results.append(result)
                self.assertFalse(result['overflow'], f'{label} {route} overflows')
            self.open_topic();self.shot(label+'-topic')
            result=self.page.evaluate(metrics);result.update(page='topic',viewport=label);results.append(result)
            self.assertFalse(result['overflow'])
            self.assertTrue(result['closeReceivesPointer'])
            self.jump('资料与证据')
            expect(self.page.get_by_role('heading',name='资料与证据',exact=True)).to_be_in_viewport()
            self.jump('研究内容')
            self.page.locator('.workspace-topic .reading-table').scroll_into_view_if_needed()
            self.shot(label+'-topic-table')
            result=self.page.evaluate(metrics);result.update(page='topic-table',viewport=label);results.append(result)
            self.assertFalse(result['overflow'])
            self.page.get_by_role('button',name='关闭',exact=True).click()
        (self.evidence/'visual-metrics.json').write_text(json.dumps({'items':results,'pageErrors':self.errors,
            'externalRequests':self.external_requests,
            'zoomLimitation':'720x500 CSS viewport is reflow equivalence only; not actual browser 200% zoom.'},ensure_ascii=False,indent=2),encoding='utf-8')
        self.assertEqual(self.errors, [])

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
