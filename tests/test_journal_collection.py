"""Synthetic Crossref JSON via member HTTP and public transport, never real services."""
import json
import io
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from tests import test_assisted_intake as base

JOURNALS = [
    ('https://www.tandfonline.com/journals/fjcs21', '2159-9165', '2159-9173', 'East European Politics'),
    ('https://www.tandfonline.com/journals/cjsb20', '1944-8953', '1944-8961', 'Journal of Balkan and Near Eastern Studies'),
    ('https://journals.sagepub.com/home/eup', '1465-1165', '1741-2757', 'European Union Politics'),
]


def work(index=0, **extra):
    website, paper, online, title = JOURNALS[index]
    return dict(DOI='10.5555/synthetic.' + paper, title=['Synthetic public article'],
                **{'container-title': [title], 'ISSN': [paper, online], 'type': 'journal-article',
                   'published-online': {'date-parts': [[2026, 11, 1]]},
                   'indexed': {'date-time': '2026-11-03T00:00:00Z'}},
                author=[{'given': 'Ada', 'family': 'Example', 'ORCID': 'https://orcid.org/0000-0002-1825-0097'}], **extra)


class JournalCollectionTests(unittest.TestCase):
    setUp = base.AssistedIntakeTests.setUp
    call = base.AssistedIntakeTests.call

    def source(self, index=0):
        website, paper, online, name = JOURNALS[index]
        response = self.call('/api/sources', dict(name=name, kind='journal', website=website, issn=paper, eissn=online))
        self.assertEqual(response.status_code, 201, response.json)
        sid = response.json['id']
        response = self.call('/api/sources/' + sid + '/ingestion', {'enabled': True}, user='admin', method='PUT')
        self.assertEqual(response.status_code, 200, response.json)
        return sid

    def worker(self, sid, items, *, next_cursor='next-page', total=None, stamp='2026-11-04T12:00:00+00:00', status='200 OK', stopping=lambda: False):
        from platform_app.ingestion import run_pending
        requests = []
        body = json.dumps({'status': 'ok', 'message': {'items': items, 'next-cursor': next_cursor, 'total-results': total if total is not None else len(items)}}).encode()
        class Socket(base.PublicSocket):
            def sendall(sock, data):
                requests.append(data.split(b' ')[1].decode())
                sock.body = base.PublicSocket(body, 'application/json', status=status, headers='Retry-After: 120\r\n').body
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), \
             patch('socket.create_connection', side_effect=lambda *a, **k: Socket(b'')), \
             patch('ssl.SSLContext.wrap_socket', side_effect=lambda sock, **k: sock), \
             patch('platform_app.store.now', return_value=stamp):
            result = run_pending(self.app.config['DATA_DIR'], source_ids=[sid], limit=1, stopping=stopping)
        return result, requests, body

    def test_three_journals_save_json_directly_and_preserve_missing_fields_and_original_response(self):
        for i in range(3):
            with self.subTest(journal=i):
                sid = self.source(i)
                item = work(i, **({'abstract': '<jats:p>Actual public abstract.</jats:p>'} if i == 2 else {}))
                result, requests, body = self.worker(sid, [item])
                self.assertEqual(result['saved'], 1, result)
                self.assertEqual(len(requests), 1, requests)
                self.assertTrue(requests[0].startswith('/journals/' + JOURNALS[i][1] + '/works?'))
                records = self.clients['researcher'].get('/api/records?source=' + sid).json
                self.assertEqual(records['total'], 1)
                record = self.clients['researcher'].get('/api/records/' + records['items'][0]['id']).json
                self.assertEqual(record['kind'], 'journal_article')
                self.assertEqual(record['serial_id'], sid)
                self.assertEqual(record['doi'], '10.5555/synthetic.' + JOURNALS[i][1])
                self.assertEqual(record['authors'], 'Ada Example')
                self.assertEqual(record['published_on'], '2026-11-01')
                self.assertEqual(record['abstract'], 'Actual public abstract.' if i == 2 else '')
                self.assertEqual((record['volume'], record['issue']), ('', ''))
                self.assertFalse(record['reading_access']['has_body'])
                snapshot = record['automatic_acquisition']['snapshots'][0]
                self.assertEqual(snapshot['content_kind'], 'bibliographic_metadata')
                self.assertEqual(self.clients['researcher'].get(snapshot['download_url']).data, body)
                self.assertEqual(self.clients['admin'].get('/api/admin/ai').json['attempts'], [])

    def test_existing_shared_article_gains_only_missing_proven_journal_relation(self):
        sid = self.source()
        publisher = self.call('/api/sources', dict(name='Human publisher', kind='institution')).json['id']
        created = self.call('/api/records', dict(kind='journal_article', title='Human title', authors='Human byline',
                           doi=work()['DOI'], abstract='Human abstract', source_id=publisher,
                           visibility='shared', volume='Human volume', issue='Human issue'))
        self.assertEqual(created.status_code, 201, created.json)
        rid = created.json['id']
        path = '/api/records/'+rid
        reviewed = self.call('/api/review/record/'+rid, dict(version=1, review_scope='metadata_only',
                             review_note='Independent synthetic metadata check'), user='admin')
        self.assertEqual(reviewed.status_code, 200, reviewed.json)
        before = self.clients['researcher'].get(path).json
        self.assertFalse(before['serial_id'])
        result, _, body = self.worker(sid, [work()])
        self.assertEqual(result['saved'], 1, result)
        records = self.clients['colleague'].get('/api/records?source='+sid).json
        self.assertEqual([r['id'] for r in records['items']], [rid])
        current = self.clients['researcher'].get(path).json
        self.assertEqual(current['serial_id'], sid)
        for key in ('kind', 'title', 'authors', 'abstract', 'source_id', 'visibility', 'owner_id', 'author_id',
                    'author_confirmed', 'status', 'doi', 'volume', 'issue', 'related_source_ids'):
            self.assertEqual(current[key], before[key], key)
        self.assertEqual(current['status'], 'verified')
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'], 1)
        snap = current['automatic_acquisition']['snapshots'][0]
        self.assertEqual(self.clients['researcher'].get(snap['download_url']).data, body)
        history = self.clients['researcher'].get('/api/history/record/'+rid).json['items']
        self.assertIn('补齐有据刊物关联', history[0]['action'])
        self.call('/api/sources/'+sid+'/ingestion/run', user='admin')
        self.worker(sid, [work()])
        self.assertEqual(self.clients['researcher'].get(path).json['serial_id'], sid)
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'], 1)

    def test_public_collection_preserves_manual_other_journal_and_private_duplicate(self):
        sid = self.source()
        other = self.call('/api/sources', dict(name='Human selected other journal', kind='journal')).json['id']
        private_work = dict(work(), DOI='10.5555/private-duplicate')
        manual = self.call('/api/records', dict(kind='journal_article', title='Manual relation',
                           doi=work()['DOI'], serial_id=other, visibility='shared')).json['id']
        private = self.call('/api/records', dict(kind='journal_article', title='Private original',
                            doi=private_work['DOI'], visibility='restricted')).json['id']
        private_path = '/api/records/'+private
        before = self.clients['researcher'].get(private_path).json
        result, _, _ = self.worker(sid, [work(), private_work])
        self.assertEqual((result['saved'], result['blocked']), (1, 1), result)
        self.assertEqual(self.clients['researcher'].get('/api/records/'+manual).json['serial_id'], other)
        self.assertEqual(self.clients['researcher'].get(private_path).json, before)
        self.assertEqual(self.clients['colleague'].get(private_path).status_code, 404)
        self.assertEqual(self.clients['colleague'].get('/api/records?source='+sid).json['total'], 0)
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'], 2)
        entry = next(e for e in self.clients['admin'].get('/api/sources/'+sid+'/ingestion').json['runs'][0]['entries'] if e['stage']=='blocked')
        self.assertIsNone(entry['record_id'])

    def test_no_journal_relation_without_matching_issn_evidence(self):
        sid = self.source()
        created = self.call('/api/records', dict(kind='journal_article', title='No unproven relation',
                           doi=work()['DOI'], visibility='shared')).json['id']
        path = '/api/records/'+created
        before = self.clients['researcher'].get(path).json
        result, _, _ = self.worker(sid, [dict(work(), ISSN=['0000-0000'])])
        self.assertEqual(result['saved'], 0, result)
        self.assertEqual(self.clients['researcher'].get(path).json, before)
        self.assertEqual(self.clients['researcher'].get('/api/records?source='+sid).json['total'], 0)

    def test_indexed_pages_resume_and_later_metadata_preserves_human_correction(self):
        sid = self.source()
        page = [dict(work(), DOI=f'10.5555/synthetic.{n}') for n in range(25)]
        first, requests, _ = self.worker(sid, page, next_cursor='second/+ page', total=26)
        self.assertEqual(first['saved'], 25)
        query = parse_qs(urlsplit(requests[0]).query)
        self.assertIn('from-index-date:2026-10-06', query['filter'][0])
        self.assertEqual(query['sort'], ['indexed'])
        config_path = '/api/sources/' + sid + '/ingestion'
        status = self.clients['admin'].get(config_path).json
        self.assertTrue(status['coverage']['cursor']['pending'])
        # A new process reads the persisted cursor, including reserved URL chars.
        from platform_app.web import create_app
        create_app(self.app.config['DATA_DIR'], testing=True)
        self.call(config_path + '/run', user='admin')
        second, requests, _ = self.worker(sid, [dict(work(), DOI='10.5555/synthetic.25')], total=26)
        self.assertEqual(second['saved'], 1)
        self.assertEqual(parse_qs(urlsplit(requests[0]).query)['cursor'], ['second/+ page'])
        self.assertTrue(self.clients['admin'].get(config_path).json['coverage']['window_complete'])
        record = self.clients['researcher'].get('/api/records?q=10.5555/synthetic.0').json['items'][0]
        detail_path = '/api/records/' + record['id']
        detail = self.clients['researcher'].get(detail_path).json
        corrected = self.call(detail_path, dict(detail, title='Human correction'), method='PUT')
        self.assertEqual(corrected.status_code, 200, corrected.json)
        self.call(config_path + '/run', user='admin')
        result, requests, _ = self.worker(sid, [dict(work(), DOI='10.5555/synthetic.0', abstract='Later supplied abstract.', volume='18', issue='2')], stamp='2026-11-05T12:00:00+00:00')
        self.assertEqual(result['saved'], 1, result)
        self.assertIn('from-index-date:2026-11-04', parse_qs(urlsplit(requests[0]).query)['filter'][0])
        current = self.clients['researcher'].get(detail_path).json
        self.assertEqual(current['title'], 'Human correction')
        latest = current['automatic_acquisition']['snapshots'][-1]['metadata']['fields']
        self.assertEqual((latest['abstract'], latest['volume'], latest['issue']), ('Later supplied abstract.', '18', '2'))
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'], 26)
        self.assertEqual(len(current['automatic_acquisition']['snapshots']), 2)

    def test_public_machine_opt_in_runs_only_selected_journals_and_no_paid_queues(self):
        from pathlib import Path
        from portable.public_collection import LocalPublicSettings, install_public_control
        from portable.worker import PortableWorker
        import threading
        sid, other = self.source(), self.source(1)
        self.call('/api/sources/' + other + '/ingestion/run', user='admin')
        public = LocalPublicSettings(Path(self.temp.name)/'copy', storage_root=Path(self.temp.name)/'local')
        class NoAI:
            enabled=False
            def status(self):
                return {'enabled': self.enabled, 'configured': False}
        worker = PortableWorker(self.app.config['DATA_DIR'], Path(self.temp.name), NoAI(), threading.Event(), public_settings=public)
        install_public_control(self.app, worker)
        self.assertEqual(self.call('/api/ingestion/local', {'enabled': True, 'source_ids': [sid]}, method='PUT').status_code, 403)
        # Configuration and HTTP authorization use the same public control seam.
        from platform_app.ingestion import run_worker
        with patch.object(worker, 'ensure_started') as launch:
            response = self.call('/api/ingestion/local', {'enabled': True, 'source_ids': [sid]}, user='admin', method='PUT')
            self.assertEqual(response.status_code, 200, response.json)
            launch.assert_called_once()
        self.assertTrue(LocalPublicSettings(Path(self.temp.name)/'copy', storage_root=Path(self.temp.name)/'local').status()['enabled'])
        self.assertFalse(LocalPublicSettings(Path(self.temp.name)/'restored', storage_root=Path(self.temp.name)/'local').status()['enabled'])
        with patch('platform_app.automatic_processing.run_pending', side_effect=AssertionError('Paid Chinese queue dispatched')), \
             patch('platform_app.archive_suggestions.run_pending', side_effect=AssertionError('Paid archive queue dispatched')), \
             patch('platform_app.ingestion.run_pending', wraps=__import__('platform_app.ingestion', fromlist=['run_pending']).run_pending):
            # Exercise the production worker loop with synthetic public sockets.
            body = json.dumps({'status': 'ok', 'message': {'items': [work()], 'total-results': 1}}).encode()
            class Socket(base.PublicSocket):
                def sendall(sock,data):
                    index=1 if b'1944-8953' in data else 0
                    payload=json.dumps({'status':'ok','message':{'items':[work(index)],'total-results':1}}).encode()
                    sock.body=base.PublicSocket(payload,'application/json').body
            with patch('socket.getaddrinfo', return_value=[(2,1,6,'',('93.184.216.34',443))]), \
                 patch('socket.create_connection', side_effect=lambda *a, **k: Socket(body, 'application/json')), \
                 patch('ssl.SSLContext.wrap_socket', side_effect=lambda sock, **k: sock):
                run_worker(self.app.config['DATA_DIR'], once=True, source_ids=worker.collection_sources, paid_enabled=worker.ai_enabled)
                self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],1)
                self.assertEqual(self.clients['admin'].get('/api/sources/'+other+'/ingestion').json['runs'][0]['status'],'queued')
                worker.settings.enabled=True
                self.call('/api/admin/ai/pause',{'paused':True},user='admin')
                self.call('/api/sources/'+sid+'/ingestion/run',user='admin')
                run_worker(self.app.config['DATA_DIR'], once=True, source_ids=worker.collection_sources, paid_enabled=worker.ai_enabled)
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'], 2)
        self.assertEqual(self.clients['admin'].get('/api/sources/'+other+'/ingestion').json['runs'][0]['status'], 'succeeded')
        self.assertEqual(self.clients['admin'].get('/api/admin/ai').json['attempts'], [])

    def test_sample_is_bounded_specific_and_preserves_watermark_and_backup_evidence(self):
        from pathlib import Path
        from platform_app.ingestion import sample_journals
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        sid, other = self.source(), self.source(1)
        self.worker(sid, [work()])
        config_path = '/api/sources/' + sid + '/ingestion'
        watermark = self.clients['admin'].get(config_path).json['cursor']
        self.call('/api/sources/'+other+'/ingestion/run', user='admin')
        requests = []
        body = json.dumps({'status': 'ok', 'message': {'items': [work()], 'total-results': 200}}).encode()
        class Socket(base.PublicSocket):
            def sendall(sock, data):
                requests.append(data.split(b' ')[1].decode())
                sock.body=base.PublicSocket(body,'application/json').body
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]), \
             patch('socket.create_connection',side_effect=lambda *a,**k:Socket(b'')), \
             patch('ssl.SSLContext.wrap_socket',side_effect=lambda sock,**k:sock):
            report = sample_journals(self.app.config['DATA_DIR'],[sid])
        self.assertEqual(report['sources'][0]['saved'],1)
        self.assertEqual(parse_qs(urlsplit(requests[0]).query)['rows'],['5'])
        self.assertEqual(len(requests),1)
        self.assertEqual(self.clients['admin'].get(config_path).json['cursor'],watermark)
        self.assertEqual(self.clients['admin'].get('/api/sources/'+other+'/ingestion').json['runs'][0]['status'],'queued')
        archive = Path(self.temp.name)/'journal-backup.zip'
        with self.call('/api/backup',user='admin') as response:
            archive.write_bytes(response.data)
        target = Path(self.temp.name)/'restored-data'
        restore_backup(archive,target)
        restored=create_app(target,testing=True).test_client()
        csrf=restored.get('/api/session').json['csrf']
        restored.post('/api/login',json={'username':'researcher','password':'LocalDemo2026!'},headers={'X-CSRF-Token':csrf})
        record=restored.get('/api/records').json['items'][0]
        current=restored.get('/api/records/'+record['id']).json
        snap=current['automatic_acquisition']['snapshots'][-1]
        self.assertEqual(restored.get(snap['download_url']).data,body)
        self.assertFalse(restored.get('/api/ingestion/local').status_code==200)

    def test_429_and_403_stop_without_other_requests_and_disable_prevents_claim(self):
        sid=self.source()
        path='/api/sources/'+sid+'/ingestion'
        result,requests,_=self.worker(sid,[work()],status='429 Too Many Requests')
        self.assertEqual(result['failed'],1)
        self.assertEqual(len(requests),1)
        coverage=self.clients['admin'].get(path).json['coverage']
        self.assertEqual(coverage['network_backoff']['http_status'],429)
        self.assertEqual(coverage['network_backoff']['retry_at'],'2026-11-04T12:02:00+00:00')
        result,requests,_=self.worker(sid,[work()])
        self.assertEqual(result['runs'],0)
        self.assertEqual(requests,[])

        result,requests,_=self.worker(sid,[work()],status='403 Forbidden',stamp='2026-11-05T12:00:00+00:00')
        self.assertEqual(result['failed'],1)
        self.assertEqual(len(requests),1)
        self.call(path,{'enabled':False},user='admin',method='PUT')
        result,requests,_=self.worker(sid,[work()],stamp='2026-11-06T12:00:00+00:00')
        self.assertEqual(result['runs'],0)
        self.assertEqual(requests,[])

    def test_journal_article_about_registration_is_not_a_notice(self):
        sid=self.source()
        result,_,_=self.worker(sid,[dict(work(),title=['Voter registration and public policy'])])
        self.assertEqual(result['saved'],1,result)

    def test_rejected_cursor_replays_same_index_window_without_advancing_past_uncovered_work(self):
        sid=self.source()
        page=[dict(work(),DOI=f'10.5555/replay.{n}') for n in range(25)]
        self.worker(sid,page,next_cursor='expired',total=26)
        result,requests,_=self.worker(sid,page,total=26,status='400 Bad Request',stamp='2026-11-04T12:06:00+00:00')
        self.assertEqual(result['failed'],1)
        self.assertEqual(len(requests),1)
        self.assertEqual(parse_qs(urlsplit(requests[0]).query)['cursor'],['expired'])
        self.call('/api/sources/'+sid+'/ingestion/run',user='admin')
        result,requests,_=self.worker(sid,page,next_cursor='renewed',total=26,stamp='2026-11-04T13:06:00+00:00')
        self.assertEqual(result['saved'],25)
        self.assertEqual(parse_qs(urlsplit(requests[0]).query)['cursor'],['*'])
        self.assertIn('from-index-date:2026-10-06',parse_qs(urlsplit(requests[0]).query)['filter'][0])
        status=self.clients['admin'].get('/api/sources/'+sid+'/ingestion').json
        self.assertTrue(status['coverage']['cursor']['pending'])
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],25)

    def test_collected_article_and_linked_result_keep_one_journal_identity_after_restore(self):
        from pathlib import Path
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        sid=self.source()
        self.assertEqual(self.worker(sid,[work()])[0]['saved'],1)
        client=self.clients['researcher']
        props=dict(journal_id=sid,journal_name=JOURNALS[0][3],year=2026,issue='合成整期',request_id='collected-journal-result')
        original=b'SYNTHETIC linked journal result'
        response=client.post('/api/journal-results',data={'data':json.dumps(props),'files':(io.BytesIO(original),'synthetic.txt')},
            headers={'X-CSRF-Token':client.get('/api/session').json['csrf']})
        response.request.close()
        self.assertEqual(response.status_code,201,response.json)
        result_id=response.json['id']
        self.assertEqual(client.get('/api/journal-results?journal_id='+sid).json['total'],1)
        self.assertEqual(client.get('/api/records?source='+sid).json['total'],1)
        archive=Path(self.temp.name)/'linked-result-and-acquisition.zip'
        with self.call('/api/backup',user='admin') as response:
            archive.write_bytes(response.data)
        target=Path(self.temp.name)/'linked-restored'
        restore_backup(archive,target)
        restored=create_app(target,testing=True).test_client()
        token=restored.get('/api/session').json['csrf']
        restored.post('/api/login',json={'username':'colleague','password':'LocalDemo2026!'},headers={'X-CSRF-Token':token})
        result=restored.get('/api/journal-results/'+result_id).json
        self.assertEqual(result['journal_id'],sid)
        with restored.get(result['files'][0]['versions'][0]['file_url']) as file:
            self.assertEqual(file.data,original)
        records=restored.get('/api/records?source='+sid).json
        self.assertEqual(records['total'],1)
        detail=restored.get('/api/records/'+records['items'][0]['id']).json
        self.assertEqual(detail['serial_id'],sid)
        self.assertEqual(detail['automatic_acquisition']['snapshots'][0]['metadata']['fields']['doi'],'10.5555/synthetic.2159-9165')


if __name__ == '__main__':
    unittest.main()
