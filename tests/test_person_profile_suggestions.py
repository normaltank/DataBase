"""Person enrichment at authenticated HTTP, persistent worker and backup seams."""
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch
import unittest

from tests import test_assisted_intake as intake_fixture, test_bylines as byline_fixture
from tests import test_archive_suggestions as archive_fixture


class PersonProfileSuggestionsTests(unittest.TestCase):
    setUp = intake_fixture.AssistedIntakeTests.setUp
    call = intake_fixture.AssistedIntakeTests.call
    get = byline_fixture.BylineTests.get
    person = byline_fixture.BylineTests.person
    merge = byline_fixture.BylineTests.merge
    source = byline_fixture.BylineTests.source
    synthetic = archive_fixture.ArchiveSuggestionsTests.synthetic

    def prepare(self):
        self.synthetic()
        self.pid = self.person('Ada Example')
        self.prefix = '/api/people/' + self.pid + '/profile-suggestions'
        self.bio = 'Ada Example is a researcher at Synthetic University. She completed her doctorate in 2009. ' + 'Complete career detail retained. ' * 700
        self.page = '<html><nav>Navigation must stay outside biography</nav><h1>Ada Example</h1><div class="post__text"><p>' + self.bio + '</p><h2>Career</h2><p>She was a fellow from 2010 to 2014.</p><h2>Publications</h2><a href="/work/one">A synthetic work</a></div><footer>Footer</footer></html>'
        self.fetcher = lambda url: {'url': url, 'content_type': 'text/html', 'bytes': self.page.encode(), 'text': self.page}
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': [{'field': 'introduction',
            'value': '合成示例：Ada Example 的研究经历，博士取得于2009年。', 'evidence_id': value['documents'][0]['id'],
            'quote': 'She completed her doctorate in 2009.'}]}

    def queue(self, request_id='one'):
        return self.call(self.prefix, {'version': self.get('/api/people/' + self.pid)['version'],
            'url': 'https://profiles.example/ada', 'identity_confirmation': True, 'request_id': request_id})

    def process(self):
        self.assertEqual(self.call('/api/admin/archive-jobs/run', user='admin').status_code, 200)
        return self.get(self.prefix)

    def database_change(self, sql, parameters=()):
        from platform_app.store import connect
        db = connect(Path(self.app.config['DATA_DIR']) / 'platform.sqlite3')
        try:
            with db:
                db.execute(sql, parameters)
        finally:
            db.close()

    def decide(self, state, action='adopt'):
        return self.call(self.prefix + '/decide', {'version': state['version'], action: [c['id'] for c in state['candidates'] if c['status'] == 'pending']}, user='colleague')

    def test_complete_profile_queue_comparison_manual_adoption_export_restore(self):
        self.prepare()
        queued = self.queue()
        self.assertEqual(queued.status_code, 201, queued.json)
        self.assertEqual(self.queue().json['id'], queued.json['id'])
        status = self.get('/api/admin/ai', user='admin')
        task = next(t for t in status['tasks'] if t.get('archive_job_id') == queued.json['id'])
        self.assertEqual((task['target_type'], task['target_id'], task['task'], task['title']),
                         ('person', self.pid, 'person-profile-v1', 'Ada Example'))
        state = self.process()
        self.assertEqual(state['jobs'][0]['status'], 'ready', state['jobs'])
        document = state['materials'][0]
        self.assertIn(self.bio.strip(), document['biography'])
        self.assertNotIn('Navigation must', document['biography'])
        self.assertNotIn('Footer', document['biography'])
        self.assertEqual(document['works'][0]['url'], 'https://profiles.example/work/one')
        self.assertEqual(self.get('/api/people/' + self.pid)['introduction_text'], '')
        candidate = state['candidates'][0]
        self.assertEqual(candidate['before'], '')
        self.assertIn('2009', candidate['evidence']['quote'])
        result = self.call(self.prefix + '/decide', {'version': 1, 'adopt': [candidate['id']]}, user='colleague')
        self.assertEqual(result.status_code, 200, result.json)
        person = self.get('/api/people/' + self.pid)
        self.assertEqual(person['version'], 2)
        self.assertIn('2009', person['introduction_text'])
        self.assertIn(document['sha256'], person['sources'])
        self.assertEqual(self.get('/api/people/' + self.pid + '/works')['total'], 0)
        export = self.clients['researcher'].get('/api/export/content?person=' + self.pid)
        self.assertEqual(export.status_code, 200, export.json)
        with zipfile.ZipFile(io.BytesIO(export.data)) as bundle:
            payload = json.loads(bundle.read('content.json'))
            offline = bundle.read(payload['people'][0]['path']).decode()
        self.assertIn(self.bio.strip(), offline)
        self.assertIn('机器建议', offline)
        person_targets = [t for t in payload['archive_suggestions']['targets'] if t['target_type'] == 'person']
        self.assertEqual(person_targets[0]['candidates'][0]['status'], 'adopted')
        from platform_app.maintenance import create_backup, restore_backup
        restored = Path(self.temp.name) / 'restored'
        restore_backup(create_backup(self.app.config['DATA_DIR']), restored)
        from platform_app.web import create_app
        app = create_app(restored, testing=True)
        client = app.test_client()
        token = client.get('/api/session').json['csrf']
        self.assertEqual(client.post('/api/login', json={'username': 'researcher', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': token}).status_code, 200)
        saved = client.get(self.prefix).json
        self.assertEqual(saved['materials'][0]['biography'], document['biography'])
        self.assertEqual(saved['candidates'][0]['status'], 'adopted')

    def test_search_failure_and_wrong_person_are_honest_and_do_not_send_to_ai(self):
        self.prepare()
        from platform_app.intake import AcquisitionError
        with patch('platform_app.intake.fetch_document', side_effect=AcquisitionError('HTTP 403', http_status=403)):
            search = self.call('/api/people/' + self.pid + '/profile-candidates', {'name': 'Ada Example', 'language': 'et'})
        self.assertEqual(search.status_code, 200, search.json)
        self.assertEqual(search.json['status'], 'unavailable')
        self.assertEqual(search.json['http_status'], 403)
        self.assertEqual(search.json['candidates'], [])
        self.page = '<h1>Different Person</h1><main><p>' + self.bio + '</p></main>'
        self.assertEqual(self.queue().status_code, 201)
        state = self.process()
        self.assertEqual(state['jobs'][0]['status'], 'failed')
        self.assertIn('姓名', state['jobs'][0]['reason'])
        self.assertEqual(state['candidates'], [])
        self.assertEqual(self.get('/api/admin/ai', user='admin')['attempts'], [])

    def test_human_revision_blocks_old_candidate_and_new_task_uses_current_original(self):
        self.prepare()
        self.queue()
        old = self.process()
        result = self.call('/api/people/' + self.pid, {'version': 1, 'introduction_html': '<p>人工保留的介绍</p>', 'change_note': '合成并发修订'}, method='PUT')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.decide(old).status_code, 409)
        self.assertEqual(self.get('/api/people/' + self.pid)['introduction_text'], '人工保留的介绍')
        self.assertTrue(self.get(self.prefix)['candidates'][0]['stale'])
        self.assertEqual(self.queue('after-human').status_code, 201)
        current = self.process()
        candidate = next(c for c in current['candidates'] if c['base_version'] == 2)
        self.assertEqual(candidate['before'], '人工保留的介绍')
        adopted = self.call(self.prefix + '/decide', {'version': 2, 'adopt': [candidate['id']]}, user='colleague')
        self.assertEqual(adopted.status_code, 200, adopted.json)
        history = self.get('/api/people/' + self.pid + '/history')['items']
        self.assertTrue(any(h['snapshot']['introduction_text'] == '人工保留的介绍' for h in history))

    def test_actor_revocation_during_provider_call_discards_result_and_retains_cost(self):
        self.prepare()
        self.queue()
        archive_fixture.Provider.before_reply = lambda: self.database_change("UPDATE users SET active=0 WHERE id='researcher'")
        self.assertEqual(self.call('/api/admin/archive-jobs/run', user='admin').status_code, 200)
        state = self.get(self.prefix, user='colleague')
        self.assertEqual(state['jobs'][0]['status'], 'invalidated')
        self.assertEqual(state['candidates'], [])
        ai = self.get('/api/admin/ai', user='admin')
        self.assertEqual(len(ai['attempts']), 1)
        self.assertGreater(ai['charged_units'] + ai['held_units'], 0)
        self.assertEqual(self.clients['researcher'].get(self.prefix).status_code, 401)

    def test_identity_merge_invalidates_old_biography_without_reassigning_it(self):
        self.prepare()
        self.queue()
        state = self.process()
        keep = self.person('Different Person')
        from tests.test_person_identity import PersonIdentityTests
        preview = PersonIdentityTests.compare(self, keep, self.pid)
        intent = PersonIdentityTests.intent(self, preview, choices={'name': 'keep', 'original_name': 'keep', 'chinese_name': 'keep', 'introduction': 'keep', 'avatar': 'keep'})
        merged = self.call('/api/people/merge', intent)
        self.assertEqual(merged.status_code, 200, merged.json)
        self.assertEqual(self.decide(state).status_code, 409)
        self.assertEqual(self.get('/api/people/' + keep)['introduction_text'], '')
        exported = self.clients['colleague'].get('/api/export/content?person=' + self.pid)
        self.assertEqual(exported.status_code, 200, exported.json)
        with zipfile.ZipFile(io.BytesIO(exported.data)) as bundle:
            payload = json.loads(bundle.read('content.json'))
        old = next(x for x in payload['archive_suggestions']['targets'] if x['target_id'] == self.pid)
        self.assertEqual(old['candidates'][0]['status'], 'pending')
        self.assertTrue(old['candidates'][0]['stale'])
        split = PersonIdentityTests.split_intent(self, merged.json['event_id'])
        result = self.call('/api/people/split', split)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertTrue(self.get(self.prefix)['candidates'][0]['stale'])

    def test_paused_unknown_cost_stop_and_cancel_use_shared_worker(self):
        from platform_app.archive_suggestions import run_pending
        self.prepare()
        self.assertEqual(self.queue().status_code, 201)
        self.assertEqual(run_pending(self.app.config['DATA_DIR'], stopping=lambda: True), {'tasks': 0, 'completed': 0})
        paused = self.call('/api/admin/ai/pause', {'paused': True}, user='admin')
        self.assertEqual(paused.status_code, 200, paused.json)
        self.assertEqual(self.process()['jobs'][0]['status'], 'paused')
        self.assertEqual(self.get('/api/admin/ai', user='admin')['attempts'], [])
        self.assertEqual(self.call('/api/admin/ai/pause', {'paused': False}, user='admin').status_code, 200)
        self.database_change("UPDATE archive_jobs SET next_run='' WHERE target_type='person'")
        archive_fixture.Provider.usage = False
        state = self.process()
        self.assertEqual(state['jobs'][0]['status'], 'paused')
        self.assertGreater(self.get('/api/admin/ai', user='admin')['held_units'], 0)
        self.assertEqual(self.call('/api/archive-jobs/' + state['jobs'][0]['id'] + '/cancel').status_code, 200)
        self.assertEqual(self.get(self.prefix)['jobs'][0]['status'], 'cancelled')

    def test_reject_does_not_reappear_and_search_candidates_never_create_people(self):
        self.prepare()
        self.queue()
        first = self.process()
        self.assertEqual(self.decide(first, 'reject').status_code, 200)
        self.queue('same-evidence')
        second = self.process()
        self.assertEqual(second['jobs'][0]['status'], 'empty')
        self.assertEqual(len(second['candidates']), 1)
        before = self.get('/api/people')['total']
        raw = json.dumps({'query': {'search': [{'title': 'Different Ada', 'snippet': '<span>Ada Example</span> mentioned'}]}}).encode()
        with patch('platform_app.intake.fetch_document', return_value={'bytes': raw, 'content_type': 'application/json'}):
            found = self.call('/api/people/' + self.pid + '/profile-candidates', {'name': 'Ada Example', 'language': 'en'})
        self.assertEqual(found.status_code, 200)
        self.assertTrue(found.json['candidates'][0]['name_only'])
        self.assertEqual(self.get('/api/people')['total'], before)
        self.assertEqual(self.call(self.prefix, {'url': 'https://profiles.example/ada', 'version': 1, 'request_id': 'no-confirmation'}).status_code, 400)

    def test_direct_employment_is_separate_optional_and_unknown_dates_stay_empty(self):
        self.prepare()
        sid = self.source('Synthetic University')
        self.page = '<h1>Ada Example</h1><article><p>Ada Example is a researcher at Synthetic University.</p><p>She completed her doctorate in 2009. All other dates are unknown.</p></article>'
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': [
            {'field': 'employment', **value['employment_facts'][0]},
            {'field': 'introduction', 'value': '合成人物介绍。', 'evidence_id': value['documents'][0]['id'], 'quote': 'She completed her doctorate in 2009.'}]}
        self.queue()
        state = self.process()
        role = next(c for c in state['candidates'] if c['field'] == 'employment')
        intro = next(c for c in state['candidates'] if c['field'] == 'introduction')
        self.assertEqual(self.get('/api/people/' + self.pid + '/employments')['items'], [])
        result = self.call(self.prefix + '/decide', {'version': 1, 'adopt': [intro['id']]})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.get('/api/people/' + self.pid + '/employments')['items'], [])
        self.queue('new-version-role')
        current = self.process()
        role = next(c for c in current['candidates'] if c['field'] == 'employment' and c['base_version'] == 2)
        result = self.call(self.prefix + '/decide', {'version': 2, 'adopt': [role['id']]})
        self.assertEqual(result.status_code, 200, result.json)
        saved = self.get('/api/people/' + self.pid + '/employments')['items'][0]
        self.assertEqual(saved['institution_id'], sid)
        self.assertEqual(saved['start_date'], '')
        self.assertEqual(saved['end_date'], '')
        self.assertIn('SHA256', saved['evidence'])

    def test_saved_biography_tamper_is_rejected_by_http_and_restore(self):
        self.prepare()
        self.queue()
        state = self.process()
        self.database_change("UPDATE archive_evidence SET text=json_set(text,'$.biography','invented material') WHERE target_type='person'")
        self.assertEqual(self.clients['colleague'].get(self.prefix).status_code, 409)
        from platform_app.maintenance import create_backup, restore_backup
        with self.assertRaises(ValueError):
            restore_backup(create_backup(self.app.config['DATA_DIR']), Path(self.temp.name) / 'tampered-restore')

    def test_synthetic_demo_proposals_adoption_and_restore_have_zero_calls(self):
        from portable.demo_seed import seed_profile_examples
        ids = [self.person('演示｜合成人物甲'), self.person('演示｜合成人物乙')]
        seed_profile_examples(self.app, ids, self.clients['researcher'], self.clients['colleague'])
        states = [self.get('/api/people/' + pid + '/profile-suggestions') for pid in ids]
        self.assertTrue(all(c['status'] == 'pending' for c in states[0]['candidates']))
        self.assertEqual({c['status'] for c in states[1]['candidates']}, {'adopted', 'rejected'})
        self.assertIn('完全虚构', states[0]['materials'][0]['biography'])
        self.assertTrue(all(c['machine']['synthetic'] and c['machine']['calls'] == 0 for state in states for c in state['candidates']))
        ai = self.get('/api/admin/ai', user='admin')
        self.assertEqual(ai['attempts'], [])
        self.assertEqual(ai['charged_units'], 0)
        self.assertEqual(ai['held_units'], 0)
        from platform_app.maintenance import create_backup, restore_backup
        restore_backup(create_backup(self.app.config['DATA_DIR']), Path(self.temp.name) / 'synthetic-restored')

    def test_orcid_public_biography_uses_person_endpoint_and_never_fetches_works(self):
        self.prepare()
        requested = []
        raw = json.dumps({'name': {'given-names': {'value': 'Ada'}, 'family-name': {'value': 'Example'}},
            'biography': {'content': self.bio}}).encode()
        def fetch(url):
            requested.append(url)
            return {'url': url, 'bytes': raw, 'content_type': 'application/json'}
        self.fetcher = fetch
        result = self.call(self.prefix, {'version': 1, 'identity_confirmation': True, 'request_id': 'orcid', 'url': 'https://orcid.org/0000-0002-1825-0097'})
        self.assertEqual(result.status_code, 201)
        state = self.process()
        self.assertEqual(state['jobs'][0]['status'], 'ready', state['jobs'])
        self.assertEqual(requested, ['https://pub.orcid.org/v3.0/0000-0002-1825-0097/person'])
        self.assertEqual(state['materials'][0]['biography'], self.bio)

    def test_no_biography_challenge_and_404_remain_failed_without_ai(self):
        self.prepare()
        self.page = '<h1>Ada Example</h1><nav>' + self.bio + '</nav><script>fake biography</script>'
        self.queue('navigation-only')
        self.assertEqual(self.process()['jobs'][0]['status'], 'failed')
        self.page = '<h1>Ada Example</h1><main><p>Checking your browser. Verify you are human. Enable JavaScript and cookies. Please wait before continuing to this protected site.</p></main>'
        self.queue('challenge')
        challenge = self.process()
        self.assertIn('访问验证', challenge['jobs'][0]['reason'])
        from platform_app.intake import AcquisitionError
        with patch('platform_app.intake.fetch_document', side_effect=AcquisitionError('HTTP 404', http_status=404)):
            self.queue('missing-page')
            state = self.process()
        self.assertIn('404', state['jobs'][0]['reason'])
        self.assertEqual(self.get('/api/admin/ai', user='admin')['attempts'], [])

    def test_same_employment_from_two_selected_pages_is_not_inserted_twice(self):
        self.prepare()
        self.source('Synthetic University')
        self.page = '<h1>Ada Example</h1><article><p>Ada Example is a researcher at Synthetic University.</p><p>She completed her doctorate in 2009. All other dates are unknown.</p></article>'
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': [{'field': 'employment', **value['employment_facts'][0]}]}
        self.queue('first-page')
        self.process()
        queued = self.call(self.prefix, {'version': 1, 'url': 'https://university.example/ada',
            'identity_confirmation': True, 'request_id': 'second-page'})
        self.assertEqual(queued.status_code, 201)
        state = self.process()
        self.assertEqual(len(state['candidates']), 2)
        self.assertEqual(self.decide(state).status_code, 400)
        self.assertEqual(self.get('/api/people/' + self.pid + '/employments')['items'], [])
        self.assertEqual(self.get('/api/people/' + self.pid)['version'], 1)


if __name__ == '__main__':
    unittest.main()
