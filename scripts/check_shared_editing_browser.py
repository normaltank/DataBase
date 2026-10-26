"""#38 acceptance through real Chromium and HTTP with owned Temp data on 8854."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8854"
OUT = Path(tempfile.mkdtemp(prefix="database-shared-editing-"))


def call(request, path, data=None, method="POST"):
    csrf = request.get(URL + "/api/session").json()["csrf"]
    response = request.fetch(URL + path, method=method, data=data or {}, headers={"X-CSRF-Token": csrf})
    assert response.ok, (path, response.status, response.text())
    return response.json()


def open_record(page, rid):
    if page.locator('.drawer-head [data-action=close]').count():
        page.locator('.drawer-head [data-action=close]').click()
    page.goto(URL + "/#library?q=共编验收")
    page.locator('[data-library-record="' + rid + '"] [data-action=detail]').first.click()
    expect(page.locator('.library-reader:visible')).to_have_count(1)


def edit(page, rid):
    open_record(page, rid)
    page.locator('.library-reader .ux-maintenance > summary').click()
    page.locator('.library-reader .ux-maintenance [data-action=edit-record]').click()
    expect(page.locator('[data-form=record] [type=submit]')).to_be_enabled()
    return page.locator('[data-rich-field=body_html] [data-rich-input]')


def run():
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", 8854)) != 0, "8854 occupied; refusing unknown service"
    log = (OUT / "server.log").open("w", encoding="utf-8")
    server = subprocess.Popen([os.environ.get("DATABASE_APP_PYTHON", r"C:\Python312\python.exe"), str(ROOT / "app.py"),
        "--no-import", "--port", "8854", "--data-dir", str(OUT / "data")], cwd=ROOT, stdout=log,
        stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        for _ in range(100):
            try:
                urlopen(URL + "/health", timeout=.5).close()
                break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError("Synthetic service did not start")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_EXECUTABLE", r"C:\Users\27451\AppData\Local\ms-playwright\chromium-1187\chrome-win\chrome.exe"))
            contexts = {who: browser.new_context(viewport={"width": 1440, "height": 1000}) for who in ["researcher", "colleague"]}
            for who, context in contexts.items():
                call(context.request, "/api/login", {"username": who, "password": "LocalDemo2026!"})
            request = contexts["researcher"].request
            note = call(request, "/api/records", {"kind": "research_note", "title": "共编验收笔记", "body_html": "<p>笔记初稿</p>"})["id"]
            raw = call(request, "/api/records", {"kind": "report", "title": "共编验收外部资料", "body_html": "<p>外部初稿</p>"})["id"]
            personal = call(request, "/api/records", {"kind": "research_report", "title": "共编验收个人报告", "body_html": "<p>个人正文</p>"})["id"]
            private = call(request, "/api/records", {"kind": "research_note", "title": "共编验收受限笔记", "visibility": "restricted"})["id"]
            pages = {who: context.new_page() for who, context in contexts.items()}
            errors = []
            for page in pages.values():
                page.set_default_timeout(8000)
                page.on("pageerror", lambda error: errors.append(str(error)))
            first, second = pages["researcher"], pages["colleague"]
            edit(first, note).fill("成员甲保存正文")
            editor = edit(second, note)
            expect(second.locator('[data-access-fields]')).to_be_hidden()
            expect(second.locator('[data-author-new]')).to_be_hidden()
            editor.fill("成员乙保留的并发输入")
            first.locator('[data-form=record] [type=submit]').click()
            expect(first.locator('[data-form=record]')).to_have_count(0)
            second.locator('[data-form=record] [type=submit]').click()
            expect(second.locator('[data-conflict-panel]')).to_be_visible()
            expect(editor).to_have_text("成员乙保留的并发输入")
            second.screenshot(path=str(OUT / "conflict-input-preserved.png"))
            second.locator('[data-action=accept-latest-version]').click()
            second.locator('[data-form=record] [type=submit]').click()
            expect(second.locator('[data-form=record]')).to_have_count(0)
            current = contexts["colleague"].request.get(URL + "/api/records/" + note).json()
            assert current["version"] == 3 and "成员乙保留的并发输入" in current["body_html"]
            open_record(second, note)
            second.locator('.library-reader .ux-maintenance > summary').click()
            second.locator('.library-reader [data-action=history]').click()
            second.locator('[data-action=restore]').last.click()
            expect(second.locator('[data-action=restore]')).to_have_count(0)
            restored = contexts["colleague"].request.get(URL + "/api/records/" + note).json()
            assert restored["version"] == 4 and restored["body_html"] == "<p>笔记初稿</p>"
            edit(second, raw).fill("另一成员维护外部资料")
            expect(second.locator('[data-access-fields]')).to_be_hidden()
            second.screenshot(path=str(OUT / "shared-editor-no-management.png"))
            second.locator('[data-form=record] [type=submit]').click()
            expect(second.locator('[data-form=record]')).to_have_count(0)
            open_record(second, personal)
            expect(second.locator('.library-reader [data-action=edit-record]')).to_have_count(0)
            denied = contexts["colleague"].request.put(URL + "/api/records/" + personal, data={"version": 1, "body_html": "越权"},
                headers={"X-CSRF-Token": contexts["colleague"].request.get(URL + "/api/session").json()["csrf"]})
            assert denied.status == 403
            second.screenshot(path=str(OUT / "personal-report-protected.png"))
            second.goto(URL + "/#library?q=共编验收")
            expect(second.locator('[data-library-record="' + private + '"]')).to_have_count(0)
            assert contexts["colleague"].request.get(URL + "/api/records/" + private).status == 404
            assert not errors, errors
            result = {"passed": True, "checks": ["two member note edits", "conflict preserves input", "member restores initial note", "external content shared editing", "editor hides management controls", "personal report edit denied", "restricted note remains unreadable"], "javascript_errors": errors, "evidence": str(OUT)}
            (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False), flush=True)
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
        log.close()


if __name__ == "__main__":
    print("Shared editing evidence:", OUT, flush=True)
    run()
