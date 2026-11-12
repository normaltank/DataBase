"""Journal archive workflows at the authenticated public HTTP boundary."""
import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from platform_app.web import create_app
from platform_app.maintenance import restore_backup


class JournalArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='journal-archive-')
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(self.temp.name, testing=True, embedded_worker=False)
        self.clients = {uid: self.login(uid) for uid in ['researcher', 'colleague', 'admin']}
        self.journal = self.call('/api/sources', {'name': 'Synthetic archive journal', 'kind': 'journal', 'issn': 'old unclassified identifier'}).json['id']
        self.base = '/api/journals/' + self.journal

    def login(self, uid, app=None):
        client = (app or self.app).test_client()
        csrf = client.get('/api/session').json['csrf']
        self.assertEqual(client.post('/api/login', json={'username': uid, 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf}).status_code, 200)
        return client

    def call(self, path, payload, method='POST', user='researcher'):
        client = self.clients[user]
        csrf = client.get('/api/session').json['csrf']
        return client.open(path, method=method, json=payload, headers={'X-CSRF-Token': csrf})

    def get(self, path, user='researcher'):
        response = self.clients[user].get(path)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def test_profile_keeps_precise_identifiers_versioned_metrics_and_unknown_values(self):
        profile = self.get(self.base)['profile']
        data = {'version': profile['version'], 'founded': '1980年代', 'frequency': '每年四期；旧周期不详',
                'frequency_evidence': 'Synthetic frequency statement', 'print_issn': '1111-1111',
                'electronic_issn': '2222-2222', 'publisher_text': 'Unlinked synthetic publisher',
                'metrics': [
                    {'id': 'metric-regular', 'kind': 'impact_factor', 'name': '普通影响因子', 'value': '0', 'year': '2024', 'released_year': '2025', 'evidence': 'Synthetic metric evidence'},
                    {'id': 'metric-five', 'kind': 'five_year', 'name': '五年影响因子', 'value': '2.5', 'year': '2024', 'evidence': 'Synthetic five year evidence'},
                    {'id': 'metric-unknown', 'kind': 'original', 'name': '未明口径', 'value': '', 'year': '', 'raw_label': 'SSCI 2/3 区', 'evidence': 'Unverified synthetic label'}],
                'rankings': [{'id': 'ranking-2024', 'year': '2024', 'edition': '合成修订版', 'evidence': 'Synthetic ranking evidence', 'subjects': [
                    {'level': 'major', 'original_name': 'Synthetic studies', 'chinese_name': '合成学科', 'quartile': '2'},
                    {'level': 'minor', 'original_name': 'Synthetic A', 'chinese_name': '', 'quartile': '2'},
                    {'level': 'minor', 'original_name': 'Synthetic B', 'chinese_name': '', 'quartile': '3'}]}],
                'indexing': 'SSCI 收录，原标注待核实'}
        response = self.call(self.base + '/profile', data, 'PUT')
        self.assertEqual(response.status_code, 200, response.json)
        saved = self.get(self.base)
        self.assertEqual(saved['profile']['metrics'][0]['value'], '0')
        self.assertEqual(saved['profile']['metrics'][2]['year'], '')
        self.assertEqual(saved['profile']['rankings'][0]['subjects'][2]['quartile'], '3')
        self.assertEqual(self.get('/api/sources/' + self.journal)['issn'], 'old unclassified identifier')
        stale = self.call(self.base + '/profile', data, 'PUT', 'colleague')
        self.assertEqual(stale.status_code, 409)
        changed = {**data, 'version': saved['profile']['version'], 'founded': '1982'}
        self.assertEqual(self.call(self.base + '/profile', changed, 'PUT', 'colleague').status_code, 200)
        history = self.get(self.base + '/profile/history')['items']
        self.assertEqual(history[1]['snapshot']['founded'], '1980年代')
        self.assertEqual(history[0]['actor_id'], 'colleague')
        institution = self.call('/api/sources', {'name': 'Synthetic institution', 'kind': 'institution'}).json['id']
        self.assertEqual(self.clients['researcher'].get('/api/journals/' + institution).status_code, 404)

    def issue(self, **extra):
        data = {'version': 0, 'label': 'Synthetic 2024 Vol 2 No 1', 'year': '2024', 'volume': '2', 'number': '1',
                'coverage': 'partial', 'catalogue_evidence': 'https://example.invalid/synthetic/toc',
                'sections': [{'id': 'research', 'title': 'Research articles', 'entries': [
                    {'id': 'article-one', 'title': 'Synthetic original article', 'authors': 'Unresolved synthetic byline', 'url': 'https://example.invalid/original', 'kind': 'Research article'}]},
                    {'id': 'reviews', 'title': 'Book reviews', 'entries': [
                        {'id': 'review-one', 'title': 'Synthetic review only', 'kind': 'Book review'}]}], **extra}
        result = self.call(self.base + '/issues', data)
        self.assertEqual(result.status_code, 201, result.json)
        return result.json

    def test_ordered_contents_link_existing_article_without_rewriting_conflicting_bibliography(self):
        article = self.call('/api/records', {'title': 'Synthetic original article', 'kind': 'journal_article', 'serial_id': self.journal,
                            'volume': '2', 'issue': '9', 'published_on': '2024', 'doi': '10.55555/synthetic-archive'}).json['id']
        before = self.get('/api/records/' + article)
        issue = self.issue()
        self.assertEqual(self.get('/api/records')['total'], 1)  # TOC entries are not automatically articles.
        linked = copy.deepcopy(issue)
        entry = linked['sections'][0]['entries'][0]
        entry.update(record_id=article, relation_evidence='Synthetic explicit original contents')
        conflict = self.call(self.base + '/issues/' + issue['id'], linked, 'PUT')
        self.assertEqual(conflict.status_code, 409, conflict.json)
        self.assertIn('冲突', conflict.json['error'])
        self.assertEqual(self.get(self.base + '/issues/' + issue['id'])['version'], 1)
        entry['conflict_note'] = 'Synthetic verified disagreement; retain both original labels'
        linked['sections'].reverse()
        linked['coverage'] = 'complete'
        saved = self.call(self.base + '/issues/' + issue['id'], linked, 'PUT', 'colleague')
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual([s['title'] for s in saved.json['sections']], ['Book reviews', 'Research articles'])
        after = self.get('/api/records/' + article)
        self.assertEqual((after['issue'], after['version'], after['doi']), ('9', before['version'], '10.55555/synthetic-archive'))
        self.assertEqual(self.get('/api/records/' + article + '/bylines')['items'], [])
        history = self.get(self.base + '/issues/' + issue['id'] + '/history')['items']
        self.assertEqual(history[-1]['snapshot']['sections'][0]['title'], 'Research articles')
        self.assertNotIn('snapshot_json', history[0])
        bad = {**saved.json, 'catalogue_evidence': ''}
        self.assertEqual(self.call(self.base + '/issues/' + issue['id'], bad, 'PUT').status_code, 400)
        with self.clients['researcher'].get('/api/export/content') as response:
            self.assertEqual(response.status_code, 200, response.json)
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                payload = json.loads(archive.read('content.json'))
                exported = payload['journal_archives'][0]
                self.assertEqual(exported['issues'][0]['sections'][1]['entries'][0]['record_id'], article)
                page = archive.read(next(p for p in archive.namelist() if p.startswith('sources/') and p.endswith('.html'))).decode()
                self.assertLess(page.index('Book reviews'), page.index('Research articles'))

    def compilation(self, kind='directory_translation', **extra):
        response = self.call('/api/records', {'title': 'Synthetic cross-issue compilation', 'kind': kind,
                            'authors': 'Synthetic compiler', 'coverage': '2024—2025 multiple original issues',
                            'body_html': '<p>Old complete manuscript remains editable.</p>',
                            'related_source_ids': [self.journal], **extra})
        self.assertEqual(response.status_code, 201, response.json)
        return self.get('/api/records/' + response.json['id'])

    def selected(self, issue, original, **extra):
        return {'id': 'selection-one', 'issue_id': issue['id'], 'entry_id': 'article-one', 'kind': 'abstract_translation',
                'compiler': 'Synthetic compiler', 'body_html': '<p>合成摘要译文，不代表真实研究结论。</p>',
                'basis': {'record_id': original['id'], 'record_version': original['version'], 'locator': 'Abstract, paragraph 1'}, **extra}

    def test_cross_issue_compilation_freezes_original_versions_and_keeps_author_policy(self):
        original_id = self.call('/api/records', {'title': 'Synthetic original', 'kind': 'journal_article', 'serial_id': self.journal,
                         'abstract': 'Original abstract version one.', 'body_html': '<p>Original full text one.</p>'}).json['id']
        original = self.get('/api/records/' + original_id)
        first, second = self.issue(), self.issue(label='Synthetic combined issue', number='2—3', year='2025', coverage='unverified')
        record = self.compilation()
        path = self.base + '/compilations/' + record['id']
        data = {'version': 0, 'record_version': record['version'], 'issue_ids': [first['id'], second['id']],
                'compiled_on': '2025-02', 'released_on': '2025-03-01', 'credits': 'Compiler / reviewer signature only',
                'selections': [self.selected(first, original)]}
        saved = self.call(path, data, 'PUT')
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json['selections'][0]['basis']['snapshot']['abstract'], 'Original abstract version one.')
        update = self.call('/api/records/' + original_id, {'version': original['version'], 'abstract': 'Corrected original abstract.', 'body_html': '<p>Full text changed.</p>'}, 'PUT')
        self.assertEqual(update.status_code, 200, update.json)
        old = self.get(path)['selections'][0]
        self.assertTrue(old['needs_review'])
        self.assertEqual(old['basis']['record_version'], original['version'])
        self.assertEqual(old['basis']['snapshot']['body_html'], '<p>Original full text one.</p>')
        other = self.compilation(title='Another synthetic compilation')
        reused = self.call(self.base + '/compilations/' + other['id'], {**data, 'record_version': other['version']}, 'PUT')
        self.assertEqual(reused.status_code, 200, reused.json)
        self.assertEqual(reused.json['selections'][0]['basis']['snapshot']['abstract'], 'Original abstract version one.')
        self.assertEqual(self.get('/api/records')['total'], 3)
        saved_data = {**data, 'version': 1, 'credits': 'Second member correction'}
        self.assertEqual(self.call(path, saved_data, 'PUT', 'colleague').status_code, 200)
        self.assertEqual(self.call(path, saved_data, 'PUT').status_code, 409)
        self.assertEqual(self.get(path + '/history')['items'][-1]['snapshot']['credits'], 'Compiler / reviewer signature only')
        self.assertEqual(self.get(path + '/history')['items'][-1]['snapshot']['record_snapshot']['body_html'], '<p>Old complete manuscript remains editable.</p>')
        self.assertEqual(self.get('/api/records/' + record['id'])['body_html'], '<p>Old complete manuscript remains editable.</p>')
        personal = self.compilation(kind='compilation', title='Personal synthetic compilation')
        private_path = self.base + '/compilations/' + personal['id']
        self.assertEqual(self.call(private_path, {**data, 'record_version': personal['version']}, 'PUT', 'colleague').status_code, 403)
        self.assertEqual(self.call(private_path, {**data, 'record_version': personal['version']}, 'PUT', 'admin').status_code, 403)
        self.assertEqual(self.call(private_path, {**data, 'record_version': personal['version']}, 'PUT').status_code, 200)
        self.assertEqual(self.clients['colleague'].get(private_path + '/history').status_code, 403)
        self.assertNotIn('record_snapshot', self.get(private_path, 'colleague'))
        with self.clients['colleague'].get('/api/export/content') as exported:
            self.assertEqual(exported.status_code, 200, exported.json)
        restricted = self.compilation(kind='compilation', title='Restricted synthetic compilation', visibility='restricted')
        self.assertEqual(self.clients['colleague'].get(self.base + '/compilations/' + restricted['id']).status_code, 404)

    def test_without_original_abstract_summary_cannot_be_presented_as_abstract_translation(self):
        issue = self.issue()
        original_id = self.call('/api/records', {'title': 'Synthetic title only', 'kind': 'journal_article'}).json['id']
        original = self.get('/api/records/' + original_id)
        record = self.compilation()
        path = self.base + '/compilations/' + record['id']
        data = {'version': 0, 'record_version': record['version'], 'issue_ids': [issue['id']], 'selections': [self.selected(issue, original)]}
        self.assertEqual(self.call(path, data, 'PUT').status_code, 400)
        data['selections'][0]['kind'] = 'editor_summary'
        self.assertEqual(self.call(path, data, 'PUT').status_code, 200)
        limited = self.call('/api/records/' + original_id, {'version': original['version'], 'visibility': 'restricted'}, 'PUT')
        self.assertEqual(limited.status_code, 200, limited.json)
        reader = self.get(path, 'colleague')
        self.assertEqual(reader['selections'], [{'id': 'selection-one', 'unavailable': True}])
        history = self.get(path + '/history', 'colleague')
        self.assertNotIn('Synthetic title only', json.dumps(history))
        self.assertFalse(reader['can_edit'])
        self.assertEqual(self.call(path, {'version': 1, 'record_version': record['version'], 'issue_ids': [], 'selections': []}, 'PUT', 'colleague').status_code, 404)

    def test_journal_identity_cannot_discard_structured_archives_during_type_change_or_merge(self):
        self.issue()
        changed = self.call('/api/sources/' + self.journal, {'version': 1, 'kind': 'institution'}, 'PUT')
        self.assertEqual(changed.status_code, 409)
        duplicate = self.call('/api/sources', {'name': 'Another synthetic journal', 'kind': 'journal'}).json['id']
        merged = self.call('/api/merge', {'type': 'source', 'keep_id': duplicate, 'duplicate_id': self.journal,
                          'keep_version': 1, 'duplicate_version': 1, 'confirmed': True}, user='admin')
        self.assertEqual(merged.status_code, 409, merged.json)
        self.assertEqual(len(self.get(self.base)['issues']), 1)

    def test_saved_attachment_cover_remains_readable_after_its_original_record_changes(self):
        rid = self.call('/api/records', {'title': 'Synthetic cover attachment holder', 'kind': 'report'}).json['id']
        revision = self.get('/api/history/record/' + rid)['items'][0]['id']
        csrf = self.clients['researcher'].get('/api/session').json['csrf']
        attached = self.clients['researcher'].put('/api/records/' + rid, data={
            'data': json.dumps({'version': 1, 'sharing_confirmed': True}),
            'file': (io.BytesIO(b'Synthetic cover attachment'), 'cover.txt')}, headers={'X-CSRF-Token': csrf})
        self.assertEqual(attached.status_code, 200, attached.json)
        record = self.get('/api/records/' + attached.json['id'])
        aid = record['attachments'][0]['id']
        saved = self.call(self.base + '/profile', {'version': 0, 'cover': {'attachment_id': aid, 'evidence': 'Synthetic attachment evidence', 'illustrative': True}}, 'PUT')
        self.assertEqual(saved.status_code, 200, saved.json)
        issue = self.issue()
        compilation = self.compilation()
        path = self.base + '/compilations/' + compilation['id']
        adopted = self.call(path, {'version': 0, 'record_version': compilation['version'], 'issue_ids': [issue['id']],
                            'selections': [self.selected(issue, record, kind='editor_summary')]}, 'PUT')
        self.assertEqual(adopted.status_code, 200, adopted.json)
        updated = self.call('/api/history/' + str(revision) + '/restore', {'version': record['version']})
        self.assertEqual(updated.status_code, 200, updated.json)
        self.assertEqual(self.clients['researcher'].get('/api/attachments/' + aid).status_code, 404)
        cover = self.get(self.base)['profile']['cover']
        with self.clients['colleague'].get(cover['url']) as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'Synthetic cover attachment')
        basis_file = self.get(path)['selections'][0]['basis']['snapshot']['attachments'][0]
        self.assertEqual(self.call(path, {'version': 1, 'record_version': compilation['version'], 'issue_ids': [issue['id']], 'selections': []}, 'PUT').status_code, 200)
        with self.clients['colleague'].get(basis_file['url']) as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'Synthetic cover attachment')
        self.assertEqual(self.clients['colleague'].get(basis_file['url'].replace(aid, 'unrelated-attachment')).status_code, 404)
        current = self.get('/api/records/' + rid)
        self.assertEqual(self.call('/api/records/' + rid, {'version': current['version'], 'visibility': 'restricted'}, 'PUT').status_code, 200)
        self.assertEqual(self.clients['colleague'].get(basis_file['url']).status_code, 404)

    def test_readable_export_and_new_directory_restore_keep_covers_metrics_order_and_adopted_versions(self):
        from PIL import Image
        image = io.BytesIO()
        Image.new('RGB', (10, 14), '#234e78').save(image, format='PNG')
        raw = image.getvalue()
        csrf = self.clients['researcher'].get('/api/session').json['csrf']
        upload = self.clients['researcher'].post(self.base + '/covers', data={'file': (io.BytesIO(raw), 'synthetic.png')}, headers={'X-CSRF-Token': csrf})
        self.assertEqual(upload.status_code, 201, upload.json)
        cover = {'file_id': upload.json['id'], 'evidence': 'Program-generated synthetic image', 'illustrative': True, 'note': 'Does not identify a current issue.'}
        profile = {'version': 0, 'cover': cover, 'founded': '1980年代', 'metrics': [
            {'id': 'zero', 'kind': 'impact_factor', 'name': 'Synthetic ordinary IF', 'year': '2024', 'value': '0', 'evidence': 'Synthetic statement'},
            {'id': 'unknown', 'kind': 'five_year', 'name': 'Synthetic five year IF', 'year': '', 'value': '', 'evidence': 'Unclear synthetic year', 'raw_label': 'Unknown year'}]}
        self.assertEqual(self.call(self.base + '/profile', profile, 'PUT').status_code, 200)
        self.assertEqual(self.call(self.base + '/profile', {**profile, 'version': 1, 'founded': '1981'}, 'PUT').status_code, 200)
        first, second = self.issue(), self.issue(label='Synthetic combined issue', number='2—3')
        original_id = self.call('/api/records', {'title': 'Synthetic frozen original', 'kind': 'journal_article', 'abstract': 'Frozen synthetic abstract.'}).json['id']
        original = self.get('/api/records/' + original_id)
        compilation = self.compilation()
        path = self.base + '/compilations/' + compilation['id']
        self.assertEqual(self.call(path, {'version': 0, 'record_version': compilation['version'], 'issue_ids': [first['id'], second['id']], 'selections': [self.selected(first, original)]}, 'PUT').status_code, 200)
        self.assertEqual(self.call('/api/records/' + original_id, {'version': original['version'], 'abstract': 'New synthetic abstract.'}, 'PUT').status_code, 200)
        with self.clients['colleague'].get('/api/export/content') as response:
            self.assertEqual(response.status_code, 200, response.json)
            exported_bytes = response.data
        with zipfile.ZipFile(io.BytesIO(exported_bytes)) as archive:
            payload = json.loads(archive.read('content.json'))
            journal = payload['journal_archives'][0]
            self.assertEqual(journal['profile']['metrics'][0]['value'], '0')
            self.assertEqual(journal['compilations'][0]['selections'][0]['basis']['snapshot']['abstract'], 'Frozen synthetic abstract.')
            self.assertEqual(archive.read(journal['profile']['cover']['file']['path']), raw)
            source_page = next(path for path in archive.namelist() if path.startswith('sources/') and path.endswith('.html'))
            readable = archive.read(source_page).decode()
            for text in ['1980年代', 'Unknown year', 'Frozen synthetic abstract.', 'Book reviews', '采用时原文摘要']:
                self.assertIn(text, readable)
            self.assertIn(journal['profile']['cover']['file']['path'], readable)
        backup = Path(self.temp.name) / 'full-journal.zip'
        with self.call('/api/backup', {}, user='admin') as response:
            self.assertEqual(response.status_code, 200)
            backup.write_bytes(response.data)
        target = Path(self.temp.name) / 'new-restored-directory'
        restore_backup(backup, target)
        restored = self.login('colleague', create_app(target, testing=True, embedded_worker=False))
        detail = restored.get(self.base).json
        self.assertEqual(detail['profile']['founded'], '1981')
        self.assertEqual(detail['profile']['metrics'][1]['year'], '')
        with restored.get(detail['profile']['cover']['url']) as response:
            self.assertEqual(response.data, raw)
        adopted = restored.get(path).json['selections'][0]
        self.assertTrue(adopted['needs_review'])
        self.assertEqual(adopted['basis']['snapshot']['abstract'], 'Frozen synthetic abstract.')
        self.assertEqual(len(restored.get(self.base + '/profile/history').json['items']), 2)
        with zipfile.ZipFile(backup) as archive:
            files = {n: archive.read(n) for n in archive.namelist()}
        manifest = json.loads(files['manifest.json'])
        cover_path = next(n for n in files if n.startswith('journal-covers/'))
        del files[cover_path]
        del manifest['files'][cover_path]
        files['manifest.json'] = json.dumps(manifest).encode()
        corrupt = Path(self.temp.name) / 'missing-historical-cover.zip'
        with zipfile.ZipFile(corrupt, 'w') as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        rejected = Path(self.temp.name) / 'must-not-be-created'
        with self.assertRaisesRegex(ValueError, '封面'):
            restore_backup(corrupt, rejected)
        self.assertFalse(rejected.exists())


if __name__ == '__main__':
    unittest.main()
