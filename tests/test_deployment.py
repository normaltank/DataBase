"""Deployment CLI and public HTTP contracts, using synthetic temporary data only."""
import tempfile
from contextlib import closing
import unittest
from pathlib import Path
import subprocess
import sys
import zipfile


class DeploymentTests(unittest.TestCase):
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
