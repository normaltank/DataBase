import io
import json
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from platform_app.maintenance import create_backup, restore_backup
from platform_app.store import connect
from platform_app.web import create_app


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="research-workflow-test-")
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"
        self.app = create_app(self.data_dir, testing=True)
        self.clients = {name: self.login(name) for name in ["researcher", "colleague", "admin"]}

    def login(self, name, app=None):
        client = (app or self.app).test_client()
        token = client.get("/api/session").json["csrf"]
        result = client.post("/api/login", json={"username": name, "password": "LocalDemo2026!"}, headers={"X-CSRF-Token": token})
        self.assertEqual(result.status_code, 200)
        return client

    def call(self, path, data=None, user="researcher", method="POST", file=None):
        client = self.clients[user]
        token = client.get("/api/session").json["csrf"]
        kwargs = {"headers": {"X-CSRF-Token": token}}
        if file:
            kwargs["data"] = {"data": json.dumps(data), "file": (io.BytesIO(file[1]), file[0])}
        else:
            kwargs["json"] = data or {}
        return client.open(path, method=method, **kwargs)

    def source(self, name="测试期刊", kind="journal", **extra):
        result = self.call("/api/sources", {"name": name, "kind": kind, **extra})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json["id"]

    def record(self, kind="report", **extra):
        result = self.call("/api/records", {"kind": kind, "title": "测试资料", **extra})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json["id"]

    def detail(self, rid, user="researcher"):
        response = self.clients[user].get("/api/records/" + rid)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def test_directory_shared_body_search_and_history(self):
        journal = self.source(aliases="别名刊物", introduction_html="<h2>领域介绍</h2><p>稀有介绍词</p>")
        institute = self.source("测试机构", "institution")
        result = self.call("/api/records", {"kind": "directory_translation", "title": "跨期译目", "authors": "译者甲",
            "coverage": "2024—2026，第 1—4 期", "related_source_ids": [journal, institute],
            "body_html": '<h2>篇目</h2><table><tr><th>题名</th></tr><tr><td>独特正文检索词</td></tr></table><script>alert(1)</script><a href="javascript:alert(1)" onclick="bad()">链接</a>',
            "aliases": "目录别称", "sharing_confirmed": True}, file=("稿件.pdf", b"%PDF-1.4\nfixture"))
        self.assertEqual(result.status_code, 201, result.json)
        rid = result.json["id"]
        first = self.detail(rid, "colleague")
        self.assertTrue(first["can_edit"])
        self.assertIn("<table>", first["body_html"])
        self.assertNotIn("script", first["body_html"])
        self.assertNotIn("onclick", first["body_html"])
        self.assertIsNone(first["source_id"])
        self.assertIsNone(first["serial_id"])
        for q in ["独特正文检索词", "目录别称", "别名刊物"]:
            results = self.clients["colleague"].get("/api/records", query_string={"q": q}).json
            self.assertEqual([r["id"] for r in results["items"]], [rid])
        self.assertEqual(self.clients["researcher"].get("/api/sources?q=稀有介绍词").json["total"], 1)
        for sid in [journal, institute]:
            self.assertEqual(self.clients["colleague"].get("/api/records?source=" + sid).json["total"], 1)
        edit = self.call("/api/records/" + rid, {"version": 1, "body_html": "<p>同事修订</p>", "related_source_ids": [journal]}, user="colleague", method="PUT")
        self.assertEqual(edit.status_code, 200, edit.json)
        conflict = self.call("/api/records/" + rid, {"version": 1, "body_html": "<p>旧版覆盖</p>"}, method="PUT")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.detail(rid)["authors"], "译者甲")
        self.assertEqual(self.detail(rid)["last_modifier"]["name"], "研究员 · 周")
        history = self.clients["colleague"].get("/api/history/record/" + rid).json["items"]
        restored = self.call(f"/api/history/{history[-1]['id']}/restore", {"version": 2}, user="colleague")
        self.assertEqual(restored.status_code, 200, restored.json)
        current = self.detail(rid)
        self.assertEqual(current["body_html"], first["body_html"])
        self.assertEqual(set(current["related_source_ids"]), {journal, institute})
        self.assertEqual(current["attachments"], first["attachments"])

    def test_personal_author_confirmation_and_admin_boundary(self):
        rid = self.record("compilation", author_id="colleague", body_html="<p>代交正文</p>", editors=["researcher", "admin"], visibility="restricted")
        for who in self.clients:
            self.assertFalse(self.detail(rid, who)["can_edit"])
            self.assertEqual(self.call("/api/records/" + rid, {"version": 1, "body_html": "越权"}, user=who, method="PUT").status_code, 403)
        self.assertEqual(self.call("/api/records/" + rid + "/author", {"version": 1, "author_id": "colleague", "confirm": True}, user="admin").status_code, 403)
        response = self.call("/api/records/" + rid + "/author", {"version": 1, "confirm": True}, user="colleague")
        self.assertEqual(response.status_code, 200, response.json)
        self.assertFalse(self.detail(rid, "admin")["can_edit"])
        self.assertTrue(self.detail(rid, "colleague")["can_edit"])
        grant = self.call("/api/records/" + rid, {"version": 2, "editors": ["admin"]}, user="colleague", method="PUT")
        self.assertEqual(grant.status_code, 200, grant.json)
        self.assertEqual(self.call("/api/records/" + rid, {"version": 3, "body_html": "<p>获授权管理员修订</p>"}, user="admin", method="PUT").status_code, 200)
        self.assertEqual(self.call("/api/records/" + rid, {"version": 4, "editors": ["admin", "researcher"]}, user="admin", method="PUT").status_code, 403)
        self.assertEqual(self.call("/api/records/" + rid, {"version": 4, "editors": []}, user="colleague", method="PUT").status_code, 200)
        with closing(connect(self.data_dir / "platform.sqlite3")) as db:
            rev = db.execute("SELECT id FROM revisions WHERE target_id=? ORDER BY id LIMIT 1", (rid,)).fetchone()[0]
        self.assertEqual(self.call(f"/api/history/{rev}/restore", {"version": 5}, user="admin").status_code, 403)
        self.assertEqual(self.call(f"/api/history/{rev}/restore", {"version": 5}, user="colleague").status_code, 200)
        self.assertTrue(self.detail(rid, "colleague")["author_confirmed"])
        self.assertEqual(self.detail(rid)["editors"], [])

    def test_restricted_search_and_common_type_cannot_widen_personal_rights(self):
        rid = self.record("compilation", body_html="<p>不应出现的密文</p>", visibility="restricted")
        self.assertEqual(self.clients["colleague"].get("/api/records?q=不应出现的密文").json["total"], 0)
        response = self.call("/api/records/" + rid, {"version": 1, "kind": "directory_translation"}, method="PUT")
        self.assertEqual(response.status_code, 400)
        raw = self.record("report")
        self.assertTrue(self.detail(raw, "admin")["can_edit"])

    def test_backup_restores_body_relations_and_historical_only_attachment(self):
        sid = self.source()
        rid = self.record("directory_translation", authors="译者", coverage="2026", related_source_ids=[sid], body_html="<p>原正文</p>")
        for version, filename in [(1, "旧文件.txt"), (2, "后来文件.txt")]:
            result = self.call("/api/records/" + rid, {"version": version, "sharing_confirmed": True}, method="PUT", file=(filename, filename.encode()))
            self.assertEqual(result.status_code, 200, result.json)
        h = self.clients["researcher"].get("/api/history/record/" + rid).json["items"]
        self.assertEqual(self.call(f"/api/history/{h[1]['id']}/restore", {"version": 3}).status_code, 200)
        archive = create_backup(self.data_dir)
        restored = restore_backup(archive, Path(self.temp.name) / "restored")
        app = create_app(restored, testing=True)
        client = self.login("colleague", app)
        data = client.get("/api/records/" + rid).json
        self.assertEqual(data["body_html"], "<p>原正文</p>")
        self.assertEqual(data["related_source_ids"], [sid])
        self.assertEqual(len(data["attachments"]), 1)
        with closing(connect(restored / "platform.sqlite3")) as db:
            attachments = db.execute("SELECT * FROM attachments").fetchall()
            self.assertEqual(len(attachments), 2)
            self.assertTrue(all((restored / "uploads" / a["stored_name"]).is_file() for a in attachments))

    def test_evidence_versions_and_report_snapshots_remain_pinned(self):
        original = self.record(title="原始政策资料", body_html="<p>原文初版</p>")
        note = self.record("research_note", title="阅读摘录", evidence_record_id=original, quote="原文观点", translation="我的译文", interpretation="研究员解释", locator="第 12 页，第 3 段", evidence_url="https://example.org/paper#page=12")
        report = self.record("research_report", evidence_ids=[note], body_html="<p>分析报告</p>")
        self.assertEqual(self.detail(note)["evidence_version"], 1)
        self.assertEqual(self.call("/api/records/" + original, {"version": 1, "body_html": "<p>原文修订</p>"}, method="PUT").status_code, 200)
        self.assertEqual(self.call("/api/records/" + note, {"version": 1, "interpretation": "修改解释"}, method="PUT").status_code, 200)
        self.assertEqual(self.detail(note)["evidence_version"], 1)
        cited = self.detail(report)["evidence_citations"][0]
        self.assertEqual(cited["snapshot"]["interpretation"], "研究员解释")
        self.assertEqual(cited["excerpt_version"], 1)
        self.assertEqual(cited["current_version"], 2)
        self.assertEqual(self.call("/api/records/" + report, {"version": 1, "evidence_ids": [note], "body_html": "<p>报告补充</p>"}, method="PUT").status_code, 200)
        self.assertEqual(self.detail(report)["evidence_citations"][0]["excerpt_version"], 1)
        self.assertEqual(self.call("/api/records/" + report, {"version": 2, "evidence_ids": [note], "refresh_citations": True}, method="PUT").status_code, 200)
        self.assertEqual(self.detail(report)["evidence_citations"][0]["excerpt_version"], 2)
        self.assertEqual(self.clients["researcher"].get("/api/records/" + original).json["excerpts"][0]["id"], note)
        self.assertEqual(self.call("/api/records/" + original, {"version": 2, "visibility": "restricted"}, method="PUT").status_code, 200)
        self.assertEqual(self.clients["colleague"].get("/api/records/" + note).status_code, 404)
        self.assertEqual(self.detail(report, "colleague")["evidence_citations"], [])
        self.assertEqual(self.clients["colleague"].get("/api/records?q=我的译文").json["total"], 0)

    def test_merge_records_redirects_every_reference_and_retains_archive(self):
        keep = self.record(title="同一资料")
        duplicate = self.record(title="同一资料", aliases="旧译题")
        self.assertEqual(self.call("/api/records/" + duplicate, {"version": 1, "sharing_confirmed": True}, method="PUT", file=("旧附件.txt", b"kept file")).status_code, 200)
        note = self.record("research_note", evidence_record_id=duplicate, quote="原文摘录", locator="第 7 页")
        report = self.record("compilation", linked_ids=[duplicate], evidence_ids=[note])
        collection = self.call("/api/collections", {"name": "合并测试专题", "visibility": "shared"}).json["id"]
        self.call(f"/api/collections/{collection}/items", {"record_id": duplicate})
        self.call("/api/favorites/" + duplicate, {"saved": True})
        candidates = self.clients["admin"].get("/api/duplicates?type=record").json["items"]
        self.assertTrue(any({r["keep"]["id"], r["duplicate"]["id"]} == {keep, duplicate} for r in candidates))
        preview = self.call("/api/merge/preview", {"type": "record", "keep_id": keep, "duplicate_id": duplicate}, user="admin")
        self.assertTrue(preview.json["allowed"])
        self.assertEqual(preview.json["impact"]["附件"], 1)
        merged = self.call("/api/merge", {"type": "record", "keep_id": keep, "duplicate_id": duplicate, "keep_version": 1, "duplicate_version": 2, "confirmed": True}, user="admin")
        self.assertEqual(merged.status_code, 200, merged.json)
        self.assertEqual(self.detail(duplicate)["id"], keep)
        self.assertEqual(self.detail(note)["evidence_record_id"], keep)
        self.assertEqual(self.detail(report)["linked_records"][0]["id"], keep)
        self.assertEqual(self.clients["researcher"].get("/api/records?collection=" + collection).json["items"][0]["id"], keep)
        self.assertTrue(self.detail(keep)["favorite"])
        self.assertEqual(len(self.detail(keep)["attachments"]), 1)
        self.assertIn(duplicate, self.detail(keep)["previous_ids"])
        self.assertIn("旧译题", self.detail(keep)["aliases"])
        self.assertEqual(self.clients["researcher"].get("/api/merged/record/" + duplicate).json["archived"]["title"], "同一资料")
        history = self.clients["researcher"].get("/api/history/record/" + keep).json["items"]
        old = next(h for h in history if h["target_id"] == duplicate)
        self.assertFalse(old["restorable"])
        self.assertEqual(self.call(f"/api/history/{old['id']}/restore", {"version": self.detail(keep)["version"]}).status_code, 409)
        self.assertEqual(self.clients["researcher"].get(f"/api/history/{old['id']}").status_code, 200)

    def test_merge_source_graph_redirects_and_blocks_collapsing_cycle(self):
        keep = self.source("机构甲", "institution")
        duplicate = self.source("机构甲另一登记", "institution")
        child = self.source("子机构", "institution", relationships=[{"type": "part_of", "target_id": duplicate, "evidence": "登记依据", "checked_on": ""}])
        journal = self.source("主办期刊", host_id=duplicate, host_evidence="主办登记")
        raw = self.record(source_id=duplicate)
        merged = self.call("/api/merge", {"type": "source", "keep_id": keep, "duplicate_id": duplicate, "keep_version": 1, "duplicate_version": 1, "confirmed": True}, user="admin")
        self.assertEqual(merged.status_code, 200, merged.json)
        self.assertEqual(self.detail(raw)["source_id"], keep)
        self.assertEqual(self.clients["researcher"].get("/api/sources/" + journal).json["host_id"], keep)
        self.assertEqual(self.clients["researcher"].get("/api/sources/" + child).json["relationships"][0]["target_id"], keep)
        self.assertEqual(self.clients["researcher"].get("/api/sources/" + duplicate).json["id"], keep)
        attempted = self.call("/api/merge", {"type": "source", "keep_id": keep, "duplicate_id": child, "keep_version": 2, "duplicate_version": 2, "confirmed": True}, user="admin")
        self.assertIn(attempted.status_code, [400, 409], attempted.json)
        self.assertEqual(self.clients["researcher"].get("/api/sources/" + child).json["id"], child)
        self.assertEqual(self.clients["researcher"].get("/api/sources/" + keep).json["version"], 2)

    def test_merge_denies_visibility_and_unauthorized_personal_content(self):
        one = self.record(visibility="shared")
        two = self.record(visibility="restricted")
        denied = self.call("/api/merge/preview", {"type": "record", "keep_id": one, "duplicate_id": two}, user="admin")
        self.assertFalse(denied.json["allowed"])
        first, second = self.record("compilation"), self.record("compilation")
        denied = self.call("/api/merge", {"type": "record", "keep_id": first, "duplicate_id": second, "keep_version": 1, "duplicate_version": 1, "confirmed": True}, user="admin")
        self.assertEqual(denied.status_code, 403)

    def test_collection_research_privacy_revision_and_reference_removal(self):
        note = self.record("research_note", title="我的笔记", body_html="<p>比较依据</p>")
        result = self.call("/api/collections", {"name": "研究问题专题", "visibility": "shared", "research_question": "政策如何变化？", "comparison_html": "<table><tr><td>比较</td></tr></table>", "stage_judgment": "尚需更多证据"})
        self.assertEqual(result.status_code, 201, result.json)
        cid = result.json["id"]
        self.call(f"/api/collections/{cid}/items", {"record_id": note})
        self.assertEqual(self.clients["colleague"].get(f"/api/collections/{cid}").json["items"][0]["id"], note)
        edited = self.call(f"/api/collections/{cid}", {"version": 2, "stage_judgment": "另一成员补充判断"}, user="colleague", method="PUT")
        self.assertEqual(edited.status_code, 200, edited.json)
        self.assertEqual(self.call(f"/api/collections/{cid}", {"version": 2, "stage_judgment": "过期覆盖"}, method="PUT").status_code, 409)
        self.assertEqual(self.call(f"/api/collections/{cid}", {"version": 3, "visibility": "private"}, user="colleague", method="PUT").status_code, 403)
        self.call(f"/api/collections/{cid}/items", {"record_id": note, "remove": True}, user="colleague")
        self.assertEqual(self.detail(note)["title"], "我的笔记")
        self.assertEqual(self.clients["researcher"].get(f"/api/collections/{cid}").json["items"], [])
        history = self.clients["researcher"].get(f"/api/collections/{cid}/history").json["items"]
        restored = self.call(f"/api/collections/{cid}/restore/{history[2]['id']}", {"version": 4})
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual(len(self.clients["researcher"].get(f"/api/collections/{cid}").json["items"]), 1)
        self.assertEqual(self.call(f"/api/collections/{cid}", {"version": 5, "visibility": "private"}, method="PUT").status_code, 200)
        self.assertEqual(self.clients["admin"].get(f"/api/collections/{cid}").status_code, 404)
        self.assertNotIn("研究问题专题", str(self.clients["colleague"].get("/api/dashboard").json))

    def test_member_management_revokes_sessions_preserves_history_and_last_admin(self):
        created = self.call("/api/members", {"username": "new.member", "name": "新成员", "role": "researcher", "password": "UniquePassword2026!"}, user="admin")
        self.assertEqual(created.status_code, 201, created.json)
        uid = created.json["id"]
        self.assertEqual(self.clients["researcher"].get("/api/members").status_code, 403)
        client = self.app.test_client()
        csrf = client.get("/api/session").json["csrf"]
        signed = client.post("/api/login", json={"username": "new.member", "password": "UniquePassword2026!"}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(signed.status_code, 200)
        self.clients["new"] = client
        rid = self.call("/api/records", {"title": "新成员稿件", "kind": "research_note"}, user="new").json["id"]
        self.assertEqual(self.call("/api/members/" + uid, {"active": False}, user="admin", method="PUT").status_code, 200)
        self.assertEqual(client.get("/api/records").status_code, 401)
        self.assertEqual(self.detail(rid)["owner_name"], "新成员")
        self.assertEqual(self.call("/api/members/admin", {"active": False}, user="admin", method="PUT").status_code, 409)
        self.assertEqual(self.call("/api/members/admin", {"role": "researcher"}, user="admin", method="PUT").status_code, 409)
        self.assertEqual(self.call("/api/members/" + uid, {"active": True, "password": "Replacement2026!"}, user="admin", method="PUT").status_code, 200)
        self.assertEqual(client.get("/api/records").status_code, 401)
        second = self.login("researcher")
        self.assertEqual(self.call("/api/account/password", {"old_password": "LocalDemo2026!", "new_password": "ChangedPassword2026!"}).status_code, 200)
        self.assertEqual(self.clients["researcher"].get("/api/records").status_code, 200)
        self.assertEqual(second.get("/api/records").status_code, 401)

    def test_readable_content_export_filters_private_evidence_and_credentials(self):
        raw = self.record(title="共享原文")
        self.call("/api/records/" + raw, {"version": 1, "sharing_confirmed": True}, method="PUT", file=("原文.txt", "文件正文".encode()))
        aid = self.detail(raw)["attachments"][0]["id"]
        note = self.record("research_note", evidence_record_id=raw, quote="原文摘录段落", translation="译文", locator="第 4 页", evidence_attachment_id=aid)
        report = self.record("research_report", title="共享分析报告", body_html="<h2>结论</h2><p>正文可阅读</p>", evidence_ids=[note])
        hidden = self.record("research_note", title="不能导出的私有文字", body_html="<p>私有笔记秘密正文</p>", visibility="restricted")
        output = self.clients["colleague"].get("/api/export/content", query_string={"kind": "research_report"})
        self.assertEqual(output.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(output.data)) as archive:
            payload = json.loads(archive.read("content.json"))
            ids = {r["id"] for r in payload["records"]}
            self.assertEqual(ids, {raw, note, report})
            self.assertNotIn(hidden, ids)
            self.assertEqual(len(payload["attachments"]), 1)
            joined = "\n".join(archive.read(n).decode("utf-8") for n in archive.namelist() if n.endswith(("html", "json")))
            self.assertIn("正文可阅读", joined)
            self.assertIn("原文摘录段落", joined)
            self.assertNotIn("password_hash", joined)
            self.assertNotIn("私有笔记秘密正文", joined)
        self.call("/api/records/" + raw, {"version": 2, "visibility": "restricted"}, method="PUT")
        output = self.clients["colleague"].get("/api/export/content", query_string={"kind": "research_report"})
        with zipfile.ZipFile(io.BytesIO(output.data)) as archive:
            payload = json.loads(archive.read("content.json"))
            self.assertEqual([r["id"] for r in payload["records"]], [report])
            self.assertEqual(payload["attachments"], [])
            self.assertNotIn("原文摘录段落", archive.read("content.json").decode())

    def test_complete_workflow_backup_restores_all_new_state(self):
        journal = self.source(aliases="可交换期刊别名", introduction_html="<h2>来源介绍</h2>")
        directory = self.record("directory_translation", title="完整流程译稿", authors="编译者", coverage="2025—2026 跨期", related_source_ids=[journal], body_html="<table><tr><td>译目录表格</td></tr></table>")
        raw = self.record(title="完整流程原文", serial_id=journal)
        self.call("/api/records/" + raw, {"version": 1, "sharing_confirmed": True}, method="PUT", file=("依据.txt", "可恢复原文附件".encode()))
        note = self.record("research_note", title="完整流程摘录", evidence_record_id=raw, quote="摘录原文", translation="对应译文", interpretation="研究判断", locator="第 8 页", evidence_attachment_id=self.detail(raw)["attachments"][0]["id"])
        report = self.record("research_report", title="完整流程报告", evidence_ids=[note], linked_ids=[raw], body_html="<h2>阶段报告</h2>")
        cid = self.call("/api/collections", {"name": "完整流程专题", "visibility": "shared", "research_question": "一个研究问题", "comparison_html": "<p>不同来源比较</p>", "stage_judgment": "待后续核对"}).json["id"]
        for rid in [directory, raw, note, report]:
            self.call(f"/api/collections/{cid}/items", {"record_id": rid})
        member = self.call("/api/members", {"username": "restore.member", "name": "恢复验收成员", "password": "RestoreMember2026!"}, user="admin").json["id"]
        self.call("/api/members/" + member, {"active": False}, user="admin", method="PUT")
        duplicate = self.record(title="待归并的原文旧记录", serial_id=journal)
        merged = self.call("/api/merge", {"type": "record", "keep_id": raw, "duplicate_id": duplicate, "keep_version": 2, "duplicate_version": 1, "confirmed": True}, user="admin")
        self.assertEqual(merged.status_code, 200, merged.json)
        archive = create_backup(self.data_dir)
        restored = restore_backup(archive, Path(self.temp.name) / "complete-restored")
        restored_app = create_app(restored, testing=True)
        with closing(connect(self.data_dir / "platform.sqlite3")) as first, closing(connect(restored / "platform.sqlite3")) as second:
            for table in ["records", "sources", "users", "attachments", "record_sources", "record_links", "evidence_links", "collections", "collection_items", "revisions", "merge_events", "member_events"]:
                self.assertEqual([tuple(r) for r in first.execute(f"SELECT * FROM {table} ORDER BY rowid")], [tuple(r) for r in second.execute(f"SELECT * FROM {table} ORDER BY rowid")], table)
            self.assertEqual(second.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(second.execute("PRAGMA foreign_key_check").fetchall(), [])
        reader = self.login("researcher", restored_app)
        self.assertIn("译目录表格", reader.get("/api/records/" + directory).json["body_html"])
        self.assertEqual(reader.get("/api/records/" + report).json["evidence_citations"][0]["snapshot"]["quote"], "摘录原文")
        self.assertEqual(reader.get("/api/records/" + duplicate).json["id"], raw)
        self.assertEqual(reader.get(f"/api/collections/{cid}").json["research_question"], "一个研究问题")
        with reader.get(f"/api/records/{note}/evidence-file") as downloaded:
            self.assertEqual(downloaded.data, "可恢复原文附件".encode())
        self.assertEqual(reader.get("/api/export/content?collection=" + cid).status_code, 200)

    def test_pinned_original_permissions_survive_note_retargeting(self):
        old = self.record(title="旧原文")
        new = self.record(title="新原文")
        note = self.record("research_note", evidence_record_id=old, quote="旧原文敏感摘录", locator="第 2 页")
        report = self.record("research_report", evidence_ids=[note], editors=["colleague"])
        revision = self.clients["researcher"].get("/api/history/record/" + report).json["items"][0]["id"]
        self.call("/api/records/" + old, {"version": 1, "visibility": "restricted"}, method="PUT")
        self.call("/api/records/" + note, {"version": 1, "evidence_record_id": new, "quote": "新原文公开摘录"}, method="PUT")
        self.assertEqual(self.detail(note, "colleague")["quote"], "新原文公开摘录")
        self.assertEqual(self.detail(report, "colleague")["evidence_citations"], [])
        historical = self.clients["colleague"].get(f"/api/history/{revision}")
        self.assertEqual(historical.status_code, 200)
        self.assertNotIn("旧原文敏感摘录", str(historical.json))
        self.assertEqual(historical.json["snapshot"]["evidence_citations"], [])

    def test_restore_after_source_merge_keeps_canonical_ids_and_old_name_search(self):
        keep = self.source("保留期刊")
        duplicate = self.source("期刊旧登记名")
        raw = self.record(serial_id=duplicate, related_source_ids=[duplicate])
        revision = self.clients["researcher"].get("/api/history/record/" + raw).json["items"][0]["id"]
        merged = self.call("/api/merge", {"type": "source", "keep_id": keep, "duplicate_id": duplicate, "keep_version": 1, "duplicate_version": 1, "confirmed": True}, user="admin")
        self.assertEqual(merged.status_code, 200, merged.json)
        restored = self.call(f"/api/history/{revision}/restore", {"version": 2})
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual(self.detail(raw)["serial_id"], keep)
        self.assertEqual(self.detail(raw)["related_source_ids"], [keep])
        self.assertEqual(self.clients["researcher"].get("/api/records?source=" + keep).json["total"], 1)
        history = self.clients["admin"].get("/api/history/source/" + keep).json["items"]
        first = next(r for r in reversed(history) if r["target_id"] == keep)
        restored = self.call(f"/api/history/{first['id']}/restore", {"version": 2}, user="admin")
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual(self.clients["researcher"].get("/api/sources?q=期刊旧登记名").json["total"], 1)
        self.assertIn(duplicate, self.clients["researcher"].get("/api/sources/" + keep).json["aliases"])


if __name__ == "__main__":
    unittest.main()
