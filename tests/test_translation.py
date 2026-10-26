import io
import json
import unittest
from unittest.mock import patch
from tests import test_workflow as workflow_tests


class TranslationTests(unittest.TestCase):
    setUp = workflow_tests.WorkflowTests.setUp
    login = workflow_tests.WorkflowTests.login
    def call(self, *args, **kwargs):
        response = workflow_tests.WorkflowTests.call(self, *args, **kwargs)
        self.addCleanup(response.close)
        return response

    def get(self, path, user='researcher'):
        response = self.clients[user].get(path)
        self.addCleanup(response.close)
        return response

    record = workflow_tests.WorkflowTests.record
    detail = workflow_tests.WorkflowTests.detail

    def test_explicit_job_only_sends_title_abstract_and_keeps_machine_separate(self):
        rid = self.record(title='Synthetic original', abstract='Synthetic abstract', body_html='<p>Private body never sent</p>')
        with patch('urllib.request.OpenerDirector.open') as network:
            job = self.call(f'/api/records/{rid}/translations', {'version': 1, 'request_id': 'first'})
            self.assertEqual(job.status_code, 201, job.json)
            item = self.get(f'/api/records/{rid}/translations').json['items'][0]
            self.assertEqual(item['status'], 'queued')
            network.assert_not_called()
        self.assertEqual(item['input_title'], 'Synthetic original')
        self.assertEqual(item['input_abstract'], 'Synthetic abstract')
        self.assertEqual(self.detail(rid)['chinese_title'], '')

    def provider(self, title='合成译题', abstract='合成摘要'):
        response = unittest.mock.MagicMock()
        response.geturl.return_value = "https://api.deepseek.com/chat/completions"
        response.read.return_value = json.dumps({'choices': [{'message': {'content': json.dumps({'title': title, 'abstract': abstract})}}]}).encode()
        response.__enter__.return_value = response
        return response

    @patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'synthetic-secret-test', 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com', 'DEEPSEEK_MODEL': 'deepseek-chat'})
    def test_run_adopt_edit_history_and_rerun_preserve_original_and_human(self):
        rid = self.record(title='Original title', abstract='Original abstract', body_html='<p>Never send body</p>')
        jid = self.call(f'/api/records/{rid}/translations', {'version': 1, 'request_id': 'adopt'}).json['id']
        with patch('urllib.request.OpenerDirector.open', return_value=self.provider()) as network:
            result = self.call(f'/api/translations/{jid}/run')
            self.assertEqual(result.status_code, 200, result.json)
            payload = json.loads(network.call_args.args[0].data)
            self.assertEqual(json.loads(payload['messages'][1]['content']), {'title': 'Original title', 'abstract': 'Original abstract'})
        generated = self.detail(rid)
        self.assertEqual(generated['translations'][0]['output_title'], '合成译题')
        self.assertEqual(generated['chinese_title'], '')
        adopted = self.call(f'/api/translations/{jid}/adopt', {'version': 1, 'chinese_title': '人工校订题名', 'chinese_abstract': '人工校订摘要'}, user='colleague')
        self.assertEqual(adopted.status_code, 200, adopted.json)
        human = self.detail(rid)
        self.assertEqual((human['title'], human['abstract']), ('Original title', 'Original abstract'))
        self.assertEqual(human['chinese_title'], '人工校订题名')
        self.assertEqual(self.call(f'/api/records/{rid}', {'version': 2, 'chinese_title': '共同修订'}, method='PUT', user='colleague').status_code, 200)
        second = self.call(f'/api/records/{rid}/translations', {'version': 3, 'request_id': 'rerun'}).json['id']
        with patch('urllib.request.OpenerDirector.open', return_value=self.provider('新机译', '新摘要')):
            self.assertEqual(self.call(f'/api/translations/{second}/run').status_code, 200)
        self.assertEqual(self.detail(rid)['chinese_title'], '共同修订')
        history = self.get(f'/api/history/record/{rid}').json['items']
        adopted_revision = next(h for h in history if '采用机器译文' in h['action'])
        self.assertEqual(self.call(f"/api/history/{adopted_revision['id']}/restore", {'version': 3}).status_code, 200)
        self.assertEqual(self.detail(rid)['chinese_title'], '人工校订题名')

    @patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'synthetic-secret-test', 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com', 'DEEPSEEK_MODEL': 'deepseek-chat'})
    def test_failure_retry_missing_abstract_and_idempotency(self):
        rid = self.record(title='Title only')
        jid = self.call(f'/api/records/{rid}/translations', {'version': 1, 'request_id': 'unique'}).json['id']
        self.assertEqual(self.call(f'/api/records/{rid}/translations', {'version': 1, 'request_id': 'unique'}).json['id'], jid)
        with patch('urllib.request.OpenerDirector.open', side_effect=TimeoutError('synthetic-secret-test')):
            result = self.call(f'/api/translations/{jid}/run')
            self.assertEqual(result.json['status'], 'failed')
            self.assertNotIn('synthetic-secret-test', result.text)
        self.assertEqual(self.call(f'/api/translations/{jid}/retry').status_code, 200)
        with patch('urllib.request.OpenerDirector.open', return_value=self.provider('仅题译文', '')):
            result = self.call(f'/api/translations/{jid}/run')
            self.assertEqual(result.json['status'], 'succeeded')
            self.assertEqual(result.json['attempts'], 2)
            self.assertEqual(result.json['output_abstract'], '')
        with patch('urllib.request.OpenerDirector.open') as network:
            self.assertEqual(self.call(f'/api/translations/{jid}/run').status_code, 409)
            network.assert_not_called()

    @patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'synthetic-secret-test', 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com', 'DEEPSEEK_MODEL': 'deepseek-chat'})
    def test_stale_result_refused_and_latest_permissions_rechecked(self):
        rid = self.record(title='Unchanged input')
        jid = self.call(f'/api/records/{rid}/translations', {'version': 1, 'request_id': 'late'}).json['id']
        def later(*args, **kwargs):
            self.assertEqual(self.call(f'/api/records/{rid}', {'version': 1, 'title': 'Revised input'}, method='PUT').status_code, 200)
            return self.provider('旧译文', '')
        with patch('urllib.request.OpenerDirector.open', side_effect=later):
            self.assertEqual(self.call(f'/api/translations/{jid}/run').json['status'], 'succeeded')
        self.assertTrue(self.detail(rid)['translations'][0]['stale'])
        self.assertEqual(self.call(f'/api/translations/{jid}/adopt', {'version': 2}).status_code, 409)
        self.assertEqual(self.call(f'/api/records/{rid}', {'version': 2, 'visibility': 'restricted'}, method='PUT').status_code, 200)
        for path, method in [(f'/api/records/{rid}/translations', 'GET'), (f'/api/records/{rid}/translations', 'POST'), (f'/api/translations/{jid}/run', 'POST'), (f'/api/translations/{jid}/retry', 'POST'), (f'/api/translations/{jid}/adopt', 'POST')]:
            self.assertEqual(self.call(path, {'version': 3, 'request_id': 'denied'}, user='colleague', method=method).status_code, 404)

    @patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'synthetic-secret-test', 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com', 'DEEPSEEK_MODEL': 'deepseek-chat'})
    def test_exports_and_backup_restore_retain_versions_without_running_jobs(self):
        import zipfile
        from pathlib import Path
        from platform_app.maintenance import create_backup, restore_backup
        from platform_app.web import create_app
        rid = self.record(title='Export original', abstract='Source abstract')
        jid = self.call(f'/api/records/{rid}/translations', {'version': 1, 'request_id': 'export'}).json['id']
        with patch('urllib.request.OpenerDirector.open', return_value=self.provider()):
            self.call(f'/api/translations/{jid}/run')
        self.call(f'/api/translations/{jid}/adopt', {'version': 1})
        pending = self.call(f'/api/records/{rid}/translations', {'version': 2, 'request_id': 'pending'}).json['id']
        exported = self.get('/api/export/content')
        with io.BytesIO(exported.data) as buffer, zipfile.ZipFile(buffer) as archive:
            payload = json.loads(archive.read('content.json'))
            item = next(x for x in payload['records'] if x['id'] == rid)
            self.assertEqual(item['chinese_title'], '合成译题')
            self.assertEqual(len(item['translations']), 2)
            self.assertIn('Export original', archive.read(item['path']).decode())
            self.assertIn('合成译题', archive.read(item['path']).decode())
            self.assertNotIn(b'synthetic-secret-test', b''.join(archive.read(n) for n in archive.namelist()))
        import subprocess
        import sys
        exported_path = Path(self.temp.name) / 'translation-content.zip'
        exported_path.write_bytes(exported.data)
        verifier = Path(__file__).resolve().parents[1] / 'scripts' / 'verify_content_export.py'
        verified = subprocess.run([sys.executable, '-I', str(verifier), str(exported_path)],
                                  cwd=self.temp.name, capture_output=True, text=True)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertIn('合成译题', self.get('/api/export').data.decode('utf-8-sig'))
        backup = create_backup(self.data_dir)
        restored = restore_backup(backup, Path(self.temp.name) / 'restored-translations')
        with patch('urllib.request.OpenerDirector.open') as network:
            app = create_app(restored, testing=True)
            client = self.login('colleague', app)
            with client.get(f'/api/records/{rid}') as response:
                detail = response.json
            self.assertEqual(detail['chinese_title'], '合成译题')
            self.assertEqual(next(x for x in detail['translations'] if x['id'] == pending)['status'], 'queued')
            network.assert_not_called()

    @patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'synthetic-secret-test', 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com', 'DEEPSEEK_MODEL': 'deepseek-chat'})
    def test_invalid_outputs_never_become_versions_and_retry_is_bounded(self):
        rid = self.record(title='Title only')
        jid = self.call(f'/api/records/{rid}/translations', {'version': 1, 'request_id': 'invalid'}).json['id']
        for title, abstract in [('Invented', 'No source exists'), ('synthetic-secret-test', ''), ('x' * 4001, '')]:
            with patch('urllib.request.OpenerDirector.open', return_value=self.provider(title, abstract)):
                result = self.call(f'/api/translations/{jid}/run')
            self.assertEqual(result.json['status'], 'failed')
            self.assertEqual(result.json['output_title'], '')
            self.assertNotIn('synthetic-secret-test', result.text)
            retry = self.call(f'/api/translations/{jid}/retry')
            self.assertEqual(retry.status_code, 409 if result.json['attempts'] == 3 else 200)

    @patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'synthetic-secret-test', 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com', 'DEEPSEEK_MODEL': 'deepseek-chat'})
    def test_permission_removed_during_network_discards_result(self):
        rid = self.record(title='Initially shared')
        jid = self.call(f'/api/records/{rid}/translations', {'version': 1, 'request_id': 'revoked'}, user='colleague').json['id']
        def revoke(*args, **kwargs):
            self.assertEqual(self.call(f'/api/records/{rid}', {'version': 1, 'visibility': 'restricted'}, method='PUT').status_code, 200)
            return self.provider('Must be discarded', '')
        with patch('urllib.request.OpenerDirector.open', side_effect=revoke):
            result = self.call(f'/api/translations/{jid}/run', user='colleague')
        self.assertEqual(result.status_code, 404)
        job = self.detail(rid)['translations'][0]
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['output_title'], '')

    def test_v11_backup_chain_to_15_preserves_prior_migrations_and_rolls_back_translation_failure(self):
        from pathlib import Path
        from platform_app.store import connect
        from platform_app.maintenance import create_backup, restore_backup
        from platform_app.web import create_app
        from contextlib import closing
        import sqlite3
        fixtures = Path(__file__).parent / 'fixtures'
        expected = json.loads((fixtures / 'collection_scope_v11.json').read_text())
        legacy = Path(self.temp.name) / 'genuine-v11'
        legacy.mkdir()
        with closing(sqlite3.connect(legacy / 'platform.sqlite3')) as db:
            db.executescript((fixtures / 'collection_scope_v11.sql').read_text())
        restored = restore_backup(create_backup(legacy), Path(self.temp.name) / 'upgrade-to-15')
        with closing(connect(restored / 'platform.sqlite3')) as db:
            db.execute("CREATE TRIGGER reject_translation_upgrade BEFORE UPDATE ON settings WHEN NEW.value='15' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
            db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            create_app(restored, testing=True)
        with closing(connect(restored / 'platform.sqlite3')) as db:
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0], '14')
            self.assertIn('volume', [row['name'] for row in db.execute('PRAGMA table_info(records)')])
            self.assertIn('stance', [row['name'] for row in db.execute('PRAGMA table_info(evidence_links)')])
            self.assertIn('disposition', [row['name'] for row in db.execute('PRAGMA table_info(collection_items)')])
            self.assertNotIn('chinese_title', [row['name'] for row in db.execute('PRAGMA table_info(records)')])
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='translation_jobs'").fetchone())
            db.execute('DROP TRIGGER reject_translation_upgrade')
            db.commit()
        backups = list((restored / 'backups').glob('*.zip'))
        self.assertEqual(len(backups), 4)
        versions = set()
        with patch('urllib.request.OpenerDirector.open') as network:
            app = create_app(restored, testing=True)
            with app.test_client().get('/health') as response:
                self.assertEqual(response.json['schema'], 15)
            client = self.login('colleague', app)
            with client.get('/api/records/' + expected['record_id']) as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json['chinese_title'], '')
                self.assertEqual(response.json['translations'], [])
            for index, archive in enumerate(backups):
                stage = restore_backup(archive, Path(self.temp.name) / ('before-15-' + str(index)))
                with closing(connect(stage / 'platform.sqlite3')) as db:
                    version = int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0])
                    versions.add(version)
                    self.assertEqual('volume' in [r['name'] for r in db.execute('PRAGMA table_info(records)')], version >= 12)
                    self.assertEqual('stance' in [r['name'] for r in db.execute('PRAGMA table_info(evidence_links)')], version >= 13)
                    self.assertEqual('disposition' in [r['name'] for r in db.execute('PRAGMA table_info(collection_items)')], version >= 14)
                    # Migration backups preserve the deliberately injected failure trigger.
                    db.execute('DROP TRIGGER IF EXISTS reject_translation_upgrade')
                    db.commit()
                with create_app(stage, testing=True).test_client().get('/health') as response:
                    self.assertEqual(response.json['schema'], 15)
            network.assert_not_called()
        self.assertEqual(versions, {11, 12, 13, 14})

    @patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'synthetic-secret-test', 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com', 'DEEPSEEK_MODEL': 'deepseek-chat'})
    def test_merge_does_not_adopt_archived_record_translation_into_survivor(self):
        keep = self.record(title='Surviving original')
        old = self.record(title='Archived original')
        self.call(f'/api/records/{old}', {'version': 1, 'title': 'Revised archived original'}, method='PUT')
        jid = self.call(f'/api/records/{old}/translations', {'version': 2, 'request_id': 'merge'}).json['id']
        with patch('urllib.request.OpenerDirector.open', return_value=self.provider('Archived translation', '')):
            self.call(f'/api/translations/{jid}/run')
        self.assertEqual(self.call('/api/merge', {'type': 'record', 'keep_id': keep, 'duplicate_id': old, 'keep_version': 1, 'duplicate_version': 2, 'confirmed': True}, user='admin').status_code, 200)
        result = self.call(f'/api/translations/{jid}/adopt', {'version': 2})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.detail(keep)['chinese_title'], '')

    @patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'synthetic-secret-test', 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com'})
    def test_network_deadline_and_429_are_safe_explicit_failures(self):
        import time
        from urllib.error import HTTPError
        rid = self.record(title='Bounded input')
        jid = self.call(f'/api/records/{rid}/translations', {'version': 1, 'request_id': 'deadline'}).json['id']
        def delayed(*args, **kwargs):
            time.sleep(.1)
            return self.provider('Late output', '')
        with patch('platform_app.translations.MAX_SECONDS', .01), patch('urllib.request.OpenerDirector.open', side_effect=delayed):
            result = self.call(f'/api/translations/{jid}/run')
            self.assertEqual(result.json['status'], 'failed')
        self.assertEqual(self.call(f'/api/translations/{jid}/retry').status_code, 200)
        with patch('urllib.request.OpenerDirector.open', side_effect=HTTPError('https://api.deepseek.com', 429, 'synthetic-secret-test', {}, None)):
            result = self.call(f'/api/translations/{jid}/run')
            self.assertEqual(result.json['status'], 'failed')
            self.assertNotIn('synthetic-secret-test', result.text)
        time.sleep(.15)
        job = self.detail(rid)['translations'][0]
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['output_title'], '')

    @patch.dict('os.environ', {'DEEPSEEK_API_KEY': '', 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com'})
    def test_missing_runtime_configuration_keeps_original_and_a_retryable_task(self):
        rid = self.record(title='Keep original when unconfigured')
        jid = self.call(f'/api/records/{rid}/translations', {'version': 1, 'request_id': 'unconfigured'}).json['id']
        with patch('urllib.request.OpenerDirector.open') as network:
            result = self.call(f'/api/translations/{jid}/run')
            self.assertEqual(result.json['status'], 'failed')
            self.assertIn('配置', result.json['error'])
            network.assert_not_called()
        self.assertEqual(self.detail(rid)['title'], 'Keep original when unconfigured')
        self.assertEqual(self.call(f'/api/translations/{jid}/retry').status_code, 200)

    def test_restore_rejects_dangling_adopted_translation_reference(self):
        from pathlib import Path
        from platform_app.store import connect
        from platform_app.maintenance import create_backup, restore_backup
        from contextlib import closing
        rid = self.record(title='Backup integrity original')
        with closing(connect(self.data_dir / 'platform.sqlite3')) as db:
            db.execute("UPDATE records SET adopted_translation_id='missing-machine-version' WHERE id=?", (rid,))
            db.commit()
        archive = create_backup(self.data_dir)
        with self.assertRaises(ValueError):
            restore_backup(archive, Path(self.temp.name) / 'invalid-adoption')
