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
