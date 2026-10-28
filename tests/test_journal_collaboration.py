"""Independent journal work through public HTTP, immutable files and recovery."""
import io
import json
import sqlite3
import hashlib
import zipfile
from pathlib import Path
from contextlib import closing
from platform_app.maintenance import restore_backup
from platform_app.web import create_app
from platform_app.store import CURRENT_SCHEMA_VERSION
import unittest

from tests.test_collaboration import CollaborationTests


class JournalCollaborationTests(unittest.TestCase):
    setUp = CollaborationTests.setUp
    login = CollaborationTests.login
    call = CollaborationTests.call
    # Reuse the authenticated HTTP fixture, not the topic scenarios.
    def work(self, kind="directory_translation", **extra):
        data = {"journal_name": "合成期刊", "coverage": "2025年第1—3期", "source_clue": "https://example.invalid/journal", "content_kind": kind, **extra}
        response = self.call("/api/collaboration/journals", data)
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["id"]

    def upload(self, wid, version=1, key="journal-request-1", user="researcher", raw=b"first original", kind="manuscript"):
        return self.call(f"/api/collaboration/journals/{wid}/submissions", {"version": version, "request_id": key, "note": "本机整体稿件", "material_kind": kind}, user, file=("整体稿.txt", raw))

    def test_journal_schema_is_advertised_at_public_health_boundary(self):
        self.assertEqual(self.clients['researcher'].get('/health').json['schema'], CURRENT_SCHEMA_VERSION)

    def test_journal_work_preserves_independent_original_versions_without_topic(self):
        wid = self.work()
        first = self.upload(wid)
        self.assertEqual(first.status_code, 201, first.json)
        second = self.upload(wid, 2, "journal-request-2", "colleague", b"revised original")
        self.assertEqual(second.status_code, 201, second.json)
        path = f"/api/collaboration/journals/{wid}"
        detail = self.clients["colleague"].get(path).json
        self.assertEqual(detail["coverage"], "2025年第1—3期")
        self.assertEqual(detail["record_kind"], "directory_translation")
        self.assertEqual([s["version"] for s in detail["submissions"]], [2, 1])
        for item, raw in zip(detail["submissions"], [b"revised original", b"first original"]):
            with self.clients["colleague"].get(item["file_url"]) as download:
                self.assertEqual(download.data, raw)
        self.assertEqual(self.clients["researcher"].get("/api/collaboration/topics").json["items"], [])
        self.assertEqual(self.clients["colleague"].get(f"/api/collaboration/topics/{wid}").status_code, 404)

    def test_personal_report_reader_cannot_submit_even_a_new_version_or_select_product(self):
        wid = self.work('compilation')
        self.assertEqual(self.upload(wid).status_code, 201)
        for user in ['colleague', 'admin']:
            detail = self.clients[user].get(f'/api/collaboration/journals/{wid}').json
            self.assertFalse(detail['can_edit'])
            self.assertEqual(self.upload(wid, 2, 'unauthorized-request', user).status_code, 403)
            self.assertEqual(self.call(f'/api/collaboration/journals/{wid}/product', {'version':2,'submission_id':detail['submissions'][0]['id']}, user).status_code, 403)
        private = self.work('compilation', visibility='restricted')
        self.assertEqual(self.clients['colleague'].get(f'/api/collaboration/journals/{private}').status_code, 404)
        self.assertNotIn(private, [w['id'] for w in self.clients['colleague'].get('/api/collaboration/journals').json['items']])

    def test_known_journal_metadata_and_explicit_product_selection_keep_history(self):
        source = self.call('/api/sources', {'name':'已登记合成期刊','kind':'journal'}).json['id']
        wid = self.work(journal_id=source)
        path = f'/api/collaboration/journals/{wid}'
        one = self.upload(wid).json['id']
        adopted = self.call(path+'/product', {'version':2, 'submission_id':one, 'note':'采用此原件为当前成品'})
        self.assertEqual(adopted.status_code, 200, adopted.json)
        self.assertEqual(self.upload(wid, 3, 'revision-after-product', raw=b'new manuscript').status_code, 201)
        detail = self.clients['colleague'].get(path).json
        self.assertEqual(detail['journal_id'], source)
        self.assertEqual(detail['journal_name'], '已登记合成期刊')
        self.assertEqual(detail['current_product_id'], one)
        self.assertEqual(detail['submissions'][0]['material_kind'], 'manuscript')
        edited = self.call(path, {'version':4,'coverage':'2025—2026跨期','source_clue':'补充出处'}, method='PUT')
        self.assertEqual(edited.status_code, 200, edited.json)
        self.assertEqual(self.call(path, {'version':4,'coverage':'过期覆盖范围'},method='PUT').status_code,409)
        events = self.clients['colleague'].get(path+'/history').json['items']
        self.assertEqual(len(events),5)
        self.assertEqual(events[-1]['snapshot']['coverage'], '2025年第1—3期')

    def test_export_and_full_restore_keep_all_originals_and_product_relation(self):
        wid = self.work()
        path = f'/api/collaboration/journals/{wid}'
        one = self.upload(wid).json['id']
        self.assertEqual(self.upload(wid,2,'journal-review-file',raw=b'review comments',kind='review').status_code,201)
        self.assertEqual(self.call(path+'/product',{'version':3,'submission_id':one}).status_code,200)
        with self.clients['colleague'].get('/api/export/content') as response:
            self.assertEqual(response.status_code,200,response.json)
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                payload = json.loads(archive.read('content.json'))
                work = next(w for w in payload['journal_works'] if w['id']==wid)
                self.assertEqual(work['current_product_id'],one)
                self.assertEqual([archive.read(s['path']) for s in work['submissions']],[b'review comments',b'first original'])
                self.assertTrue(all(s['path'].encode() in archive.read(work['path']) for s in work['submissions']))
        with self.call('/api/backup',user='admin') as response:
            backup = Path(self.temp.name)/'complete.zip'
            backup.write_bytes(response.data)
        target = Path(self.temp.name)/'new-restored-directory'
        restore_backup(backup,target)
        restored = self.login('colleague',create_app(target,testing=True))
        detail = restored.get(path).json
        self.assertEqual(detail['current_product_id'],one)
        for item,raw in zip(detail['submissions'],[b'review comments',b'first original']):
            with restored.get(item['file_url']) as response:
                self.assertEqual(response.data,raw)
        self.assertEqual(len(restored.get(path+'/history').json['items']),4)

    def test_idempotence_cross_work_validation_and_late_failure_leave_original_intact(self):
        wid, other = self.work(), self.work()
        first = self.upload(wid)
        self.assertEqual(first.status_code,201)
        self.assertEqual(self.upload(wid).json['id'],first.json['id'])
        self.assertEqual(self.upload(wid,raw=b'changed request').status_code,409)
        self.assertEqual(self.upload(wid,1,'stale-journal-request').status_code,409)
        path=f'/api/collaboration/journals/{wid}'
        item=self.clients['researcher'].get(path).json['submissions'][0]
        self.assertEqual(self.call(f'/api/collaboration/journals/{other}/product',{'version':1,'submission_id':item['id']}).status_code,400)
        self.assertEqual(self.call('/api/collaboration/journals',{'journal_name':'误串主题','coverage':'2026年','topic_id':wid}).status_code,400)
        self.assertEqual(self.clients['colleague'].get(item['file_url'].replace(wid,other)).status_code,404)
        self.assertEqual(self.clients['colleague'].get(f'/api/collaboration/topics/{wid}/candidates/{item["id"]}/file').status_code,404)
        before={p.name for p in (self.data_dir/'handoffs').iterdir()}
        with closing(sqlite3.connect(self.data_dir/'platform.sqlite3')) as db,db:
            db.execute("CREATE TRIGGER fail_synthetic_journal BEFORE INSERT ON journal_work_events WHEN NEW.version=3 BEGIN SELECT RAISE(ABORT,'late journal failure'); END")
        self.assertEqual(self.upload(wid,2,'late-journal-failure',raw=b'failed new file').status_code,409)
        self.assertEqual({p.name for p in (self.data_dir/'handoffs').iterdir()},before)
        self.assertEqual(len(self.clients['colleague'].get(path).json['submissions']),1)
        with self.clients['colleague'].get(item['file_url']) as response:
            self.assertEqual(response.data,b'first original')

    def test_failed_new_work_is_atomic_and_rejected_files_do_not_create_versions(self):
        with closing(sqlite3.connect(self.data_dir/'platform.sqlite3')) as db,db:
            db.execute("CREATE TRIGGER fail_new_journal BEFORE INSERT ON journal_work_events WHEN NEW.version=1 BEGIN SELECT RAISE(ABORT,'synthetic creation failure'); END")
        response=self.call('/api/collaboration/journals',{'journal_name':'失败不留下正文','coverage':'2026年','content_kind':'compilation'})
        self.assertEqual(response.status_code,409,response.json)
        self.assertEqual(self.clients['researcher'].get('/api/collaboration/journals').json['items'],[])
        self.assertEqual(self.clients['researcher'].get('/api/records?q=失败不留下正文').json['items'],[])
        with closing(sqlite3.connect(self.data_dir/'platform.sqlite3')) as db,db:
            db.execute('DROP TRIGGER fail_new_journal')
        wid=self.work()
        first=self.upload(wid)
        self.assertEqual(first.status_code,201)
        path=f'/api/collaboration/journals/{wid}'
        before={p.name for p in (self.data_dir/'handoffs').iterdir()}
        for name,raw in [('伪装.docx',b'not a docx'),('伪装.pdf',b'not a pdf'),('空.txt',b'')]:
            with self.subTest(name=name):
                response=self.call(path+'/submissions',{'version':2,'request_id':'invalid-journal-file','material_kind':'manuscript'},file=(name,raw))
                self.assertEqual(response.status_code,400,response.json)
        self.assertEqual({p.name for p in (self.data_dir/'handoffs').iterdir()},before)
        self.assertEqual(len(self.clients['researcher'].get(path).json['submissions']),1)

    def test_product_retry_returns_original_selection_even_after_later_submission(self):
        wid=self.work()
        sid=self.upload(wid).json['id']
        path=f'/api/collaboration/journals/{wid}'
        data={'version':2,'submission_id':sid,'request_id':'journal-product-request','note':'采用说明'}
        first=self.call(path+'/product',data)
        self.assertEqual(first.status_code,200)
        self.assertEqual(self.upload(wid,3,'journal-after-selection',raw=b'later manuscript').status_code,201)
        self.assertEqual(self.call(path+'/product',data).status_code,200)
        self.assertEqual(self.call(path+'/product',{**data,'note':'different intent'}).status_code,409)
        self.assertEqual(len(self.clients['researcher'].get(path+'/history').json['items']),4)

    def test_existing_cross_issue_body_original_links_and_author_grants_survive_new_work(self):
        sid=self.call('/api/sources',{'kind':'journal','name':'跨期原期刊'}).json['id']
        original=self.call('/api/records',{'kind':'journal_article','title':'既有原文'}).json['id']
        old=self.call('/api/records',{'kind':'directory_translation','title':'旧跨期目录','authors':'原编译署名','coverage':'2023—2025','body_html':'<p>既有网页正文</p>','related_source_ids':[sid],'linked_ids':[original],'sharing_confirmed':True},file=('旧附件.txt',b'legacy attachment')).json['id']
        before=self.clients['researcher'].get('/api/records/'+old).json
        wid=self.work(record_id=old,journal_id=sid)
        self.assertEqual(self.clients['researcher'].get('/api/records/'+old).json,before)
        self.assertEqual(self.upload(wid,user='colleague').status_code,201)
        self.assertEqual(self.clients['researcher'].get('/api/records/'+old).json,before)
        with self.clients['colleague'].get('/api/attachments/'+before['attachments'][0]['id']) as r:
            self.assertEqual(r.data,b'legacy attachment')
        personal=self.work('compilation')
        report=self.clients['researcher'].get(f'/api/collaboration/journals/{personal}').json['record_id']
        grant=self.call('/api/records/'+report,{'version':1,'editors':['colleague']},method='PUT')
        self.assertEqual(grant.status_code,200,grant.json)
        self.assertEqual(self.upload(personal,user='colleague').status_code,201)
        revoke=self.call('/api/records/'+report,{'version':2,'editors':[]},method='PUT')
        self.assertEqual(revoke.status_code,200,revoke.json)
        self.assertEqual(self.upload(personal,2,'revoked-journal-request','colleague').status_code,403)
        submitted=self.clients['colleague'].get(f'/api/collaboration/journals/{personal}').json['submissions'][0]
        with self.clients['colleague'].get(submitted['file_url']) as response:
            self.assertEqual(response.data,b'first original')

    def test_current_permissions_recheck_without_invalidating_legal_historical_backup(self):
        wid=self.work('compilation',visibility='restricted')
        path=f'/api/collaboration/journals/{wid}'
        report=self.clients['researcher'].get(path).json['record_id']
        self.assertEqual(self.call('/api/records/'+report,{'version':1,'editors':['colleague']},method='PUT').status_code,200)
        first=self.upload(wid,user='colleague')
        self.assertEqual(first.status_code,201,first.json)
        item=self.clients['colleague'].get(path).json['submissions'][0]
        self.assertEqual(self.call(path+'/product',{'version':2,'submission_id':first.json['id']},user='colleague').status_code,200)
        self.assertEqual(self.call('/api/records/'+report,{'version':2,'editors':[]},method='PUT').status_code,200)
        for suffix in ['', '/history', '/submissions/'+item['id']+'/file']:
            self.assertEqual(self.clients['colleague'].get(path+suffix).status_code,404)
        self.assertEqual(self.clients['colleague'].get('/api/collaboration/journals').json['items'],[])
        with self.clients['colleague'].get('/api/export/content') as response:
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                self.assertEqual(json.loads(archive.read('content.json'))['journal_works'],[])
                self.assertFalse(any(k.startswith('journal-originals/') for k in archive.namelist()))
        self.assertEqual(self.call('/api/members/colleague',{'active':False},'admin','PUT').status_code,200)
        self.assertEqual(self.clients['colleague'].get(item['file_url']).status_code,401)
        with self.call('/api/backup',user='admin') as response:
            backup=Path(self.temp.name)/'legal-history-after-revocation.zip'
            backup.write_bytes(response.data)
        target=Path(self.temp.name)/'restored-legal-history'
        restore_backup(backup,target)
        restored=self.login('admin',create_app(target,testing=True))
        detail=restored.get(path).json
        self.assertFalse(detail['can_edit'])
        self.assertEqual(detail['current_product_id'],first.json['id'])
        with restored.get(detail['submissions'][0]['file_url']) as response:
            self.assertEqual(response.data,b'first original')
        self.assertEqual(len(restored.get(path+'/history').json['items']),3)

    def test_restore_rejects_missing_extra_forged_and_cross_work_history_even_when_rehashed(self):
        wid,other=self.work(),self.work()
        one=self.upload(wid).json['id']
        two=self.upload(other,key='other-journal-original').json['id']
        self.assertEqual(self.call(f'/api/collaboration/journals/{wid}/product',{'version':2,'submission_id':one}).status_code,200)
        self.assertEqual(self.call('/api/collaboration/qualifications/researcher',{'version':0,'enabled':True},'admin','PUT').status_code,200)
        topic=self.call('/api/collaboration/topics',{'theme':'交叉业务原件','participant_ids':[]}).json['id']
        self.assertEqual(self.call(f'/api/collaboration/topics/{topic}/candidates',{'version':0,'topic_version':1,'request_id':'cross-business-candidate'},file=('整体稿.txt',b'first original')).status_code,201)
        with self.call('/api/backup',user='admin') as response:
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                base={name:archive.read(name) for name in archive.namelist()}
        mutations=[
            ('fingerprint',"UPDATE journal_submissions SET request_hash='forged' WHERE work_id='"+wid+"'"),
            ('cross-business-file',"UPDATE journal_submissions SET file_id=(SELECT file_id FROM topic_candidates LIMIT 1) WHERE work_id='"+wid+"'; DELETE FROM handoff_files WHERE id NOT IN (SELECT file_id FROM topic_candidates UNION SELECT file_id FROM journal_submissions)"),
            ('missing-adoption-request',"DELETE FROM journal_product_requests WHERE work_id='"+wid+"'"),
            ('cross-product',"UPDATE journal_works SET current_product_id='"+two+"' WHERE id='"+wid+"'"),
            ('history-gap',"DELETE FROM journal_work_events WHERE work_id='"+wid+"' AND version=2"),
            ('uploader',"UPDATE journal_submissions SET uploader_id='colleague' WHERE work_id='"+wid+"'"),
            ('orphan',"DELETE FROM journal_product_requests WHERE work_id='"+wid+"'; DELETE FROM journal_submissions WHERE work_id='"+wid+"'"),
            ('extra-file',None),('missing-file',None),('wrong-bytes',None),
        ]
        for name,sql in mutations:
            with self.subTest(name=name):
                files=dict(base)
                manifest=json.loads(files['manifest.json'])
                if sql:
                    database=Path(self.temp.name)/(name+'.sqlite3')
                    database.write_bytes(files['platform.sqlite3'])
                    with closing(sqlite3.connect(database)) as db,db:
                        db.executescript(sql)
                        registered={r[0] for r in db.execute('SELECT stored_name FROM handoff_files')}
                    files['platform.sqlite3']=database.read_bytes()
                    if name=='cross-business-file':
                        files={k:v for k,v in files.items() if not k.startswith('handoffs/') or k.split('/',1)[1] in registered}
                key=next(k for k in files if k.startswith('handoffs/'))
                if name=='extra-file':
                    files['handoffs/'+'f'*32+'.txt']=b'unowned file'
                elif name=='missing-file':
                    files.pop(key)
                elif name=='wrong-bytes':
                    files[key]=b'forged bytes'
                manifest['files']={k:{'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()} for k,v in files.items() if k!='manifest.json'}
                files['manifest.json']=json.dumps(manifest).encode()
                corrupt=Path(self.temp.name)/(name+'.zip')
                with zipfile.ZipFile(corrupt,'w') as archive:
                    for key,value in files.items():archive.writestr(key,value)
                target=Path(self.temp.name)/('rejected-'+name)
                with self.assertRaises(ValueError):restore_backup(corrupt,target)
                self.assertFalse(target.exists())


del CollaborationTests

if __name__ == "__main__":
    unittest.main()
