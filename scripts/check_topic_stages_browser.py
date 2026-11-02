"""Full stage workflow at four widths and real Chrome 200% browser zoom."""
import hashlib
import json
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from playwright.sync_api import expect, sync_playwright
from platform_app.web import create_app
from scripts.check_topic_finals_browser import serve
from scripts.check_collaboration_browser import no_overflow
from scripts.verify_work_materials import verify


def main():
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    out = Path(tempfile.mkdtemp(prefix="database-topic-stages-browser-"))
    (Path(tempfile.gettempdir()) / "database-topic-stages-browser-latest.txt").write_text(str(out), encoding="utf-8")
    server, thread, base = serve(create_app(out / "data", testing=True))
    clients, events, results, errors = {}, [], [], []

    def account(name):
        session = requests.Session()
        csrf = session.get(base + "/api/session").json()["csrf"]
        assert session.post(base + "/api/login", json={"username": name, "password": "LocalDemo2026!"}, headers={"X-CSRF-Token": csrf}).status_code == 200
        clients[name] = session

    def get(path, who="researcher"):
        response = clients[who].get(base + path)
        assert response.status_code == 200, response.text
        return response.json()

    def call(path, data, who="researcher", method="POST", expected=201):
        session = clients[who]
        response = session.request(method, base + path, json=data, headers={"X-CSRF-Token": session.get(base + "/api/session").json()["csrf"]})
        events.append({"path": path, "who": who, "status": response.status_code})
        assert response.status_code == expected, (path, response.status_code, response.text)
        return response.json()

    def login(page, who, tid):
        page.goto(base)
        page.locator('[data-form="login"], [data-action="nav"][data-id="collaboration"]').first.wait_for(state='attached')
        if page.get_by_role("button", name="退出登录", exact=True).count():
            logout = page.get_by_role("button", name="退出登录", exact=True)
            if not logout.is_visible():
                page.get_by_role("button", name="打开导航", exact=True).click()
            logout.click()
            expect(page.get_by_label("账号", exact=True)).to_be_visible()
        page.goto(base)
        page.get_by_label("账号", exact=True).fill(who)
        page.get_by_label("密码", exact=True).fill("LocalDemo2026!")
        page.get_by_role("button", name="查看资料", exact=True).click()
        expect(page.locator('[data-action="nav"][data-id="collaboration"]')).to_be_attached()
        page.goto(base + "/#collaboration?id=" + tid)
        expect(page.locator("[data-collaboration-topic]")).to_be_visible()

    def file(locator, name, raw):
        locator.set_input_files({"name": name, "mimeType": "text/plain", "buffer": raw})

    def snapshot(page, name):
        no_overflow(page)
        page.screenshot(path=str(out / (name + ".png")), full_page=True)
        if name.endswith(('-lead-compilation', '-author-two-drafts')):
            page.evaluate('scrollTo(0,0)')
            page.screenshot(path=str(out / (name + '-default-viewport.png')), full_page=False)

    try:
        for name in ("admin", "researcher", "colleague"):
            account(name)
        call("/api/collaboration/qualifications/researcher", {"version": 0, "enabled": True}, "admin", "PUT", 200)
        uid = call("/api/members", {"username": "unassigned", "name": "合成未分工研究员", "password": "LocalDemo2026!", "role": "researcher"}, "admin")["id"]
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(out / "profile"), executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe", headless=False, args=["--headless=new"], viewport={"width": 1440, "height": 1000}, accept_downloads=True)
            page = context.pages[0]
            page.on("pageerror", lambda e: errors.append(str(e)))
            for width, zoom in ((1440, 1), (1366, 1), (390, 1), (320, 1), (1440, 2)):
                label = f"{width}-{int(zoom * 100)}"
                tid = call("/api/collaboration/topics", {"theme": "明确两阶段 " + label, "participant_ids": ["colleague", uid]})["id"]
                root = f"/api/collaboration/topics/{tid}"
                page.set_viewport_size({"width": width, "height": 1000})
                page.goto('chrome://settings/appearance')
                page.locator('#zoomLevel').select_option(str(zoom))
                actual = float(page.locator('#zoomLevel').input_value())
                page.screenshot(path=str(out / (label + '-chrome-zoom-setting.png')), full_page=True)
                assert actual == zoom
                login(page, "researcher", tid)
                expect(page.get_by_text("第一阶段：选题", exact=True)).to_be_visible()
                page.get_by_role("button", name="记录会议决定", exact=True).click()
                page.get_by_label("简短会议决定（可选）", exact=True).fill("只保存讨论，不确认分工")
                page.get_by_role("button", name="保存会议决定 v1", exact=True).click()
                expect(page.get_by_text("第一阶段：选题", exact=True)).to_be_visible()
                assert not page.locator("[data-topic-manuscripts]").count()
                snapshot(page, label + "-selection-note")
                page.get_by_role("button", name="修改会议决定", exact=True).click()
                page.get_by_label("简短会议决定（可选）", exact=True).fill("")
                file(page.get_by_label("会议材料文件（可选）", exact=True), "仅会议附件.txt", b"meeting attachment only")
                page.get_by_role("button", name="保存会议决定 v2", exact=True).click()
                expect(page.get_by_text("第一阶段：选题", exact=True)).to_be_visible()
                page.get_by_role("button", name="修改会议决定", exact=True).click()
                for index in (1, 2):
                    page.get_by_role("button", name="添加采用文章", exact=True).click()
                    row = page.locator("[data-assignment-row]").nth(index - 1)
                    row.get_by_label("题名或报告项目 *", exact=True).fill(f"文章{index}：" + "研究对象与出处核对" * 12)
                    row.get_by_label("编译研究员 *", exact=True).select_option("colleague")
                    row.get_by_label("出处或站外链接（可选）", exact=True).fill("https://example.invalid/" + str(index))
                snapshot(page, label + "-meeting-form")
                page.get_by_role("button", name="保存会议决定 v3", exact=True).click()
                expect(page.get_by_text("第一阶段：选题", exact=True)).to_be_visible()
                assert not page.locator("[data-topic-manuscripts]").count()
                page.get_by_role("button", name="确认分工，进入编译阶段", exact=True).click()
                expect(page.get_by_role("dialog").get_by_text("研究员 · 周 —", exact=False).first).to_be_visible()
                page.get_by_role("button", name="确认以上分工，进入编译", exact=True).focus()
                page.keyboard.press("Enter")
                expect(page.get_by_text("第二阶段：编译", exact=True)).to_be_visible()
                expect(page.locator('[data-topic-finals]')).to_have_count(0)
                expect(page.get_by_role('button', name='补充选题材料', exact=True)).to_be_visible()
                summary_title=page.locator('.meeting-assignment-title').first
                expect(summary_title).to_be_visible()
                metrics=summary_title.evaluate('(e)=>({height:e.getBoundingClientRect().height,lineHeight:parseFloat(getComputedStyle(e).lineHeight)})')
                assert metrics['height'] <= metrics['lineHeight']*3+1, metrics
                long_title=page.locator('.meeting-assignments li').first
                long_title.get_by_text('完整题名',exact=True).click()
                expect(long_title.get_by_text('文章1：'+'研究对象与出处核对'*12,exact=True)).to_be_visible()
                long_title.get_by_text('完整题名',exact=True).click()
                snapshot(page, label + "-lead-compilation")
                assert get(root)["stage_events"][0]["meeting_version"] == 3
                login(page, "colleague", tid)
                page.get_by_role("button", name="我的编译分工", exact=True).click()
                cards = page.locator('[data-assignment-card][data-mine="true"]')
                expect(cards).to_have_count(2)
                aids = [a["id"] for a in get(root + "/workflow")["assignments"]]
                long_name = "编译稿_" + "原件核对与跨人接续" * 12 + ".txt"
                for index, aid in enumerate(aids):
                    card = page.locator(f'[data-assignment-card="{aid}"]')
                    control = card.get_by_label("编译稿文件 *", exact=True)
                    control.focus()
                    page.keyboard.press("Shift+Tab")
                    expect(card.get_by_label("交稿说明（可选）", exact=True)).to_be_focused()
                    file(control, long_name, b"synthetic draft v1 " + str(index).encode())
                    card.get_by_role("button", name="提交编译稿 v1", exact=True).click()
                    expect(page.locator(f'[data-assignment-card="{aid}"]').get_by_text("待审", exact=True)).to_be_visible()
                snapshot(page, label + "-author-two-drafts")
                aid = aids[0]
                login(page, "researcher", tid)
                card = page.locator(f'[data-assignment-card="{aid}"]')
                card.get_by_text("退回修改 · 针对版本 1", exact=True).click()
                card.get_by_label("退回意见", exact=True).fill("请补充具体出处页码")
                card.get_by_role("button", name="退回版本 1", exact=True).click()
                expect(page.locator(f'[data-assignment-card="{aid}"]').get_by_text("返修", exact=True)).to_be_visible()
                login(page, "colleague", tid)
                card = page.locator(f'[data-assignment-card="{aid}"]')
                card.get_by_text("提交我的编译稿 · 新版本 2", exact=True).click()
                file(card.get_by_label("编译稿文件 *", exact=True), long_name, b"synthetic revised exact original v2")
                card.get_by_label("交稿说明（可选）", exact=True).fill("冲突仍保留：已补页码")
                rows = get(root + "/workflow")["meetings"][0]["assignments"]
                rows[0]["source"] += "?updated=1"
                call(root + "/meetings", {"request_id": "concurrent-meeting-" + label, "topic_version": 1, "version": 3, "note": "同作者更正出处", "assignments": rows})
                card.get_by_role("button", name="提交编译稿 v2", exact=True).click()
                expect(card.get_by_role("heading", name="请核对最新交接", exact=True)).to_be_visible()
                expect(card.get_by_label("交稿说明（可选）", exact=True)).to_have_value("冲突仍保留：已补页码")
                assert card.get_by_label("编译稿文件 *", exact=True).evaluate("e=>e.files[0].name") == long_name
                snapshot(page, label + "-conflict-preserved")
                card.get_by_role("button", name="已核对，保留输入继续交接", exact=True).click()
                expect(card.get_by_role("heading", name="请核对最新交接", exact=True)).to_be_hidden()
                card.get_by_role("button", name="提交编译稿 v2", exact=True).click()
                expect(page.locator(f'[data-assignment-card="{aid}"]').get_by_text("待审", exact=True)).to_be_visible()
                login(page, "researcher", tid)
                page.locator(f'[data-assignment-card="{aid}"]').get_by_role("button", name="确认当前稿件定稿", exact=True).click()
                page.get_by_role("button", name="确认稿件 v2 为定稿", exact=True).click()
                expect(page.locator(f'[data-assignment-card="{aid}"]').get_by_text("已定稿", exact=True)).to_be_visible()
                page.get_by_role("button", name="提交整期汇总", exact=True).click()
                file(page.get_by_label("整期汇总文件 *", exact=True), "汇总.txt", b"summary fixed adoption v2")
                page.get_by_role("dialog").locator('[name="final_ids"]').check()
                page.get_by_role("button", name="保存整期汇总 v1", exact=True).click()
                expect(page.get_by_role("heading", name="整期汇总 v1", exact=True)).to_be_visible()
                snapshot(page, label + "-lead-final-summary")
                login(page, "colleague", tid)
                card = page.locator(f'[data-assignment-card="{aid}"]')
                card.get_by_text("提交我的编译稿 · 新版本 3", exact=True).click()
                file(card.get_by_label("编译稿文件 *", exact=True), "新版v3.txt", b"new pending version v3")
                card.get_by_role("button", name="提交编译稿 v3", exact=True).click()
                expect(page.locator(f'[data-assignment-card="{aid}"]').get_by_text("待审", exact=True)).to_be_visible()
                w = get(root + "/workflow")
                assert w["summaries"][0]["adoptions"][0]["version"] == 2
                login(page, "unassigned", tid)
                expect(page.get_by_text("当前尚无文章分工，请联系负责人。", exact=True)).to_be_visible()
                assert not page.get_by_role("button", name="我的编译分工", exact=True).count()
                page.get_by_role("button", name="补充选题材料", exact=True).click()
                file(page.get_by_label("选题报告文件 *", exact=True), "补前期选题.txt", b"late selection material")
                page.get_by_role("button", name="提交为版本 1", exact=True).click()
                snapshot(page, label + "-unassigned-supplement")
                page.get_by_text("选题报告与历史", exact=True).click()
                with page.expect_download() as download:
                    page.get_by_role("link", name="下载原件 v1", exact=True).last.click()
                assert Path(download.value.path()).read_bytes() == b"late selection material"
                page.get_by_role("button", name="← 返回主题工作", exact=True).click()
                expect(page.locator("[data-work-discovery]")).to_be_visible()
                page.get_by_role("button", name="明确两阶段 " + label, exact=True).click()
                expect(page.get_by_text("第二阶段：编译", exact=True)).to_be_visible()
                layout = no_overflow(page)
                if zoom == 2:
                    assert layout["width"] < 800 and layout["dpr"] >= 2, layout
                for scope in ("all", "products", "process"):
                    package = clients["researcher"].get(base + f"/api/collaboration/materials/topic/{tid}?scope={scope}")
                    assert package.status_code == 200
                    package_path = out / f"{label}-{scope}.zip"
                    package_path.write_bytes(package.content)
                    verify(package_path)
                results.append({"width": width, "actual_zoom": actual, "layout": layout, "topic": tid, "note_attachment_assignment_keep_selection": True, "two_drafts_return_revise_finalize_summary_new_draft": True, "conflict_keeps_bytes_and_note": True, "unassigned_supplement_read_return": True, "materials_scopes_verified": 3})
            assert not errors, errors
            context.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        for session in clients.values():
            session.close()
        (out / "results.json").write_text(json.dumps({"base": base, "results": results, "events": events, "page_errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(out), "cases": len(results), "page_errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
