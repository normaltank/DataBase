"""Report citation context through member HTTP and portable exports."""
import io
import json
import zipfile

import unittest
import test_workflow as workflow_tests


class CitationContextTests(unittest.TestCase):
    setUp = workflow_tests.WorkflowTests.setUp
    login = workflow_tests.WorkflowTests.login
    call = workflow_tests.WorkflowTests.call
    record = workflow_tests.WorkflowTests.record
    detail = workflow_tests.WorkflowTests.detail
    source = workflow_tests.WorkflowTests.source
    def chain(self):
        original = self.record(title="固定原文")
        note = self.record("research_note", evidence_record_id=original, quote="原句", locator="第1段")
        report = self.record("research_report", evidence_ids=[note], evidence_citations=[
            {"excerpt_id": note, "stance": "contradicts", "claim_note": "反例限于样本甲"}])
        return original, note, report

    def test_roles_permissions_conflict_restore_and_export(self):
        original, note, report = self.chain()
        citation = self.detail(report)["evidence_citations"][0]
        self.assertEqual((citation["stance"], citation["claim_note"]), ("contradicts", "反例限于样本甲"))
        for role in ["supports", "qualifies", "background"]:
            version = self.detail(report)["version"]
            response = self.call("/api/records/"+report, {"version": version, "evidence_ids": [note],
                "evidence_citations": [{"excerpt_id": note, "stance": role, "claim_note": role}]}, method="PUT")
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(self.detail(report)["evidence_citations"][0]["stance"], role)
        payload = {"version": 1, "evidence_ids": [note], "evidence_citations": [{"excerpt_id": note, "stance": "supports"}]}
        self.assertEqual(self.call("/api/records/"+report, payload, method="PUT").status_code, 409)
        payload["version"] = 4
        self.assertEqual(self.call("/api/records/"+report, payload, user="colleague", method="PUT").status_code, 403)
        payload["evidence_citations"][0]["stance"] = "true"
        self.assertEqual(self.call("/api/records/"+report, payload, method="PUT").status_code, 400)
        history = self.clients["researcher"].get("/api/history/record/"+report).json["items"]
        self.assertEqual(self.call(f"/api/history/{history[-1]['id']}/restore", {"version":4}).status_code, 200)
        self.assertEqual(self.detail(report)["evidence_citations"][0]["stance"], "contradicts")

    def test_original_and_note_updates_remain_independent_until_explicit_refresh(self):
        original, note, report = self.chain()
        pinned = self.detail(report)["evidence_citations"][0]["snapshot"]
        self.assertEqual(self.call("/api/records/"+original, {"version":1, "title":"修订原文"}, method="PUT").status_code, 200)
        citation = self.detail(report)["evidence_citations"][0]
        self.assertEqual(citation["staleness_reasons"], ["original_updated"])
        self.assertEqual(citation["snapshot"], pinned)
        self.assertEqual(self.call("/api/records/"+note, {"version":1, "interpretation":"新解释"}, method="PUT").status_code, 200)
        self.assertEqual(set(self.detail(report)["evidence_citations"][0]["staleness_reasons"]), {"note_updated", "original_updated"})
        self.assertEqual(self.call("/api/records/"+report, {"version":1, "evidence_ids":[note], "refresh_citations":True}, method="PUT").status_code, 200)
        self.assertEqual(self.detail(report)["evidence_citations"][0]["staleness_reasons"], ["original_updated"])
        self.assertEqual(self.call("/api/records/"+note, {"version":2, "refresh_evidence":True}, method="PUT").status_code, 200)
        self.assertEqual(self.call("/api/records/"+report, {"version":2, "evidence_ids":[note], "refresh_citations":True}, method="PUT").status_code, 200)
        self.assertEqual(self.detail(report)["evidence_citations"][0]["staleness_reasons"], [])

    def person(self, name):
        result = self.call("/api/people", {"name":name, "change_note":"合成出处"})
        self.assertEqual(result.status_code,201,result.json)
        return result.json["id"]

    def save_byline(self, original, person):
        current = self.clients["researcher"].get("/api/records/"+original+"/bylines").json
        before = current["items"][0] if current["items"] else {}
        result = self.call("/api/records/"+original+"/bylines", {"version":current["version"], "record_version":current["record_version"],
            "items":[{**before,"raw_name":"作者甲","target_type":"person","target_id":person,"status":"confirmed","evidence":"https://example.org/byline"}],"change_note":"核查署名"},method="PUT")
        self.assertEqual(result.status_code,200,result.json)
        return result.json

    def test_byline_correction_and_restoration_change_identity_without_record_version(self):
        first, second = self.person("甲"), self.person("乙")
        original = self.record()
        self.save_byline(original, first)
        note = self.record("research_note", evidence_record_id=original, quote="原句", locator="第1段")
        report = self.record("research_report", evidence_ids=[note])
        pinned = self.detail(report)["evidence_citations"][0]["snapshot"]
        self.save_byline(original, second)
        self.assertEqual(self.detail(original)["version"],1)
        cited = self.detail(report)["evidence_citations"][0]
        self.assertEqual(cited["staleness_reasons"],["identity_changed"])
        self.assertEqual(cited["identity_baseline_status"],"recorded")
        self.save_byline(original, first)
        self.assertEqual(self.detail(report)["evidence_citations"][0]["staleness_reasons"],["identity_changed"])
        self.assertEqual(self.detail(report)["evidence_citations"][0]["snapshot"],pinned)

    def test_export_records_roles_reasons_and_registered_scope_warning(self):
        original, note, report = self.chain()
        self.call("/api/records/"+original, {"version":1,"title":"后来题名"},method="PUT")
        response = self.clients["researcher"].get("/api/export/content?kind=research_report")
        self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            coverage = json.loads(archive.read("evidence-coverage.json"))
            row = next(r for r in coverage["records"] if r["id"]==report)
            citation = row["citations"][0]
            self.assertEqual(citation["stance"],"contradicts")
            self.assertEqual(citation["claim_note"],"反例限于样本甲")
            self.assertEqual(citation["staleness_reasons"],["original_updated"])
            for path in ["review.html",row["path"]]:
                text = archive.read(path).decode()
                self.assertIn("反例限于样本甲",text)
                self.assertIn("原文已修订",text)
                self.assertIn("反例",text)

    def test_hidden_counterexample_neither_leaks_nor_disappears_when_authorized_colleague_saves(self):
        original, note, report = self.chain()
        self.call("/api/records/"+report, {"version":1,"editors":["colleague"]},method="PUT")
        self.call("/api/records/"+original, {"version":1,"visibility":"restricted"},method="PUT")
        public_note = self.record("research_note",title="可见支撑")
        self.call("/api/records/"+report, {"version":2,"evidence_ids":[note,public_note],"evidence_citations":[{"excerpt_id":public_note,"stance":"supports"}]},method="PUT")
        public = self.detail(report,"colleague")
        self.assertEqual([c["excerpt_id"] for c in public["evidence_citations"]],[public_note])
        self.assertNotIn(note,json.dumps(public))
        result = self.call("/api/records/"+report,{"version":3,"evidence_ids":[public_note]},user="colleague",method="PUT")
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(len(self.detail(report)["evidence_citations"]),2)

    def test_person_merge_split_subject_review_and_profile_prose_are_distinct(self):
        from test_person_identity import PersonIdentityTests
        first, second = self.person("甲身份"), self.person("乙身份")
        original = self.record()
        self.save_byline(original,second)
        note = self.record("research_note", evidence_record_id=original,quote="原句",locator="第1段",
                           research_subjects=[{"subject_type":"person","subject_id":second}])
        report = self.record("research_report",evidence_ids=[note])
        pinned = self.detail(report)["evidence_citations"][0]["snapshot"]
        profile = self.clients["researcher"].get("/api/people/"+second).json
        self.assertEqual(self.call("/api/people/"+second,{"version":profile["version"],"introduction_html":"<p>新介绍</p>","change_note":"补介绍"},method="PUT").status_code,200)
        self.assertEqual(self.detail(report)["evidence_citations"][0]["staleness_reasons"],[])
        preview = self.call("/api/people/merge-preview",{"keep_id":first,"duplicate_id":second})
        self.assertEqual(preview.status_code,200,preview.json)
        merged = self.call("/api/people/merge",PersonIdentityTests.intent(self,preview.json))
        self.assertEqual(merged.status_code,200,merged.json)
        self.assertIn("identity_changed",self.detail(report)["evidence_citations"][0]["staleness_reasons"])
        event = merged.json["event_id"]
        split_preview = self.call(f"/api/people/identity-events/{event}/split-preview")
        split = self.call("/api/people/split",{"preview_id":split_preview.json["preview_id"],"idempotency_key":"i42-split","confirmed":True,"evidence":"合成反证"})
        self.assertEqual(split.status_code,200,split.json)
        cited = self.detail(report)["evidence_citations"][0]
        self.assertIn("identity_changed",cited["staleness_reasons"])
        self.assertEqual(cited["snapshot"],pinned)
        self.assertEqual(self.detail(original)["version"],1)
        # A subject attached to the surviving identity after merge needs explicit review on split.
        preview = self.call("/api/people/merge-preview",{"keep_id":first,"duplicate_id":second}).json
        merged = self.call("/api/people/merge",PersonIdentityTests.intent(self,preview,key="i42-again")).json
        later = self.record("research_note",research_subjects=[{"subject_type":"person","subject_id":first}])
        later_report = self.record("research_report",evidence_ids=[later])
        event = merged["event_id"]
        preview = self.call(f"/api/people/identity-events/{event}/split-preview").json
        split = self.call("/api/people/split",{"preview_id":preview["preview_id"],"idempotency_key":"i42-split-again","confirmed":True,"evidence":"另一次反证"})
        self.assertEqual(split.status_code,200,split.json)
        current = self.detail(later)
        self.assertEqual(current["research_subjects"][0]["status"],"needs_review")
        self.assertIn("identity_changed",self.detail(later_report)["evidence_citations"][0]["staleness_reasons"])
        subjects = [{**current["research_subjects"][0],"confirm":True}]
        self.assertEqual(self.call("/api/records/"+later+"/research-subjects",{"version":current["version"],"research_subjects":subjects},method="PUT").status_code,200)
        self.assertIn("identity_changed",self.detail(later_report)["evidence_citations"][0]["staleness_reasons"])

    def test_article_unit_change_is_independent_of_person_employment(self):
        person = self.person("单位作者")
        original = self.record()
        byline = self.save_byline(original,person)["items"][0]
        unit = self.source("合成文章单位","institution")
        note = self.record("research_note",evidence_record_id=original,quote="原句",locator="第1段")
        report = self.record("research_report",evidence_ids=[note])
        current = self.clients["researcher"].get("/api/records/"+original+"/affiliations").json
        response = self.call("/api/records/"+original+"/affiliations",{**current,"items":[{"byline_id":byline["id"],"institution_id":unit,"evidence":"文章首页"}],"change_note":"登记首页单位"},method="PUT")
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.detail(original)["version"],1)
        self.assertEqual(self.detail(report)["evidence_citations"][0]["staleness_reasons"],["identity_changed"])

    def merge_records(self, keep, duplicate):
        response = self.call("/api/merge/preview",{"type":"record","keep_id":keep,"duplicate_id":duplicate},user="admin")
        self.assertEqual(response.status_code,200,response.json)
        p = response.json
        return self.call("/api/merge",{"type":"record","keep_id":keep,"duplicate_id":duplicate,
            "keep_version":p["keep"]["version"],"duplicate_version":p["duplicate"]["version"],"confirmed":True},user="admin")

    def test_continuous_original_merges_use_fixed_old_identifier_and_history(self):
        original, note, report = self.chain()
        next_original = self.record(title="合并主原文")
        third = self.record(title="最终原文")
        self.assertEqual(self.merge_records(next_original,original).status_code,200)
        self.assertEqual(self.merge_records(third,next_original).status_code,200)
        cited = self.detail(report)["evidence_citations"][0]
        self.assertIn("original_merged",cited["staleness_reasons"])
        self.assertEqual(cited["current_original_id"],third)
        self.assertEqual(cited["snapshot"]["evidence_record_id"],original)
        self.assertNotIn("original_updated",cited["staleness_reasons"])
        historical = self.clients["researcher"].get("/api/history/record/"+report).json["items"][-1]
        version = self.detail(report)["version"]
        self.assertEqual(self.call(f"/api/history/{historical['id']}/restore",{"version":version}).status_code,200)
        self.assertIn("original_merged",self.detail(report)["evidence_citations"][0]["staleness_reasons"])
        # Adopting a later note does not accept a new original baseline.
        current = self.detail(report)
        self.assertEqual(self.call("/api/records/"+report,{"version":current["version"],"evidence_ids":[note],"refresh_citations":True},method="PUT").status_code,200)
        reasons = self.detail(report)["evidence_citations"][0]["staleness_reasons"]
        self.assertIn("original_merged",reasons)
        self.assertNotIn("original_updated",reasons)

    def test_different_roles_block_report_merge_atomically(self):
        note = self.record("research_note")
        first = self.record("research_report",editors=["admin"],evidence_ids=[note],evidence_citations=[{"excerpt_id":note,"stance":"supports","claim_note":"判断甲"}])
        second = self.record("research_report",editors=["admin"],evidence_ids=[note],evidence_citations=[{"excerpt_id":note,"stance":"qualifies","claim_note":"判断乙"}])
        self.assertEqual(self.merge_records(first,second).status_code,409)
        self.assertEqual(self.detail(first)["evidence_citations"][0]["stance"],"supports")
        self.assertEqual(self.detail(second)["evidence_citations"][0]["stance"],"qualifies")
        self.assertEqual(self.detail(second)["previous_ids"],[])

    def test_frozen_schema11_upgrade_unknown_history_restart_and_complete_restore(self):
        import sqlite3
        from pathlib import Path
        from contextlib import closing
        from platform_app.web import create_app
        from platform_app.maintenance import create_backup, restore_backup
        from platform_app.store import CURRENT_SCHEMA_VERSION
        fixtures = Path(__file__).parent/"fixtures"
        expected = json.loads((fixtures/"citations_v11.json").read_text())
        old = Path(self.temp.name)/"frozen11"
        old.mkdir();(old/"uploads").mkdir()
        with closing(sqlite3.connect(old/"platform.sqlite3")) as db:
            db.executescript((fixtures/"citations_v11.sql").read_text())
        target = restore_backup(create_backup(old),Path(self.temp.name)/"old-restored")
        upgraded = create_app(target,testing=True)
        self.clients = {name:self.login(name,upgraded) for name in self.clients}
        report = expected["report"]
        citation = self.detail(report)["evidence_citations"][0]
        self.assertEqual(citation["stance"],"unclassified")
        self.assertEqual(citation["identity_baseline_status"],"unknown")
        backups = list((target/"backups").glob("*.zip"))
        self.assertEqual(len(backups),CURRENT_SCHEMA_VERSION-11)
        archived_versions = set()
        for index, backup in enumerate(backups):
            before = restore_backup(backup,Path(self.temp.name)/f"before-upgrade-{index}")
            with closing(sqlite3.connect(before/"platform.sqlite3")) as db:
                archived_versions.add(int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]))
        self.assertEqual(archived_versions,set(range(11,CURRENT_SCHEMA_VERSION)))
        create_app(target,testing=True)
        self.assertEqual(len(list((target/"backups").glob("*.zip"))),len(backups))
        history = self.clients["researcher"].get("/api/history/record/"+report).json["items"][-1]
        self.assertEqual(self.call(f"/api/history/{history['id']}/restore",{"version":1}).status_code,200)
        self.assertEqual(self.detail(report)["evidence_citations"][0]["stance"],"unclassified")
        self.call("/api/records/"+report,{"version":2,"evidence_ids":[expected["note"]],"evidence_citations":[{"excerpt_id":expected["note"],"stance":"qualifies","claim_note":"旧材料范围"}]},method="PUT")
        restored = restore_backup(create_backup(target),Path(self.temp.name)/"new-restored")
        app = create_app(restored,testing=True)
        client = self.login("researcher",app)
        citation = client.get("/api/records/"+report).json["evidence_citations"][0]
        self.assertEqual((citation["stance"],citation["claim_note"]),("qualifies","旧材料范围"))
        self.assertEqual(citation["identity_baseline_status"],"unknown")

    def test_restore_rejects_malformed_citation_context(self):
        import sqlite3
        from platform_app.maintenance import create_backup, restore_backup
        from pathlib import Path
        original,note,report = self.chain()
        # Deliberately corrupt storage only to model an untrusted full backup.
        db = sqlite3.connect(self.data_dir/"platform.sqlite3")
        revision = db.execute("SELECT id,snapshot_json FROM revisions WHERE target_id=? ORDER BY id DESC LIMIT 1",(report,)).fetchone()
        state = json.loads(revision[1]);state["evidence_citations"][0]["stance"]="not-a-role"
        db.execute("UPDATE revisions SET snapshot_json=? WHERE id=?",(json.dumps(state),revision[0]));db.commit();db.close()
        with self.assertRaises(ValueError):
            restore_backup(create_backup(self.data_dir),Path(self.temp.name)/"invalid-restore")

    def test_identity_reason_names_endpoint_change_and_restored_relation_history(self):
        first, second = self.person("一"),self.person("二")
        original = self.record();self.save_byline(original,first)
        note = self.record("research_note",evidence_record_id=original,quote="原句",locator="段1")
        report = self.record("research_report",evidence_ids=[note])
        self.save_byline(original,second)
        self.assertEqual(self.detail(report)["evidence_citations"][0]["identity_changes"],[{"scope":"bylines","change":"endpoints_or_status"}])
        self.save_byline(original,first)
        self.assertEqual(self.detail(report)["evidence_citations"][0]["identity_changes"],[{"scope":"bylines","change":"relation_history"}])

    def test_aliases_cannot_assign_two_roles_to_the_same_note(self):
        keep = self.record("research_note",title="保留笔记",editors=["admin"])
        old = self.record("research_note",title="旧笔记",editors=["admin"])
        self.assertEqual(self.merge_records(keep,old).status_code,200)
        response = self.call("/api/records",{"kind":"research_report","title":"歧义引用","evidence_ids":[keep,old],
            "evidence_citations":[{"excerpt_id":keep,"stance":"supports"},{"excerpt_id":old,"stance":"contradicts"}]})
        self.assertEqual(response.status_code,400,response.json)

    def test_citation_upgrade_failure_keeps_preddl_backup_and_retryable_database(self):
        import sqlite3
        from contextlib import closing
        from pathlib import Path
        from platform_app.web import create_app
        from platform_app.evidence import SCHEMA_VERSION
        from platform_app.maintenance import restore_backup
        from platform_app.store import CURRENT_SCHEMA_VERSION
        legacy = Path(self.temp.name)/"failed-upgrade"
        legacy.mkdir();(legacy/"uploads").mkdir()
        fixture = Path(__file__).parent/"fixtures/citations_v11.sql"
        with closing(sqlite3.connect(legacy/"platform.sqlite3")) as db:
            db.executescript(fixture.read_text())
            db.execute(f"CREATE TRIGGER fail_citation_upgrade BEFORE UPDATE ON settings WHEN OLD.key='schema_version' AND NEW.value='{SCHEMA_VERSION}' BEGIN SELECT RAISE(ABORT,'synthetic citation migration failure'); END")
            db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            create_app(legacy,testing=True)
        with closing(sqlite3.connect(legacy/"platform.sqlite3")) as db:
            self.assertEqual(int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]),SCHEMA_VERSION-1)
            self.assertNotIn("stance",[r[1] for r in db.execute("PRAGMA table_info(evidence_links)")])
            db.execute("DROP TRIGGER fail_citation_upgrade");db.commit()
        backups = list((legacy/"backups").glob("*.zip"))
        self.assertEqual(len(backups),SCHEMA_VERSION-11)
        versions = set()
        for index,backup in enumerate(backups):
            restored = restore_backup(backup,Path(self.temp.name)/f"failed-backup-{index}")
            with closing(sqlite3.connect(restored/"platform.sqlite3")) as db:
                versions.add(int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]))
        self.assertEqual(versions,set(range(11,SCHEMA_VERSION)))
        app = create_app(legacy,testing=True)
        self.assertEqual(app.test_client().get("/health").json["schema"],CURRENT_SCHEMA_VERSION)

    def test_publication_snapshot_and_review_event_survive_citation_export_together(self):
        original = self.record(publication_title="合成期刊",volume="7",issue="2",pages="12–19",issn="1234-5678")
        note = self.record("research_note",evidence_record_id=original,quote="原句",locator="p12")
        report = self.record("research_report",evidence_ids=[note],evidence_citations=[{"excerpt_id":note,"stance":"qualifies","claim_note":"限该卷期"}])
        result = self.call("/api/review/record/"+report,{"version":1,"review_scope":"metadata_only","review_note":"核对合成题录"},user="admin")
        self.assertEqual(result.status_code,200,result.json)
        self.call("/api/records/"+original,{"version":1,"volume":"8"},method="PUT")
        report_data = self.detail(report)
        self.assertEqual(report_data["last_verified"]["version"],2)
        pinned = json.loads(report_data["evidence_citations"][0]["snapshot"]["evidence_snapshot_json"])
        self.assertEqual({key:pinned[key] for key in ["publication_title","volume","issue","pages","issn"]},
                         {"publication_title":"合成期刊","volume":"7","issue":"2","pages":"12–19","issn":"1234-5678"})
        output = self.clients["researcher"].get("/api/export/content?kind=research_report")
        self.assertEqual(output.status_code,200)
        with zipfile.ZipFile(io.BytesIO(output.data)) as archive:
            data = json.loads(archive.read("content.json"))
            rows = data["records"]
            row = next(r for r in rows if r["id"]==report)
            self.assertEqual(row["last_verified"]["review_note"],"核对合成题录")
            self.assertEqual(row["evidence_citations"][0]["stance"],"qualifies")
            coverage = json.loads(archive.read("evidence-coverage.json"))
            row = next(r for r in coverage["records"] if r["id"]==report)
            self.assertEqual(row["last_verified"]["version"],2)
            self.assertEqual(row["citations"][0]["staleness_reasons"],["original_updated"])

    def test_hidden_merged_origin_identity_details_and_changes_are_filtered_before_review(self):
        public_person, hidden_person, corrected = self.person("公开身份"),self.person("隐藏身份"),self.person("隐藏纠正身份")
        keep = self.record(title="公开后的主资料",visibility="restricted")
        old = self.record(title="隐藏来历原资料",visibility="restricted")
        self.save_byline(keep,public_person);self.save_byline(old,hidden_person)
        self.assertEqual(self.merge_records(keep,old).status_code,200)
        version = self.detail(keep)["version"]
        self.assertEqual(self.call("/api/records/"+keep,{"version":version,"visibility":"shared"},method="PUT").status_code,200)
        bylines = self.clients["researcher"].get("/api/records/"+keep+"/bylines").json
        hidden_byline = next(row for row in bylines["items"] if row["target_id"]==hidden_person)
        unit = self.source("隐藏来历署名单位","institution")
        current_units = self.clients["researcher"].get("/api/records/"+keep+"/affiliations").json
        result = self.call("/api/records/"+keep+"/affiliations",{**current_units,"items":[{"byline_id":hidden_byline["id"],"institution_id":unit,"evidence":"合成首页"}],"change_note":"登记单位"},method="PUT")
        self.assertEqual(result.status_code,200,result.json)
        note = self.record("research_note",evidence_record_id=keep,quote="可读原句",locator="段1")
        report = self.record("research_report",evidence_ids=[note])
        citation = self.detail(report,"colleague")["evidence_citations"][0]
        public_json = json.dumps(citation)
        self.assertNotIn(hidden_person,public_json);self.assertNotIn(old,public_json)
        self.assertNotIn(hidden_byline["id"],public_json)
        current = self.clients["researcher"].get("/api/records/"+keep+"/bylines").json
        hidden = next(row for row in current["items"] if row["target_id"]==hidden_person)
        hidden["target_id"]=corrected
        result = self.call("/api/records/"+keep+"/bylines",{**current,"change_note":"纠正隐藏来历署名"},method="PUT")
        self.assertEqual(result.status_code,200,result.json)
        self.assertIn("identity_changed",self.detail(report)["evidence_citations"][0]["staleness_reasons"])
        public = self.detail(report,"colleague")["evidence_citations"][0]
        self.assertEqual(public["staleness_reasons"],[])
        self.assertEqual(public["identity_changes"],[])
        self.assertNotIn(corrected,json.dumps(public))
