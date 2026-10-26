"""Source profile grouping through the public HTTP boundary."""
import tempfile
import unittest
from platform_app.web import create_app


class SourceProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="source-profile-")
        self.addCleanup(self.temp.cleanup)
        self.client = create_app(self.temp.name, testing=True).test_client()
        self.call("/api/login", {"username": "researcher", "password": "LocalDemo2026!"})
        self.source = self.call("/api/sources", {"name": "Synthetic institution", "kind": "institution"})["id"]
        self.journal = self.call("/api/sources", {"name": "Synthetic journal", "kind": "journal"})["id"]

    def call(self, path, payload, method="POST"):
        token = self.client.get("/api/session").json["csrf"]
        response = self.client.open(path, method=method, json=payload, headers={"X-CSRF-Token": token})
        self.assertLess(response.status_code, 300, response.json)
        return response.json

    def record(self, title, **fields):
        return self.call("/api/records", {"title": title, "kind": "report", **fields})["id"]

    def group(self, source, section, **query):
        response = self.client.get("/api/records", query_string={"source": source, "source_section": section, **query})
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def test_groups_distinguish_publication_association_and_centre_content(self):
        published = self.record("Institution publication", source_id=self.source)
        article = self.record("Journal article", serial_id=self.journal)
        related = self.record("Association only", related_source_ids=[self.source, self.journal])
        translation = self.record("Translated catalogue", kind="directory_translation", related_source_ids=[self.source, self.journal], coverage="2024–2026", authors="Translator")
        note = self.record("Authored analysis", kind="research_note", author_id="researcher", source_id=self.source, related_source_ids=[self.source], research_subjects=[{"subject_type":"institution","subject_id":self.source}])
        report = self.record("Centre report", kind="research_report", author_id="researcher", related_source_ids=[self.journal])
        for source, expected in [(self.source, published), (self.journal, article)]:
            self.assertEqual([r["id"] for r in self.group(source, "published")["items"]], [expected])
            self.assertEqual([r["id"] for r in self.group(source, "associated")["items"]], [related])
            self.assertEqual([r["id"] for r in self.group(source, "translations")["items"]], [translation])
        self.assertEqual({r["id"] for r in self.group(self.source, "outputs")["items"]}, {note})
        self.assertEqual({r["id"] for r in self.group(self.journal, "outputs")["items"]}, {report})

    def test_group_pagination_privacy_filters_and_old_source_id(self):
        ids = {self.record("Public item-%03d" % i, source_id=self.source) for i in range(105)}
        self.record("Private", source_id=self.source, visibility="restricted")
        duplicate = self.call("/api/sources", {"name":"Old source", "kind":"institution"})["id"]
        self.call("/api/logout", {})
        self.call("/api/login", {"username":"admin", "password":"LocalDemo2026!"})
        self.call("/api/merge", {"type":"source", "keep_id":self.source, "duplicate_id":duplicate, "keep_version":1, "duplicate_version":1, "confirmed":True})
        self.call("/api/logout", {})
        self.call("/api/login", {"username":"colleague", "password":"LocalDemo2026!"})
        first = self.group(duplicate, "published", size=100, page=1)
        second = self.group(duplicate, "published", size=100, page=2)
        self.assertEqual((first["total"], len(first["items"]), len(second["items"])), (105, 100, 5))
        self.assertEqual({r["id"] for r in first["items"] + second["items"]}, ids)
        self.assertEqual(self.group(duplicate, "published", q="item-104")["total"], 1)
        self.assertEqual(self.group(duplicate, "published", kind="journal_article")["total"], 0)
        self.assertEqual(self.client.get("/api/records?source_section=published").status_code, 400)
        self.assertEqual(self.client.get("/api/records", query_string={"source":self.source,"source_section":"unknown"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
