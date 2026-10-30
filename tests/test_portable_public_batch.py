"""The public preview is usable through authenticated APIs without a provider call."""
import json
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

from portable.demo_seed import call, login, seed
from platform_app.web import create_app


class PublicPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='portable-public88-')
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / 'data'
        self.app = create_app(self.data, testing=True)
        self.seed = seed(self.app)
        self.reader = login(self.app, 'researcher')

    def test_fresh_preview_preserves_fictional_work_and_reads_real_machine_excerpts(self):
        batch = self.seed['public_batch']
        self.assertEqual(len(batch['source_ids']), 65)
        self.assertEqual(len(batch['core_source_ids']), 38)
        self.assertEqual(len(batch['article_ids']), 56)
        self.assertEqual(self.reader.get('/api/records?size=100').json['total'], 62)
        self.assertEqual(self.reader.get('/api/sources').json['total'], 68)
        details = [self.reader.get('/api/records/' + rid).json for rid in batch['article_ids']]
        self.assertEqual(sum(bool(x['abstract']) for x in details), 23)
        self.assertTrue(all(x['translation_origin'] == 'machine' for x in details))
        self.assertTrue(all(not x['chinese_title'] and not x['chinese_abstract'] for x in details))
        self.assertTrue(all(not x['attachments'] and not x['linked_records'] for x in details))
        self.assertTrue(all(not x['body_html'] and not x['reading_access']['has_body'] for x in details))
        original = next(x for x in details if x['abstract'])
        job = original['translations'][0]
        self.assertEqual(job['attempts'], 0)
        self.assertEqual(job['calls'], [])
        self.assertFalse(job['can_adopt'])
        self.assertEqual(job['preview_import']['alignment'], 'independent_truncation')
        self.assertNotEqual(job['input_hash'], job['preview_import']['source_input_hash'])
        self.assertEqual(original['preview_excerpt']['abstract_mode'], 'excerpt')
        self.assertIn('独立截取', original['preview_excerpt']['notice'])
        self.assertEqual(self.reader.get('/api/records?q=平台工作者&size=100').json['total'], 1)
        admin = login(self.app, 'admin')
        ai = admin.get('/api/admin/ai').json
        self.assertEqual(ai['attempts'], [])
        self.assertEqual(ai['task_counts'], {})
        self.assertTrue(ai['paused'])
        self.assertFalse(ai['worker_heartbeat'])
        self.assertFalse(admin.get('/api/ingestion').json['worker_heartbeat'])
        workflow = self.reader.get('/api/collaboration/topics/' + self.seed['complete_topic'] + '/workflow').json
        self.assertEqual(workflow['assignments'][0]['status'], 'final')

    def test_historical_excerpts_cannot_be_adopted_and_edits_do_not_relabel_history(self):
        rid = self.seed['public_batch']['article_ids'][7]
        detail = self.reader.get('/api/records/' + rid).json
        jid = detail['translations'][0]['id']
        response = self.reader.post('/api/translations/' + jid + '/adopt', json={'version': detail['version']},
                                    headers={'X-CSRF-Token': self.reader.get('/api/session').json['csrf']})
        self.assertEqual(response.status_code, 409)
        call(self.reader, '/api/records/' + rid, {'version': detail['version'], 'keywords': '本地修订'}, method='PUT')
        current = self.reader.get('/api/records/' + rid).json
        self.assertEqual(current['translation_origin'], 'machine')
        self.assertFalse(current['translations'][0]['stale'])
        self.assertTrue(current['translations'][0]['version_changed'])
        call(self.reader, '/api/records/' + rid, {'version': current['version'], 'original_title': 'Changed original input'}, method='PUT')
        changed = self.reader.get('/api/records/' + rid).json
        self.assertEqual(changed['translation_origin'], 'original')
        self.assertFalse(changed['preview_excerpt']['current_machine'])
        self.assertTrue(changed['translations'][0]['stale'])
        self.assertIn('preview_import', changed['translations'][0])
        self.assertFalse(changed['translations'][0]['can_adopt'])
        admin = login(self.app, 'admin')
        backup = admin.post('/api/backup', json={}, headers={
            'X-CSRF-Token': admin.get('/api/session').json['csrf']})
        self.assertEqual(backup.status_code, 200)
        archive = Path(self.temp.name) / 'backup.zip'
        archive.write_bytes(backup.data)
        backup.close()
        from platform_app.maintenance import restore_backup
        restored = restore_backup(archive, Path(self.temp.name) / 'restored')
        restored_client = login(create_app(restored, testing=True), 'researcher')
        restored_detail = restored_client.get('/api/records/' + rid).json
        self.assertEqual(restored_detail['translations'], changed['translations'])
        exported = self.reader.get('/api/export/content')
        self.assertEqual(exported.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(exported.data)) as z:
            content = json.loads(z.read('content.json'))
            excerpt = next(x for x in content['records'] if x['abstract'] and x.get('preview_excerpt'))
            rendered = z.read(excerpt['path']).decode('utf-8')
        exported.close()
        row = next(x for x in content['records'] if x['id'] == rid)
        self.assertIn('preview_import', row['translations'][0])
        unedited = self.seed['public_batch']['article_ids'][8]
        current_export = next(x for x in content['records'] if x['id'] == unedited)
        self.assertIn('preview_excerpt', current_export)
        self.assertIn('历史机器节选说明', rendered)
        self.assertIn('当前阅读摘要节选', rendered)

    def test_new_translation_and_restoring_initial_content_keep_distinct_history(self):
        rid = self.seed['public_batch']['article_ids'][7]
        detail = self.reader.get('/api/records/' + rid).json
        fresh = call(self.reader, '/api/records/' + rid + '/translations', {'version': detail['version'], 'request_id': 'new-local-task'})['id']
        jobs = self.reader.get('/api/records/' + rid + '/translations').json['items']
        queued = next(j for j in jobs if j['id'] == fresh)
        self.assertEqual(queued['status'], 'queued')
        self.assertNotIn('preview_import', queued)
        initial = self.reader.get('/api/history/record/' + rid).json['items'][-1]
        call(self.reader, '/api/history/' + str(initial['id']) + '/restore', {'version': detail['version']})
        restored = self.reader.get('/api/records/' + rid).json
        old = next(j for j in restored['translations'] if j['id'].startswith('PREVIEW-CEE86-'))
        self.assertIn('preview_import', old)
        self.assertFalse(old['can_adopt'])
        self.assertEqual(restored['translation_origin'], 'machine')


if __name__ == '__main__':
    unittest.main()
