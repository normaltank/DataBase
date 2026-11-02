"""Source suggestions at authenticated HTTP seams, with synthetic network/provider."""
import json
import hashlib
import io
import os
import ssl
import sqlite3
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from tests import test_workflow as workflow_fixture
from tests.synthetic_ai import ENV


class Provider(BaseHTTPRequestHandler):
    transform = None
    before_reply = None
    usage = True
    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        material = json.loads(value['messages'][-1]['content'])
        evidence = material['documents'][0]
        output = {'suggestions': [{'field': 'location', 'value': 'Riga', 'evidence_id': evidence['id'],
                                   'quote': 'Our office is in Riga, Latvia.'}]}
        if type(self).transform:
            output = type(self).transform(output, material)
        if type(self).before_reply:
            type(self).before_reply()
        response = {'model': 'deepseek-flash', 'id': 'synthetic-source',
                         'usage': {'prompt_tokens': 23, 'completion_tokens': 7, 'total_tokens': 30},
                         'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(output)}}]}
        if not type(self).usage: response.pop('usage')
        raw = json.dumps(response).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args): pass


class ArchiveSuggestionsTests(unittest.TestCase):
    setUp = workflow_fixture.WorkflowTests.setUp
    login = workflow_fixture.WorkflowTests.login
    call = workflow_fixture.WorkflowTests.call
    source = workflow_fixture.WorkflowTests.source

    def synthetic(self, fetch=True):
        Provider.transform = Provider.before_reply = None
        Provider.usage = True
        server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        env = {**ENV, 'DEEPSEEK_API_KEY': 'synthetic-secret',
               'DEEPSEEK_BASE_URL': f'https://127.0.0.1:{server.server_port}'}
        self.document = {'url': 'https://source.example/', 'content_type': 'text/html',
                    'text': '<h1>Synthetic Institute</h1><p>Our office is in Riga, Latvia.</p>',
                    'bytes': b'<h1>Synthetic Institute</h1><p>Our office is in Riga, Latvia.</p>'}
        self.fetcher = None
        contexts = [patch.dict(os.environ, env), patch.object(ssl.SSLContext, 'wrap_socket', lambda c, s, *a, **k: s)]
        if fetch:
            contexts.append(patch('platform_app.intake.fetch_document', side_effect=lambda url, *a, **k: self.fetcher(url) if self.fetcher else self.document))
        for context in contexts:
            context.start()
            self.addCleanup(context.stop)
        self.assertEqual(self.call('/api/admin/ai/config', {'cap': '1', 'currency': 'USD'}, user='admin').status_code, 200)

    def queue_run(self, sid, request_id='one'):
        queued = self.call('/api/archive-jobs', {'source_ids': [sid], 'request_id': request_id})
        self.assertEqual(queued.status_code, 201, queued.json)
        self.assertEqual(self.call('/api/admin/archive-jobs/run', user='admin').status_code, 200)
        return self.clients['researcher'].get(f'/api/sources/{sid}/suggestions').json

    def test_queue_evidence_select_adopt_preserves_review_boundary(self):
        self.synthetic()
        sid = self.source('Synthetic Institute', kind='institution', website='https://source.example/')
        queued = self.call('/api/archive-jobs', {'source_ids': [sid], 'request_id': 'one'})
        self.assertEqual(queued.status_code, 201, queued.json)
        self.assertEqual(self.call('/api/admin/archive-jobs/run', user='admin').status_code, 200)
        detail = self.clients['researcher'].get(f'/api/sources/{sid}/suggestions')
        self.assertEqual(detail.status_code, 200, detail.json)
        candidate = detail.json['candidates'][0]
        self.assertEqual(candidate['before'], '')
        self.assertEqual(candidate['value'], 'Riga')
        self.assertEqual(candidate['evidence']['quote'], 'Our office is in Riga, Latvia.')
        adopted = self.call(f'/api/sources/{sid}/suggestions/decide',
                            {'version': 1, 'adopt': [candidate['id']], 'reject': []}, user='colleague')
        self.assertEqual(adopted.status_code, 200, adopted.json)
        source = self.clients['researcher'].get('/api/sources/' + sid).json
        self.assertEqual(source['location'], 'Riga')
        self.assertEqual(source['status'], 'pending')
        self.assertEqual(source['scope_status'], 'candidate')
        self.assertFalse(source['automatic_collection']['enabled'])
        current = self.clients['researcher'].get(f'/api/sources/{sid}/suggestions').json
        self.assertEqual(current['candidates'][0]['status'], 'adopted')
        self.assertEqual(current['events'][-1]['actor_id'], 'colleague')
        costs = self.clients['admin'].get('/api/admin/ai').json
        self.assertEqual(costs['charged_units'], 26)
        self.assertTrue(any(a['scope'] == 'source:' + sid for a in costs['attempts']))

    def test_reject_same_evidence_not_repeated_and_new_material_is_new_version(self):
        self.synthetic()
        sid = self.source('Synthetic Institute', kind='institution', website='https://source.example/')
        first = self.queue_run(sid)
        candidate = first['candidates'][0]
        self.assertEqual(self.call(f'/api/sources/{sid}/suggestions/decide', {'reject': [candidate['id']]}).status_code, 200)
        repeated = self.queue_run(sid, 'two')
        self.assertEqual(len(repeated['candidates']), 1)
        self.assertEqual(repeated['candidates'][0]['status'], 'rejected')
        self.document = {**self.document, 'text': self.document['text'] + '<p>New official page version.</p>',
                         'bytes': self.document['bytes'] + b'<p>New official page version.</p>'}
        updated = self.queue_run(sid, 'three')
        self.assertEqual(len(updated['candidates']), 2)
        self.assertEqual([c['status'] for c in updated['candidates']], ['pending', 'rejected'])

    def test_human_edit_conflict_keeps_candidate_and_selection_does_not_overwrite(self):
        self.synthetic()
        sid = self.source('Synthetic Institute', kind='institution', website='https://source.example/')
        candidate = self.queue_run(sid)['candidates'][0]
        self.assertEqual(self.call('/api/sources/' + sid, {'version': 1, 'location': 'Human location'}, method='PUT').status_code, 200)
        response = self.call(f'/api/sources/{sid}/suggestions/decide', {'version': 2, 'adopt': [candidate['id']]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.clients['researcher'].get('/api/sources/' + sid).json['location'], 'Human location')
        state = self.clients['researcher'].get(f'/api/sources/{sid}/suggestions').json
        self.assertEqual(state['candidates'][0]['status'], 'pending')
        self.assertTrue(state['candidates'][0]['stale'])

    def test_cross_target_and_invented_quote_cannot_change_formal_source(self):
        self.synthetic()
        sid = self.source('Synthetic Institute', kind='institution', website='https://source.example/')
        other = self.source('Other Institute', kind='institution', website='https://other.example/')
        candidate = self.queue_run(sid)['candidates'][0]
        response = self.call(f'/api/sources/{other}/suggestions/decide', {'version': 1, 'adopt': [candidate['id']]})
        self.assertEqual(response.status_code, 404)
        Provider.transform = lambda output, material: {'suggestions': [{**output['suggestions'][0], 'quote': 'A fabricated quote that is not in this website.'}]}
        state = self.queue_run(other, 'hostile')
        self.assertEqual(state['candidates'], [])
        self.assertEqual(state['jobs'][0]['status'], 'failed')
        self.assertEqual(self.clients['researcher'].get('/api/sources/' + other).json['location'], '')

    def test_readable_export_and_new_directory_restore_keep_raw_evidence_and_actor(self):
        self.synthetic()
        sid = self.source('Synthetic Institute', kind='institution', website='https://source.example/')
        candidate = self.queue_run(sid)['candidates'][0]
        self.call(f'/api/sources/{sid}/suggestions/decide', {'version': 1, 'adopt': [candidate['id']]}, user='colleague')
        exported = self.clients['researcher'].get(f'/api/sources/{sid}/suggestions/export')
        self.assertEqual(exported.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
            evidence = archive.read('evidence/' + candidate['evidence']['id'] + '.bin')
            self.assertEqual(evidence, self.document['bytes'])
            payload = json.loads(archive.read('suggestions.json'))
            self.assertEqual(payload['candidates'][0]['decided_by'], 'colleague')
            self.assertIn('Riga', archive.read('index.html').decode())
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        backup = self.call('/api/backup', user='admin')
        path = self.data_dir.parent / 'backup.zip'
        path.write_bytes(backup.data)
        backup.close()
        restored = self.data_dir.parent / 'restored'
        restore_backup(path, restored)
        app = create_app(restored, testing=True)
        client = self.login('colleague', app)
        state = client.get(f'/api/sources/{sid}/suggestions').json
        self.assertEqual(state['candidates'][0]['evidence']['quote'], 'Our office is in Riga, Latvia.')
        self.assertEqual(state['candidates'][0]['decided_by'], 'colleague')

    def test_admin_budget_lists_source_tasks_without_article_foreign_key(self):
        sid = self.source('Synthetic Institute', kind='institution', website='https://source.example/')
        response = self.call('/api/archive-jobs', {'source_ids': [sid], 'request_id': 'queued'})
        jid = response.json['items'][0]['id']
        summary = self.clients['admin'].get('/api/admin/ai').json
        source_task = next((t for t in summary['tasks'] if t['id'] == jid), None)
        self.assertIsNotNone(source_task)
        self.assertEqual(source_task['target_type'], 'source')
        self.assertEqual(source_task['target_id'], sid)

    def test_unregistered_publisher_keeps_visible_evidence_and_can_match_after_registration(self):
        self.synthetic()
        raw = b'<h1>Synthetic Journal</h1><p>Published by Synthetic Publisher.</p>'
        self.document = {**self.document, 'text': raw.decode(), 'bytes': raw}
        Provider.transform = lambda output, material: {'suggestions': [{'field': 'publisher',
            'value': {'target_name': 'Synthetic Publisher'}, 'evidence_id': material['documents'][0]['id'],
            'quote': 'Published by Synthetic Publisher.'}]}
        sid = self.source('Synthetic Journal', kind='journal', website='https://source.example/')
        first = self.queue_run(sid)
        self.assertEqual(first['candidates'][0]['status'], 'unmatched')
        self.assertEqual(first['candidates'][0]['evidence']['quote'], 'Published by Synthetic Publisher.')
        self.assertEqual(self.call(f'/api/sources/{sid}/suggestions/decide', {'version': 1, 'adopt': [first['candidates'][0]['id']]}).status_code, 409)
        before_cost = self.clients['admin'].get('/api/admin/ai').json['charged_units']
        self.source('Unrelated Institution', kind='institution')
        unrelated = self.queue_run(sid, 'unrelated-change')
        self.assertEqual(len(unrelated['candidates']), 1)
        self.assertEqual(self.clients['admin'].get('/api/admin/ai').json['charged_units'], before_cost)
        publisher = self.source('Synthetic Publisher', kind='institution')
        second = self.queue_run(sid, 'after-registration')
        self.assertEqual(second['candidates'][0]['status'], 'pending')
        self.assertEqual(second['candidates'][0]['input_hash'], first['candidates'][0]['input_hash'])
        self.assertEqual(self.clients['admin'].get('/api/admin/ai').json['charged_units'], before_cost)
        adopted = self.call(f'/api/sources/{sid}/suggestions/decide', {'version': 1, 'adopt': [second['candidates'][0]['id']]})
        self.assertEqual(adopted.status_code, 200, adopted.json)
        source = self.clients['researcher'].get('/api/sources/' + sid).json
        self.assertEqual(source['publisher_id'], publisher)
        self.assertEqual(source['host_id'], '')

    def test_auto_discovers_bounded_same_site_material_through_real_http_parser(self):
        self.synthetic(fetch=False)
        import socket
        from tests.test_assisted_intake import PublicSocket
        real_connect, real_resolve = socket.create_connection, socket.getaddrinfo
        home = (b'<h1>Synthetic Institute</h1><p>Our office is in Riga, Latvia.</p>'
                b'<a href="/about">About</a><a href="/contact">Contact</a><a href="/editorial">Editorial</a>'
                b'<a href="/about-extra">Extra</a><a href="http://foreign.example/about">Foreign</a>')
        def resolve(host, port, *args, **kwargs):
            return [(2, 1, 6, '', ('93.184.216.34', port))] if host == 'source.example' else real_resolve(host, port, *args, **kwargs)
        def connection(address, *args, **kwargs):
            return PublicSocket(home) if address[0] == '93.184.216.34' else real_connect(address, *args, **kwargs)
        sid = self.source('Synthetic Institute', kind='institution', website='http://source.example/')
        with patch('socket.getaddrinfo', side_effect=resolve), patch('socket.create_connection', side_effect=connection):
            state = self.queue_run(sid)
        self.assertEqual(state['jobs'][0]['status'], 'ready')
        exported = self.clients['researcher'].get(f'/api/sources/{sid}/suggestions/export')
        with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
            materials = json.loads(archive.read('materials.json'))
            self.assertEqual({m['url'] for m in materials}, {'http://source.example/', 'http://source.example/about',
                                                          'http://source.example/contact', 'http://source.example/editorial'})
            self.assertTrue(all(m['raw_base64'] for m in materials))

    def test_batch_idempotence_missing_website_cancellation_and_current_permissions(self):
        first, second = self.source('Missing Website', kind='institution'), self.source('Other Source', kind='institution')
        data = {'source_ids': [first, second], 'request_id': 'batch'}
        self.assertEqual(self.call('/api/archive-jobs', data).status_code, 403)
        queued = self.call('/api/archive-jobs', data, user='admin')
        repeated = self.call('/api/archive-jobs', data, user='admin')
        self.assertEqual(queued.json, repeated.json)
        cancelled = queued.json['items'][1]['id']
        self.assertEqual(self.call('/api/archive-jobs/' + cancelled + '/cancel', user='colleague').status_code, 403)
        self.assertEqual(self.call('/api/archive-jobs/' + cancelled + '/cancel', user='admin').status_code, 200)
        self.call('/api/admin/archive-jobs/run', user='admin')
        state = self.clients['colleague'].get(f'/api/sources/{first}/suggestions').json
        self.assertEqual(state['jobs'][0]['status'], 'failed')
        self.assertIn('官网', state['jobs'][0]['reason'])
        self.assertEqual(self.clients['colleague'].get(f'/api/sources/{second}/suggestions').json['jobs'][0]['status'], 'cancelled')
        self.assertEqual(self.call('/api/archive-jobs', {'source_ids': [{}], 'request_id': 'bad'}).status_code, 400)

    def test_permission_revoked_during_provider_cannot_create_candidate_or_clear_unknown_cost(self):
        self.synthetic()
        sid = self.source('Synthetic Institute', kind='institution', website='https://source.example/')
        Provider.before_reply = lambda: self.call('/api/members/researcher', {'active': False}, method='PUT', user='admin')
        self.call('/api/archive-jobs', {'source_ids': [sid], 'request_id': 'before-revoke'})
        self.call('/api/admin/archive-jobs/run', user='admin')
        state = self.clients['colleague'].get(f'/api/sources/{sid}/suggestions').json
        self.assertEqual(state['jobs'][0]['status'], 'invalidated')
        self.assertEqual(state['candidates'], [])
        self.assertEqual(self.clients['researcher'].get(f'/api/sources/{sid}/suggestions/export').status_code, 401)
        summary = self.clients['admin'].get('/api/admin/ai').json
        self.assertGreater(summary['held_units'], 0)
        self.assertEqual(summary['attempts'][0]['status'], 'unknown')

    def test_two_candidates_same_field_are_atomic_and_concurrent_adoption_is_single_use(self):
        self.synthetic()
        Provider.transform = lambda output, material: {'suggestions': output['suggestions'] + [{**output['suggestions'][0], 'value': 'Rīga'}]}
        sid = self.source('Synthetic Institute', kind='institution', website='https://source.example/')
        candidates = self.queue_run(sid)['candidates']
        conflict = self.call(f'/api/sources/{sid}/suggestions/decide', {'version': 1, 'adopt': [c['id'] for c in candidates]})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.clients['researcher'].get('/api/sources/' + sid).json['location'], '')
        barrier, outcomes = threading.Barrier(2), []
        def adopt(name):
            client = self.login(name)
            token = client.get('/api/session').json['csrf']
            barrier.wait()
            outcomes.append(client.post(f'/api/sources/{sid}/suggestions/decide', json={'version': 1, 'adopt': [candidates[0]['id']]}, headers={'X-CSRF-Token': token}).status_code)
        threads = [threading.Thread(target=adopt, args=(name,)) for name in ['researcher', 'colleague']]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertEqual(sorted(outcomes), [200, 409])

    def test_restore_rejects_cross_target_corrupt_raw_and_missing_candidate_history(self):
        self.synthetic()
        sid = self.source('Synthetic Institute', kind='institution', website='https://source.example/')
        other = self.source('Other Institute', kind='institution')
        candidate = self.queue_run(sid)['candidates'][0]
        self.call(f'/api/sources/{sid}/suggestions/decide', {'reject': [candidate['id']]})
        response = self.call('/api/backup', user='admin')
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            original = {name: archive.read(name) for name in archive.namelist()}
        response.close()
        cases = [
            ('UPDATE archive_candidates SET target_id=?', (other,)),
            ('UPDATE archive_evidence SET raw=?', (b'Corrupt independently expected response',)),
            ('DELETE FROM archive_events WHERE action=\'rejected\'', ()),
            ('DROP TABLE archive_candidates', ()),
            ('UPDATE archive_evidence SET text=?', ('Forged readable evidence not derived from original response.',)),
        ]
        from platform_app.maintenance import restore_backup
        for index, (sql, params) in enumerate(cases):
            with self.subTest(sql=sql):
                files = dict(original)
                database = self.data_dir.parent / ('corrupt-' + str(index) + '.sqlite3')
                database.write_bytes(files['platform.sqlite3'])
                connection = sqlite3.connect(database)
                with connection: connection.execute(sql, params)
                connection.close()
                files['platform.sqlite3'] = database.read_bytes()
                manifest = json.loads(files['manifest.json'])
                manifest['files']['platform.sqlite3'] = {'bytes': len(files['platform.sqlite3']), 'sha256': hashlib.sha256(files['platform.sqlite3']).hexdigest()}
                files['manifest.json'] = json.dumps(manifest).encode()
                path = self.data_dir.parent / ('corrupt-' + str(index) + '.zip')
                with zipfile.ZipFile(path, 'w') as archive:
                    for name, raw in files.items(): archive.writestr(name, raw)
                target = self.data_dir.parent / ('must-not-restore-' + str(index))
                with self.assertRaisesRegex(ValueError, '档案建议'):
                    restore_backup(path, target)
                self.assertFalse(target.exists())

    def test_unknown_source_cost_survives_restart_and_restore_and_cannot_be_retried(self):
        self.synthetic()
        Provider.usage = False
        sid = self.source('Synthetic Institute', kind='institution', website='https://source.example/')
        state = self.queue_run(sid)
        self.assertEqual(state['jobs'][0]['status'], 'paused')
        self.assertEqual(state['candidates'], [])
        summary = self.clients['admin'].get('/api/admin/ai').json
        held = summary['held_units']
        self.assertGreater(held, 0)
        jid = state['jobs'][0]['id']
        self.assertEqual(self.call('/api/admin/archive-jobs/' + jid + '/retry', {'basis': 'Synthetic administrator examined failure and billing.'}, user='admin').status_code, 409)
        backup = self.call('/api/backup', user='admin')
        path = self.data_dir.parent / 'unknown-cost.zip'
        path.write_bytes(backup.data)
        backup.close()
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        target = self.data_dir.parent / 'unknown-restored'
        restore_backup(path, target)
        app = create_app(target, testing=True)
        admin = self.login('admin', app)
        restored = admin.get('/api/admin/ai').json
        self.assertEqual(restored['held_units'], held)
        csrf = admin.get('/api/session').json['csrf']
        admin.post('/api/admin/archive-jobs/run', json={}, headers={'X-CSRF-Token': csrf})
        self.assertEqual(len(admin.get('/api/admin/ai').json['attempts']), 1)

    def test_cli_leased_queue_recovers_without_reader_refresh_or_real_provider(self):
        import subprocess
        import sys
        from platform_app.store import connect
        sid = self.source('Missing Website', kind='institution')
        jid = self.call('/api/archive-jobs', {'source_ids': [sid], 'request_id': 'cli'}).json['items'][0]['id']
        db = connect(self.data_dir / 'platform.sqlite3')
        with db:
            db.execute("UPDATE archive_jobs SET status='running',lease_token='old-worker',lease_until='2099-01-01T00:00:00+00:00' WHERE id=?", (jid,))
        command = [sys.executable, '-B', '-m', 'platform_app.ingestion', '--data-dir', str(self.data_dir), '--once']
        first = subprocess.run(command, capture_output=True, text=True, timeout=20, env={**os.environ, 'DEEPSEEK_API_KEY': ''})
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)['archive_suggestions']['tasks'], 0)
        with db: db.execute("UPDATE archive_jobs SET lease_until='2020-01-01T00:00:00+00:00' WHERE id=?", (jid,))
        db.close()
        second = subprocess.run(command, capture_output=True, text=True, timeout=20, env={**os.environ, 'DEEPSEEK_API_KEY': ''})
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)['archive_suggestions']['tasks'], 1)
        self.assertEqual(self.clients['colleague'].get(f'/api/sources/{sid}/suggestions').json['jobs'][0]['status'], 'failed')

    def test_actual_crossref_publisher_evidence_cannot_become_host_or_international_mission(self):
        self.synthetic()
        raw = (Path(__file__).parent / 'fixtures/archive_suggestions/crossref-0020-8833.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), '0968869804f3e19e4a2cefed5f8208fda12cbd22949b51c636b6b60df4493d30')
        self.fetcher = lambda url: {'url': url, 'content_type': 'application/json', 'bytes': raw, 'text': raw.decode()} if url.startswith('https://api.crossref.org/journals/') else self.document
        publisher = self.source('Oxford University Press', kind='institution')
        quote = '"publisher":"Oxford University Press"'
        for field, value in [('host', {'target_name': 'Oxford University Press'}), ('international_status', 'yes')]:
            with self.subTest(field=field):
                Provider.transform = lambda output, material: {'suggestions': [{'field': field, 'value': value,
                    'evidence_id': next(d['id'] for d in material['documents'] if 'api.crossref.org' in d['url']), 'quote': quote}]}
                sid = self.source('Crossref negative ' + field, kind='journal', website='https://journal.example/' + field, issn='0020-8833')
                state = self.queue_run(sid, field)
                if state['candidates']:
                    decision = self.call(f'/api/sources/{sid}/suggestions/decide', {'version': 1, 'adopt': [state['candidates'][0]['id']]})
                    self.assertEqual(decision.status_code, 409, 'A real publisher quote must never authorize this role.')
                else:
                    self.assertEqual(state['jobs'][0]['status'], 'failed')
                saved = self.clients['researcher'].get('/api/sources/' + sid).json
                self.assertEqual(saved['host_id'], '')
                self.assertEqual(saved['international_status'], 'unknown')
        Provider.transform = lambda output, material: {'suggestions': [
            {'field': 'publisher', 'value': {'target_name': 'Oxford University Press'},
             'evidence_id': next(d['id'] for d in material['documents'] if 'api.crossref.org' in d['url']), 'quote': quote},
            {'field': 'issn', 'value': '0020-8833; 1468-2478',
             'evidence_id': next(d['id'] for d in material['documents'] if 'api.crossref.org' in d['url']), 'quote': '"ISSN":["0020-8833","1468-2478"]'}]}
        sid = self.source('Crossref positive', kind='journal', website='https://journal.example/positive', issn='0020-8833')
        state = self.queue_run(sid, 'positive')
        decision = self.call(f'/api/sources/{sid}/suggestions/decide', {'version': 1, 'adopt': [c['id'] for c in state['candidates']]})
        self.assertEqual(decision.status_code, 200, decision.json)
        saved = self.clients['researcher'].get('/api/sources/' + sid).json
        self.assertEqual(saved['publisher_id'], publisher)
        self.assertEqual(saved['issn'], '0020-8833; 1468-2478')
        self.assertEqual(saved['host_id'], '')

    def test_country_alias_change_is_not_a_correction_but_missing_basis_can_be_adopted(self):
        self.synthetic()
        Provider.transform = lambda output, material: {'suggestions': [{'field': 'country', 'value': 'LATVIA',
            'evidence_id': material['documents'][0]['id'], 'quote': 'Our office is in Riga, Latvia.'}]}
        supported = self.source('Country already supported', kind='institution', website='https://source.example/supported',
                                country='拉脱维亚', country_evidence='Existing human country basis')
        self.assertEqual(self.queue_run(supported)['candidates'], [])
        missing = self.source('Country missing evidence', kind='institution', website='https://source.example/missing', country='Latvia')
        state = self.queue_run(missing, 'evidence-only')
        candidate = state['candidates'][0]
        self.assertTrue(candidate['evidence_only'])
        self.assertEqual(self.call(f'/api/sources/{missing}/suggestions/decide', {'version': 1, 'adopt': [candidate['id']]}).status_code, 200)
        current = self.clients['researcher'].get('/api/sources/' + missing).json
        self.assertEqual(current['country'], 'Latvia')
        self.assertIn('Our office is in Riga, Latvia.', current['country_evidence'])

    def test_actual_liia_developer_and_cookie_partners_cannot_be_adopted_as_cooperation(self):
        self.synthetic()
        raw = (Path(__file__).parent / 'fixtures/archive_suggestions/liia-en-20261102.html').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), '0c2cddf3bb3cc0eda089d759ad8c52cf41dd66d01c40dce1ce77154a31645f18')
        self.document = {'url': 'https://www.liia.lv/en', 'content_type': 'text/html',
                         'text': raw.decode(), 'bytes': raw}
        developer = self.source('GOLD.LV', kind='institution')
        sid = self.source('Latvian Institute of International Affairs', kind='institution', website='https://www.liia.lv/en')
        quotes = []
        def response(output, material):
            document = material['documents'][0]
            quote = document['text'][document['text'].index('© 2026'):]
            quotes.append(quote)
            return {'suggestions': [{'field': 'relationships', 'value': {'target_name': 'GOLD.LV', 'type': 'cooperates_with'},
                                     'evidence_id': document['id'], 'quote': quote}]}
        Provider.transform = response
        state = self.queue_run(sid)
        self.assertEqual(len(quotes), 1)
        self.assertEqual(len(quotes[0]), 651)
        self.assertEqual(hashlib.sha256(quotes[0].encode()).hexdigest(), 'fe551baca6df57c4a92059138c8ed90616eedde52ecec74ad78f4c8535eb3208')
        # Exercise adoption when the buggy version creates a candidate: directory
        # matching alone must not authorize a role absent from the original material.
        decisions = [self.call(f'/api/sources/{sid}/suggestions/decide', {'version': 1, 'adopt': [c['id']]})
                     for c in state['candidates']]
        self.assertFalse(any(d.status_code == 200 for d in decisions), 'Website development and generic cookie partners do not establish cooperation.')
        saved = self.clients['researcher'].get('/api/sources/' + sid).json
        self.assertFalse(any(r['target_id'] == developer for r in saved['relationships']))
        self.assertEqual(state['jobs'][0]['status'], 'failed')
        self.assertEqual(state['candidates'], [])

    def test_actual_liia_cookie_identity_does_not_establish_think_tank_type(self):
        self.synthetic()
        raw = (Path(__file__).parent / 'fixtures/archive_suggestions/liia-en-20261102.html').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), '0c2cddf3bb3cc0eda089d759ad8c52cf41dd66d01c40dce1ce77154a31645f18')
        self.document = {'url': 'https://www.liia.lv/en', 'content_type': 'text/html', 'text': raw.decode(), 'bytes': raw}
        sid = self.source('Latvian Institute of International Affairs', kind='institution', website='https://www.liia.lv/en')
        quotes = []
        def response(output, material):
            document = material['documents'][0]
            quote = document['text'][document['text'].index('© 2026'):]
            quotes.append(quote)
            return {'suggestions': [{'field': 'institution_types', 'value': ['think_tank'],
                                     'evidence_id': document['id'], 'quote': quote}]}
        Provider.transform = response
        state = self.queue_run(sid)
        self.assertEqual(len(quotes), 1)
        self.assertEqual(hashlib.sha256(quotes[0].encode()).hexdigest(), 'fe551baca6df57c4a92059138c8ed90616eedde52ecec74ad78f4c8535eb3208')
        decisions = [self.call(f'/api/sources/{sid}/suggestions/decide', {'version': 1, 'adopt': [c['id']]})
                     for c in state['candidates']]
        self.assertFalse(any(d.status_code == 200 for d in decisions), 'Cookie company text does not establish an institutional type.')
        self.assertNotIn('think_tank', self.clients['researcher'].get('/api/sources/' + sid).json['institution_types'])
        self.assertEqual(state['jobs'][0]['status'], 'failed')
        self.assertEqual(state['candidates'], [])

    def test_institution_relations_require_the_sources_own_complete_role_statement(self):
        self.synthetic()
        target = self.source('Statement Partner', kind='institution')
        for role, predicate in [('part_of', 'is part of'), ('established_by', 'was established by'),
                                ('cooperates_with', 'cooperates with'), ('funded_by', 'is funded by')]:
            with self.subTest(role=role):
                name = 'Statement Institute ' + role
                statement = name + ' ' + predicate + ' Statement Partner.'
                raw = ('<h1>' + name + '</h1><p>' + statement + '</p>').encode()
                self.document = {**self.document, 'text': raw.decode(), 'bytes': raw}
                Provider.transform = lambda output, material: {'suggestions': [{'field': 'relationships',
                    'value': {'target_name': 'Statement Partner', 'type': role},
                    'evidence_id': material['documents'][0]['id'], 'quote': statement}]}
                sid = self.source(name, kind='institution', website='https://source.example/' + role)
                state = self.queue_run(sid, role)
                self.assertEqual(len(state['candidates']), 1, state['jobs'])
                decision = self.call(f'/api/sources/{sid}/suggestions/decide', {'version': 1, 'adopt': [state['candidates'][0]['id']]})
                self.assertEqual(decision.status_code, 200, decision.json)
                saved = self.clients['researcher'].get('/api/sources/' + sid).json
                self.assertEqual([(r['type'], r['target_id']) for r in saved['relationships']], [(role, target)])

    def test_journal_host_publication_roles_stay_bound_to_the_current_journal(self):
        self.synthetic()
        target = self.source('Statement Publisher', kind='institution')
        cases = [
            ('other-subject', 'host', 'Other Journal is hosted by Statement Publisher.', None, False),
            ('website-host', 'host', 'Website is hosted by Statement Publisher.', None, False),
            ('financial-sponsor', 'host', '{name} is sponsored by Statement Publisher.', None, False),
            ('separate-role', 'host', 'Published by Statement Publisher. Hosting institution is unconfirmed.', None, False),
            ('truncated-quote', 'host', '{name} is not hosted by Statement Publisher.', 'hosted by Statement Publisher.', False),
            ('explicit-host', 'host', '{name} is hosted by Statement Publisher.', None, True),
            ('explicit-publisher', 'publisher', '{name} is published by Statement Publisher.', None, True),
            ('scoped-host-label', 'host', '主办：Statement Publisher', None, True),
        ]
        for key, field, prose, quote, supported in cases:
            with self.subTest(key=key):
                name = 'Statement Journal ' + key
                statement = prose.format(name=name)
                raw = ('<h1>' + name + '</h1><p>' + statement + '</p>').encode()
                self.document = {**self.document, 'text': raw.decode(), 'bytes': raw}
                Provider.transform = lambda output, material: {'suggestions': [{'field': field,
                    'value': {'target_name': 'Statement Publisher'}, 'evidence_id': material['documents'][0]['id'],
                    'quote': quote or statement}]}
                sid = self.source(name, kind='journal', website='https://source.example/' + key)
                state = self.queue_run(sid, key)
                if supported:
                    self.assertEqual(len(state['candidates']), 1, state['jobs'])
                    decision = self.call(f'/api/sources/{sid}/suggestions/decide', {'version': 1, 'adopt': [state['candidates'][0]['id']]})
                    self.assertEqual(decision.status_code, 200, decision.json)
                else:
                    self.assertEqual(state['candidates'], [])
                    self.assertEqual(state['jobs'][0]['status'], 'failed')
                saved = self.clients['researcher'].get('/api/sources/' + sid).json
                self.assertEqual(saved['host_id'], target if supported and field == 'host' else '')
                self.assertEqual(saved['publisher_id'], target if supported and field == 'publisher' else '')

    def test_institution_type_names_and_subjects_match_the_specific_identity_statement(self):
        self.synthetic()
        cases = [
            ('explicit-type', '{name} is an independent think tank.', ['think_tank'], True),
            ('different-type', '{name} is a university.', ['think_tank'], False),
            ('different-subject', 'Other Institute is a think tank.', ['think_tank'], False),
            ('unsupported-extra-type', '{name} is a university.', ['university', 'think_tank'], False),
        ]
        for key, prose, proposed, supported in cases:
            with self.subTest(key=key):
                name = 'Identity Institute ' + key
                statement = prose.format(name=name)
                raw = ('<h1>' + name + '</h1><p>' + statement + '</p>').encode()
                self.document = {**self.document, 'text': raw.decode(), 'bytes': raw}
                Provider.transform = lambda output, material: {'suggestions': [{'field': 'institution_types', 'value': proposed,
                    'evidence_id': material['documents'][0]['id'], 'quote': statement}]}
                sid = self.source(name, kind='institution', website='https://source.example/' + key)
                state = self.queue_run(sid, key)
                if supported:
                    self.assertEqual(len(state['candidates']), 1, state['jobs'])
                    self.assertEqual(self.call(f'/api/sources/{sid}/suggestions/decide',
                        {'version': 1, 'adopt': [state['candidates'][0]['id']]}).status_code, 200)
                    self.assertEqual(self.clients['researcher'].get('/api/sources/' + sid).json['institution_types'], proposed)
                else:
                    self.assertEqual(state['candidates'], [])
                    self.assertEqual(state['jobs'][0]['status'], 'failed')
                    self.assertEqual(self.clients['researcher'].get('/api/sources/' + sid).json['institution_types'], [])

    def test_direct_relationship_and_type_evidence_export_and_restore_after_adoption(self):
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        self.synthetic()
        partner = self.source('Recovery Partner', kind='institution')
        sid = self.source('Recovery Institute', kind='institution', website='https://source.example/')
        identity = 'Recovery Institute is a think tank.'
        relation = 'Recovery Institute cooperates with Recovery Partner.'
        raw = ('<h1>Recovery Institute</h1><p>' + identity + '</p><p>' + relation + '</p>').encode()
        self.document = {**self.document, 'text': raw.decode(), 'bytes': raw}
        Provider.transform = lambda output, material: {'suggestions': [
            {'field': 'institution_types', 'value': ['think_tank'], 'evidence_id': material['documents'][0]['id'], 'quote': identity},
            {'field': 'relationships', 'value': {'target_name': 'Recovery Partner', 'type': 'cooperates_with'},
             'evidence_id': material['documents'][0]['id'], 'quote': relation}]}
        state = self.queue_run(sid)
        self.assertEqual(len(state['candidates']), 2, state['jobs'])
        decision = self.call(f'/api/sources/{sid}/suggestions/decide',
                             {'version': 1, 'adopt': [c['id'] for c in state['candidates']]}, user='colleague')
        self.assertEqual(decision.status_code, 200, decision.json)
        exported = self.clients['researcher'].get(f'/api/sources/{sid}/suggestions/export')
        self.assertEqual(exported.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
            payload = json.loads(archive.read('suggestions.json'))
            self.assertEqual({c['evidence']['quote'] for c in payload['candidates']}, {identity, relation})
            self.assertEqual({c['decided_by'] for c in payload['candidates']}, {'colleague'})
            self.assertEqual(archive.read('evidence/' + state['candidates'][0]['evidence']['id'] + '.bin'), raw)
        backup = self.call('/api/backup', user='admin')
        path = self.data_dir.parent / 'direct-statements.zip'
        path.write_bytes(backup.data)
        backup.close()
        restored = self.data_dir.parent / 'direct-statements-restored'
        restore_backup(path, restored)
        client = self.login('colleague', create_app(restored, testing=True))
        saved = client.get('/api/sources/' + sid).json
        self.assertEqual(saved['institution_types'], ['think_tank'])
        self.assertEqual([(r['type'], r['target_id']) for r in saved['relationships']], [('cooperates_with', partner)])
        candidates = client.get(f'/api/sources/{sid}/suggestions').json['candidates']
        self.assertEqual({(c['status'], c['decided_by']) for c in candidates}, {('adopted', 'colleague')})
        self.assertEqual({c['evidence']['quote'] for c in candidates}, {identity, relation})

    def test_html_name_and_domain_do_not_support_country_or_journal_international_mission(self):
        self.synthetic()
        self.document = {'url': 'https://www.liia.lv/en', 'content_type': 'text/html',
                         'text': '<footer>© 2026 Latvian Institute of International Affairs</footer>',
                         'bytes': '<footer>© 2026 Latvian Institute of International Affairs</footer>'.encode()}
        Provider.transform = lambda output, material: {'suggestions': [{'field': 'country', 'value': 'Latvia',
            'evidence_id': material['documents'][0]['id'], 'quote': '© 2026 Latvian Institute of International Affairs'}]}
        sid = self.source('LIIA footer only', kind='institution', website='https://www.liia.lv/en')
        state = self.queue_run(sid)
        self.assertEqual(state['jobs'][0]['status'], 'failed')
        self.assertEqual(state['candidates'], [])
        self.assertEqual(self.clients['researcher'].get('/api/sources/' + sid).json['country'], '')

    def test_decision_crossing_clock_second_still_restores_with_exact_actor_history(self):
        from datetime import datetime, timezone, timedelta
        from itertools import count
        from platform_app.maintenance import restore_backup
        self.synthetic()
        sid = self.source('Clock boundary', kind='institution', website='https://source.example/')
        candidate = self.queue_run(sid)['candidates'][0]
        tick, start = count(), datetime.now(timezone.utc)
        with patch('platform_app.store.now', side_effect=lambda: (start + timedelta(seconds=next(tick))).isoformat(timespec='seconds')):
            response = self.call(f'/api/sources/{sid}/suggestions/decide', {'reject': [candidate['id']]})
        self.assertEqual(response.status_code, 200)
        backup = self.call('/api/backup', user='admin')
        path = self.data_dir.parent / 'clock.zip'
        path.write_bytes(backup.data)
        backup.close()
        target = self.data_dir.parent / 'clock-restored'
        restore_backup(path, target)
        self.assertTrue(target.is_dir())
