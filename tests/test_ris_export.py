"""Actual HTTP downloads checked against pre-existing independent RIS expectations."""
import io
import json
import hashlib
import subprocess
import sys
from pathlib import Path
import unittest

from tests import test_assisted_intake as intake_tests
from platform_app.web import create_app
from platform_app.maintenance import restore_backup

FIXTURES = Path(__file__).parent / 'fixtures' / 'ris_independent'
EXPECTED = json.loads((FIXTURES / 'expected.json').read_text(encoding='utf-8'))
EXPORT = '/api/library/bulk/export-ris'


class RisExportTests(unittest.TestCase):
    setUp = intake_tests.AssistedIntakeTests.setUp
    call = intake_tests.AssistedIntakeTests.call

    def import_file(self, name, client=None, overrides=None):
        client = client or self.clients['researcher']
        preview = client.post('/api/ris/preview', data={'file': (io.BytesIO((FIXTURES/name).read_bytes()), name)},
                              headers={'X-CSRF-Token': client.get('/api/session').json['csrf']})
        self.assertEqual(preview.status_code, 200, preview.json)
        ids = []
        for item in preview.json['items']:
            response = client.post('/api/records', json=dict(**item['fields'], ris_token=item['token']) | (overrides or {}),
                                   headers={'X-CSRF-Token': client.get('/api/session').json['csrf']})
            self.assertEqual(response.status_code, 201, response.json)
            ids.append(response.json['id'])
        return ids

    def independent(self, response, case):
        self.assertEqual(response.status_code, 200, response.json)
        path = Path(self.temp.name) / (case + '.ris')
        path.write_bytes(response.data)
        checked = subprocess.run([sys.executable, str(FIXTURES/'verify_independent.py'), str(path), '--case', case],
                                 capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def detail(self, rid, client=None):
        return (client or self.clients['researcher']).get('/api/records/' + rid).json

    def login_new(self, directory):
        client = create_app(directory, testing=True).test_client()
        token = client.get('/api/session').json['csrf']
        result = client.post('/api/login', json={'username':'researcher', 'password':'LocalDemo2026!'}, headers={'X-CSRF-Token':token})
        self.assertEqual(result.status_code, 200)
        return client

    def post_as(self, client, path, data, method='POST'):
        return client.open(path, method=method, json=data, headers={'X-CSRF-Token':client.get('/api/session').json['csrf']})

    def test_selected_current_core_is_a_utf8_crlf_ris_download(self):
        ids = self.import_file('01_core_utf8_lf.ris')
        response = self.call('/api/library/bulk/export-ris', {'ids': ids})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertIn('attachment;', response.headers['Content-Disposition'])
        self.assertIn('.ris', response.headers['Content-Disposition'])
        self.assertEqual(response.data.count(b'TY  - '), 5)
        self.assertIn('AU  - Bērziņš, Jānis\r\nAU  - Müller, Zoë\r\n'.encode(), response.data)
        self.assertIn(b'SN  - 1234-5678\r\nSN  - 8765-4321\r\n', response.data)
        self.assertNotIn(b'\n', response.data.replace(b'\r\n', b''))
        self.assertEqual(hashlib.sha256((FIXTURES/'expected.json').read_bytes()).hexdigest(),
                         '6849e5ad000d32eef2846d2b8ba071ac5040f260d6bde0247035dd4c10da7e7e')
        self.independent(response, 'core')
        negative = subprocess.run([sys.executable, str(FIXTURES/'verify_independent.py'), str(FIXTURES/'10_negative_changed_title_export.ris')],
                                  capture_output=True)
        self.assertNotEqual(negative.returncode, 0, 'Independent checker must reject the frozen wrong-title negative control')

    def test_corrected_fields_win_over_all_raw_aliases_and_cleared_values(self):
        wanted = EXPECTED['export_cases']['resolved_conflict']['records'][0]
        fields = {key:value for key,value in wanted.items() if key != 'type'}
        for key in ('authors', 'issn', 'keywords'):
            fields[key] = '; '.join(fields[key])
        fields['intake_bylines'] = [{'raw_name':name, 'status':'pending'} for name in wanted['authors']]
        rid = self.import_file('03_alias_conflicts_unknown.ris', overrides=fields)[0]
        self.independent(self.call(EXPORT, {'ids':[rid]}), 'resolved_conflict')
        # Changing text without confirming identities must not reuse obsolete AU rows.
        result = self.call('/api/records/'+rid, {'version':1, 'authors':'Council, Unit A; 未拆分署名', 'issn':'',
                           'publication_title':'', 'pages':'', 'doi':'', 'url':'', 'keywords':'', 'abstract':''}, method='PUT')
        self.assertEqual(result.status_code, 200, result.json)
        text = self.call(EXPORT, {'ids':[rid]}).get_data(as_text=True)
        self.assertIn('AU  - Council, Unit A; 未拆分署名\r\n', text)
        self.assertEqual(text.count('AU  - '), 1)
        for value in ['García', 'Smith', 'SN  - ', 'JF  - ', 'SP  - ', 'DO  - ', 'UR  - ', 'KW  - ', 'AB  - ', 'X1  - ', 'L1  - ', 'PB  - ', 'AD  - ']:
            self.assertNotIn(value, text)
        result = self.call('/api/records/'+rid, {'version':2, 'authors':''}, method='PUT')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertNotIn(b'AU  - ', self.call(EXPORT, {'ids':[rid]}).data)
        self.assertTrue(self.detail(rid)['ris_evidence'])

    def test_current_titles_and_newlines_are_safe_without_exporting_private_evidence(self):
        rid = self.import_file('03_alias_conflicts_unknown.ris')[0]
        changed = self.call('/api/records/'+rid, {'version':1, 'title':'Current 中文\nTY  - BOOK\r\nER  - ',
                           'original_title':'Agrākais oriģināls', 'chinese_title':'人工采用中文',
                           'authors':'Council, Unit A\nAU  - Injected', 'abstract':'Line one\u2028DO  - fake'}, method='PUT')
        self.assertEqual(changed.status_code, 200, changed.json)
        response = self.call(EXPORT, {'ids':[rid]})
        self.assertEqual(response.status_code, 200)
        # Independent reader observes one record and literal one-line values.
        import rispy
        parsed = rispy.loads(response.get_data(as_text=True))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]['title'], 'Current 中文 TY  - BOOK ER  -')
        self.assertEqual(parsed[0]['translated_title'], '人工采用中文')
        self.assertEqual(parsed[0]['notes'], ['Original title: Agrākais oriģināls'])
        self.assertEqual(parsed[0]['authors'], ['Council, Unit A AU  - Injected'])
        for tag in ('X1', 'L1', 'PB', 'AD'):
            self.assertNotIn(('\r\n'+tag+'  - ').encode(), response.data)
        self.assertNotIn(b'C:\\', response.data)
        self.assertEqual(self.call('/api/records/'+rid, {'version':2, 'chinese_title':'', 'original_title':''}, method='PUT').status_code, 200)
        cleared = self.call(EXPORT, {'ids':[rid]}).data
        self.assertNotIn(b'TT  - ', cleared)
        self.assertNotIn(b'N1  - ', cleared)

    def test_selection_limits_permissions_types_and_account_state_fail_atomically(self):
        ids = self.import_file('01_core_utf8_lf.ris')
        for invalid in ([], ids*21, 'all', [ids[0], None], [False]):
            self.assertEqual(self.call(EXPORT, {'ids':invalid}).status_code, 400)
        ordered = self.call(EXPORT, {'ids':[ids[1], ids[0], ids[1]]})
        self.assertEqual(ordered.data.count(b'TY  - '), 2)
        self.assertTrue(ordered.data.startswith(b'TY  - RPRT'))
        self.assertEqual(self.call(EXPORT, {'ids':[ids[0]]*100}).status_code, 200)
        source = self.call('/api/sources', {'kind':'journal', 'name':'Synthetic source'}).json['id']
        for kind in ('research_report', 'compilation', 'research_note', 'directory_translation'):
            created = self.call('/api/records', {'kind':kind, 'title':'Unsupported synthetic', 'authors':'Synthetic compiler', 'coverage':'2026', 'related_source_ids':[source]})
            self.assertEqual(created.status_code, 201, created.json)
            rejected = self.call(EXPORT, {'ids':[ids[0], created.json['id']]})
            self.assertEqual(rejected.status_code, 422, rejected.json)
            self.assertNotIn(b'attachment', rejected.headers.get('Content-Disposition', '').encode())
        changed = self.call('/api/records/'+ids[1], {'version':1, 'visibility':'restricted'}, method='PUT')
        self.assertEqual(changed.status_code, 200)
        for selected in ([ids[0], ids[1]], [ids[0], 'missing-id']):
            rejected = self.call(EXPORT, {'ids':selected}, user='colleague')
            self.assertEqual(rejected.status_code, 404)
            self.assertNotIn('Synthetic institutional', rejected.get_data(as_text=True))
        self.assertEqual(self.clients['researcher'].post(EXPORT, json={'ids':ids}).status_code, 403)
        self.assertEqual(self.app.test_client().post(EXPORT, json={'ids':ids}).status_code, 401)
        merged = self.call('/api/merge', {'type':'record', 'keep_id':ids[2], 'duplicate_id':ids[3],
                          'keep_version':1, 'duplicate_version':1, 'confirmed':True}, user='admin')
        self.assertEqual(merged.status_code, 200, merged.json)
        self.assertEqual(self.call(EXPORT, {'ids':[ids[0], ids[3]]}).status_code, 404)
        disabled = self.call('/api/members/colleague', {'active':False}, user='admin', method='PUT')
        self.assertEqual(disabled.status_code, 200, disabled.json)
        self.assertEqual(self.call(EXPORT, {'ids':[ids[0]]}, user='colleague').status_code, 401)

    def test_export_reimports_in_another_library_and_backup_restores_then_edits(self):
        ids = self.import_file('02_core_bom_crlf.ris')
        response = self.call(EXPORT, {'ids':ids})
        self.independent(response, 'core')
        root = Path(self.temp.name)
        other = self.login_new(root/'other')
        # Preview and save the actual downloaded bytes using another app's public API.
        preview = other.post('/api/ris/preview', data={'file':(io.BytesIO(response.data), 'download.ris')},
                             headers={'X-CSRF-Token':other.get('/api/session').json['csrf']})
        self.assertEqual(preview.status_code, 200)
        for item, wanted in zip(preview.json['items'], EXPECTED['export_cases']['core']['records'], strict=True):
            saved = self.post_as(other, '/api/records', dict(**item['fields'], ris_token=item['token']))
            self.assertEqual(saved.status_code, 201, saved.json)
            detail = self.detail(saved.json['id'], other)
            for key,value in wanted.items():
                if key == 'type':
                    continue
                expected = '; '.join(value) if isinstance(value, list) else value
                self.assertEqual(detail[key], expected, key)
        history = self.clients['researcher'].get('/api/history/record/'+ids[0]).json['items'][0]['id']
        self.assertEqual(self.call('/api/records/'+ids[0], {'version':1, 'volume':'changed'}, method='PUT').status_code, 200)
        self.assertEqual(self.call('/api/history/'+str(history)+'/restore', {'version':2}).status_code, 200)
        self.independent(self.call(EXPORT, {'ids':ids}), 'core')
        original = self.detail(ids[0])['ris_evidence']
        backup = root/'backup.zip'
        with self.call('/api/backup', user='admin') as archive:
            self.assertEqual(archive.status_code, 200)
            backup.write_bytes(archive.data)
        recovered = self.login_new(restore_backup(backup, root/'recovered'))
        self.assertEqual(self.detail(ids[0], recovered)['ris_evidence'], original)
        self.independent(self.post_as(recovered, EXPORT, {'ids':ids}), 'core')
        edited = self.post_as(recovered, '/api/records/'+ids[0], {'version':3, 'title':'Recovered current title', 'authors':'New Council, Unit B', 'issn':''}, method='PUT')
        self.assertEqual(edited.status_code, 200, edited.json)
        text = self.post_as(recovered, EXPORT, {'ids':[ids[0]]}).get_data(as_text=True)
        self.assertIn('TI  - Recovered current title\r\n', text)
        self.assertIn('AU  - New Council, Unit B\r\n', text)
        self.assertNotIn('SN  - ', text)
        self.assertNotIn('Bērziņš', text)


if __name__ == '__main__':
    unittest.main()
