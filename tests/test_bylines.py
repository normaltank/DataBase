"""Ordered work bylines through member HTTP and portable backup boundaries."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from platform_app.web import create_app
from platform_app.maintenance import restore_backup
from platform_app.store import CURRENT_SCHEMA_VERSION


class BylineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wiki-byline-test-")
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"
        self.app = create_app(self.data_dir, testing=True)
        self.clients = {u: self.login(u) for u in ["researcher", "colleague", "admin"]}

    def login(self, user, app=None):
        client = (app or self.app).test_client()
        token = client.get("/api/session").json["csrf"]
        result = client.post("/api/login", json={"username": user, "password": "LocalDemo2026!"},
                             headers={"X-CSRF-Token": token})
        self.assertEqual(result.status_code, 200, result.json)
        return client

    def call(self, path, data=None, user="researcher", method="POST"):
        client = self.clients[user]
        return client.open(path, method=method, json=data or {},
                           headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]})

    def get(self, path, user="researcher"):
        result = self.clients[user].get(path)
        self.assertEqual(result.status_code, 200, result.json)
        return result.json

    def person(self, name="同名人物"):
        result = self.call("/api/people", {"name": name, "change_note": "合成人物主页"})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json["id"]

    def source(self, name="合成署名机构", kind="institution"):
        result = self.call("/api/sources", {"name": name, "kind": kind})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json["id"]

    def record(self, **extra):
        result = self.call("/api/records", {"kind": "report", "title": "合成原始资料",
            "authors": "A. Smith; Example Institute & 未知作者", "body_html": "<p>原始正文</p>", **extra})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json["id"]

    def bylines(self, rid, user="researcher"):
        return self.get("/api/records/" + rid + "/bylines", user)

    def save(self, rid, items, version=None, user="researcher", note="依据合成署名页逐项确认", record_version=None):
        current = self.bylines(rid, user) if version is None or record_version is None else None
        if version is None:
            version = current["version"]
        if record_version is None:
            record_version = current["record_version"]
        return self.call("/api/records/" + rid + "/bylines",
                         {"version": version, "record_version": record_version, "items": items, "change_note": note}, user, "PUT")

    def confirmed(self, fragment, target_id, target_type="person"):
        return {"raw_name": fragment, "target_type": target_type, "target_id": target_id,
                "status": "confirmed", "evidence": "合成作品署名页 https://example.org/byline"}

    def test_member_confirms_ordered_people_institution_and_pending_without_body_permission(self):
        person, other = self.person(), self.person()
        institution, publisher = self.source(), self.source("合成发布机构")
        rid = self.record(source_id=publisher)
        initial = self.bylines(rid, "colleague")
        self.assertEqual(initial["version"], 0)
        self.assertEqual(initial["items"], [])
        self.assertEqual(initial["raw_authors"], "A. Smith; Example Institute & 未知作者")
        self.assertTrue(initial["can_edit"])
        self.assertFalse(self.get("/api/records/" + rid, "colleague")["can_edit"])
        response = self.save(rid, [self.confirmed("A. Smith", person),
            self.confirmed("Example Institute", institution, "institution"),
            {"raw_name": "未知作者", "status": "pending"}, self.confirmed("A. Smith（共同署名）", person)],
            version=0, user="colleague")
        self.assertEqual(response.status_code, 200, response.json)
        current = self.bylines(rid)
        self.assertEqual([i["raw_name"] for i in current["items"]],
                         ["A. Smith", "Example Institute", "未知作者", "A. Smith（共同署名）"])
        self.assertEqual(len({i["id"] for i in current["items"]}), 4)
        self.assertEqual([i["position"] for i in current["items"]], [1, 2, 3, 4])
        self.assertEqual(current["items"][0]["target"]["id"], person)
        self.assertEqual(current["items"][1]["target"]["type"], "institution")
        self.assertIsNone(current["items"][2]["target"])
        for target, path in [(person, "/api/people/"), (institution, "/api/sources/")]:
            works = self.get(path + target + "/works", "colleague")
            self.assertEqual(works["total"], 1)
            self.assertEqual([i["id"] for i in works["items"]], [rid])
        self.assertEqual(self.get("/api/people/" + other + "/works")["total"], 0)
        self.assertEqual(self.get("/api/sources/" + publisher + "/works")["total"], 0)
        original = self.get("/api/records/" + rid)
        self.assertEqual(original["authors"], initial["raw_authors"])
        self.assertEqual(original["body_html"], "<p>原始正文</p>")
        self.assertEqual(self.call("/api/records/" + rid, {"version": original["version"],
            "body_html": "<p>越权正文</p>"}, "colleague", "PUT").status_code, 403)

    def test_correction_pending_removal_and_relation_restore_keep_identity_and_history(self):
        first, second = self.person("第一人物"), self.person("第二人物")
        rid = self.record()
        created = self.save(rid, [self.confirmed("A. Smith", first)])
        self.assertEqual(created.status_code, 200, created.json)
        relation = created.json["items"][0]
        changed = self.save(rid, [{**relation, **self.confirmed("A. Smith", second)}], user="colleague", note="核查后纠正同名误认")
        self.assertEqual(changed.status_code, 200, changed.json)
        self.assertEqual(changed.json["items"][0]["id"], relation["id"])
        self.assertEqual(changed.json["items"][0]["manual_revision"], 2)
        stale = self.save(rid, [relation], version=1, note="过期表单")
        self.assertEqual(stale.status_code, 409, stale.json)
        self.assertEqual(self.get("/api/people/" + first + "/works")["total"], 0)
        self.assertEqual(self.get("/api/people/" + second + "/works")["total"], 1)
        item = changed.json["items"][0]
        pending = self.save(rid, [{**item, "status": "pending", "target_type": "", "target_id": ""}], note="依据不足，退回待确认")
        self.assertEqual(pending.status_code, 200, pending.json)
        self.assertEqual(self.get("/api/people/" + second + "/works")["total"], 0)
        removed = self.save(rid, [], note="移除误拆分片段，保留历史")
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.bylines(rid)["items"], [])
        events = self.get("/api/records/" + rid + "/bylines/history", "colleague")["items"]
        self.assertEqual(len(events), 4)
        correction = next(e for e in events if e["change_note"] == "核查后纠正同名误认")
        self.assertEqual(correction["before"]["target_id"], first)
        self.assertEqual(correction["after"]["target_id"], second)
        self.assertEqual(correction["actor_id"], "colleague")
        self.assertEqual(correction["change_kind"], "manual")
        self.assertTrue(events[0]["after"]["removed_at"])
        restored = self.call(f"/api/records/{rid}/bylines/history/{correction['id']}/restore",
            {"version": removed.json["version"], "change_note": "恢复已核实的第二人物归属"}, user="colleague")
        self.assertEqual(restored.status_code, 200, restored.json)
        again = restored.json["items"][0]
        self.assertEqual(again["id"], relation["id"])
        self.assertEqual(again["manual_revision"], 5)
        self.assertEqual(again["original_target_id"], first)
        self.assertEqual(again["selected_target_id"], second)
        self.assertEqual(again["original_authors"], "A. Smith; Example Institute & 未知作者")
        self.assertEqual(self.get("/api/people/" + second + "/works")["total"], 1)
        self.assertEqual(self.get("/api/records/" + rid)["version"], 1)

    def test_search_counts_and_history_follow_current_record_visibility(self):
        person = self.person("Unique Researcher")
        shared, private = self.record(title="公开合成作品"), self.record(title="Private Secret Work", visibility="restricted")
        for rid in [shared, private]:
            result = self.save(rid, [self.confirmed("A. Smith", person)])
            self.assertEqual(result.status_code, 200, result.json)
        for user, expected in [("researcher", 2), ("admin", 2), ("colleague", 1)]:
            works = self.get("/api/people/" + person + "/works", user)
            self.assertEqual(works["total"], expected)
            search = self.clients[user].get("/api/records", query_string={"q": "Unique Researcher"})
            self.assertEqual(search.status_code, 200, search.json)
            self.assertEqual(search.json["total"], expected)
        for suffix in ["/bylines", "/bylines/history"]:
            self.assertEqual(self.clients["colleague"].get("/api/records/" + private + suffix).status_code, 404)
        self.assertEqual(self.save(private, [], version=1, record_version=1, user="colleague").status_code, 404)
        self.assertEqual(self.get("/api/people/" + person + "/works?q=Secret", "colleague")["items"], [])
        record = self.get("/api/records/" + shared)
        hidden = self.call("/api/records/" + shared, {"version": record["version"], "visibility": "restricted"}, method="PUT")
        self.assertEqual(hidden.status_code, 200, hidden.json)
        self.assertEqual(self.get("/api/people/" + person + "/works", "colleague")["total"], 0)
        self.assertNotIn("Private Secret", json.dumps(self.get("/api/people/" + person + "/history", "colleague")))
        self.assertEqual(self.app.test_client().get("/api/people/" + person + "/works").status_code, 401)

    def test_unverified_identity_and_wrong_types_are_rejected_without_partial_byline_save(self):
        person, journal = self.person(), self.source("合成期刊", "journal")
        rid = self.record()
        bad = [self.confirmed("个人", person), {**self.confirmed("期刊不能作机构作者", journal, "institution")}]
        self.assertEqual(self.save(rid, bad).status_code, 400)
        self.assertEqual(self.bylines(rid)["version"], 0)
        self.assertEqual(self.bylines(rid)["items"], [])
        for item in [self.confirmed("个人", "missing"), {**self.confirmed("个人", person), "evidence": ""},
                     {"raw_name": "个人", "status": "confirmed"}]:
            self.assertEqual(self.save(rid, [item]).status_code, 400)
        self.assertEqual(self.call("/api/records/" + rid + "/bylines", {"version": 0, "record_version": 1, "change_note": "漏列表"}, method="PUT").status_code, 400)
        note = self.record(kind="research_note")
        self.assertEqual(self.save(note, [], version=0, record_version=1).status_code, 400)

    def merge(self, kind, keep, duplicate):
        preview = self.call("/api/merge/preview", {"type": kind, "keep_id": keep, "duplicate_id": duplicate}, user="admin")
        self.assertEqual(preview.status_code, 200, preview.json)
        self.assertTrue(preview.json["allowed"], preview.json)
        result = self.call("/api/merge", {"type": kind, "keep_id": keep, "duplicate_id": duplicate,
            "keep_version": preview.json["keep"]["version"], "duplicate_version": preview.json["duplicate"]["version"],
            "confirmed": True}, user="admin")
        self.assertEqual(result.status_code, 200, result.json)
        return result.json

    def test_record_and_source_merge_preserve_bylines_and_raw_origins_then_body_restore_keeps_corrections(self):
        person = self.person()
        keep, duplicate = self.record(authors="Keep original paragraph"), self.record(authors="Duplicate original paragraph")
        old_source, new_source = self.source("旧署名机构"), self.source("保留署名机构")
        kept = self.save(keep, [self.confirmed("Keep fragment", person)])
        moved = self.save(duplicate, [self.confirmed("Duplicate fragment", person), self.confirmed("Institution", old_source, "institution")])
        self.assertEqual(kept.status_code, 200)
        self.assertEqual(moved.status_code, 200)
        old_ids = [i["id"] for i in kept.json["items"] + moved.json["items"]]
        self.merge("record", keep, duplicate)
        current = self.bylines(duplicate)
        self.assertEqual(current["record_id"], keep)
        self.assertEqual([i["id"] for i in current["items"]], old_ids)
        self.assertEqual([i["original_authors"] for i in current["items"]],
                         ["Keep original paragraph", "Duplicate original paragraph", "Duplicate original paragraph"])
        self.assertEqual(self.get("/api/people/" + person + "/works")["total"], 1)
        self.assertEqual(len(self.get("/api/people/" + person + "/works")["items"][0]["bylines"]), 2)
        self.assertEqual(self.save(keep, kept.json["items"], version=1).status_code, 409)
        self.merge("source", new_source, old_source)
        after = self.bylines(keep)
        institution = after["items"][-1]
        self.assertEqual(institution["id"], old_ids[-1])
        self.assertEqual(institution["target_id"], new_source)
        self.assertEqual(institution["selected_target_id"], old_source)
        self.assertEqual(institution["manual_revision"], 1)
        unchanged = self.save(keep, after["items"], note="仅复查列表，未更改转接关系")
        self.assertEqual(unchanged.status_code, 200, unchanged.json)
        self.assertEqual(unchanged.json["items"][-1]["manual_revision"], 1)
        self.assertEqual(unchanged.json["items"][-1]["selected_target_id"], old_source)
        after = unchanged.json
        self.assertEqual(self.get("/api/sources/" + old_source + "/works")["total"], 1)
        events = self.get("/api/records/" + keep + "/bylines/history")["items"]
        self.assertIn("record_merge", {e["change_kind"] for e in events})
        self.assertIn("source_merge", {e["change_kind"] for e in events})
        history = self.get("/api/history/record/" + keep)["items"]
        earliest = min((e for e in history if e["target_id"] == keep), key=lambda e: e["id"])
        body = self.get("/api/records/" + keep)
        restored = self.call(f"/api/history/{earliest['id']}/restore", {"version": body["version"]})
        self.assertEqual(restored.status_code, 200, restored.json)
        after_restore = self.bylines(keep)
        self.assertEqual(after_restore["items"], after["items"])
        self.assertEqual(after_restore["version"], after["version"])
        source = self.get("/api/sources/" + new_source)
        wrong = self.call("/api/sources/" + new_source, {"version": source["version"], "kind": "journal"}, method="PUT")
        self.assertEqual(wrong.status_code, 400, wrong.json)
        body = self.get("/api/records/" + keep)
        wrong = self.call("/api/records/" + keep, {"version": body["version"], "kind": "research_note"}, method="PUT")
        self.assertEqual(wrong.status_code, 409, wrong.json)

    def test_source_type_history_restore_cannot_invalidate_institution_authorship(self):
        sid = self.source("先误登记期刊后更正机构", "journal")
        before = self.get("/api/history/source/" + sid)["items"][-1]
        self.assertEqual(self.call("/api/sources/" + sid, {"version": 1, "kind": "institution"}, method="PUT").status_code, 200)
        rid = self.record()
        response = self.save(rid, [self.confirmed("Institute", sid, "institution")])
        self.assertEqual(response.status_code, 200, response.json)
        restored = self.call(f"/api/history/{before['id']}/restore", {"version": 2}, user="admin")
        self.assertEqual(restored.status_code, 400, restored.json)
        self.assertEqual(self.get("/api/sources/" + sid)["kind"], "institution")
        self.assertEqual(self.bylines(rid)["items"][0]["target_id"], sid)

    def test_backup_restores_relations_versions_removed_history_and_continued_correction(self):
        person, second = self.person(), self.person("恢复后纠正对象")
        keep, duplicate = self.record(authors="Kept byline"), self.record(authors="Original moved byline")
        first = self.save(keep, [self.confirmed("Keep", person)])
        moved = self.save(duplicate, [self.confirmed("Moved", person)])
        self.assertEqual(first.status_code, 200)
        self.assertEqual(moved.status_code, 200)
        self.merge("record", keep, duplicate)
        current = self.bylines(keep)
        self.assertEqual(self.save(keep, current["items"][1:]).status_code, 200)
        note = self.record(kind="research_note", title="两项能力一起恢复的研究笔记",
                           research_subjects=[{"subject_type": "person", "subject_id": person}])
        note_before = self.get("/api/records/" + note)
        note_history = self.get("/api/records/" + note + "/research-subjects/history")
        before = self.bylines(keep)
        events = self.get("/api/records/" + keep + "/bylines/history")
        with self.call("/api/backup", user="admin") as response:
            self.assertEqual(response.status_code, 200)
            archive = Path(self.temp.name) / "all.zip"
            archive.write_bytes(response.data)
        restored = restore_backup(archive, Path(self.temp.name) / "recovered")
        app = create_app(restored, testing=True)
        self.clients = {u: self.login(u, app) for u in self.clients}
        self.assertEqual(self.bylines(keep), before)
        self.assertEqual(self.get("/api/records/" + keep + "/bylines/history"), events)
        self.assertEqual(self.get("/api/records/" + note), note_before)
        self.assertEqual(self.get("/api/records/" + note + "/research-subjects/history"), note_history)
        item = before["items"][0]
        changed = self.save(keep, [{**item, **self.confirmed("Moved", second)}], user="colleague")
        self.assertEqual(changed.status_code, 200, changed.json)
        self.assertEqual(changed.json["items"][0]["id"], item["id"])
        self.assertEqual(self.get("/api/people/" + person + "/works")["total"], 0)
        self.assertEqual(self.get("/api/people/" + second + "/works")["total"], 1)

    def test_history_failure_rolls_back_entire_relation_set_and_version(self):
        first, second = self.person(), self.person("另一个人物")
        rid = self.record()
        created = self.save(rid, [self.confirmed("A", first)])
        self.assertEqual(created.status_code, 200)
        before, events = self.bylines(rid), self.get("/api/records/" + rid + "/bylines/history")
        # Controlled temporary storage fault; observations remain HTTP responses.
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db:
            db.execute("CREATE TRIGGER fail_byline_history BEFORE INSERT ON byline_changes BEGIN SELECT RAISE(ABORT,'synthetic history fault'); END")
            db.commit()
        failed = self.save(rid, [{**before["items"][0], **self.confirmed("Changed", second)}])
        self.assertEqual(failed.status_code, 409, failed.json)
        self.assertEqual(self.bylines(rid), before)
        self.assertEqual(self.get("/api/records/" + rid + "/bylines/history"), events)
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db:
            db.execute("DROP TRIGGER fail_byline_history")
            db.commit()
        self.assertEqual(self.save(rid, [{**before["items"][0], **self.confirmed("Changed", second)}]).status_code, 200)

    def test_merged_archived_visibility_filters_history_and_does_not_delete_hidden_relations(self):
        public_person, hidden_person = self.person("公开人物"), self.person("隐藏人物")
        keep = self.record(visibility="restricted", authors="Kept original")
        duplicate = self.record(visibility="restricted", authors="Hidden original paragraph")
        self.assertEqual(self.save(keep, [self.confirmed("Kept", public_person)]).status_code, 200)
        self.assertEqual(self.save(duplicate, [self.confirmed("Hidden fragment", hidden_person)]).status_code, 200)
        self.merge("record", keep, duplicate)
        record = self.get("/api/records/" + keep)
        self.assertEqual(self.call("/api/records/" + keep, {"version": record["version"], "visibility": "shared"}, method="PUT").status_code, 200)
        visible = self.bylines(keep, "colleague")
        self.assertEqual(len(visible["items"]), 1)
        history = self.get("/api/records/" + keep + "/bylines/history", "colleague")
        self.assertNotIn("Hidden", json.dumps(history))
        self.assertNotIn("Hidden", json.dumps(visible))
        self.assertEqual(self.get("/api/people/" + hidden_person + "/works", "colleague")["total"], 0)
        response = self.save(keep, [{**visible["items"][0], "evidence": "同事核查公开署名"}], user="colleague")
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(len(self.bylines(keep)["items"]), 2)
        self.assertEqual(self.get("/api/people/" + hidden_person + "/works")["total"], 1)

    def test_restore_rejects_dangling_polymorphic_byline_target_even_with_valid_manifest(self):
        person, rid = self.person(), self.record()
        self.assertEqual(self.save(rid, [self.confirmed("A", person)]).status_code, 200)
        with self.call("/api/backup", user="admin") as response:
            self.assertEqual(response.status_code, 200)
            archive = Path(self.temp.name) / "good.zip"
            archive.write_bytes(response.data)
        with zipfile.ZipFile(archive) as z:
            files = {n: z.read(n) for n in z.namelist()}
        damaged = Path(self.temp.name) / "damaged.sqlite3"
        damaged.write_bytes(files["platform.sqlite3"])
        with closing(sqlite3.connect(damaged)) as db:
            db.execute("UPDATE record_bylines SET target_id='nonexistent-person'")
            db.commit()
        files["platform.sqlite3"] = damaged.read_bytes()
        manifest = json.loads(files["manifest.json"])
        manifest["files"]["platform.sqlite3"] = {"bytes": len(files["platform.sqlite3"]),
            "sha256": hashlib.sha256(files["platform.sqlite3"]).hexdigest()}
        files["manifest.json"] = json.dumps(manifest).encode()
        corrupt = Path(self.temp.name) / "corrupt.zip"
        with zipfile.ZipFile(corrupt, "w") as z:
            for name, content in files.items():
                z.writestr(name, content)
        target = Path(self.temp.name) / "must-not-restore"
        with self.assertRaises(ValueError):
            restore_backup(corrupt, target)
        self.assertFalse(target.exists())

    def test_changed_original_byline_rejects_stale_relation_form_without_creating_a_person(self):
        rid, person = self.record(), self.person()
        opened = self.bylines(rid)
        self.assertEqual(self.call("/api/records/" + rid, {"version": 1, "authors": "Corrected raw paragraph"}, method="PUT").status_code, 200)
        stale = self.save(rid, [self.confirmed("Old fragment", person)], version=opened["version"], record_version=opened["record_version"])
        self.assertEqual(stale.status_code, 409, stale.json)
        self.assertEqual(self.bylines(rid)["items"], [])
        self.assertEqual(self.get("/api/people")["total"], 1)

    def test_restoring_removed_byline_reinserts_it_in_order_without_collapsing_positions(self):
        person, rid = self.person(), self.record()
        response = self.save(rid, [self.confirmed("First", person), self.confirmed("Second", person)])
        self.assertEqual(response.status_code, 200)
        first, second = response.json["items"]
        created = next(item for item in self.get("/api/records/" + rid + "/bylines/history")["items"] if item["after"]["id"] == first["id"])
        removed = self.save(rid, [second])
        self.assertEqual(removed.status_code, 200)
        restored = self.call(f"/api/records/{rid}/bylines/history/{created['id']}/restore",
                             {"version": removed.json["version"], "change_note": "恢复首项署名并保留第二项"})
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual([item["id"] for item in restored.json["items"]], [first["id"], second["id"]])
        self.assertEqual([item["position"] for item in restored.json["items"]], [1, 2])

    def test_public_byline_correction_keeps_personal_note_report_and_adopted_evidence_unchanged(self):
        first, second, rid = self.person(), self.person("纠正后的身份"), self.record()
        note = self.record(kind="research_note", title="有负责作者的摘录", evidence_record_id=rid,
                           quote="Original fixed quotation", locator="page 2", interpretation="Author's interpretation")
        report = self.record(kind="research_report", title="采用摘录的研究报告", evidence_ids=[note],
                             body_html="<p>Responsible author's conclusion.</p>")
        original, note_before, report_before = [self.get("/api/records/" + value) for value in [rid, note, report]]
        relation = self.save(rid, [self.confirmed("A. Smith", first)], user="colleague")
        self.assertEqual(relation.status_code, 200)
        corrected = self.save(rid, [{**relation.json["items"][0], **self.confirmed("A. Smith", second)}], user="colleague")
        self.assertEqual(corrected.status_code, 200, corrected.json)
        self.assertEqual(self.get("/api/records/" + rid), original)
        self.assertEqual(self.get("/api/records/" + note), note_before)
        self.assertEqual(self.get("/api/records/" + report), report_before)

    def test_late_legacy_merge_failure_rolls_back_byline_transfers_and_their_history(self):
        person = self.person()
        keep, duplicate = self.record(authors="Kept"), self.record(authors="Moved")
        self.assertEqual(self.save(keep, [self.confirmed("Keep", person)]).status_code, 200)
        self.assertEqual(self.save(duplicate, [self.confirmed("Move", person)]).status_code, 200)
        before = {rid: self.bylines(rid) for rid in [keep, duplicate]}
        history = {rid: self.get("/api/records/" + rid + "/bylines/history") for rid in before}
        preview = self.call("/api/merge/preview", {"type": "record", "keep_id": keep, "duplicate_id": duplicate}, user="admin")
        self.assertEqual(preview.status_code, 200)
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db:
            db.execute("CREATE TRIGGER fail_after_byline_move BEFORE INSERT ON merge_events BEGIN SELECT RAISE(ABORT,'synthetic late merge fault'); END")
            db.commit()
        failed = self.call("/api/merge", {"type": "record", "keep_id": keep, "duplicate_id": duplicate,
            "keep_version": preview.json["keep"]["version"], "duplicate_version": preview.json["duplicate"]["version"],
            "confirmed": True}, user="admin")
        self.assertEqual(failed.status_code, 409, failed.json)
        for rid in before:
            self.assertEqual(self.bylines(rid), before[rid])
            self.assertEqual(self.get("/api/records/" + rid + "/bylines/history"), history[rid])

    def test_intermediate_v6_and_v7_backups_upgrade_preserving_old_authors_without_matching(self):
        fixtures = Path(__file__).parent / "fixtures"
        expected = json.loads((fixtures / "people_v5.json").read_text(encoding="utf-8"))
        legacy = Path(self.temp.name) / "legacy-v6"
        (legacy / "uploads").mkdir(parents=True)
        with closing(sqlite3.connect(legacy / "platform.sqlite3")) as db:
            db.executescript((fixtures / "people_v5.sql").read_text(encoding="utf-8"))
            db.executescript((fixtures / "note_subjects_v6.sql").read_text(encoding="utf-8"))
        for filename, content in expected["files"].items():
            (legacy / "uploads" / filename).write_text(content, encoding="utf-8", newline="")
        upgraded = create_app(legacy, testing=True)
        self.clients = {u: self.login(u, upgraded) for u in self.clients}
        self.assertEqual(self.get("/health")["schema"], CURRENT_SCHEMA_VERSION)
        backups = list((legacy / "backups").glob("*.zip"))
        self.assertEqual(len(backups), 2)
        rid = next(rid for rid, record in expected["records"].items() if record["kind"] == "report")
        for index, archive in enumerate(backups):
            recovered_dir = restore_backup(archive, Path(self.temp.name) / ("stage-" + str(index)))
            app = create_app(recovered_dir, testing=True)
            self.clients = {u: self.login(u, app) for u in self.clients}
            self.assertEqual(self.get("/health")["schema"], CURRENT_SCHEMA_VERSION)
            self.assertEqual(self.get("/api/records/" + rid), expected["records"][rid])
            self.assertEqual(self.bylines(rid)["raw_authors"], expected["records"][rid]["authors"])
            self.assertEqual(self.bylines(rid)["items"], [])
            self.assertEqual(self.get("/api/people")["total"], 1)
            changed = self.save(rid, [self.confirmed("Frozen author", "person-v6-fixture")])
            self.assertEqual(changed.status_code, 200, changed.json)
            before_restart = self.bylines(rid)
            migration_backups = list((recovered_dir / "backups").glob("*.zip"))
            restarted = create_app(recovered_dir, testing=True)
            self.clients = {u: self.login(u, restarted) for u in self.clients}
            self.assertEqual(self.bylines(rid), before_restart)
            self.assertEqual(list((recovered_dir / "backups").glob("*.zip")), migration_backups)


if __name__ == "__main__":
    unittest.main()
