"""Portable user-facing configuration: synthetic secrets and isolated files only."""
from contextlib import closing, redirect_stdout
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portable import launch


class PasswordGuidanceTests(unittest.TestCase):
    def test_hidden_password_explains_input_retries_then_confirms_without_echo(self):
        output = io.StringIO()
        secret = 'Synthetic password 密码 2026!'
        with patch('getpass.getpass', side_effect=['short', secret, 'different password', secret, secret]), redirect_stdout(output):
            actual = launch.prompt_admin_password()
        self.assertEqual(actual, secret)
        text = output.getvalue()
        self.assertIn('不会显示', text)
        self.assertIn('12', text)
        self.assertIn('不一致', text)
        self.assertIn('确认', text)
        self.assertNotIn(secret, text)
        self.assertNotIn('short', text)

    def test_password_cancel_is_explicit_and_does_not_return_a_password(self):
        output = io.StringIO()
        with patch('getpass.getpass', side_effect=KeyboardInterrupt), redirect_stdout(output):
            self.assertIsNone(launch.prompt_admin_password())
        self.assertIn('取消', output.getvalue())

@unittest.skipUnless(os.name == 'nt', 'Portable credential and lifecycle contract is Windows-only')
class LocalAISettingsTests(unittest.TestCase):
    def test_configuration_is_user_protected_survives_restart_and_starts_disabled(self):
        from portable.ai_settings import LocalAISettings, default_pricing
        with tempfile.TemporaryDirectory(prefix='便携 AI 假值 ') as temp:
            root = Path(temp) / '本包 with spaces'
            root.mkdir()
            storage = Path(temp) / '用户私有'
            settings = LocalAISettings(root, storage_root=storage)
            key = 'synthetic-key-never-real-20261103'
            settings.configure(key, cap='10', model='deepseek-flash', model_version='2026-11-03', pricing=default_pricing())
            restarted = LocalAISettings(root, storage_root=storage)
            self.assertFalse(restarted.status()['enabled'])
            self.assertEqual(restarted.status()['cap'], '10')
            self.assertNotIn(key.encode(), restarted.path.read_bytes())
            self.assertEqual(list(root.iterdir()), [])
            restarted.set_enabled(True)
            self.assertEqual(restarted.runtime_environment()['DEEPSEEK_API_KEY'], key)
            self.assertNotIn(key, str(restarted.status()))
            # Another extraction and a damaged blob both fail closed.
            self.assertFalse(LocalAISettings(Path(temp) / '另一个包', storage_root=storage).status()['configured'])
            restarted.path.write_bytes(b'synthetic damaged configuration')
            self.assertFalse(restarted.status()['configured'])
            self.assertEqual(restarted.runtime_environment(), {})

    def test_zero_budget_and_invalid_versions_cannot_enable_or_replace_working_settings(self):
        from portable.ai_settings import LocalAISettings, default_pricing
        with tempfile.TemporaryDirectory() as temp:
            settings = LocalAISettings(Path(temp) / 'copy', storage_root=Path(temp) / 'private')
            settings.configure('synthetic-key-not-real-0001', cap='0', model='deepseek-flash', model_version='2026-11-03', pricing=default_pricing())
            with self.assertRaises(ValueError):
                settings.set_enabled(True)
            price = default_pricing()
            price['version'] = ''
            with self.assertRaises(ValueError):
                settings.configure('synthetic-key-not-real-0001', cap='10', model='deepseek-flash', model_version='2026-11-03', pricing=price)
            self.assertEqual(settings.status()['cap'], '0')

