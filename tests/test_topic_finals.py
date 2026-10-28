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

    def test_reassignment_does_not_inherit_previous_authors_current_final(self):
        tid, aid, sid = self.ready()
        final = self.final(tid, aid, sid).json
        summary = self.summary(tid, [final["id"]]).json
        rows = self.workflow(tid)["meetings"][0]["assignments"]
        rows[0]["author_id"] = "researcher"
        self.assertEqual(self.meeting(tid, rows, version=1).status_code, 201)
        current = self.workflow(tid, "researcher")
        a = current["assignments"][0]
        self.assertEqual(a["status"], "awaiting_submission")
        self.assertIsNone(a["current_submission_id"])
        self.assertEqual(a["submissions"][0]["id"], sid)
        self.assertEqual(a["finals"][0]["id"], final["id"])
        self.assertEqual(current["summaries"][0]["id"], summary["id"])
        self.assertEqual(current["summaries"][0]["adoptions"][0]["submission_id"], sid)
        self.assertEqual(self.final(tid, aid, sid, meeting_version=2, request_id="old-after-reassign").status_code, 409)
        with self.clients["researcher"].get(a["submissions"][0]["file_url"]) as response:
            self.assertEqual(response.data, b"independent final original")

    def test_reassigned_author_submits_revises_and_finalizes_own_versions(self):
        tid, aid, sid = self.ready()
        rows = self.workflow(tid)["meetings"][0]["assignments"]
        rows[0]["author_id"] = "researcher"
        self.meeting(tid, rows, version=1)
        self.assertEqual(self.returned(tid, aid, sid, meeting_version=2).status_code, 409)
        self.assertEqual(self.workflow(tid)["assignments"][0]["returns"], [])
        self.assertEqual(self.draft(tid, aid, version=1, meeting_version=2).status_code, 403)
        submitted = self.draft(tid, aid, version=1, meeting_version=2, who="researcher")
        self.assertEqual(submitted.status_code, 201, submitted.json)
        second = submitted.json["id"]
        self.assertEqual(self.returned(tid, aid, second, meeting_version=1).status_code, 409)
        returned = self.returned(tid, aid, second, meeting_version=2)
        self.assertEqual(returned.status_code, 201, returned.json)
        self.assertEqual(self.returned(tid, aid, second, meeting_version=2).status_code, 200)
        self.assertEqual(self.workflow(tid)["assignments"][0]["status"], "returned")
        self.assertEqual(self.final(tid, aid, second, meeting_version=2, version=2).status_code, 409)
        third = self.draft(tid, aid, version=2, meeting_version=2, who="researcher").json["id"]
        result = self.final(tid, aid, third, meeting_version=2, version=3)
        self.assertEqual(result.status_code, 201, result.json)
        self.assertEqual(self.final(tid, aid, third, meeting_version=2, version=3).status_code, 200)
        a = self.workflow(tid)["assignments"][0]
        self.assertEqual((a["status"], a["current_submission_id"]), ("final", third))
        self.assertEqual(len(a["submissions"]), 3)
        self.assertEqual(a["returns"][0]["submission_id"], second)

    def test_same_article_author_survives_meeting_edit_withdrawal_and_restore(self):
        tid, aid, sid = self.ready()
        rows = self.workflow(tid)["meetings"][0]["assignments"]
        rows[0]["title"] = "更正文章题名"
        self.meeting(tid, rows, version=1, note="补充会议说明")
        a = self.workflow(tid)["assignments"][0]
        self.assertEqual((a["status"], a["current_submission_id"]), ("pending", sid))
        self.assertEqual(self.final(tid, aid, sid).status_code, 409)
        final = self.final(tid, aid, sid, meeting_version=2)
        self.assertEqual(final.status_code, 201, final.json)
        self.meeting(tid, [], version=2)
        a = self.workflow(tid)["assignments"][0]
        self.assertFalse(a["active"])
        self.assertIsNone(a["current_submission_id"])
        self.assertEqual(self.returned(tid, aid, sid, meeting_version=3, request_id="withdrawn-return").status_code, 404)
        self.meeting(tid, rows, version=3)
        self.assertEqual(self.workflow(tid)["assignments"][0]["status"], "final")
        # Same request replays its saved decision without generating a new one.
        self.assertEqual(self.final(tid, aid, sid, meeting_version=2).status_code, 200)
        self.assertEqual(len(self.workflow(tid)["assignments"][0]["finals"]), 1)
        self.assertEqual(self.returned(tid, aid, sid, meeting_version=4).status_code, 409)

    def test_reassigned_history_current23_export_and_new_directory_restore(self):
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        tid, aid, sid = self.ready()
        final = self.final(tid, aid, sid).json
        summary = self.summary(tid, [final["id"]]).json
        rows = self.workflow(tid)["meetings"][0]["assignments"]
        rows[0]["author_id"] = "researcher"
        self.meeting(tid, rows, version=1)
        before = self.workflow(tid, "researcher")
        self.assertEqual(before["assignments"][0]["status"], "awaiting_submission")
        with self.clients["researcher"].get(f"/api/collaboration/topics/{tid}/materials/export") as response:
            with zipfile.ZipFile(io.BytesIO(response.data)) as pack:
                manifest = json.loads(pack.read("manifest.json"))
                exported = manifest["workflow"]
                self.assertEqual(exported["assignments"][0]["status"], "awaiting_submission")
                self.assertEqual(exported["summaries"][0]["adoptions"][0]["submission_id"], sid)
                self.assertIn(b"independent final original", [pack.read(f["path"]) for f in manifest["files"]])
        # Content export contains the readable query result, not an `ids` filter.
        # Final and summary records can share a timestamp; select exact identities.
        with self.clients["colleague"].get("/api/export/content") as response:
            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(response.data)) as pack:
                payload = json.loads(pack.read("content.json"))
                records = [r for r in payload["records"] if r["id"] == summary["record_id"]]
                self.assertEqual(len(records), 1)
                works = [w for w in records[0]["collaboration_works"] if w["kind"] == "summary" and w["id"] == summary["id"]]
                self.assertEqual(len(works), 1)
                work = works[0]
                self.assertEqual(work["topic_id"], tid)
                self.assertEqual(len(work["adoptions"]), 1)
                adopted = work["adoptions"][0]
                self.assertEqual((adopted["id"], adopted["submission_id"], adopted["version"]), (final["id"], sid, 1))
                self.assertEqual(pack.read(work["path"]), b"actual assembled issue original")
                self.assertEqual(pack.read(adopted["path"]), b"independent final original")
        returned_tid, returned_aid, returned_sid = self.ready()
        returned = self.returned(returned_tid, returned_aid, returned_sid, file=("old-review.txt", b"previous author review original"))
        self.assertEqual(returned.status_code, 201)
        changed = self.workflow(returned_tid)["meetings"][0]["assignments"]
        changed[0]["author_id"] = "researcher"
        self.meeting(returned_tid, changed, version=1)
        returned_history = self.workflow(returned_tid, "researcher")
        self.assertEqual(returned_history["assignments"][0]["status"], "awaiting_submission")
        self.assertEqual(returned_history["assignments"][0]["returns"][0]["submission_id"], returned_sid)
        backup_path = self.data_dir.parent / "reassigned-backup.zip"
        with self.call("/api/backup", user="admin") as backup:
            backup_path.write_bytes(backup.data)
        target = self.data_dir.parent / "reassigned-restored"
        restore_backup(backup_path, target)
        app = create_app(target, testing=True)
        restored = self.login("researcher", app)
        self.assertEqual(restored.get('/health').json['schema'], 23)
        self.assertEqual(restored.get(f"/api/collaboration/topics/{tid}/workflow").json, before)
        self.assertEqual(restored.get(f"/api/collaboration/topics/{returned_tid}/workflow").json, returned_history)
        with restored.get(returned_history["assignments"][0]["returns"][0]["file_url"]) as response:
            self.assertEqual(response.data, b"previous author review original")
        with restored.get(before["summaries"][0]["adoptions"][0]["file_url"]) as response:
            self.assertEqual(response.data, b"independent final original")

        # A final after a harmless meeting revision also validates on restore.
        tid2, aid2, sid2 = self.ready()
        same = self.workflow(tid2)["meetings"][0]["assignments"]
        self.meeting(tid2, same, version=1, note="仅补字")
        self.assertEqual(self.final(tid2, aid2, sid2, meeting_version=2).status_code, 201)
        with self.call("/api/backup", user="admin") as backup:
            backup_path.write_bytes(backup.data)
        restore_backup(backup_path, self.data_dir.parent / "edited-meeting-restored")

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
        self.assertEqual(self.final(tid, aid, sid, visibility=None).status_code, 400)
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
