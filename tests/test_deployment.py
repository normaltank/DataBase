"""Deployment CLI and public HTTP contracts, using synthetic temporary data only."""
import tempfile
import json
import time
from contextlib import closing
import unittest
from pathlib import Path
import subprocess
import sys
import zipfile
import sqlite3
import hashlib


class DeploymentTests(unittest.TestCase):
    def test_production_upgrades_and_restores_researcher_only_v1_without_demo_accounts(self):
        from platform_app import store
        from platform_app.maintenance import restore_backup
        from werkzeug.security import generate_password_hash
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'legacy-production'
            (data / 'uploads').mkdir(parents=True)
            raw = b'Synthetic legacy original.\n'
            stored = 'a'*32 + '.txt'
            (data / 'uploads' / stored).write_bytes(raw)
            with closing(sqlite3.connect(data / 'platform.sqlite3')) as db, db:
                db.executescript(store.SCHEMA)
                db.execute("INSERT INTO settings VALUES ('schema_version','1')")
                db.execute("INSERT INTO users VALUES ('researcher','researcher','原研究员',?,'researcher',1)",
                           (generate_password_hash('Temporary-member-only!42'),))
                db.execute("INSERT INTO sources(id,name,kind,created_at,updated_at) VALUES ('BASE-INSTITUTE','Synthetic base institution','institution','2020','2020')")
                db.execute("INSERT INTO records(id,kind,title,source_id,owner_id,attachment_ids,created_at,updated_at) VALUES ('BASE-ORIGINAL','report','Synthetic legacy work','BASE-INSTITUTE','researcher','[\"base-file\"]','2020','2020')")
                db.execute("INSERT INTO attachments VALUES ('base-file','BASE-ORIGINAL','base.txt',?,?,?,'2020')",
                           (stored, len(raw), hashlib.sha256(raw).hexdigest()))
                db.execute("INSERT INTO revisions(target_type,target_id,action,actor_id,created_at,snapshot_json) VALUES ('record','BASE-ORIGINAL','Original human history','researcher','2020','{}')")
            store.initialize(data, mode='production')
            with closing(store.connect(data / 'platform.sqlite3')) as db:
                backup = Path(db.execute("SELECT value FROM settings WHERE key='source_catalog_migration_backup'").fetchone()[0])
            restored = restore_backup(backup, Path(tmp) / 'restored-production')
            store.initialize(restored, mode='production')
            for directory in (data, restored):
                with closing(store.connect(directory / 'platform.sqlite3')) as db:
                    self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                    self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0], str(store.CURRENT_SCHEMA_VERSION))
                    self.assertEqual([r[0] for r in db.execute("SELECT username FROM users WHERE role<>'system'")], ['researcher'])
                    self.assertEqual(db.execute("SELECT actor_id FROM revisions WHERE action='Original human history'").fetchone()[0], 'researcher')
                    actors = list(db.execute("SELECT u.role,u.active,u.password_hash FROM revisions r JOIN users u ON u.id=r.actor_id WHERE r.target_type='source'"))
                    self.assertEqual([tuple(row) for row in actors], [('system', 0, '!'), ('system', 0, '!')])
                    self.assertEqual(db.execute("SELECT title FROM records WHERE id='BASE-ORIGINAL'").fetchone()[0], 'Synthetic legacy work')
                self.assertEqual((directory / 'uploads' / stored).read_bytes(), raw)

    def test_production_member_password_guard_and_persisted_no_demo_initialization(self):
        from platform_app.deployment import initialize_admin, application
        from platform_app import store
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'production'
            initialize_admin(data, 'operator', '管理员', 'Temporary-test-only!42')
            config = {'data_dir': str(data), 'hosts': ['center.example.invalid'], 'trusted_proxy': None}
            app = application(config)
            client = app.test_client()
            origin = 'https://center.example.invalid'
            csrf = client.get('/api/session', base_url=origin).json['csrf']
            headers = {'X-CSRF-Token': csrf, 'Origin': origin}
            self.assertEqual(client.post('/api/login', base_url=origin, json={'username': 'operator',
                'password': 'Temporary-test-only!42'}, headers=headers).status_code, 200)
            headers['X-CSRF-Token'] = client.get('/api/session', base_url=origin).json['csrf']
            member = {'username': 'member1', 'name': '合成成员', 'role': 'researcher', 'password': 'LocalDemo2026!'}
            self.assertEqual(client.post('/api/members', base_url=origin, json=member, headers=headers).status_code, 400)
            member['password'] = 'Temporary-member-only!42'
            created = client.post('/api/members', base_url=origin, json=member, headers=headers)
            self.assertEqual(created.status_code, 201, created.json)
            self.assertEqual(client.put('/api/members/'+created.json['id'], base_url=origin,
                json={'password': 'LocalDemo2026!'}, headers=headers).status_code, 400)
            # Even a default/demo launcher must honor the permanent initialization
            # marker and never recreate the demo accounts in this production DB.
            store.initialize(data, mode='demo')
            with closing(store.connect(data / 'platform.sqlite3')) as db:
                self.assertEqual([r[0] for r in db.execute("SELECT username FROM users WHERE role<>'system' ORDER BY username")],
                                 ['member1', 'operator'])

    def test_independent_web_and_worker_logs_rotate_without_losing_messages(self):
        script = '''
import logging, sys, time
from pathlib import Path
from platform_app.deployment import configure_logging
directory, role = Path(sys.argv[1]), sys.argv[2]
configure_logging(directory, role)
handler = logging.getLogger().handlers[-1]
handler.maxBytes = 1024
(directory / (role + '.ready')).touch()
while not (directory / 'start').exists():
    time.sleep(.01)
for index in range(8):
    logging.info('%s-message-%s %s', role, index, 'x' * 220)
logging.shutdown()
'''
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            children = [subprocess.Popen([sys.executable, '-c', script, tmp, role],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for role in ('web', 'worker')]
            try:
                deadline = time.monotonic() + 15
                while not all((directory / (role+'.ready')).exists() for role in ('web', 'worker')):
                    self.assertTrue(all(child.poll() is None for child in children), 'logging child exited early')
                    self.assertLess(time.monotonic(), deadline, 'logging children did not become ready')
                    time.sleep(.05)
                (directory / 'start').touch()
                for child in children:
                    stdout, stderr = child.communicate(timeout=15)
                    self.assertEqual(child.returncode, 0, stderr)
                    self.assertEqual(stderr, '')
                for role in ('web', 'worker'):
                    files = list(directory.glob(role + '.log*'))
                    self.assertGreater(len(files), 1, 'log did not roll over')
                    self.assertLessEqual(len(files), 4)
                    content = ''.join(path.read_text(encoding='utf-8') for path in files)
                    for index in range(8):
                        self.assertEqual(content.count(f'{role}-message-{index} '), 1)
                    other = 'worker' if role == 'web' else 'web'
                    self.assertNotIn(other+'-message-', content)
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.communicate(timeout=10)

    def test_independent_worker_status_stop_restart_and_stale_state(self):
        from platform_app.deployment import initialize_admin
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'worker'
            initialize_admin(data, 'operator', '管理员', 'Temporary-test-only!42')
            config = Path(tmp) / 'config.json'
            config.write_text(json.dumps({'data_dir': str(data), 'log_dir': str(Path(tmp) / 'logs'),
                'hosts': ['center.example.invalid'], 'listen': '127.0.0.1:18542',
                'trusted_proxy': None}), encoding='utf-8')

            def cli(action):
                return subprocess.run([sys.executable, '-m', 'platform_app.deployment', action,
                    '--config', str(config)], capture_output=True, text=True, timeout=20)

            previous = None
            for _ in range(2):
                worker = subprocess.Popen([sys.executable, '-m', 'platform_app.deployment', 'worker',
                    '--config', str(config)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        state_path = data / '.worker-status.json'
                        state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
                        if state.get('state') == 'running' and state.get('instance') != previous:
                            break
                        self.assertIsNone(worker.poll(), 'worker exited before heartbeat')
                        time.sleep(.05)
                    else:
                        self.fail('worker did not publish a heartbeat')
                    previous = state['instance']
                    status = cli('worker-status')
                    self.assertEqual(status.returncode, 0, status.stderr)
                    live = json.loads(status.stdout)
                    self.assertEqual(live['state'], 'running')
                    self.assertTrue(live['process_lock_held'])
                    self.assertTrue(live['heartbeat_recent'])
                    duplicate = cli('worker')
                    self.assertNotEqual(duplicate.returncode, 0)
                    self.assertIn('busy', duplicate.stderr)
                    self.assertEqual(cli('worker-stop').returncode, 0)
                    stdout, stderr = worker.communicate(timeout=20)
                    self.assertEqual(worker.returncode, 0, stderr)
                    stopped = json.loads(cli('worker-status').stdout)
                    self.assertEqual(stopped['state'], 'stopped')
                    self.assertFalse(stopped['process_lock_held'])
                finally:
                    if worker.poll() is None:
                        worker.kill()  # Only this synthetic child, never a persisted PID.
                    worker.communicate(timeout=10)
            state_path.write_text(json.dumps(dict(state='running', instance=previous, heartbeat_epoch=0)), encoding='utf-8')
            stale = json.loads(cli('worker-status').stdout)
            self.assertEqual(stale['state'], 'stale')
            self.assertFalse(stale['process_lock_held'])
            self.assertFalse(stale['heartbeat_recent'])

    def test_source_zip_verifier_rejects_unsafe_names_and_duplicates(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            for index, names in enumerate((['../outside'], ['secret', 'SECRET'], ['C:/drive'])):
                with self.subTest(names=names):
                    archive = Path(tmp) / f'bad{index}.zip'
                    with zipfile.ZipFile(archive, 'w') as zipped:
                        for name in names:
                            zipped.writestr(name, b'SYNTHETIC')
                    run = subprocess.run([sys.executable, str(root / 'scripts/verify_server.py'), str(archive)],
                                         capture_output=True, text=True, timeout=15)
                    self.assertNotEqual(run.returncode, 0)
                    self.assertTrue('Unsafe' in run.stderr or 'Duplicate' in run.stderr, run.stderr)

    def test_production_initialization_and_restart_do_not_create_demo_accounts(self):
        from platform_app.deployment import initialize_admin, application
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / '中心 数据'
            initialize_admin(data, 'operator', '真实管理员', 'Temporary-test-only!42')
            config = {'data_dir': str(data), 'log_dir': str(Path(tmp) / 'logs'),
                      'hosts': ['center.example.invalid'], 'listen': '127.0.0.1:0',
                      'trusted_proxy': None}
            for _ in range(2):
                app = application(config)
                client = app.test_client()
                origin = 'https://center.example.invalid'
                csrf = client.get('/api/session', base_url=origin).json['csrf']
                result = client.post('/api/login', base_url=origin,
                    json={'username': 'operator', 'password': 'Temporary-test-only!42'},
                    headers={'X-CSRF-Token': csrf, 'Origin': origin})
                self.assertEqual(result.status_code, 200)
                self.assertEqual([x['username'] for x in client.get('/api/members', base_url=origin).json['items']], ['operator'])
                self.assertFalse(client.get('/api/session', base_url=origin).json['demo_login'])
                self.assertEqual(client.get('/health', base_url='https://evil.invalid').status_code, 400)
                self.assertEqual(client.get('/health', base_url=origin, headers={'X-Forwarded-Proto': 'https'},
                    environ_overrides={'REMOTE_ADDR': '192.0.2.45'}).status_code, 400)
                self.assertEqual(client.get('/health', base_url=origin, headers={'X-Forwarded-Host': 'evil.invalid'}).status_code, 400)
                self.assertEqual(client.post('/api/logout', base_url=origin).status_code, 403)
            with self.assertRaises(ValueError):
                initialize_admin(data, 'other', '其他', 'Temporary-test-only!42')

    def test_lan_gate_disables_default_members_and_keeps_existing_credentials(self):
        from platform_app.web import create_app
        from platform_app.deployment import configure_lan_admin, default_password_users
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(Path(tmp), testing=True)
            configure_lan_admin(tmp, 'Temporary-test-only!42')
            self.assertEqual(default_password_users(tmp), [])
            restarted = create_app(Path(tmp), testing=True).test_client()
            csrf = restarted.get('/api/session').json['csrf']
            self.assertEqual(restarted.post('/api/login', json={'username': 'researcher', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf}).status_code, 401)
            self.assertEqual(restarted.post('/api/login', json={'username': 'admin', 'password': 'Temporary-test-only!42'}, headers={'X-CSRF-Token': csrf}).status_code, 200)
            with self.assertRaises(ValueError):
                configure_lan_admin(tmp, 'Another-temporary-password!')

    def test_public_import_is_admin_authorized_and_idempotent_without_demo(self):
        from platform_app.deployment import initialize_admin
        from portable.public_batch import import_public
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'sample'
            initialize_admin(data, 'operator', '管理员', 'Temporary-test-only!42')
            with self.assertRaises(ValueError):
                import_public(data, 'operator', 'incorrect')
            first = import_public(data, 'operator', 'Temporary-test-only!42')
            self.assertEqual(len(first['article_ids']), 56)
            self.assertEqual(len(first['source_ids']), 65)
            self.assertEqual(import_public(data, 'operator', 'Temporary-test-only!42'), first)

    def test_future_schema_is_refused_without_modification(self):
        from platform_app.deployment import initialize_admin
        from platform_app.web import create_app
        from platform_app.store import connect
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'future'
            initialize_admin(data, 'operator', '管理员', 'Temporary-test-only!42')
            with closing(connect(data / 'platform.sqlite3')) as db, db:
                db.execute("UPDATE settings SET value='999' WHERE key='schema_version'")
            before = (data / 'platform.sqlite3').read_bytes()
            with self.assertRaisesRegex(ValueError, 'newer'):
                create_app(data, embedded_worker=False)
            self.assertEqual((data / 'platform.sqlite3').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
