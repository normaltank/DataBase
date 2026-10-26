"""Publication metadata and Unicode retrieval at the authenticated HTTP seam."""
import csv
import io
import json
import zipfile
import unittest
from pathlib import Path

from tests import test_assisted_intake as intake_tests
from platform_app.maintenance import restore_backup


class BibliographyTests(unittest.TestCase):
    setUp = intake_tests.AssistedIntakeTests.setUp
    call = intake_tests.AssistedIntakeTests.call
    preview = intake_tests.AssistedIntakeTests.preview

    def test_publication_fields_survive_edit_conflict_history_export_and_backup(self):
        fields = dict(volume='S1', issue='2', pages='12–18; e12345', issn='1234-5678; 8765-4321')
        saved = self.call('/api/records', dict(title='Synthetic bibliography', kind='journal_article', **fields))
        self.assertEqual(saved.status_code, 201, saved.json)
        rid = saved.json['id']
        client = self.clients['researcher']
        detail = client.get('/api/records/' + rid).json
        self.assertEqual({key: detail.get(key) for key in fields}, fields)
        initial = client.get('/api/history/record/' + rid).json['items'][0]['id']
        changed = self.call('/api/records/' + rid, dict(version=1, pages='e999'), method='PUT')
        self.assertEqual(changed.status_code, 200, changed.json)
        self.assertEqual(self.call('/api/records/' + rid, dict(version=1, pages='wrong'), method='PUT').status_code, 409)
        self.assertEqual(self.call(f'/api/history/{initial}/restore', dict(version=2)).status_code, 200)
        self.assertEqual(client.get('/api/records/' + rid).json['pages'], fields['pages'])
        text = client.get('/api/records/' + rid + '/copy-text').json['text']
        for value in fields.values():
            self.assertIn(value, text)
        row = list(csv.DictReader(io.StringIO(client.get('/api/export').data.decode('utf-8-sig'))))[0]
        self.assertEqual([row.get(k) for k in ['卷', '期', '页码', 'ISSN']], list(fields.values()))
        selected = self.call('/api/library/bulk/export', {'ids': [rid]})
        selected_row = list(csv.DictReader(io.StringIO(selected.data.decode('utf-8-sig'))))[0]
        self.assertEqual([selected_row[k] for k in ['卷', '期', '页码', 'ISSN']], list(fields.values()))
        with zipfile.ZipFile(io.BytesIO(client.get('/api/export/content').data)) as archive:
            item = json.loads(archive.read('content.json'))['records'][0]
            self.assertEqual({key: item[key] for key in fields}, fields)
            pages = ''.join(archive.read(name).decode() for name in archive.namelist() if name.startswith('records/') and name.endswith('.html'))
            for value in fields.values():
                self.assertIn(value, pages)
        archive = Path(self.temp.name) / 'publication-backup.zip'
        with self.call('/api/backup', user='admin') as response:
            archive.write_bytes(response.data)
        from platform_app.web import create_app
        app = create_app(restore_backup(archive, Path(self.temp.name) / 'recovered-publication'), testing=True)
        recovered = app.test_client()
        token = recovered.get('/api/session').json['csrf']
        self.assertEqual(recovered.post('/api/login', json=dict(username='researcher', password='LocalDemo2026!'), headers={'X-CSRF-Token': token}).status_code, 200)
        self.assertEqual({key: recovered.get('/api/records/' + rid).json[key] for key in fields}, fields)

    def test_doi_and_webpage_publication_fields_keep_multiple_identifiers_and_manual_edits(self):
        payload = {'message': {'DOI': '10.5555/publication', 'title': ['Synthetic intake'],
                   'volume': '7', 'issue': 'S2', 'page': 'e12345', 'ISSN': ['1234-5678', '8765-4321']}}
        preview = self.preview(json.dumps(payload), '10.5555/publication', content_type='application/json').json
        expected = dict(volume='7', issue='S2', pages='e12345', issn='1234-5678; 8765-4321')
        self.assertEqual({key: preview['fields'].get(key) for key in expected}, expected)
        saved = self.call('/api/records', dict(**preview['fields'], intake_token=preview['token'], kind='journal_article') )
        self.assertEqual(saved.status_code, 201, saved.json)
        self.assertEqual(self.clients['researcher'].get('/api/records/' + saved.json['id']).json['issn'], expected['issn'])
        html = '<meta name="citation_title" content="Web metadata"><meta name="citation_volume" content="S1"><meta name="citation_issue" content="3"><meta name="citation_firstpage" content="12"><meta name="citation_lastpage" content="18"><meta name="citation_issn" content="1234-5678"><meta name="citation_issn" content="8765-4321">'
        page = self.preview(html).json
        self.assertEqual({key: page['fields'].get(key) for key in expected}, dict(volume='S1', issue='3', pages='12–18', issn='1234-5678; 8765-4321'))
        ld = self.preview('<script type="application/ld+json">' + json.dumps({'@type':'ScholarlyArticle','headline':'JSON-LD work','pagination':'e999','isPartOf':{'@type':'PublicationIssue','issueNumber':'4','isPartOf':{'@type':'PublicationVolume','volumeNumber':'8','isPartOf':{'@type':'Periodical','name':'Synthetic Journal','issn':['1111-2222','3333-4444']}}}}) + '</script>').json
        self.assertEqual({key: ld['fields'].get(key) for key in expected}, dict(volume='8', issue='4', pages='e999', issn='1111-2222; 3333-4444'))
        conflicting = self.preview('<meta name="citation_title" content="Conflict work"><meta name="citation_volume" content="S1"><script type="application/ld+json">' + json.dumps({'@type':'Article','headline':'Conflict work','volumeNumber':'9'}) + '</script>').json
        self.assertEqual(conflicting['fields']['volume'], 'S1')
        self.assertNotIn('pages', conflicting['fields'])
        self.assertTrue(any('volume' in warning for warning in conflicting['warnings']))
        values = {**page['fields'], 'pages':'manual e456', 'intake_token':page['token']}
        result = self.call('/api/records', values)
        self.assertEqual(result.status_code, 201, result.json)
        detail = self.clients['researcher'].get('/api/records/' + result.json['id']).json
        self.assertEqual(detail['pages'], 'manual e456')
        self.assertEqual(detail['intake_evidence'][0]['sources'][0]['raw']['meta']['citation_firstpage'], ['12'])

    def test_unicode_substrings_and_combined_attachment_source_identity_keep_permissions(self):
        source = self.call('/api/sources', dict(name='Rīgas Pētījumu avots', kind='institution')).json['id']
        person = self.call('/api/people', dict(name='Ēriks Jēkabsons', aliases='Pētnieks', change_note='Synthetic author')).json['id']
        client = self.clients['researcher']
        token = client.get('/api/session').json['csrf']
        response = client.post('/api/records', data={'data':json.dumps(dict(title='中文子串研究', kind='report', related_source_ids=[source], sharing_confirmed=True)), 'file':(io.BytesIO('首段\n\nPētījums par vēsturi'.encode()), 'synthetic.txt')}, headers={'X-CSRF-Token':token})
        self.assertEqual(response.status_code, 201, response.json)
        rid = response.json['id']
        confirmed = self.call(f'/api/records/{rid}/bylines', dict(version=0, record_version=1, change_note='Synthetic signed work', items=[dict(raw_name='E. J.',status='confirmed',target_type='person',target_id=person,evidence='Synthetic byline')]), method='PUT')
        self.assertEqual(confirmed.status_code, 200, confirmed.json)
        hidden = self.call('/api/records', dict(title='Ēriks Jēkabsons hidden', visibility='restricted')).json['id']
        for query in ['Eriks Jekabsons', 'Rigas', 'Petnieks', 'Petijums', '中文子串', 'Jekab Petijums 中文']:
            result = client.get('/api/records', query_string={'q':query}).json
            self.assertIn(rid, [row['id'] for row in result['items']], query)
        result = client.get('/api/records', query_string={'q':'Petijums Rigas'}).json['items'][0]
        self.assertIn('Pētījums', result['attachment_matches'][0]['snippet'])
        self.assertEqual(result['attachment_matches'][0]['locator'], '第 3 行')
        self.assertEqual(client.get('/api/records', query_string={'q':'中文 absent'}).json['total'], 0)
        other = self.clients['colleague']
        self.assertEqual(other.get('/api/records', query_string={'q':'hidden'}).json['total'], 0)
        self.assertNotIn(hidden, other.get('/api/export', query_string={'q':'Eriks'}).data.decode('utf-8-sig'))
        candidate = other.get('/api/record-candidates', query_string={'purpose':'original','q':'Jekab Petijums'}).json
        self.assertEqual([item['id'] for item in candidate['items']], [rid])
        search = self.call('/api/saved-searches', dict(name='Accent-free combined', conditions={'q':'Jekab Petijums'}))
        self.assertEqual(search.status_code, 201, search.json)
        self.assertEqual(client.get('/api/records', query_string={'saved_search':search.json['id']}).json['total'], 1)
        profile = client.get('/api/people/' + person).json
        self.assertEqual(self.call('/api/people/' + person, dict(version=profile['version'], aliases='Jaunais',change_note='Correct alias'), method='PUT').status_code, 200)
        self.assertEqual(client.get('/api/records', query_string={'q':'Petnieks'}).json['total'], 0)
        self.assertEqual(client.get('/api/records', query_string={'q':'Jaunais'}).json['total'], 1)

    def test_publication_upgrade_backs_up_before_schema_changes_and_recovers_after_failure(self):
        import sqlite3
        from contextlib import closing
        from platform_app.store import CURRENT_SCHEMA_VERSION
        from platform_app.bibliography import SCHEMA_VERSION
        from platform_app.web import create_app
        data = Path(self.temp.name) / 'data'
        legacy = Path(self.temp.name) / 'legacy11'
        # The migration's own pre-DDL archive is a genuine version-11 input.
        archives = list((data / 'backups').glob('*.zip'))
        previous = None
        for index, archive in enumerate(archives):
            restored = restore_backup(archive, Path(self.temp.name) / f'input-{index}')
            with closing(sqlite3.connect(restored / 'platform.sqlite3')) as db:
                if db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0] == str(SCHEMA_VERSION - 1):
                    previous = archive
        self.assertIsNotNone(previous)
        restore_backup(previous, legacy)
        with closing(sqlite3.connect(legacy / 'platform.sqlite3')) as db:
            db.execute(f"CREATE TRIGGER fail_publication BEFORE UPDATE ON settings WHEN OLD.key='schema_version' AND NEW.value='{SCHEMA_VERSION}' BEGIN SELECT RAISE(ABORT,'synthetic bibliography failure'); END")
            db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            create_app(legacy, testing=True)
        with closing(sqlite3.connect(legacy / 'platform.sqlite3')) as db:
            self.assertNotIn('volume', [row[1] for row in db.execute('PRAGMA table_info(records)')])
            db.execute('DROP TRIGGER fail_publication')
            db.commit()
        upgraded = create_app(legacy, testing=True)
        self.assertEqual(upgraded.test_client().get('/health').json['schema'], CURRENT_SCHEMA_VERSION)
        before = len(list((legacy / 'backups').glob('*.zip')))
        create_app(legacy, testing=True)
        self.assertEqual(len(list((legacy / 'backups').glob('*.zip'))), before)

    def test_adopted_publication_citation_keeps_its_original_position_after_revision(self):
        client = self.clients['researcher']
        original = self.call('/api/records', dict(title='Original publication', publication_title='Synthetic Journal', volume='7', issue='2', pages='12–18', issn='1234-5678')).json['id']
        note = self.call('/api/records', dict(title='Evidence excerpt',kind='research_note',evidence_record_id=original,quote='Synthetic quotation',locator='p12')).json['id']
        report = self.call('/api/records', dict(title='Adopted report',kind='research_report',evidence_ids=[note])).json['id']
        self.assertEqual(self.call('/api/records/'+original, dict(version=1,volume='8',pages='e999'),method='PUT').status_code,200)
        snapshot = client.get('/api/records/'+note).json['evidence_snapshot']
        self.assertEqual([snapshot.get(key) for key in ['publication_title','volume','issue','pages','issn']], ['Synthetic Journal','7','2','12–18','1234-5678'])
        text = client.get('/api/records/'+report+'/copy-text').json['text']
        self.assertIn('卷：7',text)
        self.assertIn('页码：12–18',text)
        self.assertNotIn('e999',text)

    def test_datacite_container_publication_fields_are_editable_preview_values(self):
        from unittest.mock import patch
        from tests.test_assisted_intake import PublicSocket
        payload = {'data':{'attributes':{'doi':'10.5555/datacite-publication','titles':[{'title':'DataCite publication'}],
                   'container':{'title':'Synthetic Journal','volume':'S3','issue':'4','firstPage':'21','lastPage':'29','identifierType':'ISSN','identifier':'1111-2222'}}}}
        responses = [PublicSocket(b'{}', 'application/json', status='404 Not Found'), PublicSocket(json.dumps(payload).encode(), 'application/json')]
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]), patch('socket.create_connection',side_effect=responses), patch('ssl.SSLContext.wrap_socket',side_effect=lambda sock,**kwargs:sock):
            result = self.call('/api/intake/preview',dict(input='10.5555/datacite-publication'))
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual([result.json['fields'].get(key) for key in ['volume','issue','pages','issn']],['S3','4','21–29','1111-2222'])
