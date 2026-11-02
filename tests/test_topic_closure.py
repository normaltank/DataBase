"""End/reopen and the complete write lock at authenticated HTTP boundaries."""
import unittest
import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from tests import test_topic_stages as stages
from tests import test_topic_finals as finals


class TopicClosureTests(unittest.TestCase):
    setUp = stages.TopicStageTests.setUp
    login = stages.TopicStageTests.login
    call = stages.TopicStageTests.call
    topic = stages.TopicStageTests.topic
    docx = staticmethod(stages.TopicStageTests.docx)
    save = stages.TopicStageTests.save
    enter = stages.TopicStageTests.enter
    workflow = stages.TopicStageTests.workflow
    draft = stages.TopicStageTests.draft
    meeting = finals.TopicFinalTests.meeting
    ready = finals.TopicFinalTests.ready
    final = finals.TopicFinalTests.final
    summary = finals.TopicFinalTests.summary
    returned = finals.TopicFinalTests.returned

    def preview(self, tid):
        response = self.clients["researcher"].get(f"/api/collaboration/topics/{tid}/closure-preview")
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def end(self, tid, preview=None, **extra):
        preview = preview or self.preview(tid)
        return self.call(f"/api/collaboration/topics/{tid}/end", {
            "request_id": "closure-end-once", "lifecycle_version": preview["lifecycle_version"],
            "basis_token": preview["basis_token"], "confirm": True, **extra})

    def test_end_locks_saved_selection_form_and_reopen_restores_selection(self):
        tid = self.topic()
        root = f"/api/collaboration/topics/{tid}"
        preview = self.preview(tid)
        self.assertEqual(preview["incomplete"], [])
        self.assertEqual(self.end(tid, preview).status_code, 201)
        late = self.call(root + "/candidates", {"request_id": "closed-old-form", "version": 0, "topic_version": 1, "note": "旧表单说明"}, "colleague", file=("旧表单.txt", b"preserved file"))
        self.assertEqual(late.status_code, 409, late.json)
        topic = self.clients["colleague"].get(root).json
        self.assertEqual(topic["lifecycle_state"], "closed")
        self.assertTrue(topic["is_participant"])
        self.assertFalse(topic["can_submit"])
        reopened = self.call(root + "/reopen", {"request_id": "closure-reopen-once", "lifecycle_version": topic["lifecycle_version"]})
        self.assertEqual(reopened.status_code, 201, reopened.json)
        topic = self.clients["colleague"].get(root).json
        self.assertEqual((topic["stage"], topic["lifecycle_state"]), ("selection", "open"))

    def test_current_gaps_and_complete_lock_leave_originals_and_adoptions_readable(self):
        tid, aid, sid = self.ready()
        root = f"/api/collaboration/topics/{tid}"
        final = self.final(tid, aid, sid).json
        summary = self.summary(tid, [final["id"]]).json
        self.assertEqual(self.preview(tid)["incomplete"], [])
        self.assertEqual(self.draft(tid, aid, version=1, request_id="after-final-draft", file=("新稿.txt", b"new draft after fixed adoption")).status_code, 201)
        before_files = {p.name: p.read_bytes() for p in (self.data_dir / "handoffs").iterdir()}
        before = self.workflow(tid)
        p = self.preview(tid)
        self.assertEqual([(x["status"], x["submission_version"], x["missing_current_final"]) for x in p["incomplete"]], [("pending", 2, True)])
        self.assertEqual(self.end(tid, p).status_code, 201)
        payloads = [
            (root, {"version": 1, "theme": "不能改", "participant_ids": []}, "PUT", None),
            (root + "/candidates", {"request_id": "lock-candidate", "version": 0, "topic_version": 1}, "POST", ("选题.txt", b"candidate")),
            (root + "/meetings", {"request_id": "lock-meeting", "version": 1, "topic_version": 1, "note": "不能改", "assignments": []}, "POST", ("会议.txt", b"meeting")),
            (root + "/enter-compilation", {"request_id": "lock-stage", "stage_version": 2, "topic_version": 1, "meeting_version": 1}, "POST", None),
            (root + f"/assignments/{aid}/submissions", {"request_id": "lock-draft", "version": 2, "topic_version": 1, "meeting_version": 1}, "POST", ("编译.txt", b"draft")),
            (root + f"/assignments/{aid}/returns", {"request_id": "lock-return", "topic_version": 1, "meeting_version": 1, "submission_id": before["assignments"][0]["current_submission_id"], "note": "不能审"}, "POST", None),
            (root + f"/assignments/{aid}/finals", {"request_id": "lock-final", "topic_version": 1, "meeting_version": 1, "submission_id": before["assignments"][0]["current_submission_id"], "version": 2, "status": "pending"}, "POST", None),
            (root + "/summaries", {"request_id": "lock-summary", "topic_version": 1, "version": 1, "author_id": "researcher", "final_ids": [final["id"]]}, "POST", ("汇总.txt", b"summary")),
        ]
        for path, data, method, file in payloads:
            with self.subTest(path=path):
                self.assertEqual(self.call(path, data, method=method, file=file).status_code, 409)
        self.assertEqual({p.name: p.read_bytes() for p in (self.data_dir / "handoffs").iterdir()}, before_files)
        after = self.workflow(tid)
        self.assertEqual(after["summaries"], before["summaries"])
        self.assertEqual(after["assignments"][0]["submissions"], before["assignments"][0]["submissions"])
        self.assertEqual(after["assignments"][0]["status"], "pending")
        self.assertFalse(after["assignments"][0]["can_submit"])
        self.assertEqual(after["summaries"][0]["adoptions"][0]["submission_id"], sid)
        with self.clients["colleague"].get(after["assignments"][0]["submissions"][0]["file_url"]) as download:
            self.assertEqual(download.data, b"new draft after fixed adoption")
        for suffix in ("", "/history", "/candidates", "/workflow", "/materials/export"):
            response = self.clients["colleague"].get(root + suffix)
            self.assertEqual(response.status_code, 200)
            response.close()
        for scope in ("participating", "leading"):
            self.assertIn(tid, [x["id"] for x in self.clients["researcher"].get("/api/collaboration/works?scope=" + scope).json["items"]])
        report = self.call("/api/records", {"kind": "compilation", "title": "独立作者成果", "body_html": "<p>原文</p>"}, "colleague").json["id"]
        self.assertEqual(self.call("/api/records/" + report, {"version": 1, "body_html": "<p>闭期仍可依作者授权修改</p>"}, "colleague", "PUT").status_code, 200)

    def test_preview_changes_on_draft_return_meeting_and_candidate(self):
        tid, aid, sid = self.ready()
        root = f"/api/collaboration/topics/{tid}"
        preview = self.preview(tid)
        self.assertEqual(self.returned(tid, aid, sid).status_code, 201)
        stale = self.end(tid, preview)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json["latest_preview"]["incomplete"][0]["status"], "returned")
        preview = self.preview(tid)
        self.assertEqual(preview["incomplete"][0]["status"], "returned")
        self.assertEqual(self.draft(tid, aid, version=1).status_code, 201)
        self.assertEqual(self.end(tid, preview).status_code, 409)
        preview = self.preview(tid)
        rows = self.workflow(tid)["meetings"][0]["assignments"]
        rows[0]["title"] = "更正采用题名"
        self.assertEqual(self.meeting(tid, rows, version=1).status_code, 201)
        self.assertEqual(self.end(tid, preview).status_code, 409)
        preview = self.preview(tid)
        self.assertEqual(self.call(root + "/candidates", {"request_id": "preview-candidate", "version": 0, "topic_version": 1}, "colleague", file=("补充.txt", b"supplement")).status_code, 201)
        self.assertEqual(self.end(tid, preview).status_code, 409)
        self.assertEqual(self.end(tid).status_code, 201)

    def test_reopen_cycles_and_retry_do_not_reverse_later_state_or_bypass_revocation(self):
        tid = self.topic()
        root = f"/api/collaboration/topics/{tid}"
        p = self.preview(tid)
        self.assertEqual(self.end(tid, p).status_code, 201)
        self.assertEqual(self.end(tid, p).status_code, 200)
        for who in ("admin", "colleague"):
            self.assertEqual(self.call(root + "/reopen", {"request_id": "unauthorized-reopen", "lifecycle_version": 2}, who).status_code, 403)
        reopened = self.call(root + "/reopen", {"request_id": "cycle-reopen-1", "lifecycle_version": 2})
        self.assertEqual(reopened.status_code, 201)
        self.assertEqual(self.end(tid, p).json["lifecycle_state"], "open")
        self.assertEqual(self.end(tid, request_id="closure-end-once").status_code, 409)
        self.assertEqual(self.end(tid, request_id="cycle-end-2").status_code, 201)
        self.assertEqual(self.call(root + "/reopen", {"request_id": "cycle-reopen-1", "lifecycle_version": 2}).json["lifecycle_state"], "closed")
        self.assertEqual(self.call("/api/collaboration/qualifications/researcher", {"version": 1, "enabled": False}, "admin", "PUT").status_code, 200)
        self.assertEqual(self.end(tid, p).status_code, 403)
        self.assertEqual(self.call(root + "/reopen", {"request_id": "cycle-reopen-2", "lifecycle_version": 4}).status_code, 403)
        self.assertEqual(self.clients["researcher"].get(root).json["lifecycle_state"], "closed")
        self.assertIn(tid, [t["id"] for t in self.clients["researcher"].get("/api/collaboration/topics?scope=leading").json["items"]])

    def test_end_and_draft_race_has_a_legal_order_and_last_write_failure_rolls_back(self):
        tid = self.topic()
        self.save(tid, [{"title": "文章", "author_id": "colleague"}])
        self.enter(tid)
        root = f"/api/collaboration/topics/{tid}"
        aid = self.workflow(tid)["assignments"][0]["id"]
        p = self.preview(tid)
        with ThreadPoolExecutor(max_workers=2) as pool:
            ended = pool.submit(self.end, tid, p)
            drafted = pool.submit(self.draft, tid, aid)
            statuses = ended.result().status_code, drafted.result().status_code
        self.assertIn(statuses, ((201, 409), (409, 201)))
        if statuses[0] == 409:
            self.assertEqual(self.end(tid).status_code, 201)
        closed = self.clients["researcher"].get(root).json
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db, db:
            db.execute("CREATE TRIGGER reject_closure_update BEFORE UPDATE ON topic_closures BEGIN SELECT RAISE(ABORT,'synthetic closure failure'); END")
        self.assertEqual(self.call(root + "/reopen", {"request_id": "rollback-reopen", "lifecycle_version": closed["lifecycle_version"]}).status_code, 409)
        self.assertEqual(self.clients["researcher"].get(root).json, closed)

    def test_lifecycle_authority_current_account_and_private_scope(self):
        tid = self.topic()
        root = f"/api/collaboration/topics/{tid}"
        self.assertEqual(self.end(tid).status_code, 201)
        self.assertEqual(self.call("/api/collaboration/qualifications/colleague", {"version": 0, "enabled": True}, "admin", "PUT").status_code, 200)
        for who in ("admin", "colleague"):
            self.assertEqual(self.clients[who].get(root + "/closure-preview").status_code, 403)
            for action in ("end", "reopen"):
                self.assertEqual(self.call(root + "/" + action, {"request_id": "wrong-lead-action", "lifecycle_version": 2}, who).status_code, 403)
        self.assertEqual(self.call("/api/members", {"username": "outside", "name": "非参与者", "password": "LocalDemo2026!", "role": "researcher"}, "admin").status_code, 201)
        self.clients["outside"] = self.login("outside")
        for suffix in ("", "/history", "/closure-preview"):
            self.assertEqual(self.clients["outside"].get(root + suffix).status_code, 404)
        self.assertEqual(self.call(root + "/reopen", {"request_id": "outside-reopen", "lifecycle_version": 2}, "outside").status_code, 404)
        self.assertEqual(self.call("/api/members/researcher", {"active": False}, "admin", "PUT").status_code, 200)
        self.assertEqual(self.call(root + "/reopen", {"request_id": "disabled-reopen", "lifecycle_version": 2}).status_code, 401)
