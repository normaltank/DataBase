"""Author suggestions observed through authenticated HTTP and portable recovery."""
import json
import io
import zipfile
from pathlib import Path
import unittest
from tests import test_archive_suggestions as archive_fixture

from tests import test_assisted_intake as intake_fixture, test_bylines as byline_fixture


class AuthorSuggestionsTests(unittest.TestCase):
    setUp = intake_fixture.AssistedIntakeTests.setUp
    call = intake_fixture.AssistedIntakeTests.call
    preview = intake_fixture.AssistedIntakeTests.preview
    get = byline_fixture.BylineTests.get
    person = byline_fixture.BylineTests.person
    record = byline_fixture.BylineTests.record
    source = byline_fixture.BylineTests.source
    merge = byline_fixture.BylineTests.merge
    synthetic = archive_fixture.ArchiveSuggestionsTests.synthetic

    def queue_run(self, rid, request_id='one'):
        queued = self.call('/api/archive-jobs', {'record_ids': [rid], 'request_id': request_id})
        self.assertEqual(queued.status_code, 201, queued.json)
        self.assertEqual(self.call('/api/admin/archive-jobs/run', user='admin').status_code, 200)
        return self.get(f'/api/records/{rid}/suggestions')

    def test_public_orcid_all_authors_are_suggestions_until_one_atomic_human_decision(self):
        self.synthetic()
        authors = [{'given': name, 'family': 'Example', 'ORCID': 'https://orcid.org/' + oid,
                    'authenticated-orcid': False} for name, oid in [('Ada', '0000-0002-1825-0097'),
                    ('Bob', '0000-0001-5109-3700'), ('Carol', '0000-0002-9079-593X')]]
        raw = json.dumps({'message': {'title': ['Three authors'], 'DOI': '10.5555/three', 'author': authors}}).encode()
        self.fetcher = lambda url: {'url': url, 'content_type': 'application/json', 'bytes': raw, 'text': raw.decode()}
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': value['author_facts']}
        rid = self.record(title='Three authors', authors='Ada Example; Bob Example; Carol Example', doi='10.5555/three', url='https://article.example/three')
        before = self.get('/api/people')['total']
        state = self.queue_run(rid)
        self.assertEqual(state['coverage']['authors'], 3)
        self.assertEqual(state['coverage']['supported'], 3)
        self.assertEqual(len(state['candidates']), 3)
        self.assertIn('Ada', state['candidates'][0]['evidence']['quote'])
        self.assertIn('0000-0002-1825-0097', state['candidates'][0]['evidence']['quote'])
        self.assertEqual(self.get('/api/people')['total'], before)
        self.assertEqual(self.get(f'/api/records/{rid}/bylines')['items'], [])
        result = self.call(f'/api/records/{rid}/suggestions/decide', {'version': state['version'],
            'byline_version': state['byline_version'], 'adopt': [c['id'] for c in state['candidates']]}, user='colleague')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.get('/api/people')['total'], before + 3)
        rows = self.get(f'/api/records/{rid}/bylines')['items']
        self.assertEqual([b['raw_name'] for b in rows], ['Ada Example', 'Bob Example', 'Carol Example'])
        self.assertTrue(all(b['status'] == 'confirmed' for b in rows))
        self.assertTrue(all(self.get('/api/people/' + b['target_id'] + '/works')['total'] == 1 for b in rows))
        self.assertEqual(self.get('/api/records/' + rid)['authors'], 'Ada Example; Bob Example; Carol Example')
        self.assertEqual(self.get('/api/records/' + rid)['status'], 'pending')

    def native_case(self, names=('Ada', 'Bob'), suffix='pair'):
        self.synthetic()
        authors = [{'given': name, 'family': 'Example', 'ORCID': 'https://orcid.org/' + oid} for name, oid in
                   zip(names, ['0000-0002-1825-0097', '0000-0001-5109-3700', '0000-0002-9079-593X'])]
        raw = json.dumps({'message': {'title': ['Author sample'], 'DOI': '10.5555/' + suffix, 'author': authors}}).encode()
        self.fetcher = lambda url: {'url': url, 'content_type': 'application/json', 'bytes': raw, 'text': raw.decode()}
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': value['author_facts']}
        rid = self.record(authors='; '.join(n + ' Example' for n in names), doi='10.5555/' + suffix)
        return rid, self.queue_run(rid)

    def decision(self, rid, ids, **extra):
        state = self.get(f'/api/records/{rid}/suggestions')
        return self.call(f'/api/records/{rid}/suggestions/decide', {'version': state['version'],
            'byline_version': state['byline_version'], 'adopt': ids, **extra})

    def rewrite_candidate_backup(self, original, candidate_id, mutation, suffix):
        """Fault fixture: modify only the candidate patch and public integrity hashes."""
        import hashlib
        import sqlite3
        from contextlib import closing
        from platform_app.author_suggestions import candidate_fingerprint
        files = dict(original)
        database = Path(self.temp.name) / (suffix + '.sqlite3')
        database.write_bytes(files['platform.sqlite3'])
        with closing(sqlite3.connect(database)) as db, db:
            target, fact_json, patch_json = db.execute('SELECT target_id,value_json,patch_json FROM archive_candidates WHERE id=?', (candidate_id,)).fetchone()
            fact, operation = json.loads(fact_json), json.loads(patch_json)
            mutation(operation)
            db.execute('UPDATE archive_candidates SET patch_json=?,fingerprint=? WHERE id=?',
                (json.dumps(operation, ensure_ascii=False), candidate_fingerprint(target, fact, operation), candidate_id))
        files['platform.sqlite3'] = database.read_bytes()
        manifest = json.loads(files['manifest.json'])
        manifest['files']['platform.sqlite3'] = {'bytes': len(files['platform.sqlite3']), 'sha256': hashlib.sha256(files['platform.sqlite3']).hexdigest()}
        files['manifest.json'] = json.dumps(manifest).encode()
        archive = Path(self.temp.name) / (suffix + '.zip')
        with zipfile.ZipFile(archive, 'w') as bundle:
            for name, content in files.items():
                bundle.writestr(name, content)
        return archive

    def test_existing_identity_and_remaining_author_can_be_decided_one_at_a_time(self):
        pid = self.person('Ada Example')
        rid, state = self.native_case()
        first, second = state['candidates']
        self.assertEqual(self.decision(rid, [first['id']], choices={first['id']: pid}).status_code, 200)
        result = self.decision(rid, [second['id']])
        self.assertEqual(result.status_code, 200, result.json)
        rows = self.get(f'/api/records/{rid}/bylines')['items']
        self.assertEqual(rows[0]['target_id'], pid)
        self.assertEqual([b['status'] for b in rows], ['confirmed', 'confirmed'])

    def test_second_invalid_identity_rolls_back_new_person_and_all_formal_relations(self):
        pid = self.person('Bob Example')
        rid, state = self.native_case()
        before = self.get('/api/people')['total']
        second = state['candidates'][1]
        changed = self.call('/api/people/' + pid, {'version': 1, 'name': 'Human corrected Bob', 'change_note': 'Synthetic correction'}, method='PUT')
        self.assertEqual(changed.status_code, 200, changed.json)
        result = self.decision(rid, [c['id'] for c in state['candidates']], choices={second['id']: pid})
        self.assertEqual(result.status_code, 409, result.json)
        self.assertEqual(self.get('/api/people')['total'], before)
        self.assertEqual(self.get(f'/api/records/{rid}/bylines')['items'], [])
        self.assertEqual([c['status'] for c in self.get(f'/api/records/{rid}/suggestions')['candidates']], ['pending', 'pending'])

    def test_article_linked_profile_is_actual_material_and_wrong_subject_stays_unmatched(self):
        self.synthetic()
        article = '<h1>Article</h1><script type="application/ld+json">' + json.dumps({
            '@type': 'ScholarlyArticle', 'headline': 'Article', 'author': [
                {'@type': 'Person', 'name': 'Ada Example', 'url': 'https://profiles.example/ada'},
                {'@type': 'Person', 'name': 'Bob Example', 'url': 'https://profiles.example/bob'}]}) + '</script>'
        def fetch(url):
            text = '<h1>Ada Example</h1><p>Public author profile.</p>' if url.endswith('/ada') else '<h1>Different Person</h1>' if url.endswith('/bob') else article
            return {'url': url, 'content_type': 'text/html', 'text': text, 'bytes': text.encode()}
        self.fetcher = fetch
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': value['author_facts']}
        rid = self.record(authors='Ada Example; Bob Example', url='https://article.example/profile')
        state = self.queue_run(rid)
        self.assertEqual(len(state['candidates']), 2)
        good, bad = state['candidates']
        self.assertEqual(good['operation']['action'], 'create_person')
        self.assertEqual(bad['status'], 'unmatched')
        self.assertEqual(state['coverage']['remaining'], 1)
        self.assertEqual(self.decision(rid, [good['id']]).status_code, 200)
        self.assertEqual(self.decision(rid, [bad['id']]).status_code, 409)
        self.assertEqual(len(good['additional_evidence']), 1)
        self.assertEqual(good['additional_evidence'][0]['url'], 'https://profiles.example/ada')

    def test_model_cannot_move_one_authors_orcid_to_another_name_in_the_same_actual_response(self):
        rid, initial = self.native_case()
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': [
            {**value['author_facts'][0], 'orcid': value['author_facts'][1]['orcid']}]}
        # A new actual version forces a new gateway input rather than reusing the first cached response.
        original = self.fetcher
        def changed(url):
            document = original(url)
            raw = json.loads(document['bytes'])
            raw['message']['title'] = ['New actual version']
            document['bytes'] = json.dumps(raw).encode()
            document['text'] = document['bytes'].decode()
            return document
        self.fetcher = changed
        result = self.queue_run(rid, 'bad-model')
        self.assertEqual(result['jobs'][0]['status'], 'failed')
        self.assertEqual(len(result['candidates']), 2)
        self.assertEqual(self.get(f'/api/records/{rid}/bylines')['items'], [])

    def test_export_and_new_directory_restore_preserve_actual_materials_decisions_and_costs(self):
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        rid, state = self.native_case()
        self.assertEqual(self.decision(rid, [state['candidates'][0]['id']], reject=[state['candidates'][1]['id']]).status_code, 200)
        expected = self.get(f'/api/records/{rid}/suggestions')
        exported = self.clients['researcher'].get(f'/api/records/{rid}/suggestions/export')
        self.assertEqual(exported.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(exported.data)) as bundle:
            payload = json.loads(bundle.read('suggestions.json'))
            self.assertEqual(payload['targets'][0]['candidates'], expected['candidates'])
            self.assertTrue(any(n.startswith('evidence/') for n in bundle.namelist()))
        content = self.clients['researcher'].get('/api/export/content?id=' + rid)
        self.assertEqual(content.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(content.data)) as bundle:
            payload = json.loads(bundle.read('content.json'))
            self.assertIn(rid, [t['target_id'] for t in payload['archive_suggestions']['targets']])
        backup = self.call('/api/backup', user='admin')
        self.assertEqual(backup.status_code, 200)
        target = Path(self.temp.name) / 'restored'
        saved = Path(self.temp.name) / 'backup.zip'
        saved.write_bytes(backup.data)
        restore_backup(saved, target)
        backup.close()
        app = create_app(target, testing=True)
        client = byline_fixture.BylineTests.login(self, 'researcher', app)
        self.assertEqual(client.get(f'/api/records/{rid}/suggestions').json, expected)
        self.assertEqual(client.get(f'/api/records/{rid}/bylines').json, self.get(f'/api/records/{rid}/bylines'))

    def test_paused_record_job_has_the_correct_target_and_exception_link_in_costs(self):
        self.synthetic()
        self.assertEqual(self.call('/api/admin/ai/pause', {'paused': True}, user='admin').status_code, 200)
        raw = self.crossref(name='Ada').encode()
        self.fetcher = lambda url: {'url': url, 'content_type': 'application/json', 'bytes': raw, 'text': raw.decode()}
        rid = self.record(doi='10.5555/identity')
        state = self.queue_run(rid)
        self.assertEqual(state['jobs'][0]['status'], 'paused')
        costs = self.get('/api/admin/ai', 'admin')
        task = next((t for t in costs['tasks'] if t.get('target_id') == rid), None)
        self.assertIsNotNone(task)
        self.assertEqual(task['target_type'], 'record')
        self.assertEqual(task['task'], 'record-authors-v1')

    def test_organization_signature_and_article_units_do_not_infer_employment_from_publisher(self):
        institution = self.source('Example Institute')
        self.synthetic()
        html = '<h1>Article</h1><script type="application/ld+json">' + json.dumps({'@type': 'Article',
            'headline': 'Article', 'publisher': {'name': 'Example Institute'}, 'author': [
                {'@type': 'Organization', 'name': 'Example Institute'},
                {'@type': 'Person', 'name': 'Ada Example', 'sameAs': 'https://orcid.org/0000-0002-1825-0097',
                 'affiliation': {'name': 'Example Institute'}}]}) + '</script>'
        self.fetcher = lambda url: {'url': url, 'content_type': 'text/html', 'bytes': html.encode(), 'text': html}
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': value['author_facts']}
        rid = self.record(authors='Example Institute; Ada Example', url='https://article.example/institution')
        state = self.queue_run(rid)
        self.assertEqual(state['candidates'][0]['operation']['kind'], 'institution')
        ada = state['candidates'][1]
        self.assertEqual(ada['operation']['article_units'][0]['institution_id'], institution)
        self.assertEqual(ada['operation']['employments'], [])
        result = self.decision(rid, [c['id'] for c in state['candidates']], article_units=[ada['id']])
        self.assertEqual(result.status_code, 200, result.json)
        rows = self.get(f'/api/records/{rid}/bylines')['items']
        self.assertEqual(rows[0]['target_type'], 'institution')
        self.assertEqual(rows[0]['target_id'], institution)
        self.assertEqual(self.get('/api/people/' + rows[1]['target_id'] + '/employments')['items'], [])
        units = self.get(f'/api/records/{rid}/affiliations')['items']
        self.assertEqual([(u['byline_id'], u['institution_id']) for u in units], [(rows[1]['id'], institution)])

    def test_profile_explicit_subject_and_role_can_be_adopted_as_separate_employment(self):
        institution = self.source('Example Institute')
        self.synthetic()
        article = '<h1>Article</h1><script type="application/ld+json">' + json.dumps({'@type': 'Article',
            'headline': 'Article', 'author': {'@type': 'Person', 'name': 'Ada Example', 'url': 'https://profile.example/ada'}}) + '</script>'
        def fetch(url):
            html = '<h1>Ada Example</h1><p>Ada Example is Researcher at Example Institute.</p>' if url.endswith('/ada') else article
            return {'url': url, 'content_type': 'text/html', 'bytes': html.encode(), 'text': html}
        self.fetcher = fetch
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': value['author_facts']}
        rid = self.record(authors='Ada Example', url='https://article.example/roles')
        state = self.queue_run(rid)
        candidate = state['candidates'][0]
        self.assertEqual(candidate['operation']['employments'][0]['institution_id'], institution)
        result = self.decision(rid, [candidate['id']], employments=[candidate['id']])
        self.assertEqual(result.status_code, 200, result.json)
        pid = self.get(f'/api/records/{rid}/bylines')['items'][0]['target_id']
        employment = self.get('/api/people/' + pid + '/employments')['items'][0]
        self.assertEqual((employment['role'], employment['start_date'], employment['end_date']), ('Researcher', '', ''))
        self.assertEqual(self.get(f'/api/records/{rid}/affiliations')['items'], [])

    def test_multiple_author_units_are_atomic_and_rejected_identity_is_not_recharged(self):
        institution = self.source('Example Institute')
        self.synthetic()
        raw = json.dumps({'message': {'DOI': '10.5555/units', 'author': [
            {'given': name, 'family': 'Example', 'ORCID': 'https://orcid.org/' + oid,
             'affiliation': [{'name': 'Example Institute'}]} for name, oid in [
                 ('Ada', '0000-0002-1825-0097'), ('Bob', '0000-0001-5109-3700')]]}}).encode()
        self.fetcher = lambda url: {'url': url, 'content_type': 'application/json', 'bytes': raw, 'text': raw.decode()}
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': value['author_facts']}
        rid = self.record(authors='Ada Example; Bob Example', doi='10.5555/units')
        state = self.queue_run(rid)
        ids = [c['id'] for c in state['candidates']]
        result = self.decision(rid, ids, article_units=ids)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(len(self.get(f'/api/records/{rid}/affiliations')['items']), 2)
        other, pending = self.native_case(names=('Carol',), suffix='reject')
        cid = pending['candidates'][0]['id']
        self.assertEqual(self.decision(other, [], reject=[cid]).status_code, 200)
        costs = self.get('/api/admin/ai', 'admin')['charged_units']
        repeated = self.queue_run(other, 'again')
        self.assertEqual([c['status'] for c in repeated['candidates']], ['rejected'])
        self.assertEqual(self.get('/api/admin/ai', 'admin')['charged_units'], costs)

    def test_actual_orcid_person_conflict_is_preserved_without_adoptable_identity(self):
        self.synthetic()
        raw = self.crossref(name='Ada Example', doi='10.5555/orcid-conflict').encode()
        def fetch(url):
            value = {'name': {'given-names': {'value': 'Another'}, 'family-name': {'value': 'Person'}}} if 'pub.orcid.org' in url else json.loads(raw)
            data = json.dumps(value).encode()
            return {'url': url, 'content_type': 'application/json', 'bytes': data, 'text': data.decode()}
        self.fetcher = fetch
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': value['author_facts']}
        rid = self.record(authors='Ada Example', doi='10.5555/orcid-conflict')
        state = self.queue_run(rid)
        self.assertEqual(state['candidates'][0]['status'], 'unmatched')
        self.assertEqual(state['coverage']['remaining'], 1)
        self.assertEqual(self.decision(rid, [state['candidates'][0]['id']]).status_code, 409)
        self.assertIn('Another', state['candidates'][0]['additional_evidence'][0]['text'])

    def test_cancelled_inflight_reply_cannot_publish_candidates_or_release_unknown_cost(self):
        self.synthetic()
        raw = self.crossref(name='Ada Example').encode()
        self.fetcher = lambda url: {'url': url, 'content_type': 'application/json', 'bytes': raw, 'text': raw.decode()}
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': value['author_facts']}
        rid = self.record(authors='Ada Example', doi='10.5555/identity')
        queued = self.call('/api/archive-jobs', {'record_ids': [rid], 'request_id': 'cancel'})
        jid = queued.json['items'][0]['id']
        archive_fixture.Provider.usage = False
        archive_fixture.Provider.before_reply = lambda: self.assertEqual(self.call('/api/archive-jobs/' + jid + '/cancel').status_code, 200)
        self.assertEqual(self.call('/api/admin/archive-jobs/run', user='admin').status_code, 200)
        result = self.get(f'/api/records/{rid}/suggestions')
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['jobs'][0]['status'], 'cancelled')
        self.assertEqual(self.get(f'/api/records/{rid}/bylines')['items'], [])
        self.assertGreater(self.get('/api/admin/ai', 'admin')['held_units'], 0)

    def test_human_correction_and_removed_byline_are_protected_from_old_and_repeated_suggestions(self):
        rid, initial = self.native_case(names=('Ada',))
        self.assertEqual(self.call(f'/api/records/{rid}/bylines', {'version': 0, 'record_version': 1,
            'items': [{'raw_name': 'Human corrected name', 'status': 'pending'}], 'change_note': 'Synthetic human correction'}, method='PUT').status_code, 200)
        result = self.decision(rid, [initial['candidates'][0]['id']])
        self.assertEqual(result.status_code, 409)
        current = self.get(f'/api/records/{rid}/bylines')
        self.assertEqual(current['items'][0]['raw_name'], 'Human corrected name')
        self.assertEqual(self.call(f'/api/records/{rid}/bylines', {'version': current['version'], 'record_version': 1,
            'items': [], 'change_note': 'Synthetic deliberate removal'}, method='PUT').status_code, 200)
        self.queue_run(rid, 'after-removal')
        self.assertEqual(self.get(f'/api/records/{rid}/bylines')['items'], [])
        self.assertEqual(self.get('/api/people')['total'], 0)

    def test_concurrent_adoption_creates_only_one_person_and_one_work(self):
        from concurrent.futures import ThreadPoolExecutor
        rid, state = self.native_case(names=('Ada',))
        data = {'version':state['version'], 'byline_version':state['byline_version'], 'adopt':[state['candidates'][0]['id']]}
        clients = [byline_fixture.BylineTests.login(self, 'researcher') for unused in range(2)]
        def decide(client):
            return client.post(f'/api/records/{rid}/suggestions/decide',json=data,
                headers={'X-CSRF-Token':client.get('/api/session').json['csrf']}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(decide, clients))
        self.assertEqual(sorted(statuses), [200,409])
        self.assertEqual(self.get('/api/people')['total'], 1)
        rows = self.get(f'/api/records/{rid}/bylines')['items']
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.get('/api/people/'+rows[0]['target_id']+'/works')['total'], 1)

    def test_real_public_per_author_metadata_and_orcid_person_replay_remain_manual(self):
        import hashlib
        self.synthetic()
        fixture = Path(__file__).parent / 'fixtures' / 'author_suggestions'
        manifest = json.loads((fixture / 'manifest.json').read_text())
        for material in manifest['orcid']:
            self.assertEqual(hashlib.sha256((fixture/material['file']).read_bytes()).hexdigest(),material['sha256'])
        def fetch(url):
            if 'pub.orcid.org' in url:
                index = '01' if '0009-0000-8922-637X' in url else '02'
                oid = url.split('/')[-2]
                raw = (fixture/(index+'-'+oid+'-person.raw')).read_bytes()
            else:
                raw = (fixture/'crossref-doi-derived.json').read_bytes()
            return {'url':url,'content_type':'application/json','bytes':raw,'text':raw.decode()}
        self.fetcher = fetch
        archive_fixture.Provider.transform = lambda output,value:{'suggestions':value['author_facts']}
        institution_ids=[self.source(name) for name in ['Charles University','Institute of Sociology of the Czech Academy of Sciences, Prague, Czech Republic']]
        rid = self.record(authors='Alena Jechová; Martina Mysíková', doi='10.1080/1406099x.2026.2740283')
        state = self.queue_run(rid)
        self.assertEqual([c['value']['raw_name'] for c in state['candidates']],['Alena Jechová','Martina Mysíková'])
        self.assertEqual([c['value']['orcid'] for c in state['candidates']],['0009-0000-8922-637X','0000-0002-6340-4753'])
        self.assertTrue(all(c['value']['native']['authenticated-orcid'] is False for c in state['candidates']))
        self.assertEqual([c['value']['orcid_name'] for c in state['candidates']],['Alena Jechová','Martina Mysíková'])
        self.assertEqual(self.get('/api/people')['total'],0)
        self.assertEqual(self.get(f'/api/records/{rid}/bylines')['items'],[])
        self.assertEqual([c['operation']['article_units'][0]['institution_id'] for c in state['candidates']],institution_ids)
        self.assertEqual([c['operation']['employments'] for c in state['candidates']],[[],[]])
        self.assertEqual(json.loads((fixture/'01-0009-0000-8922-637X-works.raw').read_bytes())['group'],[])
        self.assertEqual(self.decision(rid,[c['id'] for c in state['candidates']],article_units=[c['id'] for c in state['candidates']]).status_code,200)
        self.assertEqual(self.get('/api/people')['total'],2)
        self.assertEqual([u['institution_id'] for u in self.get(f'/api/records/{rid}/affiliations')['items']],institution_ids)

    def test_real_author_unit_backup_rejects_rehashed_other_author_and_publisher_mapping(self):
        import hashlib
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        self.synthetic()
        fixture = Path(__file__).parent / 'fixtures' / 'author_suggestions'
        raw = (fixture / 'crossref-doi-derived.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), 'f9b17d55a6d9faf6dabc9a9c64db2d89d5c7ca75fa782b999f522bfe10ddba9b')
        original_raw = (fixture / '06-crossref-online.raw').read_bytes()
        self.assertEqual(hashlib.sha256(original_raw).hexdigest(), 'd0979af7849f0326d7b522fd16b83be9551448444a92e83d5ec18a273efd05a9')
        self.assertEqual(json.loads(raw)['message'], json.loads(original_raw)['message']['items'][0])
        def fetch(url):
            if 'pub.orcid.org' in url:
                oid = url.split('/')[-2]
                index = '01' if oid == '0009-0000-8922-637X' else '02'
                response = (fixture / (index + '-' + oid + '-person.raw')).read_bytes()
            else:
                response = raw
            return {'url': url, 'content_type': 'application/json', 'bytes': response, 'text': response.decode()}
        self.fetcher = fetch
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': value['author_facts']}
        names = ['Charles University', 'Institute of Sociology of the Czech Academy of Sciences, Prague, Czech Republic', 'Informa UK Limited']
        institutions = [self.source(name) for name in names]
        rid = self.record(authors='Alena Jechová; Martina Mysíková', doi='10.1080/1406099x.2026.2740283')
        state = self.queue_run(rid)
        candidate = state['candidates'][0]
        self.assertEqual(candidate['value']['raw_name'], 'Alena Jechová')
        self.assertEqual(candidate['value']['native']['affiliation'], [{'name': 'Charles University', 'place': ['Prague, Czech Republic']}])
        self.assertEqual(candidate['operation']['article_units'][0]['institution_id'], institutions[0])
        backup = self.call('/api/backup', user='admin')
        self.assertEqual(backup.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(backup.data)) as bundle:
            original = {name: bundle.read(name) for name in bundle.namelist()}
        backup.close()
        for index, institution in enumerate(institutions):
            with self.subTest(institution=names[index]):
                # Native author, Charles quote and valid institution versions stay intact.
                archive = self.rewrite_candidate_backup(original, candidate['id'],
                    lambda operation: operation['article_units'][0].update(institution_id=institution, institution_name=names[index]), 'unit-' + str(index))
                target = Path(self.temp.name) / ('unit-restored-' + str(index))
                if index:
                    with self.assertRaises(ValueError):
                        restore_backup(archive, target)
                else:
                    restore_backup(archive, target)
                    app = create_app(target, testing=True)
                    client = byline_fixture.BylineTests.login(self, 'researcher', app)
                    current = client.get(f'/api/records/{rid}/suggestions').json
                    response = client.post(f'/api/records/{rid}/suggestions/decide', json={
                        'version': current['version'], 'byline_version': current['byline_version'],
                        'adopt': [candidate['id']], 'article_units': [candidate['id']]},
                        headers={'X-CSRF-Token': client.get('/api/session').json['csrf']})
                    self.assertEqual(response.status_code, 200, response.json)
                    units = client.get(f'/api/records/{rid}/affiliations').json['items']
                    self.assertEqual([u['institution_id'] for u in units], [institutions[0]])

    def test_rehashed_employment_and_organization_signature_cannot_switch_institution(self):
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        self.synthetic()
        institution, other = self.source('Approved Institute'), self.source('Unrelated Institute')
        article = '<h1>Article</h1><script type="application/ld+json">' + json.dumps({
            '@type': 'Article', 'headline': 'Article', 'author': [
                {'@type': 'Person', 'name': 'Ada Example', 'url': 'https://profile.example/ada'},
                {'@type': 'Organization', 'name': 'Approved Institute'}]}) + '</script>'
        def fetch(url):
            text = '<h1>Ada Example</h1><p>Ada Example is Researcher at Approved Institute.</p>' if url.endswith('/ada') else article
            return {'url': url, 'content_type': 'text/html', 'bytes': text.encode(), 'text': text}
        self.fetcher = fetch
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': value['author_facts']}
        rid = self.record(authors='Ada Example; Approved Institute', url='https://article.example/roles')
        state = self.queue_run(rid)
        person, organization = state['candidates']
        self.assertEqual(person['operation']['employments'][0]['institution_id'], institution)
        self.assertEqual(organization['operation']['target_id'], institution)
        backup = self.call('/api/backup', user='admin')
        with zipfile.ZipFile(io.BytesIO(backup.data)) as bundle:
            original = {name: bundle.read(name) for name in bundle.namelist()}
        backup.close()
        cases = [
            ('correct', person['id'], lambda operation: None),
            ('wrong-employer', person['id'], lambda operation: operation['employments'][0].update(institution_id=other, institution_name='Unrelated Institute')),
            ('wrong-organization', organization['id'], lambda operation: operation.update(target_id=other)),
        ]
        for name, cid, mutation in cases:
            with self.subTest(case=name):
                archive = self.rewrite_candidate_backup(original, cid, mutation, name)
                target = Path(self.temp.name) / ('restored-' + name)
                if name != 'correct':
                    with self.assertRaises(ValueError):
                        restore_backup(archive, target)
                else:
                    restore_backup(archive, target)
                    client = byline_fixture.BylineTests.login(self, 'researcher', create_app(target, testing=True))
                    response = client.post(f'/api/records/{rid}/suggestions/decide', json={
                        'version': state['version'], 'byline_version': state['byline_version'],
                        'adopt': [person['id'], organization['id']], 'employments': [person['id']]},
                        headers={'X-CSRF-Token': client.get('/api/session').json['csrf']})
                    self.assertEqual(response.status_code, 200, response.json)
                    bylines = client.get(f'/api/records/{rid}/bylines').json['items']
                    self.assertEqual((bylines[1]['target_type'], bylines[1]['target_id']), ('institution', institution))
                    employments = client.get('/api/people/' + bylines[0]['target_id'] + '/employments').json['items']
                    self.assertEqual([(e['institution_id'], e['role']) for e in employments], [(institution, 'Researcher')])

    def test_original_institution_version_stays_readable_after_human_edit_and_blocks_adoption(self):
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        self.synthetic()
        institution = self.source('Original Institute')
        raw = json.dumps({'message': {'DOI': '10.5555/original-unit', 'author': [{
            'given': 'Ada', 'family': 'Example', 'ORCID': 'https://orcid.org/0000-0002-1825-0097',
            'affiliation': [{'name': 'Original Institute'}]}]}}).encode()
        self.fetcher = lambda url: {'url': url, 'content_type': 'application/json', 'bytes': raw, 'text': raw.decode()}
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': value['author_facts']}
        rid = self.record(authors='Ada Example', doi='10.5555/original-unit')
        state = self.queue_run(rid)
        cid = state['candidates'][0]['id']
        self.assertEqual(self.call('/api/sources/' + institution, {'version': 1, 'name': 'Human corrected institute'}, method='PUT').status_code, 200)
        current = self.get(f'/api/records/{rid}/suggestions')
        self.assertEqual(current['candidates'][0]['operation']['article_units'][0]['institution_name'], 'Original Institute')
        self.assertEqual(self.decision(rid, [cid], article_units=[cid]).status_code, 409)
        self.assertEqual(self.get(f'/api/records/{rid}/bylines')['items'], [])
        self.assertEqual(self.get('/api/people')['total'], 0)
        backup = self.call('/api/backup', user='admin')
        path = Path(self.temp.name) / 'edited-institution.zip'
        path.write_bytes(backup.data)
        backup.close()
        target = Path(self.temp.name) / 'edited-institution-restored'
        restore_backup(path, target)
        client = byline_fixture.BylineTests.login(self, 'researcher', create_app(target, testing=True))
        self.assertEqual(client.get(f'/api/records/{rid}/suggestions').json, current)
        self.assertEqual(client.get('/api/sources/' + institution).json['name'], 'Human corrected institute')

    def test_unknown_organization_signature_stays_unmatched_without_creating_person(self):
        self.synthetic()
        raw = json.dumps({'message': {'DOI':'10.5555/unknown-org','author':[{'name':'Undeclared Institute'}]}}).encode()
        self.fetcher=lambda url:{'url':url,'content_type':'application/json','bytes':raw,'text':raw.decode()}
        archive_fixture.Provider.transform=lambda output,value:{'suggestions':value['author_facts']}
        rid=self.record(authors='Undeclared Institute',doi='10.5555/unknown-org')
        state=self.queue_run(rid)
        self.assertEqual(state['candidates'][0]['status'],'unmatched')
        self.assertEqual(self.decision(rid,[state['candidates'][0]['id']]).status_code,409)
        self.assertEqual(self.get('/api/people')['total'],0)

    def test_unrelated_person_revision_does_not_recommend_or_charge_rejected_input_again(self):
        pid=self.person('Ada Example')
        rid,state=self.native_case(names=('Ada',))
        cid=state['candidates'][0]['id']
        self.assertEqual(self.decision(rid,[],reject=[cid]).status_code,200)
        before=self.get('/api/admin/ai','admin')['charged_units']
        self.assertEqual(self.call('/api/people/'+pid,{'version':1,'biography':'Human independent biography','change_note':'Synthetic unrelated edit'},method='PUT').status_code,200)
        repeated=self.queue_run(rid,'after-catalogue-edit')
        self.assertEqual([c['status'] for c in repeated['candidates']],['rejected'])
        self.assertEqual(self.get('/api/admin/ai','admin')['charged_units'],before)

    def test_bounded_author_slice_reports_unprocessed_authors_instead_of_whole_article_done(self):
        self.synthetic()
        raw=json.dumps({'message':{'DOI':'10.5555/large','author':[{'given':'Author'+str(i),'family':'Example','ORCID':'https://orcid.org/0000-0002-1825-0097'} for i in range(101)]}}).encode()
        self.fetcher=lambda url:{'url':url,'content_type':'application/json','bytes':raw,'text':raw.decode()}
        archive_fixture.Provider.transform=lambda output,value:{'suggestions':value['author_facts']}
        rid=self.record(authors='101 synthetic authors',doi='10.5555/large')
        state=self.queue_run(rid)
        self.assertEqual(state['coverage']['authors'],101)
        self.assertEqual(state['coverage']['supported'],100)
        self.assertEqual(state['coverage']['remaining'],1)

    def test_negative_profile_sentence_does_not_offer_employment(self):
        self.source('Example Institute')
        self.synthetic()
        article='<h1>Article</h1><script type="application/ld+json">'+json.dumps({'@type':'Article','headline':'Article','author':{'@type':'Person','name':'Ada Example','url':'https://profile.example/ada'}})+'</script>'
        def fetch(url):
            html='<h1>Ada Example</h1><p>It is false that Ada Example is Researcher at Example Institute.</p>' if url.endswith('/ada') else article
            return {'url':url,'content_type':'text/html','bytes':html.encode(),'text':html}
        self.fetcher=fetch
        archive_fixture.Provider.transform=lambda output,value:{'suggestions':value['author_facts']}
        rid=self.record(authors='Ada Example',url='https://article.example/negative-role')
        state=self.queue_run(rid)
        self.assertEqual(state['candidates'][0]['operation']['employments'],[])

    def test_failed_profile_requests_still_consume_the_six_request_acquisition_bound(self):
        self.synthetic()
        article='<h1>Article</h1><script type="application/ld+json">'+json.dumps({'@type':'Article','headline':'Article','author':[{'@type':'Person','name':'Author '+str(i),'url':'https://profile.example/'+str(i)} for i in range(10)]})+'</script>'
        requests=[]
        def fetch(url):
            requests.append(url)
            if 'profile.example' in url:
                raise ValueError('Synthetic public profile unavailable')
            return {'url':url,'content_type':'text/html','bytes':article.encode(),'text':article}
        self.fetcher=fetch
        archive_fixture.Provider.transform=lambda output,value:{'suggestions':value['author_facts']}
        rid=self.record(authors='Ten synthetic authors',url='https://article.example/bounded-failures')
        state=self.queue_run(rid)
        self.assertLessEqual(len(requests),6)
        self.assertEqual(state['coverage']['remaining'],10)

    def test_explicit_next_batch_prioritizes_remaining_profiles_and_reports_combined_coverage(self):
        self.synthetic()
        authors=[{'@type':'Person','name':'Author '+str(i),'url':'https://profile.example/'+str(i)} for i in range(8)]
        article='<h1>Article</h1><script type="application/ld+json">'+json.dumps({'@type':'Article','headline':'Article','author':authors})+'</script>'
        def fetch(url):
            html='<h1>Author '+url.rsplit('/',1)[1]+'</h1>' if 'profile.example' in url else article
            return {'url':url,'content_type':'text/html','bytes':html.encode(),'text':html}
        self.fetcher=fetch
        archive_fixture.Provider.transform=lambda output,value:{'suggestions':value['author_facts']}
        rid=self.record(authors='Eight synthetic authors',url='https://article.example/continue')
        first=self.queue_run(rid)
        self.assertEqual(first['coverage']['supported'],5)
        self.assertEqual(first['coverage']['remaining'],3)
        second=self.queue_run(rid,'next-explicit-batch')
        self.assertEqual(second['coverage']['supported'],8)
        self.assertEqual(second['coverage']['remaining'],0)
        self.assertEqual(self.get('/api/people')['total'],0)

    def test_batch_records_filter_lists_only_readable_external_records_with_a_public_entry(self):
        eligible=self.record(title='SYNTHETIC64 eligibility DOI',doi='10.5555/eligible')
        self.record(title='SYNTHETIC64 eligibility no entry')
        self.call('/api/records',{'kind':'research_note','title':'SYNTHETIC64 eligibility internal','doi':'10.5555/internal'})
        rows=self.get('/api/records?author_suggestions=1&q=SYNTHETIC64%20eligibility')
        self.assertEqual([r['id'] for r in rows['items']],[eligible])
        self.assertEqual(rows['total'],1)

    def test_existing_pending_bylines_can_be_adopted_together_without_mutating_the_conflict_baseline(self):
        self.synthetic()
        raw=json.dumps({'message':{'DOI':'10.5555/pending','author':[
            {'given':'Ada','family':'Example','ORCID':'https://orcid.org/0000-0002-1825-0097'},
            {'given':'Bob','family':'Example','ORCID':'https://orcid.org/0000-0001-5109-3700'}]}}).encode()
        self.fetcher=lambda url:{'url':url,'content_type':'application/json','bytes':raw,'text':raw.decode()}
        archive_fixture.Provider.transform=lambda output,value:{'suggestions':value['author_facts']}
        rid=self.record(authors='Ada Example; Bob Example',doi='10.5555/pending')
        saved=self.call(f'/api/records/{rid}/bylines',{'version':0,'record_version':1,'change_note':'Synthetic existing intake bylines',
            'items':[{'raw_name':'Ada Example','status':'pending'},{'raw_name':'Bob Example','status':'pending'}]},method='PUT')
        self.assertEqual(saved.status_code,200)
        state=self.queue_run(rid)
        result=self.decision(rid,[c['id'] for c in state['candidates']])
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual([b['status'] for b in self.get(f'/api/records/{rid}/bylines')['items']],['confirmed','confirmed'])

    def crossref(self, name='Private Alias', doi='10.5555/identity'):
        return json.dumps({'message': {'title': ['Public article'], 'DOI': doi,
            'author': [{'given': name, 'family': '', 'ORCID': 'https://orcid.org/0000-0002-1825-0097'}]}})

    def test_orcid_recall_does_not_reuse_invisible_origin_after_record_merge(self):
        pid = self.person('A different public name')
        preview = self.preview(self.crossref(), 'doi:10.5555/identity', content_type='application/json').json
        private = self.call('/api/records', {'kind': 'report', **preview['fields'], 'visibility': 'restricted',
            'intake_token': preview['token'], 'intake_bylines': [{'raw_name': 'Private Alias', 'status': 'confirmed',
                'target_type': 'person', 'target_id': pid, 'evidence': 'Synthetic private identity evidence'}]}).json['id']
        current_preview = self.preview(self.crossref(doi='10.5555/current'), 'doi:10.5555/current', content_type='application/json').json
        shared = self.call('/api/records', {'kind': 'report', **current_preview['fields'], 'visibility': 'restricted',
            'intake_token': current_preview['token']}).json['id']
        self.merge('record', shared, private)
        current = self.get('/api/records/' + shared)
        changed = self.call('/api/records/' + shared, {'version': current['version'], 'visibility': 'shared'}, method='PUT')
        self.assertEqual(changed.status_code, 200, changed.json)
        self.assertEqual(self.clients['colleague'].get('/api/records/' + private).status_code, 200)
        # The public merged record is readable, but its transferred original byline is not.
        self.assertTrue(all(b['status'] == 'pending' for b in self.clients['colleague'].get(f'/api/records/{shared}/bylines').json['items']))
        response = self.preview(self.crossref(doi='10.5555/second'), 'doi:10.5555/second', content_type='application/json')
        self.assertEqual(response.status_code, 200, response.json)
        # Query as the restricted colleague, not the original owner's preview above.
        from unittest.mock import patch
        from tests.test_assisted_intake import PublicSocket
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 80))]), \
             patch('socket.create_connection', side_effect=lambda *a, **k: PublicSocket(self.crossref(doi='10.5555/third').encode(), 'application/json')), \
             patch('ssl.SSLContext.wrap_socket', side_effect=lambda sock, **kwargs: sock):
            public = self.call('/api/intake/preview', {'input': 'doi:10.5555/third'}, user='colleague')
        self.assertEqual(public.status_code, 200, public.json)
        self.assertEqual(public.json['candidates']['authors'][0]['items'], [])

    def test_pending_candidate_can_resume_after_record_revision_without_losing_history(self):
        rid, state = self.native_case(names=('Ada',), suffix='resume')
        old = state['candidates'][0]['id']
        self.assertEqual(self.call('/api/records/' + rid, {'version': state['version'],
            'title': 'Human corrected title'}, method='PUT').status_code, 200)
        self.assertEqual(self.decision(rid, [old]).status_code, 409)
        again = self.queue_run(rid, 'resume-new-baseline')
        fresh = [c for c in again['candidates'] if not c['stale'] and c['status'] == 'pending']
        self.assertEqual(len(fresh), 1, again)
        self.assertNotEqual(fresh[0]['id'], old)
        self.assertEqual(self.decision(rid, [fresh[0]['id']]).status_code, 200)
        self.assertEqual(self.get('/api/records/' + rid)['title'], 'Human corrected title')
        self.assertIn(old, [c['id'] for c in self.get('/api/records/' + rid + '/suggestions')['candidates']])

    def test_confirmed_orcid_recalls_variant_then_removed_origin_invalidates_pending_link(self):
        rid, state = self.native_case(names=('Ada',), suffix='identity-origin')
        self.assertEqual(self.decision(rid, [state['candidates'][0]['id']]).status_code, 200)
        pid = self.get('/api/records/' + rid + '/bylines')['items'][0]['target_id']
        raw = json.dumps({'message': {'DOI': '10.5555/variant',
            'author': [{'given': 'A.', 'family': 'Example', 'ORCID': 'https://orcid.org/0000-0002-1825-0097'}]}}).encode()
        self.fetcher = lambda url: {'url': url, 'content_type': 'application/json', 'bytes': raw, 'text': raw.decode()}
        second = self.record(authors='A. Example', doi='10.5555/variant')
        pending = self.queue_run(second, 'variant')
        candidate = pending['candidates'][0]
        self.assertEqual(candidate['operation']['action'], 'link_existing')
        self.assertEqual(candidate['operation']['target_id'], pid)
        self.assertEqual(self.get('/api/records/' + second + '/bylines')['items'], [])
        origin = self.get('/api/records/' + rid + '/bylines')
        self.assertEqual(self.call('/api/records/' + rid + '/bylines', {
            'version': origin['version'], 'record_version': self.get('/api/records/' + rid)['version'],
            'items': [], 'change_note': 'Human removal of old identity evidence'}, method='PUT').status_code, 200)
        self.assertEqual(self.decision(second, [candidate['id']]).status_code, 409)
        again = self.queue_run(second, 'variant-origin-removed')
        self.assertTrue(any(c['operation']['action'] == 'create_person' and not c['stale'] for c in again['candidates']))

    def variant_work(self, suffix):
        raw = json.dumps({'message': {'DOI': '10.5555/' + suffix,
            'author': [{'given': 'A.', 'family': 'Example', 'ORCID': 'https://orcid.org/0000-0002-1825-0097'}]}}).encode()
        self.fetcher = lambda url: {'url': url, 'content_type': 'application/json', 'bytes': raw, 'text': raw.decode()}
        return self.record(authors='A. Example', doi='10.5555/' + suffix)

    def test_adopted_identifier_recall_stays_manual_and_survives_portable_restore(self):
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        rid, state = self.native_case(names=('Ada',), suffix='recall-original')
        self.assertEqual(self.decision(rid, [state['candidates'][0]['id']]).status_code, 200)
        pid = self.get('/api/records/' + rid + '/bylines')['items'][0]['target_id']
        second = self.variant_work('recall-next')
        candidate = self.queue_run(second, 'recall-next')['candidates'][0]
        self.assertEqual(candidate['operation']['target_id'], pid)
        self.assertEqual(self.decision(second, [candidate['id']]).status_code, 200)
        self.assertEqual(self.get('/api/people')['total'], 1)
        self.assertEqual(self.get('/api/people/' + pid + '/works')['total'], 2)
        backup = self.call('/api/backup', user='admin')
        saved, target = Path(self.temp.name) / 'recall.zip', Path(self.temp.name) / 'recall-restored'
        saved.write_bytes(backup.data); backup.close()
        restore_backup(saved, target)
        client = byline_fixture.BylineTests.login(self, 'researcher', create_app(target, testing=True))
        self.assertEqual(client.get('/api/people/' + pid + '/works').json['total'], 2)

    def test_pending_and_rejected_identifiers_do_not_recall_an_existing_person(self):
        rid, state = self.native_case(names=('Ada',), suffix='not-confirmed')
        second = self.variant_work('not-confirmed-next')
        self.assertEqual(self.queue_run(second, 'pending-only')['candidates'][0]['operation']['action'], 'create_person')
        self.assertEqual(self.decision(rid, [], reject=[state['candidates'][0]['id']]).status_code, 200)
        self.assertTrue(all(c['operation']['action'] == 'create_person' for c in self.queue_run(second, 'rejected-only')['candidates']))

    def test_human_corrected_or_private_adoption_cannot_recall_for_colleague(self):
        rid, state = self.native_case(names=('Ada',), suffix='private-origin')
        self.assertEqual(self.decision(rid, [state['candidates'][0]['id']]).status_code, 200)
        self.assertEqual(self.call('/api/records/' + rid, {'version': 1, 'visibility': 'restricted'}, method='PUT').status_code, 200)
        second = self.variant_work('public-next')
        queued = self.call('/api/archive-jobs', {'record_ids': [second], 'request_id': 'private-origin'}, user='colleague')
        self.assertEqual(queued.status_code, 201)
        self.call('/api/admin/archive-jobs/run', user='admin')
        state = self.get('/api/records/' + second + '/suggestions', 'colleague')
        self.assertEqual(state['candidates'][0]['operation']['action'], 'create_person')
        original = self.get('/api/records/' + rid + '/bylines')
        rows = original['items']; rows[0]['evidence'] = 'Human corrected identity basis'
        self.assertEqual(self.call('/api/records/' + rid + '/bylines', {'version': original['version'],
            'record_version': 2, 'items': rows, 'change_note': 'Human corrected evidence'}, method='PUT').status_code, 200)
        self.assertTrue(any(c['operation']['action'] != 'link_existing' for c in self.queue_run(second, 'human-corrected')['candidates']))

    def test_legacy_candidate_fingerprints_restore_reject_history_and_resume(self):
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        rid, state = self.native_case(suffix='legacy-candidates')
        ada, bob = state['candidates']
        self.assertEqual(self.decision(rid, [], reject=[bob['id']]).status_code, 200)
        backup = self.call('/api/backup', user='admin')
        with zipfile.ZipFile(io.BytesIO(backup.data)) as bundle:
            files = {n: bundle.read(n) for n in bundle.namelist()}
        backup.close()
        for index, candidate in enumerate((ada, bob)):
            saved = self.rewrite_candidate_backup(files, candidate['id'], lambda patch: None, 'legacy-signature-' + str(index))
            with zipfile.ZipFile(saved) as bundle:
                files = {n: bundle.read(n) for n in bundle.namelist()}
        target = Path(self.temp.name) / 'legacy-candidate-restored'
        restore_backup(saved, target)
        self.app = create_app(target, testing=True)
        self.clients = {u: byline_fixture.BylineTests.login(self, u, self.app) for u in ('researcher', 'colleague', 'admin')}
        self.assertEqual(self.call('/api/records/' + rid, {'version': 1, 'title': 'Restored human revision'}, method='PUT').status_code, 200)
        state = self.queue_run(rid, 'after-legacy-restore')
        fresh = [c for c in state['candidates'] if not c['stale'] and c['status'] == 'pending']
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fresh[0]['operation']['name'], 'Ada Example')
        self.assertEqual(self.decision(rid, [fresh[0]['id']]).status_code, 200)
        self.assertTrue(any(c['id'] == bob['id'] and c['status'] == 'rejected' for c in state['candidates']))

    def test_recalled_identifiers_follow_merge_split_without_automatic_confirmation(self):
        from tests.test_person_identity import PersonIdentityTests as Identity
        rid, state = self.native_case(names=('Ada',), suffix='merge-recall')
        self.assertEqual(self.decision(rid, [state['candidates'][0]['id']]).status_code, 200)
        original = self.get('/api/records/' + rid + '/bylines')['items'][0]['target_id']
        keep = self.person('Different public name')
        preview = Identity.compare(self, keep, original)
        merged = self.call('/api/people/merge', Identity.intent(self, preview))
        self.assertEqual(merged.status_code, 200, merged.json)
        second = self.variant_work('after-person-merge')
        state = self.queue_run(second, 'after-person-merge')
        self.assertEqual(state['candidates'][0]['operation']['target_id'], keep)
        split = self.call('/api/people/identity-events/' + merged.json['event_id'] + '/split-preview')
        self.assertEqual(split.status_code, 200)
        response = self.call('/api/people/split', {'preview_id': split.json['preview_id'],
            'idempotency_key': 'recall-split', 'confirmed': True, 'evidence': 'Synthetic split back to original'})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.decision(second, [state['candidates'][0]['id']]).status_code, 409)
        state = self.queue_run(second, 'after-person-split')
        fresh = [c for c in state['candidates'] if c['operation'].get('target_id') == original]
        self.assertTrue(fresh, state)

    def test_conflicting_confirmed_identifiers_remain_unmatched(self):
        rid, first = self.native_case(names=('Ada',), suffix='conflict-one')
        second = self.variant_work('conflict-two')
        pending = self.queue_run(second, 'conflict-two')
        self.assertEqual(self.decision(rid, [first['candidates'][0]['id']]).status_code, 200)
        self.assertEqual(self.decision(second, [pending['candidates'][0]['id']]).status_code, 200)
        third = self.variant_work('conflict-three')
        state = self.queue_run(third, 'conflict-three')
        candidate = state['candidates'][0]
        self.assertEqual(candidate['operation']['action'], 'unmatched')
        self.assertEqual(len([m for m in candidate['operation']['matches'] if m['basis'].startswith('ORCID')]), 2)
        self.assertEqual(self.decision(third, [candidate['id']]).status_code, 409)

    def test_adopted_orcid_does_not_escape_private_origin_after_record_merge(self):
        rid, state = self.native_case(names=('Ada',), suffix='private-merged')
        self.assertEqual(self.decision(rid, [state['candidates'][0]['id']]).status_code, 200)
        self.assertEqual(self.call('/api/records/' + rid, {'version': 1, 'visibility': 'restricted'}, method='PUT').status_code, 200)
        shared = self.record(title='Shared target', doi='10.5555/merged-target', visibility='restricted')
        self.merge('record', shared, rid)
        record = self.get('/api/records/' + shared)
        self.assertEqual(self.call('/api/records/' + shared, {'version': record['version'], 'visibility': 'shared'}, method='PUT').status_code, 200)
        second = self.variant_work('private-merged-next')
        self.assertEqual(self.call('/api/archive-jobs', {'record_ids': [second],
            'request_id': 'hidden-original'}, user='colleague').status_code, 201)
        self.call('/api/admin/archive-jobs/run', user='admin')
        state = self.get('/api/records/' + second + '/suggestions', 'colleague')
        self.assertEqual(state['candidates'][0]['operation']['action'], 'create_person')
        self.assertEqual(state['candidates'][0]['operation'].get('matches', []), [])

    def test_unknown_author_cost_keeps_attempt_and_blocks_retry_after_restore(self):
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        self.synthetic()
        archive_fixture.Provider.usage = False
        archive_fixture.Provider.transform = lambda output, value: {'suggestions': value['author_facts']}
        raw = json.dumps({'message': {'DOI': '10.5555/unknown-author',
            'author': [{'given': 'Ada', 'family': 'Example', 'ORCID': 'https://orcid.org/0000-0002-1825-0097'}]}}).encode()
        self.fetcher = lambda url: {'url': url, 'content_type': 'application/json', 'bytes': raw, 'text': raw.decode()}
        rid = self.record(authors='Ada Example', doi='10.5555/unknown-author')
        state = self.queue_run(rid, 'unknown-author')
        self.assertEqual(state['jobs'][0]['status'], 'paused')
        jid = state['jobs'][0]['id']
        costs = self.get('/api/admin/ai', 'admin')
        held = costs['held_units']
        self.assertGreater(held, 0)
        event = json.loads(state['events'][-1]['details_json'])
        self.assertEqual(event['ai']['attempt_id'], costs['attempts'][0]['id'])
        self.assertEqual(self.call('/api/admin/archive-jobs/' + jid + '/retry',
            {'basis': 'Synthetic billing investigation'}, user='admin').status_code, 409)
        backup = self.call('/api/backup', user='admin')
        saved, target = Path(self.temp.name) / 'unknown-author.zip', Path(self.temp.name) / 'unknown-author-restored'
        saved.write_bytes(backup.data); backup.close(); restore_backup(saved, target)
        client = byline_fixture.BylineTests.login(self, 'admin', create_app(target, testing=True))
        self.assertEqual(client.get('/api/admin/ai').json['held_units'], held)
        csrf = client.get('/api/session').json['csrf']
        response = client.post('/api/admin/archive-jobs/' + jid + '/retry',
            json={'basis': 'Synthetic billing investigation'}, headers={'X-CSRF-Token': csrf})
        self.assertEqual(response.status_code, 409)
