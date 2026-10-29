"""Person Wiki behaviours through HTTP and the supported backup/restore entrypoints."""
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from PIL import Image

from platform_app.web import create_app
from platform_app.maintenance import restore_backup
from platform_app.store import CURRENT_SCHEMA_VERSION


def legacy_automatic_fields(item):
    """Old member records have no public-acquisition jobs or machine results."""
    return {"automatic_tasks": [], "machine_classification": None,
            "machine_summary": None, "machine_summary_basis": None,
            "subject_countries": item["countries"], "subject_topics": item["keywords"],
            "classified_kind": item["kind"]}


def legacy_record_response(before, records):
    """Fixed public response additions to the frozen v5 record fixture."""
    def reading_fields(item):
        return {**legacy_automatic_fields(item), "chinese_title": "", "chinese_abstract": "", "display_title": item["title"],
                "display_abstract": item["abstract"], "translation_origin": "original",
                "reading_translation_id": "", "has_chinese": False, "abstract_is_chinese": False,
                "original_abstract_missing": not bool(item["abstract"]),
                "created_at": records[item["id"]]["created_at"]}
    new_defaults = {"research_subjects": []} if before["kind"] == "research_note" else {}
    new_defaults.update(reading_fields(before))
    new_defaults.update(chinese_title="", chinese_abstract="", adopted_translation_id="", translations=[], translation_history=[])
    new_defaults.update(volume="", issue="", pages="", issn="", attachment_matches=[], can_manage_access=True, last_verified=None, review_history=[], attachments=[
        {**attachment, "index": {"status": "unindexed", "message": "尚未建立索引"}}
        for attachment in before["attachments"]])
    new_defaults.update({key: [{**item, **reading_fields(item), "volume": "", "issue": "", "pages": "", "issn": "", "attachment_matches": [], "can_manage_access": True} for item in before[key]]
                         for key in ["linked_records", "cited_by", "excerpts"]})
    new_defaults["evidence_citations"] = [
        {**citation, "stance": "unclassified", "claim_note": "", "staleness_reasons": [],
         "identity_baseline_status": "unknown", "identity_changes": [],
         "current_original_id": citation["snapshot"].get("evidence_record_id")}
        for citation in before["evidence_citations"]]
    return {**before, **new_defaults}


class PeopleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="person-wiki-test-")
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"
        self.app = create_app(self.data_dir, testing=True)
        self.clients = {name: self.login(name) for name in ["researcher", "colleague", "admin"]}

    def login(self, name, app=None):
        client = (app or self.app).test_client()
        token = client.get("/api/session").json["csrf"]
        response = client.post("/api/login", json={"username": name, "password": "LocalDemo2026!"},
                               headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 200)
        return client

    def call(self, path, data=None, user="researcher", method="POST", file=None):
        client = self.clients[user]
        headers = {"X-CSRF-Token": client.get("/api/session").json["csrf"]}
        payload = {"json": data or {}} if not file else {"data": {
            "data": json.dumps(data), "file": (io.BytesIO(file[1]), file[0])}}
        return client.open(path, method=method, headers=headers, **payload)

    def person(self, **extra):
        response = self.call("/api/people", {"name": "示例作者", "change_note": "受控人物主页", **extra})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["id"]

    def detail(self, pid, user="researcher"):
        response = self.clients[user].get("/api/people/" + pid)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def download(self, url, user="researcher"):
        with self.clients[user].get(url) as response:
            self.assertEqual(response.status_code, 200)
            return response.data

    def test_create_independent_same_name_people_and_search_registered_names(self):
        first = self.person(name="Alex Smith", original_name="Aleksandrs Smits", chinese_name="亚历克斯",
                            aliases="A. Smith\n阿列克斯", introduction_html="<h2>经历</h2><p>经济研究</p>",
                            sources="https://example.org/person-a")
        second = self.person(name="Alex Smith", introduction_html="<p>语言研究</p>")
        self.assertNotEqual(first, second)
        person = self.detail(first, "colleague")
        self.assertEqual(person["version"], 1)
        self.assertTrue(person["can_edit"])
        self.assertTrue(person["can_restore"])
        self.assertIsNone(person["avatar"])
        self.assertEqual(person["sources"], "https://example.org/person-a")
        for query in ["Aleksandrs", "亚历克斯", "A. Smith", "阿列克斯"]:
            results = self.clients["colleague"].get("/api/people", query_string={"q": query}).json
            self.assertEqual([p["id"] for p in results["items"]], [first])
        results = self.clients["colleague"].get("/api/people?q=Alex%20Smith").json
        self.assertEqual({p["id"] for p in results["items"]}, {first, second})
        self.assertEqual(results["total"], 2)
        self.assertEqual(self.clients["researcher"].get("/api/records").json["total"], 0)
        self.assertNotIn(first, [u["id"] for u in self.clients["researcher"].get("/api/users").json["items"]])

    def test_same_name_people_without_introductions_have_all_registered_institution_hints(self):
        first, second = self.person(name="同名待辨认作者"), self.person(name="同名待辨认作者")
        institutions = []
        for name in ["Alpha 合成机构", "Beta 合成机构", "Gamma 历史机构", "已移除的机构"]:
            response = self.call("/api/sources", {"name": name, "kind": "institution"})
            self.assertEqual(response.status_code, 201, response.json)
            institutions.append(response.json["id"])
        for pid, selected in [(first, [0, 2, 3]), (second, [1])]:
            current = self.clients["researcher"].get(f"/api/people/{pid}/employments").json
            response = self.call(f"/api/people/{pid}/employments", {**current, "change_note": "合成机构履历",
                "items": [{"institution_id": institutions[index], "role": "有据研究任职", "start_date": "2001" if index == 2 else "",
                           "end_date": "2010" if index == 2 else "", "evidence": "合成履历原页"} for index in selected]}, method="PUT")
            self.assertEqual(response.status_code, 200, response.json)
        current = self.clients["researcher"].get(f"/api/people/{first}/employments").json
        response = self.call(f"/api/people/{first}/employments", {**current, "items": current["items"][:2], "change_note": "移除误登机构"}, method="PUT")
        self.assertEqual(response.status_code, 200, response.json)
        expected = {first: [{"id": institutions[0], "name": "Alpha 合成机构"}, {"id": institutions[2], "name": "Gamma 历史机构"}],
                    second: [{"id": institutions[1], "name": "Beta 合成机构"}]}
        for who in self.clients:
            results = self.clients[who].get("/api/people", query_string={"q": "同名待辨认作者"}).json
            self.assertEqual(results["total"], 2)
            for person in results["items"]:
                self.assertEqual(person["introduction_text"], "")
                self.assertEqual(person["institution_hints"], expected[person["id"]])
                self.assertEqual(self.detail(person["id"], who)["institution_hints"], expected[person["id"]])

    def test_members_edit_safe_introduction_reject_stale_save_and_restore_history(self):
        pid = self.person(sources="第一版出处")
        response = self.call("/api/people/" + pid, {"version": 1, "name": "共同修订姓名",
            "introduction_html": '<h2>研究</h2><p>介绍</p><ul><li>方向</li></ul><table><tr><td>任一事实</td></tr></table>'
                                 '<a href="https://example.org/">出处</a><script>bad()</script><img src=x onerror=bad()>'
                                 '<a href="javascript:bad()" onclick="bad()">不安全链接</a>',
            "sources": "机构主页第 2 节", "change_note": "依据机构介绍修订"}, user="colleague", method="PUT")
        self.assertEqual(response.status_code, 200, response.json)
        current = self.detail(pid)
        self.assertEqual(current["version"], 2)
        for element in ["<h2>", "<p>", "<ul>", "<table>", 'href="https://example.org/"']:
            self.assertIn(element, current["introduction_html"])
        for unsafe in ["script", "onerror", "onclick", "javascript:", "<img"]:
            self.assertNotIn(unsafe, current["introduction_html"])
        self.assertEqual(current["last_modifier"]["id"], "colleague")
        stale = self.call("/api/people/" + pid, {"version": 1, "name": "过期覆盖", "change_note": "旧输入"}, method="PUT")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.detail(pid)["name"], "共同修订姓名")
        history = self.clients["colleague"].get("/api/people/" + pid + "/history").json["items"]
        self.assertEqual([h["version"] for h in history], [2, 1])
        self.assertEqual(history[0]["snapshot"]["change_note"], "依据机构介绍修订")
        self.assertEqual(history[0]["actor_id"], "colleague")
        restored = self.call(f"/api/people/{pid}/restore/{history[-1]['id']}", {"version": 2, "change_note": "纠正误改"}, user="admin")
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual(self.detail(pid)["sources"], "第一版出处")
        self.assertEqual(self.detail(pid)["version"], 3)
        self.assertEqual(self.detail(pid)["change_note"], "纠正误改")
        self.assertEqual(self.call(f"/api/people/{pid}/restore/{history[-1]['id']}", {"version": 2, "change_note": "旧版本恢复"}).status_code, 409)
        anonymous = self.app.test_client()
        for path in ["/api/people", "/api/people/" + pid, "/api/people/" + pid + "/history"]:
            self.assertEqual(anonymous.get(path).status_code, 401)
        response = self.call("/api/members/colleague", {"active": False}, user="admin", method="PUT")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.clients["colleague"].get("/api/people/" + pid).status_code, 401)
        self.assertEqual(self.call("/api/people/" + pid, {"version": 3, "name": "停用账号覆盖", "change_note": "无效"}, user="colleague", method="PUT").status_code, 401)

    def test_validated_avatar_replacement_removal_and_historical_restore(self):
        images = {}
        for format in ["JPEG", "PNG", "WEBP"]:
            output = io.BytesIO()
            Image.new("RGB", (24, 24), (31, 77, 121)).save(output, format=format)
            images[format] = output.getvalue()
        response = self.call("/api/people", {"name": "合成头像人物", "change_note": "登记合成样本", "avatar_source": "测试生成图像"},
                             file=("portrait.jpg", images["JPEG"]))
        self.assertEqual(response.status_code, 201, response.json)
        pid, first = response.json["id"], response.json["avatar"]
        self.assertIsNotNone(first)
        self.assertEqual(self.download(first["url"], "colleague"), images["JPEG"])
        for version, format in [(1, "PNG"), (2, "WEBP")]:
            changed = self.call("/api/people/" + pid, {"version": version, "change_note": "替换图像", "avatar_source": "新合成图像"},
                                user="colleague", method="PUT", file=("next." + format.lower(), images[format]))
            self.assertEqual(changed.status_code, 200, changed.json)
            self.assertEqual(self.download(changed.json["avatar"]["url"]), images[format])
        stale = self.call("/api/people/" + pid, {"version": 2, "change_note": "过期替换", "avatar_source": "旧输入"},
                          method="PUT", file=("old.png", images["PNG"]))
        self.assertEqual(stale.status_code, 409)
        removed = self.call("/api/people/" + pid, {"version": 3, "remove_avatar": True, "change_note": "移除当前头像"}, method="PUT")
        self.assertEqual(removed.status_code, 200, removed.json)
        self.assertIsNone(removed.json["avatar"])
        self.assertEqual(self.download(first["url"]), images["JPEG"])
        history = self.clients["researcher"].get("/api/people/" + pid + "/history").json["items"]
        self.assertEqual(history[-1]["snapshot"]["avatar"]["id"], first["id"])
        restored = self.call(f"/api/people/{pid}/restore/{history[-1]['id']}", {"version": 4, "change_note": "恢复原头像"})
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual(restored.json["avatar"]["id"], first["id"])
        for filename, content in [("fake.png", b"not an image"), ("wrong.jpg", images["PNG"]),
                                  ("truncated.png", images["PNG"][:45]), ("big.png", images["PNG"] + b"x" * (5*1024*1024))]:
            rejected = self.call("/api/people/" + pid, {"version": 5, "name": "失败不能改名", "change_note": "不合法图像", "avatar_source": "测试"},
                                 method="PUT", file=(filename, content))
            self.assertEqual(rejected.status_code, 400, rejected.json)
            self.assertEqual(self.detail(pid)["version"], 5)
            self.assertEqual(self.detail(pid)["name"], "合成头像人物")
        self.assertEqual(self.app.test_client().get(first["url"]).status_code, 401)
        other = self.person()
        self.assertEqual(self.clients["researcher"].get(first["url"].replace(pid, other)).status_code, 404)

    def test_full_backup_restores_current_and_history_avatars_and_allows_continued_edit(self):
        output = io.BytesIO()
        Image.new("RGB", (20, 20), "blue").save(output, "PNG")
        picture = output.getvalue()
        response = self.call("/api/people", {"name": "恢复样本", "change_note": "合成主页", "avatar_source": "受控图像"},
                             file=("test.png", picture))
        self.assertEqual(response.status_code, 201)
        pid, avatar = response.json["id"], response.json["avatar"]
        changed = self.call("/api/people/" + pid, {"version": 1, "remove_avatar": True, "change_note": "移除当前图像"}, method="PUT")
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.call("/api/backup").status_code, 403)
        with self.call("/api/backup", user="admin") as backup:
            self.assertEqual(backup.status_code, 200)
            archive = Path(self.temp.name) / "full.zip"
            archive.write_bytes(backup.data)
        with zipfile.ZipFile(archive) as z:
            self.assertIn(picture, [z.read(n) for n in z.namelist() if n.startswith("avatars/")])
        target = Path(self.temp.name) / "restored"
        restore_backup(archive, target)
        recovered = create_app(target, testing=True)
        self.clients = {name: self.login(name, recovered) for name in self.clients}
        self.assertIsNone(self.detail(pid)["avatar"])
        self.assertEqual(self.download(avatar["url"]), picture)
        history = self.clients["colleague"].get("/api/people/" + pid + "/history").json["items"]
        self.assertEqual([h["version"] for h in history], [2, 1])
        restore = self.call(f"/api/people/{pid}/restore/{history[-1]['id']}", {"version": 2, "change_note": "恢复后继续工作"}, user="colleague")
        self.assertEqual(restore.status_code, 200, restore.json)
        edited = self.call("/api/people/" + pid, {"version": 3, "name": "恢复后可编辑", "change_note": "继续核对"}, method="PUT")
        self.assertEqual(edited.status_code, 200, edited.json)
        self.assertEqual(self.detail(pid)["name"], "恢复后可编辑")
        self.assertEqual(self.download(self.detail(pid)["avatar"]["url"]), picture)

    def test_v5_upgrade_backs_up_preserves_old_work_and_repeated_start_does_not_create_people(self):
        fixture = Path(__file__).parent / "fixtures"
        expected = json.loads((fixture / "people_v5.json").read_text(encoding="utf-8"))
        legacy = Path(self.temp.name) / "legacy"
        (legacy / "uploads").mkdir(parents=True)
        # A frozen legacy fixture is setup only; all assertions use HTTP or backup/restore.
        with closing(sqlite3.connect(legacy / "platform.sqlite3")) as db:
            db.executescript((fixture / "people_v5.sql").read_text(encoding="utf-8"))
        for filename, content in expected["files"].items():
            (legacy / "uploads" / filename).write_text(content, encoding="utf-8", newline="")
        upgraded = create_app(legacy, testing=True)
        self.clients = {name: self.login(name, upgraded) for name in self.clients}
        self.assertEqual(self.clients["researcher"].get("/health").json["schema"], CURRENT_SCHEMA_VERSION)
        self.assertEqual(self.clients["researcher"].get("/api/people").json["total"], 0)
        for rid, before in expected["records"].items():
            self.assertEqual(self.clients["researcher"].get("/api/records/" + rid).json, legacy_record_response(before, expected["records"]))
            self.assertEqual(self.clients["researcher"].get("/api/history/record/" + rid).json, expected["history"][rid])
            for attachment in before["attachments"]:
                self.assertEqual(self.download("/api/attachments/" + attachment["id"]), b"Synthetic legacy attachment.\n")
        # The legacy institution has no registered country. Its new query-only
        # projection is empty; every pre-existing source field must stay exact.
        expected_source = {**expected["source"], "filter_countries": [], "last_verified": None, "review_history": []}
        self.assertEqual(self.clients["researcher"].get("/api/sources/" + expected["source"]["id"]).json, expected_source)
        expected_collection = {**expected["collection"], "scope_log_json": "[]", "scope_log": [], "excluded_items": [], "items": [
            {**item, **legacy_automatic_fields(item), "chinese_title": "", "chinese_abstract": "", "display_title": item["title"],
             "display_abstract": item["abstract"], "translation_origin": "original", "reading_translation_id": "",
             "has_chinese": False, "abstract_is_chinese": False, "original_abstract_missing": not bool(item["abstract"]),
             "created_at": expected["records"][item["id"]]["created_at"],
             "attachment_matches": [], "can_manage_access": True, "volume": "", "issue": "", "pages": "", "issn": "", "disposition": "included", "rationale": ""} for item in expected["collection"]["items"]]}
        self.assertEqual(self.clients["researcher"].get("/api/collections/" + expected["collection"]["id"]).json, expected_collection)
        backups = list((legacy / "backups").glob("*.zip"))
        self.assertEqual(len(backups), CURRENT_SCHEMA_VERSION - 5)
        archived_versions = {}
        for index, archive in enumerate(backups):
            with zipfile.ZipFile(archive) as bundle:
                snapshot = Path(self.temp.name) / f"upgrade-{index}.sqlite3"
                snapshot.write_bytes(bundle.read("platform.sqlite3"))
            with closing(sqlite3.connect(snapshot)) as db:
                archived_versions[int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0])] = archive
        self.assertEqual(set(archived_versions), set(range(5, CURRENT_SCHEMA_VERSION)))
        pid = self.person(name="升级后建立的人物")
        restarted = create_app(legacy, testing=True)
        self.clients = {name: self.login(name, restarted) for name in self.clients}
        self.assertEqual(self.clients["researcher"].get("/api/people").json["total"], 1)
        self.assertEqual(self.detail(pid)["version"], 1)
        self.assertEqual(list((legacy / "backups").glob("*.zip")), backups)
        restored = restore_backup(archived_versions[5], Path(self.temp.name) / "before-upgrade")
        recovered = create_app(restored, testing=True)
        self.clients = {name: self.login(name, recovered) for name in self.clients}
        self.assertEqual(self.clients["researcher"].get("/api/people").json["total"], 0)
        for rid, before in expected["records"].items():
            self.assertEqual(self.clients["researcher"].get("/api/records/" + rid).json, legacy_record_response(before, expected["records"]))
        self.assertEqual(self.call("/api/records/" + next(iter(expected["records"])),
            {"version": 2, "title": "恢复旧版备份后继续修订"}, method="PUT").status_code, 200)


if __name__ == "__main__":
    unittest.main()
