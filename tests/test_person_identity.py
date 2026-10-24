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
        denied = self.call(f"/api/records/{note}/research-subjects", {"version": self.get(f"/api/records/{note}")["version"],
            "research_subjects": []}, "colleague", "PUT")
        self.assertEqual(denied.status_code, 403)
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
        self.assertFalse(new_preview.json["allowed"])
        self.assertEqual(self.call("/api/people/split", self.split_intent(merged.json["event_id"], key="changed-split", user="colleague"), "colleague").status_code, 409)
        self.assertEqual(self.get(f"/api/people/{second}")["name"], "之后的姓名")

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
        self.assertFalse(preview.json["allowed"])
        recovered = restore_backup(create_backup(self.data_dir), Path(self.temp.name) / "old-operations-recovered")
        self.clients["researcher"] = self.login("researcher", create_app(recovered, testing=True))
        self.assertEqual(self.get(f"/api/records/{original}/bylines")["items"], current_bylines)
        self.assertEqual(self.get(f"/api/records/{original}/affiliations")["items"], current_units)

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
