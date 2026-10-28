"""Find authorized work and reuse exact originals via public HTTP."""
import io
import json
import unittest
import zipfile
from copy import deepcopy
import os
import tracemalloc
import time

from tests import test_topic_finals as finals
from tests import test_journal_collaboration as journals


class CollaborationLibraryTests(unittest.TestCase):
    setUp = finals.TopicFinalTests.setUp
    login = finals.TopicFinalTests.login
    call = finals.TopicFinalTests.call
    topic = finals.TopicFinalTests.topic
    docx = staticmethod(finals.TopicFinalTests.docx)
    meeting = finals.TopicFinalTests.meeting
    draft = finals.TopicFinalTests.draft
    workflow = finals.TopicFinalTests.workflow
    ready = finals.TopicFinalTests.ready
    final = finals.TopicFinalTests.final
    summary = finals.TopicFinalTests.summary
    work = journals.JournalCollaborationTests.work
    upload = journals.JournalCollaborationTests.upload

    def package(self, business, wid, scope='all', who='colleague'):
        response = self.clients[who].get(f'/api/collaboration/materials/{business}/{wid}?scope={scope}')
        self.assertEqual(response.status_code, 200, response.json)
        self.addCleanup(response.close)
        return response.data

    def test_find_work_and_products_with_current_scope_and_country(self):
        tid, aid, sid = self.ready()
        self.final(tid, aid, sid)
        wid = self.work()
        self.upload(wid)
        result = self.clients['colleague'].get('/api/collaboration/works?scope=participating')
        self.assertEqual(result.status_code, 200)
        self.assertEqual([x['id'] for x in result.json['items']], [tid])
        products = self.clients['colleague'].get('/api/collaboration/works?view=products&business=topic').json
        self.assertEqual(products['total'], 1)
        self.assertEqual(products['items'][0]['products'][0]['submission_id'], sid)
        self.assertEqual(self.clients['colleague'].get('/api/collaboration/works?scope=leading').json['total'], 0)
        self.assertEqual(self.clients['researcher'].get('/api/collaboration/works?business=journal&scope=leading').json['total'], 0)
        self.assertEqual(self.clients['researcher'].get('/api/collaboration/works?country=不存在').json['total'], 0)
        self.assertEqual(self.clients['researcher'].get('/api/collaboration/works?business=journal').json['items'][0]['id'], wid)

    def test_latest_work_sort_uses_handoffs_not_only_topic_metadata(self):
        first = self.topic(theme='先开期后提交')
        time.sleep(1.05)
        second = self.topic(theme='后开期尚未提交')
        time.sleep(1.05)
        self.assertEqual(self.call(f'/api/collaboration/topics/{first}/candidates', {'version': 0, 'topic_version': 1, 'request_id': 'newest-candidate-1'}, file=('报告.txt', b'latest submitted original')).status_code, 201)
        result = self.clients['colleague'].get('/api/collaboration/works?business=topic').json
        self.assertEqual([w['id'] for w in result['items']], [first, second])

    def test_scoped_package_preserves_old_adoption_and_independent_bytes(self):
        from scripts.verify_work_materials import verify
        tid, aid, sid = self.ready()
        final = self.final(tid, aid, sid).json
        self.summary(tid, [final['id']])
        self.draft(tid, aid, version=1, file=('later.txt', b'later never adopted manuscript'))
        path = self.data_dir.parent / 'products.zip'
        path.write_bytes(self.package('topic', tid, 'products'))
        self.assertEqual(verify(path), 2)
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            adopted = manifest['workflow']['summaries'][0]['adoptions'][0]
            self.assertEqual((adopted['id'], adopted['submission_id']), (final['id'], sid))
            self.assertEqual(archive.read(adopted['path']), b'independent final original')
            self.assertNotIn(b'later never adopted manuscript', [archive.read(f['path']) for f in manifest['files']])
        for scope, count in [('all', 3), ('process', 2)]:
            path.write_bytes(self.package('topic', tid, scope))
            self.assertEqual(verify(path), count)

    def test_reassigned_article_keeps_historical_author_and_adoption(self):
        from scripts.verify_work_materials import verify
        tid, aid, sid = self.ready()
        final = self.final(tid, aid, sid).json
        self.summary(tid, [final['id']])
        self.assertEqual(self.meeting(tid, version=1, assignments=[{'id': aid, 'title': '调整后的分工', 'author_id': 'researcher', 'country': '波兰'}]).status_code, 201)
        self.assertEqual(self.draft(tid, aid, version=1, who='researcher', meeting_version=2).status_code, 201)
        path = self.data_dir.parent / 'reassigned.zip'
        path.write_bytes(self.package('topic', tid))
        self.assertEqual(verify(path), 3)

    def test_journal_scopes_and_history_do_not_create_a_topic_review_role(self):
        from scripts.verify_work_materials import verify
        wid = self.work()
        sid = self.upload(wid, raw=b'journal chosen product').json['id']
        self.assertEqual(self.call(f'/api/collaboration/journals/{wid}/product', {'version': 2, 'submission_id': sid}).status_code, 200)
        self.upload(wid, version=3, key='later-journal-1', raw=b'journal newer draft')
        self.upload(wid, version=4, key='review-journal-1', kind='review', raw=b'journal review material')
        path = self.data_dir.parent / 'journal.zip'
        for scope, expected in [('products', [b'journal chosen product']), ('process', [b'journal newer draft', b'journal review material']), ('all', [b'journal chosen product', b'journal newer draft', b'journal review material'])]:
            path.write_bytes(self.package('journal', wid, scope))
            self.assertEqual(verify(path), len(expected))
            with zipfile.ZipFile(path) as z:
                m = json.loads(z.read('manifest.json'))
                self.assertCountEqual([z.read(f['path']) for f in m['files']], expected)
                self.assertEqual(m['journal']['current_product_id'], sid)

    def test_verifier_rejects_semantic_forgery_even_when_file_hashes_still_match(self):
        from scripts.verify_work_materials import verify
        tid, aid, sid = self.ready()
        final = self.final(tid, aid, sid).json
        self.summary(tid, [final['id']])
        self.draft(tid, aid, version=1, file=('unadopted.txt', b'never chosen original'))
        raw = self.package('topic', tid)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            members = {n: z.read(n) for n in z.namelist()}
        original = json.loads(members['manifest.json'])
        mutations = []
        changed = deepcopy(original)
        changed['workflow']['summaries'][0]['adoptions'][0]['submission_id'] = changed['workflow']['assignments'][0]['submissions'][0]['id']
        mutations.append(changed)
        changed = deepcopy(original)
        changed['workflow']['assignments'][0]['submissions'] = changed['workflow']['assignments'][0]['submissions'][:1]
        mutations.append(changed)
        changed = deepcopy(original)
        changed['workflow']['summaries'][0]['adoptions'] = []
        mutations.append(changed)
        changed = deepcopy(original)
        changed['workflow']['assignments'][0]['finals'][0]['topic_id'] = 'another-period'
        mutations.append(changed)
        changed = deepcopy(original)
        changed['scope'] = 'products'
        mutations.append(changed)
        path = self.data_dir.parent / 'forged.zip'
        for m in mutations:
            with zipfile.ZipFile(path, 'w') as z:
                for name, content in members.items():
                    z.writestr(name, json.dumps(m).encode() if name == 'manifest.json' else content)
            with self.assertRaises(ValueError):
                verify(path)

    def test_current_membership_qualification_visibility_and_account_rechecked(self):
        tid, aid, sid = self.ready()
        self.final(tid, aid, sid)
        wid = self.work(kind='compilation', visibility='restricted')
        self.upload(wid)
        self.assertEqual(self.clients['colleague'].get(f'/api/collaboration/materials/journal/{wid}').status_code, 404)
        self.assertEqual(self.call(f'/api/collaboration/topics/{tid}', {'version': 1, 'theme': '移出后不泄漏', 'participant_ids': []}, method='PUT').status_code, 200)
        for query in ['', '?view=products', '?q=移出', '?country=拉脱维亚', '?participant=colleague']:
            result = self.clients['colleague'].get('/api/collaboration/works' + query)
            self.assertNotIn(tid, [w['id'] for w in result.json['items']])
            self.assertEqual(result.json['total'], len(result.json['items']))
        self.assertEqual(self.clients['colleague'].get(f'/api/collaboration/materials/topic/{tid}').status_code, 404)
        self.assertEqual(self.call('/api/collaboration/qualifications/researcher', {'version': 1, 'enabled': False}, 'admin', 'PUT').status_code, 200)
        self.assertEqual(self.clients['researcher'].get('/api/collaboration/works?scope=leading&business=topic').json['total'], 0)
        self.assertEqual(self.clients['researcher'].get('/api/collaboration/topics?scope=leading').json['items'], [])
        self.assertEqual(self.clients['admin'].get('/api/collaboration/works?scope=maintenance').json['total'], 2)
        self.assertEqual(self.clients['colleague'].get('/api/collaboration/works?scope=maintenance').status_code, 403)
        for path in ['/api/collaboration/works?from=bad', '/api/collaboration/works?from=2026-11-01&to=2026-01-01', f'/api/collaboration/materials/topic/{tid}?scope=unknown']:
            self.assertEqual(self.clients['researcher'].get(path).status_code, 400)

    def test_shared_record_does_not_publish_topic_files_or_restricted_originals(self):
        tid, aid, sid = self.ready()
        self.final(tid, aid, sid, visibility='shared', sharing_confirmed=True)
        self.assertEqual(self.call('/api/members', {'username': 'outside', 'name': '非参与成员', 'password': 'LocalDemo2026!', 'role': 'researcher'}, 'admin').status_code, 201)
        self.clients['outside'] = self.login('outside')
        self.assertEqual(self.clients['outside'].get('/api/collaboration/works?view=products').json['total'], 0)
        self.assertEqual(self.clients['outside'].get(f'/api/collaboration/materials/topic/{tid}').status_code, 404)
        private = self.call('/api/records', {'kind': 'report', 'title': '受限原文标题不可泄漏', 'visibility': 'restricted', 'sharing_confirmed': True}, file=('原文.txt', b'private original bytes')).json['id']
        shared = self.call('/api/records', {'kind': 'compilation', 'title': '共享既有成果', 'visibility': 'shared', 'linked_ids': [private], 'sharing_confirmed': True}).json['id']
        journal = self.work(record_id=shared)
        self.upload(journal)
        raw = self.package('journal', journal)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            self.assertNotIn(private.encode(), z.read('manifest.json'))
            self.assertNotIn(b'private original bytes', [z.read(n) for n in z.namelist()])
        self.assertEqual(self.clients['colleague'].get('/api/records/' + private).status_code, 404)
        self.assertEqual(self.call('/api/members/colleague', {'active': False}, 'admin', 'PUT').status_code, 200)
        for path in ['/api/collaboration/works', f'/api/collaboration/materials/topic/{tid}', f'/api/collaboration/materials/journal/{journal}']:
            self.assertEqual(self.clients['colleague'].get(path).status_code, 401)

    def test_failed_original_does_not_return_partial_zip(self):
        tid, aid, sid = self.ready()
        self.final(tid, aid, sid)
        original = next((self.data_dir / 'handoffs').iterdir())
        original.write_bytes(b'corrupted synthetic original')
        response = self.clients['colleague'].get(f'/api/collaboration/materials/topic/{tid}')
        self.assertEqual(response.status_code, 409)
        self.assertNotEqual(response.mimetype, 'application/zip')
        original.unlink()
        self.assertEqual(self.clients['colleague'].get(f'/api/collaboration/materials/topic/{tid}').status_code, 404)

    def test_export_memory_does_not_grow_with_all_original_history(self):
        wid = self.work()
        # 20MiB of independently generated, poorly compressible UTF-8 originals.
        for version in range(10):
            raw = os.urandom(1024 * 1024).hex().encode()
            self.assertEqual(self.upload(wid, version=version + 1, key=f'memory-original-{version}', raw=raw).status_code, 201)
        tracemalloc.start()
        try:
            response = self.clients['researcher'].get(f'/api/collaboration/materials/journal/{wid}')
            _, peak = tracemalloc.get_traced_memory()
            self.assertEqual(response.status_code, 200)
            response.close()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 12 * 1024 * 1024, 'Export retained an entire original history or ZIP in memory')