@unittest.skipUnless(os.name == 'nt', 'Portable credential and lifecycle contract is Windows-only')
class PortableRuntimeTests(unittest.TestCase):
    def setUp(self):
        import threading
        from platform_app.web import create_app
        from portable.ai_settings import LocalAISettings, default_pricing
        self.temp = tempfile.TemporaryDirectory(prefix='portable AI 单元 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '解压 包'
        self.root.mkdir()
        self.data = self.root / 'data'
        self.state = self.root / '.portable'
        self.state.mkdir()
        self.app = create_app(self.data, testing=True, embedded_worker=False)
        self.settings = LocalAISettings(self.root, storage_root=Path(self.temp.name) / 'private')
        self.key = 'synthetic-provider-only-key-20261103'
        self.settings.configure(self.key, cap='10', model='deepseek-flash', model_version='2026-11-03', pricing=default_pricing())
        self.stop = threading.Event()
        self.env = patch.dict('os.environ')
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_absent_or_disabled_settings_ignore_inherited_keys_and_pause_restored_database(self):
        import os
        from portable.worker import prepare_runtime, set_policy
        from platform_app.ai_gateway import runtime_configuration, summary
        from platform_app.store import connect
        set_policy(self.data, self.settings, paused=False, configure=True)
        os.environ['DEEPSEEK_API_KEY'] = 'synthetic-inherited-must-not-use'
        self.assertFalse(prepare_runtime(self.data, self.settings))
        with self.assertRaises(ValueError):
            runtime_configuration()
        with closing(connect(self.data / 'platform.sqlite3')) as db:
            self.assertTrue(summary(db)['paused'])
        self.assertNotIn('DEEPSEEK_API_KEY', os.environ)
        self.settings.set_enabled(True)
        self.assertTrue(prepare_runtime(self.data, self.settings))
        self.assertEqual(runtime_configuration()[0], self.key)

    def test_worker_opt_in_ownership_graceful_stop_and_restart_without_listeners(self):
        from portable.worker import PortableWorker, prepare_runtime, set_policy
        import time
        paused = PortableWorker(self.data, self.state, self.settings, self.stop)
        paused.start()
        self.assertEqual(paused.status()['worker_state'], 'not_started')
        self.settings.set_enabled(True)
        set_policy(self.data, self.settings, paused=False, configure=True)
        prepare_runtime(self.data, self.settings)
        worker = PortableWorker(self.data, self.state, self.settings, self.stop)
        worker.start()
        try:
            other = PortableWorker(self.data, self.state, self.settings, self.stop)
            with self.assertRaises(ValueError):
                other.start()
            with self.assertRaises(ValueError):
                worker.start()
            deadline = time.monotonic() + 5
            while not (self.state / 'worker-status.json').exists():
                self.assertLess(time.monotonic(), deadline)
            self.settings.set_enabled(False)
            worker.thread.join(timeout=5)
            self.assertFalse(worker.thread.is_alive())
            self.assertEqual(worker.status()['worker_state'], 'stopped')
            self.assertNotIn(self.key, (self.state / 'worker-status.json').read_text(encoding='utf-8'))
        finally:
            worker.stop()
        self.settings.set_enabled(True)
        import threading
        restarted = PortableWorker(self.data, self.state, self.settings, threading.Event())
        restarted.start()
        restarted.stop()
        self.assertEqual(restarted.status()['worker_state'], 'stopped')

    def test_backup_restore_preserves_business_policy_without_secret_and_defaults_to_pause(self):
        from portable.worker import prepare_runtime, set_policy
        from portable.ai_settings import LocalAISettings
        from platform_app.maintenance import create_backup, restore_backup
        from platform_app.store import connect
        from platform_app.ai_gateway import summary
        self.settings.set_enabled(True)
        set_policy(self.data, self.settings, paused=False, configure=True)
        archive = create_backup(self.data)
        self.assertNotIn(self.key.encode(), archive.read_bytes())
        target = Path(self.temp.name) / '恢复副本'
        target.mkdir()
        restore_backup(archive, target / 'data')
        restored = LocalAISettings(target, storage_root=Path(self.temp.name) / 'private')
        self.assertFalse(restored.status()['configured'])
        self.assertFalse(prepare_runtime(target / 'data', restored))
        with closing(connect(target / 'data/platform.sqlite3')) as db:
            state = summary(db)
        self.assertTrue(state['paused'])
        self.assertEqual(state['cap_units'], 10000000)

@unittest.skipUnless(os.name == 'nt', 'Portable credential and lifecycle contract is Windows-only')
class PortableTerminalIntegrationTests(unittest.TestCase):
    def test_lan_configuration_requires_no_input_and_preserves_accounts_and_port(self):
        from platform_app.web import create_app
        from platform_app.store import connect
        import json
        import sys
        with tempfile.TemporaryDirectory(prefix='LAN 中文 空格 ') as temp:
            root = Path(temp)
            create_app(root / 'data', testing=True, embedded_worker=False)
            state = root / '.portable'
            with closing(connect(root / 'data/platform.sqlite3')) as db:
                before = [tuple(r) for r in db.execute('SELECT * FROM users ORDER BY id')]
            for argv in (['launch.py', 'lan-configure', '--port', '18516'], ['launch.py', 'lan-configure']):
                output = io.StringIO()
                with patch.object(launch, 'ROOT', root), patch.object(launch, 'STATE', state), \
                     patch.dict(os.environ), patch.object(sys, 'argv', argv), \
                     patch.object(sys, 'stdin', io.StringIO('')), redirect_stdout(output):
                    launch.main()
                self.assertIn('无需账号口令', output.getvalue())
                self.assertEqual(json.loads((state / 'lan.json').read_text(encoding='utf-8')), {'port': 18516})
            with closing(connect(root / 'data/platform.sqlite3')) as db:
                self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM users ORDER BY id')], before)

@unittest.skipUnless(os.name == 'nt', 'Portable credentials use Windows DPAPI')
class PortableGatewayTests(unittest.TestCase):
    setUp = PortableRuntimeTests.setUp

    def test_local_cny_prices_settle_and_missing_usage_stays_unknown_without_retries(self):
        from unittest.mock import MagicMock
        from platform_app.ai_gateway import request_json, summary, AIBlocked, AIFailure
        from platform_app.store import connect
        from portable.worker import set_policy, prepare_runtime
        import json
        self.settings.set_enabled(True)
        set_policy(self.data, self.settings, paused=False, configure=True)
        prepare_runtime(self.data, self.settings)
        missing = False
        def respond(request, **kwargs):
            self.assertEqual(request.get_header('Authorization'), 'Bearer ' + self.key)
            data = {'model': 'deepseek-flash', 'usage': {'prompt_tokens': 23, 'completion_tokens': 7,
                'total_tokens': 30, 'prompt_cache_hit_tokens': 3, 'prompt_cache_miss_tokens': 20},
                'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":1}'}}]}
            if missing:
                data.pop('usage')
            response = MagicMock()
            response.__enter__.return_value = response
            response.geturl.return_value = request.full_url
            response.read.return_value = json.dumps(data).encode()
            return response
        with closing(connect(self.data / 'platform.sqlite3')) as db, patch('urllib.request.OpenerDirector.open', side_effect=respond) as provider:
            args = dict(scope='synthetic-portable', task='synthetic-test', validate=lambda v:v,
                        authorized=lambda:True, max_tokens=32)
            result, _ = request_json(db, messages=[{'role':'user','content':'synthetic first'}], **args)
            self.assertEqual(result, {'ok':1})
            state = summary(db)
            self.assertEqual(state['charged_units'], 97)
            self.assertEqual(state['held_units'], 0)
            self.assertEqual(state['currency'], 'CNY')
            self.assertNotIn(self.key, json.dumps(state))
            missing = True
            with self.assertRaises(AIFailure):
                request_json(db, messages=[{'role':'user','content':'synthetic missing usage'}], **args)
            with self.assertRaises(AIBlocked):
                request_json(db, messages=[{'role':'user','content':'synthetic later blocked'}], **args)
            self.assertEqual(provider.call_count, 2)
            state = summary(db)
            self.assertGreater(state['held_units'], 0)
            self.assertEqual([a['status'] for a in state['attempts']], ['unknown','settled'])

    def test_admin_status_includes_only_safe_portable_configuration_and_respects_auth(self):
        from portable.worker import PortableWorker
        worker = PortableWorker(self.data, self.state, self.settings, self.stop)
        self.app.config['PORTABLE_AI_STATUS'] = worker.status
        client = self.app.test_client()
        self.assertEqual(client.get('/api/admin/ai').status_code, 401)
        token = client.get('/api/session').json['csrf']
        result = client.post('/api/login', json={'username':'researcher','password':'LocalDemo2026!'},headers={'X-CSRF-Token':token})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(client.get('/api/admin/ai').status_code, 403)
        token = client.get('/api/session').json['csrf']
        client.post('/api/login', json={'username':'admin','password':'LocalDemo2026!'},headers={'X-CSRF-Token':token})
        result = client.get('/api/admin/ai')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['portable']['worker_state'], 'not_started')
        self.assertTrue(result.json['portable']['configured'])
        self.assertFalse(result.json['portable']['enabled'])
        self.assertNotIn(self.key, result.get_data(as_text=True))
        self.app.config.pop('PORTABLE_AI_STATUS')
        self.assertIsNone(client.get('/api/admin/ai').json['portable'])

