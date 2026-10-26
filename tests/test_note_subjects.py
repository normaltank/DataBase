"""Explicit research subjects through HTTP, isolated members and portable recovery."""
import io
import hashlib
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from platform_app.maintenance import restore_backup
from platform_app.store import connect, CURRENT_SCHEMA_VERSION
from platform_app.web import create_app


class NoteSubjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="note-subject-test-")
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"
        self.app = create_app(self.data_dir, testing=True)
        self.clients = {who: self.login(who) for who in ["researcher", "colleague", "admin"]}

    def login(self, who, app=None):
        client = (app or self.app).test_client()
        csrf = client.get("/api/session").json["csrf"]
        response = client.post("/api/login", json={"username": who, "password": "LocalDemo2026!"},
                               headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 200, response.json)
        return client

    def call(self, path, data=None, who="researcher", method="POST", file=None):
        client = self.clients[who]
        payload = {"json": data or {}} if not file else {"data": {
            "data": json.dumps(data), "file": (io.BytesIO(file[1]), file[0])}}
        return client.open(path, method=method,
                           headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]}, **payload)

    def person(self, name="合成人物甲"):
        response = self.call("/api/people", {"name": name, "change_note": "合成主页"})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["id"]

    def source(self, name, kind):
        response = self.call("/api/sources", {"name": name, "kind": kind})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["id"]

    def record(self, **extra):
        response = self.call("/api/records", {"kind": "research_note", "title": "合成比较笔记", **extra})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["id"]

    def detail(self, rid, who="researcher"):
        response = self.clients[who].get("/api/records/" + rid)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def subjects(self, *pairs):
        return [{"subject_type": kind, "subject_id": sid} for kind, sid in pairs]

    def notes(self, subject_type, subject_id, who="researcher"):
        prefix = "/api/people/" if subject_type == "person" else "/api/sources/"
        response = self.clients[who].get(prefix + subject_id + "/research-notes")
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def merge(self, kind, keep, duplicate, who="admin"):
        preview = self.call("/api/merge/preview", {"type": kind, "keep_id": keep, "duplicate_id": duplicate}, who=who)
        self.assertEqual(preview.status_code, 200, preview.json)
        self.assertTrue(preview.json["allowed"], preview.json)
        response = self.call("/api/merge", {"type": kind, "keep_id": keep, "duplicate_id": duplicate,
            "keep_version": preview.json["keep"]["version"], "duplicate_version": preview.json["duplicate"]["version"],
            "confirmed": True}, who=who)
        self.assertEqual(response.status_code, 200, response.json)

    def test_one_note_is_explicitly_shared_by_multiple_subjects_without_inferring_citations(self):
        first, second = self.person(), self.person("合成人物乙")
        institute, journal = self.source("合成机构", "institution"), self.source("合成期刊", "journal")
        original = self.record(kind="report", title="合成原文", source_id=institute, serial_id=journal)
        rid = self.record(body_html="<p>研究判断</p>", linked_ids=[original], related_source_ids=[institute],
                          research_subjects=self.subjects(("person", first)))
        self.assertEqual([(s["subject_type"], s["subject_id"]) for s in self.detail(rid)["research_subjects"]],
                         [("person", first)])
        self.assertEqual(self.notes("institution", institute)["total"], 0)
        self.assertEqual(self.notes("journal", journal)["total"], 0)
        initial = self.detail(rid)["research_subjects"][0]
        change = self.call("/api/records/" + rid + "/research-subjects", {
            "version": 1, "research_subjects": [initial, *self.subjects(
                ("person", second), ("institution", institute), ("journal", journal))]}, method="PUT")
        self.assertEqual(change.status_code, 200, change.json)
        for kind, sid in [("person", first), ("person", second), ("institution", institute), ("journal", journal)]:
            self.assertEqual([n["id"] for n in self.notes(kind, sid)["items"]], [rid])
        note = self.detail(rid)
        self.assertEqual(note["body_html"], "<p>研究判断</p>")
        self.assertEqual([r["id"] for r in note["linked_records"]], [original])
        self.assertEqual(note["related_source_ids"], [institute])
        removed = self.call("/api/records/" + rid + "/research-subjects", {
            "version": note["version"], "research_subjects": [s for s in note["research_subjects"]
                if s["subject_id"] != second]}, method="PUT")
        self.assertEqual(removed.status_code, 200, removed.json)
        self.assertEqual(self.notes("person", second)["total"], 0)
        self.assertEqual(len(self.detail(rid)["research_subjects"]), 3)

    def test_subject_editing_and_picker_follow_reading_access_without_author_confirmation(self):
        pid = self.person()
        rid = self.record(author_id="colleague", editors=["researcher", "admin"],
                          research_subjects=self.subjects(("person", pid)))
        for version, who in enumerate(self.clients, 1):
            changed = self.call("/api/records/" + rid + "/research-subjects", {
                "version": version, "research_subjects": self.subjects(("person", pid))}, who=who, method="PUT")
            self.assertEqual(changed.status_code, 200, changed.json)
            self.assertEqual(self.clients[who].get("/api/records?kind=research_note&editable=1").json["total"], 1)
        confirm = self.call("/api/records/" + rid + "/author", {"version": 4, "confirm": True}, who="colleague")
        self.assertEqual(confirm.status_code, 200, confirm.json)
        self.assertEqual(self.clients["colleague"].get("/api/records?kind=research_note&editable=1").json["total"], 1)
        self.assertEqual(self.clients["admin"].get("/api/records?kind=research_note&editable=1").json["total"], 1)
        grant = self.call("/api/records/" + rid, {"version": 5, "editors": ["researcher"]}, who="colleague", method="PUT")
        self.assertEqual(grant.status_code, 200, grant.json)
        changed = self.call("/api/records/" + rid + "/research-subjects", {
            "version": 6, "research_subjects": []}, method="PUT")
        self.assertEqual(changed.status_code, 200, changed.json)
        history = self.clients["researcher"].get("/api/records/" + rid + "/research-subjects/history")
        self.assertEqual(history.status_code, 200, history.json)
        self.assertEqual([h["action"] for h in history.json["items"]], ["removed", "created"])
        revoke = self.call("/api/records/" + rid, {"version": 7, "editors": [], "visibility": "restricted"},
                           who="colleague", method="PUT")
        self.assertEqual(revoke.status_code, 200, revoke.json)
        self.assertEqual(self.call("/api/records/" + rid + "/research-subjects", {
            "version": 8, "research_subjects": self.subjects(("person", pid))}, method="PUT").status_code, 200)
        self.assertEqual(self.clients["researcher"].get("/api/records/" + rid + "/research-subjects/history").status_code, 200)
        for who in ["researcher", "admin"]:
            self.assertEqual(self.clients[who].get("/api/records?kind=research_note&editable=1").json["total"], 1)

    def test_subject_history_conflict_and_content_restore_preserve_stable_relations(self):
        first, second = self.person(), self.person("合成人物乙")
        rid = self.record(research_subjects=self.subjects(("person", first)))
        first_relation = self.detail(rid)["research_subjects"][0]
        initial_history = self.clients["researcher"].get("/api/history/record/" + rid).json["items"][-1]["id"]
        edit = self.call("/api/records/" + rid, {"version": 1, "body_html": "<p>正文新稿</p>",
            "research_subjects": [first_relation, *self.subjects(("person", second))]}, method="PUT")
        self.assertEqual(edit.status_code, 200, edit.json)
        second_relation = next(s for s in self.detail(rid)["research_subjects"] if s["subject_id"] == second)
        body = self.call("/api/records/" + rid, {"version": 2, "body_html": "<p>普通保存</p>"}, method="PUT")
        self.assertEqual(body.status_code, 200, body.json)
        self.assertEqual({s["id"] for s in self.detail(rid)["research_subjects"]}, {first_relation["id"], second_relation["id"]})
        stale = self.call("/api/records/" + rid + "/research-subjects", {"version": 2, "research_subjects": []}, method="PUT")
        self.assertEqual(stale.status_code, 409, stale.json)
        restored = self.call(f"/api/history/{initial_history}/restore", {"version": 3})
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual([s["id"] for s in self.detail(rid)["research_subjects"]], [first_relation["id"]])
        history = self.clients["researcher"].get("/api/records/" + rid + "/research-subjects/history").json["items"]
        self.assertEqual(history[0]["snapshot"]["status"], "removed")
        self.assertEqual(history[0]["snapshot"]["id"], second_relation["id"])
        readded = self.call("/api/records/" + rid + "/research-subjects", {"version": 4,
            "research_subjects": [self.detail(rid)["research_subjects"][0], *self.subjects(("person", second))]}, method="PUT")
        self.assertEqual(readded.status_code, 200, readded.json)
        self.assertNotEqual(next(s["id"] for s in self.detail(rid)["research_subjects"] if s["subject_id"] == second), second_relation["id"])

    def test_source_and_note_merges_preserve_colliding_relation_origins_and_block_unsafe_types(self):
        first = self.source("合成机构甲", "institution")
        second = self.source("合成机构乙", "institution")
        rid = self.record(research_subjects=self.subjects(("institution", first), ("institution", second)))
        original = {s["id"]: s for s in self.detail(rid)["research_subjects"]}
        history_id = self.clients["researcher"].get("/api/history/record/" + rid).json["items"][-1]["id"]
        unsafe = self.call("/api/sources/" + first, {"version": 1, "kind": "journal"}, method="PUT")
        self.assertEqual(unsafe.status_code, 409, unsafe.json)
        self.merge("source", first, second)
        current = self.detail(rid)
        self.assertEqual({s["id"] for s in current["research_subjects"]}, set(original))
        self.assertEqual({s["subject_id"] for s in current["research_subjects"]}, {first})
        self.assertEqual({s["original_subject_id"] for s in current["research_subjects"]}, {first, second})
        self.assertEqual({s["manual_revision"] for s in current["research_subjects"]}, {1})
        self.assertEqual(self.notes("institution", first)["total"], 1)
        same_selection = self.call("/api/records/" + rid + "/research-subjects", {
            "version": current["version"], "research_subjects": self.subjects(("institution", first))}, method="PUT")
        self.assertEqual(same_selection.status_code, 200, same_selection.json)
        current = self.detail(rid)
        self.assertEqual({s["id"] for s in current["research_subjects"]}, set(original))
        restored = self.call(f"/api/history/{history_id}/restore", {"version": current["version"]})
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual(len(self.detail(rid)["research_subjects"]), 2)
        other = self.record(research_subjects=self.subjects(("institution", first)))
        other_relation = self.detail(other)["research_subjects"][0]
        self.merge("record", rid, other, who="researcher")
        merged = self.detail(rid)
        self.assertEqual(len(merged["research_subjects"]), 3)
        moved = next(s for s in merged["research_subjects"] if s["id"] == other_relation["id"])
        self.assertEqual((moved["original_note_id"], moved["note_id"]), (other, rid))
        self.assertEqual(self.notes("institution", first)["total"], 1)
        events = self.clients["researcher"].get("/api/records/" + rid + "/research-subjects/history").json["items"]
        self.assertIn("source_merge", [h["action"] for h in events])
        self.assertIn("record_merge", [h["action"] for h in events])

    def test_private_notes_leave_identical_empty_profile_results_and_fixed_report_citations_remain_pinned(self):
        first, empty_person = self.person(), self.person("无笔记的人物")
        institute = self.source("私有关系合成机构", "institution")
        journal = self.source("私有关系合成期刊", "journal")
        original = self.record(kind="report", title="引用原文", body_html="<p>原文初稿</p>")
        rid = self.record(title="隐藏笔记独有题名", abstract="隐藏笔记独有摘要", visibility="restricted",
            evidence_record_id=original, quote="固定摘录", locator="合成第1页", interpretation="初始分析", body_html="<p>独立判断</p>",
            research_subjects=self.subjects(("person", first), ("institution", institute), ("journal", journal)))
        report = self.record(kind="research_report", title="采用笔记的报告", evidence_ids=[rid], body_html="<p>报告结论</p>")
        fixed = self.detail(report)["evidence_citations"][0]
        for kind, sid in [("person", first), ("institution", institute), ("journal", journal)]:
            self.assertEqual(self.notes(kind, sid, "colleague"), {"items": [], "total": 0})
        self.assertEqual(self.notes("person", first, "colleague"), self.notes("person", empty_person, "colleague"))
        client = self.clients["colleague"]
        self.assertEqual(client.get("/api/records?q=隐藏笔记独有").json["total"], 0)
        self.assertEqual(client.get("/api/records/" + rid).status_code, 404)
        self.assertEqual(client.get("/api/records/" + rid + "/research-subjects/history").status_code, 404)
        self.assertEqual(client.get("/api/history/record/" + rid).status_code, 404)
        changed = self.call("/api/records/" + rid + "/research-subjects", {
            "version": 1, "research_subjects": self.subjects(("person", empty_person))}, method="PUT")
        self.assertEqual(changed.status_code, 200, changed.json)
        note = self.detail(rid)
        self.assertEqual((note["body_html"], note["interpretation"], note["quote"]), ("<p>独立判断</p>", "初始分析", "固定摘录"))
        current = self.detail(report)["evidence_citations"][0]
        self.assertEqual(current["snapshot"], fixed["snapshot"])
        self.assertEqual(current["excerpt_version"], 1)
        self.assertEqual(current["current_version"], 2)

    def test_full_backup_restores_relation_history_and_rejects_unresolvable_subjects(self):
        pid = self.person()
        rid = self.record(research_subjects=self.subjects(("person", pid)))
        before = self.detail(rid)["research_subjects"][0]
        removed = self.call("/api/records/" + rid + "/research-subjects", {"version": 1, "research_subjects": []}, method="PUT")
        self.assertEqual(removed.status_code, 200, removed.json)
        readded = self.call("/api/records/" + rid + "/research-subjects", {
            "version": 2, "research_subjects": self.subjects(("person", pid))}, method="PUT")
        self.assertEqual(readded.status_code, 200, readded.json)
        expected = self.detail(rid)
        expected_history = self.clients["researcher"].get("/api/records/" + rid + "/research-subjects/history").json
        archive = Path(self.temp.name) / "full.zip"
        with self.call("/api/backup", who="admin") as backup:
            self.assertEqual(backup.status_code, 200)
            archive.write_bytes(backup.data)
        restored = restore_backup(archive, Path(self.temp.name) / "restored")
        recovered = create_app(restored, testing=True)
        self.clients = {who: self.login(who, recovered) for who in self.clients}
        self.assertEqual(self.detail(rid)["research_subjects"], expected["research_subjects"])
        self.assertEqual(self.clients["researcher"].get("/api/records/" + rid + "/research-subjects/history").json, expected_history)
        self.assertEqual(self.notes("person", pid)["total"], 1)
        continued = self.call("/api/records/" + rid + "/research-subjects", {"version": 3, "research_subjects": []}, method="PUT")
        self.assertEqual(continued.status_code, 200, continued.json)
        self.assertNotEqual(expected["research_subjects"][0]["id"], before["id"])
        # Corruption is controlled fixture setup; acceptance/rejection uses the backup boundary.
        with zipfile.ZipFile(archive) as bundle:
            payloads = {name: bundle.read(name) for name in bundle.namelist() if name != "manifest.json"}
            manifest = json.loads(bundle.read("manifest.json"))
        broken_db = Path(self.temp.name) / "broken.sqlite3"
        broken_db.write_bytes(payloads["platform.sqlite3"])
        with closing(sqlite3.connect(broken_db)) as db:
            db.execute("UPDATE research_subjects SET subject_id='missing-person' WHERE status='confirmed'")
            db.commit()
        payloads["platform.sqlite3"] = broken_db.read_bytes()
        manifest["files"]["platform.sqlite3"] = {"bytes": len(payloads["platform.sqlite3"]),
            "sha256": hashlib.sha256(payloads["platform.sqlite3"]).hexdigest()}
        invalid = Path(self.temp.name) / "invalid.zip"
        with zipfile.ZipFile(invalid, "w") as bundle:
            for name, payload in payloads.items():
                bundle.writestr(name, payload)
            bundle.writestr("manifest.json", json.dumps(manifest))
        rejected = Path(self.temp.name) / "rejected"
        with self.assertRaises(ValueError):
            restore_backup(invalid, rejected)
        self.assertFalse(rejected.exists())

    def test_invalid_or_stale_subject_changes_roll_back_and_explicit_reconfirmation_is_audited(self):
        pid, second = self.person(), self.person("另一个对象")
        rid = self.record(research_subjects=self.subjects(("person", pid)))
        before = self.detail(rid)
        history_url = "/api/records/" + rid + "/research-subjects/history"
        history = self.clients["researcher"].get(history_url).json
        for subjects in [None, [{"subject_type": [], "subject_id": pid}],
                         [{"subject_type": "person", "subject_id": []}],
                         self.subjects(("person", second), ("person", "missing")),
                         [{**before["research_subjects"][0], "version": 0}]]:
            with self.subTest(subjects=subjects):
                rejected = self.call("/api/records/" + rid + "/research-subjects", {
                    "version": 1, "research_subjects": subjects}, method="PUT")
                self.assertIn(rejected.status_code, [400, 409], rejected.json)
                self.assertEqual(self.detail(rid)["research_subjects"], before["research_subjects"])
                self.assertEqual(self.detail(rid)["version"], 1)
                self.assertEqual(self.clients["researcher"].get(history_url).json, history)
        confirmed = self.call("/api/records/" + rid + "/research-subjects", {
            "version": 1, "research_subjects": [{**before["research_subjects"][0], "confirm": True}]}, method="PUT")
        self.assertEqual(confirmed.status_code, 200, confirmed.json)
        current = self.detail(rid)["research_subjects"][0]
        self.assertEqual((current["id"], current["version"], current["manual_revision"]),
                         (before["research_subjects"][0]["id"], 2, 2))
        self.assertEqual(self.clients["researcher"].get(history_url).json["items"][0]["action"], "manual")

    def test_late_history_failure_does_not_leave_new_relations_or_increment_versions(self):
        pid, second = self.person(), self.person("回滚对象")
        rid = self.record(research_subjects=self.subjects(("person", pid)))
        before = self.detail(rid)
        history_url = "/api/records/" + rid + "/research-subjects/history"
        history = self.clients["researcher"].get(history_url).json
        with closing(connect(self.data_dir / "platform.sqlite3")) as db:
            db.execute("CREATE TRIGGER reject_note_revision BEFORE INSERT ON revisions WHEN NEW.target_type='record' BEGIN SELECT RAISE(ABORT,'synthetic history failure'); END")
            db.commit()
        rejected = self.call("/api/records/" + rid + "/research-subjects", {
            "version": 1, "research_subjects": self.subjects(("person", second))}, method="PUT")
        self.assertEqual(rejected.status_code, 409, rejected.json)
        self.assertEqual(self.detail(rid)["research_subjects"], before["research_subjects"])
        self.assertEqual(self.detail(rid)["version"], 1)
        self.assertEqual(self.clients["researcher"].get(history_url).json, history)

    def test_cross_type_subject_correction_keeps_original_identity_in_history_and_full_recovery(self):
        pid = self.person()
        sid = self.source("跨类型合成机构", "institution")
        rid = self.record(research_subjects=self.subjects(("person", pid)))
        first = self.detail(rid)["research_subjects"][0]
        changed = self.call("/api/records/" + rid + "/research-subjects", {
            "version": 1, "research_subjects": [{**first, "subject_type": "institution", "subject_id": sid}]}, method="PUT")
        self.assertEqual(changed.status_code, 200, changed.json)
        current = self.detail(rid)["research_subjects"][0]
        self.assertEqual((current["id"], current["subject_type"], current["subject_id"]), (first["id"], "institution", sid))
        archive = Path(self.temp.name) / "cross-type.zip"
        with self.call("/api/backup", who="admin") as backup:
            self.assertEqual(backup.status_code, 200)
            archive.write_bytes(backup.data)
        restored = restore_backup(archive, Path(self.temp.name) / "cross-type-restored")
        recovered = create_app(restored, testing=True)
        self.clients = {who: self.login(who, recovered) for who in self.clients}
        relation = self.detail(rid)["research_subjects"][0]
        self.assertEqual((relation["original_subject_type"], relation["original_subject_id"]), ("person", pid))
        history = self.clients["researcher"].get("/api/records/" + rid + "/research-subjects/history").json["items"]
        self.assertEqual(history[-1]["snapshot"]["subject_type"], "person")
        self.assertEqual(history[0]["snapshot"]["subject_type"], "institution")
        self.assertEqual(history[0]["snapshot"]["original_subject_type"], "person")
        self.assertEqual(history[0]["snapshot"]["subject_name"], "跨类型合成机构")
        self.assertEqual(history[0]["snapshot"]["original_subject_name"], "合成人物甲")
        removed = self.call("/api/records/" + rid + "/research-subjects", {"version": 2, "research_subjects": []}, method="PUT")
        self.assertEqual(removed.status_code, 200, removed.json)
        forbidden_type = self.call("/api/records/" + rid, {"version": 3, "kind": "report"}, method="PUT")
        self.assertEqual(forbidden_type.status_code, 400, forbidden_type.json)

    def test_frozen_v6_upgrade_and_its_backup_preserve_legacy_history_without_clearing_new_subjects(self):
        fixtures = Path(__file__).parent / "fixtures"
        expected = json.loads((fixtures / "people_v5.json").read_text(encoding="utf-8"))
        legacy = Path(self.temp.name) / "legacy-v6"
        (legacy / "uploads").mkdir(parents=True)
        with closing(sqlite3.connect(legacy / "platform.sqlite3")) as db:
            db.executescript((fixtures / "people_v5.sql").read_text(encoding="utf-8"))
            db.executescript((fixtures / "note_subjects_v6.sql").read_text(encoding="utf-8"))
        for filename, content in expected["files"].items():
            (legacy / "uploads" / filename).write_text(content, encoding="utf-8", newline="")
        app = create_app(legacy, testing=True)
        self.clients = {who: self.login(who, app) for who in self.clients}
        self.assertEqual(self.clients["researcher"].get("/health").json["schema"], CURRENT_SCHEMA_VERSION)
        self.assertEqual(self.clients["researcher"].get("/api/people").json["total"], 1)
        pid = "person-v6-fixture"
        self.assertEqual(self.clients["researcher"].get("/api/people/" + pid).json["name"], "Frozen v6 synthetic person")
        rid = next(rid for rid, row in expected["records"].items() if row["kind"] == "research_note")
        current = self.detail(rid)
        self.assertEqual(current["research_subjects"], [])
        original_links = current["linked_records"]
        history_id = self.clients["researcher"].get("/api/history/record/" + rid).json["items"][-1]["id"]
        old = self.clients["researcher"].get("/api/history/" + str(history_id)).json["snapshot"]
        self.assertNotIn("research_subjects", old)
        changed = self.call("/api/records/" + rid + "/research-subjects", {
            "version": current["version"], "research_subjects": self.subjects(("person", pid))}, method="PUT")
        self.assertEqual(changed.status_code, 200, changed.json)
        relation = self.detail(rid)["research_subjects"]
        restored_history = self.call(f"/api/history/{history_id}/restore", {"version": current["version"] + 1})
        self.assertEqual(restored_history.status_code, 200, restored_history.json)
        self.assertEqual(self.detail(rid)["research_subjects"], relation)
        self.assertEqual(self.detail(rid)["linked_records"], original_links)
        backups = list((legacy / "backups").glob("*.zip"))
        self.assertEqual(len(backups), CURRENT_SCHEMA_VERSION - 6)
        restarted = create_app(legacy, testing=True)
        self.assertEqual(list((legacy / "backups").glob("*.zip")), backups)
        self.clients = {who: self.login(who, restarted) for who in self.clients}
        self.assertEqual(self.detail(rid)["research_subjects"], relation)
        for index, backup in enumerate(backups):
            recovered_dir = restore_backup(backup, Path(self.temp.name) / f"recovered-stage-{index}")
            recovered = create_app(recovered_dir, testing=True)
            self.clients = {who: self.login(who, recovered) for who in self.clients}
            self.assertEqual(self.clients["researcher"].get("/health").json["schema"], CURRENT_SCHEMA_VERSION)
            self.assertEqual(self.detail(rid)["research_subjects"], [])
            self.assertEqual(self.clients["researcher"].get("/api/people").json["total"], 1)
            add = self.call("/api/records/" + rid + "/research-subjects", {
                "version": self.detail(rid)["version"], "research_subjects": self.subjects(("person", pid))}, method="PUT")
            self.assertEqual(add.status_code, 200, add.json)

    def test_source_history_restore_checks_current_research_subject_type(self):
        sid = self.source("历史类型合成来源", "serial")
        history_id = self.clients["researcher"].get("/api/history/source/" + sid).json["items"][-1]["id"]
        corrected = self.call("/api/sources/" + sid, {"version": 1, "kind": "institution"}, method="PUT")
        self.assertEqual(corrected.status_code, 200, corrected.json)
        rid = self.record(research_subjects=self.subjects(("institution", sid)))
        denied = self.call(f"/api/history/{history_id}/restore", {"version": 2}, who="admin")
        self.assertEqual(denied.status_code, 409, denied.json)
        self.assertEqual(self.clients["researcher"].get("/api/sources/" + sid).json["kind"], "institution")
        self.assertEqual(self.notes("institution", sid)["items"][0]["id"], rid)
