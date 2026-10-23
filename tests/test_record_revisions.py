"""Revision outcomes through HTTP, with synthetic storage faults in a temporary database."""
import io
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from platform_app.store import connect
from platform_app.web import create_app


class RecordRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="record-revision-test-")
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"
        self.app = create_app(self.data_dir, testing=True)
        self.clients = {}
        for user in ["researcher", "colleague", "admin"]:
            client = self.app.test_client()
            csrf = client.get("/api/session").json["csrf"]
            result = client.post("/api/login", json={"username": user, "password": "LocalDemo2026!"},
                                 headers={"X-CSRF-Token": csrf})
            self.assertEqual(result.status_code, 200)
            self.clients[user] = client

    def call(self, path, data=None, method="POST", user="researcher", upload=None):
        client = self.clients[user]
        kwargs = {"headers": {"X-CSRF-Token": client.get("/api/session").json["csrf"]}}
        if upload is not None:
            kwargs["data"] = {"data": json.dumps(data), "file": (io.BytesIO(upload), "合成附件.txt")}
        else:
            kwargs["json"] = data or {}
        return client.open(path, method=method, **kwargs)

    def create(self, **values):
        result = self.call("/api/records", {"kind": "report", "title": "合成资料", **values})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json["id"]

    def source(self, **values):
        result = self.call("/api/sources", {"name": "合成机构", "kind": "institution", **values})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json["id"]

    def get(self, path, user="researcher"):
        response = self.clients[user].get(path)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def files(self):
        return {p.name: p.read_bytes() for p in (self.data_dir / "uploads").iterdir()}

    def storage_fault(self, stage=None):
        # Arrange external storage failures; assertions use HTTP and the upload directory.
        with closing(connect(self.data_dir / "platform.sqlite3")) as db, db:
            db.execute("DROP TRIGGER IF EXISTS synthetic_failure")
            db.execute("DROP TABLE IF EXISTS deferred_failure")
            if stage == "commit":
                db.execute("CREATE TABLE deferred_failure(record_id TEXT REFERENCES records(id) DEFERRABLE INITIALLY DEFERRED)")
                db.execute("CREATE TRIGGER synthetic_failure AFTER INSERT ON revisions BEGIN INSERT INTO deferred_failure VALUES ('MISSING-SYNTHETIC-ID'); END")
            elif stage:
                table = {"attachment": "attachments", "history": "revisions", "merge": "merge_events"}[stage]
                db.execute(f"CREATE TRIGGER synthetic_failure BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END")

    def test_edit_failure_preserves_current_and_historical_files_and_all_relations(self):
        original = self.create(title="原始资料")
        note = self.create(kind="research_note", evidence_record_id=original, quote="固定摘录", locator="第 2 页")
        sid = self.source()
        created = self.call("/api/records", {"kind": "compilation", "title": "有历史附件的成果", "linked_ids": [original],
                            "evidence_ids": [note], "related_source_ids": [sid], "sharing_confirmed": True}, upload=b"first version")
        self.assertEqual(created.status_code, 201, created.json)
        rid = created.json["id"]
        url, history_url = "/api/records/" + rid, "/api/history/record/" + rid
        changed = self.call(url, {"version": 1, "sharing_confirmed": True}, method="PUT", upload=b"historical file")
        self.assertEqual(changed.status_code, 200, changed.json)
        history = self.get(history_url)["items"]
        old_file_revision = history[0]["id"]
        restored = self.call(f"/api/history/{history[-1]['id']}/restore", {"version": 2})
        self.assertEqual(restored.status_code, 200, restored.json)
        before, history_before, files_before = self.get(url), self.get(history_url), self.files()
        self.assertEqual(len(files_before), 2)
        self.assertEqual(len(before["attachments"]), 1)
        for stage in ["attachment", "history", "commit"]:
            with self.subTest(stage=stage):
                self.storage_fault(stage)
                failed = self.call(url, {"version": before["version"], "title": "不得落地", "linked_ids": [],
                                        "evidence_ids": [], "related_source_ids": [], "sharing_confirmed": True},
                                   method="PUT", upload=b"unfinished upload")
                self.assertEqual(failed.status_code, 409, failed.json)
                self.assertEqual(self.get(url), before)
                self.assertEqual(self.get(history_url), history_before)
                self.assertEqual(self.files(), files_before)
                aid = before["attachments"][0]["id"]
                with self.clients["researcher"].get("/api/attachments/" + aid) as download:
                    self.assertEqual(download.data, b"first version")
        self.storage_fault()
        restored = self.call(f"/api/history/{old_file_revision}/restore", {"version": before["version"]})
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual(len(self.get(url)["attachments"]), 2)
        self.assertEqual(self.files(), files_before)

    def test_create_late_failure_leaves_no_content_relations_history_or_upload(self):
        original = self.create()
        sid = self.source()
        before = self.get("/api/records/" + original)
        activity = self.get("/api/dashboard")["activities"]
        for stage in ["history", "commit"]:
            with self.subTest(stage=stage):
                self.storage_fault(stage)
                failed = self.call("/api/records", {"kind": "compilation", "title": "失败的提交", "linked_ids": [original],
                                  "related_source_ids": [sid], "sharing_confirmed": True}, upload=b"unfinished")
                self.assertEqual(failed.status_code, 409, failed.json)
                self.assertEqual(self.get("/api/records")["total"], 1)
                self.assertEqual(self.get("/api/records/" + original), before)
                self.assertEqual(self.get("/api/dashboard")["activities"], activity)
                self.assertEqual(self.get("/api/records?source=" + sid)["total"], 0)
                self.assertEqual(self.files(), {})

    def test_restore_history_failure_and_stale_edit_do_not_partially_write(self):
        original = self.create()
        sid = self.source()
        rid = self.create(kind="compilation", linked_ids=[original], related_source_ids=[sid], body_html="<p>旧正文</p>")
        url, history_url = "/api/records/" + rid, "/api/history/record/" + rid
        revision = self.get(history_url)["items"][0]["id"]
        edited = self.call(url, {"version": 1, "linked_ids": [], "related_source_ids": [], "body_html": "<p>新正文</p>"}, method="PUT")
        self.assertEqual(edited.status_code, 200, edited.json)
        before, history_before = self.get(url), self.get(history_url)
        self.storage_fault("history")
        failed = self.call(f"/api/history/{revision}/restore", {"version": before["version"]})
        self.assertEqual(failed.status_code, 409, failed.json)
        self.assertEqual(self.get(url), before)
        self.assertEqual(self.get(history_url), history_before)
        self.storage_fault()
        stale = self.call(url, {"version": 1, "sharing_confirmed": True}, method="PUT", upload=b"stale upload")
        self.assertEqual(stale.status_code, 409, stale.json)
        self.assertEqual(stale.json["error"], "这条内容已被更新，请重新打开后再保存。")
        self.assertEqual(self.get(url), before)
        self.assertEqual(self.get(history_url), history_before)
        self.assertEqual(self.files(), {})

    def test_author_confirmation_and_review_roll_back_without_history(self):
        rid = self.create(kind="compilation", author_id="colleague")
        url = "/api/records/" + rid
        before = self.get(url)
        self.storage_fault("history")
        failed = self.call(url + "/author", {"version": 1, "confirm": True}, user="colleague")
        self.assertEqual(failed.status_code, 409, failed.json)
        self.assertEqual(self.get(url), before)
        self.storage_fault()
        confirmed = self.call(url + "/author", {"version": 1, "confirm": True}, user="colleague")
        self.assertEqual(confirmed.status_code, 200, confirmed.json)
        before = self.get(url)
        history_url = "/api/history/record/" + rid
        history_before = self.get(history_url, user="colleague")
        self.assertEqual([h["version"] for h in history_before["items"]], [2, 1])
        self.storage_fault("commit")
        failed = self.call("/api/review/record/" + rid, {"version": 2}, user="admin")
        self.assertEqual(failed.status_code, 409, failed.json)
        self.assertEqual(self.get(url), before)
        self.assertEqual(self.get(history_url, user="colleague"), history_before)
        self.storage_fault()
        reviewed = self.call("/api/review/record/" + rid, {"version": 2}, user="admin")
        self.assertEqual(reviewed.status_code, 200, reviewed.json)
        self.assertEqual(self.get(url)["status"], "verified")
        self.assertFalse(self.get(url, user="admin")["can_edit"])
        stale = self.call("/api/review/record/" + rid, {"version": 2}, user="admin")
        self.assertEqual(stale.status_code, 409, stale.json)
        self.assertEqual(self.get(url)["version"], 3)

    def test_record_merge_late_failure_rolls_back_all_affected_records(self):
        keep, duplicate = self.create(title="保留资料"), self.create(title="重复资料")
        uploaded = self.call("/api/records/" + duplicate, {"version": 1, "sharing_confirmed": True}, method="PUT", upload=b"preserved")
        self.assertEqual(uploaded.status_code, 200, uploaded.json)
        note = self.create(kind="research_note", evidence_record_id=duplicate, quote="合并前的原文", locator="第 9 页")
        report = self.create(kind="compilation", linked_ids=[duplicate], evidence_ids=[note])
        collection = self.call("/api/collections", {"name": "合成专题", "visibility": "shared"})
        self.assertEqual(collection.status_code, 201, collection.json)
        cid = collection.json["id"]
        self.assertEqual(self.call(f"/api/collections/{cid}/items", {"record_id": duplicate}).status_code, 200)
        self.assertEqual(self.call("/api/favorites/" + duplicate, {"saved": True}).status_code, 200)
        urls = [p + rid for rid in [keep, duplicate, note, report] for p in ["/api/records/", "/api/history/record/"]]
        urls += [f"/api/collections/{cid}"]
        before, files = {url: self.get(url) for url in urls}, self.files()
        payload = {"type": "record", "keep_id": keep, "duplicate_id": duplicate, "keep_version": 1, "duplicate_version": 2, "confirmed": True}
        self.storage_fault("merge")
        failed = self.call("/api/merge", payload, user="admin")
        self.assertEqual(failed.status_code, 409, failed.json)
        self.assertEqual({url: self.get(url) for url in urls}, before)
        self.assertEqual(self.files(), files)
        self.assertEqual(self.clients["researcher"].get("/api/merged/record/" + duplicate).status_code, 404)
        self.storage_fault()
        succeeded = self.call("/api/merge", payload, user="admin")
        self.assertEqual(succeeded.status_code, 200, succeeded.json)
        for rid in [keep, note, report]:
            self.assertEqual(self.get("/api/records/" + rid)["version"], 2)
        self.assertEqual(self.get("/api/records/" + report)["evidence_citations"][0]["snapshot"]["evidence_record_id"], duplicate)
        stale = self.call("/api/records/" + report, {"version": 1, "linked_ids": [duplicate]}, method="PUT")
        self.assertEqual(stale.status_code, 409, stale.json)

    def test_source_merge_late_failure_rolls_back_graph_and_record_versions(self):
        keep, duplicate = self.source(name="保留来源"), self.source(name="重复来源")
        child = self.source(name="子机构", relationships=[{"type": "part_of", "target_id": duplicate, "evidence": "合成依据", "checked_on": ""}])
        raw = self.create(source_id=duplicate)
        directory = self.create(kind="directory_translation", authors="译者", coverage="2026", related_source_ids=[duplicate])
        urls = [p + sid for sid in [keep, duplicate, child] for p in ["/api/sources/", "/api/history/source/"]]
        urls += [p + rid for rid in [raw, directory] for p in ["/api/records/", "/api/history/record/"]]
        before = {url: self.get(url) for url in urls}
        payload = {"type": "source", "keep_id": keep, "duplicate_id": duplicate, "keep_version": 1, "duplicate_version": 1, "confirmed": True}
        self.storage_fault("merge")
        failed = self.call("/api/merge", payload, user="admin")
        self.assertEqual(failed.status_code, 409, failed.json)
        self.assertEqual({url: self.get(url) for url in urls}, before)
        self.storage_fault()
        succeeded = self.call("/api/merge", payload, user="admin")
        self.assertEqual(succeeded.status_code, 200, succeeded.json)
        for rid in [raw, directory]:
            self.assertEqual(self.get("/api/records/" + rid)["version"], 2)
            self.assertIn("合并转接编号", self.get("/api/history/record/" + rid)["items"][0]["action"])
        self.assertEqual(self.get("/api/records/" + raw)["source_id"], keep)
        self.assertEqual(self.get("/api/records/" + directory)["related_source_ids"], [keep])
        stale = self.call("/api/records/" + raw, {"version": 1, "source_id": duplicate}, method="PUT")
        self.assertEqual(stale.status_code, 409, stale.json)
