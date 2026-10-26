"""Research scope through authenticated HTTP, portable export and new-directory restore."""
import io
from contextlib import closing
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from platform_app.web import create_app


class CollectionScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='collection-scope-')
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / 'data'
        self.app = create_app(self.data_dir, testing=True)
        self.clients = {}
        for name in ['researcher', 'colleague', 'admin']:
            client = self.app.test_client()
            token = client.get('/api/session').json['csrf']
            self.assertEqual(client.post('/api/login', json={'username': name, 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': token}).status_code, 200)
            self.clients[name] = client
        self.client = self.clients['researcher']

    def call(self, path, data, status=200, method='POST', who='researcher'):
        client = self.clients[who]
        token = client.get('/api/session').json['csrf']
        response = client.open(path, method=method, json=data, headers={'X-CSRF-Token': token})
        try:
            self.assertEqual(response.status_code, status, response.json)
            return response.json
        finally:
            response.close()

    def record(self, title='Synthetic material', **extra):
        return self.call('/api/records', {'kind': 'report', 'title': title, **extra}, 201)['id']

    def topic(self, **extra):
        return self.call('/api/collections', {'name': 'Synthetic scope', 'visibility': 'shared', **extra}, 201)['id']

    def test_excluded_item_requires_reason_and_leaves_default_sample(self):
        rid, cid = self.record(), self.topic()
        path = '/api/collections/' + cid
        self.call(path + '/items', {'record_id': rid})
        self.call(path + '/items', {'record_id': rid, 'version': 2, 'disposition': 'excluded', 'rationale': ''}, 400)
        self.call(path + '/items', {'record_id': rid, 'version': 2, 'disposition': 'excluded', 'rationale': 'Outside the specified period'})
        current = self.client.get(path).json
        self.assertEqual(current['items'], [])
        self.assertEqual([(r['id'], r['disposition'], r['rationale']) for r in current['excluded_items']], [(rid, 'excluded', 'Outside the specified period')])
        self.assertEqual(self.client.get('/api/records?collection=' + cid).json['total'], 0)
        listed = next(r for r in self.client.get('/api/collections').json['items'] if r['id'] == cid)
        self.assertEqual(listed['count'], 0)
        self.call(path + '/items', {'record_id': rid, 'version': 2, 'disposition': 'included'}, 409)
        self.call(path + '/items', {'record_id': rid, 'version': 3, 'disposition': 'included', 'rationale': 'Scope expanded'})
        self.assertEqual(self.client.get(path).json['items'][0]['rationale'], 'Scope expanded')

    def test_search_log_validation_conflicts_and_restore(self):
        cid = self.topic()
        path = '/api/collections/' + cid
        self.assertEqual(self.client.get(path).json['scope_log'], [])
        log = [{'source': 'Synthetic archive', 'query': 'language policy', 'time_range': '2020—2024', 'language': 'Latvian', 'searched_on': '2026-10-26', 'outcome': 'zero_results', 'notes': 'No matching entries in this search'}]
        self.call(path, {'version': 1, 'scope_log': log}, method='PUT')
        self.assertEqual(self.client.get(path).json['scope_log'], log)
        for field, value in [('searched_on', '2026-02-30'), ('outcome', 'unsearched'), ('source', None)]:
            self.call(path, {'version': 2, 'scope_log': [{**log[0], field: value}]}, 400, method='PUT')
        self.call(path, {'version': 2, 'scope_log': [{**log[0], 'source': '', 'query': ''}]}, 400, method='PUT')
        self.call(path, {'version': 1, 'scope_log': []}, 409, method='PUT')
        self.assertEqual(self.client.get(path).json['scope_log'], log)
        revisions = self.client.get(path + '/history').json['items']
        self.assertEqual(self.client.get('/api/history/' + str(revisions[0]['id'])).json['snapshot']['scope_log'], log)
        self.call(path + '/restore/' + str(revisions[-1]['id']), {'version': 2})
        self.assertEqual(self.client.get(path).json['scope_log'], [])

    def test_item_history_restore_and_current_permission_hide_reason(self):
        rid, cid = self.record(), self.topic()
        path = '/api/collections/' + cid
        self.call(path + '/items', {'record_id': rid, 'version': 1, 'disposition': 'excluded', 'rationale': 'Private reason marker'})
        revision = self.client.get(path + '/history').json['items'][0]['id']
        snap = self.client.get('/api/history/' + str(revision)).json['snapshot']
        self.assertEqual(snap['item_details'], [{'record_id': rid, 'disposition': 'excluded', 'rationale': 'Private reason marker'}])
        self.call(path + '/items', {'record_id': rid, 'version': 2, 'disposition': 'included', 'rationale': 'Reconsidered'})
        self.call(path + '/restore/' + str(revision), {'version': 3})
        current = self.client.get(path).json
        self.assertEqual(current['items'], [])
        self.assertEqual(current['excluded_items'][0]['rationale'], 'Private reason marker')
        self.call('/api/records/' + rid, {'version': 1, 'visibility': 'restricted'}, method='PUT')
        reader = self.clients['colleague']
        self.assertNotIn('Private reason marker', str(reader.get(path).json))
        hidden_history = reader.get('/api/history/' + str(revision)).json['snapshot']
        self.assertEqual(hidden_history['item_details'], [])
        self.assertEqual(hidden_history['item_ids'], [])
        self.call(path + '/items', {'record_id': rid, 'version': 4, 'remove': True}, who='colleague', status=404)
        self.call(path, {'version': 4, 'visibility': 'private'}, method='PUT')
        for who in ['colleague', 'admin']:
            self.assertEqual(self.clients[who].get(path).status_code, 404)
            self.assertEqual(self.clients[who].get('/api/history/' + str(revision)).status_code, 404)

    def test_old_snapshot_means_included_and_no_registered_search(self):
        import sqlite3
        rid, cid = self.record(), self.topic()
        path = '/api/collections/' + cid
        self.call(path + '/items', {'record_id': rid})
        revision = self.client.get(path + '/history').json['items'][0]['id']
        # Fixture for a historical snapshot made by the v11 application.
        with closing(sqlite3.connect(self.data_dir / 'platform.sqlite3')) as db:
            snapshot = json.loads(db.execute('SELECT snapshot_json FROM revisions WHERE id=?', (revision,)).fetchone()[0])
            snapshot.pop('item_details', None)
            snapshot.pop('scope_log_json', None)
            db.execute('UPDATE revisions SET snapshot_json=? WHERE id=?', (json.dumps(snapshot), revision))
            db.commit()
        self.call(path + '/items', {'record_id': rid, 'version': 2, 'disposition': 'excluded', 'rationale': 'New decision'})
        self.call(path + '/restore/' + str(revision), {'version': 3})
        current = self.client.get(path).json
        self.assertEqual([(r['id'], r['disposition'], r['rationale']) for r in current['items']], [(rid, 'included', '')])
        self.assertEqual(current['scope_log'], [])

    def test_scoped_export_keeps_exclusions_and_log_without_hidden_records(self):
        included = self.record('Included visible material')
        excluded = self.record('Excluded visible material')
        hidden = self.record('Hidden exclusion title', visibility='restricted')
        log = [{'source': 'Public archive', 'query': '', 'time_range': '2020—2024', 'language': 'lv', 'searched_on': '2026-10-26', 'outcome': 'access_blocked', 'notes': 'Synthetic access denial'}]
        cid = self.topic(scope_log=log)
        path = '/api/collections/' + cid
        self.call(path + '/items', {'record_id': included})
        self.call(path + '/items', {'record_id': excluded, 'version': 2, 'disposition': 'excluded', 'rationale': 'Not in scope'})
        self.call(path + '/items', {'record_id': hidden, 'version': 3, 'disposition': 'excluded', 'rationale': 'Hidden exclusion rationale'})
        response = self.clients['colleague'].get('/api/export/content?collection=' + cid)
        self.assertEqual(response.status_code, 200)
        content = response.data
        response.close()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            payload = json.loads(archive.read('content.json'))
            self.assertEqual(payload['selected_ids'], [included])
            self.assertEqual({r['id'] for r in payload['records']}, {included, excluded})
            topic = payload['collections'][0]
            self.assertEqual(topic['scope_log'], log)
            self.assertEqual({r['record_id']: (r['disposition'], r['rationale']) for r in topic['item_details']}, {included: ('included', ''), excluded: ('excluded', 'Not in scope')})
            for name in ['index.html', 'review.html']:
                html = archive.read(name).decode()
                for expected in ['已纳入', '已排查并排除', 'Not in scope', 'Synthetic access denial', '访问受阻']:
                    self.assertIn(expected, html)
            self.assertNotIn('Hidden exclusion', str([archive.read(name) for name in archive.namelist()]))
        self.call(path, {'version': 4, 'visibility': 'private'}, method='PUT')
        self.assertEqual(self.clients['colleague'].get('/api/export/content?collection=' + cid).status_code, 404)

    def test_merge_preserves_decisions_or_rejects_collisions_atomically(self):
        keep, duplicate, cid = self.record(), self.record(), self.topic()
        path = '/api/collections/' + cid
        self.call(path + '/items', {'record_id': keep})
        self.call(path + '/items', {'record_id': duplicate, 'version': 2, 'disposition': 'excluded', 'rationale': 'Different coverage'})
        merge = {'type': 'record', 'keep_id': keep, 'duplicate_id': duplicate, 'keep_version': 1, 'duplicate_version': 1, 'confirmed': True}
        self.call('/api/merge', merge, 409, who='admin')
        unchanged = self.client.get(path).json
        self.assertEqual((unchanged['version'], unchanged['items'][0]['id'], unchanged['excluded_items'][0]['id']), (3, keep, duplicate))
        self.assertEqual(self.client.get('/api/records/' + duplicate).json['id'], duplicate)
        conflict_revision = self.client.get(path + '/history').json['items'][0]['id']
        self.call(path + '/items', {'record_id': keep, 'version': 3, 'remove': True})
        self.call('/api/merge', merge, who='admin')
        current = self.client.get(path).json
        self.assertEqual([(r['id'], r['rationale']) for r in current['excluded_items']], [(keep, 'Different coverage')])
        self.assertEqual(current['version'], 5)
        self.call(path + '/items', {'record_id': keep, 'version': 4, 'remove': True}, 409)
        self.call(path + '/restore/' + str(conflict_revision), {'version': 5}, 409)
        self.assertEqual(self.client.get(path).json, current)

    def test_bulk_add_defaults_to_included_and_keeps_existing_exclusions(self):
        first, second, cid = self.record(), self.record(), self.topic()
        path = '/api/collections/' + cid
        self.call(path + '/items', {'record_id': first, 'version': 1, 'disposition': 'excluded', 'rationale': 'Already considered'})
        result = self.call('/api/library/bulk/collections/' + cid, {'ids': [first, second], 'version': 2})
        self.assertEqual((result['added'], result['existing']), (1, 1))
        topic = self.client.get(path).json
        self.assertEqual([(r['id'], r['disposition']) for r in topic['items']], [(second, 'included')])
        self.assertEqual(topic['excluded_items'][0]['rationale'], 'Already considered')

    def test_complete_backup_new_directory_restore_preserves_scope(self):
        from platform_app.maintenance import restore_backup
        rid = self.record()
        log = [{'source': 'Synthetic source', 'query': '', 'time_range': '', 'language': '', 'searched_on': '2026-10-26', 'outcome': 'found', 'notes': 'Two entries reviewed'}]
        cid = self.topic(scope_log=log)
        self.call('/api/collections/' + cid + '/items', {'record_id': rid, 'version': 1, 'disposition': 'excluded', 'rationale': 'Backup decision'})
        admin = self.clients['admin']
        response = admin.post('/api/backup', headers={'X-CSRF-Token': admin.get('/api/session').json['csrf']})
        self.assertEqual(response.status_code, 200)
        archive_path = Path(self.temp.name) / 'complete.zip'
        archive_path.write_bytes(response.data)
        response.close()
        restored = restore_backup(archive_path, Path(self.temp.name) / 'restored')
        app = create_app(restored, testing=True)
        client = app.test_client()
        token = client.get('/api/session').json['csrf']
        self.assertEqual(client.post('/api/login', json={'username': 'researcher', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': token}).status_code, 200)
        detail = client.get('/api/collections/' + cid).json
        self.assertEqual(detail['scope_log'], log)
        self.assertEqual(detail['excluded_items'][0]['rationale'], 'Backup decision')
        self.assertEqual(client.get('/api/records?collection=' + cid).json['total'], 0)
        history = client.get('/api/collections/' + cid + '/history').json['items']
        self.assertEqual(client.get('/api/history/' + str(history[0]['id'])).json['snapshot']['item_details'][0]['rationale'], 'Backup decision')

    def test_restore_rejects_resigned_backup_with_invalid_scope(self):
        import hashlib
        import sqlite3
        from platform_app.maintenance import create_backup, restore_backup
        cid = self.topic()
        archive = create_backup(self.data_dir)
        with zipfile.ZipFile(archive) as source:
            payloads = {name: source.read(name) for name in source.namelist()}
        copy = Path(self.temp.name) / 'tampered.sqlite3'
        copy.write_bytes(payloads['platform.sqlite3'])
        with closing(sqlite3.connect(copy)) as db, db:
            db.execute('UPDATE collections SET scope_log_json=? WHERE id=?', ('[{"source":"invalid"}]', cid))
        payloads['platform.sqlite3'] = copy.read_bytes()
        manifest = json.loads(payloads['manifest.json'])
        manifest['files']['platform.sqlite3'] = {'bytes': len(payloads['platform.sqlite3']), 'sha256': hashlib.sha256(payloads['platform.sqlite3']).hexdigest()}
        payloads['manifest.json'] = json.dumps(manifest).encode()
        corrupt = Path(self.temp.name) / 'corrupt.zip'
        with zipfile.ZipFile(corrupt, 'w') as output:
            for name, content in payloads.items():
                output.writestr(name, content)
        target = Path(self.temp.name) / 'rejected'
        with self.assertRaises(ValueError):
            restore_backup(corrupt, target)
        self.assertFalse(target.exists())

    def test_v11_backup_upgrade_is_backed_up_idempotent_and_transactional(self):
        import sqlite3
        from platform_app.maintenance import create_backup, restore_backup
        from platform_app.store import CURRENT_SCHEMA_VERSION
        from platform_app.collection_scope import SCHEMA_VERSION as SCOPE_SCHEMA_VERSION
        fixture = Path(__file__).parent / 'fixtures'
        expected = json.loads((fixture / 'collection_scope_v11.json').read_text(encoding="utf-8"))
        rid, cid = expected['record_id'], expected['collection_id']
        legacy = Path(self.temp.name) / 'legacy-shape'
        legacy.mkdir()
        # Frozen non-empty schema and snapshots produced by the actual v11 application.
        with closing(sqlite3.connect(legacy / 'platform.sqlite3')) as db, db:
            db.executescript((fixture / 'collection_scope_v11.sql').read_text(encoding="utf-8"))
        legacy_backup = create_backup(legacy)
        restored = restore_backup(legacy_backup, Path(self.temp.name) / 'upgrade-v11')
        app = create_app(restored, testing=True)
        self.assertEqual(app.test_client().get('/health').json['schema'], CURRENT_SCHEMA_VERSION)
        backups = list((restored / 'backups').glob('*.zip'))
        self.assertEqual(len(backups), CURRENT_SCHEMA_VERSION - 11)
        archived_versions = set()
        for index, archive in enumerate(backups):
            before = restore_backup(archive, Path(self.temp.name) / ('before-upgrade-' + str(index)))
            with closing(sqlite3.connect(before / 'platform.sqlite3')) as db:
                version = int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0])
                archived_versions.add(version)
                collection_columns = {r[1] for r in db.execute('PRAGMA table_info(collection_items)')}
                self.assertEqual('disposition' in collection_columns, version >= SCOPE_SCHEMA_VERSION)
                record_columns = {r[1] for r in db.execute('PRAGMA table_info(records)')}
                citation_columns = {r[1] for r in db.execute('PRAGMA table_info(evidence_links)')}
                self.assertEqual('volume' in record_columns, version >= 12)
                self.assertEqual('stance' in citation_columns, version >= 13)
            # Each genuine intermediate backup remains restorable and can finish the chain.
            intermediate = create_app(before, testing=True)
            self.assertEqual(intermediate.test_client().get('/health').json['schema'], CURRENT_SCHEMA_VERSION)
        self.assertEqual(archived_versions, set(range(11, CURRENT_SCHEMA_VERSION)))
        create_app(restored, testing=True)
        self.assertEqual(len(list((restored / 'backups').glob('*.zip'))), len(backups))
        client = app.test_client()
        token = client.get('/api/session').json['csrf']
        client.post('/api/login', json={'username': 'researcher', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': token})
        current = client.get('/api/collections/' + cid).json
        self.assertEqual((current['items'][0]['id'], current['items'][0]['disposition'], current['items'][0]['rationale'], current['scope_log']), (rid, 'included', '', []))
        history = client.get('/api/collections/' + cid + '/history').json['items']
        historical = client.get('/api/history/' + str(history[0]['id'])).json['snapshot']
        self.assertEqual(historical['scope_log'], [])
        self.assertEqual(historical['item_details'], [{'record_id': rid, 'disposition': 'included', 'rationale': ''}])
        failed = restore_backup(legacy_backup, Path(self.temp.name) / 'failed-upgrade')
        with closing(sqlite3.connect(failed / 'platform.sqlite3')) as db, db:
            db.execute("CREATE TRIGGER fail_scope BEFORE UPDATE ON settings WHEN OLD.key='schema_version' AND NEW.value='14' BEGIN SELECT RAISE(ABORT,'synthetic migration failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            create_app(failed, testing=True)
        with closing(sqlite3.connect(failed / 'platform.sqlite3')) as db, db:
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0], '13')
            self.assertIn('volume', [r[1] for r in db.execute('PRAGMA table_info(records)')])
            self.assertIn('stance', [r[1] for r in db.execute('PRAGMA table_info(evidence_links)')])
            self.assertNotIn('disposition', [r[1] for r in db.execute('PRAGMA table_info(collection_items)')])
            db.execute('DROP TRIGGER fail_scope')
        self.assertEqual(create_app(failed, testing=True).test_client().get('/health').json['schema'], CURRENT_SCHEMA_VERSION)

    def test_reason_only_edit_keeps_exclusion_and_requires_version_for_removal(self):
        rid, cid = self.record(), self.topic()
        path = '/api/collections/' + cid
        self.call(path + '/items', {'record_id': rid, 'version': 1, 'disposition': 'excluded', 'rationale': 'Initial reason'})
        self.call(path + '/items', {'record_id': rid, 'version': 2, 'rationale': 'Corrected reason'})
        current = self.client.get(path).json
        self.assertEqual([(r['disposition'], r['rationale']) for r in current['excluded_items']], [('excluded', 'Corrected reason')])
        self.call(path + '/items', {'record_id': rid, 'remove': True}, 409)
        self.call(path + '/items', {'record_id': rid, 'version': 2, 'remove': True}, 409)
        self.call(path + '/items', {'record_id': rid, 'version': 3, 'remove': True})
        self.assertEqual(self.client.get('/api/records/' + rid).status_code, 200)
        self.assertEqual(self.client.get(path).json['excluded_items'], [])

    def test_scope_export_and_complete_restore_keep_bibliography_reviews_and_citations(self):
        from platform_app.maintenance import restore_backup
        fields = {'volume': '7', 'issue': 'S2', 'pages': 'e314', 'issn': '1234-5678'}
        original = self.record('Cross-feature original', **fields)
        self.call('/api/review/record/' + original, {'version': 1, 'review_scope': 'metadata_only', 'review_note': 'Synthetic catalogue compared'}, who='admin')
        note = self.record('Cross-feature excerpt', kind='research_note', evidence_record_id=original, quote='Synthetic quotation', locator='paragraph 1')
        report = self.record('Cross-feature report', kind='research_report', evidence_ids=[note], evidence_citations=[{'excerpt_id': note, 'stance': 'contradicts', 'claim_note': 'Counterexample within the synthetic scope'}])
        cid = self.topic()
        path = '/api/collections/' + cid
        self.call(path + '/items', {'record_id': report})
        self.call(path + '/items', {'record_id': original, 'version': 2, 'disposition': 'excluded', 'rationale': 'Kept only as cited evidence'})
        with self.client.get('/api/export/content?collection=' + cid) as response:
            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                payload = json.loads(archive.read('content.json'))
                self.assertEqual(payload['selected_ids'], [report])
                originals = {item['id']: item for item in payload['records']}
                self.assertEqual({key: originals[original][key] for key in fields}, fields)
                self.assertEqual(originals[original]['last_verified']['review_note'], 'Synthetic catalogue compared')
                citation = originals[report]['evidence_citations'][0]
                self.assertEqual((citation['stance'], citation['claim_note']), ('contradicts', 'Counterexample within the synthetic scope'))
                self.assertEqual(payload['collections'][0]['item_details'], sorted([{'record_id': original, 'disposition': 'excluded', 'rationale': 'Kept only as cited evidence'}, {'record_id': report, 'disposition': 'included', 'rationale': ''}], key=lambda item: item['record_id']))
        backup = Path(self.temp.name) / 'combined-backup.zip'
        admin = self.clients['admin']
        with admin.post('/api/backup', headers={'X-CSRF-Token': admin.get('/api/session').json['csrf']}) as response:
            self.assertEqual(response.status_code, 200)
            backup.write_bytes(response.data)
        app = create_app(restore_backup(backup, Path(self.temp.name) / 'combined-restored'), testing=True)
        reader = app.test_client()
        csrf = reader.get('/api/session').json['csrf']
        self.assertEqual(reader.post('/api/login', json={'username': 'researcher', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf}).status_code, 200)
        restored_original = reader.get('/api/records/' + original).json
        self.assertEqual({key: restored_original[key] for key in fields}, fields)
        self.assertEqual(restored_original['last_verified']['review_note'], 'Synthetic catalogue compared')
        self.assertEqual(reader.get('/api/records/' + report).json['evidence_citations'][0]['stance'], 'contradicts')
        self.assertEqual(reader.get(path).json['excluded_items'][0]['rationale'], 'Kept only as cited evidence')
