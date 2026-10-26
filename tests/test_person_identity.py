"""Person identity comparison, merges and splits through HTTP and portable backups."""
import io
import hashlib
import json
import sqlite3
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from PIL import Image

from platform_app.web import create_app
from platform_app.maintenance import create_backup, restore_backup


class PersonIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wiki-identity-test-")
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"
        self.app = create_app(self.data_dir, testing=True)
        self.clients = {user: self.login(user) for user in ["researcher", "colleague", "admin"]}

    def login(self, user, app=None):
        client = (app or self.app).test_client()
        token = client.get("/api/session").json["csrf"]
        response = client.post("/api/login", json={"username": user, "password": "LocalDemo2026!"},
                               headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 200, response.json)
        return client

    def call(self, path, data=None, user="researcher", method="POST", image=None):
        client = self.clients[user]
        payload = {"json": data or {}}
        if image:
            payload = {"data": {"data": json.dumps(data), "file": (io.BytesIO(image), "synthetic.png")}}
        return client.open(path, method=method, **payload,
                           headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]})

    def get(self, path, user="researcher"):
        response = self.clients[user].get(path)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def download(self, url, user="researcher"):
        with self.clients[user].get(url) as response:
            self.assertEqual(response.status_code, 200)
            return response.data

    def person(self, name="合成人物甲", **extra):
        response = self.call("/api/people", {"name": name, "change_note": "合成作者主页", **extra})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["id"]

    def compare(self, keep, duplicate, user="researcher"):
        response = self.call("/api/people/merge-preview", {"keep_id": keep, "duplicate_id": duplicate}, user)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def intent(self, preview, key="synthetic-merge", **extra):
        return {"preview_id": preview["preview_id"], "idempotency_key": key, "confirmed": True,
                "evidence": "合成机构主页与作品署名共同确认是同一人",
                "choices": {"name": "keep", "original_name": "keep", "chinese_name": "keep",
                            "introduction": "duplicate", "avatar": "keep"}, **extra}

    def record(self, **extra):
        response = self.call("/api/records", {"kind": "report", "title": "合成原文", "body_html": "<p>原文保持</p>", **extra})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["id"]

    def source(self, name="合成任职机构"):
        response = self.call("/api/sources", {"name": name, "kind": "institution"})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["id"]

    def bylines(self, rid, people):
        current = self.get(f"/api/records/{rid}/bylines")
        response = self.call(f"/api/records/{rid}/bylines", {**current, "change_note": "合成首页的个人署名",
            "items": [{"raw_name": "同名作者" + str(index), "status": "confirmed", "target_type": "person",
                       "target_id": pid, "evidence": "合成作品作者主页"} for index, pid in enumerate(people)]}, method="PUT")
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def split_intent(self, event, key="synthetic-split", user="researcher"):
        preview = self.call(f"/api/people/identity-events/{event}/split-preview", user=user)
        self.assertEqual(preview.status_code, 200, preview.json)
        return {"preview_id": preview.json["preview_id"], "idempotency_key": key,
                "confirmed": True, "evidence": "合成反证，恢复两个身份"}

    def image(self, color):
        output = io.BytesIO()
        Image.new("RGB", (24, 24), color).save(output, format="PNG")
        return output.getvalue()

    def test_split_preserves_independent_corrections_removals_and_later_profile_fields(self):
        first = self.person("原人物甲", introduction_html="<p>原介绍甲</p>")
        second = self.person("原人物乙", introduction_html="<p>原介绍乙</p>")
        third = self.person("已核实的第三人")
        work = self.record()
        originals = self.bylines(work, [second, second, second])["items"]
        merged = self.call("/api/people/merge", self.intent(self.compare(first, second))).json
        current = self.get(f"/api/records/{work}/bylines")
        rows = current["items"]
        rows[1].update(target_id=third, evidence="独立核实为第三人")
        response = self.call(f"/api/records/{work}/bylines", {**current, "items": rows[:2], "change_note": "改归与解除"}, method="PUT")
        self.assertEqual(response.status_code, 200, response.json)
        # Moving away and back is still an independent decision, even at the same endpoint.
        current = response.json
        current["items"][1].update(target_id=first, evidence="再次核实为甲")
        self.assertEqual(self.call(f"/api/records/{work}/bylines", {**current, "change_note": "明确改回甲"}, method="PUT").status_code, 200)
        profile = self.get(f"/api/people/{first}")
        saved = self.call(f"/api/people/{first}", {"version": profile["version"], "introduction_html": "<p>合并后新介绍</p>",
            "avatar_source": "后续合成头像", "change_note": "独立补充介绍头像"}, method="PUT", image=self.image("green"))
        self.assertEqual(saved.status_code, 200, saved.json)
        preview = self.call(f"/api/people/identity-events/{merged['event_id']}/split-preview")
        self.assertTrue(preview.json["allowed"], preview.json)
        self.assertEqual({r["id"]: r["classification"] for r in preview.json["changes"]["bylines"]},
                         {originals[0]["id"]: "transferred", originals[1]["id"]: "corrected", originals[2]["id"]: "removed"})
        result = self.call("/api/people/split", self.split_intent(merged["event_id"]))
        self.assertEqual(result.status_code, 200, result.json)
        rows = self.get(f"/api/records/{work}/bylines")["items"]
        self.assertEqual([(r["id"], r["target_id"]) for r in rows], [(originals[0]["id"], second), (originals[1]["id"], first)])
        first_now = self.get(f"/api/people/{first}")
        self.assertEqual(first_now["introduction_html"], "<p>合并后新介绍</p>")
        self.assertEqual(self.download(first_now["avatar"]["url"]), self.image("green"))
        self.assertEqual(self.get(f"/api/people/{second}")["introduction_html"], "<p>原介绍乙</p>")

    def test_later_merge_must_split_first_and_system_split_versions_do_not_block_the_earlier_merge(self):
        first, second, fourth = self.person(), self.person("人物乙"), self.person("人物丁")
        work = self.record()
        self.bylines(work, [second, fourth])
        early = self.call("/api/people/merge", self.intent(self.compare(first, second), key="merge-first-pair")).json
        later = self.call("/api/people/merge", self.intent(self.compare(first, fourth), key="merge-second-pair")).json
        preview = self.call(f"/api/people/identity-events/{early['event_id']}/split-preview").json
        self.assertFalse(preview["allowed"])
        self.assertEqual([item["event_id"] for item in preview["split_order"]], [later["event_id"]])
        self.assertEqual(self.call("/api/people/split", self.split_intent(early["event_id"], key="early-rejected")).status_code, 409)
        self.assertEqual(self.call("/api/people/split", self.split_intent(later["event_id"], key="later-first")).status_code, 200)
        current = self.call(f"/api/people/identity-events/{early['event_id']}/split-preview").json
        self.assertTrue(current["allowed"], current)
        self.assertEqual(self.call("/api/people/split", self.split_intent(early["event_id"], key="early-after-later")).status_code, 200)
        self.assertEqual([row["target_id"] for row in self.get(f"/api/records/{work}/bylines")["items"]], [second, fourth])
        self.assertEqual([self.get(f"/api/people/{pid}")["id"] for pid in [first, second, fourth]], [first, second, fourth])

    def test_private_added_note_edges_allow_readable_member_review_without_blocking_or_leaking(self):
        first, second, third = self.person(), self.person("人物乙"), self.person("确定的其他人物")
        institute = self.source()
        journal = self.call("/api/sources", {"name": "合成期刊", "kind": "journal"}).json["id"]
        merged = self.call("/api/people/merge", self.intent(self.compare(first, second)), "researcher").json
        notes = [self.record(kind="research_note", title="隐藏的延后复核笔记" + str(index), visibility="restricted",
            body_html="<p>独立正文保持</p>", research_subjects=[{"subject_type": "person", "subject_id": first},
                {"subject_type": "person", "subject_id": third}, {"subject_type": "institution", "subject_id": institute},
                {"subject_type": "journal", "subject_id": journal}]) for index in range(3)]
        report = self.record(kind="research_report", evidence_ids=[notes[0]], body_html="<p>固定报告正文</p>")
        citation = self.get(f"/api/records/{report}")["evidence_citations"][0]["snapshot"]
        before = {rid: self.get(f"/api/records/{rid}") for rid in notes}
        preview = self.call(f"/api/people/identity-events/{merged['event_id']}/split-preview", user="colleague").json
        self.assertTrue(preview["allowed"], preview)
        self.assertEqual(preview["changes"]["subjects"], [])
        self.assertEqual(preview["relationships"]["notes"], [])
        self.assertNotIn("隐藏", json.dumps(preview, ensure_ascii=False))
        for rid in notes:
            self.assertNotIn(rid, json.dumps(preview))
        split = self.call("/api/people/split", self.split_intent(merged["event_id"], user="colleague"), "colleague")
        self.assertEqual(split.status_code, 200, split.json)
        self.assertEqual(self.get(f"/api/people/{first}/research-notes")["total"], 0)
        for rid in notes:
            current = self.get(f"/api/records/{rid}")
            self.assertEqual({s["subject_id"]: s["status"] for s in current["research_subjects"]},
                {first: "needs_review", third: "confirmed", institute: "confirmed", journal: "confirmed"})
            for key in ["body_html", "author_id", "author_confirmed", "editors", "visibility"]:
                self.assertEqual(current[key], before[rid][key])
            self.assertEqual(next(s for s in current["research_subjects"] if s["subject_id"] == first)["identity_change"]["evidence"], "合成反证，恢复两个身份")
            # Saving a normal editor payload cannot silently confirm an ambiguous edge.
            saved = self.call(f"/api/records/{rid}", {"version": current["version"], "body_html": current["body_html"],
                "research_subjects": current["research_subjects"]}, method="PUT")
            self.assertEqual(saved.status_code, 200, saved.json)
            self.assertEqual(next(s for s in self.get(f"/api/records/{rid}")["research_subjects"] if s["subject_id"] == first)["status"], "needs_review")
        for user in ["colleague", "admin"]:
            current = self.get(f"/api/records/{notes[0]}")
            response = self.call(f"/api/records/{notes[0]}/research-subjects", {"version": current["version"],
                "research_subjects": current["research_subjects"]}, user, "PUT")
            self.assertEqual(response.status_code, 404 if user == "colleague" else 200, response.json)
        # Readable members explicitly confirm, replace or remove; saving alone
        # still cannot silently confirm an ambiguous identity edge.
        for rid, decision in zip(notes, ["original", "replace", "remove"]):
            current = self.get(f"/api/records/{rid}")
            subjects = current["research_subjects"]
            if decision == "remove":
                subjects = [s for s in subjects if s["subject_id"] != first]
            else:
                next(s for s in subjects if s["subject_id"] == first).update(confirm=True, subject_id=first if decision == "original" else second)
            response = self.call(f"/api/records/{rid}/research-subjects", {"version": current["version"], "research_subjects": subjects},
                                 user="admin" if decision == "replace" else "researcher", method="PUT")
            self.assertEqual(response.status_code, 200, response.json)
            actual = self.get(f"/api/records/{rid}")["research_subjects"]
            self.assertEqual(len(actual), 3 if decision == "remove" else 4)
            self.assertTrue(all(s["status"] == "confirmed" for s in actual))
        self.assertEqual(self.get(f"/api/records/{report}")["evidence_citations"][0]["snapshot"], citation)
        self.assertNotIn("隐藏", json.dumps(self.get(f"/api/people/{first}/identity-history", "colleague"), ensure_ascii=False))

    def test_new_works_employment_and_readable_note_allocations_preserve_later_fields_and_hidden_notes(self):
        first, second, institute = self.person(), self.person("人物乙"), self.source()
        original = self.call(f"/api/people/{second}/employments", {"version": 0, "change_note": "原任职",
            "items": [{"institution_id": institute, "role": "研究员", "start_date": "2020", "end_date": "", "evidence": "原履历"}]}, method="PUT").json["items"][0]
        merged = self.call("/api/people/merge", self.intent(self.compare(first, second))).json
        jobs = self.get(f"/api/people/{first}/employments")
        jobs["items"][0].update(role="后续补充的高级研究员", end_date="2024", evidence="新履历依据")
        jobs["items"].append({"institution_id": institute, "role": "新增访问学者", "start_date": "2025", "end_date": "", "evidence": "合并后的新履历"})
        saved = self.call(f"/api/people/{first}/employments", {**jobs, "change_note": "补充任职字段与新经历"}, method="PUT")
        self.assertEqual(saved.status_code, 200, saved.json)
        added_job = next(row for row in saved.json["items"] if row["id"] != original["id"])
        work = self.record()
        new_bylines = self.bylines(work, [first, first])["items"]
        note = self.record(kind="research_note", research_subjects=[{"subject_type": "person", "subject_id": first}])
        subject = self.get(f"/api/records/{note}")["research_subjects"][0]
        private = self.record(kind="research_note", title="不可读关系分配笔记", visibility="restricted",
                              research_subjects=[{"subject_type": "person", "subject_id": first}])
        private_subject = self.get(f"/api/records/{private}")["research_subjects"][0]
        preview = self.call(f"/api/people/identity-events/{merged['event_id']}/split-preview", user="colleague").json
        self.assertEqual({r["id"]: r["classification"] for r in preview["changes"]["employments"]},
                         {original["id"]: "transferred", added_job["id"]: "added"})
        self.assertTrue(preview["changes"]["subjects"][0]["can_assign"])
        self.assertNotIn(private, json.dumps(preview))
        self.assertNotIn(private_subject["id"], json.dumps(preview))
        payload = self.split_intent(merged["event_id"], user="colleague")
        rejected = self.call("/api/people/split", payload, "colleague")
        self.assertEqual(rejected.status_code, 400, rejected.json)
        payload["allocations"] = {"employments": {added_job["id"]: "duplicate"}, "bylines": {new_bylines[0]["id"]: "duplicate"}}
        forbidden = {**self.split_intent(merged["event_id"], key="forbidden-hidden-note", user="colleague"),
            "allocations": {**payload["allocations"], "subjects": {private_subject["id"]: "duplicate"}}}
        self.assertEqual(self.call("/api/people/split", forbidden, "colleague").status_code, 403)
        self.assertEqual(self.clients["colleague"].get(f"/api/records/{private}").status_code, 404)
        payload["allocations"]["subjects"] = {subject["id"]: "duplicate"}
        result = self.call("/api/people/split", payload, "colleague")
        self.assertEqual(result.status_code, 200, result.json)
        second_jobs = self.get(f"/api/people/{second}/employments")["items"]
        self.assertEqual({row["id"] for row in second_jobs}, {original["id"], added_job["id"]})
        old_now = next(row for row in second_jobs if row["id"] == original["id"])
        self.assertEqual((old_now["role"], old_now["end_date"], old_now["evidence"]), ("后续补充的高级研究员", "2024", "新履历依据"))
        current = self.get(f"/api/records/{work}/bylines")["items"]
        self.assertEqual([(r["target_id"], r["status"]) for r in current], [(second, "confirmed"), (first, "pending")])
        self.assertEqual(self.get(f"/api/people/{first}/works")["total"], 0)
        self.assertEqual(self.get(f"/api/people/{second}/works")["total"], 1)
        assigned = self.get(f"/api/records/{note}")["research_subjects"][0]
        self.assertEqual((assigned["subject_id"], assigned["status"]), (second, "confirmed"))
        self.assertEqual(self.get(f"/api/records/{private}")["research_subjects"][0]["status"], "needs_review")

    def test_field_only_edits_do_not_disambiguate_added_employment_or_byline_identity(self):
        first, second, institute = self.person(), self.person("人物乙"), self.source()
        old_work = self.record()
        self.bylines(old_work, [second])
        merge = self.call("/api/people/merge", self.intent(self.compare(first, second))).json
        jobs = self.call(f"/api/people/{first}/employments", {"version": 0, "change_note": "新增任职", "items": [
            {"institution_id": institute, "role": "研究员", "start_date": "2024", "end_date": "", "evidence": "合成履历"}]}, method="PUT").json
        job = jobs["items"][0]
        job["role"] = "高级研究员"
        self.assertEqual(self.call(f"/api/people/{first}/employments", {**jobs, "change_note": "只修正角色用词"}, method="PUT").status_code, 200)
        added_work = self.record()
        self.bylines(added_work, [first])
        for rid in [old_work, added_work]:
            current = self.get(f"/api/records/{rid}/bylines")
            current["items"][0].update(raw_name="只补全署名片段", evidence="只完善作品页码依据")
            self.assertEqual(self.call(f"/api/records/{rid}/bylines", {**current, "change_note": "只修订文字"}, method="PUT").status_code, 200)
        preview = self.call(f"/api/people/identity-events/{merge['event_id']}/split-preview").json
        self.assertEqual(preview["changes"]["employments"][0]["classification"], "added")
        self.assertEqual(sorted(row["classification"] for row in preview["changes"]["bylines"]), ["added", "transferred"])
        payload = self.split_intent(merge["event_id"])
        self.assertEqual(self.call("/api/people/split", payload).status_code, 400)
        payload["allocations"] = {"employments": {job["id"]: "duplicate"}}
        self.assertEqual(self.call("/api/people/split", payload).status_code, 200)
        self.assertEqual(self.get(f"/api/records/{old_work}/bylines")["items"][0]["target_id"], second)
        self.assertEqual(self.get(f"/api/records/{added_work}/bylines")["items"][0]["status"], "pending")
        self.assertEqual(self.get(f"/api/people/{second}/employments")["items"][0]["role"], "高级研究员")

    def test_split_preview_protects_the_current_corrected_person_and_source_endpoints(self):
        first, second, third = self.person(), self.person("人物乙"), self.person("人物丙")
        institute = self.source()
        work = self.record()
        self.bylines(work, [second])
        merged = self.call("/api/people/merge", self.intent(self.compare(first, second))).json
        for kind, endpoint in [("person", third), ("institution", institute)]:
            current = self.get(f"/api/records/{work}/bylines")
            current["items"][0].update(target_type=kind, target_id=endpoint, evidence="更正到独立身份")
            self.assertEqual(self.call(f"/api/records/{work}/bylines", {**current, "change_note": "更正归属"}, method="PUT").status_code, 200)
            payload = self.split_intent(merged["event_id"], key="endpoint-" + kind)
            path = f"/api/people/{endpoint}" if kind == "person" else f"/api/sources/{endpoint}"
            profile = self.get(path)
            result = self.call(path, {"version": profile["version"], "name": "更新后的" + kind, "change_note": "端点档案更新"}, method="PUT")
            self.assertEqual(result.status_code, 200, result.json)
            stale = self.call("/api/people/split", payload)
            self.assertEqual(stale.status_code, 409, stale.json)
        success = self.call("/api/people/split", self.split_intent(merged["event_id"], key="new-endpoint-preview"))
        self.assertEqual(success.status_code, 200, success.json)
        self.assertEqual(self.get(f"/api/records/{work}/bylines")["items"][0]["target_id"], institute)

    def test_full_recovery_continues_inverse_splits_and_authorized_delayed_review_and_rejects_broken_review_provenance(self):
        first, second, fourth = self.person(), self.person("人物乙"), self.person("人物丁")
        early = self.call("/api/people/merge", self.intent(self.compare(first, second), key="recover-early")).json
        private = self.record(kind="research_note", title="恢复后延后确认的私人笔记", visibility="restricted",
                              research_subjects=[{"subject_type": "person", "subject_id": first}])
        work = self.record()
        byline = self.bylines(work, [first])["items"][0]
        later = self.call("/api/people/merge", self.intent(self.compare(first, fourth), key="recover-later")).json
        recovered = restore_backup(create_backup(self.data_dir), Path(self.temp.name) / "recovered-chain")
        app = create_app(recovered, testing=True)
        self.clients = {user: self.login(user, app) for user in self.clients}
        for event, key in [(later, "recover-later-split"), (early, "recover-early-split")]:
            payload = self.split_intent(event["event_id"], key=key, user="colleague")
            if event == early:
                payload["allocations"] = {"bylines": {byline["id"]: "duplicate"}}
            result = self.call("/api/people/split", payload, "colleague")
            self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.get(f"/api/records/{private}")["research_subjects"][0]["status"], "needs_review")
        archive = create_backup(recovered)
        twice = restore_backup(archive, Path(self.temp.name) / "recovered-review")
        self.clients = {user: self.login(user, create_app(twice, testing=True)) for user in self.clients}
        current = self.get(f"/api/records/{private}")
        grant = self.call(f"/api/records/{private}", {"version": current["version"], "editors": ["colleague"]}, method="PUT")
        self.assertEqual(grant.status_code, 200, grant.json)
        current = self.get(f"/api/records/{private}", "colleague")
        current["research_subjects"][0].update(subject_id=second, confirm=True)
        reviewed = self.call(f"/api/records/{private}/research-subjects", {"version": current["version"], "research_subjects": current["research_subjects"]}, "colleague", "PUT")
        self.assertEqual(reviewed.status_code, 200, reviewed.json)
        self.assertEqual(self.get(f"/api/people/{second}/research-notes", "colleague")["total"], 1)
        with zipfile.ZipFile(archive) as bundle:
            payloads = {name: bundle.read(name) for name in bundle.namelist()}
        for index, sql in enumerate([
            "UPDATE person_identity_events SET choices_json='{\"bylines\":{\"missing-row\":\"duplicate\"}}' WHERE event_type='split'",
            "UPDATE research_subject_history SET identity_event_id=NULL WHERE action='person_split_review'",
        ]):
            snapshot = Path(self.temp.name) / f"broken-review-{index}.sqlite3"
            snapshot.write_bytes(payloads["platform.sqlite3"])
            with closing(sqlite3.connect(snapshot)) as db:
                db.execute(sql)
                db.commit()
            damaged = dict(payloads)
            damaged["platform.sqlite3"] = snapshot.read_bytes()
            manifest = json.loads(damaged["manifest.json"])
            manifest["files"]["platform.sqlite3"] = {"bytes": len(damaged["platform.sqlite3"]), "sha256": hashlib.sha256(damaged["platform.sqlite3"]).hexdigest()}
            damaged["manifest.json"] = json.dumps(manifest).encode()
            path = Path(self.temp.name) / f"broken-review-{index}.zip"
            with zipfile.ZipFile(path, "w") as bundle:
                for name, content in damaged.items():
                    bundle.writestr(name, content)
            with self.assertRaises(ValueError):
                restore_backup(path, Path(self.temp.name) / f"broken-review-target-{index}")

    def test_split_history_projects_allocations_using_current_note_and_work_visibility(self):
        first, second = self.person(), self.person("人物乙")
        merged = self.call("/api/people/merge", self.intent(self.compare(first, second))).json
        private = self.record(kind="research_note", visibility="restricted", title="不能透露的分配笔记",
                              research_subjects=[{"subject_type": "person", "subject_id": first}])
        public = self.record(kind="research_note", title="可阅读的分配笔记",
                             research_subjects=[{"subject_type": "person", "subject_id": first}])
        hidden_subject = self.get(f"/api/records/{private}")["research_subjects"][0]["id"]
        public_subject = self.get(f"/api/records/{public}")["research_subjects"][0]["id"]
        work = self.record(visibility="restricted", title="不能透露的分配作品")
        hidden_byline = self.bylines(work, [first])["items"][0]["id"]
        payload = {**self.split_intent(merged["event_id"]), "allocations": {
            "subjects": {hidden_subject: "duplicate", public_subject: "keep"}, "bylines": {hidden_byline: "duplicate"}}}
        result = self.call("/api/people/split", payload)
        self.assertEqual(result.status_code, 200, result.json)
        event_id = result.json["event_id"]
        for shared in [False, True, False]:
            for rid in [private, work]:
                current = self.get(f"/api/records/{rid}")
                changed = self.call(f"/api/records/{rid}", {"version": current["version"], "visibility": "shared" if shared else "restricted"}, method="PUT")
                self.assertEqual(changed.status_code, 200, changed.json)
            history = self.get(f"/api/people/{first}/identity-history", "colleague")
            event = next(row for row in history["items"] if row["id"] == event_id)
            self.assertEqual(event["choices"].get("subjects"), {public_subject: "keep", **({hidden_subject: "duplicate"} if shared else {})})
            self.assertEqual(event["choices"].get("bylines", {}), {hidden_byline: "duplicate"} if shared else {})
            if not shared:
                for hidden in [private, work, hidden_subject, hidden_byline]:
                    self.assertNotIn(hidden, json.dumps(history))
        author = next(row for row in self.get(f"/api/people/{first}/identity-history")["items"] if row["id"] == event_id)
        self.assertEqual(author["choices"], payload["allocations"])

    def test_complex_split_invalid_allocation_and_late_storage_failures_roll_back_all_changes_and_retry(self):
        first, second, institute = self.person(), self.person("人物乙"), self.source()
        merge = self.call("/api/people/merge", self.intent(self.compare(first, second))).json
        private = self.record(kind="research_note", visibility="restricted", research_subjects=[{"subject_type": "person", "subject_id": first}])
        subject = self.get(f"/api/records/{private}")["research_subjects"][0]
        work = self.record()
        byline = self.bylines(work, [first])["items"][0]
        job = self.call(f"/api/people/{first}/employments", {"version": 0, "change_note": "新增经历", "items": [
            {"institution_id": institute, "role": "新研究员", "start_date": "2024", "end_date": "", "evidence": "合成新主页"}]}, method="PUT").json["items"][0]
        payload = {**self.split_intent(merge["event_id"]), "allocations": {"employments": {job["id"]: "duplicate"},
            "bylines": {byline["id"]: "pending"}, "subjects": {subject["id"]: "duplicate"}}}
        def observed():
            paths = [f"/api/people/{pid}{suffix}" for pid in [first, second] for suffix in ["", "/history", "/identity-history", "/employments", "/employments/history", "/works", "/research-notes"]]
            paths += [f"/api/records/{private}", f"/api/records/{private}/research-subjects/history", f"/api/records/{work}/bylines", f"/api/records/{work}/bylines/history"]
            return {path: self.get(path) for path in paths}
        before = observed()
        invalid = {**payload, "allocations": {**payload["allocations"], "bylines": {byline["id"]: {"bad": "nested"}}}}
        response = self.call("/api/people/split", invalid)
        self.assertEqual(response.status_code, 400, response.json)
        self.assertEqual(observed(), before)
        for fault in ["late", "commit"]:
            with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db:
                if fault == "late":
                    db.execute("CREATE TRIGGER synthetic_complex_fault BEFORE INSERT ON person_identity_requests BEGIN SELECT RAISE(ABORT,'synthetic end write'); END")
                else:
                    db.execute("CREATE TABLE synthetic_complex_commit(person_id TEXT REFERENCES people(id) DEFERRABLE INITIALLY DEFERRED)")
                    db.execute("CREATE TRIGGER synthetic_complex_fault AFTER INSERT ON person_identity_requests BEGIN INSERT INTO synthetic_complex_commit VALUES ('missing-person'); END")
                db.commit()
            response = self.call("/api/people/split", payload)
            self.assertEqual(response.status_code, 409, response.json)
            self.assertEqual(observed(), before)
            with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db:
                db.execute("DROP TRIGGER synthetic_complex_fault")
                if fault == "commit":
                    db.execute("DROP TABLE synthetic_complex_commit")
                db.commit()
        success = self.call("/api/people/split", payload)
        self.assertEqual(success.status_code, 200, success.json)
        self.assertEqual(self.call("/api/people/split", payload).json, success.json)
        self.assertEqual(self.get(f"/api/records/{private}")["research_subjects"][0]["subject_id"], second)
        self.assertEqual(self.get(f"/api/records/{work}/bylines")["items"][0]["status"], "pending")
        self.assertEqual(self.get(f"/api/people/{second}/employments")["items"][0]["id"], job["id"])

    def test_explicit_author_allocation_in_a_later_split_remains_a_decision_in_the_earlier_split(self):
        first, second, fourth = self.person(), self.person("人物乙"), self.person("人物丁")
        early = self.call("/api/people/merge", self.intent(self.compare(first, second), key="author-early")).json
        later = self.call("/api/people/merge", self.intent(self.compare(first, fourth), key="author-later")).json
        note = self.record(kind="research_note", research_subjects=[{"subject_type": "person", "subject_id": first}])
        subject = self.get(f"/api/records/{note}")["research_subjects"][0]
        payload = {**self.split_intent(later["event_id"], key="author-split-later"), "allocations": {"subjects": {subject["id"]: "keep"}}}
        self.assertEqual(self.call("/api/people/split", payload).status_code, 200)
        preview = self.call(f"/api/people/identity-events/{early['event_id']}/split-preview").json
        self.assertEqual(preview["changes"]["subjects"][0]["classification"], "corrected")
        self.assertEqual(self.call("/api/people/split", self.split_intent(early["event_id"], key="author-split-earlier")).status_code, 200)
        current = self.get(f"/api/records/{note}")["research_subjects"][0]
        self.assertEqual((current["id"], current["subject_id"], current["status"]), (subject["id"], first, "confirmed"))

    def test_private_corrected_endpoint_is_freshness_state_without_becoming_a_public_participant(self):
        first, second, third = self.person(), self.person("人物乙"), self.person("私人关联的第三人")
        merge = self.call("/api/people/merge", self.intent(self.compare(first, second))).json
        note = self.record(kind="research_note", visibility="restricted", research_subjects=[{"subject_type": "person", "subject_id": first}])
        current = self.get(f"/api/records/{note}")
        current["research_subjects"][0].update(subject_id=third)
        saved = self.call(f"/api/records/{note}/research-subjects", {"version": current["version"], "research_subjects": current["research_subjects"]}, method="PUT")
        self.assertEqual(saved.status_code, 200, saved.json)
        result = self.call("/api/people/split", self.split_intent(merge["event_id"], user="colleague"), "colleague")
        self.assertEqual(result.status_code, 200, result.json)
        public = self.get(f"/api/people/{first}/identity-history", "colleague")
        self.assertNotIn(third, json.dumps(public))
        self.assertNotIn(note, json.dumps(public))
        self.assertEqual(self.get(f"/api/records/{note}")["research_subjects"][0]["subject_id"], third)

    def test_compare_select_information_follow_old_entry_and_split_an_unchanged_merge(self):
        first = self.person(introduction_html="<p>甲的介绍</p>", sources="合成出处甲")
        second = self.person("合成人物乙", introduction_html="<p>乙的介绍</p>", sources="合成出处乙")
        preview = self.compare(first, second)
        self.assertEqual(preview["keep"]["sources"], "合成出处甲")
        self.assertEqual(preview["duplicate"]["introduction_html"], "<p>乙的介绍</p>")
        self.assertIn("introduction", preview["conflicts"])
        missing_choice = self.intent(preview, choices={"name": "keep"})
        self.assertEqual(self.call("/api/people/merge", missing_choice).status_code, 400)
        merged = self.call("/api/people/merge", self.intent(preview))
        self.assertEqual(merged.status_code, 200, merged.json)
        event = merged.json["event_id"]
        current = self.get(f"/api/people/{second}")
        self.assertEqual(current["id"], first)
        self.assertEqual(current["requested_id"], second)
        self.assertEqual(current["introduction_html"], "<p>乙的介绍</p>")
        self.assertIn(second, current["previous_ids"])
        self.assertEqual(self.get("/api/people?q=合成人物乙")["items"][0]["id"], first)
        historical = self.get(f"/api/people/{first}/history")["items"]
        self.assertIn("<p>甲的介绍</p>", [item["snapshot"]["introduction_html"] for item in historical])
        split_preview = self.call(f"/api/people/identity-events/{event}/split-preview")
        self.assertEqual(split_preview.status_code, 200, split_preview.json)
        self.assertTrue(split_preview.json["allowed"])
        result = self.call("/api/people/split", {"preview_id": split_preview.json["preview_id"],
            "idempotency_key": "synthetic-split", "confirmed": True, "evidence": "合成反证，恢复两个身份"})
        self.assertEqual(result.status_code, 200, result.json)
        for pid, intro in [(first, "<p>甲的介绍</p>"), (second, "<p>乙的介绍</p>")]:
            actual = self.get(f"/api/people/{pid}")
            self.assertEqual((actual["id"], actual["introduction_html"]), (pid, intro))
        history = self.get(f"/api/people/{first}/identity-history")["items"]
        self.assertEqual([item["event_type"] for item in history], ["split", "merge"])

    def test_all_relation_origins_survive_even_when_actor_cannot_read_a_private_note(self):
        first, second, institute = self.person(), self.person("合成人物乙"), self.source()
        work = self.record(authors="同名作者0；同名作者1")
        original_bylines = self.bylines(work, [first, second])
        units = self.get(f"/api/records/{work}/affiliations")
        units = self.call(f"/api/records/{work}/affiliations", {**units, "change_note": "合成首页单位",
            "items": [{"byline_id": row["id"], "institution_id": institute, "evidence": "合成作者单位"}
                      for row in original_bylines["items"]]}, method="PUT")
        self.assertEqual(units.status_code, 200, units.json)
        employment_ids = []
        for pid in [first, second]:
            response = self.call(f"/api/people/{pid}/employments", {"version": 0, "change_note": "合成履历",
                "items": [{"institution_id": institute, "role": "研究员", "start_date": "2020", "end_date": "",
                           "evidence": "合成机构主页的履历"}]}, method="PUT")
            self.assertEqual(response.status_code, 200, response.json)
            employment_ids.append(response.json["items"][0]["id"])
        note = self.record(kind="research_note", title="合成公开比较笔记", body_html="<p>作者独立判断</p>",
            research_subjects=[{"subject_type": "person", "subject_id": pid} for pid in [first, second]])
        private = self.record(kind="research_note", title="仅作者可读的合成秘密笔记", visibility="restricted",
            body_html="<p>秘密研究判断</p>", research_subjects=[{"subject_type": "person", "subject_id": second},
                {"subject_type": "institution", "subject_id": institute}])
        report = self.record(kind="research_report", title="采用固定依据的合成报告", evidence_ids=[note],
                             body_html="<p>报告结论保持</p>")
        before_notes = {rid: self.get(f"/api/records/{rid}") for rid in [note, private]}
        citation = self.get(f"/api/records/{report}")["evidence_citations"][0]
        preview = self.compare(first, second, "colleague")
        self.assertEqual([item["id"] for item in preview["relationships"]["works"]], [work])
        self.assertEqual([item["id"] for item in preview["relationships"]["notes"]], [note])
        self.assertNotIn(private, json.dumps(preview))
        self.assertNotIn("秘密", json.dumps(preview, ensure_ascii=False))
        merged = self.call("/api/people/merge", self.intent(preview), "colleague")
        self.assertEqual(merged.status_code, 200, merged.json)
        current = self.get(f"/api/records/{work}/bylines")
        self.assertEqual([row["id"] for row in current["items"]], [row["id"] for row in original_bylines["items"]])
        self.assertEqual([row["target_id"] for row in current["items"]], [first, first])
        self.assertEqual([row["selected_target_id"] for row in current["items"]], [first, second])
        self.assertEqual([row["manual_revision"] for row in current["items"]], [1, 1])
        self.assertEqual(current["raw_authors"], "同名作者0；同名作者1")
        current_units = self.get(f"/api/records/{work}/affiliations")["items"]
        self.assertEqual([{key: value for key, value in row.items() if key != "byline"} for row in current_units],
                         [{key: value for key, value in row.items() if key != "byline"} for row in units.json["items"]])
        self.assertEqual([row["byline"]["target_id"] for row in current_units], [first, first])
        combined = self.get(f"/api/people/{second}/employments")
        self.assertEqual(combined["person_id"], first)
        self.assertEqual({row["id"] for row in combined["items"]}, set(employment_ids))
        self.assertEqual([row["manual_revision"] for row in combined["items"]], [1, 1])
        self.assertEqual(self.get(f"/api/people/{second}/works")["total"], 1)
        self.assertEqual(self.get(f"/api/people/{second}/research-notes", "colleague")["total"], 1)
        changed_subject = next(row for row in self.get(f"/api/records/{note}")["research_subjects"] if row["original_subject_id"] == second)
        self.assertEqual(changed_subject["identity_change"]["action"], "person_merge")
        for rid in [note, private]:
            actual = self.get(f"/api/records/{rid}")
            for key in ["body_html", "author_id", "author_confirmed", "editors", "visibility", "evidence_snapshot_json"]:
                self.assertEqual(actual[key], before_notes[rid][key])
            self.assertEqual([row["original_subject_id"] for row in actual["research_subjects"]],
                             [row["original_subject_id"] for row in before_notes[rid]["research_subjects"]])
        self.assertEqual(self.get(f"/api/records/{report}")["evidence_citations"][0]["snapshot"], citation["snapshot"])
        event = merged.json["event_id"]
        self.assertNotIn(private, json.dumps(self.get(f"/api/people/{first}/identity-history", "colleague")))
        current_note = self.get(f"/api/records/{note}")
        shared_edit = self.call(f"/api/records/{note}/research-subjects", {"version": current_note["version"],
            "research_subjects": current_note["research_subjects"]}, "colleague", "PUT")
        self.assertEqual(shared_edit.status_code, 200, shared_edit.json)
        self.assertEqual(self.clients["colleague"].get(f"/api/records/{private}").status_code, 404)
        restored = self.call("/api/people/split", self.split_intent(event, user="colleague"), "colleague")
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual([row["target_id"] for row in self.get(f"/api/records/{work}/bylines")["items"]], [first, second])
        for pid, eid in zip([first, second], employment_ids):
            self.assertEqual([row["id"] for row in self.get(f"/api/people/{pid}/employments")["items"]], [eid])
        for rid in [note, private]:
            actual = self.get(f"/api/records/{rid}")
            self.assertEqual([(s["id"], s["subject_id"], s["manual_revision"]) for s in actual["research_subjects"]],
                             [(s["id"], s["subject_id"], s["manual_revision"]) for s in before_notes[rid]["research_subjects"]])
        changed_subject = next(row for row in self.get(f"/api/records/{note}")["research_subjects"] if row["original_subject_id"] == second)
        self.assertEqual(changed_subject["identity_change"]["action"], "person_split")

    def test_other_person_avatar_keeps_original_urls_ownership_and_restorable_history(self):
        first, second = self.person(), self.person("合成人物乙")
        images, avatars = {}, {}
        for pid, color in [(first, "navy"), (second, "gold")]:
            images[pid] = self.image(color)
            response = self.call(f"/api/people/{pid}", {"version": 1, "avatar_source": "合成图像来源",
                "change_note": "补充合成头像"}, method="PUT", image=images[pid])
            self.assertEqual(response.status_code, 200, response.json)
            avatars[pid] = response.json["avatar"]
        old_second = avatars[second]
        replacement = self.call(f"/api/people/{second}", {"version": 2, "avatar_source": "合成新头像来源",
            "change_note": "替换合成头像"}, method="PUT", image=self.image("green"))
        self.assertEqual(replacement.status_code, 200, replacement.json)
        preview = self.compare(first, second)
        payload = self.intent(preview)
        payload["choices"]["avatar"] = "duplicate"
        merged = self.call("/api/people/merge", payload)
        self.assertEqual(merged.status_code, 200, merged.json)
        actual = self.get(f"/api/people/{first}")
        self.assertEqual(actual["avatar"]["id"], replacement.json["avatar"]["id"])
        self.assertEqual(actual["avatar"]["owner_id"], second)
        self.assertEqual(self.download(actual["avatar"]["url"], "colleague"), self.image("green"))
        self.assertEqual(self.download(old_second["url"], "colleague"), images[second])
        self.assertEqual(self.download(avatars[first]["url"], "colleague"), images[first])
        historical = self.get(f"/api/people/{first}/history")["items"]
        chosen = next(row for row in historical if row["snapshot"]["avatar_id"] == actual["avatar_id"])
        result = self.call("/api/people/split", self.split_intent(merged.json["event_id"]))
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.get(f"/api/people/{first}")["avatar_id"], avatars[first]["id"])
        self.assertEqual(self.get(f"/api/people/{second}")["avatar_id"], replacement.json["avatar"]["id"])
        latest = self.get(f"/api/people/{first}")
        restored = self.call(f"/api/people/{first}/restore/{chosen['id']}", {"version": latest["version"],
            "change_note": "从合并历史恢复选定头像"})
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual(self.download(restored.json["avatar"]["url"], "colleague"), self.image("green"))

    def test_full_preview_changes_require_new_comparison_and_tokens_disclose_no_private_plan(self):
        first, second, institute = self.person(), self.person("合成人物乙"), self.source()
        work = self.record()
        self.bylines(work, [second])
        for change in ["profile", "new_byline", "employment", "unit", "removed", "hidden_note", "event"]:
            with self.subTest(change=change):
                preview = self.compare(first, second, "colleague")
                self.assertRegex(preview["preview_id"], r"^[a-f0-9]{64}$")
                self.assertEqual(self.call("/api/people/merge", self.intent(preview), "researcher").status_code, 409)
                if change == "profile":
                    person = self.get(f"/api/people/{first}")
                    result = self.call(f"/api/people/{first}", {"version": person["version"], "name": "修订合成人物甲", "change_note": "新合成证据"}, method="PUT")
                elif change == "new_byline":
                    result = self.call(f"/api/records/{work}/bylines", {**self.get(f"/api/records/{work}/bylines"),
                        "change_note": "补充署名", "items": [{"raw_name": "另一个署名", "status": "confirmed",
                            "target_type": "person", "target_id": first, "evidence": "合成新主页"}]}, method="PUT")
                elif change == "employment":
                    result = self.call(f"/api/people/{second}/employments", {"version": 0, "change_note": "新履历",
                        "items": [{"institution_id": institute, "role": "访问学者", "start_date": "", "end_date": "", "evidence": "合成履历"}]}, method="PUT")
                elif change == "unit":
                    byline = self.get(f"/api/records/{work}/bylines")["items"][0]
                    result = self.call(f"/api/records/{work}/affiliations", {**self.get(f"/api/records/{work}/affiliations"),
                        "change_note": "新增文章单位", "items": [{"byline_id": byline["id"], "institution_id": institute, "evidence": "合成署名单位"}]}, method="PUT")
                elif change == "removed":
                    result = self.call(f"/api/people/{second}/employments", {**self.get(f"/api/people/{second}/employments"),
                        "change_note": "移除误认任职", "items": []}, method="PUT")
                elif change == "hidden_note":
                    hidden = self.record(kind="research_note", title="隐藏合成笔记不泄露", visibility="restricted",
                        research_subjects=[{"subject_type": "person", "subject_id": second}])
                    result = self.clients["researcher"].get(f"/api/records/{hidden}")
                    self.assertNotIn(hidden, json.dumps(preview))
                else:
                    another = self.person("合成第三人")
                    active = self.call("/api/people/merge", self.intent(self.compare(first, another), key="other-merge"))
                    self.assertEqual(active.status_code, 200, active.json)
                    result = self.call("/api/people/split", self.split_intent(active.json["event_id"], key="other-split"))
                self.assertEqual(result.status_code, 200, result.json)
                rejected = self.call("/api/people/merge", self.intent(preview, key="stale-" + change), "colleague")
                self.assertEqual(rejected.status_code, 409, rejected.json)
                self.assertIn("重新比较", rejected.json["error"])
                self.assertNotIn("隐藏", rejected.json["error"])
        latest = self.compare(first, second, "colleague")
        merged = self.call("/api/people/merge", self.intent(latest), "colleague")
        self.assertEqual(merged.status_code, 200, merged.json)
        split = self.split_intent(merged.json["event_id"], user="colleague")
        current = self.get(f"/api/people/{first}")
        self.assertEqual(self.call(f"/api/people/{first}", {"version": current["version"], "change_note": "合并后独立编辑", "name": "之后的姓名"}, method="PUT").status_code, 200)
        self.assertEqual(self.call("/api/people/split", split, "colleague").status_code, 409)
        new_preview = self.call(f"/api/people/identity-events/{merged.json['event_id']}/split-preview", user="colleague")
        self.assertTrue(new_preview.json["allowed"])
        self.assertEqual(self.call("/api/people/split", self.split_intent(merged.json["event_id"], key="changed-split", user="colleague"), "colleague").status_code, 200)
        self.assertEqual(self.get(f"/api/people/{first}")["name"], "之后的姓名")
        self.assertEqual(self.get(f"/api/people/{second}")["name"], "合成人物乙")

    def test_successful_merge_and_split_requests_are_persistent_and_actor_intent_bound(self):
        first, second = self.person(), self.person("合成人物乙")
        payload = self.intent(self.compare(first, second))
        client = self.clients["researcher"]
        # Separate member sessions exercise simultaneous network retries at the HTTP seam.
        sessions = [self.login("researcher") for _ in range(2)]
        tokens = [session.get("/api/session").json["csrf"] for session in sessions]
        def send(index):
            return sessions[index].post("/api/people/merge", json=payload, headers={"X-CSRF-Token": tokens[index]})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, [0, 1]))
        for result in results:
            self.assertEqual(result.status_code, 200, result.json)
            self.assertEqual(result.json, results[0].json)
        merged = results[0].json
        self.assertEqual(len(self.get(f"/api/people/{first}/identity-history")["items"]), 1)
        self.assertEqual(self.call("/api/people/merge", {**payload, "evidence": "同键不同意图"}).status_code, 409)
        self.assertEqual(self.call("/api/people/merge", payload, "colleague").status_code, 409)
        split = self.split_intent(merged["event_id"])
        result = self.call("/api/people/split", split)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.call("/api/people/split", split).json, result.json)
        self.clients["researcher"] = self.login("researcher", create_app(self.data_dir, testing=True))
        self.assertEqual(self.call("/api/people/merge", payload).json, merged)
        self.assertEqual(self.call("/api/people/split", split).json, result.json)
        self.assertEqual(len(self.get(f"/api/people/{first}/identity-history")["items"]), 2)
        self.assertEqual(client.get(f"/api/people/{second}").json["id"], second)

    def test_late_write_and_commit_failures_roll_back_merge_split_history_and_keep_retry_key(self):
        first, second = self.person(), self.person("合成人物乙")
        image = self.call(f"/api/people/{second}", {"version": 1, "avatar_source": "合成头像", "change_note": "合成图像"},
                          method="PUT", image=self.image("purple"))
        self.assertEqual(image.status_code, 200)
        work = self.record()
        self.bylines(work, [second])
        note = self.record(kind="research_note", body_html="<p>私人正文保持</p>", visibility="restricted",
                           research_subjects=[{"subject_type": "person", "subject_id": second}])
        payload = self.intent(self.compare(first, second))

        def observed():
            paths = [f"/api/people/{pid}{suffix}" for pid in [first, second]
                     for suffix in ["", "/history", "/identity-history", "/employments", "/works", "/research-notes"]]
            paths += [f"/api/records/{work}/bylines", f"/api/records/{work}/bylines/history", f"/api/records/{note}",
                      f"/api/records/{note}/research-subjects/history"]
            return {path: self.get(path) for path in paths}

        original_files = {path.name: path.read_bytes() for path in (self.data_dir / "avatars").iterdir()}
        for action in ["merge", "split"]:
            for fault in ["late_write", "commit"]:
                with self.subTest(action=action, fault=fault):
                    before = observed()
                    with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db:
                        if fault == "late_write":
                            db.execute("CREATE TRIGGER synthetic_identity_fault BEFORE INSERT ON person_identity_requests BEGIN SELECT RAISE(ABORT,'synthetic late fault'); END")
                        else:
                            db.execute("CREATE TABLE synthetic_commit_fault (person_id TEXT REFERENCES people(id) DEFERRABLE INITIALLY DEFERRED)")
                            db.execute("CREATE TRIGGER synthetic_identity_fault AFTER INSERT ON person_identity_requests BEGIN INSERT INTO synthetic_commit_fault VALUES ('missing-synthetic-person'); END")
                        db.commit()
                    response = self.call("/api/people/" + action, payload)
                    self.assertEqual(response.status_code, 409, response.json)
                    self.assertEqual(observed(), before)
                    self.assertEqual({path.name: path.read_bytes() for path in (self.data_dir / "avatars").iterdir()}, original_files)
                    with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as db:
                        db.execute("DROP TRIGGER synthetic_identity_fault")
                        if fault == "commit":
                            db.execute("DROP TABLE synthetic_commit_fault")
                        db.commit()
            success = self.call("/api/people/" + action, payload)
            self.assertEqual(success.status_code, 200, success.json)
            self.assertEqual(self.call("/api/people/" + action, payload).json, success.json)
            if action == "merge":
                payload = self.split_intent(success.json["event_id"])

    def test_old_identifiers_resolve_in_new_selections_and_profile_restore_cannot_split_identity(self):
        first = self.person("合成人物甲")
        second = self.person("合成人物乙", chinese_name="合成乙中文名")
        old_revision = self.get(f"/api/people/{second}/history")["items"][-1]
        merged = self.call("/api/people/merge", self.intent(self.compare(first, second)))
        self.assertEqual(merged.status_code, 200, merged.json)
        work = self.record()
        selected = self.bylines(work, [second])["items"][0]
        self.assertEqual((selected["selected_target_id"], selected["target_id"]), (second, first))
        note = self.record(kind="research_note", research_subjects=[{"subject_type": "person", "subject_id": second}])
        subject = self.get(f"/api/records/{note}")["research_subjects"][0]
        self.assertEqual((subject["original_subject_id"], subject["subject_id"]), (second, first))
        original = self.get(f"/api/people/{second}/history")["items"]
        self.assertTrue(all(not row["can_restore"] for row in original))
        self.assertEqual(self.call(f"/api/people/{second}/restore/{old_revision['id']}", {"version": 2, "change_note": "不能用正文恢复拆回身份"}).status_code, 409)
        current = self.get(f"/api/people/{first}")
        changed = self.call(f"/api/people/{first}", {"version": current["version"], "aliases": "", "change_note": "整理当前人物别名"}, method="PUT")
        self.assertEqual(changed.status_code, 200, changed.json)
        self.assertNotIn(second, changed.json["aliases"].splitlines())
        for name in ["合成人物乙", "合成乙中文名", second]:
            self.assertEqual([row["id"] for row in self.get("/api/people?q=" + name)["items"]], [first])
        for pair in [(first, first), (first, second), (second, first)]:
            self.assertEqual(self.call("/api/people/merge-preview", {"keep_id": pair[0], "duplicate_id": pair[1]}).status_code, 400)
        institute = self.source()
        self.assertEqual(self.call("/api/people/merge-preview", {"keep_id": first, "duplicate_id": institute, "type": "institution"}).status_code, 400)

    def test_full_backup_recovers_merged_identity_private_relations_avatars_and_successful_retry(self):
        first, second = self.person(), self.person("合成人物乙")
        avatar = self.call(f"/api/people/{second}", {"version": 1, "change_note": "合成头像", "avatar_source": "合成生成"},
                           method="PUT", image=self.image("maroon"))
        self.assertEqual(avatar.status_code, 200)
        hidden = self.record(kind="research_note", visibility="restricted", title="恢复时保全的合成私人笔记",
                             research_subjects=[{"subject_type": "person", "subject_id": second}])
        work = self.record()
        self.bylines(work, [first, second])
        payload = self.intent(self.compare(first, second, "colleague"))
        payload["choices"]["avatar"] = "duplicate"
        merged = self.call("/api/people/merge", payload, "colleague")
        self.assertEqual(merged.status_code, 200, merged.json)
        before = self.get(f"/api/people/{first}/identity-history")
        restored = restore_backup(create_backup(self.data_dir), Path(self.temp.name) / "recovered")
        app = create_app(restored, testing=True)
        self.clients = {user: self.login(user, app) for user in self.clients}
        self.assertEqual(self.get(f"/api/people/{second}")["id"], first)
        self.assertEqual(self.get(f"/api/people/{first}/identity-history"), before)
        self.assertEqual(self.download(self.get(f"/api/people/{first}")["avatar"]["url"]), self.image("maroon"))
        self.assertEqual(self.get(f"/api/records/{hidden}")["research_subjects"][0]["original_subject_id"], second)
        self.assertEqual(self.clients["colleague"].get(f"/api/records/{hidden}").status_code, 404)
        self.assertEqual(self.call("/api/people/merge", payload, "colleague").json, merged.json)
        split = self.call("/api/people/split", self.split_intent(merged.json["event_id"], user="colleague"), "colleague")
        self.assertEqual(split.status_code, 200, split.json)
        self.assertEqual(self.get(f"/api/records/{hidden}")["research_subjects"][0]["subject_id"], second)
        self.assertEqual([row["target_id"] for row in self.get(f"/api/records/{work}/bylines")["items"]], [first, second])

    def test_restore_rejects_missing_identity_provenance_cycles_and_broken_historical_avatar_references(self):
        first, second = self.person(), self.person("合成人物乙")
        merged = self.call("/api/people/merge", self.intent(self.compare(first, second)))
        self.assertEqual(merged.status_code, 200)
        archive = create_backup(self.data_dir)
        with zipfile.ZipFile(archive) as bundle:
            original = {name: bundle.read(name) for name in bundle.namelist()}
        faults = ["UPDATE person_identity_events SET before_json='{}'",
                  "UPDATE person_identity_events SET dependencies_json='[\"missing-identity\"]'",
                  f"UPDATE people SET merged_into='{second}' WHERE id='{first}'",
                  "DELETE FROM person_merge_state",
                  "UPDATE person_merge_state SET status='split'",
                  "UPDATE revisions SET snapshot_json=json_set(snapshot_json,'$.avatar_id','missing-avatar') WHERE target_type='person'"]
        for index, sql in enumerate(faults):
            with self.subTest(fault=index):
                snapshot = Path(self.temp.name) / f"corrupt-{index}.sqlite3"
                snapshot.write_bytes(original["platform.sqlite3"])
                with closing(sqlite3.connect(snapshot)) as db:
                    db.execute(sql)
                    db.commit()
                payloads = {**original, "platform.sqlite3": snapshot.read_bytes()}
                manifest = json.loads(payloads["manifest.json"])
                manifest["files"]["platform.sqlite3"] = {"bytes": len(payloads["platform.sqlite3"]),
                    "sha256": hashlib.sha256(payloads["platform.sqlite3"]).hexdigest()}
                payloads["manifest.json"] = json.dumps(manifest).encode("utf-8")
                damaged = Path(self.temp.name) / f"corrupt-{index}.zip"
                with zipfile.ZipFile(damaged, "w") as bundle:
                    for name, content in payloads.items():
                        bundle.writestr(name, content)
                target = Path(self.temp.name) / f"bad-recovery-{index}"
                with self.assertRaises(ValueError):
                    restore_backup(damaged, target)
                self.assertFalse(target.exists())

    def test_existing_source_record_merges_and_body_restore_keep_merged_person_provenance(self):
        first, second, institute, other_institute = self.person(), self.person("合成人物乙"), self.source(), self.source("合成第二机构")
        original, duplicate = self.record(authors="原始甲署名"), self.record(authors="原始乙署名")
        first_bylines = self.bylines(original, [first])
        second_bylines = self.bylines(duplicate, [second])
        units = self.get(f"/api/records/{duplicate}/affiliations")
        saved = self.call(f"/api/records/{duplicate}/affiliations", {**units, "change_note": "合成单位",
            "items": [{"byline_id": second_bylines["items"][0]["id"], "institution_id": institute, "evidence": "合成首页"}]}, method="PUT")
        self.assertEqual(saved.status_code, 200, saved.json)
        note = self.record(kind="research_note", research_subjects=[{"subject_type": "person", "subject_id": second},
                           {"subject_type": "institution", "subject_id": institute}])
        revision = self.get(f"/api/history/record/{original}")["items"][-1]["id"]
        person_merge = self.call("/api/people/merge", self.intent(self.compare(first, second)))
        self.assertEqual(person_merge.status_code, 200, person_merge.json)
        for kind, keep, old in [("source", other_institute, institute), ("record", original, duplicate)]:
            preview = self.call("/api/merge/preview", {"type": kind, "keep_id": keep, "duplicate_id": old}, "admin")
            self.assertEqual(preview.status_code, 200, preview.json)
            response = self.call("/api/merge", {"type": kind, "keep_id": keep, "duplicate_id": old,
                "keep_version": preview.json["keep"]["version"], "duplicate_version": preview.json["duplicate"]["version"], "confirmed": True}, "admin")
            self.assertEqual(response.status_code, 200, response.json)
        current = self.get(f"/api/records/{original}")
        restored = self.call(f"/api/history/{revision}/restore", {"version": current["version"]})
        self.assertEqual(restored.status_code, 200, restored.json)
        current_bylines = self.get(f"/api/records/{duplicate}/bylines")["items"]
        self.assertEqual([row["id"] for row in current_bylines], [first_bylines["items"][0]["id"], second_bylines["items"][0]["id"]])
        self.assertEqual([row["selected_target_id"] for row in current_bylines], [first, second])
        current_units = self.get(f"/api/records/{original}/affiliations")["items"]
        self.assertEqual((current_units[0]["id"], current_units[0]["institution_id"]), (saved.json["items"][0]["id"], other_institute))
        self.assertEqual(current_units[0]["byline_snapshot_json"], saved.json["items"][0]["byline_snapshot_json"])
        subjects = self.get(f"/api/records/{note}")["research_subjects"]
        self.assertEqual({(row["subject_type"], row["subject_id"]) for row in subjects}, {("person", first), ("institution", other_institute)})
        preview = self.call(f"/api/people/identity-events/{person_merge.json['event_id']}/split-preview")
        self.assertTrue(preview.json["allowed"])
        recovered = restore_backup(create_backup(self.data_dir), Path(self.temp.name) / "old-operations-recovered")
        self.clients["researcher"] = self.login("researcher", create_app(recovered, testing=True))
        self.assertEqual(self.get(f"/api/records/{original}/bylines")["items"], current_bylines)
        self.assertEqual(self.get(f"/api/records/{original}/affiliations")["items"], current_units)
        split = self.call("/api/people/split", self.split_intent(person_merge.json["event_id"], key="after-other-merges"))
        self.assertEqual(split.status_code, 200, split.json)
        self.assertEqual([r["target_id"] for r in self.get(f"/api/records/{original}/bylines")["items"]], [first, second])
        self.assertEqual(self.get(f"/api/records/{original}/affiliations")["items"][0]["institution_id"], other_institute)

    def test_identity_preview_and_history_filter_private_original_note_provenance_after_note_merge(self):
        first, second = self.person(), self.person("合成人物乙")
        old = self.record(kind="research_note", title="不能从身份预览透露的原笔记", visibility="restricted",
                          research_subjects=[{"subject_type": "person", "subject_id": second}])
        current = self.record(kind="research_note", title="合并后主动共享的合成笔记", visibility="restricted")
        person_merge = self.call("/api/people/merge", self.intent(self.compare(first, second)))
        self.assertEqual(person_merge.status_code, 200, person_merge.json)
        preview = self.call("/api/merge/preview", {"type": "record", "keep_id": current, "duplicate_id": old})
        self.assertEqual(preview.status_code, 200, preview.json)
        result = self.call("/api/merge", {"type": "record", "keep_id": current, "duplicate_id": old,
            "keep_version": preview.json["keep"]["version"], "duplicate_version": preview.json["duplicate"]["version"], "confirmed": True})
        self.assertEqual(result.status_code, 200, result.json)
        note = self.get(f"/api/records/{current}")
        shared = self.call(f"/api/records/{current}", {"version": note["version"], "visibility": "shared"}, method="PUT")
        self.assertEqual(shared.status_code, 200, shared.json)
        third = self.person("第三个合成人物")
        public = self.compare(first, third, "colleague")
        self.assertEqual([row["id"] for row in public["relationships"]["notes"]], [current])
        relation = public["relationships"]["notes"][0]["subjects"][0]
        self.assertEqual((relation["note_id"], relation["subject_id"]), (current, first))
        self.assertNotIn("original_note_id", relation)
        self.assertNotIn(old, json.dumps(public))
        self.assertNotIn("不能从身份预览透露的原笔记", json.dumps(public, ensure_ascii=False))
        author_note = self.compare(first, third)["relationships"]["notes"][0]
        self.assertEqual(author_note["subjects"][0]["original_note_id"], old)
        events = self.get(f"/api/people/{first}/identity-history", "colleague")["items"]
        self.assertEqual([row["id"] for row in events[0]["relationships"]["notes"]], [current])
        self.assertEqual(events[0]["relationships"]["notes"][0]["subjects"][0]["note_id"], current)
        self.assertNotIn(old, json.dumps(events))
        self.assertNotIn("不能从身份预览透露的原笔记", json.dumps(events, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
