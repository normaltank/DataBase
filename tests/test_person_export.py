"""Offline person exports use the same authenticated HTTP/file boundary as reading."""
import io
import json
import posixpath
import unittest
import zipfile
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

import test_person_identity as identity_tests


class Links(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.links = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        self.links.extend(value for key, value in attrs if key in {"href", "src"})


class PersonExportTests(unittest.TestCase):
    # Reuse HTTP setup/builders without inheriting or running the identity test cases.
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

    def export(self, pid, user="researcher"):
        response = self.clients[user].get("/api/export/content", query_string={"person": pid})
        self.assertEqual(response.status_code, 200, response.json)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        return json.loads(files["content.json"]), files

    def assert_local_links(self, files):
        for name, content in files.items():
            if not name.endswith(".html"):
                continue
            for link in Links(content.decode()).links:
                parsed = urlsplit(link)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                self.assertFalse(parsed.path.startswith("/"), (name, link))
                target = posixpath.normpath(posixpath.join(posixpath.dirname(name), unquote(parsed.path)))
                self.assertIn(target, files, (name, link))

    def test_selected_person_exports_readable_profile_relations_avatar_and_only_its_content(self):
        pid = self.person("导出人物", original_name="Synthetic Original", chinese_name="合成中文名", aliases="Other writing",
                          sources="https://example.org/synthetic-profile", introduction_html="<h2>履历</h2><table><tr><th>年份</th><th>事项</th></tr><tr><td>2024</td><td>合成介绍</td></tr></table>")
        avatar = self.image("blue")
        self.assertEqual(self.call(f"/api/people/{pid}", {"version": 1, "avatar_source": "合成头像说明", "change_note": "添加头像"},
                                   method="PUT", image=avatar).status_code, 200)
        institution = self.source()
        employment = self.call(f"/api/people/{pid}/employments", {"version": 0, "change_note": "主页履历",
            "items": [{"institution_id": institution, "role": "研究员", "start_date": "2020", "end_date": "", "evidence": "可核查任职出处"}]}, method="PUT")
        self.assertEqual(employment.status_code, 200, employment.json)
        work = self.record(title="人物的可见作品", authors="Synthetic Original", body_html="<p>原文正文</p>")
        self.bylines(work, [pid])
        note = self.record(kind="research_note", title="人物比较笔记", body_html="<p>独立判断</p>",
                           research_subjects=[{"subject_type": "person", "subject_id": pid},
                                              {"subject_type": "institution", "subject_id": institution}])
        unrelated = self.record(title="无关合成资料不应选中")
        payload, files = self.export(pid)
        self.assertEqual(set(payload["selected_ids"]), {work, note})
        self.assertNotIn(unrelated, json.dumps(payload))
        person = payload["people"][0]
        self.assertEqual((person["id"], person["version"], person["original_name"]), (pid, 2, "Synthetic Original"))
        self.assertEqual(person["employments"]["items"][0]["evidence"], "可核查任职出处")
        self.assertEqual([item["id"] for item in person["works"]], [work])
        self.assertEqual([item["id"] for item in person["research_notes"]], [note])
        self.assertEqual(files[person["avatar"]["path"]], avatar)
        offline = files[person["path"]].decode()
        for text in ["Other writing", "合成中文名", "任职出处", "人物的可见作品", "人物比较笔记", "reading-table", "Synthetic Original"]:
            self.assertIn(text, offline)
        self.assert_local_links(files)
        self.assertEqual(self.clients["researcher"].get("/api/export/content?person=missing-person").status_code, 404)
        self.assertEqual(self.app.test_client().get("/api/export/content?person=" + pid).status_code, 401)

    def test_offline_records_explain_coauthors_article_units_and_multiple_note_subjects_with_files(self):
        first, second, institution = self.person(), self.person("合成合作者"), self.source()
        journal = self.call("/api/sources", {"name": "合成期刊", "kind": "journal"}).json["id"]
        client = self.clients["researcher"]
        created = client.post("/api/records", data={"data": json.dumps({"kind": "report", "title": "带文件作品", "authors": "甲；乙", "sharing_confirmed": True}),
            "file": (io.BytesIO(b"synthetic attachment"), "synthetic-readable.txt")}, headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]})
        self.assertEqual(created.status_code, 201, created.json)
        work = created.json["id"]
        byline = self.bylines(work, [first, second])["items"][0]
        units = self.call(f"/api/records/{work}/affiliations", {**self.get(f"/api/records/{work}/affiliations"), "change_note": "作品首页",
            "items": [{"byline_id": byline["id"], "institution_id": institution, "evidence": "此作品的署名单位出处"}]}, method="PUT")
        self.assertEqual(units.status_code, 200, units.json)
        note = self.record(kind="research_note", title="跨对象比较", research_subjects=[{"subject_type": "person", "subject_id": first},
            {"subject_type": "person", "subject_id": second}, {"subject_type": "institution", "subject_id": institution},
            {"subject_type": "journal", "subject_id": journal}])
        payload, files = self.export(first)
        work_data = next(row for row in payload["records"] if row["id"] == work)
        self.assertEqual([row["target_id"] for row in work_data["bylines"]["items"]], [first, second])
        self.assertEqual(work_data["affiliations"]["items"][0]["byline_id"], byline["id"])
        offline = "\n".join(value.decode() for name, value in files.items() if name.endswith(".html"))
        for text in ["此作品的署名单位出处", "合成合作者", "合成期刊", "跨对象比较", "笔记研究对象", "甲；乙"]:
            self.assertIn(text, offline)
        # Same-name coauthors/subjects remain distinguishable in the readable HTML.
        self.assertIn(second, offline)
        attachment = payload["attachments"][0]
        self.assertEqual(files[attachment["path"]], b"synthetic attachment")
        self.assertEqual(set(row["id"] for row in payload["sources"]), {institution, journal})
        self.assert_local_links(files)

    def test_exports_recompute_permissions_for_shared_current_notes_private_origins_choices_and_endpoints(self):
        first, second, third = self.person(), self.person("另一身份"), self.person("私人改归第三人")
        old = self.record(kind="research_note", title="PRIVATE-OLD-TITLE-731", visibility="restricted",
                          research_subjects=[{"subject_type": "person", "subject_id": second}])
        current = self.record(kind="research_note", title="当前主动共享笔记", visibility="restricted")
        merged = self.call("/api/people/merge", self.intent(self.compare(first, second))).json
        preview = self.call("/api/merge/preview", {"type": "record", "keep_id": current, "duplicate_id": old}).json
        self.assertEqual(self.call("/api/merge", {"type": "record", "keep_id": current, "duplicate_id": old,
            "keep_version": preview["keep"]["version"], "duplicate_version": preview["duplicate"]["version"], "confirmed": True}).status_code, 200)
        note = self.get(f"/api/records/{current}")
        self.assertEqual(self.call(f"/api/records/{current}", {"version": note["version"], "visibility": "shared"}, method="PUT").status_code, 200)
        private = self.record(kind="research_note", title="PRIVATE-NEW-TITLE-519", visibility="restricted",
            research_subjects=[{"subject_type": "person", "subject_id": first}])
        relation = self.get(f"/api/records/{private}")["research_subjects"][0]
        corrected = self.record(kind="research_note", title="PRIVATE-CORRECTED-456", visibility="restricted",
            research_subjects=[{"subject_type": "person", "subject_id": first}])
        value = self.get(f"/api/records/{corrected}")
        value["research_subjects"][0]["subject_id"] = third
        self.assertEqual(self.call(f"/api/records/{corrected}/research-subjects", {"version": value["version"], "research_subjects": value["research_subjects"]}, method="PUT").status_code, 200)
        split = {**self.split_intent(merged["event_id"]), "allocations": {"subjects": {relation["id"]: "duplicate"}}}
        self.assertEqual(self.call("/api/people/split", split).status_code, 200)
        for pid in [first, second]:
            payload, files = self.export(pid, "colleague")
            text = "\n".join(value.decode() for name, value in files.items() if name.endswith((".json", ".html")))
            for secret in [old, "PRIVATE-OLD-TITLE-731", private, relation["id"], "PRIVATE-NEW-TITLE-519", corrected,
                           "PRIVATE-CORRECTED-456", third, "私人改归第三人", "password_hash", "credential_version", "before_json", "after_json", "choices_json"]:
                self.assertNotIn(secret, text)
            self.assert_local_links(files)
        public, _ = self.export(second, "colleague")
        self.assertIn(current, {row["id"] for row in public["records"]})
        author, _ = self.export(second)
        self.assertIn(private, {row["id"] for row in author["records"]})
        self.assertIn(relation["id"], json.dumps(author["people"][0]["identity_history"]))
        note = self.get(f"/api/records/{current}")
        self.assertEqual(self.call(f"/api/records/{current}", {"version": note["version"], "visibility": "restricted"}, method="PUT").status_code, 200)
        revoked, revoked_files = self.export(second, "colleague")
        self.assertNotIn(current, json.dumps(revoked))
        self.assertNotIn("当前主动共享笔记", "\n".join(value.decode() for name, value in revoked_files.items() if name.endswith((".json", ".html"))))

    def test_pending_and_removed_subjects_remain_explained_without_becoming_confirmed_notes(self):
        first, second = self.person(), self.person("待复核的另一身份")
        merged = self.call("/api/people/merge", self.intent(self.compare(first, second))).json
        pending = self.record(kind="research_note", title="待复核笔记", research_subjects=[{"subject_type": "person", "subject_id": first}])
        removed = self.record(kind="research_note", title="已经移除的关系笔记", research_subjects=[{"subject_type": "person", "subject_id": first}])
        note = self.get(f"/api/records/{removed}")
        self.assertEqual(self.call(f"/api/records/{removed}/research-subjects", {"version": note["version"], "research_subjects": []}, method="PUT").status_code, 200)
        self.assertEqual(self.call("/api/people/split", self.split_intent(merged["event_id"], user="colleague"), "colleague").status_code, 200)
        payload, files = self.export(first)
        person = payload["people"][0]
        self.assertEqual(person["research_notes"], [])
        self.assertEqual([row["id"] for row in person["research_notes_pending"]], [pending])
        subject = person["research_notes_pending"][0]["subjects"][0]
        self.assertEqual((subject["status"], subject["original_subject_id"]), ("needs_review", first))
        self.assertIn("合成反证", subject["identity_change"]["evidence"])
        offline = files[person["path"]].decode()
        self.assertIn("研究对象待复核", offline)
        self.assertIn("已移除", offline)
        self.assertEqual(set(payload["selected_ids"]), {pending})
        self.assert_local_links(files)

    def test_person_note_export_keeps_original_evidence_version_and_fixed_report_citations(self):
        pid = self.person()
        original = self.record(title="被摘录原文", body_html="<p>合成原始段落</p>")
        note = self.record(kind="research_note", title="带出处的对象研究笔记", evidence_record_id=original,
            quote="合成原始段落", locator="第八页", research_subjects=[{"subject_type": "person", "subject_id": pid}])
        report = self.record(kind="research_report", title="采用此笔记的报告", evidence_ids=[note])
        citation = self.get(f"/api/records/{report}")["evidence_citations"][0]["snapshot"]
        payload, files = self.export(pid)
        exported_note = next(row for row in payload["records"] if row["id"] == note)
        self.assertEqual(exported_note["evidence_version"], 1)
        self.assertIn(original, {row["id"] for row in payload["records"]})
        self.assertIn("引用原文版本 1", files[exported_note["path"]].decode())
        self.assertEqual(self.get(f"/api/records/{report}")["evidence_citations"][0]["snapshot"], citation)
        self.assert_local_links(files)

    def test_empty_person_scope_is_a_bad_request_instead_of_an_identity_cycle_or_unscoped_export(self):
        for value in ["", " "]:
            self.assertEqual(self.clients["researcher"].get("/api/export/content", query_string={"person": value}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