@unittest.skipUnless(os.name == 'nt', 'Portable terminal contract is Windows-only')
class PortableEncodingTests(unittest.TestCase):
    def test_utf8_cli_preserves_existing_password_without_prompt(self):
        import subprocess
        import sys
        from platform_app.web import create_app
        from werkzeug.security import check_password_hash
        from platform_app.store import connect
        with tempfile.TemporaryDirectory(prefix='CLI 中文 空格 ') as temp:
            root = Path(temp)
            create_app(root / 'data', testing=True, embedded_worker=False)
            password = 'Synthetic 中文 空格口令 2026!'
            helper = "import sys; from pathlib import Path; from portable import launch; launch.ROOT=Path(sys.argv.pop(1)); launch.STATE=launch.ROOT/'.portable'; launch.main()"
            result = subprocess.run([sys.executable, '-c', helper, str(root), 'lan-configure', '--password-stdin'],
                input=password+'\n'+password+'\n', text=True, encoding='utf-8', capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('无需账号口令', result.stdout)
            self.assertNotIn(password, result.stdout+result.stderr)
            with closing(connect(root / 'data/platform.sqlite3')) as db:
                stored = db.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
            self.assertTrue(check_password_hash(stored, 'LocalDemo2026!'))

@unittest.skipUnless(os.name == 'nt', 'Portable credential storage is Windows-only')
class PortableWizardTests(unittest.TestCase):
    setUp = PortableRuntimeTests.setUp

    def test_save_enable_disable_are_explicit_and_preserve_current_database_budget(self):
        from portable.ai_configure import prompt_configuration, enable, disable
        from portable.worker import prepare_runtime
        from platform_app.store import connect
        from platform_app.ai_gateway import summary
        output = io.StringIO()
        answers = iter(['', '2026-11-03', '', '', '', '', '10', 'SAVE'])
        with redirect_stdout(output):
            self.assertTrue(prompt_configuration(self.settings, self.data, read=lambda _:next(answers), secret_reader=lambda _:self.key))
        self.assertFalse(self.settings.status()['enabled'])
        self.assertNotIn(self.key, output.getvalue())
        with closing(connect(self.data / 'platform.sqlite3')) as db, db:
            db.execute("UPDATE settings SET value=? WHERE key='ai_policy'", ('{"cap":"0.5","currency":"CNY"}',))
        with redirect_stdout(io.StringIO()):
            self.assertFalse(enable(self.settings, self.data, read=lambda _:'cancel'))
            self.assertFalse(self.settings.status()['enabled'])
            self.assertTrue(enable(self.settings, self.data, read=lambda _:'ENABLE'))
            self.assertTrue(prepare_runtime(self.data, self.settings))
            disable(self.settings, self.data)
        self.assertFalse(self.settings.status()['enabled'])
        with closing(connect(self.data / 'platform.sqlite3')) as db:
            state = summary(db)
        self.assertTrue(state['paused'])
        self.assertEqual(state['cap_units'], 500000)

    def test_cancel_does_not_replace_local_configuration_and_missing_terminal_never_echoes(self):
        from portable.ai_configure import prompt_configuration
        from portable.terminal import hidden_input
        import getpass
        import warnings
        output = io.StringIO()
        answers = iter(['', '2026-11-03', '', '', '', '', '1', 'cancel'])
        with redirect_stdout(output):
            self.assertFalse(prompt_configuration(self.settings, self.data, read=lambda _:next(answers), secret_reader=lambda _:'synthetic-new-key-not-saved'))
        self.assertEqual(self.settings.load()['key'], self.key)
        def unavailable(_):
            warnings.warn('synthetic unavailable console', getpass.GetPassWarning)
            raise AssertionError('echoing fallback must never be reached')
        with patch('getpass.getpass', side_effect=unavailable):
            with self.assertRaises(ValueError):
                hidden_input('synthetic prompt')

@unittest.skipUnless(os.name == 'nt', 'Portable runtime credentials use Windows DPAPI')
class PortableDisableGuardTests(unittest.TestCase):
    setUp = PortableRuntimeTests.setUp

    def test_local_disable_overrides_web_unpause_and_corrupt_local_state(self):
        from portable.worker import prepare_runtime, set_policy, install_runtime_guard
        from portable.ai_configure import disable
        from platform_app.ai_gateway import runtime_configuration
        self.settings.set_enabled(True)
        set_policy(self.data, self.settings, paused=False, configure=True)
        prepare_runtime(self.data, self.settings)
        install_runtime_guard(self.app, self.settings)
        client = self.app.test_client()
        token = client.get('/api/session').json['csrf']
        result = client.post('/api/login', json={'username':'admin','password':'LocalDemo2026!'}, headers={'X-CSRF-Token':token})
        self.assertEqual(result.status_code,200)
        self.assertEqual(runtime_configuration()[0],self.key)
        with redirect_stdout(io.StringIO()):
            disable(self.settings,self.data)
        token = client.get('/api/session').json['csrf']
        result = client.post('/api/admin/ai/pause',json={'paused':False},headers={'X-CSRF-Token':token})
        self.assertEqual(result.status_code,200)
        with self.assertRaises(ValueError):
            runtime_configuration()
        # Reconstructing a previously enabled runtime followed by damaged local
        # storage also fails closed before a new Web operation.
        self.settings.set_enabled(True)
        prepare_runtime(self.data,self.settings)
        self.settings.path.write_bytes(b'synthetic damaged blob')
        client.get('/api/session')
        with self.assertRaises(ValueError):
            runtime_configuration()
