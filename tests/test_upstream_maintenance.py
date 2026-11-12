"""Issue 66: member HTTP, bounded public transport, worker and recovery."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from tests import test_journal_collection as collection


def bje(**values):
    return {**collection.work(), 'ISSN':['1406-099X','2334-4385'],
            'container-title':['Baltic Journal of Economics'], **values}


class UpstreamMaintenanceTests(unittest.TestCase):
    def setUp(self):
        collection.JournalCollectionTests.setUp(self)
        clock=patch('platform_app.record_revisions.now',return_value='2026-11-04T00:00:00+00:00')
        clock.start();self.addCleanup(clock.stop)
    call = collection.JournalCollectionTests.call
    worker = collection.JournalCollectionTests.worker

    def source(self):
        response = self.call('/api/sources', dict(name='Baltic Journal of Economics', kind='journal',
            website='https://www.sseriga.edu/centres/biceps/bje', issn='1406-099X; 2334-4385'))
        self.assertEqual(response.status_code, 201, response.json)
        sid = response.json['id']
        response = self.call('/api/sources/'+sid+'/ingestion', {'enabled': True}, user='admin', method='PUT')
        self.assertEqual(response.status_code, 200, response.json)
        return sid

    def test_bje_bootstrap_uses_complementary_windows_then_indexed_and_keeps_dates(self):
        sid = self.source()
        path = '/api/sources/'+sid+'/ingestion'
        item = bje(**{'published': {'date-parts': [[2026, 1, 2]]},
            'created': {'date-parts': [[2026, 11, 2]], 'date-time': '2026-11-02T01:00:00Z'}})
        first, requests, _ = self.worker(sid, [item])
        self.assertEqual(first['saved'], 1, first)
        query = parse_qs(urlsplit(requests[0]).query)
        self.assertIn('from-online-pub-date:2026-10-06', query['filter'][0])
        self.assertNotIn('sort', query)
        self.assertNotIn('from-created-date', query['filter'][0])
        status = self.clients['admin'].get(path).json
        self.assertEqual(status['last_success'], '')
        self.assertTrue(status['coverage']['cursor']['pending'])
        # Finish seven-day subwindows for each independently requested phase.
        bases = [status['coverage']['window']['basis']]
        missing_online=dict(bje(),DOI='10.5555/missing-online',published={'date-parts':[[1999,3]]},
            created={'date-parts':[[2026,11]]},author=[{'family':'No ORCID'}])
        missing_online.pop('published-online')
        for n in range(15):
            self.call(path+'/run', user='admin')
            phase=state['coverage']['cursor']['basis'] if n else status['coverage']['cursor']['basis']
            _, requests, _ = self.worker(sid, [missing_online if phase=='created' else item], stamp='2026-11-04T12:01:00+00:00')
            state = self.clients['admin'].get(path).json
            bases.append(state['coverage']['window']['basis'])
            if not state['coverage']['cursor']['pending']:
                break
        self.assertIn('created', bases)
        self.assertTrue(state['last_success'])
        self.call(path+'/run', user='admin')
        _, requests, _ = self.worker(sid, [item], stamp='2026-11-05T12:00:00+00:00')
        self.assertIn('from-index-date:2026-11-03', parse_qs(urlsplit(requests[0]).query)['filter'][0])
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'], 2)
        record = self.clients['researcher'].get('/api/records?q='+item['DOI']).json['items'][0]
        detail = self.clients['researcher'].get('/api/records/'+record['id']).json
        raw = detail['automatic_acquisition']['snapshots'][0]['metadata']['raw']['date_fields']
        self.assertEqual(raw['created'], item['created'])
        self.assertEqual(raw['published-online'], item['published-online'])
        self.assertEqual(detail['published_on'], '2026-01-02')
        self.assertFalse(detail['reading_access']['has_body'])
        late=self.clients['researcher'].get('/api/records?q=10.5555/missing-online').json['items'][0]
        self.assertEqual(late['published_on'],'1999-03')

    def test_registered_notice_on_bounded_old_work_recheck_preserves_local_fields(self):
        from tests.test_assisted_intake import PublicSocket
        from platform_app.ingestion import run_pending
        sid = self.source()
        item = bje()
        self.worker(sid,[item])
        rid = self.clients['researcher'].get('/api/records').json['items'][0]['id']
        path = '/api/records/'+rid
        detail = self.clients['researcher'].get(path).json
        edited = self.call(path,dict(version=detail['version'],title='Human corrected title',chinese_title='人工校订题名'),method='PUT')
        self.assertEqual(edited.status_code,200,edited.json)
        requests = []
        changed = dict(item,title=['Changed upstream title'])
        notice = dict(DOI='10.5555/notice', **{'update-to':[dict(DOI=item['DOI'],type='retraction',updated={'date-parts':[[2026,11,12]]})]})
        class Socket(PublicSocket):
            def sendall(sock,data):
                url=data.split(b' ')[1].decode(); requests.append(url)
                message = changed if url.startswith('/works/10.') else dict(items=[notice],**{'total-results':1}) if url.startswith('/works?') else dict(items=[],**{'total-results':0})
                sock.body=PublicSocket(json.dumps(dict(status='ok',message=message)).encode(),'application/json').body
        self.call('/api/sources/'+sid+'/ingestion/run',user='admin')
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]), \
             patch('socket.create_connection',side_effect=lambda *a,**k:Socket(b'')), \
             patch('ssl.SSLContext.wrap_socket',side_effect=lambda sock,**k:sock), \
             patch('platform_app.store.now',return_value='2026-11-12T12:00:00+00:00'):
            result=run_pending(self.app.config['DATA_DIR'],source_ids=[sid],limit=1)
        self.assertEqual(len(requests),3,(requests,result))
        detail=self.clients['researcher'].get(path).json
        self.assertEqual(detail['title'],'Human corrected title')
        self.assertEqual(detail['chinese_title'],'人工校订题名')
        upstream=detail['automatic_acquisition']['upstream']
        self.assertEqual(upstream['notices'][0]['kind'],'retraction')
        self.assertIn('title',upstream['exception']['fields'])
        self.assertIn('title',upstream['last_changed_fields'])
        self.assertEqual(len(detail['automatic_acquisition']['snapshots']),2)
        problems=self.clients['admin'].get('/api/ingestion/exceptions').json
        self.assertEqual([p['record_id'] for p in problems['items']],[rid])
        self.assertEqual(self.clients['researcher'].get('/api/ingestion/exceptions').status_code,403)
        self.assertEqual(self.call(path+'/upstream/acknowledge',dict(version=detail['version'],signature=upstream['exception']['signature']),user='admin').status_code,200)
        self.assertEqual(self.clients['admin'].get('/api/ingestion/exceptions').json['items'],[])
        # Acknowledgement never removes the warning or its immutable response.
        detail=self.clients['researcher'].get(path).json
        self.assertEqual(detail['automatic_acquisition']['upstream']['notices'][0]['doi'],'10.5555/notice')
        oldest=self.clients['researcher'].get('/api/history/record/'+rid).json['items'][-1]
        self.assertEqual(self.call('/api/history/'+str(oldest['id'])+'/restore',dict(version=detail['version'])).status_code,200)
        detail=self.clients['researcher'].get(path).json
        self.assertEqual(detail['automatic_acquisition']['upstream']['notices'][0]['kind'],'retraction')
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        archive=Path(self.temp.name)/'upstream.zip'
        with self.call('/api/backup',user='admin') as response:
            archive.write_bytes(response.data)
        target=Path(self.temp.name)/'restored'
        restore_backup(archive,target)
        client=create_app(target,testing=True).test_client()
        csrf=client.get('/api/session').json['csrf']
        client.post('/api/login',json=dict(username='researcher',password='LocalDemo2026!'),headers={'X-CSRF-Token':csrf})
        restored=client.get(path).json
        self.assertEqual(restored['automatic_acquisition'],detail['automatic_acquisition'])
        proof=restored['automatic_acquisition']['upstream']['notice_evidence'][0]
        self.assertEqual(json.loads(client.get(proof['download_url']).data)['message']['items'],[notice])
        for snap in restored['automatic_acquisition']['snapshots']:
            self.assertEqual(__import__('hashlib').sha256(client.get(snap['download_url']).data).hexdigest(),snap['sha256'])

    def test_rejected_cursor_duplicates_and_unstable_count_keep_the_successful_watermark(self):
        sid=self.source();path='/api/sources/'+sid+'/ingestion'
        page=[dict(bje(),DOI='10.5555/page.'+str(i)) for i in range(25)]
        first,_,_=self.worker(sid,page,next_cursor='page/2+cursor',total=26)
        self.assertEqual(first['saved'],25)
        checkpoint=self.clients['admin'].get(path).json['cursor']
        self.call(path+'/run',user='admin')
        failed,requests,_=self.worker(sid,[],status='400 Bad Request')
        self.assertEqual(failed['failed'],1)
        state=self.clients['admin'].get(path).json
        self.assertEqual(state['last_success'],'')
        self.assertEqual(parse_qs(urlsplit(requests[0]).query)['cursor'],['page/2+cursor'])
        self.call(path+'/run',user='admin')
        self.worker(sid,page,next_cursor='page/2+cursor',total=26)
        self.call(path+'/run',user='admin')
        # The final page repeats a work and changes the count; the completed
        # item count alone cannot prove coverage of a changing result set.
        result,_,_=self.worker(sid,[page[0]],total=27)
        state=self.clients['admin'].get(path).json
        self.assertTrue(state['coverage']['coverage_uncertain'])
        self.assertEqual(state['last_success'],'')
        cursor=json.loads(state['cursor'])
        self.assertEqual(cursor['next_cursor'],'*')
        self.assertEqual(cursor['start'],json.loads(checkpoint)['start'])
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],25)

    def test_old_shared_manual_records_rotate_in_bounded_batches_private_and_reports_are_skipped(self):
        from tests.test_assisted_intake import PublicSocket
        from platform_app.ingestion import run_pending
        sid=self.source(); records=[]
        for i in range(5):
            records.append(self.call('/api/records',dict(kind='journal_article',title='Manual '+str(i),doi='10.5555/old.'+str(i),serial_id=sid)).json['id'])
        private=self.call('/api/records',dict(kind='journal_article',title='Private untouched',doi='10.5555/private',serial_id=sid,visibility='restricted')).json['id']
        report=self.call('/api/records',dict(kind='research_report',title='Authored report untouched',doi='10.5555/report',serial_id=sid)).json['id']
        requests=[]
        class Socket(PublicSocket):
            def sendall(sock,data):
                url=data.split(b' ')[1].decode();requests.append(url)
                if url.startswith('/works/10.'):
                    from urllib.parse import unquote
                    item=dict(bje(),DOI=unquote(url.removeprefix('/works/')))
                    message=item
                else:
                    message=dict(items=[],**{'total-results':0})
                sock.body=PublicSocket(json.dumps(dict(status='ok',message=message)).encode(),'application/json').body
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]), \
             patch('socket.create_connection',side_effect=lambda *a,**k:Socket(b'')), \
             patch('ssl.SSLContext.wrap_socket',side_effect=lambda sock,**k:sock), \
             patch('platform_app.store.now',return_value='2026-11-12T12:00:00+00:00'):
            self.assertEqual(run_pending(self.app.config['DATA_DIR'],source_ids=[sid])['saved'],3)
            self.call('/api/sources/'+sid+'/ingestion/run',user='admin')
            self.assertEqual(run_pending(self.app.config['DATA_DIR'],source_ids=[sid])['saved'],2)
        self.assertEqual(len(requests),12)
        self.assertFalse(any('private' in r for r in requests))
        self.assertFalse(any('10.5555%2Freport' in r for r in requests))
        for rid in records:
            detail=self.clients['researcher'].get('/api/records/'+rid).json
            self.assertTrue(detail['title'].startswith('Manual '))
            self.assertEqual(len(detail['automatic_acquisition']['snapshots']),1)
        self.assertNotIn('automatic_acquisition',self.clients['researcher'].get('/api/records/'+private).json)
        self.assertNotIn('automatic_acquisition',self.clients['researcher'].get('/api/records/'+report).json)

    def test_preupgrade_crossref_snapshot_restores_with_its_original_extraction_contract(self):
        from platform_app import store
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        legacy=json.loads((Path(__file__).parent/'fixtures/crossref_snapshot_v1.json').read_text(encoding='utf-8'))
        source=collection.JournalCollectionTests.source(self)
        self.worker(source,[collection.work(**{'created':{'date-parts':[[2026,11,2]]}})])
        rid=self.clients['researcher'].get('/api/records').json['items'][0]['id']
        # Fixed fixture was generated using c88a52d's unchanged v1 extractor,
        # before created/indexed/deposited were added to date_fields.
        db=store.connect(self.app.config['DATA_DIR']/'platform.sqlite3')
        with db:
            row=db.execute('SELECT raw_json FROM records WHERE id=?',(rid,)).fetchone()
            raw=json.loads(row[0]);raw['automatic_acquisition']['snapshots']=[legacy]
            raw['automatic_acquisition'].pop('upstream',None)
            for entry in raw['discovery_evidence']:
                entry['article_snapshot_id']=legacy['id'];entry['article_fields']=legacy['metadata']['fields']
            db.execute('UPDATE records SET raw_json=? WHERE id=?',(json.dumps(raw),rid))
        db.close()
        archive=Path(self.temp.name)/'preupgrade.zip'
        with self.call('/api/backup',user='admin') as response:
            archive.write_bytes(response.data)
        target=Path(self.temp.name)/'legacy-restored';restore_backup(archive,target)
        client=create_app(target,testing=True).test_client();token=client.get('/api/session').json['csrf']
        client.post('/api/login',json=dict(username='researcher',password='LocalDemo2026!'),headers={'X-CSRF-Token':token})
        snap=client.get('/api/records/'+rid).json['automatic_acquisition']['snapshots'][0]
        self.assertNotIn('created',snap['metadata']['raw']['date_fields'])
        self.assertEqual(snap['sha256'],legacy['sha256'])


if __name__ == '__main__':
    unittest.main()
