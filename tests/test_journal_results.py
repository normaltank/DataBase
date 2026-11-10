"""Journal results use authenticated HTTP and isolated synthetic originals."""
import io
import json
import unittest
import zipfile
import sqlite3
from contextlib import closing
from unittest.mock import patch
from pathlib import Path

from tests import test_collaboration as fixtures


class JournalResultsTests(unittest.TestCase):
    setUp = fixtures.CollaborationTests.setUp
    login = fixtures.CollaborationTests.login
    call = fixtures.CollaborationTests.call
    @staticmethod
    def docx(text):
        # Stable fixture bytes: exact-original checks must not compare ZIP wall
        # clock timestamps from separately generated expected/actual fixtures.
        output = io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:
            info = zipfile.ZipInfo('word/document.xml',date_time=(2026,1,1,0,0,0))
            archive.writestr(info,'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>')
        return output.getvalue()

    def save(self, data=None, user='researcher', path='/api/journal-results', raw=None, name='虚构概览.docx'):
        return self.call(path, data or {'journal_name':'虚构期刊','year':2026,'issue':'第1—2期','request_id':'create-result-001'}, user,
                         file=(name, raw or self.docx('虚构中心成果正文')))

    def test_save_first_original_and_read_from_another_member(self):
        response = self.save()
        self.assertEqual(response.status_code, 201, response.json)
        rid = response.json['id']
        detail = self.clients['colleague'].get('/api/journal-results/'+rid).json
        self.assertEqual((detail['journal_name'],detail['year'],detail['issue']), ('虚构期刊',2026,'第1—2期'))
        self.assertEqual(detail['files'][0]['versions'][0]['version'],1)
        item = detail['files'][0]['versions'][0]
        with self.clients['colleague'].get(item['file_url']) as response:
            self.assertEqual(response.data,self.docx('虚构中心成果正文'))
        listing = self.clients['colleague'].get('/api/journal-results?year=2026&q=虚构概览').json
        self.assertEqual([r['id'] for r in listing['items']],[rid])
        self.assertEqual(self.clients['colleague'].get('/api/collaboration/journals').json['items'],[])

    def test_lost_create_response_can_be_looked_up_without_recreating_or_changing_originals(self):
        props = dict(journal_name='Recovered synthetic journal', year=2026, issue='1',
                     note='Original note', request_id='lost-create-response-001')
        response = self.save(props)
        self.assertEqual(response.status_code, 201, response.json)
        rid = response.json['id']
        props['note'] = 'New unsaved note'
        self.assertEqual(self.save(props).status_code, 409)
        receipt_path = '/api/journal-results/requests/lost-create-response-001'
        receipt = self.clients['researcher'].get(receipt_path)
        self.assertEqual(receipt.status_code, 200, receipt.json)
        self.assertEqual(receipt.json['action'], 'create')
        result = receipt.json['result']
        self.assertEqual((result['id'], result['note'], result['version']), (rid, 'Original note', 1))
        self.assertEqual(self.clients['colleague'].get(receipt_path).status_code, 404)
        self.assertEqual(self.app.test_client().get(receipt_path).status_code, 401)
        self.assertEqual(self.clients['researcher'].get(receipt_path+'-absent').status_code, 404)
        updated = self.call('/api/journal-results/'+rid,
                            dict(props, version=result['version'], request_id='explicit-recovery-001'),
                            method='PUT')
        self.assertEqual(updated.status_code, 200, updated.json)
        current = self.clients['researcher'].get('/api/journal-results/'+rid).json
        self.assertEqual(current['note'], 'New unsaved note')
        self.assertEqual(len(current['files']), 1)
        self.assertEqual(len(current['files'][0]['versions']), 1)
        self.assertEqual(self.clients['researcher'].get('/api/journal-results').json['total'], 1)

    def test_parallel_files_explicit_update_and_shared_history(self):
        rid = self.save().json['id']
        path = '/api/journal-results/'+rid
        first = self.clients['colleague'].get(path).json['files'][0]
        second = self.save({'version':1,'request_id':'parallel-file-001'},'colleague',path+'/files',self.docx('第二份'), '并列.docx')
        self.assertEqual(second.status_code,201,second.json)
        revised = self.save({'version':2,'request_id':'revise-file-001','series_id':first['id']},'colleague',path+'/files',self.docx('修订一'), '修订.docx')
        self.assertEqual(revised.status_code,201,revised.json)
        detail = self.clients['researcher'].get(path).json
        series = {f['id']:f for f in detail['files']}
        self.assertEqual([v['version'] for v in series[first['id']]['versions']],[2,1])
        self.assertEqual(sorted(len(f['versions']) for f in detail['files']),[1,2])
        self.assertEqual(series[first['id']]['versions'][0]['actor_id'],'colleague')
        history = self.clients['researcher'].get(path+'/history').json['items']
        self.assertEqual([e['action'] for e in history],['更新文件','添加并列文件','保存一期成果'])
        restore = self.call(path+'/restore',{'version':3,'request_id':'restore-file-001','series_id':first['id'],'file_version':1},'colleague')
        self.assertEqual(restore.status_code,200,restore.json)
        current = next(f for f in self.clients['researcher'].get(path).json['files'] if f['id']==first['id'])['versions'][0]
        self.assertEqual(current['version'],3)
        with self.clients['colleague'].get(current['file_url']) as response:
            self.assertEqual(response.data,self.docx('虚构中心成果正文'))

    def test_multiple_initial_originals_and_atomic_failure(self):
        client = self.clients['researcher']
        props = {'journal_name':'虚构多文件','year':2025,'issue':'特刊','request_id':'multi-create-001'}
        csrf = client.get('/api/session').json['csrf']
        with patch('platform_app.journal_results.handoff_files.save_original',side_effect=OSError('synthetic disk failure')):
            response = self.save(props)
        self.assertEqual(response.status_code,503)
        self.assertEqual(client.get('/api/journal-results').json['items'],[])
        response = client.post('/api/journal-results',data={'data':json.dumps(props),'files':[(io.BytesIO(self.docx('甲')),'甲.docx'),(io.BytesIO(b'%PDF-1.4\nsynthetic'),'乙.pdf')]},headers={'X-CSRF-Token':csrf})
        response.request.close()
        self.assertEqual(response.status_code,201,response.json)
        item = client.get('/api/journal-results/'+response.json['id']).json
        self.assertEqual(len(item['files']),2)

    def test_idempotence_stale_duplicate_and_invalid_input(self):
        first = self.save()
        rid = first.json['id']
        self.assertEqual(self.save().json['id'],rid)
        self.assertEqual(self.save(raw=self.docx('不同原件')).status_code,409)
        duplicate = self.save({'journal_name':'虚构期刊','year':2026,'issue':'第1—2期','request_id':'duplicate-result-001'})
        self.assertEqual(duplicate.status_code,409)
        self.assertIn(rid,duplicate.json['error'])
        path = '/api/journal-results/'+rid
        self.assertEqual(self.save({'version':0,'request_id':'stale-file-001'},path=path+'/files').status_code,409)
        self.assertEqual(self.save({'version':1,'request_id':'foreign-file-001','series_id':'foreign'},path=path+'/files').status_code,404)
        for name,raw in [('bad.exe',b'bad'),('bad.pdf',b'not pdf'),('bad.docx',b'not word'),('empty.txt',b''),('big.txt',b'x'*(20*1024*1024+1))]:
            response = self.call(path+'/files',{'version':1,'request_id':'invalid-original-001'},file=(name,raw))
            self.assertEqual(response.status_code,400,(name,response.status_code))
        self.assertEqual(self.app.test_client().get(path).status_code,401)
        self.assertEqual(len(self.clients['researcher'].get(path).json['files']),1)

    def test_metadata_find_optional_relation_preview_and_restore(self):
        jid = self.call('/api/sources',{'kind':'journal','name':'虚构已建档刊'}).json['id']
        rid = self.save().json['id']
        path = '/api/journal-results/'+rid
        updated = self.call(path,{'version':1,'request_id':'metadata-edit-001','journal_id':jid,'issue':'跨期（标题标注）','authors':'离线署名'},'colleague','PUT')
        self.assertEqual(updated.status_code,200,updated.json)
        self.assertEqual(self.clients['researcher'].get('/api/journal-results?journal_id='+jid).json['total'],1)
        self.assertEqual(self.clients['researcher'].get('/api/journal-results?year=2025').json['total'],0)
        self.assertEqual(self.clients['researcher'].get('/api/journal-results?year=bad').status_code,400)
        detail = self.clients['researcher'].get(path).json
        preview = self.clients['researcher'].get(detail['files'][0]['versions'][0]['preview_url']).json
        self.assertEqual(preview['text'],'虚构中心成果正文')
        self.assertEqual(self.call(path+'/restore',{'version':2,'request_id':'restore-metadata-001','history_version':1},'colleague').status_code,200)
        self.assertEqual(self.clients['researcher'].get(path).json['issue'],'第1—2期')

    def test_backup_readable_export_restore_and_corruption_rejection(self):
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        rid = self.save().json['id']
        path = '/api/journal-results/'+rid
        self.assertEqual(self.save({'version':1,'request_id':'export-second-001'},path=path+'/files',raw=b'%PDF-1.4\nsynthetic',name='虚构.pdf').status_code,201)
        with self.clients['colleague'].get('/api/journal-results/export?ids='+rid) as response:
            self.assertEqual(response.status_code,200,response.json)
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                result = json.loads(archive.read('content.json'))['journal_results'][0]
                self.assertEqual(result['id'],rid)
                self.assertEqual(len(result['history']),2)
                for series in result['files']:
                    for version in series['versions']:
                        self.assertEqual(len(archive.read(version['path'])),version['bytes'])
        with self.call('/api/backup',user='admin') as response:
            backup = Path(self.temp.name)/'new-results.zip'
            backup.write_bytes(response.data)
        target = Path(self.temp.name)/'restored'
        restore_backup(backup,target)
        client = self.login('colleague',create_app(target,testing=True))
        detail = client.get(path).json
        self.assertEqual(len(detail['files']),2)
        self.assertEqual(len(client.get(path+'/history').json['items']),2)
        pdf = next(f['versions'][0] for f in detail['files'] if f['versions'][0]['name']=='虚构.pdf')
        with client.get(pdf['file_url']) as response:
            self.assertTrue(response.data.startswith(b'%PDF-'))
        from platform_app import journal_results
        with closing(sqlite3.connect(target/'platform.sqlite3')) as db:
            db.row_factory = sqlite3.Row
            db.execute('UPDATE journal_result_events SET snapshot_json=? WHERE version=2',(json.dumps({'files':{}}),))
            with self.assertRaisesRegex(ValueError,'快照'):
                journal_results.validate_backup(db)

    def test_late_failure_cleans_files_and_preserves_originals(self):
        rid = self.save().json['id']
        before = {p.name for p in (self.data_dir/'handoffs').iterdir()}
        with closing(sqlite3.connect(self.data_dir/'platform.sqlite3')) as db,db:
            db.execute("CREATE TRIGGER synthetic_late_result BEFORE INSERT ON journal_result_events WHEN NEW.version=2 BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        self.assertEqual(self.save({'version':1,'request_id':'late-result-001'},path='/api/journal-results/'+rid+'/files').status_code,409)
        self.assertEqual({p.name for p in (self.data_dir/'handoffs').iterdir()},before)
        self.assertEqual(self.clients['colleague'].get('/api/journal-results/'+rid).json['version'],1)

    def test_word_preview_is_bounded_and_pdf_preview_keeps_original(self):
        text = '合成文字' * 8000
        rid = self.save(raw=self.docx(text)).json['id']
        detail = self.clients['colleague'].get('/api/journal-results/'+rid).json
        item = detail['files'][0]['versions'][0]
        preview = self.clients['colleague'].get(item['preview_url']).json
        self.assertEqual(preview,{'kind':'text','text':text[:30000],'truncated':True})
        self.assertEqual(self.app.test_client().get(item['file_url']).status_code,401)
        path = '/api/journal-results/'+rid
        self.assertEqual(self.save({'version':1,'request_id':'pdf-preview-001'},path=path+'/files',raw=b'%PDF-1.4\nsynthetic',name='合成.pdf').status_code,201)
        pdf = next(f['versions'][0] for f in self.clients['colleague'].get(path).json['files'] if f['versions'][0]['name']=='合成.pdf')
        url = self.clients['colleague'].get(pdf['preview_url']).json['url']
        with self.clients['colleague'].get(url) as response:
            self.assertEqual(response.data,b'%PDF-1.4\nsynthetic')
            self.assertTrue(response.headers['Content-Disposition'].startswith('inline'))

    def test_schema27_migration_preserves_old_record_permission_and_adoption(self):
        from platform_app.web import create_app
        from platform_app.store import connect
        response = self.call('/api/collaboration/journals',{'journal_name':'原有私人成果','coverage':'旧跨期','content_kind':'compilation','visibility':'restricted'})
        wid = response.json['id']
        path = '/api/collaboration/journals/'+wid
        uploaded = self.call(path+'/submissions',{'version':1,'request_id':'legacy-migrate-001','material_kind':'product'},file=('原有.txt',b'old synthetic original'))
        self.assertEqual(self.call(path+'/product',{'version':2,'submission_id':uploaded.json['id']}).status_code,200)
        before = self.clients['researcher'].get(path).json
        with closing(connect(self.data_dir/'platform.sqlite3')) as db,db:
            old_records = [tuple(r) for r in db.execute('SELECT * FROM records ORDER BY id')]
            for table in ['maintenance_evidence','maintenance_steps','maintenance_jobs']:
                db.execute('DROP TABLE '+table)
            db.execute('ALTER TABLE people DROP COLUMN orcid')
            for table in ['journal_result_requests','journal_result_events','journal_result_versions','journal_result_series','journal_results']:
                db.execute('DROP TABLE '+table)
            db.execute("UPDATE settings SET value='27' WHERE key='schema_version'")
        app = create_app(self.data_dir,testing=True,embedded_worker=False)
        reader = self.login('researcher',app)
        colleague = self.login('colleague',app)
        self.assertEqual(reader.get('/health').json['schema'],29)
        self.assertEqual(reader.get(path).json,before)
        self.assertEqual(colleague.get(path).status_code,404)
        with closing(connect(self.data_dir/'platform.sqlite3')) as db:
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM records ORDER BY id')],old_records)
            self.assertTrue(Path(db.execute("SELECT value FROM settings WHERE key='journal_results_migration_backup'").fetchone()[0]).is_file())

    def test_complete_restore_rejects_rehashed_broken_history_and_original(self):
        import hashlib
        from platform_app.maintenance import restore_backup
        rid = self.save().json['id']
        with self.call('/api/backup',user='admin') as response:
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                files = {name:archive.read(name) for name in archive.namelist()}
        for mutation in ['history','bytes']:
            with self.subTest(mutation=mutation):
                bad = dict(files)
                manifest = json.loads(bad['manifest.json'])
                if mutation=='history':
                    db_path = Path(self.temp.name)/'tampered.sqlite3'
                    db_path.write_bytes(bad['platform.sqlite3'])
                    with closing(sqlite3.connect(db_path)) as db,db:
                        db.execute("DELETE FROM journal_result_events WHERE result_id=?",(rid,))
                    bad['platform.sqlite3'] = db_path.read_bytes()
                    manifest['files']['platform.sqlite3'] = {'bytes':len(bad['platform.sqlite3']),'sha256':hashlib.sha256(bad['platform.sqlite3']).hexdigest()}
                    bad['manifest.json'] = json.dumps(manifest).encode()
                else:
                    original = next(name for name in bad if name.startswith('handoffs/'))
                    bad[original] = b'corrupted original'
                backup = Path(self.temp.name)/(mutation+'.zip')
                with zipfile.ZipFile(backup,'w') as archive:
                    for name,raw in bad.items():archive.writestr(name,raw)
                target = Path(self.temp.name)/('rejected-'+mutation)
                with self.assertRaises(ValueError):
                    restore_backup(backup,target)
                self.assertFalse(target.exists())

    def test_restore_rejects_cross_series_swap_even_with_valid_original_hashes(self):
        from platform_app import journal_results
        from platform_app.store import connect
        rid = self.save().json['id']
        self.assertEqual(self.save({'version':1,'request_id':'swap-parallel-001'},path='/api/journal-results/'+rid+'/files',name='另一份.docx',raw=self.docx('独立另一份')).status_code,201)
        with closing(connect(self.data_dir/'platform.sqlite3')) as db,db:
            rows = db.execute('SELECT id,series_id FROM journal_result_versions ORDER BY id').fetchall()
            db.execute('UPDATE journal_result_versions SET series_id=?,version=2 WHERE id=?',(rows[1]['series_id'],rows[0]['id']))
            db.execute('UPDATE journal_result_versions SET series_id=? WHERE id=?',(rows[0]['series_id'],rows[1]['id']))
            db.execute('UPDATE journal_result_versions SET version=1 WHERE id=?',(rows[0]['id'],))
            with self.assertRaisesRegex(ValueError,'原件|请求'):
                journal_results.validate_backup(db)

    def test_native_release_result_checker_uses_the_same_http_contract(self):
        from types import SimpleNamespace
        import sys
        with patch.object(sys,'path',[str(Path(__file__).resolve().parents[1]/'scripts'),*sys.path]):
            from scripts.check_portable_preview import continue_journal_results
        rid = self.save().json['id']
        path = '/api/journal-results/'+rid
        sid = self.clients['researcher'].get(path).json['files'][0]['id']
        self.assertEqual(self.save({'version':1,'request_id':'native-prior-001','series_id':sid},path=path+'/files',raw=self.docx('已有第二版')).status_code,201)
        self.assertEqual(self.save({'version':2,'request_id':'native-prior-002'},path=path+'/files',raw=self.docx('已有附录'),name='附录.docx').status_code,201)
        def adapter(user):
            def request(url,data=None,file=None,method=None,raw=False):
                response = self.call(url,data,user,method or 'POST',file) if data is not None or file else self.clients[user].get(url)
                try:
                    self.assertIn(response.status_code,[200,201],response.json if response.is_json else url)
                    return response.data if raw else response.json
                finally:
                    response.close()
            return SimpleNamespace(request=request)
        result = continue_journal_results(adapter('researcher'),adapter('colleague'),{'journal_result':rid})
        self.assertEqual(result['version'],5)

    def test_explicit_journal_relation_follows_a_confirmed_source_merge(self):
        old = self.call('/api/sources',{'kind':'journal','name':'虚构旧档案'}).json['id']
        keep = self.call('/api/sources',{'kind':'journal','name':'虚构保留档案'}).json['id']
        rid = self.save({'journal_name':'成果自己的刊名','year':2026,'issue':'特刊','journal_id':old,'request_id':'merged-source-result'}).json['id']
        merged = self.call('/api/merge',{'type':'source','keep_id':keep,'duplicate_id':old,'keep_version':1,'duplicate_version':1,'confirmed':True},'admin')
        self.assertEqual(merged.status_code,200,merged.json)
        self.assertEqual(self.clients['colleague'].get('/api/journal-results?journal_id='+keep).json['total'],1)
        detail = self.clients['colleague'].get('/api/journal-results/'+rid).json
        self.assertEqual(detail['journal_id'],keep)
        self.assertEqual(detail['journal_name'],'成果自己的刊名')
        self.assertEqual(self.clients['colleague'].get('/api/journal-results/'+rid+'/history').json['items'][0]['snapshot']['journal_id'],old)
        duplicate = self.save({'journal_name':'另外的标题写法','year':2026,'issue':'特刊','journal_id':keep,'request_id':'merged-source-duplicate'})
        self.assertEqual(duplicate.status_code,409)
        distinct = self.call('/api/sources',{'kind':'journal','name':'明确不同的另一期刊档案'}).json['id']
        separate = self.save({'journal_name':'成果自己的刊名','year':2026,'issue':'特刊','journal_id':distinct,'request_id':'distinct-journal-result'})
        self.assertEqual(separate.status_code,201,separate.json)
