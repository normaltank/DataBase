"""Real local Chromium meeting/draft/return/revision flows, including 200% zoom."""
import hashlib
import io
import json
import logging
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server
from platform_app.web import create_app
from scripts.check_collaboration_browser import login, no_overflow, original


def signout(page):
    page.get_by_role("button", name="退出登录", exact=True).click()


def main():
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    evidence = Path(tempfile.mkdtemp(prefix="database-topic-review-browser-"))
    extension = evidence / "zoom-extension"
    extension.mkdir()
    (extension / "manifest.json").write_text(json.dumps({"manifest_version": 3, "name": "Local zoom check", "version": "1.0", "permissions": ["tabs"], "background": {"service_worker": "worker.js"}}), encoding="utf-8")
    (extension / "worker.js").write_text("chrome.runtime.onInstalled.addListener(() => {});", encoding="utf-8")
    app = create_app(evidence / "data", testing=True)
    def account(name):
        client = app.test_client()
        token = client.get('/api/session').json['csrf']
        result = client.post('/api/login', json={'username': name, 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': token})
        assert result.status_code == 200
        return client
    fixture_admin = account('admin')
    response = fixture_admin.post('/api/members', json={'username': 'observer', 'name': '同伴研究员', 'password': 'LocalDemo2026!', 'role': 'researcher'}, headers={'X-CSRF-Token': fixture_admin.get('/api/session').json['csrf']})
    assert response.status_code == 201
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    results, errors = [], []
    try:
        with sync_playwright() as p:
            executable = os.environ.get("DATABASE_BROWSER_EXECUTABLE")
            context = p.chromium.launch_persistent_context(str(evidence / "profile"), headless=False,
                **({"executable_path": executable} if executable else {}),
                ignore_default_args=["--disable-extensions"],
                args=["--headless=new", f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
                viewport={"width": 1366, "height": 900}, accept_downloads=True)
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
            page = context.pages[0]
            page.on("pageerror", lambda e: errors.append(str(e)))
            login(page, base, "admin")
            page.get_by_role("button", name="负责人资格", exact=True).click()
            page.get_by_role("dialog").get_by_role("article").filter(has_text="研究员 · 林").get_by_role("button", name="登记资格", exact=True).click()
            expect(page.get_by_role("dialog").get_by_role("button", name="撤销资格", exact=True)).to_be_visible()
            page.get_by_role("button", name="关闭", exact=True).click()
            signout(page)
            login(page, base, 'researcher')
            page.get_by_role('button', name='开启一期主题', exact=False).click()
            page.get_by_label('本期主题', exact=False).fill('独立会议冲突复核')
            page.get_by_role('dialog').get_by_role('checkbox', name='研究员 · 周', exact=True).check()
            page.get_by_role('button', name='保存本期信息', exact=True).click()
            expect(page.get_by_role('heading', name='独立会议冲突复核', exact=True)).to_be_visible()
            conflict_tid = page.url.split('id=')[1]
            page.get_by_role('button', name='记录会议决定', exact=True).click()
            meeting_form = page.get_by_role('dialog')
            meeting_form.get_by_label('简短会议决定', exact=False).fill('保留的会议表单意见')
            meeting_form.get_by_label('会议材料文件', exact=False).set_input_files({'name': '保留会议.txt', 'mimeType': 'text/plain', 'buffer': b'preserved meeting original'})
            concurrent_lead = account('researcher')
            response = concurrent_lead.post(f'/api/collaboration/topics/{conflict_tid}/meetings', json={'request_id': 'concurrent-meeting-conflict', 'version': 0, 'topic_version': 1, 'note': '另一页决定', 'assignments': [{'title': '另一页新增的采用文章', 'author_id': 'colleague'}]}, headers={'X-CSRF-Token': concurrent_lead.get('/api/session').json['csrf']})
            assert response.status_code == 201, response.json
            meeting_form.get_by_role('button', name='保存会议决定 v1', exact=True).click()
            conflict = meeting_form.locator('[data-topic-review-conflict]')
            expect(conflict.get_by_role('heading', name='请核对最新交接', exact=True)).to_be_visible()
            # A meeting conflict must expose current adoptions, not only its note.
            conflict.get_by_text('采用文章与分工 1 项', exact=True).click()
            expect(conflict.get_by_text('另一页新增的采用文章', exact=True)).to_be_visible()
            expect(meeting_form.get_by_label('简短会议决定', exact=False)).to_have_value('保留的会议表单意见')
            assert meeting_form.get_by_label('会议材料文件', exact=False).evaluate('el=>el.files[0].name') == '保留会议.txt'
            conflict.get_by_role('button', name='已核对，保留输入继续交接', exact=True).click()
            meeting_form.get_by_role('button', name='保存会议决定 v2', exact=True).click()
            expect(page.get_by_role('heading', name='会议决定 v2 · 研究员 · 林', exact=True)).to_be_visible()
            signout(page)
            for width, zoom in ((1366, 1), (390, 1), (1366, 2)):
                page.set_viewport_size({"width": width, "height": 900})
                worker.evaluate("async ({url,zoom})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,zoom)}", {"url": base, "zoom": zoom})
                login(page, base, "researcher")
                theme = f"会议与返修 {width}/{zoom} · 东欧跨境交流"
                title = "站外采用文章_" + "跨国研究与少数民族资料" * 8
                page.get_by_role("button", name="开启一期主题", exact=False).click()
                page.get_by_label("本期主题", exact=False).fill(theme)
                page.get_by_role("dialog").get_by_role("checkbox", name="研究员 · 周", exact=True).check()
                page.get_by_role("dialog").get_by_role("checkbox", name="同伴研究员", exact=True).check()
                page.get_by_role("button", name="保存本期信息", exact=True).click()
                expect(page.get_by_role("heading", name=theme, exact=True)).to_be_visible()
                topic_url = page.url
                candidate = original("独立合成候选报告")
                page.get_by_label("选题报告文件", exact=False).set_input_files({"name": "选题.docx", "mimeType": "application/octet-stream", "buffer": candidate})
                page.get_by_role("button", name="提交为版本 1", exact=True).click()
                expect(page.get_by_role("link", name="下载原件 v1", exact=True)).to_be_visible()
                page.get_by_role("button", name="记录会议决定", exact=True).click()
                page.get_by_label("简短会议决定", exact=False).fill("采用报告第2项及站外出处；在本机完成编译后交稿。")
                page.get_by_label("会议材料文件", exact=False).set_input_files({"name": "会议材料.txt", "mimeType": "text/plain", "buffer": b"actual meeting synthetic bytes"})
                page.get_by_role("button", name="添加采用文章", exact=True).click()
                row = page.get_by_role("dialog").locator("[data-assignment-row]")
                row.get_by_label("题名或报告项目", exact=False).fill(title)
                row.get_by_label("编译研究员", exact=False).select_option("colleague")
                row.get_by_label("出处或站外链接", exact=False).fill("https://example.invalid/uncatalogued-article")
                row.get_by_text("报告位置与国家分工（可选）", exact=True).click()
                row.get_by_label("所据选题报告版本", exact=True).select_option(index=1)
                row.get_by_label("报告项目或页码", exact=True).fill("第2项，第3页")
                row.get_by_label("国家或范围分工", exact=True).fill("拉脱维亚、波兰")
                no_overflow(page)
                page.get_by_role("button", name="保存会议决定 v1", exact=True).click()
                expect(page.get_by_role("heading", name="编译稿与返修", exact=True)).to_be_visible()
                expect(page.get_by_text("待交稿", exact=True)).to_be_visible()
                # The top action must reveal the form inside folded candidate history.
                page.get_by_role("button", name="提交我的选题报告", exact=True).click()
                expect(page.get_by_label("选题报告文件", exact=False)).to_be_visible(timeout=3000)
                signout(page)
                login(page, base, "colleague")
                page.get_by_role("button", name=theme, exact=True).click()
                page.get_by_role("button", name="我的编译分工", exact=True).click()
                card = page.locator('[data-assignment-card][data-mine="true"]')
                card.get_by_label("交稿说明", exact=False).focus()
                page.keyboard.press("Tab")
                expect(card.get_by_label("编译稿文件", exact=False)).to_be_focused()
                first = original("编译稿第一版")
                filename = "编译稿_" + "需要核对的长文件名" * 10 + ".docx"
                card.get_by_label("编译稿文件", exact=False).set_input_files({"name": filename, "mimeType": "application/octet-stream", "buffer": first})
                card.get_by_label("交稿说明", exact=False).fill("本机完成，无须原文逐篇入库。")
                card.get_by_role("button", name="提交编译稿 v1", exact=True).click()
                expect(page.get_by_text("待审", exact=True)).to_be_visible()
                expect(card.get_by_label("编译稿文件", exact=False)).to_be_hidden()
                card.get_by_text("完整题名", exact=True).click()
                expect(card.get_by_text(title, exact=True)).to_be_visible()
                card.get_by_text("完整题名", exact=True).click()
                card.get_by_text("完整文件名", exact=True).click()
                expect(card.get_by_text(filename, exact=True)).to_be_visible()
                card.get_by_text("完整文件名", exact=True).click()
                no_overflow(page)
                signout(page)
                login(page, base, "researcher")
                page.get_by_role("button", name=theme, exact=True).click()
                card = page.locator('[data-assignment-card]')
                card.get_by_text("退回修改 · 针对版本 1", exact=True).click()
                card.get_by_label("退回意见", exact=True).fill("请补来源页码，保留所据原句。")
                card.get_by_label("批注文件", exact=False).set_input_files({"name": "批注.txt", "mimeType": "text/plain", "buffer": b"annotation bytes"})
                card.get_by_role("button", name="退回版本 1", exact=True).click()
                expect(page.get_by_text("返修", exact=True)).to_be_visible()
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(evidence / f"returned-{width}-{zoom}.png"), full_page=zoom == 1)
                no_overflow(page)
                signout(page)
                login(page, base, "colleague")
                page.get_by_role("button", name=theme, exact=True).click()
                card = page.locator('[data-assignment-card]')
                expect(card.get_by_text("请补来源页码，保留所据原句。", exact=True)).to_be_visible()
                page.get_by_role("button", name="我的编译分工", exact=True).click()
                revised = original("返修编译稿第二版")
                card.get_by_label("编译稿文件", exact=False).set_input_files({"name": "返修稿.docx", "mimeType": "application/octet-stream", "buffer": revised})
                card.get_by_label("交稿说明", exact=False).fill("冲突后仍保留的返修说明")
                peer = context.new_page()
                peer.on("pageerror", lambda e: errors.append(str(e)))
                peer.goto(topic_url)
                peer.get_by_role("button", name="我的编译分工", exact=True).click()
                peer.get_by_label("编译稿文件", exact=False).set_input_files({"name": "另一页面返修.docx", "mimeType": "application/octet-stream", "buffer": revised})
                peer.get_by_role("button", name="提交编译稿 v2", exact=True).click()
                expect(peer.get_by_role("link", name="下载原件 v2", exact=True)).to_be_visible()
                card.get_by_role("button", name="提交编译稿 v2", exact=True).click()
                expect(card.get_by_role("heading", name="请核对最新交接", exact=True)).to_be_visible()
                expect(card.get_by_label("交稿说明", exact=False)).to_have_value("冲突后仍保留的返修说明")
                assert card.get_by_label("编译稿文件", exact=False).evaluate("el=>el.files[0].name") == "返修稿.docx"
                card.get_by_role("button", name="已核对，保留输入继续交接", exact=True).click()
                card.get_by_role("button", name="提交编译稿 v3", exact=True).click()
                expect(card.get_by_role("link", name="下载原件 v3", exact=True)).to_be_visible()
                expect(card.get_by_label("编译稿文件", exact=False)).to_be_hidden()
                peer.close()
                card.get_by_text("此前 2 版稿件及退回意见", exact=True).click()
                expect(card.get_by_text("请补来源页码，保留所据原句。", exact=True)).to_be_visible()
                with page.expect_download() as download:
                    card.get_by_role("link", name="下载原件 v1", exact=True).click()
                assert Path(download.value.path()).read_bytes() == first
                assert download.value.suggested_filename == filename
                layout = no_overflow(page)
                if zoom == 2:
                    assert layout["width"] < 800 and layout["dpr"] >= 2, layout
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(evidence / f"resubmitted-{width}-{zoom}.png"), full_page=zoom == 1)
                signout(page)
                login(page, base, "researcher")
                page.get_by_role("button", name=theme, exact=True).click()
                expect(page.get_by_text("待审", exact=True)).to_be_visible()
                lead_card = page.locator('[data-assignment-card]')
                lead_card.get_by_text('退回修改 · 针对版本 3', exact=True).click()
                lead_card.get_by_label('退回意见', exact=True).fill('过期审稿仍保留的意见')
                lead_card.get_by_label('批注文件', exact=False).set_input_files({'name': '最新批注.txt', 'mimeType': 'text/plain', 'buffer': b'latest annotation'})
                # Another authenticated author request commits while this review page remains open.
                author = account('colleague')
                tid = page.url.split('id=')[1]
                workflow_path = f'/api/collaboration/topics/{tid}/workflow'
                workflow = author.get(workflow_path).json
                a = workflow['assignments'][0]
                payload = {'request_id': f'concurrent-review-{width}-{zoom}', 'version': 3, 'topic_version': 1, 'meeting_version': 1, 'note': '另一设备交稿'}
                result = author.post(f'/api/collaboration/topics/{tid}/assignments/{a["id"]}/submissions', data={'data': json.dumps(payload), 'file': (io.BytesIO(b'concurrent draft'), '第四版.txt')}, headers={'X-CSRF-Token': author.get('/api/session').json['csrf']})
                assert result.status_code == 201, result.json
                result.request.close()
                lead_card.get_by_role('button', name='退回版本 3', exact=True).click()
                expect(lead_card.get_by_role('heading', name='请核对最新交接', exact=True)).to_be_visible()
                expect(lead_card.get_by_label('退回意见', exact=True)).to_have_value('过期审稿仍保留的意见')
                assert lead_card.get_by_label('批注文件', exact=False).evaluate('el=>el.files[0].name') == '最新批注.txt'
                lead_card.get_by_role('button', name='已核对，保留意见审阅最新稿', exact=True).click()
                lead_card.get_by_role('button', name='退回版本 4', exact=True).click()
                expect(page.get_by_text('返修', exact=True)).to_be_visible()
                signout(page)
                login(page, base, 'colleague')
                page.get_by_role('button', name=theme, exact=True).click()
                page.get_by_role('button', name='我的编译分工', exact=True).click()
                page.get_by_label('编译稿文件', exact=False).set_input_files({'name': '最终返修.txt', 'mimeType': 'text/plain', 'buffer': b'resubmitted pending review'})
                page.get_by_role('button', name='提交编译稿 v5', exact=True).click()
                expect(page.get_by_text('待审', exact=True)).to_be_visible()
                signout(page)
                # Ordinary peer reads exact history without author or lead actions.
                login(page, base, "observer")
                page.get_by_role('button', name=theme, exact=True).click()
                page.locator('[data-assignment-card]').get_by_text("此前 4 版稿件及退回意见", exact=True).click()
                expect(page.get_by_text("请补来源页码，保留所据原句。", exact=True)).to_be_visible()
                assert page.get_by_label("编译稿文件", exact=False).count() == 0
                assert page.get_by_label("退回意见", exact=True).count() == 0
                no_overflow(page)
                signout(page)
                login(page, base, "admin")
                page.get_by_role("button", name="维护查阅", exact=True).click()
                page.get_by_role("button", name=theme, exact=True).click()
                assert page.get_by_label("退回意见", exact=True).count() == 0
                assert page.get_by_label("编译稿文件", exact=False).count() == 0
                no_overflow(page)
                signout(page)
                results.append({"width": width, "zoom": zoom, "layout": layout, "manuscript_versions": 5, "returns_bound_to_v1_and_v4": True, "draft_conflict_preserved_file_and_note": True, "review_conflict_preserved_file_and_note": True, "submitted_form_collapsed": True, "ordinary_peer_readonly": True, "admin_readonly": True, "keyboard_file_control": True, "first_original_sha256": hashlib.sha256(first).hexdigest()})
            assert not errors, errors
            context.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    (evidence / "results.json").write_text(json.dumps({"results": results, "page_errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(evidence), "results": results, "page_errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
