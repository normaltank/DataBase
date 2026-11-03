"""Two-stage handoffs exercised through authenticated HTTP and backup restore."""
import unittest
import io
import json
import zipfile
from pathlib import Path
from platform_app.maintenance import create_backup, restore_backup
from platform_app.web import create_app
from tests import test_collaboration as base


class HandoffTests(unittest.TestCase):
    setUp = base.CollaborationTests.setUp
    login = base.CollaborationTests.login
    call = base.CollaborationTests.call
    topic = base.CollaborationTests.topic

    def board(self, tid, who='researcher'):
        response = self.clients[who].get(f'/api/collaboration/topics/{tid}/handoffs')
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def test_no_meeting_direct_advance_and_selection_review(self):
        tid = self.topic()
        result = self.call(f'/api/collaboration/topics/{tid}/enter-compilation', {
            'request_id': 'direct-advance-once', 'topic_version': 1, 'stage_version': 1})
        self.assertEqual(result.status_code, 201, result.json)
        self.assertEqual(self.board(tid)['stage'], 'compilation')

    def upload(self, tid, who='colleague', stage='selection', material_ref=None, key=None, **extra):
        data = dict(stage=stage, token=self.board(tid, who)['token'], request_id=key or __import__('uuid').uuid4().hex, note='合成说明', **extra)
        if material_ref:
            data['material_ref'] = material_ref
            material=next(m for m in self.board(tid,who)['materials'] if m['ref']==material_ref)
            if material['legacy']:
                data['source_ref']=material['versions'][0]['ref']
        return self.call(f'/api/collaboration/topics/{tid}/handoffs', data, who, file=('合成材料.txt', b'synthetic original'))

    def decide(self, tid, ref, decision='returned', who='researcher', **extra):
        return self.call(f'/api/collaboration/topics/{tid}/handoff-reviews', dict(token=self.board(tid, who)['token'], request_id=__import__('uuid').uuid4().hex, version_ref=ref, decision=decision, **extra), who)

    def test_selection_material_can_be_returned_without_note_then_new_version_approved(self):
        tid = self.topic()
        first = self.upload(tid)
        self.assertEqual(first.status_code, 201, first.json)
        item = self.board(tid)['materials'][0]
        self.assertEqual(self.decide(tid, item['versions'][0]['ref']).status_code, 201)
        self.assertEqual(self.board(tid)['materials'][0]['status'], 'returned')
        second = self.upload(tid, material_ref=first.json['material_ref'])
        self.assertEqual(second.status_code, 201, second.json)
        item = self.board(tid)['materials'][0]
        self.assertEqual(item['status'], 'pending')
        self.assertEqual(len(item['versions']), 2)
        self.assertEqual(self.decide(tid, item['versions'][0]['ref'], 'approved').status_code, 201)
        self.assertEqual(self.upload(tid, material_ref=first.json['material_ref']).status_code, 201)
        item = self.board(tid)['materials'][0]
        self.assertEqual(item['status'], 'pending')
        self.assertEqual(item['versions'][1]['status'], 'approved')
        for v in item['versions']:
            with self.clients['researcher'].get(v['file_url']) as original:
                self.assertEqual(original.data, b'synthetic original')

    def test_two_people_two_stages_multiple_materials_and_closed_restore(self):
        tid = self.topic()
        for who in ('colleague', 'researcher'):
            for n in range(2):
                submitted = self.upload(tid, who)
                self.assertEqual(submitted.status_code, 201, submitted.json)
                m = next(m for m in self.board(tid)['materials'] if m['ref'] == submitted.json['material_ref'])
                self.assertEqual(self.decide(tid, m['versions'][0]['ref']).status_code, 201)
                self.assertEqual(self.upload(tid, who, material_ref=m['ref']).status_code, 201)
                m = next(x for x in self.board(tid)['materials'] if x['ref'] == m['ref'])
                self.assertEqual(self.decide(tid, m['versions'][0]['ref'], 'approved').status_code, 201)
        self.assertEqual(self.call(f'/api/collaboration/topics/{tid}/enter-compilation', dict(request_id='two-stage-direct', topic_version=1, stage_version=1)).status_code, 201)
        for who in ('colleague', 'researcher'):
            for n in range(2):
                submitted = self.upload(tid, who, 'compilation')
                self.assertEqual(submitted.status_code, 201, submitted.json)
                m = next(m for m in self.board(tid)['materials'] if m['ref'] == submitted.json['material_ref'])
                self.assertEqual(self.decide(tid, m['versions'][0]['ref']).status_code, 201)
                self.assertEqual(self.upload(tid, who, 'compilation', m['ref']).status_code, 201)
                m = next(x for x in self.board(tid)['materials'] if x['ref'] == m['ref'])
                self.assertEqual(self.decide(tid, m['versions'][0]['ref'], 'approved').status_code, 201)
        self.assertEqual(self.upload(tid).status_code, 201)  # selection remains open
        b = self.board(tid)
        self.assertEqual(len(b['materials']), 9)
        for scope, expected in (('all', 9), ('process', 9), ('products', 0)):
            with self.clients['researcher'].get(f'/api/collaboration/materials/topic/{tid}?scope={scope}') as response:
                self.assertEqual(response.status_code, 200)
                with zipfile.ZipFile(io.BytesIO(response.data)) as z:
                    manifest = json.loads(z.read('manifest.json'))
                    self.assertEqual(len(manifest['handoffs']['materials']), expected)
                package = Path(self.temp.name) / (scope + '.zip')
                package.write_bytes(response.data)
                from scripts.verify_work_materials import verify
                verify(package)
        preview = self.clients['researcher'].get(f'/api/collaboration/topics/{tid}/closure-preview').json
        self.assertEqual(self.call(f'/api/collaboration/topics/{tid}/end', dict(request_id='direct-end-once', confirm=True, **{k:preview[k] for k in ('basis_token','lifecycle_version')})).status_code, 201)
        closed = self.board(tid)
        self.assertTrue(closed['is_lead'])
        self.assertFalse(closed['can_manage'])
        self.assertEqual(self.upload(tid).status_code, 409)
        restored = Path(self.temp.name) / 'restored'
        restore_backup(create_backup(self.data_dir), restored)
        app = create_app(restored, testing=True)
        client = self.login('researcher', app)
        recovered = client.get(f'/api/collaboration/topics/{tid}/handoffs').json
        self.assertEqual(recovered['materials'], closed['materials'])
        self.assertEqual(self.call(f'/api/collaboration/topics/{tid}/reopen', dict(request_id='direct-reopen-once', lifecycle_version=closed['lifecycle_version'])).status_code, 201)
        self.assertEqual(self.board(tid)['stage'], 'compilation')

    def test_authority_retry_and_conflict_preserve_exact_version(self):
        tid = self.topic()
        b = self.board(tid)
        data = dict(stage='selection', token=b['token'], request_id='unknown-result-upload')
        url = f'/api/collaboration/topics/{tid}/handoffs'
        first = self.call(url, data, 'colleague', file=('one.txt', b'first'))
        self.assertEqual(first.status_code, 201, first.json)
        retry = self.call(url, data, 'colleague', file=('one.txt', b'first'))
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(first.json['id'], retry.json['id'])
        self.assertEqual(self.call(url, data, 'colleague', file=('one.txt', b'changed')).status_code, 409)
        self.assertEqual(self.upload(tid, 'researcher', material_ref=first.json['material_ref']).status_code, 403)
        self.assertEqual(self.upload(tid, 'admin').status_code, 403)
        m = self.board(tid)['materials'][0]
        self.assertEqual(self.decide(tid, m['versions'][0]['ref'], who='colleague').status_code, 403)
        self.assertEqual(self.decide(tid, m['versions'][0]['ref'], who='admin').status_code, 403)
        preview = self.clients['researcher'].get(f'/api/collaboration/topics/{tid}/closure-preview').json
        self.assertEqual(self.decide(tid, m['versions'][0]['ref'], 'approved').status_code, 201)
        self.assertEqual(self.call(f'/api/collaboration/topics/{tid}/end', dict(request_id='stale-review-end', confirm=True, **{k:preview[k] for k in ('basis_token','lifecycle_version')})).status_code, 409)
        self.assertEqual(self.call('/api/collaboration/qualifications/researcher', dict(version=1,enabled=False), 'admin', 'PUT').status_code, 200)
        self.assertEqual(self.decide(tid, m['versions'][0]['ref']).status_code, 403)

    def test_docx_preview_is_text_and_each_original_is_exact(self):
        tid = self.topic()
        originals = [base.CollaborationTests.docx('合成正文第一版 &lt;test&gt;'), base.CollaborationTests.docx('合成正文第二版')]
        ref = None
        for i, raw in enumerate(originals):
            data = dict(stage='selection', request_id=f'docx-original-{i}', token=self.board(tid)['token'])
            if ref:
                data['material_ref'] = ref
            r = self.call(f'/api/collaboration/topics/{tid}/handoffs', data, 'colleague', file=('合成文件.docx', raw))
            self.assertEqual(r.status_code, 201, r.json)
            ref = r.json['material_ref']
        material = self.board(tid)['materials'][0]
        for v, raw in zip(reversed(material['versions']), originals):
            with self.clients['researcher'].get(v['file_url']) as r:
                self.assertEqual(r.data, raw)
            preview = self.clients['researcher'].get(f'/api/collaboration/topics/{tid}/handoff-preview', query_string={'version_ref':v['ref']})
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview.json['status'], 'ready')
            self.assertIn('合成正文', preview.json['segments'][0]['text'])
        other = self.topic([])
        self.assertEqual(self.clients['researcher'].get(f'/api/collaboration/topics/{other}/handoff-preview',query_string={'version_ref':v['ref']}).status_code, 404)

    def test_legacy_author_change_continues_own_series_and_restores_exact_adoption(self):
        from tests.test_topic_finals import TopicFinalTests
        from platform_app.store import connect
        from contextlib import closing
        helper = TopicFinalTests()
        for key in ('app', 'clients', 'data_dir'):
            setattr(helper, key, getattr(self, key))
        tid, aid, sid = helper.ready()
        final = helper.final(tid, aid, sid).json
        self.assertEqual(helper.summary(tid, [final['id']]).status_code, 201)
        meeting = helper.workflow(tid)['meetings'][0]['assignments']
        meeting[0]['author_id'] = 'researcher'
        self.assertEqual(helper.meeting(tid, meeting, version=1).status_code, 201)
        self.assertEqual(helper.draft(tid, aid, version=1, who='researcher', meeting_version=2).status_code, 201)
        with closing(connect(self.data_dir / 'platform.sqlite3')) as db:
            snapshot = {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY id')] for table in ('topic_candidates','topic_meetings','topic_manuscripts','topic_returns','topic_finals','topic_summaries')}
        b = self.board(tid)
        previous = next(m for m in b['materials'] if m['owner_id']=='colleague' and m['stage']=='compilation')
        self.assertEqual(self.upload(tid, 'researcher', 'compilation', previous['ref']).status_code, 403)
        continued = self.upload(tid, 'colleague', 'compilation', previous['ref'])
        self.assertEqual(continued.status_code, 201, continued.json)
        b = self.board(tid)
        fresh = next(m for m in b['materials'] if m['ref']==continued.json['material_ref'])
        self.assertEqual(fresh['source_ref'], previous['versions'][0]['ref'])
        self.assertEqual(fresh['versions'][0]['version'], 1)
        with closing(connect(self.data_dir / 'platform.sqlite3')) as db:
            self.assertEqual(snapshot, {table:[tuple(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY id')] for table in snapshot})
        restored = Path(self.temp.name) / 'legacy-and-direct-restored'
        restore_backup(create_backup(self.data_dir), restored)
        client = self.login('researcher', create_app(restored, testing=True))
        self.assertEqual(client.get(f'/api/collaboration/topics/{tid}/handoffs').json['materials'], b['materials'])
        fixed = client.get(f'/api/collaboration/topics/{tid}/workflow').json['summaries'][0]['adoptions'][0]
        self.assertEqual(fixed['submission_id'], sid)
        with client.get(fixed['file_url']) as r:
            self.assertEqual(r.data, b'independent final original')

    def test_schema26_closed_history_upgrades_without_rewriting_rows(self):
        from tests.test_topic_finals import TopicFinalTests
        from platform_app import topic_closure, topic_stages, topic_handoffs, topic_review
        from platform_app.store import connect
        from contextlib import closing
        helper = TopicFinalTests()
        for key in ('app','clients','data_dir'):
            setattr(helper, key, getattr(self, key))
        tid, aid, sid = helper.ready()
        final = helper.final(tid, aid, sid).json
        helper.summary(tid, [final['id']])
        preview = self.clients['researcher'].get(f'/api/collaboration/topics/{tid}/closure-preview').json
        self.call(f'/api/collaboration/topics/{tid}/end', dict(request_id='old26-end-once', confirm=True, lifecycle_version=preview['lifecycle_version'], basis_token=preview['basis_token']))
        # Synthetic pre-27 fixture: actual legacy meeting/stage and closure formats.
        with closing(connect(self.data_dir / 'platform.sqlite3')) as db, db:
            meeting = db.execute('SELECT * FROM topic_meetings WHERE topic_id=?',(tid,)).fetchone()
            event = db.execute('SELECT * FROM topic_stage_events WHERE topic_id=?',(tid,)).fetchone()
            data = json.loads(event['request_json']);data.pop('decision_kind',None);data['meeting_version']=meeting['version']
            db.execute('UPDATE topic_stage_events SET meeting_id=?,request_json=?,request_hash=? WHERE id=?',(meeting['id'],json.dumps(data,ensure_ascii=False),topic_review.fingerprint(data),event['id']))
            end = db.execute('SELECT * FROM topic_closure_events WHERE topic_id=?',(tid,)).fetchone()
            saved = json.loads(end['basis_json']);saved.pop('format_version')
            for table in topic_handoffs.TABLES:
                saved['materials'].pop(table)
            gaps = topic_closure.incomplete(db,saved)
            request_data=json.loads(end['request_json']);request_data['basis_token']=topic_review.fingerprint(saved)
            db.execute('UPDATE topic_closure_events SET basis_json=?,incomplete_json=?,request_json=?,request_hash=? WHERE id=?',(json.dumps(saved,ensure_ascii=False),json.dumps(gaps,ensure_ascii=False),json.dumps(request_data,ensure_ascii=False),topic_review.fingerprint({'action':'end','data':request_data}),end['id']))
            for table in reversed(topic_handoffs.TABLES):
                db.execute(f'DROP TABLE {table}')
            db.execute('ALTER TABLE topic_stage_events RENAME TO stage_direct_fixture')
            db.execute(topic_stages.SCHEMA[1])
            db.execute('INSERT INTO topic_stage_events SELECT * FROM stage_direct_fixture')
            db.execute('DROP TABLE stage_direct_fixture')
            db.execute("UPDATE settings SET value='26' WHERE key='schema_version'")
            tables=(*topic_closure.WORK_TABLES,'topic_stages','topic_stage_events','topic_closures','topic_closure_events','handoff_files')
            before={t:[tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in tables}
        destination=Path(self.temp.name)/'old26-restored'
        restore_backup(create_backup(self.data_dir),destination)
        upgraded=create_app(destination,testing=True)
        create_app(destination,testing=True)  # repeat startup must be inert
        with closing(connect(destination/'platform.sqlite3')) as db:
            self.assertEqual(before,{t:[tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in tables})
        lead=self.login('researcher',upgraded)
        b=lead.get(f'/api/collaboration/topics/{tid}/handoffs').json
        self.assertEqual(b['lifecycle_events'][0]['basis'],saved)
        self.assertEqual(b['stage_events'][0]['meeting_id'],meeting['id'])
        csrf=lead.get('/api/session').json['csrf']
        reopened=lead.post(f'/api/collaboration/topics/{tid}/reopen',json={'request_id':'reopen-old26','lifecycle_version':2},headers={'X-CSRF-Token':csrf})
        self.assertEqual(reopened.status_code,201,reopened.json)
        restore_backup(create_backup(destination),Path(self.temp.name)/'old26-plus-reopen')

    def test_restore_rejects_cross_topic_review_even_with_rehashed_archive(self):
        import sqlite3
        import hashlib
        tid=self.topic()
        self.upload(tid)
        v=self.board(tid)['materials'][0]['versions'][0]
        result=self.call(f'/api/collaboration/topics/{tid}/handoff-reviews',dict(request_id='review-with-attachment',token=self.board(tid)['token'],version_ref=v['ref'],decision='returned'),'researcher',file=('review.txt',b'synthetic review bytes'))
        self.assertEqual(result.status_code,201,result.json)
        backup=create_backup(self.data_dir)
        with zipfile.ZipFile(backup) as z:
            files={name:z.read(name) for name in z.namelist()}
        database=Path(self.temp.name)/'corrupt.sqlite3';database.write_bytes(files['platform.sqlite3'])
        from contextlib import closing
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("UPDATE topic_material_reviews SET version_ref='version:missing'")
        files['platform.sqlite3']=database.read_bytes()
        manifest=json.loads(files['manifest.json'])
        manifest['files']['platform.sqlite3']={'bytes':len(files['platform.sqlite3']),'sha256':hashlib.sha256(files['platform.sqlite3']).hexdigest()}
        files['manifest.json']=json.dumps(manifest).encode()
        bad=Path(self.temp.name)/'corrupt.zip'
        with zipfile.ZipFile(bad,'w') as z:
            for name,raw in files.items():z.writestr(name,raw)
        with self.assertRaises(ValueError):restore_backup(bad,Path(self.temp.name)/'rejected')
        good=Path(self.temp.name)/'attachment-restored'
        restore_backup(backup,good)
        recovered=self.login('researcher',create_app(good,testing=True)).get(f'/api/collaboration/topics/{tid}/handoffs').json
        review_file=recovered['materials'][0]['versions'][0]['reviews'][0]
        with self.clients['researcher'].get(review_file['file_url']) as r:
            self.assertEqual(r.data,b'synthetic review bytes')

    def test_concurrent_new_version_and_review_have_one_legal_winner_and_failure_cleans_file(self):
        from concurrent.futures import ThreadPoolExecutor
        from platform_app.store import connect
        from contextlib import closing
        tid=self.topic()
        first=self.upload(tid)
        b=self.board(tid);m=b['materials'][0];v=m['versions'][0]
        upload_data=dict(request_id='racing-revision',token=b['token'],stage='selection',material_ref=m['ref'])
        review_data=dict(request_id='racing-review',token=b['token'],version_ref=v['ref'],decision='approved')
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(self.call,f'/api/collaboration/topics/{tid}/handoffs',upload_data,'colleague',file=('race.txt',b'racing original'))
            r=pool.submit(self.call,f'/api/collaboration/topics/{tid}/handoff-reviews',review_data)
            statuses=a.result().status_code,r.result().status_code
        self.assertIn(statuses,((201,409),(409,201)))
        current=self.board(tid)['materials'][0]
        if statuses[0]==201:
            self.assertEqual(current['status'],'pending')
            self.assertEqual(len(current['versions']),2)
        else:
            self.assertEqual(current['status'],'approved')
            self.assertEqual(len(current['versions']),1)
        before={p.name:p.read_bytes() for p in (self.data_dir/'handoffs').iterdir()}
        with closing(connect(self.data_dir/'platform.sqlite3')) as db,db:
            db.execute("CREATE TRIGGER reject_material_version BEFORE INSERT ON topic_material_versions BEGIN SELECT RAISE(ABORT,'synthetic failure after original save'); END")
        failed=self.upload(tid,material_ref=first.json['material_ref'])
        self.assertEqual(failed.status_code,409,failed.json)
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.data_dir/'handoffs').iterdir()})
        self.assertEqual(self.board(tid)['materials'][0],current)
