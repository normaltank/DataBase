"""Exact final decisions and immutable issue adoptions at authenticated HTTP."""
import io
import json
import zipfile
import unittest
import sqlite3
import hashlib
from contextlib import closing

from tests import test_topic_review as base


class TopicFinalTests(unittest.TestCase):
    setUp = base.TopicReviewTests.setUp
    login = base.TopicReviewTests.login
    call = base.TopicReviewTests.call
    topic = base.TopicReviewTests.topic
    docx = staticmethod(base.TopicReviewTests.docx)
    meeting = base.TopicReviewTests.meeting
    draft = base.TopicReviewTests.draft
    workflow = base.TopicReviewTests.workflow
    returned = base.TopicReviewTests.returned

    def ready(self):
        tid = self.topic()
        self.assertEqual(self.meeting(tid).status_code, 201)
        aid = self.workflow(tid)["assignments"][0]["id"]
        sid = self.draft(tid, aid, file=("original.txt", b"independent final original")).json["id"]
        return tid, aid, sid

    def final(self, tid, aid, sid, who="researcher", **extra):
        return self.call(f"/api/collaboration/topics/{tid}/assignments/{aid}/finals", {
            "request_id": "final-request-one", "topic_version": 1, "meeting_version": 1,
            "submission_id": sid, "version": 1, "status": "pending", "note": "已核对所据原件", **extra}, who)

    def test_final_binds_current_version_and_creates_existing_author_controlled_identity(self):
        tid, aid, sid = self.ready()
        for who in ("admin", "colleague"):
            self.assertEqual(self.final(tid, aid, sid, who).status_code, 403)
        result = self.final(tid, aid, sid)
        self.assertEqual(result.status_code, 201, result.json)
        rid = result.json["record_id"]
        record = self.clients["colleague"].get("/api/records/" + rid).json
        self.assertEqual((record["kind"], record["author_id"], record["owner_id"], record["author_confirmed"]), ("compilation", "colleague", "researcher", 0))
        self.assertFalse(record["can_edit"])
        self.assertEqual(record["editors"], [])
        self.assertEqual(self.final(tid, aid, sid).status_code, 200)
        a = self.workflow(tid)["assignments"][0]
        self.assertEqual(a["status"], "final")
        self.assertEqual(a["finals"][0]["submission_id"], sid)
        self.assertEqual(a["finals"][0]["actor_id"], "researcher")
        with self.clients["colleague"].get(a["finals"][0]["file_url"]) as response:
            self.assertEqual(response.data, b"independent final original")
        self.assertEqual(self.draft(tid, aid, version=1).status_code, 201)
        self.assertEqual(self.workflow(tid)["assignments"][0]["status"], "pending")
        self.assertEqual(self.final(tid, aid, sid, request_id="stale-final-request").status_code, 409)

    def summary(self, tid, finals, who="researcher", **extra):
        file = extra.pop("file", ("issue.txt", b"actual assembled issue original"))
        return self.call(f"/api/collaboration/topics/{tid}/summaries", {
            "request_id": "summary-request-one", "topic_version": 1, "version": 0,
            "author_id": "colleague", "final_ids": finals, "note": "本机合稿，采用所选各篇定稿", **extra}, who, file=file)

    def test_summary_keeps_exact_adoptions_through_replacement_export_and_restore(self):
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        tid, aid, sid = self.ready()
        final = self.final(tid, aid, sid).json
        result = self.summary(tid, [final["id"]])
        self.assertEqual(result.status_code, 201, result.json)
        self.assertEqual(self.summary(tid, [final["id"]]).status_code, 200)
        rid = result.json["record_id"]
        before = self.workflow(tid)
        self.assertEqual(before["summaries"][0]["adoptions"][0]["submission_id"], sid)
        self.assertEqual(self.draft(tid, aid, version=1).status_code, 201)
        current = self.workflow(tid)
        self.assertEqual(current["assignments"][0]["status"], "pending")
        self.assertEqual(current["summaries"], before["summaries"])
        with self.clients["researcher"].get(f"/api/collaboration/topics/{tid}/materials/export") as response:
            with zipfile.ZipFile(io.BytesIO(response.data)) as pack:
                manifest = json.loads(pack.read("manifest.json"))
                self.assertEqual(manifest["workflow"]["summaries"][0]["adoptions"][0]["submission_id"], sid)
                self.assertIn(b"actual assembled issue original", [pack.read(f["path"]) for f in manifest["files"]])
        with self.clients["colleague"].get("/api/export/content?ids=" + rid) as response:
            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(response.data)) as pack:
                payload = json.loads(pack.read("content.json"))
                work = next(r for r in payload["records"] if r["id"] == rid)["collaboration_works"][0]
                self.assertEqual(work["adoptions"][0]["submission_id"], sid)
                self.assertEqual(pack.read(work["path"]), b"actual assembled issue original")
        backup_path = self.data_dir.parent / "backup.zip"
        with self.call("/api/backup", user="admin") as backup:
            self.assertEqual(backup.status_code, 200)
            backup_path.write_bytes(backup.data)
        restored_dir = self.data_dir.parent / "restored"
        restore_backup(backup_path, restored_dir)
        restored = self.login("colleague", create_app(restored_dir, testing=True))
        self.assertEqual(restored.get(f"/api/collaboration/topics/{tid}/workflow").json, current)
        with restored.get(current["summaries"][0]["file_url"]) as response:
            self.assertEqual(response.data, b"actual assembled issue original")

    def test_linking_shared_record_does_not_publish_topic_original_or_change_old_author_acl(self):
        tid, aid, sid = self.ready()
        old = self.call("/api/records", {"kind": "compilation", "title": "既有共享成果", "body_html": "<p>作者既有正文</p>", "visibility": "shared", "sharing_confirmed": True}, "colleague", file=("旧合法附件.txt", b"old legitimately shared attachment"))
        self.assertEqual(old.status_code, 201, old.json)
        rid = old.json["id"]
        before = self.clients["colleague"].get("/api/records/" + rid).json
        result = self.final(tid, aid, sid, record_id=rid, record_version=1)
        self.assertEqual(result.status_code, 201, result.json)
        after = self.clients["colleague"].get("/api/records/" + rid).json
        for key in ("body_html", "attachment_ids", "visibility", "author_id", "author_confirmed", "editors", "version", "owner_id"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(self.call("/api/records/" + rid, {"version": 1, "body_html": "<p>负责人越权</p>"}, method="PUT").status_code, 403)
        self.assertEqual(self.call("/api/members", {"username": "outside", "name": "非参与成员", "password": "LocalDemo2026!", "role": "researcher"}, "admin").status_code, 201)
        self.clients["outside"] = self.login("outside")
        readable = self.clients["outside"].get("/api/records/" + rid).json
        self.assertEqual(readable["body_html"], "<p>作者既有正文</p>")
        self.assertEqual(readable.get("collaboration_works", []), [])
        final_url = after["collaboration_works"][0]["file_url"]
        self.assertEqual(self.clients["outside"].get(final_url).status_code, 404)
        with self.clients["outside"].get("/api/attachments/" + before["attachment_ids"][0]) as response:
            self.assertEqual(response.data, b"old legitimately shared attachment")
        with self.clients["outside"].get("/api/export/content?ids=" + rid) as response:
            with zipfile.ZipFile(io.BytesIO(response.data)) as pack:
                self.assertFalse(any(n.startswith("handoffs/") for n in pack.namelist()))
                self.assertNotIn(b"independent final original", [pack.read(n) for n in pack.namelist()])

    def test_current_state_cross_topic_idempotency_and_actor_are_rechecked(self):
        tid, aid, sid = self.ready()
        self.assertEqual(self.final(tid, aid, sid, meeting_version=0).status_code, 409)
        self.assertEqual(self.final(tid, aid, sid, status="returned").status_code, 409)
        self.assertEqual(self.final(tid, aid, sid, version=0).status_code, 409)
        final = self.final(tid, aid, sid).json
        self.assertEqual(self.final(tid, aid, sid, note="different content").status_code, 409)
        self.assertEqual(self.returned(tid, aid, sid).status_code, 409)
        other = self.topic(["colleague"], "另一独立期次")
        self.assertEqual(self.final(other, aid, sid).status_code, 404)
        self.assertEqual(self.summary(other, [final["id"]]).status_code, 400)
        self.assertEqual(self.summary(tid, [], file=None).status_code, 400)
        self.assertEqual(self.summary(tid, [final["id"]], who="admin").status_code, 403)
        self.assertEqual(self.summary(tid, [final["id"]], who="colleague").status_code, 201)
        self.assertEqual(self.summary(tid, [final["id"]], who="colleague", note="different").status_code, 409)
        self.assertEqual(self.call("/api/collaboration/qualifications/researcher", {"version": 1, "enabled": False}, "admin", "PUT").status_code, 200)
        self.assertEqual(self.final(tid, aid, sid).status_code, 403)
        # Revocation affects new operations, not historical validity.
        with self.call("/api/backup", user="admin") as response:
            archive = self.data_dir.parent / "revoked.zip"
            archive.write_bytes(response.data)
        from platform_app.maintenance import restore_backup
        restore_backup(archive, self.data_dir.parent / "revoked-restored")

    def test_failure_rolls_back_identity_decision_and_summary_original(self):
        tid, aid, sid = self.ready()
        before = self.clients["researcher"].get("/api/records?size=100").json
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db, db:
            db.execute("CREATE TRIGGER fail_final BEFORE INSERT ON topic_finals BEGIN SELECT RAISE(ABORT,'synthetic late final failure'); END")
        self.assertEqual(self.final(tid, aid, sid).status_code, 409)
        self.assertEqual(self.clients["researcher"].get("/api/records?size=100").json, before)
        self.assertEqual(self.workflow(tid)["assignments"][0]["status"], "pending")
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db, db:
            db.execute("DROP TRIGGER fail_final")
        final = self.final(tid, aid, sid).json
        originals = set((self.data_dir / "handoffs").iterdir())
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db, db:
            db.execute("CREATE TRIGGER fail_summary BEFORE INSERT ON topic_summaries BEGIN SELECT RAISE(ABORT,'synthetic late summary failure'); END")
        self.assertEqual(self.summary(tid, [final["id"]]).status_code, 409)
        self.assertEqual(set((self.data_dir / "handoffs").iterdir()), originals)
        self.assertEqual(self.workflow(tid)["summaries"], [])
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db, db:
            db.execute("DROP TRIGGER fail_summary")
        self.assertEqual(self.summary(tid, [final["id"]]).status_code, 201)

    def test_restore_rejects_dangling_adoption_and_mixed_original_ownership(self):
        from platform_app.maintenance import restore_backup
        from scripts.check_collaboration_recovery import corrupt_archive
        tid, aid, sid = self.ready()
        final = self.final(tid, aid, sid).json
        self.assertEqual(self.summary(tid, [final["id"]]).status_code, 201)
        with self.call("/api/backup", user="admin") as response:
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                files = {n: archive.read(n) for n in archive.namelist()}
        destination = self.data_dir.parent / "tampered.zip"
        corrupt_archive(files, destination, mutation="UPDATE topic_summaries SET adoptions_json='[\"missing-final\"]'")
        target = self.data_dir.parent / "tampered-restore"
        with self.assertRaises(ValueError):
            restore_backup(destination, target)
        self.assertFalse(target.exists())
        corrupt_archive(files, destination, mutation="UPDATE topic_finals SET assignment_id='wrong-assignment'")
        with self.assertRaises(ValueError):
            restore_backup(destination, target)
        corrupt_archive(files, destination, wrong_hash=True)
        with self.assertRaises(ValueError):
            restore_backup(destination, target)


if __name__ == "__main__":
    unittest.main()
