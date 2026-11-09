"""Review regressions at offline HTTP, shared worker, export and restore seams."""
from contextlib import closing, nullcontext
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from platform_app import archive_suggestions as archive, author_suggestions as authors, store
from platform_app.maintenance import create_backup, restore_backup
from platform_app.web import create_app
from tests import test_assisted_intake as intake_fixture, test_bylines as byline_fixture
from tests.fixtures.legacy_record_authors import legacy_native_authors
from tests.test_source_adapters import OJS, CJIR, INTERSECTIONS, GSSC_LIST, feed


class ReviewRegressionTests(unittest.TestCase):
    setUp = intake_fixture.AssistedIntakeTests.setUp
    call = intake_fixture.AssistedIntakeTests.call
    get = byline_fixture.BylineTests.get
    person = byline_fixture.BylineTests.person
    source = byline_fixture.BylineTests.source
    record = byline_fixture.BylineTests.record

    def mock_external(self, page, suggestions):
        fetch = patch('platform_app.intake.fetch_document', side_effect=lambda url, *a, **k:
            {'url': url, 'content_type': 'text/html', 'bytes': page.encode(), 'text': page})
        def reply(db, **kw):
            if kw.get('_tools'):
                goal = json.loads(kw['messages'][1]['content'])['goal']
                kind = 'record' if 'bylines' in goal else 'person' if 'employments' in goal else 'source'
                name, args = ('finish', {'reason': '暂无补充资料。'}) if any(m['role']=='tool' for m in kw['messages']) else ('read', {'target_type': kind, 'id': goal['id']})
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'synthetic-' + name,
                    'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
                # Native turns use the provider protocol rather than the old
                # candidate-only JSON response consumed below.
                from platform_app.ai_gateway import validate_tool_response
                return validate_tool_response(message, kw['_tools']), {'synthetic': True}
            value = json.loads(kw['messages'][-1]['content'])
            return kw['validate']({'suggestions': suggestions(value)}), {'synthetic': True}
        gateway = patch('platform_app.ai_gateway.request_json', side_effect=reply)
        fetch.start(); mock_gateway = gateway.start()
        self.addCleanup(fetch.stop); self.addCleanup(gateway.stop)
        return mock_gateway

    def test_legacy_ojs_pending_unmatched_adopted_keep_projection_export_and_restore(self):
        native = [{'@type': 'Person', 'name': 'Ada Example', 'sameAs': 'https://orcid.org/0000-0002-1825-0097'},
                  {'@type': 'Person', 'name': 'Bea Example'}]
        page = OJS.format(root=CJIR).replace('</head>', '<script type="application/ld+json">' +
            json.dumps({'@type': 'ScholarlyArticle', 'headline': 'Synthetic education study', 'author': native}) + '</script></head>')
        self.mock_external(page, lambda value: value['author_facts'])
        records = []
        save_document = authors.save_document
        with patch.object(authors, 'native_authors', side_effect=lambda document, base, *args: legacy_native_authors(document, base)), \
             patch.object(authors, 'save_document', side_effect=lambda db, job, document, method:
                 save_document(db, job, document, 'article-authors-v1' if method == 'article-authors-v2' else method)):
            for index in range(2):
                rid = self.record(title='Synthetic education study', authors='Ada Example; Bea Example', url=CJIR+'/article/view/'+str(index+1))
                records.append(rid)
                self.assertEqual(self.call('/api/archive-jobs', {'record_ids': [rid], 'request_id': 'legacy'}).status_code, 201)
                self.assertEqual(archive.run_pending(self.app.config['DATA_DIR'])['completed'], 1)
            first = self.get('/api/records/'+records[0]+'/suggestions')
            pending = next(c for c in first['candidates'] if c['status'] == 'pending')
            self.assertEqual(self.call('/api/records/'+records[0]+'/suggestions/decide',
                {'version': first['version'], 'byline_version': first['byline_version'], 'adopt': [pending['id']]}).status_code, 200)
            # Build the genuinely unversioned input shape, without touching facts or decisions.
            with closing(store.connect(Path(self.app.config['DATA_DIR'])/'platform.sqlite3')) as db, db:
                for row in db.execute("SELECT * FROM archive_jobs WHERE target_type='record'").fetchall():
                    value = json.loads(row['input_json']); value.pop('extraction_version', None)
                    digest = archive.digest(value)
                    db.execute('UPDATE archive_jobs SET input_json=?,input_hash=? WHERE id=?', (json.dumps(value), digest, row['id']))
                    db.execute('UPDATE archive_candidates SET input_hash=? WHERE job_id=?', (digest, row['id']))
            before = [self.get('/api/records/'+rid+'/suggestions') for rid in records]
            backup = create_backup(self.app.config['DATA_DIR'])
        after = [self.get('/api/records/'+rid+'/suggestions') for rid in records]
        self.assertEqual(after, before)
        self.assertEqual({c['status'] for s in after for c in s['candidates']}, {'pending', 'unmatched', 'adopted'})
        response = self.clients['researcher'].get('/api/export/content')
        self.assertEqual(response.status_code, 200, response.json)
        with zipfile.ZipFile(io.BytesIO(response.data)) as bundle:
            payload = json.loads(bundle.read('content.json'))
        response.close()
        targets = [t for t in payload['archive_suggestions']['targets'] if t['target_id'] in records]
        self.assertEqual({c['status'] for t in targets for c in t['candidates']}, {'pending', 'unmatched', 'adopted'})
        restored = restore_backup(backup, Path(self.temp.name)/'restored')
        client = create_app(restored, testing=True, embedded_worker=False).test_client()
        csrf = client.get('/api/session').json['csrf']
        self.assertEqual(client.post('/api/login', json={'username': 'researcher', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf}).status_code, 200)
        self.assertEqual([client.get('/api/records/'+rid+'/suggestions').json for rid in records], before)

    def test_new_ojs_evidence_uses_versioned_bound_author_objects(self):
        self.mock_external(OJS.format(root=CJIR), lambda value: value['author_facts'])
        rid = self.record(title='Synthetic education study', authors='Ada Example; Bea Example', url=CJIR+'/article/view/1')
        self.assertEqual(self.call('/api/archive-jobs', {'record_ids': [rid], 'request_id': 'new'}).status_code, 201)
        archive.run_pending(self.app.config['DATA_DIR'])
        state = self.get('/api/records/'+rid+'/suggestions')
        self.assertEqual([c['status'] for c in state['candidates']], ['pending', 'pending'])
        self.assertEqual(state['candidates'][0]['value']['orcid'], '0000-0002-4878-9755')
        self.assertEqual(state['candidates'][0]['value']['affiliations'], ['Synthetic University'])
        with closing(store.connect(Path(self.app.config['DATA_DIR'])/'platform.sqlite3')) as db:
            value = json.loads(db.execute('SELECT input_json FROM archive_jobs').fetchone()[0])
            self.assertEqual(value['extraction_version'], 'record-authors-v2')
            self.assertEqual(db.execute('SELECT method FROM archive_evidence ORDER BY rowid LIMIT 1').fetchone()[0], 'article-authors-v2')
        restore_backup(create_backup(self.app.config['DATA_DIR']), Path(self.temp.name)/'new-restored')

    def test_valueless_profile_attributes_finish_and_shared_portable_worker_continues(self):
        from portable.worker import PortableWorker
        from portable.public_collection import LocalPublicSettings
        from platform_app.ingestion import run_worker
        page = '<div class id><h1>Ada Example</h1><article class><p>' + ('A complete synthetic career biography. ' * 5) + '</p><a href>Work</a></article></div>'
        gateway = self.mock_external(page, lambda value: [])
        ids = [self.person('Ada Example') for _ in range(2)]
        for index, pid in enumerate(ids):
            self.assertEqual(self.call('/api/people/'+pid+'/profile-suggestions', {'version': 1,
                'url': 'https://profiles.example/ada', 'identity_confirmation': True, 'request_id': str(index)}).status_code, 201)
        state_dir = Path(self.temp.name)/'worker-state'; state_dir.mkdir()
        # This cross-platform queue test owns all its files; native Windows
        # per-user permission storage belongs to the separate portable contract.
        public = LocalPublicSettings(Path(self.temp.name)/'copy', storage_root=Path(self.temp.name)/'public-settings')
        self.assertFalse(public.status()['enabled'])
        with patch('portable.public_collection.user_storage', side_effect=AssertionError('Unexpected native user storage access')):
            worker = PortableWorker(self.app.config['DATA_DIR'], state_dir,
                SimpleNamespace(status=lambda: {'enabled': True}), threading.Event(), public_settings=public)
        worker.worker_state = 'running'
        worker.ownership = nullcontext(); worker.ownership.__enter__()
        with patch('platform_app.ingestion.run_worker', side_effect=lambda data, **kw: run_worker(data, once=True, **kw)):
            worker.run()
        self.assertEqual(worker.status()['worker_state'], 'stopped', worker.status())
        self.assertFalse(worker.status()['public_collection']['enabled'])
        states = [self.get('/api/people/'+pid+'/profile-suggestions') for pid in ids]
        self.assertEqual([s['jobs'][0]['status'] for s in states], ['empty', 'empty'])
        self.assertEqual(sum(not call.kwargs.get('_tools') for call in gateway.call_args_list), 2)
        maintenance = self.get('/api/maintenance/jobs')['items']
        self.assertEqual(sum(job['status'] == 'completed' for job in maintenance), 1)
        self.assertTrue(all(not job['steps'] for job in maintenance if job['status'] == 'queued'))
        self.assertTrue(all('complete synthetic career' in s['materials'][0]['biography'] for s in states))

    def test_profile_comparison_includes_manual_employment_and_stale_current_value(self):
        pid = self.person('Ada Example'); sid = self.source('Synthetic University')
        path = '/api/people/'+pid
        def save(role):
            current = self.get(path+'/employments')
            return self.call(path+'/employments', {'version': current['version'], 'change_note': 'Synthetic manual revision',
                'items': [{'institution_id': sid, 'role': role, 'start_date': '', 'end_date': '', 'evidence': 'Synthetic manual career source'}]}, method='PUT')
        self.assertEqual(save('Lecturer').status_code, 200)
        original = self.get(path+'/employments')
        page = '<h1>Ada Example</h1><article><p>Ada Example is a researcher at Synthetic University.</p><p>Her previous career dates remain unknown in this synthetic biography.</p></article>'
        self.mock_external(page, lambda value: [{'field': 'employment', **value['employment_facts'][0]}])
        self.assertEqual(self.call(path+'/profile-suggestions', {'version': 1, 'url': 'https://profiles.example/ada',
            'identity_confirmation': True, 'request_id': 'manual-compare'}).status_code, 201)
        archive.run_pending(self.app.config['DATA_DIR'])
        state = self.get(path+'/profile-suggestions')
        self.assertEqual([r['role'] for r in state['current']['employment']], ['Lecturer'])
        self.assertEqual(state['employment_version'], original['version'])
        candidate = state['candidates'][0]
        self.assertEqual([r['role'] for r in candidate['before']], ['Lecturer'])
        self.assertEqual(save('Professor').status_code, 200)
        changed = self.get(path+'/profile-suggestions')
        self.assertTrue(changed['candidates'][0]['stale'])
        self.assertEqual([r['role'] for r in changed['current']['employment']], ['Professor'])
        self.assertEqual([r['role'] for r in changed['candidates'][0]['before']], ['Lecturer'])
        self.assertEqual(self.call(path+'/profile-suggestions/decide', {'version': changed['version'], 'adopt': [candidate['id']]}).status_code, 409)
        self.assertEqual(self.get(path+'/employments')['items'][0]['role'], 'Professor')

    def test_discovery_http_describes_actual_entry_and_date_basis(self):
        cases = [('LIIA Opinions', 'institution', 'https://liia.lv/', 'rss', 'published',
                  '<rss><channel><item><title>Synthetic item</title><link>https://liia.lv/en/opinions/synthetic</link><pubDate>Thu, 22 Oct 2026 00:00:00 +0000</pubDate></item></channel></rss>'),
                 ('GSSC Publications', 'institution', 'https://www.gssc.lt/', 'html', 'published', GSSC_LIST),
                 ('CJIR RSS', 'journal', CJIR, 'rss', 'rss_online', feed(CJIR)),
                 ('Intersections RSS', 'journal', INTERSECTIONS, 'rss', 'rss_online', feed(INTERSECTIONS))]
        for name, kind, website, entry_type, date_basis, raw in cases:
            with self.subTest(source=name):
                result = self.call('/api/sources', {'name': name, 'kind': kind, 'website': website})
                self.assertEqual(result.status_code, 201, result.json)
                def fetch(url, *a, **k):
                    return {'url': url, 'content_type': 'text/html' if entry_type == 'html' else 'application/xml', 'bytes': raw.encode()}
                with patch('platform_app.intake.fetch_document', side_effect=fetch), patch('platform_app.store.now', return_value='2026-11-03T00:00:00+00:00'):
                    response = self.call('/api/sources/'+result.json['id']+'/discovery')
                self.assertEqual(response.status_code, 200, response.json)
                queue = response.json
                self.assertEqual((queue['source_name'], queue['entry_type'], queue['date_basis']), (name, entry_type, date_basis))
                self.assertEqual(queue['items'][0]['fields']['published_on'], '2026-10-21' if entry_type == 'html' else '2026-10-22')
                if date_basis == 'rss_online':
                    self.assertIn('不替代原文发表日期、引用年份或首次入库时间', queue['window_role'])


if __name__ == '__main__':
    unittest.main()
