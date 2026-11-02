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
        contexts = [patch.dict(os.environ, env), patch.object(ssl.SSLContext, 'wrap_socket', lambda c, s, *a, **k: s)]
        if fetch:
            contexts.append(patch('platform_app.intake.fetch_document', side_effect=lambda *a, **k: self.document))
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
        if True:
            self.assertEqual(self.call('/api/admin/ai/config', {'cap': '1', 'currency': 'USD'}, user='admin').status_code, 200)
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
        self.document = {**self.document, 'text': '<p>Published by Synthetic Publisher.</p>',
                         'bytes': b'<p>Published by Synthetic Publisher.</p>'}
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
        jid = self.call('/api/archive-jobs', {'source_ids': [sid], 'request_id': 'cli'}) .json['items'][0]['id']
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
