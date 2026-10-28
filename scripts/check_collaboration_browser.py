"""Real Chromium checks using synthetic originals, dynamic port and isolated data.

Uses Chromium's tabs.setZoom API for real 200% browser zoom (not CSS zoom).
Evidence stays in a new Temp directory, with no ingestion worker or external AI.
"""
import hashlib
import io
import json
import logging
import os
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server
from platform_app.web import create_app


def original(text):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>')
    return stream.getvalue()


def login(page, base, name):
    page.goto(base)
    page.get_by_label("账号", exact=True).fill(name)
    page.get_by_label("密码", exact=True).fill("LocalDemo2026!")
    page.get_by_role("button", name="查看资料", exact=True).click()
    expect(page.locator('[data-action="nav"][data-id="collaboration"]')).to_be_attached()
    toggle = page.get_by_role("button", name="打开导航", exact=True)
    if toggle.is_visible():
        toggle.click()
    page.get_by_role("button", name="编译协作", exact=True).click()
    expect(page.get_by_role("heading", name="编译协作", exact=True)).to_be_visible()


def no_overflow(page):
    result = page.evaluate("({width:innerWidth,scroll:document.documentElement.scrollWidth,dpr:devicePixelRatio})")
    assert result["scroll"] <= result["width"] + 1, result
    return result


def main():
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    evidence = Path(tempfile.mkdtemp(prefix="database-collaboration-browser-"))
    extension = evidence / "zoom-extension"
    extension.mkdir()
    (extension / "manifest.json").write_text(json.dumps({"manifest_version": 3, "name": "Synthetic local zoom verifier", "version": "1.0", "permissions": ["tabs"], "background": {"service_worker": "worker.js"}}), encoding="utf-8")
    (extension / "worker.js").write_text("chrome.runtime.onInstalled.addListener(() => {});", encoding="utf-8")
    app = create_app(evidence / "data", testing=True)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    results, errors = [], []
    try:
        with sync_playwright() as p:
            executable = os.environ.get("DATABASE_BROWSER_EXECUTABLE")
            context = p.chromium.launch_persistent_context(str(evidence / "browser-profile"), headless=False,
                **({"executable_path": executable} if executable else {}),
                ignore_default_args=["--disable-extensions"],
                args=["--headless=new", f"--disable-extensions-except={extension}", f"--load-extension={extension}"], viewport={"width": 1366, "height": 900}, accept_downloads=True)
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
            page = context.pages[0]
            page.on("pageerror", lambda error: errors.append(str(error)))
            login(page, base, "admin")
            page.get_by_role("button", name="负责人资格", exact=True).click()
            card = page.get_by_role("dialog").get_by_role("article").filter(has_text="研究员 · 林")
            card.get_by_role("button", name="登记资格", exact=True).click()
            expect(card.get_by_role("button", name="撤销资格", exact=True)).to_be_visible()
            page.get_by_role("button", name="关闭", exact=True).click()
            page.get_by_role("button", name="退出登录", exact=True).click()
            for width, zoom in ((1366, 1), (390, 1), (1366, 2)):
                page.set_viewport_size({"width": width, "height": 900})
                worker.evaluate("async ({url,zoom})=>{const tabs=await chrome.tabs.query({});const t=tabs.find(x=>x.url.startsWith(url));await chrome.tabs.setZoom(t.id,zoom);}", {"url": base, "zoom": zoom})
                login(page, base, "researcher")
                theme = f"合成主题 {width} / {int(zoom*100)}% 东欧少数民族与跨境交流"
                page.get_by_role("button", name="开启一期主题", exact=False).click()
                page.get_by_label("本期主题", exact=False).fill(theme)
                page.get_by_role("dialog").get_by_role("checkbox", name="研究员 · 周", exact=True).check()
                page.get_by_label("提交日期", exact=False).fill("2026-11-10")
                page.get_by_role("button", name="保存本期信息", exact=True).click()
                expect(page.get_by_role("heading", name=theme, exact=True)).to_be_visible()
                topic_url = page.url
                assert len(page.get_by_role("checkbox").all()) == 0
                first, second = original("候选原件一"), original("候选原件二")
                long_name = "选题报告_" + "跨国来源与资料复核" * 10 + ".docx"
                page.get_by_label("选题报告文件", exact=False).set_input_files({"name": long_name, "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "buffer": first})
                page.get_by_label("简短说明", exact=False).fill("本机模板直接上传，无需重填题录。")
                page.get_by_role("button", name="提交为版本 1", exact=True).click()
                expect(page.get_by_role("link", name="下载原件 v1", exact=True)).to_be_visible()
                # A second real page updates the same report. The first keeps its selected file on conflict.
                peer = context.new_page()
                peer.goto(topic_url)
                page.get_by_label("选题报告文件", exact=False).set_input_files({"name": "修改稿.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "buffer": second})
                page.get_by_label("简短说明", exact=False).fill("冲突仍保留的说明")
                peer.get_by_label("选题报告文件", exact=False).set_input_files({"name": "另一页提交.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "buffer": second})
                peer.get_by_role("button", name="提交为版本 2", exact=True).click()
                expect(peer.get_by_role("link", name="下载原件 v2", exact=True)).to_be_visible()
                page.get_by_role("button", name="提交为版本 2", exact=True).click()
                expect(page.get_by_role("heading", name="请核对本期最新信息")).to_be_visible()
                expect(page.get_by_label("简短说明", exact=False)).to_have_value("冲突仍保留的说明")
                assert page.locator("#candidate-file").evaluate("el=>el.files[0].name") == "修改稿.docx"
                page.get_by_role("button", name="已核对，保留输入继续", exact=True).click()
                page.get_by_role("button", name="提交为版本 3", exact=True).click()
                expect(page.get_by_role("link", name="下载原件 v3", exact=True)).to_be_visible()
                peer.close()
                page.get_by_text("查看此前 2 个原件版本", exact=True).click()
                with page.expect_download() as download:
                    page.get_by_role("link", name="下载原件 v1", exact=True).click()
                assert Path(download.value.path()).read_bytes() == first
                layout = no_overflow(page)
                if zoom == 2:
                    assert layout["width"] < 800 and layout["dpr"] >= 2, layout
                page.screenshot(path=str(evidence / f"topic-{width}-{int(zoom*100)}.png"), full_page=True)
                # Keyboard reaches the actual file control and enters the note field.
                page.get_by_label("选题报告文件", exact=False).focus()
                page.keyboard.press("Tab")
                expect(page.get_by_label("简短说明", exact=False)).to_be_focused()
                page.get_by_role("button", name="退出登录", exact=True).click()
                login(page, base, "colleague")
                page.get_by_role("button", name=theme, exact=True).click()
                expect(page.get_by_role("link", name="下载原件 v3", exact=True)).to_be_visible()
                page.get_by_text("查看此前 2 个原件版本", exact=True).click()
                with page.expect_download() as peer_download:
                    page.get_by_role("link", name="下载原件 v1", exact=True).click()
                assert Path(peer_download.value.path()).read_bytes() == first
                no_overflow(page)
                assert page.get_by_role("button", name="维护本期信息", exact=True).count() == 0
                page.get_by_role("button", name="退出登录", exact=True).click()
                results.append({"width": width, "zoom": zoom, "layout": layout, "versions": 3, "old_original_sha256": hashlib.sha256(first).hexdigest(), "peer_read": True, "conflict_preserved_file": True})
            assert not errors, errors
            context.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    (evidence / "results.json").write_text(json.dumps({"results": results, "page_errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(evidence), "cases": len(results), "page_errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
