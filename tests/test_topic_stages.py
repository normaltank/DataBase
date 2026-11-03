"""Explicit topic stages observed through authenticated public HTTP."""
import unittest
import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from tests import test_collaboration as base
from tests import test_topic_review as review


class TopicStageTests(unittest.TestCase):
    setUp = base.CollaborationTests.setUp
    login = base.CollaborationTests.login
    call = base.CollaborationTests.call
    topic = base.CollaborationTests.topic
    docx = staticmethod(base.CollaborationTests.docx)
    workflow = review.TopicReviewTests.workflow
    draft = review.TopicReviewTests.draft

    def save(self, tid, rows, version=0, **extra):
        return self.call(f"/api/collaboration/topics/{tid}/meetings", {"request_id": f"stage-meeting-{version}", "version": version, "topic_version": 1, "note": "实际会议说明", "assignments": rows, **extra})

    def enter(self, tid, **extra):
        return self.call(f"/api/collaboration/topics/{tid}/enter-compilation", {"request_id": "stage-enter-once", "stage_version": 1, "topic_version": 1, "meeting_version": 1, **extra})

    def test_saving_discussion_never_enters_compilation(self):
        tid = self.topic()
        url = f"/api/collaboration/topics/{tid}"
        saved = self.call(url + "/meetings", {
            "request_id": "stage-note-only", "version": 0, "topic_version": 1,
            "note": "会议仅讨论，尚未确认分工", "assignments": [],
        })
        self.assertEqual(saved.status_code, 201, saved.json)
        detail = self.clients["colleague"].get(url).json
        self.assertEqual(detail.get("stage"), "selection", detail)
        self.assertEqual(self.clients["colleague"].get(url + "/workflow").json["meeting_version"], 1)

    def test_explicit_direct_advance_opens_legacy_drafts_without_meeting_basis(self):
        tid = self.topic()
        rows = [{"title": title, "author_id": "colleague", "source": "https://example.invalid/source"} for title in ("文章一", "文章二")]
        self.assertEqual(self.save(tid, rows).status_code, 201)
        w = self.workflow(tid)
        self.assertFalse(any(a["can_submit"] for a in w["assignments"]))
        aid = w["assignments"][0]["id"]
        self.assertEqual(self.draft(tid, aid).status_code, 409)
        for who in ("colleague", "admin"):
            self.assertEqual(self.call(f"/api/collaboration/topics/{tid}/enter-compilation", {
                "request_id": "stage-forbidden-confirm", "stage_version": 1,
                "topic_version": 1, "meeting_version": 1,
            }, who).status_code, 403)
        entered = self.enter(tid)
        self.assertEqual(entered.status_code, 201, entered.json)
        self.assertEqual(self.enter(tid).status_code, 200)
        self.assertEqual(self.enter(tid, meeting_version=0).status_code, 409)
        t = self.clients["colleague"].get(f"/api/collaboration/topics/{tid}").json
        self.assertEqual(t["stage"], "compilation")
        self.assertEqual(len(t["stage_events"]), 1)
        self.assertIsNone(t["stage_events"][0]["meeting_version"])
        self.assertEqual(t["stage_events"][0]["actor_id"], "researcher")
        self.assertTrue(all(a["can_submit"] for a in self.workflow(tid)["assignments"]))
        self.assertEqual(self.draft(tid, aid).status_code, 201)
        self.assertEqual(self.save(tid, [], version=1).status_code, 201)
        self.assertEqual(self.clients["colleague"].get(f"/api/collaboration/topics/{tid}").json["stage"], "compilation")
        self.assertEqual(self.call("/api/collaboration/qualifications/researcher", {"version": 1, "enabled": False}, "admin", "PUT").status_code, 200)
        self.assertEqual(self.enter(tid).status_code, 403)

    def test_no_assignment_gate_but_stale_stage_and_revoked_lead_are_rejected(self):
        tid = self.topic()
        self.assertEqual(self.enter(tid, stage_version=0).status_code, 409)
        self.assertEqual(self.call("/api/collaboration/qualifications/researcher", {"version": 1, "enabled": False}, "admin", "PUT").status_code, 200)
        self.assertEqual(self.enter(tid).status_code, 403)
        topic = self.clients["researcher"].get(f"/api/collaboration/topics/{tid}").json
        self.assertTrue(topic["is_lead"])
        self.assertFalse(topic["can_manage"])
        self.assertEqual(topic["stage"], "selection")
        self.assertEqual(self.call("/api/collaboration/qualifications/researcher", {"version": 2, "enabled": True}, "admin", "PUT").status_code, 200)
        self.assertEqual(self.enter(tid).status_code, 201)
        self.assertIn(tid, [t["id"] for t in self.clients["researcher"].get("/api/collaboration/works?scope=leading").json["items"]])

    def test_meeting_reading_retains_people_and_report_location_per_version(self):
        tid = self.topic()
        cid = self.call(f"/api/collaboration/topics/{tid}/candidates", {"request_id": "stage-candidate-v1", "version": 0, "topic_version": 1}, "colleague", file=("选题.txt", b"synthetic selection")).json["id"]
        self.assertEqual(self.save(tid, [{"title": "文章", "author_id": "colleague", "candidate_id": cid, "candidate_item": "第3页"}]).status_code, 201)
        rows = self.workflow(tid)["meetings"][0]["assignments"]
        rows[0]["author_id"] = "researcher"
        self.assertEqual(self.save(tid, rows, version=1).status_code, 201)
        meetings = self.workflow(tid)["meetings"]
        self.assertEqual(meetings[0]["assignments"][0]["author_name"], "研究员 · 林")
        self.assertEqual(meetings[1]["assignments"][0]["author_name"], "研究员 · 周")
        self.assertEqual(meetings[1]["assignments"][0]["candidate_version"], 1)
        self.assertEqual(meetings[1]["assignments"][0]["candidate_item"], "第3页")

    def test_concurrent_confirmation_has_one_decision_and_failure_rolls_back(self):
        tid = self.topic()
        self.assertEqual(self.save(tid, [{"title": "文章", "author_id": "colleague"}]).status_code, 201)
        url = f"/api/collaboration/topics/{tid}"
        clients = [self.login("researcher"), self.login("researcher")]

        def enter(pair):
            index, client = pair
            return client.post(url + "/enter-compilation", json={
                "request_id": f"concurrent-confirm-{index}", "stage_version": 1,
                "topic_version": 1, "meeting_version": 1,
            }, headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]}).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(enter, enumerate(clients))), [201, 409])
        self.assertEqual(len(self.clients["researcher"].get(url).json["stage_events"]), 1)
        other = self.topic()
        self.assertEqual(self.save(other, [{"title": "另一文章", "author_id": "colleague"}]).status_code, 201)
        # Inject a database-boundary failure after the event INSERT.
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db, db:
            db.execute("CREATE TRIGGER reject_stage_update BEFORE UPDATE ON topic_stages BEGIN SELECT RAISE(ABORT,'synthetic stage failure'); END")
        self.assertEqual(self.enter(other).status_code, 409)
        unchanged = self.clients["researcher"].get(f"/api/collaboration/topics/{other}").json
        self.assertEqual(unchanged["stage"], "selection")
        self.assertEqual(unchanged["stage_events"], [])
        self.assertEqual(unchanged["stage_version"], 1)

    def test_disabled_legacy_compiler_is_not_a_direct_stage_gate(self):
        tid = self.topic()
        self.assertEqual(self.save(tid, [{'title': 'Valid', 'author_id': 'researcher'},
            {'title': 'Disabled', 'author_id': 'colleague'}]).status_code, 201)
        self.assertEqual(self.call('/api/members/colleague', {'active': False}, 'admin', 'PUT').status_code, 200)
        self.assertEqual(self.enter(tid).status_code, 201)
        self.assertEqual(self.clients['researcher'].get('/api/collaboration/topics/' + tid).json['stage'], 'compilation')
