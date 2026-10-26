import hashlib
import io
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from platform_app.store import connect
from platform_app.web import create_app


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="research-ux-backend-")
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"
        self.app = create_app(self.data_dir, testing=True)
        self.clients = {}
        for uid in ["researcher", "colleague", "admin"]:
            client = self.app.test_client()
            csrf = client.get("/api/session").json["csrf"]
            result = client.post("/api/login", json={"username": uid, "password": "LocalDemo2026!"}, headers={"X-CSRF-Token": csrf})
            self.assertEqual(result.status_code, 200)
            self.clients[uid] = client

    def call(self, path, values, user="researcher", method="POST", file=None):
        client = self.clients[user]
        csrf = client.get("/api/session").json["csrf"]
        args = {"headers": {"X-CSRF-Token": csrf}}
        if file:
            args["data"] = {"data": json.dumps(values), "file": (io.BytesIO(file[1]), file[0])}
        else:
            args["json"] = values
        return client.open(path, method=method, **args)

    def record(self, kind="report", user="researcher", file=None, **values):
        result = self.call("/api/records", {"kind": kind, "title": "测试资料", **values}, user=user, file=file)
        self.assertEqual(result.status_code, 201, result.json)
        return result.json["id"]

    def detail(self, rid, user="researcher"):
        result = self.clients[user].get("/api/records/" + rid)
        self.assertEqual(result.status_code, 200, result.json)
        return result.json

    def copy(self, rid, user="researcher"):
        result = self.clients[user].get("/api/records/" + rid + "/copy-text")
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(set(result.json), {"mode", "text", "notice"})
        return result.json

    def fixture_values(self, rid, **values):
        with closing(connect(self.data_dir / "platform.sqlite3")) as db:
            with db:
                db.execute("UPDATE records SET " + ",".join(key + "=?" for key in values) + " WHERE id=?", [*values.values(), rid])

    def test_reading_access_real_import_shape_and_current_file(self):
        rid = self.record(url="https://example.org/article", body_html="<p>已保存正文</p>", sharing_confirmed=True, file=("当前稿件.txt", b"current file"))
        imported = [{"name": "D:/private/notes.docx", "url": "https://example.org/file.docx", "type": "docx", "sha256": "fixture", "sharing_status": "metadata_only"},
                    {"name": "重复", "url": " https://example.org/file.docx ", "type": "document"},
                    {"name": "非 PDF", "url": "https://example.org/download?id=2", "type": "unknown"}]
        self.fixture_values(rid, raw_json=json.dumps({"imported_attachments": imported}))
        detailed = self.detail(rid)
        summary = self.clients["researcher"].get("/api/records").json["items"][0]
        access = detailed["reading_access"]
        self.assertEqual(summary["reading_access"], access)
        self.assertEqual(access["original_url"], "https://example.org/article")
        self.assertEqual(access["official_files"], [{"url": "https://example.org/file.docx", "label": "官方文件链接"}, {"url": "https://example.org/download?id=2", "label": "官方文件链接"}])
        self.assertTrue(access["has_body"])
        self.assertNotIn("D:/private", json.dumps(access))
        self.assertEqual(len(access["platform_files"]), 1)
        attached = access["platform_files"][0]
        self.assertEqual(attached["id"], detailed["attachments"][0]["id"])
        self.assertEqual(attached["name"], "当前稿件.txt")
        with self.clients["colleague"].get(attached["url"]) as download:
            self.assertEqual(download.data, b"current file")

    def test_missing_malformed_and_unsafe_external_links_are_not_reading_entries(self):
        rid = self.record(abstract="摘要不代表已保存正文", body_html="<p><br></p>")
        bad = ["javascript:alert(1)", "data:text/html,test", "file:///D:/private/file.pdf", "//example.org/file", "https://user:pass@example.org/file", "https://@example.org/file", "https://example.org:bad/file", "https://example.org:99999/file", "https://exa mple.org/file", "https://example.org/pa\nth", "https://example.org\\@other.org/file", "https:///missing-host", "http://[bad", ""]
        for link in bad:
            with self.subTest(link=link):
                self.fixture_values(rid, url=link, raw_json=json.dumps({"imported_attachments": [{"url": link}, None, {"url": []}, {"local_path": "D:/private/file.pdf"}]}))
                access = self.detail(rid)["reading_access"]
                self.assertEqual(access, {"original_url": "", "official_files": [], "platform_files": [], "has_body": False})
                self.assertNotIn("原文地址：", self.copy(rid)["text"])
        for imported in [None, {}, "https://example.org/file", [None, {}, {"url": None}]]:
            self.fixture_values(rid, raw_json=json.dumps({"imported_attachments": imported}))
            self.assertEqual(self.detail(rid)["reading_access"]["official_files"], [])

    def test_platform_reading_entries_follow_current_version_and_file_presence(self):
        rid = self.record(sharing_confirmed=True, file=("最初.txt", b"first"))
        first = self.detail(rid)["attachments"][0]["id"]
        changed = self.call("/api/records/" + rid, {"version": 1, "sharing_confirmed": True}, method="PUT", file=("后来.txt", b"second"))
        self.assertEqual(changed.status_code, 200)
        second = next(a["id"] for a in self.detail(rid)["attachments"] if a["id"] != first)
        history = self.clients["researcher"].get("/api/history/record/" + rid).json["items"]
        restored = self.call(f"/api/history/{history[-1]['id']}/restore", {"version": 2})
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual([a["id"] for a in self.detail(rid)["reading_access"]["platform_files"]], [first])
        with closing(connect(self.data_dir / "platform.sqlite3")) as db:
            stored = db.execute("SELECT stored_name FROM attachments WHERE id=?", (first,)).fetchone()[0]
        (self.data_dir / "uploads" / stored).unlink()
        other = self.record(sharing_confirmed=True, file=("其他资料.txt", b"other record"))
        other_aid = self.detail(other)["attachments"][0]["id"]
        self.fixture_values(rid, attachment_ids=json.dumps([first, other_aid]))
        self.assertEqual(self.detail(rid)["reading_access"]["platform_files"], [])
        self.assertEqual(self.clients["researcher"].get("/api/attachments/" + second).status_code, 404)

    def test_reading_and_copy_endpoints_respect_record_permissions(self):
        rid = self.record(visibility="restricted", url="https://example.org/private", sharing_confirmed=True, file=("受限.txt", b"restricted"))
        attached = self.detail(rid)["reading_access"]["platform_files"][0]
        result = self.clients["colleague"].get("/api/records").json
        self.assertNotIn(rid, json.dumps(result))
        for path in ["/api/records/" + rid, "/api/records/" + rid + "/copy-text", attached["url"]]:
            self.assertEqual(self.clients["colleague"].get(path).status_code, 404)
        self.assertEqual(self.copy(rid, "admin")["mode"], "citation")
        self.assertEqual(self.app.test_client().get("/api/records/" + rid + "/copy-text").status_code, 401)

    def test_citation_copy_omits_missing_fields_and_is_read_only(self):
        rid = self.record(title="中文题名", original_title="Original title", authors="原作者", published_on="2026-01", publication_title="测试刊物", doi="10.1234/test", url="https://example.org/original")
        source = self.call("/api/sources", {"name": "目录期刊", "kind": "journal"}).json["id"]
        directory = self.record("directory_translation", title="跨期译目", authors="编译署名", coverage="2024—2026", related_source_ids=[source])
        missing = self.record(title="只有题名")
        def fingerprint():
            with closing(connect(self.data_dir / "platform.sqlite3")) as db:
                return hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()
        before = fingerprint()
        text = self.copy(rid)
        self.assertEqual(text["mode"], "citation")
        for value in ["中文题名", "Original title", "原作者", "2026-01", "测试刊物", "10.1234/test", "https://example.org/original", rid, "版本：1"]:
            self.assertIn(value, text["text"])
        directory_text = self.copy(directory)
        self.assertEqual(directory_text["mode"], "citation")
        self.assertIn("2024—2026", directory_text["text"])
        self.assertIn("编译署名", directory_text["text"])
        self.assertNotIn("DOI：", self.copy(missing)["text"])
        self.assertEqual(fingerprint(), before)

    def test_excerpt_and_report_copy_keep_adopted_versions(self):
        original = self.record(title="原文旧题名", authors="原文旧作者", published_on="2025-01", url="https://example.org/old")
        note = self.record("research_note", title="摘录题名", authors="笔记署名", evidence_record_id=original, quote="原文摘录第一版", translation="译文第一版", interpretation="解释第一版", locator="第 8 页", body_html="<p>笔记正文第一版</p>")
        report = self.record("research_report", evidence_ids=[note])
        self.assertEqual(self.call("/api/records/" + original, {"version": 1, "title": "原文新题名", "authors": "原文新作者", "published_on": "2026-10", "url": "https://example.org/new"}, method="PUT").status_code, 200)
        self.assertEqual(self.call("/api/records/" + note, {"version": 1, "quote": "原文摘录第二版", "body_html": "<p>笔记正文第二版</p>"}, method="PUT").status_code, 200)
        direct = self.copy(note)
        self.assertEqual(direct["mode"], "excerpt")
        self.assertIn("原文摘录第二版", direct["text"])
        pinned = self.copy(report)
        self.assertEqual(pinned["mode"], "references")
        for value in ["原文摘录第一版", "译文第一版", "解释第一版", "第 8 页", "笔记正文第一版", "采用笔记版本：1"]:
            self.assertIn(value, pinned["text"])
        for copied in [direct, pinned]:
            self.assertIn("原文旧题名", copied["text"])
            self.assertIn("原文旧作者", copied["text"])
            self.assertIn("2025-01", copied["text"])
            self.assertIn("https://example.org/old", copied["text"])
            self.assertIn("引用原文版本：1", copied["text"])
            self.assertNotIn("原文新题名", copied["text"])
            self.assertNotIn("<p>", copied["text"])
        self.assertNotIn("第二版", pinned["text"])
        self.assertEqual(self.call("/api/records/" + report, {"version": 1, "evidence_ids": [note], "refresh_citations": True}, method="PUT").status_code, 200)
        refreshed = self.copy(report)["text"]
        self.assertIn("采用笔记版本：2", refreshed)
        self.assertIn("原文摘录第二版", refreshed)
        self.assertIn("原文旧题名", refreshed)

    def test_hidden_references_and_no_references_share_non_disclosing_empty_state(self):
        original = self.record(title="之后撤权的原文")
        note = self.record("research_note", evidence_record_id=original, quote="可访问摘录", locator="第 2 页")
        hidden = self.record("research_note", title="隐藏笔记题名", body_html="<p>隐藏笔记正文</p>", visibility="restricted")
        report = self.record("compilation", evidence_ids=[note, hidden])
        empty = self.record("research_report")
        allowed = self.copy(report, "colleague")
        self.assertIn("可访问摘录", allowed["text"])
        for value in [hidden, "隐藏笔记题名", "隐藏笔记正文"]:
            self.assertNotIn(value, json.dumps(allowed, ensure_ascii=False))
        self.assertEqual(self.call("/api/records/" + original, {"version": 1, "visibility": "restricted"}, method="PUT").status_code, 200)
        self.assertEqual(self.clients["colleague"].get("/api/records/" + note + "/copy-text").status_code, 404)
        self.assertEqual(self.copy(report, "colleague"), self.copy(empty, "colleague"))
        self.assertEqual(self.copy(empty)["text"], "暂无可复制的引用。")
        self.assertIn("隐藏笔记正文", self.copy(report, "admin")["text"])

    def test_report_copy_checks_pinned_source_after_note_is_retargeted(self):
        old = self.record(title="原采用资料秘密题名")
        new = self.record(title="现在关联的公开资料")
        note = self.record("research_note", evidence_record_id=old, quote="原采用秘密摘录", locator="第 2 页")
        report = self.record("research_report", evidence_ids=[note])
        self.assertEqual(self.call("/api/records/" + note, {"version": 1, "evidence_record_id": new, "quote": "目前公开摘录"}, method="PUT").status_code, 200)
        self.assertEqual(self.call("/api/records/" + old, {"version": 1, "visibility": "restricted"}, method="PUT").status_code, 200)
        self.assertIn("目前公开摘录", self.copy(note, "colleague")["text"])
        inaccessible = self.copy(report, "colleague")
        for value in [old, "原采用资料秘密题名", "原采用秘密摘录"]:
            self.assertNotIn(value, json.dumps(inaccessible, ensure_ascii=False))
        self.assertEqual(inaccessible["text"], "暂无可复制的引用。")
        self.assertIn("原采用秘密摘录", self.copy(report, "admin")["text"])

    def test_reading_note_uses_existing_links_shared_editing_and_current_provenance(self):
        original = self.record(title="公开关联原题名", authors="原作者")
        hidden = self.record(title="不应复制的私密关联", visibility="restricted", url="https://example.org/private")
        note = self.record("research_note", title="为何值得读", authors="研究员署名", linked_ids=[original, hidden], body_html="<h2>用途</h2><p>阅读说明<strong>可以复用</strong></p><table><tr><th>限制</th><td>样本小</td></tr></table><script>不应出现脚本内容</script>")
        origin_detail = self.detail(original)
        related = next(r for r in origin_detail["cited_by"] if r["id"] == note)
        self.assertEqual(related["author_name"], "研究员 · 林")
        self.assertEqual(related["evidence_record_id"], "")
        self.assertTrue(self.detail(note, "colleague")["can_edit"])
        self.assertFalse(self.detail(note, "colleague")["can_manage_access"])
        self.assertEqual(self.call("/api/records/" + original, {"version": 1, "title": "关联资料最新题名"}, method="PUT").status_code, 200)
        copied = self.copy(note, "colleague")
        self.assertEqual(copied["mode"], "note")
        for value in ["为何值得读", "研究员署名", "阅读说明可以复用", "样本小", "关联资料最新题名", "当前登记，未固定引用快照"]:
            self.assertIn(value, copied["text"])
        for value in ["<h2>", "<strong>", "<table>", "不应出现脚本内容", hidden, "不应复制的私密关联", "https://example.org/private"]:
            self.assertNotIn(value, copied["text"])
        self.assertEqual(self.call("/api/records", {"kind": "research_note", "title": "正式摘录仍需定位", "evidence_record_id": original, "quote": "引文"}).status_code, 400)

    def test_my_work_requires_confirmed_responsible_author_and_real_update_order(self):
        own = [self.record("research_note", title="本人笔记" + str(i), visibility="restricted" if i == 5 else "shared") for i in range(6)]
        for index, rid in enumerate(own):
            self.fixture_values(rid, updated_at=f"2026-10-23T09:00:0{index}+00:00")
        self.record(title="本人上传原始资料")
        self.record("research_report", title="代交给同事", author_id="colleague")
        self.record("research_report", user="colleague", title="尚未确认由本人负责", author_id="researcher")
        other = self.record("research_note", user="colleague", title="本人有编辑权但不是作者", editors=["researcher"])
        self.assertTrue(self.detail(other)["can_edit"])
        legacy = self.record("research_report", title="历史成果未认领")
        self.fixture_values(legacy, author_id=None, author_confirmed=0)
        result = self.clients["researcher"].get("/api/dashboard").json
        self.assertTrue({"stats", "latest", "activities", "imported"}.issubset(result))
        self.assertEqual([r["id"] for r in result["my_work"]], own[::-1][:4])
        for row in result["my_work"]:
            self.assertEqual(row["author_id"], "researcher")
            self.assertTrue(row["author_confirmed"] and row["can_edit"])
            self.assertIn("reading_access", row)
        self.assertEqual(self.clients["admin"].get("/api/dashboard").json["my_work"], [])

    def test_summary_reading_information_uses_one_attachment_scan_per_request(self):
        for index in range(14):
            self.record(title="列表资料" + str(index))
        queries = []
        def traced_connect(path):
            connection = connect(path)
            connection.set_trace_callback(queries.append)
            return connection
        with patch("platform_app.web.connect", side_effect=traced_connect):
            result = self.clients["researcher"].get("/api/records?size=100")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json["items"]), 14)
        scans = [sql for sql in queries if "FROM ATTACHMENTS" in sql.upper()]
        self.assertLessEqual(len(scans), 1, scans)
        self.assertTrue(all("reading_access" in row and "author_name" in row for row in result.json["items"]))


if __name__ == "__main__":
    unittest.main()
