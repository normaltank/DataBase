"""Actual Chrome end/reopen, stale forms and read access in both topic phases."""
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
    out = Path(tempfile.mkdtemp(prefix="database-topic-closure-browser-"))
    (Path(tempfile.gettempdir()) / "database-topic-closure-browser-latest.txt").write_text(str(out), encoding="utf-8")
    server, thread, base = serve(create_app(out / "data", testing=True))
    clients, results, events, errors = {}, [], [], []

    def account(name):
        s = requests.Session()
        token = s.get(base + "/api/session").json()["csrf"]
        assert s.post(base + "/api/login", json={"username": name, "password": "LocalDemo2026!"}, headers={"X-CSRF-Token": token}).status_code == 200
        clients[name] = s

    def get(path, who="researcher"):
        r = clients[who].get(base + path)
        assert r.status_code == 200, r.text
        return r.json()

    def call(path, data, who="researcher", raw=None, method="POST", expected=201):
        s = clients[who]
        options = {"headers": {"X-CSRF-Token": s.get(base + "/api/session").json()["csrf"]}}
        options.update({"json": data} if raw is None else {"data": {"data": json.dumps(data)}, "files": {"file": ("synthetic.txt", raw, "text/plain")}})
        r = s.request(method, base + path, **options)
        events.append({"path": path, "who": who, "status": r.status_code})
        assert r.status_code == expected, (path, r.status_code, r.text)
        return r.json()

    def login(page, who, tid):
        page.goto(base)
        page.locator('[data-form="login"], [data-action="nav"][data-id="collaboration"]').first.wait_for(state="attached")
        logout = page.get_by_role("button", name="退出登录", exact=True)
        if logout.count():
            if not logout.is_visible():
                page.get_by_role("button", name="打开导航", exact=True).click()
            logout.click()
            expect(page.get_by_label("账号", exact=True)).to_be_visible()
        page.get_by_label("账号", exact=True).fill(who)
        page.get_by_label("密码", exact=True).fill("LocalDemo2026!")
        page.get_by_role("button", name="查看资料", exact=True).click()
        expect(page.locator('[data-action="nav"][data-id="collaboration"]')).to_be_attached()
        page.goto(base + "/#collaboration?id=" + tid)
        expect(page.locator("[data-collaboration-topic]")).to_be_visible()

    def snap(page, name):
        layout = no_overflow(page)
        page.screenshot(path=str(out / (name + ".png")), full_page=True)
        (out / (name + ".txt")).write_text(page.locator("body").inner_text(), encoding="utf-8")
        if name.endswith(("-confirmation", "-lead-closed", "-researcher-readonly")):
            page.evaluate("scrollTo(0,0)")
            page.screenshot(path=str(out / (name + "-default-viewport.png")), full_page=False)
        return layout

    def upload(locator, name, raw):
        locator.set_input_files({"name": name, "mimeType": "text/plain", "buffer": raw})

    def api_end(root, key):
        p = get(root + "/closure-preview")
        return call(root + "/end", {"request_id": key, "lifecycle_version": p["lifecycle_version"], "basis_token": p["basis_token"], "confirm": True})

    def api_reopen(root, key):
        return call(root + "/reopen", {"request_id": key, "lifecycle_version": get(root)["lifecycle_version"]})

    def seed(phase, label):
        tid = call("/api/collaboration/topics", {"theme": "结束与重开 " + phase + " " + label, "participant_ids": ["colleague"]})["id"]
        root = "/api/collaboration/topics/" + tid
        call(root + "/candidates", {"request_id": "seed-candidate", "version": 0, "topic_version": 1}, "colleague", b"original selection material")
        rows = [{"title": ("长题名跨人交接与真实出处核对" * 7) + str(i), "author_id": "colleague", "source": "https://example.invalid/" + str(i)} for i in range(3 if phase == "compilation" else 1)]
        call(root + "/meetings", {"request_id": "seed-meeting", "version": 0, "topic_version": 1, "assignments": rows})
        if phase == "selection":
            return tid, root, None
        call(root + "/enter-compilation", {"request_id": "seed-stage-enter", "stage_version": 1, "topic_version": 1, "meeting_version": 1})
        a1, a2, _ = get(root + "/workflow")["assignments"]
        def draft(aid, version, key):
            return call(root + f"/assignments/{aid}/submissions", {"request_id": key, "version": version, "topic_version": 1, "meeting_version": 1}, "colleague", ("synthetic draft v" + str(version + 1)).encode())["id"]
        first = draft(a1["id"], 0, "seed-first-draft")
        call(root + f"/assignments/{a1['id']}/returns", {"request_id": "seed-first-return", "submission_id": first, "topic_version": 1, "meeting_version": 1, "note": "补出处"})
        second = draft(a1["id"], 1, "seed-second-draft")
        final = call(root + f"/assignments/{a1['id']}/finals", {"request_id": "seed-second-final", "submission_id": second, "version": 2, "status": "pending", "topic_version": 1, "meeting_version": 1})["id"]
        call(root + "/summaries", {"request_id": "seed-summary", "version": 0, "topic_version": 1, "author_id": "researcher", "final_ids": [final]}, raw=b"summary adopts exact draft v2")
        draft(a1["id"], 2, "seed-third-draft")
        returned = draft(a2["id"], 0, "seed-other-draft")
        call(root + f"/assignments/{a2['id']}/returns", {"request_id": "seed-other-return", "submission_id": returned, "topic_version": 1, "meeting_version": 1, "note": "退回修改"})
        return tid, root, a1["id"]

    try:
        for name in ("admin", "researcher", "colleague"):
            account(name)
        call("/api/collaboration/qualifications/researcher", {"version": 0, "enabled": True}, "admin", method="PUT", expected=200)
        call("/api/members/colleague", {"name": "研究员 · 周（合成长姓名与跨人交接核对）"}, "admin", method="PUT", expected=200)
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(out / "profile"), executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe", headless=False, args=["--headless=new"], viewport={"width": 1440, "height": 1000}, accept_downloads=True)
            page = context.pages[0]
            page.on("pageerror", lambda error: errors.append(str(error)))
            for width, zoom in ((1440, 1), (1366, 1), (390, 1), (320, 1), (1440, 2)):
                page.set_viewport_size({"width": width, "height": 1000})
                page.goto("chrome://settings/appearance")
                page.locator("#zoomLevel").select_option(str(zoom))
                actual_zoom = float(page.locator("#zoomLevel").input_value())
                assert actual_zoom == zoom
                page.screenshot(path=str(out / f"{width}-{zoom}-chrome-setting.png"))
                for phase in ("selection", "compilation"):
                    label = f"{width}-{int(zoom*100)}-{phase}"
                    tid, root, aid = seed(phase, label)
                    login(page, "researcher", tid)
                    page.get_by_role("button", name="结束本期", exact=True).click()
                    dialog = page.get_by_role("dialog")
                    expect(dialog.get_by_text("待交稿 · 缺当前定稿", exact=True)).to_be_visible()
                    if phase == "compilation":
                        expect(dialog.get_by_text("待审 · 当前稿 v3 · 缺当前定稿", exact=True)).to_be_visible()
                        expect(dialog.get_by_text("返修 · 当前稿 v1 · 缺当前定稿", exact=True)).to_be_visible()
                        # New handoff commits after the preview, so the old end cannot succeed.
                        call(root + f"/assignments/{aid}/submissions", {"request_id": "concurrent-draft-v4", "version": 3, "topic_version": 1, "meeting_version": 1}, "colleague", b"new handoff after end preview")
                        dialog.get_by_role("button", name="确认结束本期", exact=True).click()
                        expect(dialog.get_by_text("本期交稿、审稿或分工已变化", exact=False)).to_be_visible()
                        assert get(root)["lifecycle_state"] == "open"
                        dialog.get_by_role("button", name="重新核对结束内容", exact=True).click()
                        expect(dialog.get_by_text("待审 · 当前稿 v4 · 缺当前定稿", exact=True)).to_be_visible()
                    snap(page, label + "-confirmation")
                    dialog.get_by_role("button", name="确认结束本期", exact=True).focus()
                    page.keyboard.press("Enter")
                    expect(page.locator("[data-topic-closed]")).to_be_visible()
                    expect(page.get_by_text("已结束 · " + ("第一阶段：选题" if phase == "selection" else "第二阶段：编译"), exact=True)).to_be_visible()
                    assert not page.locator('input[type="file"]').count()
                    layout = snap(page, label + "-lead-closed")
                    if zoom == 2:
                        assert layout["width"] < 800 and layout["dpr"] >= 2
                    login(page, "colleague", tid)
                    expect(page.locator("[data-topic-closed]")).to_be_visible()
                    assert not page.get_by_role("button", name="重新开启本期", exact=True).count()
                    if phase == "compilation":
                        page.get_by_text("核对采用的 1 篇具体定稿版本", exact=True).click()
                        with page.expect_download() as download:
                            page.get_by_role("link", name="下载所采用的定稿 v2", exact=True).click()
                        assert Path(download.value.path()).read_bytes() == b"synthetic draft v2"
                    page.get_by_text("下载本期材料包", exact=True).click()
                    with page.expect_download() as download:
                        page.get_by_role("link", name="全部已提交材料", exact=True).click()
                    package = out / (label + "-closed.zip")
                    download.value.save_as(str(package))
                    verify(package)
                    page.get_by_role("button", name="← 返回主题工作", exact=True).click()
                    expect(page.locator(f'[data-work-id="{tid}"]')).to_contain_text("已结束")
                    page.get_by_role("button", name="结束与重开 " + phase + " " + label, exact=True).click()
                    expect(page.locator("[data-topic-closed]")).to_be_visible()
                    snap(page, label + "-researcher-readonly")
                    login(page, "admin", tid)
                    assert not page.get_by_role("button", name="重新开启本期", exact=True).count()
                    assert not page.get_by_role("button", name="结束本期", exact=True).count()
                    login(page, "researcher", tid)
                    page.get_by_role("button", name="重新开启本期", exact=True).click()
                    page.get_by_role("button", name="确认重新开启", exact=True).click()
                    expect(page.get_by_role("button", name="结束本期", exact=True)).to_be_visible()
                    expect(page.locator("[data-topic-closed]")).to_have_count(0)
                    assert get(root)["stage"] == phase
                    login(page, "colleague", tid)
                    if phase == "selection":
                        page.get_by_role("button", name="提交我的选题报告", exact=True).click()
                        form = page.locator('[data-form="collaboration-upload"]')
                        control = form.get_by_label("选题报告文件 *", exact=True)
                        note = form.get_by_label("简短说明（可选）", exact=True)
                        button_name = "提交为版本 2"
                    else:
                        page.get_by_role("button", name="我的编译分工", exact=True).click()
                        card = page.locator(f'[data-assignment-card="{aid}"]')
                        form = card.locator('[data-form="topic-review-draft"]')
                        control = form.get_by_label("编译稿文件 *", exact=True)
                        note = form.get_by_label("交稿说明（可选）", exact=True)
                        button_name = "提交编译稿 v5"
                    name = "结束时保留的长文件名_" + "出处与作者核对" * 12 + ".txt"
                    upload(control, name, b"preserved old-page original")
                    note.fill("结束冲突后保留的说明")
                    note.focus()
                    page.keyboard.press("Shift+Tab" if phase == "selection" else "Tab")
                    expect(control).to_be_focused()
                    api_end(root, "close-during-old-form")
                    form.get_by_role("button", name=button_name, exact=True).click()
                    expect(form.get_by_text("本期已结束", exact=False).first).to_be_visible()
                    expect(note).to_have_value("结束冲突后保留的说明")
                    assert control.evaluate("e=>e.files[0].name") == name
                    snap(page, label + "-old-form-preserved")
                    api_reopen(root, "reopen-old-form")
                    resume = "已核对，保留输入继续" if phase == "selection" else "已核对，保留输入继续交接"
                    form.get_by_role("button", name=resume, exact=True).click()
                    expect(form.locator('[data-collaboration-conflict], [data-topic-review-conflict]')).to_be_empty()
                    form.get_by_role("button", name=button_name, exact=True).click()
                    if phase == "selection":
                        expect(page.get_by_role("link", name="下载原件 v2", exact=True)).to_be_visible()
                    else:
                        expect(page.locator(f'[data-assignment-card="{aid}"]').get_by_text("待审", exact=True)).to_be_visible()
                        assert get(root + "/workflow")["summaries"][0]["adoptions"][0]["version"] == 2
                    snap(page, label + "-continued")
                    topic = get(root)
                    assert topic["lifecycle_state"] == "open" and len(topic["lifecycle_events"]) == 4
                    results.append({"width": width, "actual_zoom": actual_zoom, "phase": phase, "topic": tid, "layout": layout, "end_reopen_read_export_old_form_preserved_and_continued": True, "stale_preview_rechecked": phase == "compilation"})
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
