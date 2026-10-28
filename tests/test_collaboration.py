"""Collaboration is tested through authenticated HTTP and portable backups."""
import io
import json
import sqlite3
import hashlib
from contextlib import closing
import tempfile
import unittest
import zipfile
from pathlib import Path

from platform_app.web import create_app
from platform_app.maintenance import restore_backup


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="collaboration-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"
        self.app = create_app(self.data_dir, testing=True)
        self.clients = {name: self.login(name) for name in ("researcher", "colleague", "admin")}

    def login(self, name, app=None):
        client = (app or self.app).test_client()
        csrf = client.get("/api/session").json["csrf"]
        result = client.post("/api/login", json={"username": name, "password": "LocalDemo2026!"}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(result.status_code, 200)
        return client

    def call(self, path, data=None, user="researcher", method="POST", file=None):
        client = self.clients[user]
        options = {"headers": {"X-CSRF-Token": client.get("/api/session").json["csrf"]}}
        if file:
            options["data"] = {"data": json.dumps(data or {}), "file": (io.BytesIO(file[1]), file[0])}
        else:
            options["json"] = data or {}
        return client.open(path, method=method, **options)

    def topic(self, participants=None, theme="合成主题"):
        current = self.clients["admin"].get("/api/collaboration/qualifications").json["items"]
        q = next(x for x in current if x["id"] == "researcher")
        if not q["enabled"]:
            self.assertEqual(self.call("/api/collaboration/qualifications/researcher", {"version": q["version"], "enabled": True}, "admin", "PUT").status_code, 200)
        result = self.call("/api/collaboration/topics", {"theme": theme, "participant_ids": participants if participants is not None else ["colleague"]})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json["id"]

    @staticmethod
    def docx(text):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>')
        return output.getvalue()

    def test_only_admin_grants_independent_lead_qualification(self):
        path = "/api/collaboration/qualifications/researcher"
        self.assertEqual(self.call(path, {"version": 0, "enabled": True}, method="PUT").status_code, 403)
        self.assertEqual(self.call("/api/collaboration/topics", {"theme": "合成主题", "participant_ids": ["colleague"]}).status_code, 403)
        granted = self.call(path, {"version": 0, "enabled": True}, user="admin", method="PUT")
        self.assertEqual(granted.status_code, 200, granted.json)
        created = self.call("/api/collaboration/topics", {"theme": "合成主题", "participant_ids": ["colleague"], "due_on": "2026-11-10"})
        self.assertEqual(created.status_code, 201, created.json)
        detail = self.clients["colleague"].get("/api/collaboration/topics/" + created.json["id"])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json["lead_id"], "researcher")
        self.assertEqual(detail.json["due_on"], "2026-11-10")
        self.assertEqual(self.clients["researcher"].get("/api/session").json["user"]["role"], "researcher")
        self.assertEqual(self.call("/api/collaboration/topics", {"theme": "管理员无资格", "participant_ids": []}, user="admin").status_code, 403)

    def test_candidates_are_immutable_versioned_and_idempotent_only_inside_the_topic(self):
        tid, other = self.topic(), self.topic([], "另一主题")
        url = f"/api/collaboration/topics/{tid}/candidates"
        first = self.docx("独立合成候选一")
        payload = {"request_id": "candidate-request-1", "version": 0, "topic_version": 1, "note": "站外材料直接交接", "sharing_confirmed": True}
        result = self.call(url, payload, "colleague", file=("候选一.docx", first))
        self.assertEqual(result.status_code, 201, result.json)
        sid = result.json["id"]
        retry = self.call(url, payload, "colleague", file=("候选一.docx", first))
        self.assertEqual(retry.status_code, 200, retry.json)
        self.assertEqual(retry.json["id"], sid)
        second = self.docx("独立合成候选二")
        payload.update(request_id="candidate-request-2", version=1, note="新说明")
        result2 = self.call(url, payload, "colleague", file=("候选二.docx", second))
        self.assertEqual(result2.status_code, 201, result2.json)
        items = self.clients["researcher"].get(url).json["items"]
        self.assertEqual([x["version"] for x in items], [2, 1])
        self.assertEqual(items[1]["author_id"], "colleague")
        self.assertEqual(items[1]["uploader_id"], "colleague")
        for who in ("researcher", "colleague", "admin"):
            for sub, raw in ((items[0], second), (items[1], first)):
                with self.clients[who].get(sub["file_url"]) as download:
                    self.assertEqual(download.data, raw)
                self.assertEqual(self.call(sub["file_url"], {}, who, "PUT").status_code, 405)
        self.assertEqual(self.clients["colleague"].get(f"/api/collaboration/topics/{other}/candidates/{sid}/file").status_code, 404)
        # Dedicated work files never become generally searchable library records or attachments.
        self.assertEqual(self.clients["admin"].get("/api/records?q=候选").json["total"], 0)
        self.assertEqual(self.clients["colleague"].get("/api/attachments/" + items[1]["file_id"]).status_code, 404)

    def test_full_backup_restores_qualification_membership_and_history_bytes(self):
        tid = self.topic()
        url = f"/api/collaboration/topics/{tid}/candidates"
        originals = [self.docx("备份前原件"), b"%PDF-1.4\nsynthetic-revision"]
        for version, content in enumerate(originals):
            result = self.call(url, {"request_id": f"restore-request-{version}", "version": version, "topic_version": 1, "sharing_confirmed": True}, "colleague", file=("备份.docx" if version == 0 else "修订.pdf", content))
            self.assertEqual(result.status_code, 201, result.json)
        with self.call("/api/backup", user="admin") as response:
            self.assertEqual(response.status_code, 200)
            archive = Path(self.temp.name) / "backup.zip"
            archive.write_bytes(response.data)
        target = Path(self.temp.name) / "restored"
        restore_backup(archive, target)
        restored_app = create_app(target, testing=True)
        colleague = self.login("colleague", restored_app)
        self.assertEqual(colleague.get(f"/api/collaboration/topics/{tid}").json["participants"][0]["active"], 1)
        versions = colleague.get(url).json["items"]
        for item, expected in zip(versions, reversed(originals)):
            with colleague.get(item["file_url"]) as download:
                self.assertEqual(download.data, expected)
        admin = self.login("admin", restored_app)
        self.assertEqual(next(q for q in admin.get("/api/collaboration/qualifications").json["items"] if q["id"] == "researcher")["enabled"], 1)

    def test_candidate_export_is_scoped_and_contains_original_versions(self):
        tid = self.topic()
        raw = self.docx("导出的独立原件")
        uploaded = self.call(f"/api/collaboration/topics/{tid}/candidates", {"request_id": "export-request-1", "version": 0, "topic_version": 1, "note": "仅本期", "sharing_confirmed": True}, file=("候选报告.docx", raw))
        self.assertEqual(uploaded.status_code, 201)
        with self.clients["colleague"].get(f"/api/collaboration/topics/{tid}/candidates/export") as response:
            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["topic"]["id"], tid)
                self.assertEqual(len(manifest["submissions"]), 1)
                self.assertEqual(archive.read(manifest["submissions"][0]["path"]), raw)
        other = self.topic([])
        self.assertEqual(self.clients["colleague"].get(f"/api/collaboration/topics/{other}/candidates/export").status_code, 404)

    def test_restore_rejects_forged_request_fingerprint_even_with_rewritten_archive_hashes(self):
        tid = self.topic()
        self.assertEqual(self.call(f"/api/collaboration/topics/{tid}/candidates", {"request_id": "tamper-request-1", "version": 0, "topic_version": 1, "note": "原说明", "sharing_confirmed": True}, file=("原件.txt", b"original")).status_code, 201)
        with self.call("/api/backup", user="admin") as response:
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                files = {name: archive.read(name) for name in archive.namelist()}
        database = Path(self.temp.name) / "tampered.sqlite3"
        database.write_bytes(files["platform.sqlite3"])
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("UPDATE topic_candidates SET request_hash=?", ("0" * 64,))
        files["platform.sqlite3"] = database.read_bytes()
        manifest = json.loads(files["manifest.json"])
        manifest["files"]["platform.sqlite3"] = {"bytes": len(files["platform.sqlite3"]), "sha256": hashlib.sha256(files["platform.sqlite3"]).hexdigest()}
        files["manifest.json"] = json.dumps(manifest).encode()
        corrupt = Path(self.temp.name) / "corrupt.zip"
        with zipfile.ZipFile(corrupt, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        target = Path(self.temp.name) / "must-not-be-published"
        with self.assertRaises(ValueError):
            restore_backup(corrupt, target)
        self.assertFalse(target.exists())

    def test_current_membership_revocation_disabled_accounts_and_maintenance_access(self):
        tid = self.topic()
        url = f"/api/collaboration/topics/{tid}"
        submitted = self.call(url + "/candidates", {"request_id": "permission-request-1", "version": 0, "topic_version": 1}, "colleague", file=("选题.docx", self.docx("权限样本")))
        self.assertEqual(submitted.status_code, 201, submitted.json)
        file_url = self.clients["colleague"].get(url + "/candidates").json["items"][0]["file_url"]
        created = self.call("/api/members", {"username": "outside", "name": "未参与成员", "password": "LocalDemo2026!", "role": "researcher"}, "admin")
        self.assertEqual(created.status_code, 201, created.json)
        self.clients["outside"] = self.login("outside")
        for suffix in ("", "/history", "/candidates", "/candidates/export"):
            self.assertEqual(self.clients["outside"].get(url + suffix).status_code, 404)
        self.assertEqual(self.clients["outside"].get(file_url).status_code, 404)
        self.assertEqual(self.clients["outside"].get("/api/collaboration/topics").json["items"], [])
        self.assertEqual(self.call(url, {"version": 1, "theme": "越权", "participant_ids": []}, "admin", "PUT").status_code, 403)
        # Removing access preserves the contribution, while every direct history/file path rechecks membership.
        self.assertEqual(self.call(url, {"version": 1, "theme": "调整参与者", "participant_ids": []}, method="PUT").status_code, 200)
        for suffix in ("", "/history", "/candidates", "/candidates/export"):
            self.assertEqual(self.clients["colleague"].get(url + suffix).status_code, 404)
        self.assertEqual(self.clients["colleague"].get(file_url).status_code, 404)
        self.assertEqual(len(self.clients["admin"].get(url + "/candidates").json["items"]), 1)
        self.assertEqual(len(self.clients["admin"].get(url + "/history").json["items"]), 2)
        self.assertEqual(self.call("/api/collaboration/qualifications/researcher", {"version": 1, "enabled": False}, "admin", "PUT").status_code, 200)
        self.assertFalse(self.clients["researcher"].get(url).json["can_manage"])
        self.assertEqual(self.call(url, {"version": 2, "theme": "撤销后维护", "participant_ids": []}, method="PUT").status_code, 403)
        self.assertEqual(self.call("/api/collaboration/topics", {"theme": "撤销后开期", "participant_ids": []}).status_code, 403)
        self.assertEqual(self.call("/api/members/researcher", {"active": False}, "admin", "PUT").status_code, 200)
        self.assertEqual(self.clients["researcher"].get(file_url).status_code, 401)
        self.assertEqual(self.clients["admin"].get(url).status_code, 200)

    def test_stale_versions_request_collision_invalid_files_and_separate_authored_body(self):
        tid = self.topic()
        url = f"/api/collaboration/topics/{tid}"
        payload = {"request_id": "conflict-request-1", "version": 0, "topic_version": 1, "note": "保留说明"}
        self.assertEqual(self.call(url + "/candidates", payload, "colleague", file=("候选.docx", self.docx("初稿"))).status_code, 201)
        self.assertEqual(self.call(url + "/candidates", payload, "colleague", file=("候选.docx", self.docx("不同字节"))).status_code, 409)
        payload["request_id"] = "conflict-request-2"
        self.assertEqual(self.call(url + "/candidates", payload, "colleague", file=("候选.docx", self.docx("过期"))).status_code, 409)
        self.assertEqual(self.call(url, {"version": 1, "theme": "更新主题", "participant_ids": ["colleague"]}, method="PUT").status_code, 200)
        self.assertEqual(self.call(url, {"version": 1, "theme": "过期主题", "participant_ids": []}, method="PUT").status_code, 409)
        payload["version"] = 1
        self.assertEqual(self.call(url + "/candidates", payload, "colleague", file=("候选.docx", self.docx("旧期信息"))).status_code, 409)
        payload["topic_version"] = 2
        for filename, content in (("恶意.exe", b"binary"), ("伪装.docx", b"not a docx"), ("伪装.pdf", b"not a pdf"), ("空.txt", b""), ("错误.txt", b"\xff"), ("过大.txt", b"a" * (20 * 1024 * 1024 + 1))):
            self.assertEqual(self.call(url + "/candidates", payload, "colleague", file=(filename, content)).status_code, 400, filename)
        self.assertEqual(len(self.clients["researcher"].get(url + "/candidates").json["items"]), 1)
        report = self.call("/api/records", {"kind": "compilation", "title": "独立作者正文", "body_html": "<p>作者原文</p>", "visibility": "restricted"}, "colleague").json["id"]
        for who in ("researcher", "admin"):
            self.assertIn(self.call("/api/records/" + report, {"version": 1, "body_html": "越权改稿"}, who, "PUT").status_code, (403, 404))
            self.assertIn(self.clients[who].get("/api/history/record/" + report).status_code, (403, 404))

    def test_late_storage_failure_leaves_neither_half_submission_nor_orphan_file(self):
        tid = self.topic()
        url = f"/api/collaboration/topics/{tid}/candidates"
        first = self.docx("成功原件")
        payload = {"request_id": "rollback-request-1", "version": 0, "topic_version": 1}
        self.assertEqual(self.call(url, payload, file=("原件.docx", first)).status_code, 201)
        original = self.clients["colleague"].get(url).json["items"][0]
        # Inject a failure at the durable database boundary, after the file has been written.
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db, db:
            db.execute("CREATE TRIGGER reject_synthetic_candidate BEFORE INSERT ON topic_candidates BEGIN SELECT RAISE(ABORT,'synthetic late failure'); END")
        payload.update(request_id="rollback-request-2", version=1)
        self.assertEqual(self.call(url, payload, file=("失败.docx", self.docx("失败原件"))).status_code, 409)
        self.assertEqual(len(self.clients["colleague"].get(url).json["items"]), 1)
        with self.clients["colleague"].get(original["file_url"]) as response:
            self.assertEqual(response.data, first)
        # Independent filesystem inventory catches leaked files omitted from an export.
        self.assertEqual(len(list((self.data_dir / "handoffs").iterdir())), 1)
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db, db:
            db.execute("DROP TRIGGER reject_synthetic_candidate")
        self.assertEqual(self.call(url, payload, file=("恢复.docx", self.docx("成功重试"))).status_code, 201)

    def test_unavailable_file_storage_reports_retryable_failure_without_half_submission(self):
        tid = self.topic()
        path = self.data_dir / "handoffs"
        path.write_bytes(b"synthetic blocked directory")
        payload = {"request_id": "disk-failure-request", "version": 0, "topic_version": 1}
        result = self.call(f"/api/collaboration/topics/{tid}/candidates", payload, file=("报告.txt", b"synthetic"))
        self.assertEqual(result.status_code, 503)
        self.assertIn("重试", result.json["error"])
        self.assertEqual(self.clients["researcher"].get(f"/api/collaboration/topics/{tid}/candidates").json["items"], [])
        path.unlink()
        self.assertEqual(self.call(f"/api/collaboration/topics/{tid}/candidates", payload, file=("报告.txt", b"synthetic")).status_code, 201)
