"""Meeting decisions and review handoffs exercised at authenticated HTTP."""
import hashlib
import io
import json
import sqlite3
import unittest
import zipfile
from contextlib import closing

from tests import test_collaboration as base
from platform_app.maintenance import restore_backup
from platform_app.web import create_app


class TopicReviewTests(unittest.TestCase):
    setUp = base.CollaborationTests.setUp
    login = base.CollaborationTests.login
    call = base.CollaborationTests.call
    topic = base.CollaborationTests.topic
    docx = staticmethod(base.CollaborationTests.docx)
    def draft(self, tid, aid, version=0, who="colleague", **extra):
        file = extra.pop("file", ("编译.docx", self.docx("独立编译稿")))
        return self.call(f"/api/collaboration/topics/{tid}/assignments/{aid}/submissions", {
            "request_id": f"draft-request-{version}", "version": version,
            "topic_version": 1, "meeting_version": 1, "note": "本机完成", **extra}, who, file=file)

    def returned(self, tid, aid, sid, **extra):
        file = extra.pop("file", None)
        who = extra.pop("who", "researcher")
        return self.call(f"/api/collaboration/topics/{tid}/assignments/{aid}/returns", {
            "request_id": "return-request-1", "submission_id": sid,
            "topic_version": 1, "meeting_version": 1, "note": "请补充出处并核对译文", **extra}, who, file=file)

    def meeting(self, tid, assignments=None, version=0, **extra):
        file = extra.pop("file", None)
        return self.call(f"/api/collaboration/topics/{tid}/meetings", {
            "request_id": f"meeting-request-{version}", "version": version,
            "topic_version": 1, "note": "采用站外文章，由研究员本机编译",
            "assignments": assignments if assignments is not None else [
                {"title": "未入库文章", "source": "https://example.invalid/article", "author_id": "colleague", "country": "拉脱维亚"}
            ], **extra}, file=file)

    def workflow(self, tid, who="colleague"):
        result = self.clients[who].get(f"/api/collaboration/topics/{tid}/workflow")
        self.assertEqual(result.status_code, 200, result.json)
        return result.json

    def test_meeting_preserves_actual_material_and_adopted_candidate_version(self):
        tid = self.topic()
        candidate = self.call(f"/api/collaboration/topics/{tid}/candidates", {
            "request_id": "candidate-meeting-1", "version": 0, "topic_version": 1},
            "colleague", file=("选题.docx", self.docx("报告含三个候选"))).json["id"]
        rows = [{"title": "报告第2项", "candidate_id": candidate, "candidate_item": "第2项，第3页", "author_id": "colleague", "country": "拉脱维亚"},
                {"title": "站外另一篇", "source": "https://example.invalid/other", "author_id": "colleague", "country": "波兰"}]
        result = self.meeting(tid, rows, file=("会议.docx", self.docx("实际会议材料")))
        self.assertEqual(result.status_code, 201, result.json)
        first = self.workflow(tid)
        self.assertEqual(len(first["assignments"]), 2)
        self.assertEqual(first["meetings"][0]["assignments"][0]["candidate_id"], candidate)
        with self.clients["colleague"].get(first["meetings"][0]["file_url"]) as response:
            self.assertEqual(response.data, self.docx("实际会议材料"))
        changed = first["meetings"][0]["assignments"]
        changed[0]["title"] = "会议后更正题名"
        self.assertEqual(self.meeting(tid, changed, version=1).status_code, 201)
        current = self.workflow(tid)
        self.assertEqual(current["meetings"][1]["assignments"][0]["title"], "报告第2项")
        self.assertEqual(current["assignments"][0]["id"], first["assignments"][0]["id"])
        self.assertEqual(current["meetings"][1]["assignments"][0]["candidate_id"], candidate)

    def test_article_series_return_and_resubmit_keep_originals_and_exact_decisions(self):
        tid = self.topic()
        self.assertEqual(self.meeting(tid, [
            {"title": "文章甲", "author_id": "colleague"},
            {"title": "文章乙", "author_id": "colleague"}]).status_code, 201)
        first, second = self.workflow(tid)["assignments"]
        a, b = first["id"], second["id"]
        raw1, raw2 = b"original draft one", b"revised draft two"
        submitted = self.draft(tid, a, file=("初稿.txt", raw1))
        self.assertEqual(submitted.status_code, 201, submitted.json)
        sid = submitted.json["id"]
        self.assertEqual(self.draft(tid, b).json["version"], 1)
        current = self.workflow(tid)
        self.assertEqual([x["status"] for x in current["assignments"]], ["pending", "pending"])
        self.assertEqual(self.returned(tid, a, sid, who="admin").status_code, 403)
        self.assertEqual(self.returned(tid, a, sid, who="colleague").status_code, 403)
        annotation = b"%PDF-1.4\nsynthetic annotation"
        result = self.returned(tid, a, sid, file=("批注.pdf", annotation))
        self.assertEqual(result.status_code, 201, result.json)
        retry = self.returned(tid, a, sid, file=("批注.pdf", annotation))
        self.assertEqual(retry.status_code, 200, retry.json)
        returned = self.workflow(tid)["assignments"][0]
        self.assertEqual(returned["status"], "returned")
        self.assertEqual(returned["returns"][0]["submission_id"], sid)
        self.assertEqual(self.draft(tid, a, version=1, file=("返修.txt", raw2)).status_code, 201)
        stale = self.returned(tid, a, sid, request_id="return-stale-request")
        self.assertEqual(stale.status_code, 409)
        revised = self.workflow(tid)["assignments"][0]
        self.assertEqual(revised["status"], "pending")
        self.assertEqual([x["version"] for x in revised["submissions"]], [2, 1])
        self.assertEqual(revised["submissions"][0]["author_id"], "colleague")
        self.assertEqual(revised["submissions"][0]["uploader_id"], "colleague")
        for who in ("colleague", "researcher", "admin"):
            for row, content in [(revised["submissions"][0], raw2), (revised["submissions"][1], raw1), (revised["returns"][0], annotation)]:
                with self.clients[who].get(row["file_url"]) as response:
                    self.assertEqual(response.data, content)
        self.assertEqual(self.draft(tid, a, version=2, who="researcher").status_code, 403)

    def test_process_export_and_new_directory_restore_preserve_all_handoffs(self):
        tid = self.topic()
        self.assertEqual(self.meeting(tid, file=("会议.txt", b"meeting bytes")).status_code, 201)
        aid = self.workflow(tid)["assignments"][0]["id"]
        sid = self.draft(tid, aid, file=("初稿.txt", b"draft bytes")).json["id"]
        self.assertEqual(self.returned(tid, aid, sid, file=("意见.txt", b"review bytes")).status_code, 201)
        self.assertEqual(self.draft(tid, aid, version=1, file=("重交.txt", b"revision bytes")).status_code, 201)
        # Later revocation changes access, not the validity of earlier contributions.
        self.assertEqual(self.call(f"/api/collaboration/topics/{tid}", {"version": 1, "theme": "移出研究员", "participant_ids": []}, method="PUT").status_code, 200)
        self.assertEqual(self.call("/api/collaboration/qualifications/researcher", {"version": 1, "enabled": False}, "admin", "PUT").status_code, 200)
        current = self.workflow(tid, "admin")
        with self.clients["admin"].get(f"/api/collaboration/topics/{tid}/materials/export") as result:
            self.assertEqual(result.status_code, 200, result.json)
            with zipfile.ZipFile(io.BytesIO(result.data)) as pack:
                manifest = json.loads(pack.read("manifest.json"))
                self.assertEqual(manifest["workflow"]["assignments"][0]["status"], "pending")
                self.assertEqual({pack.read(r["path"]) for r in manifest["files"]}, {b"meeting bytes", b"draft bytes", b"review bytes", b"revision bytes"})
        self.assertEqual(self.clients["colleague"].get(f"/api/collaboration/topics/{tid}/materials/export").status_code, 404)
        with self.call("/api/backup", user="admin") as result:
            self.assertEqual(result.status_code, 200)
            backup = self.data_dir.parent / "new-review-backup.zip"
            backup.write_bytes(result.data)
        target = self.data_dir.parent / "restored-review"
        restore_backup(backup, target)
        restored = self.login("admin", create_app(target, testing=True))
        after = restored.get(f"/api/collaboration/topics/{tid}/workflow")
        self.assertEqual(after.json, current)
        rows = after.json["meetings"] + after.json["assignments"][0]["submissions"] + after.json["assignments"][0]["returns"]
        for row in rows:
            if row["file_url"]:
                with restored.get(row["file_url"]) as response:
                    self.assertEqual(hashlib.sha256(response.data).hexdigest(), row["sha256"])

    def test_stale_meetings_cross_topic_ids_and_unauthorized_handoffs_are_rejected(self):
        tid, other = self.topic(), self.topic([], "独立期次")
        self.assertEqual(self.meeting(tid).status_code, 201)
        a = self.workflow(tid)["assignments"][0]
        aid = a["id"]
        self.assertEqual(self.meeting(tid).status_code, 200)
        self.assertEqual(self.meeting(tid, note="同请求不同决定").status_code, 409)
        self.assertEqual(self.draft(other, aid, who="researcher").status_code, 404)
        self.assertEqual(self.meeting(other, [dict(a)]).status_code, 400)
        original = self.draft(tid, aid, file=("稿件.txt", b"v1"))
        self.assertEqual(original.status_code, 201)
        sid = original.json["id"]
        self.assertEqual(self.draft(tid, aid, file=("稿件.txt", b"v1")).status_code, 200)
        self.assertEqual(self.draft(tid, aid, file=("稿件.txt", b"different")).status_code, 409)
        self.assertEqual(self.draft(tid, aid, request_id="different-stale-request").status_code, 409)
        self.assertEqual(self.returned(other, aid, sid).status_code, 404)
        self.assertEqual(self.meeting(tid, [a], version=1).status_code, 201)
        self.assertEqual(self.draft(tid, aid, version=1).status_code, 409)
        self.assertEqual(self.returned(tid, aid, sid).status_code, 409)
        # An unchanged byte sequence is still a new handoff when its request and note are new.
        self.assertEqual(self.draft(tid, aid, version=1, meeting_version=2, file=("稿件.txt", b"v1"), note="补充说明").status_code, 201)
        self.assertEqual(self.call(f"/api/collaboration/topics/{tid}/meetings", {"request_id": "admin-meeting-request", "version": 2, "topic_version": 1, "note": "越权"}, "admin").status_code, 403)
        self.assertEqual(self.call("/api/collaboration/qualifications/researcher", {"version": 1, "enabled": False}, "admin", "PUT").status_code, 200)
        latest = self.workflow(tid)["assignments"][0]["submissions"][0]
        self.assertEqual(self.returned(tid, aid, latest["id"], meeting_version=2).status_code, 403)
        # Nonparticipants cannot discover, export or download any process history.
        self.assertEqual(self.call("/api/members", {"username": "outside", "name": "旁观者", "password": "LocalDemo2026!", "role": "researcher"}, "admin").status_code, 201)
        self.clients["outside"] = self.login("outside")
        for path in (f"/api/collaboration/topics/{tid}/workflow", f"/api/collaboration/topics/{tid}/materials/export", latest["file_url"]):
            self.assertEqual(self.clients["outside"].get(path).status_code, 404)
        self.assertEqual(self.call(f"/api/members/colleague", {"active": False}, "admin", "PUT").status_code, 200)
        self.assertEqual(self.clients["colleague"].get(latest["file_url"]).status_code, 401)

    def test_invalid_assignment_types_are_client_errors_and_empty_reviews_do_not_return(self):
        tid = self.topic()
        for bad in ({"title": "题名", "author_id": []}, {"title": "题名", "author_id": "colleague", "id": []}, {"title": "题名", "author_id": "colleague", "candidate_id": []}):
            self.assertEqual(self.meeting(tid, [bad]).status_code, 400)
        self.assertEqual(self.meeting(tid).status_code, 201)
        aid = self.workflow(tid)["assignments"][0]["id"]
        sid = self.draft(tid, aid).json["id"]
        self.assertEqual(self.returned(tid, aid, sid, note="").status_code, 400)
        self.assertEqual(self.workflow(tid)["assignments"][0]["status"], "pending")

