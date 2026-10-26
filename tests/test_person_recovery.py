"""Restore rejects re-signed semantic corruption before publishing a new directory."""
import base64
import hashlib
import json
import sqlite3
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

import test_person_identity as identity_tests
from platform_app.maintenance import create_backup, restore_backup
from platform_app.web import create_app
from platform_app.store import SCHEMA, CURRENT_SCHEMA_VERSION
from werkzeug.security import generate_password_hash


class PersonRecoveryTests(unittest.TestCase):
    setUp = identity_tests.PersonIdentityTests.setUp
    login = identity_tests.PersonIdentityTests.login
    call = identity_tests.PersonIdentityTests.call
    get = identity_tests.PersonIdentityTests.get
    person = identity_tests.PersonIdentityTests.person
    record = identity_tests.PersonIdentityTests.record
    source = identity_tests.PersonIdentityTests.source
    bylines = identity_tests.PersonIdentityTests.bylines
    image = identity_tests.PersonIdentityTests.image
    compare = identity_tests.PersonIdentityTests.compare
    intent = identity_tests.PersonIdentityTests.intent
    split_intent = identity_tests.PersonIdentityTests.split_intent
    download = identity_tests.PersonIdentityTests.download

    def assert_subset(self, expected, actual, location="response"):
        if isinstance(expected, dict):
            self.assertIsInstance(actual, dict, location)
            for key, value in expected.items():
                self.assertIn(key, actual, location + "." + key)
                self.assert_subset(value, actual[key], location + "." + key)
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected), location)
            for index, (old, new) in enumerate(zip(expected, actual)):
                self.assert_subset(old, new, f"{location}[{index}]")
        else:
            self.assertEqual(actual, expected, location)

    def damaged_backup(self, archive, name, mutate):
        root = Path(self.temp.name)
        with zipfile.ZipFile(archive) as bundle:
            files = {key: bundle.read(key) for key in bundle.namelist()}
        database = root / (name + ".sqlite3")
        database.write_bytes(files["platform.sqlite3"])
        with closing(sqlite3.connect(database)) as db:
            mutate(db)
            db.commit()
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        files["platform.sqlite3"] = database.read_bytes()
        manifest = json.loads(files["manifest.json"])
        manifest["files"]["platform.sqlite3"] = {"bytes": len(files["platform.sqlite3"]), "sha256": hashlib.sha256(files["platform.sqlite3"]).hexdigest()}
        files["manifest.json"] = json.dumps(manifest).encode()
        damaged = root / (name + ".zip")
        with zipfile.ZipFile(damaged, "w") as bundle:
            for key, value in files.items():
                bundle.writestr(key, value)
        return damaged

    def rejects(self, archive, name, mutate):
        damaged = self.damaged_backup(archive, name, mutate)
        target = Path(self.temp.name) / (name + "-recovered")
        with self.assertRaises(ValueError):
            restore_backup(damaged, target)
        self.assertFalse(target.exists())

    def test_restore_rejects_omitted_transferred_relations_in_otherwise_valid_identity_snapshots(self):
        first, second = self.person(), self.person("需恢复署名的另一人")
        work = self.record()
        self.bylines(work, [first, second])
        merged = self.call("/api/people/merge", self.intent(self.compare(first, second)))
        self.assertEqual(merged.status_code, 200, merged.json)
        archive = create_backup(self.data_dir)
        restore_backup(archive, Path(self.temp.name) / "valid-merge")
        self.rejects(archive, "missing-before-bylines", lambda db: db.execute("UPDATE person_identity_events SET before_json=json_set(before_json,'$.bylines',json('[]'))"))
        self.rejects(archive, "missing-both-bylines", lambda db: db.execute("UPDATE person_identity_events SET before_json=json_set(before_json,'$.bylines',json('[]')),after_json=json_set(after_json,'$.bylines',json('[]'))"))

    def test_restore_rejects_identity_retry_results_for_different_or_missing_people(self):
        first, second = self.person(), self.person("重试的另一人物")
        payload = self.intent(self.compare(first, second), key="retry-result-test")
        merged = self.call("/api/people/merge", payload)
        self.assertEqual(merged.status_code, 200)
        archive = create_backup(self.data_dir)
        self.rejects(archive, "missing-retry-person", lambda db: db.execute("UPDATE person_identity_requests SET result_json=json_set(result_json,'$.keep_id','missing-person')"))
        self.rejects(archive, "swapped-retry-person", lambda db: db.execute("UPDATE person_identity_requests SET result_json=json_set(result_json,'$.duplicate_id',?)", (first,)))

    def test_restore_rejects_dangling_subject_history_and_broken_versions_or_terminal_states(self):
        first, second = self.person(), self.person("历史改选人物")
        note = self.record(kind="research_note", research_subjects=[{"subject_type": "person", "subject_id": first}])
        current = self.get(f"/api/records/{note}")
        current["research_subjects"][0]["subject_id"] = second
        self.assertEqual(self.call(f"/api/records/{note}/research-subjects", {"version": current["version"], "research_subjects": current["research_subjects"]}, method="PUT").status_code, 200)
        current = self.get(f"/api/records/{note}")
        self.assertEqual(self.call(f"/api/records/{note}/research-subjects", {"version": current["version"], "research_subjects": []}, method="PUT").status_code, 200)
        archive = create_backup(self.data_dir)
        restore_backup(archive, Path(self.temp.name) / "valid-removed-subject")
        self.rejects(archive, "dangling-historical-subject", lambda db: db.execute("UPDATE research_subject_history SET snapshot_json=json_set(snapshot_json,'$.subject_id','missing-person') WHERE id=(SELECT min(id) FROM research_subject_history)"))
        for name, sql in [
                ("dangling-history-origin", "UPDATE research_subject_history SET snapshot_json=json_set(snapshot_json,'$.original_note_id','missing-note')"),
                ("subject-version-gap", "UPDATE research_subject_history SET snapshot_json=json_set(snapshot_json,'$.version',9) WHERE id=(SELECT min(id) FROM research_subject_history)"),
                ("subject-terminal-state", "UPDATE research_subject_history SET snapshot_json=json_set(snapshot_json,'$.status','confirmed') WHERE id=(SELECT max(id) FROM research_subject_history)")]:
            with self.subTest(name=name):
                self.rejects(archive, name, lambda db: db.execute(sql))

    def test_old_schema_restore_rejects_dangling_historical_avatars_before_publishing(self):
        legacy = Path(self.temp.name) / "legacy-real-v8"
        (legacy / "uploads").mkdir(parents=True)
        with closing(sqlite3.connect(legacy / "platform.sqlite3")) as db:
            db.executescript((Path(__file__).parent / "fixtures" / "affiliations_v8.sql").read_text(encoding="utf-8"))
        archive = create_backup(legacy)
        restore_backup(archive, Path(self.temp.name) / "valid-real-v8")
        self.rejects(archive, "old-history-avatar", lambda db: db.execute("UPDATE revisions SET snapshot_json=json_set(snapshot_json,'$.avatar_id','missing-avatar') WHERE target_type='person'"))

    def test_restore_rejects_a_byline_history_that_invents_the_previous_identity(self):
        first, second = self.person(), self.person("另一个合法人物")
        work = self.record()
        self.bylines(work, [first])
        state = self.get(f"/api/records/{work}/bylines")
        state["items"][0].update(target_id=second, evidence="明确更正为另一人")
        self.assertEqual(self.call(f"/api/records/{work}/bylines", {**state, "change_note": "纠正"}, method="PUT").status_code, 200)
        self.rejects(create_backup(self.data_dir), "invented-byline-before", lambda db: db.execute("UPDATE byline_changes SET before_json=json_set(before_json,'$.target_id',?) WHERE before_json IS NOT NULL", (second,)))

    def test_restore_rejects_missing_merge_dependencies_even_when_the_list_is_well_formed(self):
        first, second, third = self.person(), self.person("连续合并乙"), self.person("连续合并丙")
        early = self.call("/api/people/merge", self.intent(self.compare(first, second), key="dependency-early")).json
        later = self.call("/api/people/merge", self.intent(self.compare(first, third), key="dependency-later")).json
        archive = create_backup(self.data_dir)
        restore_backup(archive, Path(self.temp.name) / "valid-dependencies")
        self.rejects(archive, "omitted-dependency", lambda db: db.execute("UPDATE person_identity_events SET dependencies_json='[]' WHERE id=?", (later["event_id"],)))

    def test_recovered_inverse_splits_use_event_provenance_when_history_display_labels_change(self):
        first = self.person("原人物甲", introduction_html="<p>原介绍甲</p>")
        second, third = self.person("原人物乙"), self.person("原人物丙")
        choices = {"name": "duplicate", "original_name": "keep", "chinese_name": "keep", "introduction": "keep", "avatar": "keep"}
        early = self.call("/api/people/merge", self.intent(self.compare(first, second), key="label-early-merge", choices=choices)).json
        later = self.call("/api/people/merge", self.intent(self.compare(first, third), key="label-later-merge", choices=choices)).json
        profile = self.get(f"/api/people/{first}")
        saved = self.call(f"/api/people/{first}", {"version": profile["version"], "introduction_html": "<p>后来有据人工补充</p>",
                         "change_note": "保持真实后续编辑"}, method="PUT")
        self.assertEqual(saved.status_code, 200, saved.json)
        manual_revision = self.get(f"/api/people/{first}/history")["items"][0]["id"]

        def relabel(db):
            # A portable old archive may use translated history labels. No event,
            # person snapshot or relationship is changed by this presentation edit.
            for event in [early, later]:
                db.execute("UPDATE revisions SET action='Identity update' WHERE target_type='person' AND action LIKE ?", ("%" + event["event_id"],))
            db.execute("UPDATE revisions SET action='人物合并后的人工补记' WHERE id=?", (manual_revision,))

        archive = self.damaged_backup(create_backup(self.data_dir), "translated-history", relabel)
        target = restore_backup(archive, Path(self.temp.name) / "translated-history-recovered")
        self.clients = {who: self.login(who, create_app(target, testing=True)) for who in self.clients}
        result = self.call("/api/people/split", self.split_intent(later["event_id"], key="label-split-later"))
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.get(f"/api/people/{first}")["name"], "原人物乙")
        self.assertEqual(self.get(f"/api/people/{first}")["introduction_html"], "<p>后来有据人工补充</p>")
        # Also recognize a completed split after a second backup/restart, while
        # the next split has its own not-yet-complete event in the transaction.
        split_event = result.json["event_id"]
        archive = self.damaged_backup(create_backup(target), "translated-split-history", lambda db: db.execute(
            "UPDATE revisions SET action='Restored identities' WHERE target_type='person' AND action LIKE ?", ("%" + split_event,)))
        target = restore_backup(archive, Path(self.temp.name) / "translated-split-recovered")
        self.clients = {who: self.login(who, create_app(target, testing=True)) for who in self.clients}
        result = self.call("/api/people/split", self.split_intent(early["event_id"], key="label-split-early"))
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual([self.get(f"/api/people/{pid}")["name"] for pid in [first, second, third]], ["原人物甲", "原人物乙", "原人物丙"])
        self.assertEqual(self.get(f"/api/people/{first}")["introduction_html"], "<p>后来有据人工补充</p>")

    def test_fixed_real_v6_v7_v8_v9_histories_files_and_relations_restore_upgrade_restart_and_continue(self):
        fixtures = Path(__file__).parent / "fixtures"
        for version in [6, 7, 8, 9]:
            with self.subTest(schema=version):
                expected = json.loads((fixtures / f"person_delivery_v{version}.json").read_text(encoding="utf-8"))
                legacy = Path(self.temp.name) / f"fixed-real-v{version}"
                legacy.mkdir()
                with closing(sqlite3.connect(legacy / "platform.sqlite3")) as db:
                    db.executescript((fixtures / f"person_delivery_v{version}.sql").read_text(encoding="utf-8"))
                for name, info in expected["files"].items():
                    path = legacy / name
                    path.parent.mkdir(exist_ok=True)
                    path.write_bytes(base64.b64decode(info["base64"]))
                target = restore_backup(create_backup(legacy), Path(self.temp.name) / f"upgraded-real-v{version}")
                app = create_app(target, testing=True)
                self.clients = {who: self.login(who, app) for who in self.clients}
                self.assertEqual(self.get("/health")["schema"], CURRENT_SCHEMA_VERSION)
                for path, response in expected["responses"].items():
                    self.assert_subset(response, self.get(path), path)
                pid, work, note, report = [expected["ids"][key] for key in ["person", "work", "note", "report"]]
                self.assertEqual(self.get("/api/people")["total"], 2)
                profile = self.get(f"/api/people/{pid}")
                self.assertIsNone(profile["avatar"])
                historical = self.get(f"/api/people/{pid}/history")["items"]
                avatars = [row["snapshot"]["avatar"] for row in historical if row["snapshot"].get("avatar")]
                self.assertEqual(len(avatars), 2)
                for avatar in avatars:
                    self.assertEqual(hashlib.sha256(self.download(avatar["url"])).hexdigest(), avatar["sha256"])
                for name, info in expected["files"].items():
                    self.assertEqual(hashlib.sha256((target / name).read_bytes()).hexdigest(), info["sha256"])
                backups = sorted((target / "backups").glob("*.zip"))
                self.assertEqual(len(backups), CURRENT_SCHEMA_VERSION - version)
                self.clients = {who: self.login(who, create_app(target, testing=True)) for who in self.clients}
                self.assertEqual(sorted((target / "backups").glob("*.zip")), backups)
                fixed = self.get(f"/api/records/{report}")["evidence_citations"][0]["snapshot"]
                self.assertEqual(self.call(f"/api/people/{pid}", {"version": profile["version"], "change_note": "Continue using stable person identity", "introduction_html": "<p>After recovery.</p>"}, method="PUT").status_code, 200)
                current_note = self.get(f"/api/records/{note}")
                self.assertEqual(self.call(f"/api/records/{note}", {"version": current_note["version"], "translation": "Recovered translation draft preserves original evidence."}, method="PUT").status_code, 200)
                self.assertEqual(self.get(f"/api/records/{report}")["evidence_citations"][0]["snapshot"], fixed)
                self.assertEqual(self.get(f"/api/people/{pid}")["version"], profile["version"] + 1)
                # Independent relation writes reuse the restored identity and versions.
                byline = self.get(f"/api/records/{work}/bylines")
                byline["items"].append({"raw_name": "Recovered author", "target_type": "person", "target_id": pid, "status": "confirmed", "evidence": "Restored stable identity"})
                saved = self.call(f"/api/records/{work}/bylines", {**byline, "change_note": "Continue relation maintenance"}, method="PUT")
                self.assertEqual(saved.status_code, 200, saved.json)
                self.assertEqual(saved.json["items"][-1]["target_id"], pid)
                # Corruption of historical files/endpoints is rejected in each old schema.
                self.rejects(create_backup(legacy), f"v{version}-historical-avatar", lambda db: db.execute("UPDATE revisions SET snapshot_json=json_set(snapshot_json,'$.avatar_id','missing-avatar') WHERE target_type='person'"))

    def test_base_v1_and_generated_v2_v3_v4_backups_keep_legacy_records_files_history_and_author_confirmation(self):
        # A clearly labelled base-schema reconstruction, not a frozen historical app.
        legacy = Path(self.temp.name) / "reconstructed-base-v1"
        (legacy / "uploads").mkdir(parents=True)
        content = b"Reconstructed base-schema attachment.\n"
        stored = "a" * 32 + ".txt"
        (legacy / "uploads" / stored).write_bytes(content)
        with closing(sqlite3.connect(legacy / "platform.sqlite3")) as db:
            db.row_factory = sqlite3.Row
            db.executescript(SCHEMA)
            db.execute("INSERT INTO settings VALUES ('schema_version','1')")
            db.execute("INSERT INTO users(id,username,name,password_hash,role) VALUES ('researcher','researcher','研究员 · 林',?,'researcher')", (generate_password_hash("LocalDemo2026!"),))
            db.execute("INSERT INTO sources(id,name,kind,created_at,updated_at) VALUES ('BASE-INSTITUTE','Synthetic base institution','institution','2020','2020')")
            for rid, kind, title in [("BASE-ORIGINAL", "report", "Synthetic base original"), ("BASE-COMPILATION", "compilation", "Synthetic legacy personal report")]:
                db.execute("INSERT INTO records(id,kind,title,authors,source_id,owner_id,attachment_ids,created_at,updated_at) VALUES (?,?,?,'Original author text','BASE-INSTITUTE','researcher',?,'2020','2020')", (rid, kind, title, '["base-file"]' if rid == "BASE-ORIGINAL" else '[]'))
            db.execute("INSERT INTO attachments VALUES ('base-file','BASE-ORIGINAL','base.txt',?,?,?,'2020')", (stored, len(content), hashlib.sha256(content).hexdigest()))
            db.execute("INSERT INTO record_links VALUES ('BASE-COMPILATION','BASE-ORIGINAL')")
            db.execute("INSERT INTO collections VALUES ('BASE-COLLECTION','Synthetic base collection','','shared','researcher','2020')")
            db.execute("INSERT INTO collection_items VALUES ('BASE-COLLECTION','BASE-COMPILATION')")
            for row in db.execute("SELECT * FROM records").fetchall():
                snapshot = {**dict(row), "linked_ids": ["BASE-ORIGINAL"] if row["kind"] == "compilation" else []}
                db.execute("INSERT INTO revisions(target_type,target_id,action,actor_id,created_at,snapshot_json) VALUES ('record',?,'Synthetic historical record','researcher','2020',?)", (row["id"], json.dumps(snapshot)))
            db.commit()
        create_app(legacy, testing=True)
        versions = {}
        for index, archive in enumerate((legacy / "backups").glob("*.zip")):
            with zipfile.ZipFile(archive) as bundle:
                temporary = Path(self.temp.name) / f"migration-stage-{index}.sqlite3"
                temporary.write_bytes(bundle.read("platform.sqlite3"))
            with closing(sqlite3.connect(temporary)) as db:
                version = int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0])
            versions[version] = archive
        self.assertTrue({1, 2, 3, 4} <= versions.keys())
        for version in [1, 2, 3, 4]:
            with self.subTest(schema=version):
                target = restore_backup(versions[version], Path(self.temp.name) / f"restored-generated-v{version}")
                app = create_app(target, testing=True)
                self.clients = {who: self.login(who, app) for who in self.clients}
                self.assertEqual(self.get("/health")["schema"], CURRENT_SCHEMA_VERSION)
                self.assertEqual(self.get("/api/people")["total"], 0)
                original = self.get("/api/records/BASE-ORIGINAL")
                self.assertEqual((original["id"], original["authors"]), ("BASE-ORIGINAL", "Original author text"))
                self.assertEqual(self.download("/api/attachments/base-file"), content)
                self.assertEqual(self.get("/api/collections/BASE-COLLECTION")["items"][0]["id"], "BASE-COMPILATION")
                self.assertEqual(len(self.get("/api/history/record/BASE-ORIGINAL")["items"]), 1)
                personal = self.get("/api/records/BASE-COMPILATION")
                self.assertFalse(personal["author_confirmed"])
                self.assertEqual(self.call("/api/records/BASE-COMPILATION", {"version": personal["version"], "body_html": "<p>Unauthorized rewrite</p>"}, method="PUT").status_code, 403)
                self.assertEqual(self.call("/api/records/BASE-ORIGINAL", {"version": original["version"], "body_html": "<p>Continued legacy work</p>"}, method="PUT").status_code, 200)
                count = len(list((target / "backups").glob("*.zip")))
                self.clients = {who: self.login(who, create_app(target, testing=True)) for who in self.clients}
                self.assertEqual(self.get("/api/records/BASE-ORIGINAL")["body_html"], "<p>Continued legacy work</p>")
                self.assertEqual(len(list((target / "backups").glob("*.zip"))), count)


if __name__ == "__main__":
    unittest.main()
