"""A delayed read response must not restore a cookie after logout."""
from http.cookies import SimpleCookie
from pathlib import Path
import tempfile
import unittest

from platform_app.web import create_app


class SessionReadResponseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="session-read-race-")
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Path(self.temp.name) / "data", testing=True)
        self.client = self.app.test_client()
        token = self.client.get("/api/session").json["csrf"]
        response = self.client.post("/api/login", json={"username": "researcher", "password": "LocalDemo2026!"}, headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 200)
        self.csrf = response.json["csrf"]
        self.assertIn("Set-Cookie", response.headers)

    def test_authenticated_reads_do_not_resend_login_cookie(self):
        for path in ("/api/session", "/api/collaboration/works", "/api/records", "/health", "/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("Set-Cookie", response.headers)

    def test_late_read_headers_cannot_restore_logged_out_account(self):
        delayed = self.client.get("/api/collaboration/works")
        self.assertEqual(delayed.status_code, 200)
        logout = self.client.post("/api/logout", json={}, headers={"X-CSRF-Token": self.csrf})
        self.assertEqual(logout.status_code, 200)
        self.assertIsNone(self.client.get("/api/session").json["user"])
        # Apply delayed headers in the order a browser would receive them.
        for header in delayed.headers.getlist("Set-Cookie"):
            cookies = SimpleCookie()
            cookies.load(header)
            for name, value in cookies.items():
                self.client.set_cookie(name, value.value)
        anonymous = self.client.get("/api/session").json
        self.assertIsNone(anonymous["user"])
        switched = self.client.post("/api/login", json={"username": "admin", "password": "LocalDemo2026!"}, headers={"X-CSRF-Token": anonymous["csrf"]})
        self.assertEqual(switched.status_code, 200)
        self.assertEqual(switched.json["user"]["id"], "admin")


if __name__ == "__main__":
    unittest.main()
