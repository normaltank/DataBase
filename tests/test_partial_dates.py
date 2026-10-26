"""Publication precision and range selection through the public HTTP interface."""
import csv
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from platform_app.web import create_app
from platform_app.store import connect


class PartialDateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="partial-dates-")
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Path(self.temp.name) / "data", testing=True)
        self.client = self.app.test_client()
        self.post("/api/login", {"username": "researcher", "password": "LocalDemo2026!"})

    def post(self, path, body):
        token = self.client.get("/api/session").json["csrf"]
        response = self.client.post(path, json=body, headers={"X-CSRF-Token": token})
        self.assertLess(response.status_code, 300, response.json)
        return response.json

    def record(self, published_on, **values):
        return self.post("/api/records", {"title": published_on or "Unknown date", "kind": "report",
                                          "published_on": published_on, **values})["id"]

    def results(self, **query):
        response = self.client.get("/api/records", query_string=query)
        self.assertEqual(response.status_code, 200, response.json)
        return {row["id"]: row["published_on"] for row in response.json["items"]}

    def test_partial_dates_overlap_the_selected_day_and_keep_original_precision(self):
        year = self.record("2026")
        month = self.record("2026-02")
        day = self.record("2026-02-01")
        self.record("2026-01-31")
        self.record("2026-02-02")
        self.record("")
        self.assertEqual(self.results(**{"from": "2026-02-01", "to": "2026-02-01"}),
                         {year: "2026", month: "2026-02", day: "2026-02-01"})

    def test_invalid_and_reversed_query_dates_return_clear_errors_even_without_records(self):
        for query in [{"from": value} for value in ["2026", "2026-02", "2026-02-30", "0000-01-01",
                                                   "20260101", "2026-1-01", " ", "2026-01-01x"]] + [
                          {"to": "2025-02-29"}, {"from": "2026-02-02", "to": "2026-02-01"}]:
            for endpoint in ["/api/records", "/api/record-candidates", "/api/export", "/api/export/content"]:
                with self.subTest(query=query, endpoint=endpoint):
                    response = self.client.get(endpoint, query_string={"purpose": "original", **query})
                    self.assertEqual(response.status_code, 400, response.data[:200])
                    self.assertIn("发布日期", response.json["error"])

    def test_saved_queries_reject_the_same_malformed_date_bounds(self):
        for index, value in enumerate([" ", " 2026-01-01 ", "2026", "2026-02-30"]):
            with self.subTest(value=value):
                token = self.client.get("/api/session").json["csrf"]
                response = self.client.post("/api/saved-searches", json={"name": f"Invalid date {index}",
                    "conditions": {"from": value}}, headers={"X-CSRF-Token": token})
                self.assertEqual(response.status_code, 400, response.json)
                self.assertIn("发布日期", response.json["error"])

    def test_leap_month_year_edges_and_single_bounds_are_inclusive(self):
        dates = ["2023-12-31", "2024", "2024-02", "2024-02-28", "2024-02-29", "2024-03-01",
                 "2024-12-31", "2025", "2025-01", "2025-01-01", "9999", "9999-12"]
        records = {value: self.record(value) for value in dates}
        cases = [({"from": "2024-02-29", "to": "2024-02-29"}, ["2024", "2024-02", "2024-02-29"]),
                 ({"to": "2024-02-01"}, ["2023-12-31", "2024", "2024-02"]),
                 ({"from": "2024-12-31"}, ["2024", "2024-12-31", "2025", "2025-01", "2025-01-01", "9999", "9999-12"]),
                 ({"from": "2024-12-31", "to": "2025-01-01"}, ["2024", "2024-12-31", "2025", "2025-01", "2025-01-01"]),
                 ({"from": "9999-12-31"}, ["9999", "9999-12"])]
        for query, expected in cases:
            with self.subTest(query=query):
                self.assertEqual(self.results(**query), {records[value]: value for value in expected})

    def test_unknown_and_legacy_invalid_dates_only_appear_without_date_conditions(self):
        values = ["", "2024-02-30", "2025-02-29", "2026-13", "0000", "not a date", " "]
        ids = [self.record("", title=f"Legacy date {index}") for index in range(len(values))]
        # Legacy imports may predate write validation; seed such input, observe only HTTP results.
        with closing(connect(Path(self.temp.name) / "data" / "platform.sqlite3")) as db, db:
            db.executemany("UPDATE records SET published_on=? WHERE id=?", zip(values, ids))
        self.assertEqual(self.results(), dict(zip(ids, values)))
        for query in [{"from": "0001-01-01"}, {"to": "9999-12-31"},
                      {"from": "2024-01-01", "to": "2026-12-31"}]:
            self.assertEqual(self.results(**query), {})

    def test_candidates_saved_query_csv_and_content_export_share_scope_and_precision(self):
        year = self.record("2026", title="Year")
        month = self.record("2026-02", title="Month")
        day = self.record("2026-02-01", title="Day")
        self.record("2026-01-31", title="Outside")
        self.record("", title="Unknown")
        self.record("2026", title="Private", visibility="restricted")
        self.post("/api/logout", {})
        self.post("/api/login", {"username": "colleague", "password": "LocalDemo2026!"})
        query = {"from": "2026-02-01", "to": "2026-02-01", "sort": "title"}
        expected = {day: "2026-02-01", month: "2026-02", year: "2026"}
        self.assertEqual(self.results(**query), expected)
        ordered = self.client.get("/api/records", query_string=query).json["items"]
        self.assertEqual([row["id"] for row in ordered], [day, month, year])
        candidates = self.client.get("/api/record-candidates", query_string={"purpose": "original", **query}).json
        self.assertEqual([row["id"] for row in candidates["items"]], [day, month, year])
        saved = self.post("/api/saved-searches", {"name": "Partial publication dates", "conditions": query})
        self.assertEqual(saved["conditions"], query)
        self.assertEqual(self.results(saved_search=saved["id"], **{"from": "2030-01-01"}), expected)
        for scope in [query, {"saved_search": saved["id"]}]:
            with self.subTest(scope=scope):
                csv_response = self.client.get("/api/export", query_string=scope)
                self.assertEqual(csv_response.status_code, 200)
                rows = list(csv.DictReader(io.StringIO(csv_response.data.decode("utf-8-sig"))))
                self.assertEqual({row["稳定编号"]: row["日期"] for row in rows}, expected)
                with self.client.get("/api/export/content", query_string=scope) as response:
                    self.assertEqual(response.status_code, 200)
                    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                        content = json.loads(archive.read("content.json"))
                self.assertEqual(content["selected_ids"], [day, month, year])
                self.assertEqual({row["id"]: row["published_on"] for row in content["records"]}, expected)
