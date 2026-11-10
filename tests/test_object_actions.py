"""Issue 144: portable return and versioned assets through the HTTP boundary."""
from pathlib import Path
from contextlib import closing
import re
import tempfile
import unittest
from unittest.mock import patch

from platform_app.web import create_app
from platform_app.store import connect


class ObjectEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='object-actions-synthetic-')
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / 'data'
        self.app = create_app(self.data, testing=True, embedded_worker=False, portable_trial=True)
        self.client = self.app.test_client()

    def post(self, path, remote='127.0.0.1', token=None):
        token = token or self.client.get('/api/session').json['csrf']
        return self.client.post(path, json={}, headers={'X-CSRF-Token': token}, environ_overrides={'REMOTE_ADDR': remote})

    def test_host_return_keeps_authenticated_identity_rotates_csrf_and_survives_repeat_entry(self):
        before = self.client.get('/api/session').json
        host = self.post('/api/trial/host').json
        self.assertNotEqual(host['csrf'], before['csrf'])
        self.post('/api/trial/host')
        self.assertTrue(self.client.get('/api/session').json['research_return_available'])
        result = self.post('/api/trial/return')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['user']['id'], before['user']['id'])
        self.assertNotEqual(result.json['csrf'], host['csrf'])
        self.assertEqual(self.post('/api/trial/host', token=host['csrf']).status_code, 403)

    def test_return_rejects_remote_revoked_credentials_missing_marker_and_logout(self):
        uid = self.client.get('/api/session').json['user']['id']
        self.post('/api/trial/host')
        self.assertEqual(self.post('/api/trial/return', remote='192.0.2.4').status_code, 403)
        with closing(connect(self.data / 'platform.sqlite3')) as db, db:
            db.execute('UPDATE users SET credential_version=credential_version+1 WHERE id=?', (uid,))
        self.assertEqual(self.post('/api/trial/return').status_code, 403)
        self.assertEqual(self.post('/api/logout').status_code, 200)
        self.assertEqual(self.post('/api/trial/host').status_code, 200)
        self.assertFalse(self.client.get('/api/session').json['research_return_available'])
        self.assertEqual(self.post('/api/trial/return').status_code, 403)

    def test_html_and_lazy_assets_share_revision_and_reject_mixed_versions(self):
        self.client.get('/api/session')
        result = self.client.get('/api/client-revision')
        self.assertEqual(result.status_code, 200)
        revision = result.json['revision']
        self.assertRegex(revision, r'^[a-f0-9]{16}$')
        html = self.client.get('/').text
        urls = re.findall(r'(?:src|href)="(/static/[^\"]+)"', html)
        self.assertTrue(urls)
        self.assertTrue(all('v=' + revision in url for url in urls))
        asset = self.client.get('/static/app.js?v=' + revision)
        self.assertEqual(asset.status_code, 200)
        etag = asset.headers['ETag']
        asset.close()
        unchanged = self.client.get('/static/app.js?v=' + revision, headers={'If-None-Match': etag})
        self.assertEqual(unchanged.status_code, 304)
        unchanged.close()
        self.assertEqual(self.client.get('/static/app.js?v=old').status_code, 409)

    def test_inactive_or_unmarked_member_cannot_return_and_normal_login_can_recover(self):
        first = self.client.get('/api/session').json['user']
        self.post('/api/trial/host')
        with closing(connect(self.data / 'platform.sqlite3')) as db, db:
            db.execute('UPDATE users SET active=0 WHERE id=?', (first['id'],))
        self.assertEqual(self.post('/api/trial/return').status_code, 403)
        with closing(connect(self.data / 'platform.sqlite3')) as db, db:
            db.execute('UPDATE users SET active=1 WHERE id=?', (first['id'],))
            db.execute('DELETE FROM settings WHERE key=?', ('portable_trial_member:' + first['id'],))
        self.assertEqual(self.post('/api/trial/return').status_code, 403)
        with closing(connect(self.data / 'platform.sqlite3')) as db, db:
            db.execute('INSERT INTO settings VALUES (?,?)', ('portable_trial_member:' + first['id'], '1'))
        token = self.client.get('/api/session').json['csrf']
        saved = self.client.put('/api/members/' + first['id'], json={'password': 'SyntheticRestore2026!'}, headers={'X-CSRF-Token': token})
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertFalse(self.client.get('/api/session').json['research_return_available'])
        logged_in = self.client.post('/api/login', json={'username': first['username'], 'password': 'SyntheticRestore2026!'}, headers={'X-CSRF-Token': token})
        self.assertEqual(logged_in.status_code, 200, logged_in.json)
        self.assertEqual(logged_in.json['user']['id'], first['id'])

    def test_replaced_static_file_rejects_old_revision_without_restarting_server(self):
        root = Path(self.tmp.name) / 'isolated-assets'
        (root / 'static').mkdir(parents=True)
        (root / 'templates').mkdir()
        asset = root / 'static' / 'sample.js'
        asset.write_text('version one', encoding='utf-8')
        (root / 'templates' / 'index.html').write_text('<script src="{{ asset("sample.js") }}"></script>', encoding='utf-8')
        with patch('platform_app.web.ROOT', root):
            app = create_app(self.data, testing=True, embedded_worker=False)
        client = app.test_client()
        first = client.get('/').headers['X-Client-Revision']
        asset.write_text('version two is different', encoding='utf-8')
        replaced = client.get('/static/sample.js?v=' + first)
        self.assertEqual(replaced.status_code, 409)
        current = replaced.headers['X-Client-Revision']
        self.assertNotEqual(current, first)
        result = client.get('/static/sample.js?v=' + current)
        self.assertEqual(result.text, 'version two is different')
        result.close()


if __name__ == '__main__':
    unittest.main()
