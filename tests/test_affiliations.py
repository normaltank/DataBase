"""Employment and article affiliations through authenticated HTTP and backups."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from platform_app.web import create_app
from platform_app.maintenance import create_backup, restore_backup
from platform_app.store import CURRENT_SCHEMA_VERSION


class AffiliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wiki-affiliations-test-")
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"
        self.app = create_app(self.data_dir, testing=True)
        self.clients = {name: self.login(name) for name in ["researcher", "colleague", "admin"]}

    def login(self, name, app=None):
        client = (app or self.app).test_client()
        token = client.get("/api/session").json["csrf"]
        result = client.post("/api/login", json={"username": name, "password": "LocalDemo2026!"},
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

    def person(self, name="合成人物"):
        result = self.call("/api/people", {"name": name, "change_note": "合成人物主页"})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json["id"]

    def source(self, name="合成机构", kind="institution"):
        result = self.call("/api/sources", {"name": name, "kind": kind})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json["id"]

    def employments(self, pid, user="researcher"):
        return self.get(f"/api/people/{pid}/employments", user)

    def save_employments(self, pid, items, version=None, user="researcher"):
        if version is None:
            version = self.employments(pid, user)["version"]
        return self.call(f"/api/people/{pid}/employments", {"items": items, "version": version,
                         "change_note": "核查合成人物及机构履历页"}, user, "PUT")

    def employment(self, sid, role="研究员", start="", end=""):
        return {"institution_id": sid, "role": role, "start_date": start, "end_date": end,
                "evidence": "合成履历 https://example.org/profile#career"}

    def record(self, **extra):
        result = self.call("/api/records", {"kind": "report", "title": "合成文章", "authors": "同名作者；同名作者",
                         "body_html": "<p>原始正文</p>", **extra})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json["id"]

    def bylines(self, rid, people):
        current = self.get(f"/api/records/{rid}/bylines")
        result = self.call(f"/api/records/{rid}/bylines", {"version": current["version"], "record_version": current["record_version"],
            "change_note": "合成署名页", "items": [{"raw_name": "同名作者", "status": "confirmed", "target_type": "person",
            "target_id": pid, "evidence": "合成署名页的作者主页链接"} for pid in people]}, method="PUT")
        self.assertEqual(result.status_code, 200, result.json)
        return result.json["items"]

    def affiliations(self, rid, user="researcher"):
        return self.get(f"/api/records/{rid}/affiliations", user)

    def save_affiliations(self, rid, items, current=None, user="researcher"):
        current = current or self.affiliations(rid, user)
        return self.call(f"/api/records/{rid}/affiliations", {"version": current["version"],
            "record_version": current["record_version"], "byline_version": current["byline_version"],
            "change_note": "核查合成文章署名页", "items": items}, user, "PUT")

    def unit(self, bid, sid):
        return {"byline_id": bid, "institution_id": sid, "evidence": "合成文章首页 https://example.org/paper#authors"}

    def merge(self, kind, keep, duplicate):
        preview = self.call("/api/merge/preview", {"type": kind, "keep_id": keep, "duplicate_id": duplicate}, "admin")
        self.assertEqual(preview.status_code, 200, preview.json)
        self.assertTrue(preview.json["allowed"], preview.json)
        result = self.call("/api/merge", {"type": kind, "keep_id": keep, "duplicate_id": duplicate,
            "keep_version": preview.json["keep"]["version"], "duplicate_version": preview.json["duplicate"]["version"],
            "confirmed": True}, "admin")
        self.assertEqual(result.status_code, 200, result.json)

    def test_members_record_parallel_periods_and_unknown_dates_readable_at_both_ends(self):
        person, first, second = self.person(), self.source("第一机构"), self.source("第二机构")
        initial = self.employments(person)
        self.assertEqual(initial["items"], [])
        result = self.save_employments(person, [self.employment(first, start="2018", end="2020"),
            self.employment(first, role="高级研究员", start="2022-03"),
            self.employment(second, role="客座研究员"),
            self.employment(second, role="顾问", end="2024-02-29")], user="colleague")
        self.assertEqual(result.status_code, 200, result.json)
        rows = result.json["items"]
        self.assertEqual(len({row["id"] for row in rows}), 4)
        self.assertEqual([(row["start_date"], row["end_date"]) for row in rows],
                         [("2018", "2020"), ("2022-03", ""), ("", ""), ("", "2024-02-29")])
        self.assertEqual(rows[0]["person"]["name"], "合成人物")
        self.assertEqual(rows[0]["institution"]["name"], "第一机构")
        self.assertEqual(rows[0]["original_person_id"], person)
        self.assertEqual(rows[0]["selected_institution_id"], first)
        self.assertEqual(rows[0]["manual_revision"], 1)
        reverse = self.get(f"/api/sources/{second}/employments", "colleague")
        self.assertEqual(len(reverse["items"]), 2)
        history = self.get(f"/api/people/{person}/employments/history")["items"]
        self.assertEqual(len(history), 4)
        self.assertTrue(all(item["actor_id"] == "colleague" for item in history))
        self.assertTrue(all(item["change_note"] for item in history))
        self.assertEqual(self.app.test_client().get(f"/api/people/{person}/employments").status_code, 401)

    def test_article_units_belong_to_stable_bylines_and_never_follow_current_employment_or_publisher(self):
        first, second = self.person(), self.person()
        old, concurrent, new, publisher = [self.source(name) for name in ["旧机构", "同时署名单位", "新任职机构", "发布机构"]]
        rid = self.record(source_id=publisher)
        bylines = self.bylines(rid, [first, second])
        self.assertEqual(self.save_employments(first, [self.employment(old, start="2010", end="2019")]).status_code, 200)
        self.assertFalse(self.get(f"/api/records/{rid}", "colleague")["can_edit"])
        result = self.save_affiliations(rid, [self.unit(bylines[0]["id"], old), self.unit(bylines[0]["id"], concurrent),
            self.unit(bylines[1]["id"], old)], user="colleague")
        self.assertEqual(result.status_code, 200, result.json)
        before = result.json
        self.assertEqual([row["byline_id"] for row in before["items"]], [bylines[0]["id"], bylines[0]["id"], bylines[1]["id"]])
        self.assertEqual(before["items"][0]["byline"]["target_id"], first)
        self.assertEqual(before["items"][2]["byline"]["target_id"], second)
        self.assertEqual(self.save_employments(first, [self.employment(new, start="2020")]).status_code, 200)
        self.assertEqual(self.affiliations(rid), before)
        self.assertEqual(self.get(f"/api/sources/{publisher}/employments")["items"], [])
        self.assertEqual(self.get(f"/api/sources/{old}/affiliations")["total"], 2)
        history = self.get(f"/api/records/{rid}/affiliations/history")["items"]
        self.assertTrue(all(event["actor_id"] == "colleague" for event in history))
        record = self.get(f"/api/records/{rid}")
        self.assertEqual(record["body_html"], "<p>原始正文</p>")
        self.assertEqual(record["version"], 1)
        self.assertEqual(self.call(f"/api/records/{rid}", {"version": 1, "body_html": "<p>越权</p>"}, "colleague", "PUT").status_code, 403)

    def test_rejected_dates_stale_edits_and_relation_restore_keep_versions_and_removal_history(self):
        person, institution = self.person(), self.source()
        valid = self.employment(institution, start="2020-02", end="2020")
        first = self.save_employments(person, [valid])
        self.assertEqual(first.status_code, 200, first.json)
        item = first.json["items"][0]
        created = self.get(f"/api/people/{person}/employments/history")["items"][0]
        for extra in [{"start_date": "2023-02-29"}, {"end_date": "2019"}, {"start_date": "2020-13"},
                      {"start_date": "20"}, {"role": ""}, {"evidence": ""}]:
            self.assertEqual(self.save_employments(person, [{**item, **extra}]).status_code, 400)
            self.assertEqual(self.employments(person), first.json)
        changed = self.save_employments(person, [{**item, "role": "新角色"}], user="colleague")
        self.assertEqual(changed.status_code, 200, changed.json)
        stale = self.save_employments(person, [{**item, "role": "过期输入"}], version=first.json["version"])
        self.assertEqual(stale.status_code, 409)
        removed = self.save_employments(person, [])
        self.assertEqual(removed.status_code, 200)
        history = self.get(f"/api/people/{person}/employments/history")["items"]
        self.assertIsNotNone(history[0]["after"]["removed_at"])
        result = self.call(f"/api/people/{person}/employments/history/{created['id']}/restore",
            {"version": removed.json["version"], "change_note": "重新核实后恢复这一项"}, "colleague")
        self.assertEqual(result.status_code, 200, result.json)
        restored = result.json["items"][0]
        self.assertEqual(restored["id"], item["id"])
        self.assertEqual(restored["role"], "研究员")
        self.assertEqual(restored["manual_revision"], 4)
        self.assertIsNone(restored["removed_at"])

    def test_merges_keep_distinct_origins_and_system_revisions_while_type_and_body_restores_preserve_relations(self):
        person, keep_source = self.person(), self.source("保留机构")
        old_source = self.source("曾误记期刊", "journal")
        wrong_type = self.get(f"/api/history/source/{old_source}")["items"][-1]
        self.assertEqual(self.call(f"/api/sources/{old_source}", {"version": 1, "kind": "institution"}, method="PUT").status_code, 200)
        initial_employments = self.save_employments(person, [self.employment(old_source), self.employment(keep_source)])
        self.assertEqual(initial_employments.status_code, 200)
        type_restore = self.call(f"/api/history/{wrong_type['id']}/restore", {"version": 2}, "admin")
        self.assertEqual(type_restore.status_code, 400, type_restore.json)
        keep, duplicate = self.record(title="保留文章"), self.record(title="重复文章")
        bids = [self.bylines(rid, [person])[0]["id"] for rid in [keep, duplicate]]
        kept = self.save_affiliations(keep, [self.unit(bids[0], keep_source)])
        moved = self.save_affiliations(duplicate, [self.unit(bids[1], old_source)])
        self.assertEqual(kept.status_code, 200)
        self.assertEqual(moved.status_code, 200)
        self.merge("record", keep, duplicate)
        merged = self.affiliations(duplicate)
        self.assertEqual(merged["record_id"], keep)
        self.assertEqual({row["id"] for row in merged["items"]}, {kept.json["items"][0]["id"], moved.json["items"][0]["id"]})
        self.assertEqual(merged["items"][1]["origin_record_id"], duplicate)
        self.assertEqual(merged["items"][1]["byline_id"], bids[1])
        self.merge("source", keep_source, old_source)
        employments = self.employments(person)
        self.assertEqual(len(employments["items"]), 2)
        moved_employment = employments["items"][0]
        self.assertEqual(moved_employment["institution_id"], keep_source)
        self.assertEqual(moved_employment["original_institution_id"], old_source)
        self.assertEqual(moved_employment["selected_institution_id"], old_source)
        self.assertEqual(moved_employment["manual_revision"], 1)
        self.assertEqual(moved_employment["version"], 2)
        self.assertEqual(self.save_employments(person, initial_employments.json["items"], version=1).status_code, 409)
        unchanged = self.save_employments(person, employments["items"])
        self.assertEqual(unchanged.status_code, 200, unchanged.json)
        self.assertEqual(unchanged.json["items"][0]["manual_revision"], 1)
        self.assertEqual(unchanged.json["items"][0]["selected_institution_id"], old_source)
        units = self.affiliations(keep)
        moved_unit = units["items"][1]
        self.assertEqual(moved_unit["institution_id"], keep_source)
        self.assertEqual(moved_unit["original_institution_id"], old_source)
        self.assertEqual(moved_unit["manual_revision"], 1)
        self.assertEqual(moved_unit["version"], 3)
        no_change = self.save_affiliations(keep, units["items"])
        self.assertEqual(no_change.status_code, 200, no_change.json)
        self.assertEqual(no_change.json["items"][1]["manual_revision"], 1)
        self.assertEqual(no_change.json["items"][1]["selected_institution_id"], old_source)
        history = self.get(f"/api/records/{keep}/affiliations/history")["items"]
        self.assertEqual({event["change_kind"] for event in history}, {"manual", "record_merge", "source_merge"})
        current = self.get(f"/api/sources/{keep_source}")
        self.assertEqual(self.call(f"/api/sources/{keep_source}", {"version": current["version"], "kind": "journal"}, method="PUT").status_code, 400)
        body = self.get(f"/api/records/{keep}")
        earliest = self.get(f"/api/history/record/{keep}")["items"][-1]
        self.assertEqual(self.call(f"/api/history/{earliest['id']}/restore", {"version": body["version"]}).status_code, 200)
        self.assertEqual(self.affiliations(keep)["items"], units["items"])
        self.assertEqual(self.employments(person), unchanged.json)

    def test_complete_backup_restores_removed_and_transferred_relations_then_accepts_new_maintenance(self):
        person, old, keep = self.person(), self.source("旧机构"), self.source("保留机构")
        result = self.save_employments(person, [self.employment(old), self.employment(keep, role="客座")])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.save_employments(person, result.json["items"][:1]).status_code, 200)
        rid = self.record()
        bid = self.bylines(rid, [person])[0]["id"]
        self.assertEqual(self.save_affiliations(rid, [self.unit(bid, old)]).status_code, 200)
        self.merge("source", keep, old)
        before = self.employments(person), self.affiliations(rid)
        events = self.get(f"/api/people/{person}/employments/history"), self.get(f"/api/records/{rid}/affiliations/history")
        with self.call("/api/backup", user="admin") as response:
            self.assertEqual(response.status_code, 200)
            archive = Path(self.temp.name) / "all.zip"
            archive.write_bytes(response.data)
        recovered = restore_backup(archive, Path(self.temp.name) / "recovered")
        app = create_app(recovered, testing=True)
        self.clients = {name: self.login(name, app) for name in self.clients}
        self.assertEqual((self.employments(person), self.affiliations(rid)), before)
        self.assertEqual((self.get(f"/api/people/{person}/employments/history"), self.get(f"/api/records/{rid}/affiliations/history")), events)
        changed = self.save_employments(person, [{**before[0]["items"][0], "role": "恢复后维护"}], user="colleague")
        self.assertEqual(changed.status_code, 200, changed.json)
        self.assertEqual(changed.json["items"][0]["manual_revision"], 2)
        self.assertEqual(self.save_affiliations(rid, [], user="colleague").status_code, 200)
        self.assertEqual(self.affiliations(rid)["items"], [])

    def test_restore_rejects_forged_relation_history_even_with_valid_file_manifest(self):
        person, sid = self.person(), self.source()
        self.assertEqual(self.save_employments(person, [self.employment(sid)]).status_code, 200)
        with self.call("/api/backup", user="admin") as response:
            archive = Path(self.temp.name) / "good.zip"
            archive.write_bytes(response.data)
        with zipfile.ZipFile(archive) as zipped:
            files = {name: zipped.read(name) for name in zipped.namelist()}
        damaged = Path(self.temp.name) / "damaged.sqlite3"
        damaged.write_bytes(files["platform.sqlite3"])
        with closing(sqlite3.connect(damaged)) as db:
            db.execute("UPDATE affiliation_changes SET after_json='{}'")
            db.commit()
        files["platform.sqlite3"] = damaged.read_bytes()
        manifest = json.loads(files["manifest.json"])
        manifest["files"]["platform.sqlite3"] = {"bytes": len(files["platform.sqlite3"]), "sha256": hashlib.sha256(files["platform.sqlite3"]).hexdigest()}
        files["manifest.json"] = json.dumps(manifest).encode()
        corrupt = Path(self.temp.name) / "corrupt.zip"
        with zipfile.ZipFile(corrupt, "w") as zipped:
            for name, content in files.items():
                zipped.writestr(name, content)
        target = Path(self.temp.name) / "must-not-exist"
        with self.assertRaises(ValueError):
            restore_backup(corrupt, target)
        self.assertFalse(target.exists())

    def test_private_original_byline_stays_hidden_after_public_reassignment_and_backup(self):
        person, sid = self.person(), self.source()
        keep = self.record(title="公开后保留文章", visibility="restricted")
        hidden = self.record(title="Private original title", visibility="restricted", authors="Private original paragraph")
        public_bid = self.bylines(keep, [person])[0]["id"]
        current = self.get(f"/api/records/{hidden}/bylines")
        created = self.call(f"/api/records/{hidden}/bylines", {"version": current["version"], "record_version": current["record_version"],
            "change_note": "Private source evidence", "items": [{"raw_name": "Private byline fragment", "status": "confirmed",
            "target_type": "person", "target_id": person, "evidence": "Private byline evidence"}]}, method="PUT")
        self.assertEqual(created.status_code, 200)
        private_bid = created.json["items"][0]["id"]
        self.merge("record", keep, hidden)
        record = self.get(f"/api/records/{keep}")
        self.assertEqual(self.call(f"/api/records/{keep}", {"version": record["version"], "visibility": "shared"}, method="PUT").status_code, 200)
        first = self.save_affiliations(keep, [self.unit(public_bid, sid), self.unit(private_bid, sid)], user="admin")
        self.assertEqual(first.status_code, 200, first.json)
        revised = self.save_affiliations(keep, [first.json["items"][0], {**first.json["items"][1], "byline_id": public_bid}], user="admin")
        self.assertEqual(revised.status_code, 200, revised.json)
        for recovery in [False, True]:
            if recovery:
                with self.call("/api/backup", user="admin") as response:
                    archive = Path(self.temp.name) / "privacy.zip"
                    archive.write_bytes(response.data)
                restored = restore_backup(archive, Path(self.temp.name) / "privacy-restored")
                app = create_app(restored, testing=True)
                self.clients = {name: self.login(name, app) for name in self.clients}
            visible = self.affiliations(keep, "colleague")
            self.assertEqual(len(visible["items"]), 1)
            history = self.get(f"/api/records/{keep}/affiliations/history", "colleague")
            reverse = self.get(f"/api/sources/{sid}/affiliations", "colleague")
            self.assertEqual(reverse["total"], 1)
            for output in [visible, history, reverse]:
                self.assertNotIn("Private", json.dumps(output))
            saved = self.save_affiliations(keep, visible["items"], user="colleague")
            self.assertEqual(saved.status_code, 200, saved.json)
            self.assertEqual(len(self.affiliations(keep, "admin")["items"]), 2)

    def test_institution_published_works_exclude_general_associations_and_private_content(self):
        sid = self.source()
        published = self.record(title="真正发布作品", source_id=sid)
        self.record(title="一般相关资料", related_source_ids=[sid])
        self.record(title="私密发布作品", source_id=sid, visibility="restricted")
        result = self.get(f"/api/sources/{sid}/published-works", "colleague")
        self.assertEqual(result["total"], 1)
        self.assertEqual([item["id"] for item in result["items"]], [published])
        self.assertEqual(self.get(f"/api/sources/{sid}/employments")["items"], [])
        self.assertEqual(self.get(f"/api/sources/{sid}/affiliations")["items"], [])

    def test_wrong_types_cross_work_bylines_and_changed_authors_reject_atomically_and_reconfirm_is_explicit(self):
        person, institution, journal = self.person(), self.source(), self.source("期刊", "journal")
        rid, other = self.record(), self.record()
        bid, foreign = self.bylines(rid, [person])[0]["id"], self.bylines(other, [person])[0]["id"]
        for bad in [self.unit(foreign, institution), self.unit(bid, journal), {**self.unit(bid, institution), "evidence": ""}]:
            self.assertEqual(self.save_affiliations(rid, [self.unit(bid, institution), bad]).status_code, 400)
            self.assertEqual(self.affiliations(rid)["items"], [])
            self.assertEqual(self.affiliations(rid)["version"], 0)
        opened = self.affiliations(rid)
        current = self.get(f"/api/records/{rid}/bylines")
        self.assertEqual(self.call(f"/api/records/{rid}/bylines", {**current, "items": current["items"], "change_note": "同事复查署名"}, "colleague", "PUT").status_code, 200)
        self.assertEqual(self.save_affiliations(rid, [self.unit(bid, institution)], current=opened).status_code, 409)
        created = self.save_affiliations(rid, [self.unit(bid, institution)])
        self.assertEqual(created.status_code, 200)
        repeated = self.save_affiliations(rid, created.json["items"])
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json["items"][0]["manual_revision"], 1)
        reconfirmed = self.save_affiliations(rid, [{**repeated.json["items"][0], "reconfirm": True}])
        self.assertEqual(reconfirmed.status_code, 200)
        self.assertEqual(reconfirmed.json["items"][0]["manual_revision"], 2)
        self.assertEqual(self.app.test_client().get(f"/api/records/{rid}/affiliations/history").status_code, 401)
        hidden = self.record(visibility="restricted")
        self.assertEqual(self.clients["colleague"].get(f"/api/records/{hidden}/affiliations").status_code, 404)

    def test_storage_and_late_merge_failure_roll_back_rows_history_and_collection_versions(self):
        person, old, new = self.person(), self.source(), self.source("新机构")
        created = self.save_employments(person, [self.employment(old)])
        self.assertEqual(created.status_code, 200)
        before, events = self.employments(person), self.get(f"/api/people/{person}/employments/history")
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db:
            db.execute("CREATE TRIGGER fail_affiliation_history BEFORE INSERT ON affiliation_changes BEGIN SELECT RAISE(ABORT,'synthetic history fault'); END")
            db.commit()
        failed = self.save_employments(person, [{**created.json["items"][0], "institution_id": new}])
        self.assertEqual(failed.status_code, 409)
        self.assertEqual(self.employments(person), before)
        self.assertEqual(self.get(f"/api/people/{person}/employments/history"), events)
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db:
            db.execute("DROP TRIGGER fail_affiliation_history")
            db.commit()
        rid = self.record()
        bid = self.bylines(rid, [person])[0]["id"]
        self.assertEqual(self.save_affiliations(rid, [self.unit(bid, old)]).status_code, 200)
        units, unit_events = self.affiliations(rid), self.get(f"/api/records/{rid}/affiliations/history")
        preview = self.call("/api/merge/preview", {"type": "source", "keep_id": new, "duplicate_id": old}, "admin").json
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db:
            db.execute("CREATE TRIGGER fail_after_affiliation_move BEFORE INSERT ON merge_events BEGIN SELECT RAISE(ABORT,'synthetic late merge fault'); END")
            db.commit()
        result = self.call("/api/merge", {"type": "source", "keep_id": new, "duplicate_id": old,
            "keep_version": preview["keep"]["version"], "duplicate_version": preview["duplicate"]["version"], "confirmed": True}, "admin")
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.employments(person), before)
        self.assertEqual(self.get(f"/api/people/{person}/employments/history"), events)
        self.assertEqual(self.affiliations(rid), units)
        self.assertEqual(self.get(f"/api/records/{rid}/affiliations/history"), unit_events)

    def test_v8_backup_upgrade_preserves_existing_bylines_notes_and_empty_unknown_relationships(self):
        fixtures = Path(__file__).parent / "fixtures"
        expected = json.loads((fixtures / "affiliations_v8.json").read_text(encoding="utf-8"))
        person, sid, rid, note = [expected[key] for key in ["person_id", "source_id", "record_id", "note_id"]]
        # Frozen through the actual schema-8 commit, independent of current initialization.
        legacy = Path(self.temp.name) / "frozen-v8"
        (legacy / "uploads").mkdir(parents=True)
        with closing(sqlite3.connect(legacy / "platform.sqlite3")) as db:
            db.executescript((fixtures / "affiliations_v8.sql").read_text(encoding="utf-8"))
        archive = create_backup(legacy)
        target = restore_backup(archive, Path(self.temp.name) / "v8-recovered")

        def verify_upgrade(directory):
            app = create_app(directory, testing=True)
            self.clients = {name: self.login(name, app) for name in self.clients}
            self.assertEqual(self.get("/health")["schema"], CURRENT_SCHEMA_VERSION)
            bylines = self.get(f"/api/records/{rid}/bylines")
            self.assertEqual(bylines["raw_authors"], expected["raw_authors"])
            self.assertEqual(len(bylines["items"]), len(expected["bylines"]))
            for actual, frozen in zip(bylines["items"], expected["bylines"]):
                self.assertEqual({key: actual[key] for key in frozen}, frozen)
            note_data = self.get(f"/api/records/{note}")
            self.assertEqual({key: note_data[key] for key in expected["note_fields"]}, expected["note_fields"])
            self.assertEqual(len(note_data["research_subjects"]), len(expected["research_subjects"]))
            for actual, frozen in zip(note_data["research_subjects"], expected["research_subjects"]):
                self.assertEqual({key: actual[key] for key in frozen}, frozen)
            self.assertEqual(self.employments(person)["items"], [])
            self.assertEqual(self.affiliations(rid)["items"], [])

        verify_upgrade(target)
        backups = list((target / "backups").glob("*.zip"))
        self.assertEqual(len(backups), CURRENT_SCHEMA_VERSION - expected["schema_version"])
        archived_versions = set()
        for index, backup in enumerate(backups):
            intermediate = restore_backup(backup, Path(self.temp.name) / f"intermediate-{index}")
            with closing(sqlite3.connect(intermediate / "platform.sqlite3")) as db:
                archived_versions.add(int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]))
            verify_upgrade(intermediate)
        self.assertEqual(archived_versions, set(range(expected["schema_version"], CURRENT_SCHEMA_VERSION)))
        verify_upgrade(target)
        self.assertEqual(self.save_employments(person, [self.employment(sid)]).status_code, 200)
        saved = self.employments(person)
        bid = expected["bylines"][0]["id"]
        self.assertEqual(self.save_affiliations(rid, [self.unit(bid, sid)]).status_code, 200)
        units = self.affiliations(rid)
        oldest = self.get(f"/api/history/record/{rid}")["items"][-1]
        body = self.get(f"/api/records/{rid}")
        self.assertEqual(self.call(f"/api/history/{oldest['id']}/restore", {"version": body["version"]}).status_code, 200)
        self.assertEqual(self.employments(person), saved)
        self.assertEqual(self.affiliations(rid)["items"], units["items"])
        backups_before_restart = list((target / "backups").glob("*.zip"))
        app = create_app(target, testing=True)
        self.clients = {name: self.login(name, app) for name in self.clients}
        self.assertEqual(self.employments(person), saved)
        self.assertEqual(self.affiliations(rid)["items"], units["items"])
        self.assertEqual(list((target / "backups").glob("*.zip")), backups_before_restart)

    def test_removed_institution_byline_keeps_its_unit_trace_editable_after_author_type_correction(self):
        author, unit, rid = self.source("机构作者"), self.source("文章单位"), self.record()
        created = self.call(f"/api/records/{rid}/bylines", {"version": 0, "record_version": 1, "change_note": "合成机构署名",
            "items": [{"raw_name": "机构作者", "status": "confirmed", "target_type": "institution", "target_id": author, "evidence": "合成首页"}]}, method="PUT")
        self.assertEqual(created.status_code, 200)
        bid = created.json["items"][0]["id"]
        self.assertEqual(self.save_affiliations(rid, [self.unit(bid, unit)]).status_code, 200)
        current = self.get(f"/api/records/{rid}/bylines")
        self.assertEqual(self.call(f"/api/records/{rid}/bylines", {**current, "items": [], "change_note": "移除误认的机构署名"}, method="PUT").status_code, 200)
        self.assertEqual(self.call(f"/api/sources/{author}", {"version": 1, "kind": "journal"}, method="PUT").status_code, 200)
        current = self.affiliations(rid)
        self.assertTrue(current["items"][0]["byline"]["removed_at"])
        self.assertEqual(self.get(f"/api/sources/{unit}/affiliations")["total"], 0)
        self.assertEqual(self.save_affiliations(rid, [], user="colleague").status_code, 200)
        self.assertEqual(self.call(f"/api/sources/{unit}", {"version": 1, "kind": "journal"}, method="PUT").status_code, 200)
        original = self.get(f"/api/records/{rid}/affiliations/history")["items"][-1]
        current = self.affiliations(rid)
        result = self.call(f"/api/records/{rid}/affiliations/history/{original['id']}/restore", {**current, "change_note": "尝试恢复已不适用关系"})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.affiliations(rid), current)


if __name__ == "__main__":
    unittest.main()
