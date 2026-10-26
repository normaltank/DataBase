"""Assisted intake through authenticated HTTP and external socket boundaries."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from platform_app.web import create_app
from platform_app.maintenance import restore_backup


class PublicSocket:
    """Synthetic public server; production DNS, peer and response checks still run."""
    def __init__(self, body, content_type="text/html", status="200 OK", headers=""):
        self.body = (f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\n"
                     f"Content-Length: {len(body)}\r\n{headers}\r\n").encode() + body
    def makefile(self, *args, **kwargs):
        return io.BytesIO(self.body)
    def getpeername(self):
        return ("93.184.216.34", 80)
    def sendall(self, data):
        pass
    def settimeout(self, timeout):
        pass
    def close(self):
        pass


class AssistedIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="assisted-intake-")
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Path(self.temp.name) / "data", testing=True)
        self.clients = {}
        for name in ["researcher", "colleague", "admin"]:
            client = self.app.test_client()
            token = client.get("/api/session").json["csrf"]
            result = client.post("/api/login", json={"username": name, "password": "LocalDemo2026!"},
                                 headers={"X-CSRF-Token": token})
            self.assertEqual(result.status_code, 200)
            self.clients[name] = client

    def call(self, path, data=None, user="researcher", method="POST"):
        client = self.clients[user]
        return client.open(path, method=method, json=data or {},
                           headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]})

    def preview(self, html, value="http://example.org/article", **kwargs):
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 80))]), \
             patch("socket.create_connection", side_effect=lambda *a, **k: PublicSocket(html.encode(), **kwargs)), \
             patch("ssl.SSLContext.wrap_socket", side_effect=lambda sock, **kwargs: sock):
            return self.call("/api/intake/preview", {"input": value})

    def test_preview_is_read_only_and_save_preserves_order_and_evidence(self):
        html = '<title>Low title</title><meta name="citation_title" content="Synthetic article">' \
               '<meta name="citation_author" content="Ada Example"><meta name="citation_author" content="Bob Example">' \
               '<meta name="citation_date" content="2024"><meta name="citation_doi" content="10.5555/EXAMPLE">' \
               '<meta name="citation_journal_title" content="Synthetic Journal">'
        before = self.clients["researcher"].get("/api/records").json["total"]
        response = self.preview(html)
        self.assertEqual(response.status_code, 200, response.json)
        preview = response.json
        self.assertEqual(preview["fields"]["title"], "Synthetic article")
        self.assertEqual(preview["fields"]["published_on"], "2024")
        self.assertEqual(preview["fields"]["doi"], "10.5555/example")
        self.assertEqual([a["raw_name"] for a in preview["authors"]], ["Ada Example", "Bob Example"])
        self.assertEqual(self.clients["researcher"].get("/api/records").json["total"], before)
        saved = self.call("/api/records", {"kind": "journal_article", **preview["fields"],
                          "intake_token": preview["token"]})
        self.assertEqual(saved.status_code, 201, saved.json)
        rid = saved.json["id"]
        detail = self.clients["researcher"].get("/api/records/" + rid).json
        self.assertEqual(detail["intake_evidence"][0]["sources"][0]["url"], "http://example.org/article")
        self.assertEqual(detail["intake_evidence"][0]["sources"][0]["raw"]["meta"]["citation_title"], ["Synthetic article"])
        bylines = self.clients["researcher"].get(f"/api/records/{rid}/bylines").json["items"]
        self.assertEqual([b["status"] for b in bylines], ["pending", "pending"])
        history = self.clients["researcher"].get(f"/api/history/record/{rid}").json["items"]
        snapshot = self.clients["researcher"].get("/api/history/" + str(history[0]["id"])).json["snapshot"]
        self.assertIn("intake_evidence", json.loads(snapshot["raw_json"]))

    def test_doi_preview_candidates_need_confirmation_and_failed_save_rolls_back(self):
        person = self.call("/api/people", {"name": "Ada Example", "change_note": "Synthetic identity"}).json["id"]
        journal = self.call("/api/sources", {"name": "Synthetic Journal", "kind": "journal", "issn": "1234-5678"}).json["id"]
        payload = {"message": {"title": ["DOI article"], "DOI": "10.5555/EXAMPLE", "container-title": ["Synthetic Journal"],
                   "ISSN": ["1234-5678"], "publisher": "Publisher only", "published": {"date-parts": [[2024, 5]]},
                   "author": [{"given": "Ada", "family": "Example", "ORCID": "https://orcid.org/0000-0002-1825-0097",
                               "affiliation": [{"name": "Article affiliation only"}]}]}}
        response = self.preview(json.dumps(payload), "https://doi.org/10.5555/EXAMPLE", content_type="application/json")
        self.assertEqual(response.status_code, 200, response.json)
        preview = response.json
        self.assertEqual(preview["fields"]["published_on"], "2024-05")
        self.assertEqual(preview["authors"][0]["identifiers"]["ORCID"], "https://orcid.org/0000-0002-1825-0097")
        self.assertEqual(preview["candidates"]["authors"][0]["items"][0]["id"], person)
        self.assertEqual(preview["candidates"]["sources"][0]["id"], journal)
        self.assertNotIn("source_id", preview["fields"])
        self.assertNotIn("countries", preview["fields"])
        values = {"kind": "journal_article", **preview["fields"], "intake_token": preview["token"], "serial_id": journal,
                  "intake_bylines": [{"raw_name": "Ada Example", "status": "confirmed", "target_type": "person", "target_id": person}]}
        before = self.clients["researcher"].get("/api/records").json["total"]
        self.assertEqual(self.call("/api/records", values).status_code, 400)
        self.assertEqual(self.clients["researcher"].get("/api/records").json["total"], before)
        values["intake_bylines"][0]["evidence"] = "https://doi.org/10.5555/example 人工核对"
        saved = self.call("/api/records", values)
        self.assertEqual(saved.status_code, 201, saved.json)
        works = self.clients["researcher"].get(f"/api/people/{person}/works").json
        self.assertEqual(works["total"], 1)
        self.assertEqual(self.call("/api/records", values).status_code, 409)
        again = self.preview(json.dumps(payload), "DOI:10.5555/example", content_type="application/json").json
        self.assertEqual(again["duplicates"][0]["id"], saved.json["id"])
        renamed = {"message": {**payload["message"], "DOI": "10.5555/renamed", "author": [
            {"given": "Different", "family": "Writing", "ORCID": "http://orcid.org/0000-0002-1825-0097"}]}}
        result = self.preview(json.dumps(renamed), "10.5555/renamed", content_type="application/json")
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json["candidates"]["authors"][0]["items"][0]["id"], person)
        self.assertIn("ORCID", result.json["candidates"]["authors"][0]["items"][0]["basis"])

    def test_private_duplicates_and_foreign_evidence_never_reveal_metadata(self):
        preview = self.preview('<meta name="citation_title" content="Private synthetic"><meta name="citation_doi" content="10.5555/private">').json
        saved = self.call("/api/records", {"title": "Private synthetic", "doi": "https://doi.org/10.5555/PRIVATE",
                          "kind": "report", "visibility": "restricted", "intake_token": preview["token"]})
        self.assertEqual(saved.status_code, 201, saved.json)
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 80))]), \
             patch("socket.create_connection", return_value=PublicSocket(b'<meta name="citation_doi" content="10.5555/private">')):
            other = self.call("/api/intake/preview", {"input": "http://example.org/article"}, "colleague")
        self.assertEqual(other.status_code, 200)
        self.assertEqual(other.json["duplicates"], [])
        self.assertNotIn("Private synthetic", json.dumps(other.json))
        foreign = self.call("/api/records", {"title": "Foreign token", "intake_token": preview["token"]}, "colleague")
        self.assertEqual(foreign.status_code, 403, foreign.json)
        before = self.clients["colleague"].get("/api/records").json["total"]
        invalid = self.call("/api/records", {"title": "Changed token", "intake_token": preview["token"] + "invalid"}, "colleague")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.clients["colleague"].get("/api/records").json["total"], before)

    def test_network_rejects_private_dns_actual_peer_redirect_files_and_oversize(self):
        for address in ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "::ffff:127.0.0.1", "100.64.0.1"]:
            with self.subTest(address=address), patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", (address, 80))]), \
                 patch("socket.create_connection") as connection:
                result = self.call("/api/intake/preview", {"input": "http://example.org/article"})
                self.assertEqual(result.status_code, 422)
                connection.assert_not_called()
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 80))]), \
             patch("socket.create_connection", return_value=PublicSocket(b"private")), \
             patch.object(PublicSocket, "getpeername", return_value=("127.0.0.1", 80)):
            self.assertEqual(self.call("/api/intake/preview", {"input": "http://example.org"}).status_code, 422)
        addresses = [[(2, 1, 6, "", ("93.184.216.34", 80))], [(2, 1, 6, "", ("10.0.0.1", 80))]]
        with patch("socket.getaddrinfo", side_effect=addresses), \
             patch("socket.create_connection", return_value=PublicSocket(b"", status="302 Found", headers="Location: http://internal.example/secret\r\n")) as connection:
            self.assertEqual(self.call("/api/intake/preview", {"input": "http://example.org"}).status_code, 422)
            self.assertEqual(connection.call_count, 1)
        for mime, content in [("application/pdf", "%PDF"), ("text/html", "a" * (1024 * 1024 + 1))]:
            result = self.preview(content, content_type=mime)
            self.assertEqual(result.status_code, 422)
        self.assertEqual(self.call("/api/intake/preview", {"input": "file:///C:/secret"}).status_code, 422)

    def test_url_duplicates_and_readable_export_keep_evidence(self):
        preview = self.preview('<meta name="citation_title" content="URL only article">').json
        values = {"title": "URL only article", "url": "http://EXAMPLE.org:80/article#section", "intake_token": preview["token"]}
        saved = self.call("/api/records", values)
        self.assertEqual(saved.status_code, 201, saved.json)
        self.assertEqual(self.call("/api/records", values).status_code, 409)
        response = self.clients["researcher"].get("/api/export/content")
        self.assertEqual(response.status_code, 200, response.json)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            payload = json.loads(archive.read("content.json"))
            record = next(r for r in payload["records"] if r["id"] == saved.json["id"])
            self.assertEqual(record["intake_evidence"][0]["input"], "http://example.org/article")
            pages = [archive.read(name).decode() for name in archive.namelist() if name.startswith("records/") and name.endswith(".html")]
            self.assertTrue(any("辅助录入取得依据" in page and "citation_title" in page for page in pages))

    def test_ambiguous_jsonld_does_not_mix_articles_and_registry_mismatch_falls_back(self):
        html = '<title>Landing title</title><meta name="description" content="."><script type="application/ld+json">' + json.dumps([
            {"@type": "Article", "headline": "First article", "author": {"name": "First person"}},
            {"@type": "Article", "datePublished": "2020-01", "author": {"name": "Other person"}}
        ]) + '</script>'
        result = self.preview(html)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json["fields"]["title"], "Landing title")
        self.assertNotIn("published_on", result.json["fields"])
        self.assertNotIn("abstract", result.json["fields"])
        self.assertEqual(result.json["authors"], [])
        self.assertTrue(result.json["warnings"])
        bad = json.dumps({"message": {"DOI": "10.5555/other", "title": ["Wrong work"]}})
        self.assertEqual(self.preview(bad, "10.5555/requested", content_type="application/json").status_code, 422)

    def test_backup_and_record_restore_keep_evidence_and_current_identity_correction(self):
        person = self.call("/api/people", {"name": "Ada Example", "change_note": "Synthetic identity"}).json["id"]
        preview = self.preview('<meta name="citation_title" content="Restore article"><meta name="citation_author" content="Ada Example">').json
        saved = self.call("/api/records", {**preview["fields"], "intake_token": preview["token"]})
        rid = saved.json["id"]
        initial = self.clients["researcher"].get(f"/api/history/record/{rid}").json["items"][0]["id"]
        changed = self.call(f"/api/records/{rid}", {"title": "Manually revised", "version": 1}, method="PUT")
        self.assertEqual(changed.status_code, 200, changed.json)
        corrected = self.call(f"/api/records/{rid}/bylines", {"version": 1, "record_version": 2, "change_note": "Manual confirmation",
                              "items": [{"raw_name": "Ada Example", "status": "confirmed", "target_type": "person", "target_id": person, "evidence": "Synthetic article byline"}]}, method="PUT")
        self.assertEqual(corrected.status_code, 200, corrected.json)
        restored = self.call(f"/api/history/{initial}/restore", {"version": 2})
        self.assertEqual(restored.status_code, 200, restored.json)
        detail = self.clients["researcher"].get(f"/api/records/{rid}").json
        self.assertEqual(detail["title"], "Restore article")
        self.assertEqual(detail["intake_evidence"][0]["input"], "http://example.org/article")
        self.assertEqual(self.clients["researcher"].get(f"/api/people/{person}/works").json["total"], 1)
        archive = Path(self.temp.name) / "backup.zip"
        with self.call("/api/backup", user="admin") as backup:
            archive.write_bytes(backup.data)
        directory = restore_backup(archive, Path(self.temp.name) / "recovered")
        app = create_app(directory, testing=True)
        client = app.test_client()
        token = client.get("/api/session").json["csrf"]
        login = client.post("/api/login", json={"username": "researcher", "password": "LocalDemo2026!"}, headers={"X-CSRF-Token": token})
        self.assertEqual(login.status_code, 200)
        recovered = client.get(f"/api/records/{rid}").json
        self.assertEqual(recovered["intake_evidence"], detail["intake_evidence"])
        self.assertEqual(client.get(f"/api/people/{person}/works").json["total"], 1)

    def test_datacite_fallback_and_jsonld_main_article_keep_source_precision(self):
        data = {"data": {"attributes": {"doi": "10.5555/datacite", "titles": [{"title": "DataCite work"}],
                "publicationYear": 2021, "url": "https://example.org/data", "creators": [{"name": "One Person",
                "nameIdentifiers": [{"nameIdentifierScheme": "ORCID", "nameIdentifier": "0000-0002-1825-0097"}]}]}}}
        responses = [PublicSocket(b'{}', "application/json", status="404 Not Found"),
                     PublicSocket(json.dumps(data).encode(), "application/json")]
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]), \
             patch("socket.create_connection", side_effect=responses), \
             patch("ssl.SSLContext.wrap_socket", side_effect=lambda sock, **kwargs: sock):
            response = self.call("/api/intake/preview", {"input": "doi:10.5555/DATACITE"})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["fields"]["published_on"], "2021")
        self.assertEqual(response.json["sources"][0]["provider"], "DataCite")
        html = '<script type="application/ld+json">' + json.dumps({"@graph": [
            {"@type": "Article", "url": "http://example.org/article", "headline": "Main work", "datePublished": "2024-03", "author": {"name": "Main author"}},
            {"@type": "Article", "url": "http://example.org/other", "headline": "Related work", "datePublished": "2019", "author": {"name": "Related author"}}
        ]}) + '</script><meta property="article:modified_time" content="2026-10-26">'
        result = self.preview(html)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["fields"]["title"], "Main work")
        self.assertEqual(result.json["fields"]["authors"], "Main author")
        self.assertEqual(result.json["fields"]["published_on"], "2024-03")



if __name__ == "__main__":
    unittest.main()
