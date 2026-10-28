"""Collaboration is tested through authenticated HTTP and portable backups."""
import io
import json
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
