"""Synthetic official layouts through HTTP, durable worker and recovery boundaries."""
import json
import unittest
from unittest.mock import patch, MagicMock

from tests import test_assisted_intake as base

CJIR = 'https://cjir.iir.cz/index.php/cjir'
INTERSECTIONS = 'https://intersections.tk.hu/index.php/intersections'


def feed(root, dates=('Thu, 22 Oct 2026 00:00:00 +0000',)):
    return '<rss><channel>' + ''.join(
        f'<item><title>Synthetic work {index}</title><link>{root}/article/view/{index}</link>'
        f'<guid>{index}</guid><pubDate>{stamp}</pubDate><description>Listing excerpt only.</description></item>'
        for index, stamp in enumerate(dates, 1)) + '</channel></rss>'


OJS = '''<html><head><meta name="citation_title" content="Synthetic education study">
<meta name="citation_author" content="Ada Example"><meta name="citation_author" content="Bea Example">
<meta name="citation_doi" content="10.1234/synthetic.1"><meta name="citation_date" content="2025">
<meta name="DC.Date.issued" content="2026-08-26"><meta name="DC.Date.created" content="2026-08-26">
<meta name="DC.Date.modified" content="2026-09-22"><meta name="citation_journal_title" content="Synthetic Journal">
<meta name="citation_pdf_url" content="{root}/article/download/1/2"></head><body>
<section class="item authors"><ul class="authors"><li><span class="name">Ada Example</span>
<span class="affiliation">Synthetic University</span><span class="orcid"><a href="https://orcid.org/0000-0002-4878-9755">ORCID</a></span></li>
<li><span class="name">Bea Example</span><span class="orcid"><a href="https://orcid.org/0000-0002-5779-752X">ORCID</a></span></li></ul></section>
<section class="item abstract"><h2>Abstract</h2><p>Original abstract about education policy.</p></section></body></html>'''

GSSC_LIST = '''<html><article class="single-article"><div class="info-wrap"><div class="meta"><span class="date">Oct 21, 2026</span></div>
<a class="title" href="https://www.gssc.lt/en/publication/synthetic-study/">Synthetic policy study</a><div class="text"><p>Listing introduction.</p></div>
<div class="authors"><span class="author">Ada Example</span></div></div></article></html>'''
GSSC_PAGE = '''<main class="single-publication"><section><div class="meta"><span class="date">Oct 21, 2026</span></div><h1>Synthetic policy study</h1>
<div class="authors"><div class="author"><a class="title" href="https://www.gssc.lt/en/autoriai/ada-example/">Ada Example</a></div></div>
<div class="excerpt"><span>Summary</span><div class="text">Separate introductory summary.</div></div></section>
<section class="content-block"><div class="text excerpt"><h2>Evidence</h2><p>Actual synthetic policy body.</p><p>Second body paragraph.</p></div></section>
<section><div class="authors"><a class="title" href="https://www.gssc.lt/en/autoriai/ada-example/">Ada Example</a><p>Unrelated author biography and navigation.</p></div></section></main>'''


