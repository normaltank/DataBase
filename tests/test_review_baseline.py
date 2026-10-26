import io
import json
import unittest
import zipfile

from tests import test_workflow as fixture


class ReviewBaselineTests(unittest.TestCase):
    setUp = fixture.WorkflowTests.setUp
    login = fixture.WorkflowTests.login
    call = fixture.WorkflowTests.call
    source = fixture.WorkflowTests.source
    record = fixture.WorkflowTests.record
    detail = fixture.WorkflowTests.detail

    def test_review_requires_scope_and_note_without_partial_history(self):
        rid = self.record()
        before = self.clients['researcher'].get('/api/history/record/' + rid).json
        for extra in [{}, {'review_scope': 'metadata_only'}, {'review_note': '检查题录'},
                      {'review_scope': 'invalid', 'review_note': '检查题录'},
                      {'review_scope': 'metadata_only', 'review_note': '  '}]:
            result = self.call('/api/review/record/' + rid, {'version': 1, **extra}, user='admin')
            self.assertEqual(result.status_code, 400, result.json)
            self.assertEqual(self.detail(rid)['version'], 1)
            self.assertEqual(self.clients['researcher'].get('/api/history/record/' + rid).json, before)

    def test_record_latest_actual_review_survives_edit_recheck_and_restore(self):
        rid = self.record(title='核对原稿', body_html='<p>第一版</p>')
        payload = {'version': 1, 'review_scope': 'metadata_only', 'review_note': '对照合成目录的题名'}
        self.assertEqual(self.call('/api/review/record/' + rid, payload).status_code, 403)
        self.assertEqual(self.call('/api/review/record/' + rid, payload, user='admin').status_code, 200)
        reviewed = self.detail(rid)
        baseline = reviewed['last_verified']
        self.assertEqual((baseline['target_id'], baseline['version'], baseline['actor_id']), (rid, 2, 'admin'))
        self.assertEqual(baseline['review_scope'], 'metadata_only')
        self.assertEqual(baseline['review_note'], '对照合成目录的题名')
        self.assertFalse(baseline['same_as_submitter'])
        self.assertFalse(baseline['same_as_last_modifier'])
        self.assertEqual(baseline['last_modifier_id'], 'researcher')
        self.assertEqual(reviewed['last_modifier']['name'], '研究员 · 林')
        self.assertEqual(self.call('/api/records/' + rid, {'version': 2, 'body_html': '<p>第二版</p>'}, user='colleague', method='PUT').status_code, 200)
        edited = self.detail(rid)
        self.assertEqual(edited['status'], 'pending')
        self.assertEqual(edited['last_verified'], baseline)
        payload.update(version=3, review_scope='fulltext_and_bylines', review_note='第二次核对正文和署名')
        self.assertEqual(self.call('/api/review/record/' + rid, payload, user='admin').status_code, 200)
        latest = self.detail(rid)['last_verified']
        self.assertEqual(latest['last_modifier_id'], 'colleague')
        history = self.clients['researcher'].get('/api/history/record/' + rid).json['items']
        original = next(row for row in history if row['version'] == 1)
        self.assertEqual(self.call('/api/history/' + str(original['id']) + '/restore', {'version': 4}).status_code, 200)
        restored = self.detail(rid)
        self.assertEqual((restored['version'], restored['status'], restored['body_text']), (5, 'pending', '第一版'))
        self.assertEqual(restored['last_verified'], latest)
        self.assertEqual(len(restored['review_history']), 2)
        self.assertEqual(self.call('/api/review/record/' + rid, payload, user='admin').status_code, 409)

    def test_source_review_records_self_review_and_is_not_rolled_back_by_restore(self):
        created = self.call('/api/sources', {'name': '合成来源', 'kind': 'journal'}, user='admin')
        sid = created.json['id']
        url = '/api/sources/' + sid
        invalid = self.call('/api/review/source/' + sid, {'version': 1}, user='admin')
        self.assertEqual(invalid.status_code, 400)
        payload = {'version': 1, 'review_scope': 'metadata_only', 'review_note': '核对合成来源目录'}
        self.assertEqual(self.call('/api/review/source/' + sid, payload, user='admin').status_code, 200)
        baseline = self.clients['researcher'].get(url).json['last_verified']
        self.assertTrue(baseline['same_as_submitter'])
        self.assertTrue(baseline['same_as_last_modifier'])
        self.assertIsNone(baseline['same_as_author'])
        self.assertEqual(self.call(url, {'version': 2, 'notes': '共同维护新说明'}, method='PUT').status_code, 200)
        self.assertEqual(self.clients['researcher'].get(url).json['last_verified'], baseline)
        history = self.clients['researcher'].get('/api/history/source/' + sid).json['items']
        self.assertEqual(self.call('/api/history/' + str(history[-1]['id']) + '/restore', {'version': 3}).status_code, 200)
        current = self.clients['researcher'].get(url).json
        self.assertEqual(current['status'], 'pending')
        self.assertEqual(current['last_verified'], baseline)

    def test_review_export_backup_and_reader_permissions_preserve_only_summary(self):
        from platform_app.maintenance import create_backup, restore_backup
        from platform_app.web import create_app
        sid = self.source()
        rid = self.record(source_id=sid)
        for kind, target in [('source', sid), ('record', rid)]:
            payload = {'version': 1, 'review_scope': 'argument_and_translation', 'review_note': '合成核对说明 <证据>'}
            self.assertEqual(self.call('/api/review/' + kind + '/' + target, payload, user='admin').status_code, 200)
        self.assertEqual(self.call('/api/records/' + rid, {'version': 2, 'title': '核对后修改'}, method='PUT').status_code, 200)
        restricted = self.record(title='不可见秘密', visibility='restricted')
        self.assertEqual(self.call('/api/review/record/' + restricted, {'version': 1, 'review_scope': 'metadata_only', 'review_note': '不可见核对依据'}, user='admin').status_code, 200)
        archive = zipfile.ZipFile(io.BytesIO(self.clients['colleague'].get('/api/export/content').data))
        payload = json.loads(archive.read('content.json'))
        record = next(item for item in payload['records'] if item['id'] == rid)
        source = next(item for item in payload['sources'] if item['id'] == sid)
        self.assertEqual(record['status'], 'pending')
        self.assertEqual(record['last_verified']['version'], 2)
        self.assertEqual(source['last_verified']['version'], 2)
        coverage = json.loads(archive.read('evidence-coverage.json'))
        self.assertEqual(next(item for item in coverage['records'] if item['id'] == rid)['last_verified'], record['last_verified'])
        self.assertEqual(next(item for item in coverage['sources'] if item['id'] == sid)['last_verified'], source['last_verified'])
        self.assertIn('合成核对说明 &lt;证据&gt;', archive.read('review.html').decode())
        source_html = next(name for name in archive.namelist() if name.startswith('sources/'))
        self.assertIn('合成核对说明 &lt;证据&gt;', archive.read(source_html).decode())
        for name in archive.namelist():
            if name.endswith(('.html', '.json')):
                content = archive.read(name).decode()
                self.assertNotIn('不可见秘密', content)
                self.assertNotIn('不可见核对依据', content)
                self.assertNotIn('raw_json', content)
        target = self.data_dir.parent / 'restored'
        restore_backup(create_backup(self.data_dir), target)
        restored_app = create_app(target, testing=True)
        restored_reader = self.login('colleague', restored_app)
        for kind, target_id in [('records', rid), ('sources', sid)]:
            self.assertEqual(restored_reader.get('/api/' + kind + '/' + target_id).json['last_verified'],
                             self.clients['colleague'].get('/api/' + kind + '/' + target_id).json['last_verified'])
        self.assertEqual(restored_reader.get('/api/records/' + restricted).status_code, 404)

    def test_legacy_review_facts_remain_unknown_after_reopening_schema11(self):
        from platform_app.store import connect
        from platform_app.web import create_app
        rid = self.record()
        # Arrange the exact old revision shape: actor/time/version were saved, no review facts.
        with connect(self.data_dir / 'platform.sqlite3') as db:
            snapshot = json.loads(db.execute('SELECT snapshot_json FROM revisions WHERE target_id=?', (rid,)).fetchone()[0])
            snapshot.update(version=2, status='verified')
            db.execute("UPDATE records SET version=2,status='verified' WHERE id=?", (rid,))
            db.execute("INSERT INTO revisions(target_type,target_id,action,actor_id,created_at,snapshot_json) VALUES ('record',?,'完成信息核对','admin','2026-10-20T10:00:00',?)", (rid, json.dumps(snapshot)))
        client = self.login('researcher', create_app(self.data_dir, testing=True))
        event = client.get('/api/records/' + rid).json['last_verified']
        self.assertEqual((event['version'], event['actor_id'], event['created_at']), (2, 'admin', '2026-10-20T10:00:00'))
        for key in ['review_scope', 'review_note', 'same_as_submitter', 'same_as_last_modifier']:
            self.assertIsNone(event[key])
        archive = zipfile.ZipFile(io.BytesIO(client.get('/api/export/content').data))
        self.assertIn('历史未注明', archive.read('review.html').decode())

    def test_reviewed_personal_report_reader_sees_summary_without_body_history_access(self):
        rid = self.record(kind='research_report')
        payload = {'version': 1, 'review_scope': 'argument_and_translation', 'review_note': '作者授权范围未改变'}
        self.assertEqual(self.call('/api/review/record/' + rid, payload, user='admin').status_code, 200)
        reader = self.detail(rid, 'colleague')
        self.assertEqual(reader['last_verified']['author_id'], 'researcher')
        self.assertFalse(reader['last_verified']['same_as_author'])
        self.assertEqual(self.clients['colleague'].get('/api/history/record/' + rid).status_code, 403)
        self.assertEqual(self.clients['admin'].get('/api/history/record/' + rid).status_code, 403)
        self.assertEqual(self.call('/api/records/' + rid, {'version': 2, 'body_html': '<p>越权</p>'}, user='admin', method='PUT').status_code, 403)
        self.assertEqual(self.detail(rid)['last_verified'], reader['last_verified'])

    def test_merged_record_and_source_preserve_original_review_identity(self):
        for kind in ['record', 'source']:
            if kind == 'record':
                keep, duplicate = self.record(title='保留'), self.record(title='原身份')
            else:
                keep, duplicate = self.source('保留'), self.source('原身份')
            payload = {'version': 1, 'review_scope': 'metadata_only', 'review_note': '原身份的核对依据'}
            self.assertEqual(self.call('/api/review/' + kind + '/' + duplicate, payload, user='admin').status_code, 200)
            merged = self.call('/api/merge', {'type': kind, 'keep_id': keep, 'duplicate_id': duplicate,
                'keep_version': 1, 'duplicate_version': 2, 'confirmed': True}, user='admin')
            self.assertEqual(merged.status_code, 200, merged.json)
            url = '/api/' + ('records/' if kind == 'record' else 'sources/')
            canonical = self.clients['researcher'].get(url + keep).json
            original = self.clients['researcher'].get(url + duplicate).json
            self.assertEqual(canonical['last_verified']['target_id'], duplicate)
            self.assertEqual(canonical['last_verified']['version'], 2)
            self.assertEqual(canonical['last_verified'], original['last_verified'])

    def test_sharing_current_merged_record_does_not_publish_private_review_origin(self):
        keep = self.record(visibility='restricted', title='后来共享')
        duplicate = self.record(visibility='restricted', title='旧私人身份')
        payload = {'version': 1, 'review_scope': 'metadata_only', 'review_note': '私人核对依据'}
        self.assertEqual(self.call('/api/review/record/' + duplicate, payload, user='admin').status_code, 200)
        merged = self.call('/api/merge', {'type': 'record', 'keep_id': keep, 'duplicate_id': duplicate,
            'keep_version': 1, 'duplicate_version': 2, 'confirmed': True}, user='admin')
        self.assertEqual(merged.status_code, 200, merged.json)
        current = self.detail(keep)
        self.assertEqual(self.call('/api/records/' + keep, {'version': current['version'], 'visibility': 'shared'}, method='PUT').status_code, 200)
        shared = self.detail(keep, 'colleague')
        self.assertIsNone(shared['last_verified'])
        self.assertEqual(shared['review_history'], [])
        archive = zipfile.ZipFile(io.BytesIO(self.clients['colleague'].get('/api/export/content').data))
        for name in ['content.json', 'review.html', 'evidence-coverage.json']:
            self.assertNotIn('私人核对依据', archive.read(name).decode())
            self.assertNotIn(duplicate, archive.read(name).decode())

    def test_repeated_review_does_not_make_previous_reviewer_the_content_modifier(self):
        rid = self.record()
        payload = {'version': 1, 'review_scope': 'metadata_only', 'review_note': '首次合成核对'}
        self.assertEqual(self.call('/api/review/record/' + rid, payload, user='admin').status_code, 200)
        payload.update(version=2, review_note='复查同一正文')
        self.assertEqual(self.call('/api/review/record/' + rid, payload, user='admin').status_code, 200)
        current = self.detail(rid)
        self.assertEqual(current['last_verified']['last_modifier_id'], 'researcher')
        self.assertFalse(current['last_verified']['same_as_last_modifier'])
        self.assertEqual([row['version'] for row in current['review_history']], [3, 2])

    def test_source_review_storage_failure_leaves_no_partial_event(self):
        from platform_app.store import connect
        sid = self.source()
        url = '/api/sources/' + sid
        before = self.clients['researcher'].get(url).json
        history = self.clients['researcher'].get('/api/history/source/' + sid).json
        # Inject a storage fault only; every assertion stays at the HTTP seam.
        with connect(self.data_dir / 'platform.sqlite3') as db:
            db.execute("CREATE TRIGGER synthetic_review_failure BEFORE INSERT ON revisions BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        result = self.call('/api/review/source/' + sid, {'version': 1, 'review_scope': 'metadata_only', 'review_note': '不会部分写入'}, user='admin')
        self.assertEqual(result.status_code, 409, result.json)
        self.assertEqual(self.clients['researcher'].get(url).json, before)
        self.assertEqual(self.clients['researcher'].get('/api/history/source/' + sid).json, history)
