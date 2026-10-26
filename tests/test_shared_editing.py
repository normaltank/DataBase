"""Shared content editing and unchanged access boundaries through public HTTP."""
import unittest
import json
from contextlib import closing

import test_workflow
from platform_app.store import connect


class SharedEditingTests(unittest.TestCase):
    setUp = test_workflow.WorkflowTests.setUp
    login = test_workflow.WorkflowTests.login
    call = test_workflow.WorkflowTests.call
    source = test_workflow.WorkflowTests.source
    record = test_workflow.WorkflowTests.record
    detail = test_workflow.WorkflowTests.detail

    def test_members_edit_restore_and_conflict_without_new_management_rights(self):
        for kind in ["research_note", "report", "journal_article", "directory_translation"]:
            with self.subTest(kind=kind):
                extra = {"authors": "原署名", "body_html": "<p>初稿</p>"}
                if kind == "directory_translation":
                    extra.update(coverage="2026", related_source_ids=[self.source()])
                rid = self.record(kind, **extra)
                first = self.detail(rid, "colleague")
                self.assertTrue(first["can_edit"])
                self.assertFalse(first["can_manage_access"])
                history = self.clients["colleague"].get("/api/history/record/" + rid).json["items"]
                changed = self.call("/api/records/" + rid, {"version": 1, "body_html": "<p>同事修订</p>"}, user="colleague", method="PUT")
                self.assertEqual(changed.status_code, 200, changed.json)
                self.assertEqual(self.call("/api/records/" + rid, {"version": 1, "body_html": "冲突"}, method="PUT").status_code, 409)
                restored = self.call(f"/api/history/{history[0]['id']}/restore", {"version": 2}, user="colleague")
                self.assertEqual(restored.status_code, 200, restored.json)
                current = self.detail(rid)
                self.assertEqual(current["body_html"], "<p>初稿</p>")
                self.assertEqual(current["authors"], "原署名")
                self.assertEqual(current["author_id"], first["author_id"])
                self.assertEqual(current["version"], 3)
                self.assertEqual(current["last_modifier"]["name"], "研究员 · 周")
                self.assertEqual(self.call("/api/records/" + rid, {"version": 3, "visibility": "restricted"}, user="colleague", method="PUT").status_code, 403 if kind != "directory_translation" else 400)

    def test_shared_editor_cannot_claim_report_responsibility_or_merge_author_content(self):
        raw = self.record()
        for kind in ["compilation", "research_report", "research_note"]:
            changed = self.call("/api/records/" + raw, {"version": 1, "kind": kind}, user="colleague", method="PUT")
            self.assertEqual(changed.status_code, 403, changed.json)
        notes = [self.record("research_note") for _ in range(2)]
        preview = self.call("/api/merge/preview", {"type": "record", "keep_id": notes[0], "duplicate_id": notes[1]}, user="colleague")
        self.assertFalse(preview.json["allowed"])

    def test_members_restore_public_source_and_conflict_without_review_permission(self):
        sid = self.source(introduction_html="<p>公开档案初稿</p>")
        history = self.clients["colleague"].get("/api/history/source/" + sid).json["items"]
        edited = self.call("/api/sources/" + sid, {"version": 1, "introduction_html": "<p>同事补充</p>"}, user="colleague", method="PUT")
        self.assertEqual(edited.status_code, 200, edited.json)
        restored = self.call(f"/api/history/{history[0]['id']}/restore", {"version": 2}, user="colleague")
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual(self.call(f"/api/history/{history[0]['id']}/restore", {"version": 2}).status_code, 409)
        self.assertEqual(self.clients["researcher"].get("/api/sources/" + sid).json["introduction_html"], "<p>公开档案初稿</p>")
        self.assertEqual(self.call("/api/review/source/" + sid, {"version": 3}, user="colleague").status_code, 403)

    def test_legacy_restricted_unconfirmed_note_does_not_expose_reading_to_editors(self):
        rid = self.record("research_note", visibility="restricted")
        # A pre-existing legacy row with an unconfirmed editor is fixture input,
        # never a new read grant created by the shared editing policy.
        with closing(connect(self.data_dir / "platform.sqlite3")) as db, db:
            db.execute("UPDATE records SET author_confirmed=0,editors=? WHERE id=?", (json.dumps(["colleague"]), rid))
        self.assertEqual(self.clients["colleague"].get("/api/records/" + rid).status_code, 404)
        self.assertEqual(self.call("/api/records/" + rid, {"version": 1, "body_html": "越界"}, user="colleague", method="PUT").status_code, 404)
        self.assertTrue(self.detail(rid)["can_edit"])
        self.assertTrue(self.detail(rid, "admin")["can_edit"])
        self.assertFalse(self.detail(rid)["author_confirmed"])

    def test_history_cannot_restore_a_personal_report_over_common_content(self):
        rid = self.record("compilation", body_html="<p>旧个人成果</p>")
        revision = self.clients["researcher"].get("/api/history/record/" + rid).json["items"][0]["id"]
        # A historical installation could retain a report revision after a type
        # correction. Common editing must never resurrect that author boundary.
        with closing(connect(self.data_dir / "platform.sqlite3")) as db, db:
            db.execute("UPDATE records SET kind='report' WHERE id=?", (rid,))
        restored = self.call(f"/api/history/{revision}/restore", {"version": 1}, user="colleague")
        self.assertEqual(restored.status_code, 409, restored.json)
        self.assertEqual(self.detail(rid)["kind"], "report")

    def test_common_edit_preserves_unreadable_existing_original_relations(self):
        private = self.record(title="不可见原文", visibility="restricted")
        public = self.record(title="可见原文")
        note = self.record("research_note", linked_ids=[private, public])
        initial = self.clients["colleague"].get("/api/history/record/" + note).json["items"][0]["id"]
        self.assertEqual([row["id"] for row in self.detail(note, "colleague")["linked_records"]], [public])
        changed = self.call("/api/records/" + note, {"version": 1, "body_html": "<p>共同补充</p>", "linked_ids": []}, user="colleague", method="PUT")
        self.assertEqual(changed.status_code, 200, changed.json)
        self.assertEqual([row["id"] for row in self.detail(note)["linked_records"]], [private])
        self.assertEqual(self.detail(note, "colleague")["linked_records"], [])
        restored = self.call(f"/api/history/{initial}/restore", {"version": 2}, user="colleague")
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual({row["id"] for row in self.detail(note)["linked_records"]}, {private, public})

    def test_personal_reports_keep_confirmation_edit_restore_and_relationship_boundaries(self):
        for kind in ["compilation", "research_report"]:
            with self.subTest(kind=kind):
                rid = self.record(kind, body_html="<p>个人报告</p>", author_id="colleague")
                for who in self.clients:
                    self.assertFalse(self.detail(rid, who)["can_edit"])
                self.assertEqual(self.call("/api/records/" + rid + "/author", {"version": 1, "confirm": True}, user="colleague").status_code, 200)
                history = self.clients["colleague"].get("/api/history/record/" + rid).json["items"]
                for who in ["researcher", "admin"]:
                    self.assertFalse(self.detail(rid, who)["can_edit"])
                    for change in [{"body_html": "越界"}, {"kind": "report"}, {"linked_ids": [self.record()]}]:
                        self.assertEqual(self.call("/api/records/" + rid, {"version": 2, **change}, user=who, method="PUT").status_code, 403)
                    self.assertEqual(self.call(f"/api/history/{history[0]['id']}/restore", {"version": 2}, user=who).status_code, 403)
                self.assertEqual(self.call("/api/records/" + rid, {"version": 2, "editors": ["researcher"]}, user="colleague", method="PUT").status_code, 200)
                self.assertEqual(self.call("/api/records/" + rid, {"version": 3, "body_html": "<p>作者授权修订</p>"}, method="PUT").status_code, 200)

    def test_disabled_legacy_grantee_does_not_block_current_common_editors(self):
        rid = self.record("research_note", editors=["colleague"])
        self.assertEqual(self.call("/api/members/colleague", {"active": False}, user="admin", method="PUT").status_code, 200)
        changed = self.call("/api/records/" + rid, {"version": 1, "body_html": "<p>有效成员继续共编</p>"}, user="admin", method="PUT")
        self.assertEqual(changed.status_code, 200, changed.json)
        self.assertEqual(self.detail(rid)["editors"], ["colleague"])
        self.assertEqual(self.clients["colleague"].get("/api/records/" + rid).status_code, 401)


if __name__ == "__main__":
    unittest.main()