class SourceAdapterTests(unittest.TestCase):
    def setUp(self):
        base.AssistedIntakeTests.setUp(self)
        clock = patch('platform_app.store.now', return_value='2026-11-03T12:00:00+00:00')
        clock.start()
        self.addCleanup(clock.stop)
        record_clock = patch('platform_app.record_revisions.now', return_value='2026-11-03T12:00:00+00:00')
        record_clock.start()
        self.addCleanup(record_clock.stop)
    call = base.AssistedIntakeTests.call

    def test_upstream_return_to_observed_body_uses_a_without_erasing_a_or_b(self):
        from platform_app.automatic_processing import run_pending
        root = 'https://www.gssc.lt/en/'
        sid = self.source(root, 'institution')
        path = '/api/sources/' + sid + '/ingestion'
        self.assertEqual(self.call(path, {'enabled': True}, user='admin', method='PUT').status_code, 200)
        observations = []
        for n, body in enumerate([GSSC_PAGE, GSSC_PAGE.replace('Actual synthetic policy body.', 'INTERMEDIATE B policy body.'), GSSC_PAGE]):
            if n:
                self.assertEqual(self.call(path + '/run', {}, user='admin').status_code, 200)
            self.worker(root, xml=GSSC_LIST, page=body, stamp=f'2026-11-{3+n*8:02}T12:00:00+00:00')
            run_pending(self.app.config['DATA_DIR'], limit=0)
            rid = self.clients['researcher'].get('/api/records').json['items'][0]['id']
            detail = self.clients['researcher'].get('/api/records/' + rid).json
            observations.append(detail)
        self.assertEqual(observations[2]['fulltext']['original']['text'], 'Evidence\n\nActual synthetic policy body.\n\nSecond body paragraph.')
        snapshots = observations[2]['automatic_acquisition']['snapshots']
        self.assertEqual(len(snapshots), 2)
        self.assertIn('INTERMEDIATE B policy body.', snapshots[1]['page_text'])
        self.assertEqual(observations[2]['fulltext']['original']['snapshot_id'], snapshots[0]['id'])
        classifications = [item for item in observations[2]['automatic_tasks'] if item['task'] == 'classification' and not item['stale']]
        self.assertEqual(len(classifications), 1)
        self.assertEqual(classifications[0]['input']['body'], 'Evidence\n\nActual synthetic policy body.\n\nSecond body paragraph.')
        self.assertEqual(self.clients['researcher'].get('/api/records?q=INTERMEDIATE%20B').json['total'], 0)

    def test_returned_body_reuses_translation_human_edit_and_retains_unknown_charge(self):
        from pathlib import Path
        from tests.test_fulltext import FulltextTests
        from platform_app.maintenance import create_backup, restore_backup
        from platform_app.web import create_app
        root = 'https://www.gssc.lt/en/'
        sid = self.source(root, 'institution')
        path = '/api/sources/' + sid + '/ingestion'
        self.call(path, {'enabled': True}, user='admin', method='PUT')
        self.call('/api/admin/ai/config', {'cap': '1', 'currency': 'USD'}, user='admin')
        a = GSSC_PAGE.replace('<h2>Evidence</h2>', '')
        jobs = []
        for n, body in enumerate([a, a.replace('Actual synthetic policy body.', 'INTERMEDIATE B policy body.'), a]):
            if n:
                self.call(path + '/run', {}, user='admin')
            self.worker(root, xml=GSSC_LIST, page=body, stamp=f'2026-11-{3+n*8:02}T12:00:00+00:00')
            rid = self.clients['researcher'].get('/api/records').json['items'][0]['id']
            response = self.call('/api/records/' + rid + '/fulltext')
            self.assertEqual(response.status_code, 200 if n == 2 else 201, response.json)
            jobs.append(response.json['id'])
            if n < 2:
                with FulltextTests.provider(self, unknown=n == 1) as provider:
                    FulltextTests.worker(self, stamp='2090-10-31T23:59:00+00:00')
                    self.assertEqual(provider.sent.call_count, 1 if n == 1 else 2)
            if n == 0:
                self.assertEqual(self.call('/api/fulltext/' + jobs[0] + '/edit', {'paragraph': 0, 'revision': 0, 'text': '人工保留的 A 校订。'}).status_code, 200)
        self.assertEqual(jobs[2], jobs[0])
        before = self.clients['admin'].get('/api/admin/ai').json['attempts']
        unknown = next(item for item in before if item['status'] == 'unknown')
        self.assertGreater(unknown['reserved_units'], 0)
        restored = restore_backup(create_backup(self.app.config['DATA_DIR']), Path(self.temp.name) / 'reverted-translation-restored')
        with FulltextTests.provider(self) as provider:
            FulltextTests.worker(self, stamp='2090-11-01T00:01:00+00:00', data_dir=restored)
            self.assertEqual(provider.sent.call_count, 0)
        client = create_app(restored, testing=True, embedded_worker=False).test_client()
        csrf = client.get('/api/session').json['csrf']
        client.post('/api/login', json={'username': 'researcher', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf})
        detail = client.get('/api/records/' + rid).json
        versions = {v['id']: v for v in detail['fulltext']['versions']}
        self.assertFalse(versions[jobs[0]]['stale'])
        self.assertTrue(versions[jobs[1]]['stale'])
        self.assertEqual(versions[jobs[0]]['segments'][0]['reading_text'], '人工保留的 A 校订。')
        self.assertEqual(self.clients['admin'].get('/api/admin/ai').json['attempts'], before)

    def source(self, root=CJIR, kind='journal'):
        response = self.call('/api/sources', dict(name='Synthetic official source ' + root, kind=kind, website=root))
        self.assertEqual(response.status_code, 201, response.json)
        return response.json['id']

    def worker(self, root, xml=None, page=None, stamp='2026-11-03T12:00:00+00:00'):
        from platform_app.ingestion import run_pending
        requests = []
        class Socket(base.PublicSocket):
            def sendall(sock, data):
                path = data.split(b' ')[1].decode()
                requests.append(path)
                listing = 'WebFeedGatewayPlugin' in path or path == '/en/publications/'
                body = (xml if xml is not None else feed(root)) if listing else (page or OJS.format(root=root))
                sock.body = base.PublicSocket(body.encode(), 'application/xml' if listing and '<rss>' in body else 'text/html').body
        with patch('socket.getaddrinfo', return_value=[(2,1,6,'',('93.184.216.34',443))]), \
             patch('socket.create_connection', side_effect=lambda *a, **k: Socket(b'')), \
             patch('ssl.SSLContext.wrap_socket', side_effect=lambda sock, **k: sock), \
             patch('platform_app.store.now', return_value=stamp):
            result = run_pending(self.app.config['DATA_DIR'], limit=5)
        return result, requests

    def test_ojs_persists_real_abstract_dates_and_pdf_link_without_claiming_fulltext_and_queues_once(self):
        sid = self.source()
        path = '/api/sources/' + sid + '/ingestion'
        enabled = self.call(path, {'enabled': True}, user='admin', method='PUT')
        self.assertEqual(enabled.status_code, 200, enabled.json)
        cjir_page = OJS.format(root=CJIR).replace('<section class="item abstract">', '<div class="article-details-main"><section>').replace('policy.</p></section>', 'policy.</p></section></div>')
        result, requests = self.worker(CJIR, page=cjir_page)
        self.assertEqual(result['saved'], 1)
        self.assertFalse(any('/download/' in path for path in requests))
        rid = self.clients['researcher'].get('/api/records').json['items'][0]['id']
        detail = self.clients['researcher'].get('/api/records/' + rid).json
        self.assertEqual(detail['title'], 'Synthetic education study')
        self.assertEqual(detail['authors'], 'Ada Example; Bea Example')
        self.assertEqual(detail['abstract'], 'Original abstract about education policy.')
        self.assertEqual(detail['published_on'], '2025')
        self.assertEqual(detail['serial_id'], sid)
        self.assertIsNone(detail['source_id'])
        snap = detail['automatic_acquisition']['snapshots'][0]
        self.assertFalse(snap['work_body_available'])
        self.assertEqual(snap['metadata']['raw']['meta']['dc.date.issued'], ['2026-08-26'])
        self.assertEqual(snap['pdf_links'], [CJIR + '/article/download/1/2'])
        jobs = self.clients['admin'].get('/api/records/' + rid + '/suggestions').json['jobs']
        self.assertEqual(jobs, [])
        from platform_app.maintenance_agent import run_pending as maintain_pending
        maintain_pending(self.app.config['DATA_DIR'], limit=0)
        automatic = [job for job in self.clients['admin'].get('/api/maintenance/jobs').json['items'] if job['target_id'] == rid]
        self.assertEqual(len(automatic), 1)
        self.assertEqual(automatic[0]['status'], 'queued')
        self.call(path + '/run', {}, user='admin')
        self.worker(CJIR, page=cjir_page)
        jobs2 = self.clients['admin'].get('/api/records/' + rid + '/suggestions').json['jobs']
        self.assertEqual([j['id'] for j in jobs2], [j['id'] for j in jobs])
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'], 1)
        # Queued Chinese inputs use the actual article abstract, and must
        # restore against that same evidence rather than the RSS excerpt.
        from pathlib import Path
        from platform_app.automatic_processing import run_pending
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY':''}):
            run_pending(self.app.config['DATA_DIR'], limit=10)
        backup = Path(self.temp.name) / 'ojs-chinese.zip'
        with self.call('/api/backup', user='admin') as response:
            backup.write_bytes(response.data)
        restored = restore_backup(backup, Path(self.temp.name) / 'ojs-restored')
        client = create_app(restored,testing=True).test_client()
        csrf = client.get('/api/session').json['csrf']
        client.post('/api/login',json=dict(username='researcher',password='LocalDemo2026!'),headers={'X-CSRF-Token':csrf})
        self.assertEqual(len(client.get('/api/records/'+rid).json['automatic_tasks']),2)

    def test_non_monotonic_feed_scans_past_old_items_and_explicit_backfill_keeps_original_dates(self):
        sid = self.source(INTERSECTIONS)
        path = '/api/sources/' + sid + '/ingestion'
        self.call(path, {'enabled': True}, user='admin', method='PUT')
        old = feed(INTERSECTIONS, ('Wed, 26 Aug 2026 00:00:00 +0000',))
        result, requests = self.worker(INTERSECTIONS, xml=old)
        self.assertEqual(result['saved'], 0)
        self.assertEqual(len(requests), 1)
        config = self.clients['admin'].get(path).json
        self.assertEqual(config['coverage']['counts']['outside_window'], 1)
        self.assertIn('零条', config['coverage']['zero_interpretation'])
        self.call(path, {'enabled': True, 'backfill_days': 365}, user='admin', method='PUT')
        self.call(path + '/run', {}, user='admin')
        self.assertEqual(self.worker(INTERSECTIONS, xml=old)[0]['saved'], 1)
        item = self.clients['researcher'].get('/api/records').json['items'][0]
        self.assertEqual(item['published_on'], '2025')
        detail = self.clients['researcher'].get('/api/records/' + item['id']).json
        self.assertEqual(detail['discovery_evidence'][0]['raw']['pubDate'], 'Wed, 26 Aug 2026 00:00:00 +0000')
        self.assertTrue(detail['created_at'].startswith('2026-11-03'))
        # An old item between recent items must not terminate the feed scan.
        other = self.source(CJIR)
        self.call('/api/sources/' + other + '/ingestion', {'enabled': True}, user='admin', method='PUT')
        mixed = feed(CJIR, ('Thu, 22 Oct 2026 00:00:00 +0000', 'Fri, 24 Jul 2026 00:00:00 +0000', 'Fri, 30 Oct 2026 00:00:00 +0000'))
        result, requests = self.worker(CJIR, xml=mixed, page=OJS.format(root=CJIR).replace('10.1234/synthetic.1', ''))
        self.assertEqual(result['saved'], 2)
        self.assertTrue(any('/article/view/3' in p for p in requests))

    def test_ojs_author_identifiers_bind_to_each_author_and_never_confirm_people(self):
        from platform_app.author_suggestions import native_authors
        document = dict(url=INTERSECTIONS+'/article/view/1', content_type='text/html', text=OJS.format(root=INTERSECTIONS))
        authors = native_authors(document, {})
        self.assertEqual([(a['raw_name'], a['orcid']) for a in authors], [('Ada Example','0000-0002-4878-9755'),('Bea Example','0000-0002-5779-752X')])
        self.assertEqual(authors[0]['affiliations'], ['Synthetic University'])
        self.assertEqual(authors[1]['affiliations'], [])
        # A global identifier cannot be assigned to authors lacking their own binding.
        document['text'] = document['text'].replace('<span class="orcid"><a href="https://orcid.org/0000-0002-5779-752X">ORCID</a></span>', '')
        self.assertEqual(native_authors(document, {})[1]['orcid'], '')

    def test_gssc_saves_actual_body_bound_profile_and_backup_restores_queue_and_raw_bytes(self):
        from pathlib import Path
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        from platform_app.author_suggestions import native_authors
        root = 'https://www.gssc.lt/en/'
        sid = self.source(root, 'institution')
        self.call('/api/sources/' + sid + '/ingestion', {'enabled': True}, user='admin', method='PUT')
        result, requests = self.worker(root, xml=GSSC_LIST, page=GSSC_PAGE)
        self.assertEqual(result['saved'], 1)
        rid = self.clients['researcher'].get('/api/records').json['items'][0]['id']
        detail = self.clients['researcher'].get('/api/records/' + rid).json
        snap = detail['automatic_acquisition']['snapshots'][0]
        self.assertTrue(snap['work_body_available'])
        self.assertEqual(snap['content_kind'], 'work_body')
        self.assertIn('Actual synthetic policy body.', snap['work_body']['text'])
        self.assertNotIn('introductory', snap['work_body']['text'])
        self.assertNotIn('biography', snap['work_body']['text'])
        self.assertEqual(detail['abstract'], '')
        self.assertEqual(detail['published_on'], '2026-10-21')
        self.assertEqual(detail['authors'], 'Ada Example')
        from platform_app.automatic_processing import run_pending
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY':''}), patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('unconfigured AI must not send')):
            run_pending(self.app.config['DATA_DIR'], limit=10)
        tasks = self.clients['researcher'].get('/api/records/'+rid).json['automatic_tasks']
        self.assertEqual({t['task'] for t in tasks}, {'translation','classification','summary'})
        authors = native_authors(dict(url='https://www.gssc.lt/en/publication/synthetic-study/', text=GSSC_PAGE, content_type='text/html'), {})
        self.assertEqual(authors[0]['profile_url'], 'https://www.gssc.lt/en/autoriai/ada-example/')
        self.assertEqual(self.clients['researcher'].get('/api/records/' + rid + '/bylines').json['items'], [])
        backup = Path(self.temp.name) / 'three-sources.zip'
        with self.call('/api/backup', user='admin') as response:
            backup.write_bytes(response.data)
        restored = restore_backup(backup, Path(self.temp.name) / 'restored-sources')
        client = create_app(restored, testing=True).test_client()
        csrf = client.get('/api/session').json['csrf']
        client.post('/api/login', json=dict(username='admin', password='LocalDemo2026!'), headers={'X-CSRF-Token': csrf})
        recovered = client.get('/api/records/' + rid).json
        self.assertEqual(client.get(recovered['automatic_acquisition']['snapshots'][0]['download_url']).data, GSSC_PAGE.encode())
        self.assertEqual(client.get('/api/records/' + rid + '/suggestions').json['jobs'], [])
        from platform_app.maintenance_agent import run_pending as maintain_pending
        maintain_pending(restored, limit=0)
        jobs = [job for job in client.get('/api/maintenance/jobs').json['items'] if job['target_id'] == rid]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['status'], 'queued')
        self.assertTrue(client.get('/api/sources/' + sid + '/ingestion').json['enabled'])
        # Integrity hashes alone must not authorize a substituted summary body
        # or an adapter relabel that evades replay of the saved official bytes.
        import hashlib, sqlite3, zipfile
        with zipfile.ZipFile(backup) as archive:
            originals = {name:archive.read(name) for name in archive.namelist()}
        for corruption in ['body','adapter','fields']:
            files = dict(originals)
            database = Path(self.temp.name) / ('corrupt-'+corruption+'.sqlite3')
            database.write_bytes(files['platform.sqlite3'])
            db = sqlite3.connect(database)
            with db:
                raw = json.loads(db.execute('SELECT raw_json FROM records WHERE id=?',(rid,)).fetchone()[0])
                changed = raw['automatic_acquisition']['snapshots'][0]
                if corruption == 'body':
                    changed['work_body'] = dict(html='<p>Forged substitute body.</p>',text='Forged substitute body.')
                elif corruption == 'adapter':
                    changed['adapter'] = 'liia-opinions-auto-v1'
                else:
                    raw['discovery_evidence'][-1]['article_fields']['title'] = 'Forged substitute title'
                db.execute('UPDATE records SET raw_json=? WHERE id=?',(json.dumps(raw),rid))
            db.close()
            files['platform.sqlite3'] = database.read_bytes()
            manifest = json.loads(files['manifest.json'])
            manifest['files']['platform.sqlite3'] = dict(bytes=len(files['platform.sqlite3']),sha256=hashlib.sha256(files['platform.sqlite3']).hexdigest())
            files['manifest.json'] = json.dumps(manifest).encode()
            broken = Path(self.temp.name) / ('corrupt-'+corruption+'.zip')
            with zipfile.ZipFile(broken,'w') as archive:
                for name, data in files.items(): archive.writestr(name,data)
            target = Path(self.temp.name) / ('must-not-publish-'+corruption)
            with self.assertRaisesRegex(ValueError,'自动取得'):
                restore_backup(broken,target)
            self.assertFalse(target.exists())

    def test_inactive_enabling_operator_does_not_enqueue_but_public_articles_still_arrive(self):
        sid = self.source()
        self.call('/api/sources/'+sid+'/ingestion', {'enabled':True}, user='admin', method='PUT')
        created = self.call('/api/members', {'username':'otheradmin','name':'Other admin','password':'OtherSynthetic2026!','role':'admin'}, user='admin')
        self.assertEqual(created.status_code, 201, created.json)
        client = self.app.test_client()
        csrf = client.get('/api/session').json['csrf']
        logged = client.post('/api/login', json={'username':'otheradmin','password':'OtherSynthetic2026!'}, headers={'X-CSRF-Token':csrf})
        self.assertEqual(logged.status_code,200)
        disabled = client.put('/api/members/admin',json={'active':False},headers={'X-CSRF-Token':logged.json['csrf']})
        self.assertEqual(disabled.status_code,200,disabled.json)
        self.assertEqual(self.worker(CJIR)[0]['saved'],1)
        rid = self.clients['researcher'].get('/api/records').json['items'][0]['id']
        self.assertEqual(self.clients['researcher'].get('/api/records/'+rid+'/suggestions').json['jobs'],[])

    def test_explicit_legacy_author_job_uses_official_evidence_and_human_adoption(self):
        from platform_app.archive_suggestions import run_pending
        from tests.synthetic_ai import ENV
        sid = self.source()
        self.call('/api/sources/' + sid + '/ingestion', {'enabled': True}, user='admin', method='PUT')
        self.worker(CJIR)
        rid = self.clients['researcher'].get('/api/records').json['items'][0]['id']
        self.assertEqual(self.call('/api/archive-jobs', {'record_ids': [rid], 'request_id': 'explicit-official-evidence'}).status_code, 201)
        acquired = []
        def fetch(url, *args, **kwargs):
            acquired.append(url)
            if '/article/view/' in url:
                text, mime = OJS.format(root=CJIR), 'text/html'
            else:
                first = 'Ada' if '4878-9755' in url else 'Bea'
                text = json.dumps({'name': {'given-names': {'value': first}, 'family-name': {'value': 'Example'}}})
                mime = 'application/json'
            return dict(url=url, text=text, bytes=text.encode(), content_type=mime, encoding='utf-8')
        sent = []
        def respond(request, **kwargs):
            prompt = json.loads(request.data)
            value = json.loads(prompt['messages'][-1]['content'])
            sent.append(value)
            response = MagicMock()
            response.__enter__.return_value = response
            response.geturl.return_value = request.full_url
            response.read.return_value = json.dumps({'model': 'deepseek-flash', 'usage': {'prompt_tokens': 23, 'completion_tokens': 7, 'total_tokens': 30},
                'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'suggestions': value['author_facts']})}}]}).encode()
            return response
        self.call('/api/admin/ai/config', {'cap': '1', 'currency': 'USD'}, user='admin')
        with patch.dict('os.environ', {**ENV, 'DEEPSEEK_API_KEY': 'synthetic-only'}), \
             patch('platform_app.intake.fetch_document', side_effect=fetch), \
             patch('urllib.request.OpenerDirector.open', side_effect=respond):
            self.assertEqual(run_pending(self.app.config['DATA_DIR'])['completed'], 1)
        self.assertFalse(any('crossref.org' in u for u in acquired))
        self.assertEqual(len(sent), 1)
        state = self.clients['researcher'].get('/api/records/' + rid + '/suggestions').json
        self.assertEqual(len(state['candidates']), 2)
        self.assertEqual(self.clients['researcher'].get('/api/records/' + rid + '/bylines').json['items'], [])
        self.assertEqual(self.clients['researcher'].get('/api/people').json['total'], 0)
        result = self.call('/api/records/' + rid + '/suggestions/decide', {'version': state['version'], 'byline_version': state['byline_version'], 'adopt': [c['id'] for c in state['candidates']]})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(len(self.clients['researcher'].get('/api/records/' + rid + '/bylines').json['items']), 2)
        self.assertEqual(self.clients['researcher'].get('/api/records/' + rid).json['status'], 'pending')

    def test_public_maintenance_does_not_depend_on_collection_switch_or_operator_session(self):
        from platform_app.maintenance_agent import run_pending
        sid = self.source()
        path = '/api/sources/' + sid + '/ingestion'
        self.call(path, {'enabled': True}, user='admin', method='PUT')
        self.worker(CJIR)
        rid = self.clients['researcher'].get('/api/records').json['items'][0]['id']
        self.call(path, {'enabled': False}, user='admin', method='PUT')
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('scan must not spend')):
            run_pending(self.app.config['DATA_DIR'], limit=0)
        first = [job for job in self.clients['researcher'].get('/api/maintenance/jobs').json['items'] if job['target_id'] == rid]
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]['status'], 'queued')
        self.call(path, {'enabled': True}, user='admin', method='PUT')
        self.call(path + '/run', {}, user='admin')
        self.worker(CJIR, xml=feed(CJIR).replace('/view/1','/view/2'), page=OJS.format(root=CJIR).replace('synthetic.1','synthetic.2'))
        second = next(r for r in self.clients['researcher'].get('/api/records').json['items'] if r['id'] != rid)
        changed = self.call('/api/members/admin', {'password':'ChangedSynthetic2026!'}, user='admin', method='PUT')
        self.assertEqual(changed.status_code, 200, changed.json)
        run_pending(self.app.config['DATA_DIR'], limit=0)
        jobs = self.clients['researcher'].get('/api/maintenance/jobs').json['items']
        self.assertEqual([job['id'] for job in jobs if job['target_id'] == rid], [first[0]['id']])
        self.assertTrue(any(job['target_id'] == second['id'] and job['status'] == 'queued' for job in jobs))

    def test_collection_keeps_human_metadata_without_legacy_author_jobs_after_retry(self):
        sid = self.source()
        path = '/api/sources/' + sid + '/ingestion'
        old = self.call('/api/records', dict(kind='journal_article', title='Human existing title', abstract='Human existing abstract', doi='10.1234/synthetic.1', visibility='shared')).json['id']
        self.call(path, {'enabled': True}, user='admin', method='PUT')
        self.worker(CJIR)
        self.assertEqual(self.clients['researcher'].get('/api/records/'+old+'/suggestions').json['jobs'], [])
        detail = self.clients['researcher'].get('/api/records/'+old).json
        self.assertEqual((detail['title'],detail['abstract']), ('Human existing title','Human existing abstract'))
        self.call(path+'/run', {}, user='admin')
        badfeed = feed(CJIR).replace('/view/1','/view/2')
        self.assertEqual(self.worker(CJIR, xml=badfeed, page='<html><script>challenge()</script></html>')[0]['failed'], 1)
        row = next(r for r in self.clients['researcher'].get('/api/records').json['items'] if r['id']!=old)
        rid = row['id']
        self.assertEqual(self.clients['researcher'].get('/api/records/'+rid+'/suggestions').json['jobs'], [])
        # Human corrections made during the outage survive successful retry.
        self.call('/api/records/'+rid, {'version':row['version'], 'title':'Human corrected after failure'}, method='PUT')
        run = self.clients['admin'].get(path).json['runs'][0]
        self.call('/api/ingestion/runs/'+run['id']+'/retry', {}, user='admin')
        self.assertEqual(self.worker(CJIR, page=OJS.format(root=CJIR).replace('synthetic.1','synthetic.2'))[0]['saved'], 1)
        detail = self.clients['researcher'].get('/api/records/'+rid).json
        self.assertEqual(detail['title'], 'Human corrected after failure')
        self.assertEqual(self.clients['researcher'].get('/api/records/'+rid+'/suggestions').json['jobs'], [])
        self.call(path+'/run', {}, user='admin')
        self.worker(CJIR, xml=badfeed, page=OJS.format(root=CJIR).replace('synthetic.1','synthetic.2'))
        self.assertEqual(self.clients['researcher'].get('/api/records/'+rid+'/suggestions').json['jobs'], [])

    def test_paused_budget_does_not_stop_public_acquisition_and_chinese_uses_acquired_not_human_fields(self):
        from platform_app.automatic_processing import run_pending
        from tests.synthetic_ai import ENV
        sid = self.source()
        self.call('/api/sources/'+sid+'/ingestion', {'enabled':True}, user='admin', method='PUT')
        self.assertEqual(self.worker(CJIR)[0]['saved'], 1)
        row = self.clients['researcher'].get('/api/records').json['items'][0]
        rid = row['id']
        self.call('/api/records/'+rid, {'version':row['version'], 'title':'Private human title', 'abstract':'Private human abstract', 'chinese_title':'人工译题'}, method='PUT')
        self.call('/api/admin/ai/config', {'cap':'1','currency':'USD'}, user='admin')
        self.call('/api/admin/ai/pause', {'paused':True}, user='admin')
        with patch.dict('os.environ', {**ENV,'DEEPSEEK_API_KEY':'synthetic-only'}), \
             patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('paused budget must not send')):
            run_pending(self.app.config['DATA_DIR'], limit=10)
        detail = self.clients['researcher'].get('/api/records/'+rid).json
        self.assertEqual(len(detail['automatic_tasks']), 2)
        self.assertEqual({t['task'] for t in detail['automatic_tasks']}, {'translation','classification'})
        self.assertTrue(all(t['status']=='paused' for t in detail['automatic_tasks']))
        self.assertEqual(detail['title'], 'Private human title')
        # The public input can be independently inspected in the persistent task
        # rows; nothing from the later human edit is a provider input.
        from platform_app.store import connect
        db = connect(self.app.config['DATA_DIR']/'platform.sqlite3')
        try:
            inputs = [json.loads(r[0]) for r in db.execute('SELECT input_json FROM automatic_tasks')]
        finally:
            db.close()
        self.assertTrue(all(v['title']=='Synthetic education study' and v['abstract']=='Original abstract about education policy.' for v in inputs))
        self.call('/api/admin/ai/pause', {'paused':False}, user='admin')
        self.call('/api/admin/ai/config', {'cap':'0.000001','currency':'USD'}, user='admin')
        with patch('platform_app.store.now', return_value='2026-11-03T12:10:00+00:00'), \
             patch.dict('os.environ', {**ENV,'DEEPSEEK_API_KEY':'synthetic-only'}), \
             patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('exhausted budget must not send')):
            run_pending(self.app.config['DATA_DIR'], limit=10)
        tasks = self.clients['researcher'].get('/api/records/'+rid).json['automatic_tasks']
        self.assertTrue(all(t['status']=='paused' for t in tasks))
        self.call('/api/sources/'+sid+'/ingestion/run', {}, user='admin')
        result, unused = self.worker(CJIR, xml=feed(CJIR).replace('/view/1','/view/2'), page=OJS.format(root=CJIR).replace('synthetic.1','synthetic.2'))
        self.assertEqual(result['saved'], 1)
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'], 2)


if __name__ == '__main__':
    unittest.main()
