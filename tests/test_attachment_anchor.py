"""Attachment evidence through HTTP, exported ZIP and the independent CLI."""
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
import unittest
import test_workflow as workflow_tests


class AttachmentAnchorTests(unittest.TestCase):
    setUp = workflow_tests.WorkflowTests.setUp
    login = workflow_tests.WorkflowTests.login
    call = workflow_tests.WorkflowTests.call
    record = workflow_tests.WorkflowTests.record
    detail = workflow_tests.WorkflowTests.detail

    def original(self, content=b'First line\nBefore exact quotation after\nLast line', **fields):
        response = self.call('/api/records', {'kind': 'report', 'title': 'Anchor original', 'sharing_confirmed': True, **fields}, file=('anchor.txt', content))
        self.assertEqual(response.status_code, 201, response.json)
        row = self.detail(response.json['id'])
        return row['id'], row['attachments'][0]['id']

    def excerpt(self, rid, aid, **fields):
        return self.record('research_note', evidence_record_id=rid, evidence_attachment_id=aid,
                           quote=fields.pop('quote', 'exact quotation'), locator=fields.pop('locator', '第 2 行'), **fields)

    def test_anchor_is_server_owned_and_matches_only_the_selected_location(self):
        rid, aid = self.original()
        nid = self.excerpt(rid, aid, evidence_snapshot_json='{"attachment_anchor":{"sha256":"fake"}}')
        anchor = self.detail(nid)['evidence_snapshot']['attachment_anchor']
        self.assertEqual((anchor['id'], anchor['name'], anchor['bytes']), (aid, 'anchor.txt', 49))
        self.assertEqual(anchor['sha256'], '798aa519de442c73d2746473b3ad9b4fe26e6d590f1ff1b51ff8d552ce64810b')
        self.assertEqual(anchor['quote_match']['status'], 'matched')
        self.assertEqual((anchor['context_prefix'], anchor['context_suffix']), ('Before ', ' after'))
        normalized = self.excerpt(rid, aid, quote='exact\t  quotation')
        self.assertEqual(self.detail(normalized)['evidence_snapshot']['attachment_anchor']['quote_match']['status'], 'matched')
        wrong = self.excerpt(rid, aid, locator='第 1 行')
        self.assertEqual(self.detail(wrong)['evidence_snapshot']['attachment_anchor']['quote_match'], {'status': 'not_matched', 'reason': 'quote_not_at_location'})

    def test_hit_opens_full_authorized_segment_and_preserves_editor_selection(self):
        content = ('Before ' * 40 + 'unique sentence' + ' after' * 40).encode()
        rid, aid = self.original(content)
        found = self.clients['researcher'].get('/api/records?q=unique').json['items'][0]['attachment_matches'][0]
        self.assertIn('…', found['snippet'])
        selected = self.clients['researcher'].get('/api/attachments/' + aid + '/segment', query_string={'locator': found['locator']})
        self.assertEqual(selected.status_code, 200, selected.json)
        self.assertEqual(selected.json['text'], content.decode())
        self.assertEqual((selected.json['record_id'], selected.json['attachment_id']), (rid, aid))
        self.assertEqual(self.clients['researcher'].get('/api/attachments/' + aid + '/segment?locator=elsewhere').status_code, 404)
        self.assertEqual(self.call('/api/records/' + rid, {'version': 1, 'visibility': 'restricted'}, method='PUT').status_code, 200)
        self.assertEqual(self.clients['colleague'].get('/api/attachments/' + aid + '/segment?locator=第%201%20行').status_code, 404)

    def test_edits_restore_and_report_keep_their_own_fixed_anchor(self):
        rid, aid = self.original()
        nid = self.excerpt(rid, aid)
        report = self.record('research_report', evidence_ids=[nid])
        pinned = self.detail(report)['evidence_citations'][0]['snapshot']
        self.assertEqual(self.call('/api/records/' + rid, {'version': 1, 'title': 'Updated original'}, method='PUT').status_code, 200)
        edit = self.call('/api/records/' + nid, {'version': 1, 'quote': 'different quote'}, method='PUT', user='colleague')
        self.assertEqual(edit.status_code, 200, edit.json)
        current = self.detail(nid)
        self.assertEqual(current['evidence_version'], 1)
        self.assertEqual(current['evidence_snapshot']['title'], 'Anchor original')
        self.assertEqual(current['evidence_snapshot']['attachment_anchor']['quote_match']['status'], 'not_matched')
        self.assertEqual(self.detail(report)['evidence_citations'][0]['snapshot'], pinned)
        history = self.clients['researcher'].get('/api/history/record/' + nid).json['items']
        self.assertEqual(self.call('/api/history/' + str(history[-1]['id']) + '/restore', {'version': 2}).status_code, 200)
        self.assertEqual(self.detail(nid)['evidence_snapshot']['attachment_anchor']['quote_match']['status'], 'matched')
        self.assertEqual(self.call('/api/records/' + nid, {'version': 2, 'quote': 'stale'}, method='PUT').status_code, 409)
        self.assertEqual(self.call('/api/records/' + nid, {'version': 3, 'refresh_evidence': True}, method='PUT').status_code, 200)
        self.assertEqual(self.detail(nid)['evidence_version'], 2)
        self.assertEqual(self.detail(report)['evidence_citations'][0]['snapshot'], pinned)

    def test_unavailable_index_and_tampered_file_are_never_matched(self):
        rid, aid = self.original()
        for path in (self.data_dir / 'attachment-index').glob('*.json'):
            path.unlink()
        nid = self.excerpt(rid, aid)
        match = self.detail(nid)['evidence_snapshot']['attachment_anchor']['quote_match']
        self.assertEqual(match, {'status': 'unchecked', 'reason': 'unindexed'})
        self.assertEqual(self.call('/api/attachments/' + aid + '/index').status_code, 200)
        cached = next((self.data_dir / 'attachment-index').glob('*.json'))
        stale = json.loads(cached.read_text())
        stale['sha256'] = '0' * 64
        cached.write_text(json.dumps(stale))
        unchecked = self.excerpt(rid, aid)
        self.assertEqual(self.detail(unchecked)['evidence_snapshot']['attachment_anchor']['quote_match'], {'status': 'unchecked', 'reason': 'unindexed'})
        self.assertEqual(self.call('/api/attachments/' + aid + '/index').status_code, 200)
        original_file = next((self.data_dir / 'uploads').iterdir())
        original_file.write_bytes(b'Changed bytes')
        changed = self.excerpt(rid, aid)
        self.assertEqual(self.detail(changed)['evidence_snapshot']['attachment_anchor']['quote_match'], {'status': 'unchecked', 'reason': 'file_mismatch'})

    def exported(self, report):
        response = self.clients['researcher'].get('/api/export/content?kind=research_report')
        self.assertEqual(response.status_code, 200, response.json)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def verify_files(self, files):
        # Simulate an editor who re-signs the manifest; anchor checks must be independent.
        manifest = {'format': 'research-content-manifest-v1', 'files': [
            {'path': name, 'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
            for name, value in files.items() if name != 'manifest.json']}
        files = {**files, 'manifest.json': json.dumps(manifest).encode()}
        target = self.data_dir / 'check.zip'
        with zipfile.ZipFile(target, 'w') as archive:
            for name, value in files.items():
                archive.writestr(name, value)
        return subprocess.run([sys.executable, '-I', str(Path(__file__).resolve().parents[1] / 'scripts/verify_content_export.py'), str(target)], capture_output=True, text=True)

    def test_offline_cli_rejects_dangling_attachment_in_content_after_manifest_rewrite(self):
        rid, aid = self.original()
        nid = self.excerpt(rid, aid)
        report = self.record('research_report', evidence_ids=[nid])
        files = self.exported(report)
        self.assertEqual(self.verify_files(files).returncode, 0)
        payload = json.loads(files['content.json'])
        note = next(r for r in payload['records'] if r['id'] == nid)
        note['evidence_attachment_id'] = 'missing-file'
        files['content.json'] = json.dumps(payload).encode()
        result = self.verify_files(files)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('anchor', result.stderr.lower())

    def test_offline_reading_and_review_expose_the_saved_anchor_and_checks(self):
        rid, aid = self.original()
        nid = self.excerpt(rid, aid)
        report = self.record('research_report', evidence_ids=[nid])
        files = self.exported(report)
        payload = json.loads(files['content.json'])
        report_row = next(r for r in payload['records'] if r['id'] == report)
        self.assertIn('已在指定位置的提取文字中匹配', files[report_row['path']].decode())
        self.assertIn('已在指定位置的提取文字中匹配', files['review.html'].decode())
        coverage = json.loads(files['evidence-coverage.json'])
        saved = next(r for r in coverage['records'] if r['id'] == report)['citations'][0]['attachment_anchor']
        self.assertEqual(saved, self.detail(nid)['evidence_snapshot']['attachment_anchor'])
        for mutation in ['bytes', 'digest', 'missing', 'path', 'coverage', 'content-anchor', 'coverage-anchor', 'coverage-path-missing', 'content-file-missing']:
            altered = dict(files)
            data = json.loads(altered['content.json'])
            checklist = json.loads(altered['evidence-coverage.json'])
            cited = next(r for r in data['records'] if r['id'] == report)['evidence_citations'][0]['snapshot']
            original = json.loads(cited['evidence_snapshot_json'])
            if mutation == 'content-file-missing':
                del altered['content.json']
            elif mutation in ['bytes', 'digest']:
                attached = data['attachments'][0]
                altered[attached['path']] = b'Changed file'
                if mutation == 'digest':
                    attached.update(bytes=12, sha256=hashlib.sha256(b'Changed file').hexdigest())
            elif mutation == 'missing':
                del altered[data['attachments'][0]['path']]
            elif mutation == 'path':
                data['attachments'][0]['path'] = 'records/wrong.html'
            elif mutation == 'content-anchor':
                del original['attachment_anchor']
                cited['evidence_snapshot_json'] = json.dumps(original)
            else:
                retained = next(r for r in checklist['records'] if r['id'] == report)['citations'][0]
                if mutation == 'coverage-path-missing':
                    del retained['attachment']['path']
                elif mutation == 'coverage':
                    retained['attachment']['path'] = 'records/wrong.html'
                else:
                    del retained['attachment_anchor']
            if mutation != 'content-file-missing':
                altered['content.json'] = json.dumps(data).encode()
            altered['evidence-coverage.json'] = json.dumps(checklist).encode()
            with self.subTest(mutation=mutation):
                result = self.verify_files(altered)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_repeated_sentence_keeps_the_selected_occurrence_context(self):
        rid, aid = self.original(b'First quote here; second quote there')
        nid = self.excerpt(rid, aid, quote='quote', locator='第 1 行', evidence_occurrence=1)
        anchor = self.detail(nid)['evidence_snapshot']['attachment_anchor']
        self.assertEqual(anchor['context_suffix'], ' there')
        self.assertEqual(anchor['context_prefix'], 'First quote here; second ')
        large, file_id = self.original(b'q ' * 50000 + b'end')
        last = self.excerpt(large, file_id, quote='q', locator='第 1 行', evidence_occurrence=49999)
        self.assertEqual(self.detail(last)['evidence_snapshot']['attachment_anchor']['context_suffix'], ' end')

    def test_pdf_docx_and_no_text_have_honest_location_checks(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        pdf = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 20 200 Td (PDF exact quote) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        writer.write(pdf)
        docx = io.BytesIO()
        with zipfile.ZipFile(docx, 'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>DOCX exact quote</w:t></w:r></w:p></w:body></w:document>')
        blank = io.BytesIO()
        empty = PdfWriter()
        empty.add_blank_page(width=100, height=100)
        empty.write(blank)
        for name, content, quote, locator, expected in [
            ('quote.pdf', pdf.getvalue(), 'PDF exact quote', 'PDF 第 2 页（文件页码）', 'matched'),
            ('quote.docx', docx.getvalue(), 'DOCX exact quote', 'DOCX 正文第 1 段', 'matched'),
            ('blank.pdf', blank.getvalue(), 'Manual transcription', 'PDF 第 1 页（文件页码）', 'unchecked')]:
            with self.subTest(name=name):
                result = self.call('/api/records', {'kind': 'report', 'title': name, 'sharing_confirmed': True}, file=(name, content))
                self.assertEqual(result.status_code, 201, result.json)
                row = self.detail(result.json['id'])
                nid = self.excerpt(row['id'], row['attachments'][0]['id'], quote=quote, locator=locator)
                anchor = self.detail(nid)['evidence_snapshot']['attachment_anchor']
                self.assertEqual(anchor['quote_match']['status'], expected, anchor)
                if expected == 'unchecked':
                    self.assertEqual(anchor['quote_match']['reason'], 'empty')

    def test_historical_attachment_and_backup_restore_keep_anchor_without_index(self):
        from platform_app.maintenance import create_backup, restore_backup
        from platform_app.web import create_app
        rid = self.record(title='Original before attachment')
        upload = self.call('/api/records/' + rid, {'version': 1, 'sharing_confirmed': True}, method='PUT', file=('anchor.txt', b'First line\nBefore exact quotation after\nLast line'))
        self.assertEqual(upload.status_code, 200, upload.json)
        aid = self.detail(rid)['attachments'][0]['id']
        nid = self.excerpt(rid, aid)
        report = self.record('research_report', evidence_ids=[nid])
        pinned = self.detail(report)['evidence_citations'][0]['snapshot']
        uploaded = self.call('/api/records/' + rid, {'version': 2, 'sharing_confirmed': True}, method='PUT', file=('later.txt', b'Later attachment'))
        self.assertEqual(uploaded.status_code, 200)
        history = self.clients['researcher'].get('/api/history/record/' + rid).json['items']
        self.assertEqual(self.call('/api/history/' + str(history[-1]['id']) + '/restore', {'version': 3}).status_code, 200)
        self.assertEqual(self.detail(rid)['attachments'], [])
        self.assertEqual(self.clients['researcher'].get('/api/attachments/' + aid).status_code, 404)
        revised = self.call('/api/records/' + nid, {'version': 1, 'quote': 'exact quotation after'}, method='PUT')
        self.assertEqual(revised.status_code, 200, revised.json)
        self.assertEqual(self.detail(nid)['evidence_version'], 2)
        self.assertEqual(self.detail(nid)['evidence_snapshot']['attachment_anchor']['quote_match']['status'], 'matched')
        backup = create_backup(self.data_dir)
        restored = restore_backup(backup, Path(self.temp.name) / 'restored')
        app = create_app(restored, testing=True)
        client = self.login('researcher', app)
        self.assertEqual(client.get('/api/records/' + report).json['evidence_citations'][0]['snapshot'], pinned)
        self.assertEqual(client.get('/api/records/' + rid).json['attachments'], [])
        self.assertFalse((restored / 'attachment-index').exists())
        with client.get('/api/records/' + nid + '/evidence-file') as response:
            self.assertEqual(response.data, b'First line\nBefore exact quotation after\nLast line')
        output = client.get('/api/export/content?kind=research_report')
        self.assertEqual(output.status_code, 200, output.json)
        with zipfile.ZipFile(io.BytesIO(output.data)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        self.assertEqual(self.verify_files(files).returncode, 0)

    def test_hidden_original_and_foreign_attachment_cannot_leak_anchor(self):
        rid, aid = self.original()
        other, foreign = self.original(b'Other attachment')
        response = self.call('/api/records', {'kind': 'research_note', 'title': 'Foreign attachment', 'evidence_record_id': rid, 'evidence_attachment_id': foreign, 'quote': 'Other', 'locator': '第 1 行'})
        self.assertEqual(response.status_code, 400)
        nid = self.excerpt(rid, aid)
        report = self.record('research_report', evidence_ids=[nid])
        self.assertEqual(self.call('/api/records/' + rid, {'version': 1, 'visibility': 'restricted'}, method='PUT').status_code, 200)
        self.assertEqual(self.clients['colleague'].get('/api/records/' + nid).status_code, 404)
        self.assertEqual(self.detail(report, 'colleague')['evidence_citations'], [])
        response = self.clients['colleague'].get('/api/export/content?kind=research_report')
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            for name in ['content.json', 'evidence-coverage.json', 'review.html']:
                self.assertNotIn(aid, archive.read(name).decode())

    def test_old_no_anchor_snapshots_remain_unknown_without_current_backfill(self):
        # Build only a legacy-format fixture. All behavioral observations use HTTP/CLI.
        from contextlib import closing
        from platform_app.store import connect
        rid, aid = self.original()
        nid = self.excerpt(rid, aid)
        with closing(connect(self.data_dir / 'platform.sqlite3')) as database, database:
            original = self.detail(nid)['evidence_snapshot']
            del original['attachment_anchor']
            database.execute('UPDATE records SET evidence_snapshot_json=? WHERE id=?', (json.dumps(original), nid))
        report = self.record('research_report', evidence_ids=[nid])
        self.assertNotIn('attachment_anchor', self.detail(nid)['evidence_snapshot'])
        self.assertEqual(self.call('/api/records/' + nid, {'version': 1, 'interpretation': 'Clarified'}, method='PUT').status_code, 200)
        self.assertNotIn('attachment_anchor', self.detail(nid)['evidence_snapshot'])
        files = self.exported(report)
        self.assertEqual(self.verify_files(files).returncode, 0)
        self.assertIn('历史未记录附件锚点', files['review.html'].decode())
