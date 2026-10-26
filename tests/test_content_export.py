import io
import unittest
import test_workflow as workflow_tests


class ContentExportTests(unittest.TestCase):
    setUp = workflow_tests.WorkflowTests.setUp
    login = workflow_tests.WorkflowTests.login
    call = workflow_tests.WorkflowTests.call
    record = workflow_tests.WorkflowTests.record
    detail = workflow_tests.WorkflowTests.detail

    def test_export_rejects_same_length_attachment_tampering(self):
        result = self.call('/api/records', {'kind': 'report', 'title': '附件校验', 'sharing_confirmed': True}, file=('evidence.txt', b'original'))
        self.assertEqual(result.status_code, 201)
        path = next((self.data_dir / 'uploads').iterdir())
        path.write_bytes(b'modified')
        response = self.clients['researcher'].get('/api/export/content')
        self.assertEqual(response.status_code, 409)
        self.assertIn('不一致', response.json['error'])


    def test_coverage_separates_current_content_from_pinned_citations(self):
        import json
        import zipfile
        original = self.record(title='原文', body_html='<p>当前正文</p>')
        note = self.record('research_note', evidence_record_id=original, quote='固定摘录', locator='p1')
        ordinary = self.record('research_note', title='普通笔记')
        report = self.record('research_report', evidence_ids=[note, ordinary])
        self.call('/api/records/' + original, {'version': 1, 'body_html': '<p>后来正文</p>'}, method='PUT')
        response = self.clients['researcher'].get('/api/export/content?kind=research_report')
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            coverage = json.loads(archive.read('evidence-coverage.json'))
            row = next(r for r in coverage['records'] if r['id'] == report)
            pinned = next(c for c in row['citations'] if c['excerpt_id'] == note)
            self.assertTrue(pinned['original_metadata'])
            self.assertFalse(pinned['original_body'])
            self.assertTrue(pinned['quote'])
            self.assertEqual(pinned['attachment'], None)
            plain = next(c for c in row['citations'] if c['excerpt_id'] == ordinary)
            self.assertFalse(plain['original_metadata'])
            self.assertIn('未建立固定原文依据', plain['notice'])
            self.assertIn('review.html', archive.namelist())

    def test_metadata_only_original_and_ordinary_note_do_not_claim_retained_original(self):
        import json
        import zipfile
        original = self.record(title='只有题录与外链', url='https://example.org/original?a=1&b=2', doi='10.1234/example')
        ordinary = self.record('research_note', title='没有固定原文的普通笔记', body_html='<p>研究员自己的想法</p>')
        output = self.clients['researcher'].get('/api/export/content')
        self.assertEqual(output.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(output.data)) as archive:
            coverage = json.loads(archive.read('evidence-coverage.json'))
            row = next(r for r in coverage['records'] if r['id'] == original)
            self.assertTrue(row['current']['metadata'])
            self.assertFalse(row['current']['body'])
            self.assertEqual(row['current']['attachments'], [])
            self.assertEqual(row['current']['external_url'], 'https://example.org/original?a=1&b=2')
            self.assertEqual(row['current']['doi'], '10.1234/example')
            self.assertEqual(row['evidence']['notice'], '本条未登记固定原文依据。')
            note = next(r for r in coverage['records'] if r['id'] == ordinary)
            self.assertTrue(note['current']['body'])
            self.assertFalse(note['evidence']['original_body'])
            self.assertIn('普通笔记未建立固定原文依据', note['evidence']['notice'])
            review = archive.read('review.html').decode()
            self.assertIn('含题录；无网页正文', review)
            self.assertIn('当前外部链接（不表示网页已留存）', review)
            self.assertIn('href="https://example.org/original?a=1&amp;b=2"', review)
            self.assertIn('当前 DOI：10.1234/example', review)

    def test_download_manifest_passes_standalone_verifier(self):
        import subprocess
        import sys
        self.record(title='独立校验正常包')
        response = self.clients['researcher'].get('/api/export/content')
        target = self.data_dir / 'download.zip'
        target.write_bytes(response.data)
        script = __import__('pathlib').Path(__file__).resolve().parents[1] / 'scripts' / 'verify_content_export.py'
        result = subprocess.run([sys.executable, '-I', str(script), str(target)], cwd=self.data_dir, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pinned_attachment_survives_updates_and_private_original_is_omitted(self):
        import json
        import zipfile
        original = self.record(title='旧原文题名', body_html='<p>原文初版</p>')
        self.call('/api/records/' + original, {'version': 1, 'sharing_confirmed': True}, method='PUT', file=('old.txt', b'old original'))
        aid = self.detail(original)['attachments'][0]['id']
        note = self.record('research_note', title='证据笔记', evidence_record_id=original, evidence_attachment_id=aid, quote='旧摘录', locator='p2')
        private = self.record('research_note', title='隐藏笔记标题', visibility='restricted')
        report = self.record('research_report', evidence_ids=[note, private])
        self.call('/api/records/' + original, {'version': 2, 'body_html': '<p>新正文</p>', 'sharing_confirmed': True}, method='PUT', file=('new.txt', b'new original'))
        self.call('/api/records/' + note, {'version': 1, 'quote': '新摘录'}, method='PUT')
        output = self.clients['colleague'].get('/api/export/content?kind=research_report')
        with zipfile.ZipFile(io.BytesIO(output.data)) as archive:
            coverage = json.loads(archive.read('evidence-coverage.json'))
            row = next(r for r in coverage['records'] if r['id'] == report)
            self.assertEqual(len(row['citations']), 1)
            pinned = row['citations'][0]
            self.assertEqual(pinned['original_version'], 2)
            self.assertEqual(pinned['excerpt_version'], 1)
            self.assertEqual(archive.read(pinned['attachment']['path']), b'old original')
            self.assertFalse(pinned['original_body'])
            html = archive.read(row['path']).decode()
            self.assertIn('旧摘录', html)
            self.assertNotIn('新摘录', html)
            self.assertNotIn(private, archive.read('evidence-coverage.json').decode())
        self.call('/api/records/' + original, {'version': 3, 'visibility': 'restricted'}, method='PUT')
        output = self.clients['colleague'].get('/api/export/content?kind=research_report')
        with zipfile.ZipFile(io.BytesIO(output.data)) as archive:
            coverage = json.loads(archive.read('evidence-coverage.json'))
            self.assertEqual([r['id'] for r in coverage['records']], [report])
            self.assertEqual(coverage['records'][0]['citations'], [])
            for name in ['evidence-coverage.json', 'review.html']:
                text = archive.read(name).decode()
                for hidden in [original, note, private, '旧原文题名', '隐藏笔记标题']:
                    self.assertNotIn(hidden, text)

    def test_missing_and_wrong_registered_size_refuse_export(self):
        from contextlib import closing
        from platform_app.store import connect
        result = self.call('/api/records', {'kind': 'report', 'title': '大小校验', 'sharing_confirmed': True}, file=('evidence.txt', b'abc'))
        self.assertEqual(result.status_code, 201)
        with closing(connect(self.data_dir / 'platform.sqlite3')) as db:
            db.execute('UPDATE attachments SET bytes=4')
            db.commit()
        response = self.clients['researcher'].get('/api/export/content')
        self.assertEqual(response.status_code, 409)
        next((self.data_dir / 'uploads').iterdir()).unlink()
        response = self.clients['researcher'].get('/api/export/content')
        self.assertEqual(response.status_code, 409)
        self.assertIn('缺失', response.json['error'])

    def test_legacy_snapshot_body_remains_explicitly_historical(self):
        import json
        import zipfile
        from contextlib import closing
        from platform_app.store import connect
        original = self.record(title='仅题录原文', url='https://example.org/original')
        note = self.record('research_note', evidence_record_id=original, quote='摘录', locator='p1')
        # A legacy fixture contains body text which new snapshots do not capture.
        with closing(connect(self.data_dir / 'platform.sqlite3')) as db:
            snap = json.loads(db.execute('SELECT evidence_snapshot_json FROM records WHERE id=?', (note,)).fetchone()[0])
            snap['body_html'] = '<p>旧快照保留正文</p>'
            db.execute('UPDATE records SET evidence_snapshot_json=? WHERE id=?', (json.dumps(snap), note))
            db.commit()
        report = self.record('research_report', evidence_ids=[note])
        output = self.clients['researcher'].get('/api/export/content?kind=research_report')
        with zipfile.ZipFile(io.BytesIO(output.data)) as archive:
            coverage = json.loads(archive.read('evidence-coverage.json'))
            row = next(r for r in coverage['records'] if r['id'] == report)
            self.assertTrue(row['citations'][0]['original_body'])
            self.assertIn('旧快照保留正文', archive.read(row['path']).decode())
            raw = next(r for r in coverage['records'] if r['id'] == original)
            self.assertFalse(raw['current']['body'])

    def test_merge_keeps_pinned_original_identity_and_attachment(self):
        import json
        import zipfile
        keep = self.record(title='保留资料')
        old = self.record(title='归并前题名')
        self.call('/api/records/' + old, {'version': 1, 'sharing_confirmed': True}, method='PUT', file=('old.txt', b'old identity original'))
        aid = self.detail(old)['attachments'][0]['id']
        note = self.record('research_note', evidence_record_id=old, evidence_attachment_id=aid, quote='归并前摘录', locator='p1')
        report = self.record('research_report', evidence_ids=[note])
        response = self.call('/api/merge', {'type': 'record', 'keep_id': keep, 'duplicate_id': old, 'keep_version': 1, 'duplicate_version': 2, 'confirmed': True}, user='admin')
        self.assertEqual(response.status_code, 200, response.json)
        output = self.clients['researcher'].get('/api/export/content?kind=research_report')
        self.assertEqual(output.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(output.data)) as archive:
            coverage = json.loads(archive.read('evidence-coverage.json'))
            self.assertEqual({r['id'] for r in coverage['records']}, {keep, note, report})
            row = next(r for r in coverage['records'] if r['id'] == report)
            self.assertEqual(archive.read(row['citations'][0]['attachment']['path']), b'old identity original')
            self.assertIn('归并前题名', archive.read(row['path']).decode())
