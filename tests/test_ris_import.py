"""RIS exchange through authenticated HTTP with synthetic UTF-8 files."""
import io
import json
import unittest
import subprocess
import sys
import zipfile
from pathlib import Path

from tests import test_assisted_intake as intake_tests


SAMPLE = ('TY  - JOUR\r\nTI  - Rīgas 中文研究\r\nT1  - Alias title\r\n'
          'AU  - Example, Ada\r\nA1  - Pētnieku institūts\r\nPY  - 2024/05/\r\n'
          'JF  - Sintētisks žurnāls\r\nVL  - 7\r\nIS  - S2\r\nSP  - 12\r\nEP  - 18\r\n'
          'SN  - 1234-5678\r\nSN  - 8765-4321\r\nDO  - 10.5555/EXAMPLE\r\n'
          'UR  - https://example.org/article\r\nAB  - First line\r\n  continuation\r\n'
          'KW  - Baltics\r\nKW  - 中文\r\nLA  - lv\r\nL1  - C:\\private\\paper.pdf\r\nER  - \r\n')


class RisImportTests(unittest.TestCase):
    setUp = intake_tests.AssistedIntakeTests.setUp
    call = intake_tests.AssistedIntakeTests.call

    def preview(self, text=SAMPLE, user='researcher', filename='synthetic.ris'):
        client = self.clients[user]
        return client.post('/api/ris/preview', data={'file': (io.BytesIO(text.encode('utf-8')), filename)},
                           headers={'X-CSRF-Token': client.get('/api/session').json['csrf']})

    def test_member_previews_edits_and_saves_one_entry_with_original_evidence(self):
        client = self.clients['researcher']
        before = client.get('/api/records').json['total']
        response = self.preview('\ufeff' + SAMPLE + 'TY  - BOOK\nTI  - Skipped secret\nER  -\n')
        self.assertEqual(response.status_code, 200, response.json)
        preview = response.json
        self.assertEqual(client.get('/api/records').json['total'], before)
        item = preview['items'][0]
        self.assertEqual(item['fields'], dict(kind='journal_article', title='Rīgas 中文研究', authors='Example, Ada; Pētnieku institūts',
            published_on='2024-05', publication_title='Sintētisks žurnāls', volume='7', issue='S2', pages='12-18',
            issn='1234-5678; 8765-4321', doi='10.5555/example', url='https://example.org/article',
            abstract='First line\ncontinuation', keywords='Baltics; 中文', language='lv'))
        self.assertTrue(any('TI' in w and 'T1' in w for w in item['warnings']))
        self.assertEqual([a['raw_name'] for a in item['authors']], ['Example, Ada', 'Pētnieku institūts'])
        self.assertFalse(preview['items'][1]['supported'])
        saved = self.call('/api/records', dict(**item['fields'], ris_token=item['token']) | {'title': '人工核对题名'})
        self.assertEqual(saved.status_code, 201, saved.json)
        detail = client.get('/api/records/' + saved.json['id']).json
        self.assertEqual(detail['title'], '人工核对题名')
        self.assertEqual(detail['status'], 'pending')
        evidence = detail['ris_evidence'][0]
        self.assertEqual(evidence['raw_entry'], SAMPLE)
        self.assertEqual(evidence['fields']['title'], 'Rīgas 中文研究')
        self.assertEqual(evidence['saved_fields']['title'], '人工核对题名')
        self.assertEqual(evidence['file_name'], 'synthetic.ris')
        self.assertNotIn('Skipped secret', json.dumps(detail, ensure_ascii=False))
        bylines = client.get('/api/records/' + saved.json['id'] + '/bylines').json['items']
        self.assertEqual([b['status'] for b in bylines], ['pending', 'pending'])

    def test_unparseable_date_requires_review_and_structure_errors_are_local(self):
        response = self.preview('TY  - WEB\nTI  - Web item\nPY  - circa 1990\nUR  - javascript:alert(1)\nER  -\n'
                                'TY  - RPRT\nTI  - Broken\nnot a tag\nER  -\nTY  - GEN\nTI  - General\nER  -\n')
        self.assertEqual(response.status_code, 200, response.json)
        web, broken, general = response.json['items']
        self.assertEqual(web['fields']['kind'], 'other')
        self.assertNotIn('url', web['fields'])
        self.assertNotIn('published_on', web['fields'])
        self.assertTrue(web['evidence']['requires_date_review'])
        self.assertTrue(broken['errors'])
        self.assertEqual(broken['token'], '')
        self.assertEqual(general['errors'], [])
        values = dict(**web['fields'], ris_token=web['token'])
        self.assertEqual(self.call('/api/records', values).status_code, 400)
        self.assertEqual(self.call('/api/records', values | {'ris_date_reviewed': True}).status_code, 201)

    def test_similar_title_candidates_are_visible_hints_and_recheck_uses_edited_fields(self):
        rid = self.call('/api/records', {'title': 'Synthetic report on Baltic trade', 'url': 'https://example.org/existing'}).json['id']
        item = self.preview('TY  - RPRT\nTI  - Synthetic report on Baltic trades\nER  -\n').json['items'][0]
        self.assertEqual(item['duplicates'][0]['id'], rid)
        self.assertIn('题名', item['duplicates'][0]['basis'])
        result = self.call('/api/ris/status', dict(token=item['token'], fields={'url':'https://EXAMPLE.org:443/existing#part'}))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['duplicates'][0]['id'], rid)
        saved = self.call('/api/records', dict(**item['fields'], ris_token=item['token']))
        self.assertEqual(saved.status_code, 201, saved.json)

    def test_limits_utf8_aliases_and_recoverable_damage_have_explicit_feedback(self):
        client = self.clients['researcher']
        csrf = client.get('/api/session').json['csrf']
        bad = client.post('/api/ris/preview', data={'file':(io.BytesIO(b'\xff'), 'bad.ris')}, headers={'X-CSRF-Token':csrf})
        self.assertEqual(bad.status_code, 422)
        for text in ['x' * (1024*1024+1), 'TY  - GEN\nTI  - x\nER  -\n' * 101, 'outside\nTY  - GEN\nER  -\n']:
            self.assertEqual(self.preview(text).status_code, 422)
        text = 'TY  - GEN\nT1  - Fallback\nY1  - 2023///\nN2  - Abstract alias\nJO  - Alias journal\nSP  - e123\nER  -\n'
        item = self.preview(text).json['items'][0]
        self.assertEqual({k:item['fields'][k] for k in ['title','published_on','abstract','publication_title','pages']},
                         dict(title='Fallback', published_on='2023', abstract='Abstract alias', publication_title='Alias journal', pages='e123'))
        broken = self.preview('TY  - ELEC\nTI  - Valid prefix\nER  -\nTY  - JOUR\nTI  - Lost end\n').json['items']
        self.assertEqual(broken[0]['fields']['kind'], 'other')
        self.assertIn('缺少 ER', broken[1]['errors'][0])
        self.assertEqual(broken[1]['token'], '')
        long = self.preview('TY  - GEN\nTI  - ' + 'x'*4001 + '\nER  -\n').json['items'][0]
        self.assertTrue(long['errors'])
        self.assertEqual(long['token'], '')
        self.assertEqual(len(long['fields']['title']), 4001)

    def test_nested_ty_is_rejected_as_ambiguous_structure(self):
        result = self.preview('TY  - JOUR\nTI  - First\nTY  - RPRT\nTI  - Second\nER  -\n')
        self.assertEqual(result.status_code, 422, result.json)
        self.assertIn('分段', result.json['error'])

    def test_authentication_csrf_tampering_and_foreign_replay_are_rejected(self):
        self.assertEqual(self.app.test_client().post('/api/ris/preview').status_code, 401)
        self.assertEqual(self.clients['researcher'].post('/api/ris/preview').status_code, 403)
        item = self.preview().json['items'][0]
        values = dict(**item['fields'], ris_token=item['token'])
        self.assertEqual(self.call('/api/records', values | {'ris_token':item['token']+'x'}).status_code, 400)
        self.assertEqual(self.call('/api/records', values, user='colleague').status_code, 403)
        for kind in ['compilation', 'research_report', 'research_note', 'directory_translation']:
            self.assertEqual(self.call('/api/records', values | {'kind':kind, 'coverage':'2024'}).status_code, 400)
        self.assertEqual(self.call('/api/ris/status', {'token':item['token']}, user='colleague').status_code, 403)
        actor = self.clients['researcher'].get('/api/session').json['user']['id']
        self.assertEqual(self.call('/api/members/'+actor, {'active':False}, user='admin', method='PUT').status_code, 200)
        self.assertEqual(self.preview().status_code, 401)
        self.assertEqual(self.call('/api/records', values).status_code, 401)

    def test_duplicate_races_private_records_and_entry_retries_do_not_leak(self):
        # Preview precedes another member's write; the save transaction rechecks.
        item = self.preview().json['items'][0]
        hidden = self.call('/api/records', {'title':'Secret duplicate', 'doi':'10.5555/example', 'visibility':'restricted'}, user='colleague').json['id']
        result = self.call('/api/records', dict(**item['fields'], ris_token=item['token']))
        self.assertEqual(result.status_code, 409)
        self.assertNotIn(hidden, result.data.decode())
        self.assertNotIn('Secret duplicate', result.data.decode())
        self.assertEqual(self.preview().json['items'][0]['duplicates'], [])
        for text in ['TY  - GEN\nTI  - URL entry\nUR  - https://example.org/url-only\nER  -\n',
                     'TY  - GEN\nTI  - Identifier-free entry\nER  -\n']:
            preview = self.preview(text + text).json
            first = preview['items'][0]
            self.assertEqual(first['file_duplicates'], [2])
            values = dict(**first['fields'], ris_token=first['token'])
            saved = self.call('/api/records', values)
            self.assertEqual(saved.status_code, 201, saved.json)
            rid = saved.json['id']
            self.assertEqual(self.call('/api/records', values | {'title':'Changed retry', 'url':''}).status_code, 409)
            # Re-preview signs a fresh payload but the stable entry identity survives.
            again = self.preview(text + text).json['items'][0]
            self.assertEqual(self.call('/api/records', dict(**again['fields'], ris_token=again['token'])).status_code, 409)
            self.assertEqual(self.call('/api/ris/status', {'token':again['token']}).json['id'], rid)

    def test_merged_entry_retry_is_blocked_and_status_follows_current_record(self):
        text = 'TY  - GEN\nTI  - Identifier-free merged entry\nER  -\n'
        item = self.preview(text).json['items'][0]
        values = dict(**item['fields'], ris_token=item['token'])
        original = self.call('/api/records', values).json['id']
        survivor = self.call('/api/records', {'kind':'other', 'title':'Manually retained record'}).json['id']
        merged = self.call('/api/merge', dict(type='record', keep_id=survivor, duplicate_id=original,
            keep_version=1, duplicate_version=1, confirmed=True), user='admin')
        self.assertEqual(merged.status_code, 200, merged.json)
        retry = self.call('/api/records', values)
        self.assertEqual(retry.status_code, 409, retry.json)
        status = self.call('/api/ris/status', {'token':item['token']})
        self.assertEqual(status.json, {'saved':True, 'id':survivor, 'title':'Manually retained record'})

    def test_merged_private_entry_repreview_follows_multiple_merges_without_foreign_leak(self):
        text = 'TY  - GEN\nTI  - Private archived RIS title\nER  -\n'
        item = self.preview(text).json['items'][0]
        values = dict(**item['fields'], ris_token=item['token'], visibility='restricted')
        original = self.call('/api/records', values).json['id']
        first = self.call('/api/records', {'kind':'other','title':'Private first survivor','visibility':'restricted'}).json['id']
        last = self.call('/api/records', {'kind':'other','title':'Current private survivor','visibility':'restricted'}).json['id']
        for survivor, duplicate, duplicate_version in [(first, original, 1), (last, first, 2)]:
            result = self.call('/api/merge', dict(type='record', keep_id=survivor, duplicate_id=duplicate,
                keep_version=1, duplicate_version=duplicate_version, confirmed=True), user='admin')
            self.assertEqual(result.status_code, 200, result.json)
        again = self.preview(text).json['items'][0]
        for token in [item['token'], again['token']]:
            self.assertEqual(self.call('/api/records', values | {'ris_token':token}).status_code, 409)
            self.assertEqual(self.call('/api/ris/status', {'token':token}).json,
                             {'saved':True,'id':last,'title':'Current private survivor'})
            response = self.call('/api/ris/status', {'token':token}, user='colleague')
            self.assertEqual(response.status_code, 403)
            for hidden in [original, first, last, 'Private archived RIS title', 'Current private survivor']:
                self.assertNotIn(hidden, response.get_data(as_text=True))
        foreign = self.preview(text, user='colleague').json['items'][0]
        self.assertEqual(foreign['duplicates'], [])
        self.assertEqual(self.call('/api/ris/status', {'token':foreign['token']}, user='colleague').json,
                         {'saved':False,'duplicates':[]})

    def test_identity_requires_evidence_and_late_failure_rolls_back_record_and_attachment(self):
        person = self.call('/api/people', {'name':'Example, Ada', 'change_note':'Synthetic identity'}).json['id']
        journal = self.call('/api/sources', {'name':'Sintētisks žurnāls','kind':'journal','issn':'1234-5678'}).json['id']
        item = self.preview().json['items'][0]
        self.assertEqual(item['candidates']['authors'][0]['items'][0]['id'], person)
        self.assertEqual(item['candidates']['sources'][0]['id'], journal)
        byline = dict(raw_name='Example, Ada',status='confirmed',target_type='person',target_id=person)
        values = dict(**item['fields'], ris_token=item['token'], serial_id=journal, intake_bylines=[byline], sharing_confirmed=True)
        client = self.clients['researcher']
        before = client.get('/api/records').json['total']
        response = client.post('/api/records', data={'data':json.dumps(values), 'file':(io.BytesIO(b'synthetic attachment'), 'synthetic.txt')},
                               headers={'X-CSRF-Token':client.get('/api/session').json['csrf']})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(client.get('/api/records').json['total'], before)
        self.assertEqual(client.get('/api/people/'+person+'/works').json['total'], 0)
        self.assertFalse(self.call('/api/ris/status', {'token':item['token']}).json['saved'])
        values['intake_bylines'][0]['evidence'] = 'Synthetic author homepage; human confirmed'
        saved = self.call('/api/records', values)
        self.assertEqual(saved.status_code, 201, saved.json)
        self.assertEqual(client.get('/api/people/'+person+'/works').json['total'], 1)

    def test_evidence_survives_shared_edit_history_content_package_and_cli_full_restore(self):
        item = self.preview().json['items'][0]
        saved = self.call('/api/records', dict(**item['fields'], ris_token=item['token']))
        self.assertEqual(saved.status_code, 201, saved.json)
        rid = saved.json['id']
        client = self.clients['researcher']
        original = client.get('/api/records/'+rid).json['ris_evidence']
        first_history = client.get('/api/history/record/'+rid).json['items'][0]['id']
        self.assertEqual(self.call('/api/records/'+rid, {'version':1,'pages':'e999'}, user='colleague', method='PUT').status_code, 200)
        self.assertEqual(self.call('/api/history/'+str(first_history)+'/restore', {'version':2}, user='colleague').status_code, 200)
        self.assertEqual(client.get('/api/records/'+rid).json['ris_evidence'], original)
        self.assertEqual(client.get('/api/records/'+rid).json['pages'], '12-18')
        temp = Path(self.temp.name)
        archive_path = temp/'content.zip'
        archive_path.write_bytes(client.get('/api/export/content').data)
        with zipfile.ZipFile(archive_path) as archive:
            record = next(r for r in json.loads(archive.read('content.json'))['records'] if r['id']==rid)
            self.assertEqual(record['ris_evidence'], original)
            pages = ''.join(archive.read(p).decode() for p in archive.namelist() if p.startswith('records/') and p.endswith('.html'))
            self.assertIn('RIS 交换依据', pages)
            self.assertIn('1234-5678', pages)
        root = Path(__file__).resolve().parents[1]
        checked = subprocess.run([sys.executable,str(root/'scripts/verify_content_export.py'),str(archive_path)], capture_output=True,text=True)
        self.assertEqual(checked.returncode, 0, checked.stdout+checked.stderr)
        backup = subprocess.run([sys.executable,'-m','platform_app.maintenance','--backup',str(temp/'data')],cwd=root,capture_output=True,text=True)
        self.assertEqual(backup.returncode,0,backup.stderr)
        restored = temp/'restored'
        result = subprocess.run([sys.executable,'-m','platform_app.maintenance','--restore',backup.stdout.strip(),'--target',str(restored)],cwd=root,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        from platform_app.web import create_app
        recovered = create_app(restored,testing=True).test_client()
        csrf = recovered.get('/api/session').json['csrf']
        login = recovered.post('/api/login',json={'username':'researcher','password':'LocalDemo2026!'},headers={'X-CSRF-Token':csrf})
        self.assertEqual(login.status_code,200)
        self.assertEqual(recovered.get('/api/records/'+rid).json['ris_evidence'], original)
        self.assertEqual(recovered.put('/api/records/'+rid,json={'version':3,'issue':'Recovered S3'},headers={'X-CSRF-Token':login.json['csrf']}).status_code,200)
        self.assertEqual(recovered.get('/api/records/'+rid).json['issue'],'Recovered S3')


if __name__ == '__main__':
    unittest.main()
