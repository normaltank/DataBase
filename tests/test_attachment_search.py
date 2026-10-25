import io
from contextlib import closing
import json
import tempfile
import unittest
from pathlib import Path

from platform_app.web import create_app


class AttachmentSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='attachment-search-')
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / 'data'
        self.app = create_app(self.data, testing=True)
        self.clients = {}
        for uid in ['researcher', 'colleague', 'admin']:
            client = self.app.test_client()
            csrf = client.get('/api/session').json['csrf']
            self.assertEqual(client.post('/api/login', json={'username': uid, 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf}).status_code, 200)
            self.clients[uid] = client

    def call(self, path, payload=None, uid='researcher', method='POST', file=None):
        client = self.clients[uid]
        kwargs = {'headers': {'X-CSRF-Token': client.get('/api/session').json['csrf']}}
        if file:
            kwargs['data'] = {'data': json.dumps(payload), 'file': (io.BytesIO(file[1]), file[0])}
        else:
            kwargs['json'] = payload or {}
        response = client.open(path, method=method, **kwargs)
        response.request.close()
        return response

    def upload(self, name, content, **fields):
        response = self.call('/api/records', {'title': '附件合成样本', 'kind': 'report', 'sharing_confirmed': True, **fields}, file=(name, content))
        self.assertEqual(response.status_code, 201, response.json)
        return self.clients['researcher'].get('/api/records/' + response.json['id']).json

    def search(self, phrase, uid='researcher'):
        return self.clients[uid].get('/api/records', query_string={'q': phrase}).json

    def test_text_upload_search_location_download_and_rebuild(self):
        content = '普通首段\n\n翠鸟索引独有短语\n下一行'.encode()
        record = self.upload('中文材料.md', content)
        attachment = record['attachments'][0]
        self.assertEqual(attachment['index']['status'], 'ready')
        found = self.search('翠鸟索引独有短语')
        self.assertEqual(found['total'], 1)
        self.assertEqual(found['items'][0]['search_snippet'], '')
        match = found['items'][0]['attachment_matches'][0]
        self.assertEqual((match['attachment_id'], match['name'], match['locator']), (attachment['id'], '中文材料.md', '第 3 行'))
        self.assertIn('翠鸟索引独有短语', match['snippet'])
        with self.clients['researcher'].get(match['url']) as response:
            self.assertEqual(response.data, content)
        for _ in range(2):
            rebuilt = self.call('/api/attachments/' + attachment['id'] + '/index')
            self.assertEqual(rebuilt.status_code, 200, rebuilt.json)
            self.assertEqual(rebuilt.json['status'], 'ready')
        current = self.clients['researcher'].get('/api/records/' + record['id']).json
        self.assertEqual(current['version'], 1)
        self.assertEqual(current['body_html'], '')

    def test_pdf_and_docx_locations_and_mixed_query(self):
        import zipfile
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        output = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 20 200 Td (KestrelPDFMarker) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        writer.write(output)
        pdf = self.upload('report.pdf', output.getvalue())
        self.assertEqual(pdf['attachments'][0]['index']['status'], 'ready')
        result = self.search('合成 KestrelPDFMarker')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['attachment_matches'][0]['locator'], 'PDF 第 2 页（文件页码）')
        document = io.BytesIO()
        with zipfile.ZipFile(document, 'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>正文段落</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>翠鸟表格标记</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
        docx = self.upload('材料.docx', document.getvalue())
        self.assertEqual(docx['attachments'][0]['index']['status'], 'ready')
        result = self.search('翠鸟表格标记')
        self.assertEqual(result['items'][0]['attachment_matches'][0]['locator'], 'DOCX 表格 1 第 1 行')

    def test_docx_hyperlink_text_is_part_of_body_paragraph(self):
        import zipfile
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:hyperlink><w:r><w:t>正文链接独有短语</w:t></w:r></w:hyperlink></w:p></w:body></w:document>')
        self.upload('链接.docx', data.getvalue())
        self.assertEqual(self.search('正文链接独有短语')['total'], 1)

    def test_failures_keep_saved_record_and_original_file(self):
        from pypdf import PdfWriter
        import zipfile
        blank = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(blank)
        expanded = io.BytesIO()
        with zipfile.ZipFile(expanded, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('word/document.xml', b' ' * (21 * 1024 * 1024))
        encrypted = io.BytesIO()
        writer.encrypt('test-password')
        writer.write(encrypted)
        oversized = io.BytesIO()
        writer = PdfWriter()
        for _ in range(301):
            writer.add_blank_page(width=100, height=100)
        writer.write(oversized)
        samples = [('encrypted.pdf', encrypted.getvalue(), 'failed'), ('pages.pdf', oversized.getvalue(), 'limit'), ('blank.pdf', blank.getvalue(), 'empty'), ('broken.pdf', b'%PDF-1.7\nbroken', 'failed'), ('large.txt', b'X' * (10 * 1024 * 1024 + 1), 'limit'), ('expanded.docx', expanded.getvalue(), 'limit'), ('empty.md', b' \n\n', 'empty'), ('many.txt', b'Y' * 1000001, 'limit')]
        for name, content, expected in samples:
            with self.subTest(name=name):
                record = self.upload(name, content)
                attachment = record['attachments'][0]
                self.assertEqual(attachment['index']['status'], expected)
                with self.clients['researcher'].get('/api/attachments/' + attachment['id']) as downloaded:
                    self.assertEqual(downloaded.data, content)
                self.assertEqual(self.call('/api/attachments/' + attachment['id'] + '/index').json['status'], expected)
                self.assertEqual(self.search('X' * 20)['total'], 0)

    def test_permission_changes_and_history_use_only_current_attachments(self):
        record = self.upload('private.txt', b'SecretAttachmentMarker', visibility='restricted', editors=['colleague'])
        rid, aid = record['id'], record['attachments'][0]['id']
        self.assertEqual(self.search('SecretAttachmentMarker', 'colleague')['total'], 1)
        self.assertEqual(self.call('/api/records/' + rid, {'version': 1, 'editors': []}, method='PUT').status_code, 200)
        self.assertEqual(self.search('SecretAttachmentMarker', 'colleague')['total'], 0)
        self.assertEqual(self.call('/api/attachments/' + aid + '/index', uid='colleague').status_code, 404)
        self.assertEqual(self.clients['colleague'].get('/api/attachments/' + aid).status_code, 404)
        self.assertEqual(self.call('/api/records/' + rid, {'version': 2, 'sharing_confirmed': True}, method='PUT', file=('new.txt', b'HistoricalOnlyMarker')).status_code, 200)
        detail = self.clients['researcher'].get('/api/records/' + rid).json
        new_aid = next(a['id'] for a in detail['attachments'] if a['id'] != aid)
        self.assertEqual(self.search('HistoricalOnlyMarker')['total'], 1)
        history = self.clients['researcher'].get('/api/history/record/' + rid).json['items']
        self.assertEqual(self.call('/api/history/' + str(history[-1]['id']) + '/restore', {'version': 3}).status_code, 200)
        self.assertEqual(self.search('HistoricalOnlyMarker')['total'], 0)
        self.assertEqual(self.call('/api/attachments/' + new_aid + '/index').status_code, 404)
        self.assertEqual(self.search('SecretAttachmentMarker', 'colleague')['total'], 0)
        self.assertEqual(self.call('/api/history/' + str(history[0]['id']) + '/restore', {'version': 4}).status_code, 200)
        self.assertEqual(self.search('HistoricalOnlyMarker')['total'], 1)

    def test_merge_and_backup_restore_rebuild_without_content_changes(self):
        from platform_app.maintenance import create_backup, restore_backup
        import zipfile
        first = self.upload('first.txt', b'FirstAttachmentMarker')
        second = self.upload('second.txt', b'SecondAttachmentMarker')
        response = self.call('/api/merge', {'type': 'record', 'keep_id': first['id'], 'duplicate_id': second['id'], 'keep_version': 1, 'duplicate_version': 1, 'confirmed': True}, uid='admin')
        self.assertEqual(response.status_code, 200, response.json)
        found = self.search('FirstAttachmentMarker SecondAttachmentMarker')
        self.assertEqual(found['total'], 1)
        self.assertEqual(found['items'][0]['id'], first['id'])
        self.assertEqual(len(found['items'][0]['attachment_matches']), 2)
        before = self.clients['researcher'].get('/api/records/' + first['id']).json
        backup = create_backup(self.data)
        with zipfile.ZipFile(backup) as archive:
            self.assertFalse(any('attachment-index' in n for n in archive.namelist()))
        restored = restore_backup(backup, Path(self.temp.name) / 'restored')
        app = create_app(restored, testing=True)
        client = app.test_client()
        token = client.get('/api/session').json['csrf']
        login = client.post('/api/login', json={'username': 'researcher', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': token})
        token = login.json['csrf']
        self.assertEqual(client.get('/api/records?q=FirstAttachmentMarker').json['total'], 0)
        current = client.get('/api/records/' + first['id']).json
        for attachment in current['attachments']:
            self.assertEqual(attachment['index']['status'], 'unindexed')
            self.assertEqual(client.post('/api/attachments/' + attachment['id'] + '/index', json={}, headers={'X-CSRF-Token': token}).json['status'], 'ready')
            with client.get('/api/attachments/' + attachment['id']) as download:
                self.assertIn(download.data, [b'FirstAttachmentMarker', b'SecondAttachmentMarker'])
        after = client.get('/api/records/' + first['id']).json
        self.assertEqual((after['version'], after['body_html'], after['attachment_ids']), (before['version'], before['body_html'], before['attachment_ids']))
        self.assertEqual(client.get('/api/records?q=FirstAttachmentMarker%20SecondAttachmentMarker').json['total'], 1)

    def test_missing_files_and_orphan_membership_do_not_search(self):
        from platform_app.store import connect
        record = self.upload('gone.txt', b'DisappearingAttachmentMarker')
        aid = record['attachments'][0]['id']
        # Storage loss is an external boundary; the database is not an assertion seam.
        for path in (self.data / 'uploads').iterdir():
            path.unlink()
        self.assertEqual(self.search('DisappearingAttachmentMarker')['total'], 0)
        self.assertEqual(self.call('/api/attachments/' + aid + '/index').status_code, 404)
        other = self.upload('orphan.txt', b'OrphanAttachmentMarker')
        with closing(connect(self.data / 'platform.sqlite3')) as database, database:
            database.execute('UPDATE records SET attachment_ids=? WHERE id=?', (json.dumps([other['attachments'][0]['id']]), record['id']))
            database.execute('UPDATE records SET attachment_ids=? WHERE id=?', ('[]', other['id']))
        self.assertEqual(self.search('OrphanAttachmentMarker')['total'], 0)
        self.assertEqual(self.call('/api/attachments/' + other['attachments'][0]['id'] + '/index').status_code, 404)

    def test_old_unsupported_attachment_is_downloadable_and_index_status_is_explicit(self):
        from platform_app.store import connect
        record = self.upload('legacy.txt', b'LegacyFormatMarker')
        aid = record['attachments'][0]['id']
        original = next((self.data / 'uploads').iterdir())
        target = original.with_suffix('.rtf')
        original.rename(target)
        with closing(connect(self.data / 'platform.sqlite3')) as database, database:
            database.execute('UPDATE attachments SET name=?,stored_name=? WHERE id=?', ('legacy.rtf', target.name, aid))
        self.assertEqual(self.call('/api/attachments/' + aid + '/index').json['status'], 'unsupported')
        with self.clients['researcher'].get('/api/attachments/' + aid) as download:
            self.assertEqual(download.data, b'LegacyFormatMarker')
        self.assertEqual(self.search('LegacyFormatMarker')['total'], 0)

    def test_timeout_and_cache_failure_do_not_fail_saved_upload(self):
        from unittest.mock import patch
        import subprocess
        # Process/time and filesystem failures are external boundaries.
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('parser', 12)):
            record = self.upload('timeout.txt', b'TimeoutAttachmentMarker')
        self.assertEqual(record['attachments'][0]['index']['status'], 'limit')
        self.assertEqual(self.search('TimeoutAttachmentMarker')['total'], 0)
        rebuilt = self.call('/api/attachments/' + record['attachments'][0]['id'] + '/index')
        self.assertEqual(rebuilt.json['status'], 'ready')
        self.assertEqual(self.search('TimeoutAttachmentMarker')['total'], 1)
        with patch('os.replace', side_effect=OSError('cache unavailable')):
            saved = self.upload('cache.txt', b'CacheFailureMarker')
        self.assertEqual(saved['version'], 1)
        with self.clients['researcher'].get('/api/attachments/' + saved['attachments'][0]['id']) as downloaded:
            self.assertEqual(downloaded.data, b'CacheFailureMarker')

    def test_corrupt_disposable_cache_can_be_rebuilt(self):
        record = self.upload('cache.txt', b'RecoverableCacheMarker')
        cache = next((self.data / 'attachment-index').glob('*.json'))
        original = json.loads(cache.read_text(encoding='utf-8'))
        malformed = ['{', '[]', json.dumps({**original, 'status': 'surprise'}), json.dumps({**original, 'segments': {}}), json.dumps({**original, 'segments': [{'text': 42, 'locator': 'here'}]})]
        for value in malformed:
            cache.write_text(value, encoding='utf-8')
            self.assertEqual(self.search('RecoverableCacheMarker')['total'], 0)
            current = self.clients['researcher'].get('/api/records/' + record['id']).json
            self.assertEqual(current['attachments'][0]['index']['status'], 'unindexed')
        self.assertEqual(self.call('/api/attachments/' + record['attachments'][0]['id'] + '/index').json['status'], 'ready')
        self.assertEqual(self.search('RecoverableCacheMarker')['total'], 1)
