"""Portable opt-in is exercised through independent HTTP sessions, never real data."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import closing

from platform_app.web import create_app
from platform_app.maintenance import create_backup, restore_backup
from platform_app.store import connect


class PortableTrialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='portable-trial-synthetic-')
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / 'data'

    def app(self):
        return create_app(self.data, testing=True, embedded_worker=False, portable_trial=True)

    def call(self, client, path, payload=None, method='POST', file=None, remote='192.0.2.10'):
        csrf = client.get('/api/session').json['csrf']
        kwargs = dict(headers={'X-CSRF-Token': csrf}, environ_overrides={'REMOTE_ADDR': remote})
        if file:
            kwargs['data'] = {'data': json.dumps(payload), 'file': (io.BytesIO(file), '练习.txt')}
        else:
            kwargs['json'] = payload or {}
        result = client.open(path, method=method, **kwargs)
        result.request.close()
        return result

    def test_two_visitors_reuse_identity_create_and_upload_with_original_authorship(self):
        app = self.app()
        a, b = app.test_client(), app.test_client()
        first, second = a.get('/api/session').json, b.get('/api/session').json
        self.assertNotEqual(first['user']['id'], second['user']['id'])
        self.assertEqual(first['user']['role'], 'researcher')
        self.assertTrue(first['user']['temporary'])
        refreshed = a.get('/api/session')
        self.assertEqual(refreshed.json['user']['id'], first['user']['id'])
        self.assertNotIn('Set-Cookie', refreshed.headers)
        renamed = self.call(a, '/api/trial/nickname', {'name': '小林'}, 'PUT')
        self.assertEqual(renamed.status_code, 200, renamed.json)
        self.assertEqual(a.get('/api/session').json['user']['name'], '小林')
        single = self.call(a, '/api/collaboration/topics', {'theme': '单人实践', 'participant_ids': []})
        self.assertEqual(single.status_code, 201, single.json)
        topic = self.call(a, '/api/collaboration/topics', {'theme': '多人实践', 'participant_ids': [second['user']['id']]})
        self.assertEqual(topic.status_code, 201, topic.json)
        prefix = '/api/collaboration/topics/' + topic.json['id']
        saved = self.call(b, prefix + '/candidates', {'request_id': 'trial-upload', 'version': 0, 'topic_version': 1, 'sharing_confirmed': True}, file=b'synthetic report')
        self.assertEqual(saved.status_code, 201, saved.json)
        item = a.get(prefix + '/candidates').json['items'][0]
        self.assertEqual(item['author_id'], second['user']['id'])
        self.assertEqual(a.get(prefix).json['lead_id'], first['user']['id'])
        cookie = a.get_cookie('session')
        restarted = self.app().test_client()
        restarted.set_cookie('session', cookie.value)
        self.assertEqual(restarted.get('/api/session').json['user']['id'], first['user']['id'])
        self.assertEqual(restarted.get(prefix).status_code, 200)
        normal = create_app(self.data, testing=True, embedded_worker=False).test_client()
        normal.set_cookie('session', cookie.value)
        self.assertEqual(normal.get('/api/users').status_code, 401)

    def test_seed_samples_are_read_only_and_survive_backup_without_reassigning_old_work(self):
        from portable.demo_seed import seed
        seed_app = create_app(self.data, testing=True, embedded_worker=False)
        sample = seed(seed_app)
        app, client = self.app(), None
        client = app.test_client()
        visitor = client.get('/api/session').json['user']
        prefix = '/api/collaboration/topics/' + sample['active_topic']
        detail = client.get(prefix)
        self.assertEqual(detail.status_code, 200, detail.json)
        self.assertTrue(detail.json['trial_sample'])
        self.assertFalse(detail.json['can_submit'])
        self.assertNotEqual(detail.json['lead_id'], visitor['id'])
        denied = self.call(client, prefix + '/candidates', {'request_id': 'cannot-own-sample', 'version': 0, 'topic_version': 1, 'sharing_confirmed': True}, file=b'synthetic')
        self.assertEqual(denied.status_code, 403)
        own = self.call(client, '/api/collaboration/topics', {'theme': '私有的练习', 'participant_ids': []}).json['id']
        stranger = app.test_client()
        stranger.get('/api/session')
        self.assertEqual(stranger.get('/api/collaboration/topics/' + own).status_code, 404)
        journal = client.get('/api/collaboration/journals/' + sample['journal'])
        self.assertEqual(journal.status_code, 200, journal.json)
        self.assertFalse(journal.json['can_edit'])
        self.assertTrue(any(w.get('trial_sample') for w in client.get('/api/collaboration/works?scope=all').json['items']))
        archive = create_backup(self.data)
        target = Path(self.tmp.name) / 'restored'
        restore_backup(archive, target)
        restored = create_app(target, testing=True, embedded_worker=False, portable_trial=True).test_client()
        restored.get('/api/session')
        self.assertEqual(restored.get(prefix).status_code, 200)
        self.assertEqual(restored.get('/api/collaboration/topics/' + own).status_code, 404)

    def test_host_is_local_only_and_public_demo_password_never_grants_admin(self):
        app = self.app()
        a = app.test_client()
        a.get('/api/session')
        for path in ('/api/backup', '/api/trial/host'):
            self.assertEqual(self.call(a, path).status_code, 403)
        denied = self.call(a, '/api/login', {'username': 'admin', 'password': 'LocalDemo2026!'})
        self.assertEqual(denied.status_code, 403)
        host = self.call(a, '/api/trial/host', remote='127.0.0.1')
        self.assertEqual(host.status_code, 200, host.json)
        self.assertEqual(host.json['user']['role'], 'admin')
        self.assertEqual(a.get('/api/users', environ_overrides={'REMOTE_ADDR': '192.0.2.11'}).status_code, 403)
        self.assertEqual(a.get('/api/session', headers={'X-Forwarded-For': '127.0.0.1'}).status_code, 400)
        self.assertEqual(self.call(a, '/api/trial/host', remote='192.0.2.11').status_code, 403)

    def test_logout_disable_and_normal_application_keep_authentication_boundary(self):
        app, a = self.app(), None
        a = app.test_client()
        uid = a.get('/api/session').json['user']['id']
        self.assertEqual(self.call(a, '/api/logout').status_code, 200)
        self.assertIsNone(a.get('/api/session').json['user'])
        self.assertEqual(a.get('/api/users').status_code, 401)
        self.assertEqual(self.call(a, '/api/trial/enter').status_code, 200)
        current = a.get('/api/session').json['user']['id']
        self.assertNotEqual(current, uid)
        db = connect(self.data / 'platform.sqlite3')
        with db:
            db.execute('UPDATE users SET active=0 WHERE id=?', (current,))
        db.close()
        self.assertIsNone(a.get('/api/session').json['user'])
        self.assertEqual(a.get('/api/users').status_code, 401)
        self.assertEqual(self.call(a, '/api/trial/enter').status_code, 401)
        normal = create_app(self.data, testing=True, embedded_worker=False).test_client()
        self.assertIsNone(normal.get('/api/session').json['user'])
        self.assertEqual(normal.get('/api/users').status_code, 401)
        with self.assertRaises(ValueError):
            create_app(self.data, testing=True, initialization_mode='production', portable_trial=True)

    def test_unmarked_legacy_backup_retains_accounts_and_private_topic_permissions(self):
        original = create_app(self.data, testing=True, embedded_worker=False)
        admin = original.test_client()
        csrf = admin.get('/api/session').json['csrf']
        admin.post('/api/login', json={'username': 'admin', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf})
        qualifications = admin.get('/api/collaboration/qualifications').json['items']
        current = next(q for q in qualifications if q['id'] == 'colleague')
        self.call(admin, '/api/collaboration/qualifications/colleague', {'version': current['version'], 'enabled': True}, 'PUT')
        old_member = original.test_client()
        csrf = old_member.get('/api/session').json['csrf']
        old_member.post('/api/login', json={'username': 'colleague', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf})
        old_topic = self.call(old_member, '/api/collaboration/topics', {'theme': '演示标题也不能作为开放依据', 'participant_ids': []}).json['id']
        old_record = self.call(old_member, '/api/records', {'kind': 'research_report', 'title': '旧私人研究报告', 'visibility': 'restricted', 'sharing_confirmed': True}).json['id']
        with closing(connect(self.data / 'platform.sqlite3')) as db:
            with db:
                db.execute("UPDATE users SET active=0 WHERE id='researcher'")
                from werkzeug.security import generate_password_hash
                db.execute("UPDATE users SET password_hash=?,credential_version=credential_version+1 WHERE id='admin'", (generate_password_hash('Synthetic private host password 2026!'),))
            old_users = [tuple(r) for r in db.execute('SELECT * FROM users ORDER BY id')]
        archive = create_backup(self.data)
        target = Path(self.tmp.name) / 'old-restored'
        restore_backup(archive, target)
        app = create_app(target, testing=True, embedded_worker=False, portable_trial=True)
        visitor = app.test_client()
        identity = visitor.get('/api/session').json['user']
        self.assertEqual(identity['trial_sample_topics'], [])
        self.assertEqual(visitor.get('/api/collaboration/topics/' + old_topic).status_code, 404)
        self.assertEqual(visitor.get('/api/records/' + old_record).status_code, 404)
        self.assertTrue(visitor.get('/api/collaboration/works').json['can_create'])
        with closing(connect(target / 'platform.sqlite3')) as db:
            self.assertEqual([tuple(r) for r in db.execute("SELECT * FROM users WHERE id NOT LIKE 'trial_%' ORDER BY id")], old_users)
        created = self.call(visitor, '/api/collaboration/topics', {'theme': '新目录可单人实践', 'participant_ids': []})
        self.assertEqual(created.status_code, 201, created.json)

    def test_public_demo_cookie_is_downgraded_and_revoked_qualification_is_not_regranted(self):
        legacy = create_app(self.data, testing=True, embedded_worker=False).test_client()
        csrf = legacy.get('/api/session').json['csrf']
        legacy.post('/api/login', json={'username': 'admin', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf})
        app = self.app()
        visitor = app.test_client()
        visitor.set_cookie('session', legacy.get_cookie('session').value)
        self.assertEqual(visitor.get('/api/members').status_code, 401)
        account = visitor.get('/api/session').json['user']
        self.assertTrue(account['temporary'])
        self.assertEqual(account['role'], 'researcher')
        host = app.test_client()
        self.assertEqual(self.call(host, '/api/trial/host', remote='127.0.0.1').status_code, 200)
        revoked = self.call(host, '/api/collaboration/qualifications/' + account['id'], {'version': 1, 'enabled': False}, 'PUT', remote='127.0.0.1')
        self.assertEqual(revoked.status_code, 200, revoked.json)
        self.assertEqual(visitor.get('/api/session').json['user']['id'], account['id'])
        self.assertFalse(visitor.get('/api/collaboration/works').json['can_create'])
        denied = self.call(visitor, '/api/collaboration/topics', {'theme': '已撤资格不能重授', 'participant_ids': []})
        self.assertEqual(denied.status_code, 403)


if __name__ == '__main__':
    unittest.main()
