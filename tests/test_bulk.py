"""Batch library behavior at the authenticated HTTP and CSV download boundaries."""
import csv
import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from platform_app.web import create_app


class BulkTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="database-bulk-test-")
        self.addCleanup(temp.cleanup)
        self.data_dir = Path(temp.name)
        self.app = create_app(self.data_dir, testing=True)
        self.clients = {}
        for name in ["researcher", "colleague", "admin"]:
            client = self.app.test_client()
            token = client.get("/api/session").json["csrf"]
            response = client.post("/api/login", json={"username": name, "password": "LocalDemo2026!"}, headers={"X-CSRF-Token": token})
            self.assertEqual(response.status_code, 200)
            self.clients[name] = client

    def call(self, path, data, user="researcher", method="POST"):
        client = self.clients[user]
        token = client.get("/api/session").json["csrf"]
        return client.open(path, method=method, json=data, headers={"X-CSRF-Token": token})

    def record(self, **extra):
        response = self.call("/api/records", {"kind": "report", "title": "合成资料", **extra})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["id"]

    def favorites(self, user="researcher"):
        return {r["id"] for r in self.clients[user].get("/api/records?favorite=1&size=100").json["items"]}

    def collection(self, visibility="shared"):
        response = self.call("/api/collections", {"name": "合成专题", "visibility": visibility})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["id"]

    def collection_detail(self, cid, user="researcher"):
        return self.clients[user].get("/api/collections/" + cid).json

    def test_favorite_selection_is_idempotent_personal_and_preserves_content(self):
        first, second = self.record(), self.record()
        before = self.clients["researcher"].get("/api/records/" + first).json
        self.call("/api/favorites/" + first, {"saved": True})
        response = self.call("/api/library/bulk/favorites", {"ids": [first, second, first]})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json, {"selected": 2, "added": 1, "existing": 1})
        self.assertEqual(self.favorites(), {first, second})
        self.assertEqual(self.favorites("colleague"), set())
        again = self.call("/api/library/bulk/favorites", {"ids": [first, second]})
        self.assertEqual(again.json, {"selected": 2, "added": 0, "existing": 2})
        after = self.clients["researcher"].get("/api/records/" + first).json
        for field in ["body_html", "authors", "author_id", "visibility", "editors", "version"]:
            self.assertEqual(after[field], before[field])

    def test_add_selection_to_collection_preserves_one_copy_and_versioned_history(self):
        first, second = self.record(), self.record()
        cid = self.collection()
        self.call(f"/api/collections/{cid}/items", {"record_id": first})
        response = self.call(f"/api/library/bulk/collections/{cid}", {"ids": [first, second], "version": 2}, user="colleague")
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json, {"selected": 2, "added": 1, "existing": 1, "version": 3})
        current = self.collection_detail(cid)
        self.assertEqual({r["id"] for r in current["items"]}, {first, second})
        self.assertEqual(current["version"], 3)
        history = self.clients["researcher"].get(f"/api/collections/{cid}/history").json["items"]
        self.assertEqual([r["version"] for r in history], [3, 2, 1])
        actor = self.clients["colleague"].get("/api/session").json["user"]["name"]
        self.assertEqual(history[0]["actor_name"], actor)
        again = self.call(f"/api/library/bulk/collections/{cid}", {"ids": [first, second], "version": 3})
        self.assertEqual(again.json, {"selected": 2, "added": 0, "existing": 2, "version": 3})
        self.assertEqual(self.clients["researcher"].get(f"/api/collections/{cid}/history").json["items"], history)

    def test_selected_csv_only_exports_explicit_visible_ids_and_escapes_text(self):
        first = self.record(title='=中文"题名"\n第二行', authors="+作者", original_title="@原题", keywords="-关键词", abstract="摘要")
        second = self.record(title="普通中文", publication_title="刊物\n第二行")
        omitted = self.record(title="未选资料")
        response = self.call("/api/library/bulk/export", {"ids": [second, first, second]})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        self.assertTrue(response.data.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.DictReader(io.StringIO(response.data.decode("utf-8-sig"))))
        self.assertEqual([r["稳定编号"] for r in rows], [second, first])
        self.assertEqual(rows[0]["刊物"], "刊物\n第二行")
        self.assertEqual(rows[1]["题名"], "'=中文\"题名\"\n第二行")
        self.assertEqual(rows[1]["作者/编译者"], "'+作者")
        self.assertEqual(rows[1]["原题名"], "'@原题")
        self.assertEqual(rows[1]["关键词"], "'-关键词")
        self.assertNotIn(omitted, response.data.decode("utf-8-sig"))
        old_export = self.clients["researcher"].get("/api/export?q=未选资料")
        old_rows = list(csv.DictReader(io.StringIO(old_export.data.decode("utf-8-sig"))))
        self.assertEqual([r["稳定编号"] for r in old_rows], [omitted])

    def test_all_endpoints_reject_invalid_or_hidden_ids_without_partial_results(self):
        first, hidden = self.record(), self.record(title="不可泄露的合成资料", visibility="restricted")
        cid = self.collection()
        urls = ["/api/library/bulk/favorites", f"/api/library/bulk/collections/{cid}", "/api/library/bulk/export"]
        for url in urls:
            for ids in [[first, hidden], [first, "missing-id"]]:
                response = self.call(url, {"ids": ids, "version": 1}, user="colleague")
                self.assertEqual(response.status_code, 404, (url, response.json))
                self.assertNotIn("不可泄露", response.get_data(as_text=True))
            for ids in [[], [first] * 101, "all", [first, None], [False]]:
                response = self.call(url, {"ids": ids, "version": 1})
                self.assertEqual(response.status_code, 400, (url, response.json))
        self.assertEqual(self.favorites("colleague"), set())
        self.assertEqual(self.collection_detail(cid)["items"], [])
        self.assertEqual(self.collection_detail(cid)["version"], 1)

    def test_collection_permission_and_version_conflicts_leave_items_and_history_unchanged(self):
        first, second = self.record(), self.record()
        private, shared = self.collection("private"), self.collection()
        forbidden = self.call(f"/api/library/bulk/collections/{private}", {"ids": [first], "version": 1}, user="colleague")
        self.assertEqual(forbidden.status_code, 404)
        self.assertEqual(self.collection_detail(private)["items"], [])
        self.call(f"/api/collections/{shared}/items", {"record_id": first})
        detail = self.collection_detail(shared)
        history = self.clients["researcher"].get(f"/api/collections/{shared}/history").json
        for version in [1, None, True, "2"]:
            failed = self.call(f"/api/library/bulk/collections/{shared}", {"ids": [second], "version": version})
            self.assertEqual(failed.status_code, 409, failed.json)
        self.assertEqual(self.collection_detail(shared), detail)
        self.assertEqual(self.clients["researcher"].get(f"/api/collections/{shared}/history").json, history)

    def test_permission_loss_and_expired_account_are_rechecked(self):
        first, second = self.record(), self.record()
        self.assertEqual(self.clients["colleague"].get("/api/records/" + second).status_code, 200)
        self.assertEqual(self.call("/api/records/" + second, {"version": 1, "visibility": "restricted"}, method="PUT").status_code, 200)
        failed = self.call("/api/library/bulk/favorites", {"ids": [first, second]}, user="colleague")
        self.assertEqual(failed.status_code, 404)
        self.assertEqual(self.favorites("colleague"), set())
        self.call("/api/logout", {}, user="colleague")
        failed = self.call("/api/library/bulk/favorites", {"ids": [first]}, user="colleague")
        self.assertEqual(failed.status_code, 401)
        self.assertEqual(self.app.test_client().post("/api/library/bulk/export", json={"ids": [first]}).status_code, 401)

    def test_storage_failure_rolls_back_earlier_additions_and_collection_history(self):
        first, second = self.record(), self.record()
        cid = self.collection()
        # Storage faults are injected at SQLite's public boundary; assertions use HTTP.
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as connection, connection:
            connection.execute(f"CREATE TRIGGER fail_batch_favorite BEFORE INSERT ON favorites WHEN NEW.record_id='{second}' BEGIN SELECT RAISE(ABORT,'synthetic storage failure'); END")
            connection.execute("CREATE TRIGGER fail_batch_history BEFORE INSERT ON revisions WHEN NEW.target_type='collection' BEGIN SELECT RAISE(ABORT,'synthetic storage failure'); END")
        failed = self.call("/api/library/bulk/favorites", {"ids": [first, second]})
        self.assertEqual(failed.status_code, 409, failed.json)
        self.assertEqual(self.favorites(), set())
        detail = self.collection_detail(cid)
        history = self.clients["researcher"].get(f"/api/collections/{cid}/history").json
        failed = self.call(f"/api/library/bulk/collections/{cid}", {"ids": [first, second], "version": 1})
        self.assertEqual(failed.status_code, 409, failed.json)
        self.assertEqual(self.collection_detail(cid), detail)
        self.assertEqual(self.clients["researcher"].get(f"/api/collections/{cid}/history").json, history)
        with closing(sqlite3.connect(self.data_dir / "platform.sqlite3")) as connection, connection:
            connection.execute("DROP TRIGGER fail_batch_favorite")
            connection.execute("DROP TRIGGER fail_batch_history")
        self.assertEqual(self.call(f"/api/library/bulk/collections/{cid}", {"ids": [first, second], "version": 1}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
