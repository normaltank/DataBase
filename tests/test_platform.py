import csv
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from platform_app.importer import DEFAULT_ROOT, FILES, import_thinktank
from platform_app.maintenance import create_backup, restore_backup
from platform_app.store import connect
from platform_app.web import create_app


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="research-platform-test-")
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"
        self.app = create_app(self.data_dir, testing=True)
        self.clients = {u: self.login(u) for u in ["admin", "researcher", "colleague"]}

    def login(self, uid, app=None):
        c = (app or self.app).test_client()
        token = c.get("/api/session").json["csrf"]
        r = c.post("/api/login", json={"username": uid, "password": "LocalDemo2026!"}, headers={"X-CSRF-Token": token})
        self.assertEqual(r.status_code, 200)
        return c

    def call(self, uid, path, payload=None, method="POST", file=None):
        c = self.clients[uid]
        token = c.get("/api/session").json["csrf"]
        kwargs = {"headers": {"X-CSRF-Token": token}}
        if file:
            kwargs["data"] = {"data": json.dumps(payload), "file": (io.BytesIO(file[1]), file[0])}
        else:
            kwargs["json"] = payload or {}
        return c.open(path, method=method, **kwargs)

    def record(self, uid="researcher", **kwargs):
        r = self.call(uid, "/api/records", dict(title="测试资料", kind="report", **kwargs))
        self.assertEqual(r.status_code, 201, r.json)
        return r.json["id"]

    def detail(self, rid, uid="researcher"):
        r = self.clients[uid].get("/api/records/" + rid)
        self.assertEqual(r.status_code, 200, r.json)
        return r.json

    def test_authentication_csrf_host_and_origin(self):
        c = self.app.test_client()
        for url in ["/api/records", "/api/sources", "/api/export", "/api/dashboard", "/api/users"]:
            self.assertEqual(c.get(url).status_code, 401)
        self.assertEqual(c.post("/api/login", json={}).status_code, 403)
        token = c.get("/api/session").json["csrf"]
        self.assertEqual(c.post("/api/login", json={}, headers={"X-CSRF-Token": token, "Origin": "https://other.test"}).status_code, 403)
        self.assertEqual(c.get("/health", headers={"Host": "evil.test"}).status_code, 400)
        response = self.clients["admin"].get("/")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])

    def test_shared_submission_editing_and_review(self):
        rid = self.record()
        self.assertEqual(self.detail(rid, "colleague")["status"], "pending")
        self.assertEqual(self.call("colleague", "/api/records/" + rid, {"title": "不允许修改", "version": 1}, "PUT").status_code, 403)
        self.assertEqual(self.call("researcher", "/api/review/record/" + rid, {"version": 1}).status_code, 403)
        self.assertEqual(self.call("admin", "/api/review/record/" + rid, {"version": 1}).status_code, 200)
        self.assertEqual(self.detail(rid)["status"], "verified")
        self.assertEqual(self.call("researcher", "/api/records/" + rid, {"title": "修订题名", "version": 2}, "PUT").status_code, 200)
        self.assertEqual(self.detail(rid)["status"], "pending")
        self.assertEqual(self.call("researcher", "/api/records/" + rid, {"title": "过期覆盖", "version": 2}, "PUT").status_code, 409)

    def test_restricted_content_every_surface(self):
        response = self.call("researcher", "/api/records", {"title": "机密试验标题", "kind": "compilation", "visibility": "restricted", "sharing_confirmed": True}, file=("受限.txt", b"private test content"))
        self.assertEqual(response.status_code, 201)
        rid = response.json["id"]
        aid = self.detail(rid)["attachments"][0]["id"]
        c = self.clients["colleague"]
        for url in ["/api/records/"+rid, "/api/attachments/"+aid]:
            self.assertEqual(c.get(url).status_code, 404)
        self.assertEqual(c.get("/api/history/record/"+rid).status_code, 404)
        self.assertEqual(c.get("/api/records").json["total"], 0)
        self.assertEqual(c.get("/api/dashboard").json["stats"]["records"], 0)
        self.assertNotIn("机密试验标题", c.get("/api/export").data.decode("utf-8-sig"))
        col = self.call("researcher", "/api/collections", {"name": "共享试验专题", "visibility": "shared"}).json["id"]
        self.call("researcher", f"/api/collections/{col}/items", {"record_id": rid})
        self.assertEqual(c.get("/api/collections").json["items"][0]["count"], 0)
        self.assertEqual(c.get("/api/records?collection="+col).json["total"], 0)
        with self.clients["admin"].get("/api/attachments/"+aid) as download:
            self.assertEqual(download.data, b"private test content")

    def test_authorized_editors_cannot_widen_acl(self):
        rid = self.record(visibility="restricted", editors=["colleague"])
        self.assertEqual(self.detail(rid, "colleague")["title"], "测试资料")
        response = self.call("colleague", "/api/records/"+rid, {"version": 1, "title": "共同修订"}, "PUT")
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.call("colleague", "/api/records/"+rid, {"version": 2, "visibility": "shared"}, "PUT").status_code, 403)
        self.assertEqual(self.call("colleague", "/api/records/"+rid, {"version": 2, "editors": []}, "PUT").status_code, 403)

    def test_many_to_many_links_and_hidden_reference_export(self):
        a = self.record()
        b = self.record(visibility="restricted")
        reports = []
        for title in ["成果甲", "成果乙"]:
            r = self.call("researcher", "/api/records", {"title": title, "kind": "compilation", "linked_ids": [a,b], "unresolved_refs": "https://example.org/other"})
            self.assertEqual(r.status_code, 201, r.json)
            reports.append(r.json["id"])
        self.assertEqual(len(self.detail(a)["cited_by"]), 2)
        self.assertEqual(len(self.detail(reports[0])["linked_records"]), 2)
        self.assertEqual(len(self.detail(reports[0], "colleague")["linked_records"]), 1)
        output = self.clients["colleague"].get("/api/export")
        self.assertEqual(output.status_code, 200)
        self.assertNotIn(b, output.data.decode("utf-8-sig"))
        self.assertEqual(self.call("researcher", "/api/records", {"title": "循环", "kind": "compilation", "linked_ids": [reports[0]]}).status_code, 400)

    def test_revision_restore_keeps_current_permissions(self):
        rid = self.record()
        self.call("researcher", "/api/records/"+rid, {"title": "新版本", "visibility": "restricted", "version": 1}, "PUT")
        h = self.clients["researcher"].get("/api/history/record/"+rid).json["items"]
        self.assertEqual(len(h), 2)
        response = self.call("researcher", f"/api/history/{h[-1]['id']}/restore", {"version": 2})
        self.assertEqual(response.status_code, 200, response.json)
        current = self.detail(rid)
        self.assertEqual((current["title"],current["version"],current["visibility"],current["status"]), ("测试资料",3,"restricted","pending"))
        self.assertEqual(self.clients["colleague"].get("/api/records/"+rid).status_code, 404)

    def test_source_collaboration_and_admin_restore(self):
        s = self.call("researcher", "/api/sources", {"name": "测试来源", "kind": "think_tank", "website": "https://example.org"})
        self.assertEqual(s.status_code, 201)
        sid = s.json["id"]
        self.assertEqual(self.call("colleague", "/api/sources/"+sid, {"version": 1, "name": "共同维护的来源"}, "PUT").status_code, 200)
        self.assertEqual(self.call("admin", "/api/review/source/"+sid, {"version": 2}).status_code, 200)
        history = self.clients["researcher"].get("/api/history/source/"+sid).json["items"]
        self.assertEqual(self.call("researcher", f"/api/history/{history[-1]['id']}/restore", {"version": 3}).status_code, 403)
        self.assertEqual(self.call("admin", f"/api/history/{history[-1]['id']}/restore", {"version": 3}).status_code, 200)
        self.assertEqual(self.clients["colleague"].get("/api/sources/"+sid).json["name"], "测试来源")

    def test_collections_and_favorites_are_personal(self):
        rid = self.record()
        cid = self.call("researcher", "/api/collections", {"name": "个人专题", "visibility": "private"}).json["id"]
        self.assertEqual(self.call("researcher", f"/api/collections/{cid}/items", {"record_id": rid}).status_code, 200)
        self.assertEqual(self.clients["researcher"].get("/api/records?collection="+cid).json["total"], 1)
        self.assertEqual(self.clients["colleague"].get("/api/collections").json["items"], [])
        self.assertEqual(self.clients["colleague"].get("/api/export?collection="+cid).status_code, 404)
        self.call("researcher", "/api/favorites/"+rid, {"saved": True})
        self.call("researcher", "/api/favorites/"+rid, {"saved": True})
        self.assertEqual(self.clients["researcher"].get("/api/records?favorite=1").json["total"], 1)
        self.assertEqual(self.clients["colleague"].get("/api/records?favorite=1").json["total"], 0)
        self.call("researcher", f"/api/collections/{cid}/items", {"record_id": rid, "remove": True})
        self.assertEqual(self.clients["researcher"].get("/api/records?collection="+cid).json["total"], 0)

    def test_combined_search_and_csv_injection_protection(self):
        self.call("researcher", "/api/records", {"title": "=敏感公式样本", "kind": "report", "authors": "测试作者", "countries": "拉脱维亚; 爱沙尼亚", "language": "zh", "published_on": "2026-10-10", "keywords": "语言政策"})
        query = "q=测试作者&country=拉脱维亚&language=zh&from=2026-10-01&to=2026-10-15"
        self.assertEqual(self.clients["colleague"].get("/api/records?"+query).json["total"], 1)
        text = self.clients["colleague"].get("/api/export?"+query).data.decode("utf-8-sig")
        self.assertEqual(list(csv.reader(io.StringIO(text)))[1][1], "'=敏感公式样本")
        self.assertEqual(self.clients["colleague"].get("/api/records?country=德国").json["total"], 0)

    def test_upload_validation_and_path_safety(self):
        payload = {"title": "附件测试", "kind": "report", "sharing_confirmed": True}
        bad = self.call("researcher", "/api/records", payload, file=("attack.html", b"<script>alert(1)</script>"))
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.clients["admin"].get("/api/records").json["total"], 0)
        for name,content in [("fake.pdf", b"not a pdf"), ("fake.docx", b"not a zip"), ("blank.txt", b"")]:
            self.assertEqual(self.call("researcher", "/api/records", payload, file=(name,content)).status_code, 400)
        r = self.call("researcher", "/api/records", payload, file=("../../中文附件.txt", "可共享的测试文本".encode()))
        self.assertEqual(r.status_code, 201, r.json)
        a = self.detail(r.json["id"])["attachments"][0]
        self.assertEqual(a["name"], "中文附件.txt")
        with self.clients["colleague"].get("/api/attachments/"+a["id"]) as download:
            self.assertEqual(download.data, "可共享的测试文本".encode())
        self.assertFalse((Path(self.temp.name) / "中文附件.txt").exists())
        payload["sharing_confirmed"] = False
        self.assertEqual(self.call("researcher", "/api/records", payload, file=("x.txt", b"x")).status_code, 400)

    def test_attachment_versions_restore(self):
        payload = {"title": "附件版本", "kind": "report", "sharing_confirmed": True}
        rid = self.call("researcher", "/api/records", payload, file=("一.txt", b"one")).json["id"]
        first = self.detail(rid)["attachments"][0]["id"]
        self.call("researcher", "/api/records/"+rid, {"version": 1, "sharing_confirmed": True}, "PUT", file=("二.txt", b"two"))
        attachments = self.detail(rid)["attachments"]
        self.assertEqual(len(attachments), 2)
        second = next(a["id"] for a in attachments if a["id"] != first)
        revision = self.clients["researcher"].get("/api/history/record/"+rid).json["items"][-1]["id"]
        self.call("researcher", f"/api/history/{revision}/restore", {"version": 2})
        self.assertEqual(len(self.detail(rid)["attachments"]), 1)
        self.assertEqual(self.clients["researcher"].get("/api/attachments/"+second).status_code, 404)

    def test_attachment_insert_failure_cleans_new_record_and_upload(self):
        original = self.record()
        original_before = self.detail(original)
        db = connect(self.data_dir / "platform.sqlite3")
        try:
            with db:
                db.execute("CREATE TRIGGER refuse_upload BEFORE INSERT ON attachments BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END")
        finally:
            db.close()
        failed = self.call("researcher", "/api/records",
                           {"title": "未完成的上传", "kind": "compilation", "linked_ids": [original], "sharing_confirmed": True},
                           file=("失败附件.txt", b"must be removed"))
        self.assertEqual(failed.status_code, 409, failed.json)
        self.assertEqual(self.clients["researcher"].get("/api/records").json["total"], 1)
        self.assertEqual(self.detail(original), original_before)
        self.assertEqual(list((self.data_dir / "uploads").iterdir()), [])

    def test_duplicates_and_malformed_inputs(self):
        self.record(doi="10.1234/test")
        self.assertEqual(self.call("colleague", "/api/records", {"title": "重复", "doi": "10.1234/TEST"}).status_code, 409)
        for bad in [{"title": ""}, {"title": "x", "url": "javascript:alert(1)"}, {"title": "x", "editors": "admin"}, {"title": "x", "kind": "arbitrary"}, {"title": "x", "published_on": "2026-02-30"}]:
            self.assertEqual(self.call("researcher", "/api/records", bad).status_code, 400)
        self.call("researcher", "/api/sources", {"name": "唯一来源", "kind": "institution"})
        self.assertEqual(self.call("colleague", "/api/sources", {"name": "唯一来源", "kind": "institution"}).status_code, 409)

    def test_multilingual_search_and_linked_original_type(self):
        rid = self.record(language="lv; en")
        self.assertEqual(self.clients["colleague"].get("/api/records?language=en").json["total"], 1)
        self.assertEqual(self.clients["colleague"].get("/api/records?language=lv").json["total"], 1)
        self.call("researcher", "/api/records", {"title": "引用成果", "kind": "compilation", "linked_ids": [rid]})
        self.assertEqual(self.call("researcher", "/api/records/"+rid, {"version": 1, "kind": "compilation"}, "PUT").status_code, 409)

    def test_joint_hosts_are_visible_from_both_institutions(self):
        ids = []
        for name in ["机构甲", "机构乙"]:
            response = self.call("researcher", "/api/sources", {"name": name, "kind": "institution"})
            self.assertEqual(response.status_code, 201, response.json)
            ids.append(response.json["id"])
        serial = self.call("researcher", "/api/sources", {"name": "联合期刊", "kind": "journal", "host_id": " | ".join(ids)})
        self.assertEqual(serial.status_code, 201)
        sid = serial.json["id"]
        detail = self.clients["colleague"].get("/api/sources/"+sid).json
        self.assertEqual({s["id"] for s in detail["institutions"]}, set(ids))
        for parent in ids:
            self.assertIn(sid, [s["id"] for s in self.clients["colleague"].get("/api/sources/"+parent).json["related"]])

    def test_restore_old_type_preserves_current_personal_responsibility(self):
        rid = self.record()
        history_url = "/api/history/record/" + rid
        revision = self.clients["researcher"].get(history_url).json["items"][-1]["id"]
        changed = self.call("researcher", "/api/records/" + rid,
                            {"version": 1, "kind": "compilation"}, "PUT")
        self.assertEqual(changed.status_code, 200, changed.json)
        before = self.detail(rid)
        history_before = self.clients["researcher"].get(history_url).json
        self.assertEqual(before["kind"], "compilation")
        self.assertEqual(before["author_id"], "researcher")
        restored = self.call("researcher", f"/api/history/{revision}/restore", {"version": before["version"]})
        self.assertEqual(restored.status_code, 409, restored.json)
        self.assertEqual(restored.json["error"], "历史类型不符合当前维护责任，请手工修订内容。")
        self.assertEqual(self.detail(rid), before)
        self.assertEqual(self.clients["researcher"].get(history_url).json, history_before)

    def test_legacy_content_snapshot_cannot_restore_over_referenced_original(self):
        # Compatibility fixture: current clients cannot create this historical type transition.
        for reference in ["linked_ids", "evidence_record_id"]:
            with self.subTest(reference=reference):
                rid = self.record()
                history_url = "/api/history/record/" + rid
                revision = self.clients["researcher"].get(history_url).json["items"][-1]["id"]
                snapshot = self.clients["researcher"].get(f"/api/history/{revision}").json["snapshot"]
                snapshot["kind"] = "compilation"
                db = connect(self.data_dir / "platform.sqlite3")
                try:
                    with db:
                        db.execute("UPDATE revisions SET snapshot_json=? WHERE id=?", (json.dumps(snapshot), revision))
                finally:
                    db.close()
                payload = {"title": "引用旧状态的原文", "kind": "compilation", "linked_ids": [rid]}
                if reference == "evidence_record_id":
                    payload = {"title": "摘录旧状态的原文", "kind": "research_note", "evidence_record_id": rid,
                               "quote": "原文观点", "locator": "第 3 页"}
                created = self.call("researcher", "/api/records", payload)
                self.assertEqual(created.status_code, 201, created.json)
                before = self.detail(rid)
                dependent_before = self.detail(created.json["id"])
                history_before = self.clients["researcher"].get(history_url).json
                restored = self.call("researcher", f"/api/history/{revision}/restore", {"version": before["version"]})
                self.assertEqual(restored.status_code, 409, restored.json)
                self.assertEqual(restored.json["error"], "此资料现已被成果或摘录引用，不能恢复为研究内容类型。")
                self.assertEqual(self.detail(rid), before)
                self.assertEqual(self.detail(created.json["id"]), dependent_before)
                self.assertEqual(self.clients["researcher"].get(history_url).json, history_before)

    def test_persistence_after_application_restart(self):
        rid = self.record()
        restarted = create_app(self.data_dir, testing=True)
        c = self.login("researcher", restarted)
        self.assertEqual(c.get("/api/records/"+rid).json["title"], "测试资料")
        self.assertEqual(c.get("/api/history/record/"+rid).json["items"][0]["version"], 1)

    def test_backup_restore_preserves_database_relations_and_files(self):
        rid = self.record()
        self.call("researcher", "/api/records", {"title": "备份成果", "kind": "compilation", "linked_ids": [rid], "sharing_confirmed": True}, file=("研究成果.md", b"# Test backup"))
        self.assertEqual(self.call("researcher", "/api/backup").status_code, 403)
        backup = create_backup(self.data_dir)
        restored = restore_backup(backup, Path(self.temp.name) / "restored")
        a,b = connect(self.data_dir/"platform.sqlite3"), connect(restored/"platform.sqlite3")
        try:
            for table in ["records", "users", "record_links", "attachments", "revisions"]:
                self.assertEqual([tuple(r) for r in a.execute(f"SELECT * FROM {table}")], [tuple(r) for r in b.execute(f"SELECT * FROM {table}")])
        finally:
            a.close(); b.close()
        self.assertEqual(next((restored/"uploads").iterdir()).read_bytes(), b"# Test backup")
        with self.assertRaises(ValueError):
            restore_backup(backup, restored)

    def test_restore_rejects_path_traversal_and_tampering(self):
        backup = create_backup(self.data_dir)
        unsafe = Path(self.temp.name)/"unsafe.zip"
        with zipfile.ZipFile(unsafe, "w") as z:
            z.writestr("../escape", "bad")
        with self.assertRaises(ValueError):
            restore_backup(unsafe, Path(self.temp.name)/"unsafe-output")
        tampered = Path(self.temp.name)/"tampered.zip"
        with zipfile.ZipFile(backup) as original, zipfile.ZipFile(tampered,"w") as dest:
            for name in original.namelist():
                content = original.read(name)
                if name == "platform.sqlite3": content += b"bad"
                dest.writestr(name,content)
        with self.assertRaises(ValueError):
            restore_backup(tampered, Path(self.temp.name)/"tampered-output")

    @unittest.skipUnless(os.environ.get("RUN_THINKTANK_IMPORT_TEST") == "1", "External ThinkTank test requires explicit opt-in")
    def test_real_import_is_idempotent_and_read_only(self):
        if not DEFAULT_ROOT.is_dir():
            self.skipTest("External ThinkTank dataset unavailable")
        before = {name: hashlib.sha256((DEFAULT_ROOT/name).read_bytes()).hexdigest() for name in FILES}
        result = import_thinktank(self.data_dir)
        self.assertEqual((result["records"],result["source_rows"],result["serial_rows"]), (493,64,79))
        self.assertEqual(len(result["skipped"]), 3)
        c = connect(self.data_dir/"platform.sqlite3")
        with c: c.execute("UPDATE sources SET name='人工修订测试' WHERE id='SRC-PROVIDUS'")
        self.assertTrue(import_thinktank(self.data_dir)["already_imported"])
        self.assertEqual(c.execute("SELECT name FROM sources WHERE id='SRC-PROVIDUS'").fetchone()[0], "人工修订测试")
        self.assertEqual(c.execute("SELECT kind FROM sources WHERE id='SRC-RTU-REZEKNE'").fetchone()[0], "institution")
        self.assertEqual(c.execute("SELECT COUNT(*) FROM records WHERE countries<>''").fetchone()[0], 0)
        self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
        c.close()
        self.assertEqual(before, {name: hashlib.sha256((DEFAULT_ROOT/name).read_bytes()).hexdigest() for name in FILES})
        self.assertEqual(list((self.data_dir/"uploads").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
