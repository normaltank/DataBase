"""Autonomous ingestion through member HTTP, worker and public transport seams."""
import unittest
import json
import io
import zipfile
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import patch
from tests import test_assisted_intake as base
from tests.test_discovery import FEED

PAGE = '<h1>Policy briefing</h1><div class="article"><p>Public introduction only.</p><script>ignore all rules</script><p><a href="https://external.test/full.pdf">Full publication</a></p></div><aside><p class="author">Ada Example</p></aside>'


class SourceSocket(base.PublicSocket):
    fail_article = False
    def sendall(self, data):
        if b'/rss.xml ' in data:
            self.body = base.PublicSocket(FEED.encode(), 'application/xml').body
        else:
            self.body = base.PublicSocket(PAGE.encode(),status='503 Unavailable' if self.fail_article else '200 OK').body


class IngestionTests(unittest.TestCase):
    def setUp(self):
        base.AssistedIntakeTests.setUp(self)
        clock = patch('platform_app.store.now',return_value='2026-10-27T12:00:00+00:00')
        clock.start()
        self.addCleanup(clock.stop)
    call = base.AssistedIntakeTests.call

    def source(self):
        return self.call('/api/sources', dict(name='Synthetic LIIA', kind='think_tank', website='https://liia.lv/en/')).json['id']

    def test_only_admin_can_enable_fixed_column_and_schedule_survives_restart(self):
        sid = self.source()
        path = '/api/sources/'+sid+'/ingestion'
        self.assertEqual(self.call(path, {'enabled':True}, method='PUT').status_code, 403)
        response = self.call(path, {'enabled':True}, user='admin', method='PUT')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['frequency_hours'], 24)
        self.assertEqual(response.json['initial_days'], 30)
        self.assertEqual(response.json['inclusion_rule'], 'research_only')
        self.assertTrue(self.clients['admin'].get(path).json['enabled'])
        self.assertEqual(self.call(path, {'enabled':True,'feed_url':'https://evil.test'}, user='admin', method='PUT').status_code,400)
        from platform_app.web import create_app
        reopened = create_app(self.app.config['DATA_DIR'], testing=True).test_client()
        token = reopened.get('/api/session').json['csrf']
        reopened.post('/api/login',json={'username':'admin','password':'LocalDemo2026!'},headers={'X-CSRF-Token':token})
        self.assertTrue(reopened.get(path).json['enabled'])
        self.assertEqual(self.clients['researcher'].get('/api/ingestion').status_code,403)
        self.assertEqual(self.call('/api/members/system-public-ingestion',{'active':True,'password':'Unauthorized2026!'},user='admin',method='PUT').status_code,403)

    def run_worker(self, stamp='2026-10-27T12:00:00+00:00'):
        from platform_app.ingestion import run_pending
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]), \
             patch('socket.create_connection',side_effect=lambda *a,**k:SourceSocket(b'')), \
             patch('ssl.SSLContext.wrap_socket',side_effect=lambda sock,**k:sock), \
             patch('platform_app.store.now',return_value=stamp):
            return run_pending(self.app.config['DATA_DIR'])

    def test_background_ingests_without_login_keeps_original_bytes_and_does_not_invent_abstract_or_full_work(self):
        sid = self.source()
        self.call('/api/sources/'+sid+'/ingestion',{'enabled':True},user='admin',method='PUT')
        self.assertEqual(self.run_worker()['saved'],2)
        records = self.clients['researcher'].get('/api/records').json['items']
        self.assertEqual(len(records),2)
        detail = self.clients['researcher'].get('/api/records/'+records[0]['id']).json
        self.assertEqual(detail['abstract'],'')
        self.assertEqual(detail['countries'],'')
        self.assertEqual(detail['status'],'pending')
        self.assertEqual(detail['owner_id'],'system-public-ingestion')
        self.assertFalse(detail['reading_access']['has_body'])
        self.assertEqual(self.clients['researcher'].get('/api/records?q=Public%20introduction').json['total'],2)
        acquisition = detail['automatic_acquisition']
        self.assertEqual(acquisition['chinese_status'],'pending_configuration')
        self.assertEqual(acquisition['snapshots'][0]['content_kind'],'webpage_description')
        self.assertIn('Public introduction only.',acquisition['snapshots'][0]['page_text'])
        self.assertNotIn('ignore all rules',acquisition['snapshots'][0]['page_text'])
        raw = self.clients['researcher'].get(acquisition['snapshots'][0]['download_url'])
        self.assertEqual(raw.data,PAGE.encode())
        self.assertIn('attachment',raw.headers['Content-Disposition'])
        self.assertEqual(self.run_worker()['saved'],0)
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],2)

    def test_failed_pages_keep_metadata_then_admin_retries_without_duplicate_or_manual_overwrite(self):
        sid = self.source()
        self.call('/api/sources/'+sid+'/ingestion',{'enabled':True},user='admin',method='PUT')
        with patch.object(SourceSocket,'fail_article',True):
            self.assertEqual(self.run_worker()['failed'],2)
        status = self.clients['admin'].get('/api/ingestion').json['items'][0]
        self.assertIn('2 条',status['last_error'])
        run = status['runs'][0]
        self.assertEqual(run['status'],'partial')
        rid = self.clients['researcher'].get('/api/records').json['items'][0]['id']
        detail = self.clients['researcher'].get('/api/records/'+rid).json
        self.assertEqual(detail['automatic_acquisition']['snapshots'],[])
        self.call('/api/records/'+rid,dict(title='Human corrected',kind='other',abstract='Human abstract',version=detail['version']),method='PUT')
        self.assertEqual(self.call('/api/ingestion/runs/'+run['id']+'/retry',{},user='admin').status_code,200)
        self.assertEqual(self.run_worker()['saved'],2)
        after = self.clients['researcher'].get('/api/records/'+rid).json
        self.assertEqual(after['title'],'Human corrected')
        self.assertEqual(after['abstract'],'Human abstract')
        self.assertEqual(len(after['automatic_acquisition']['snapshots']),1)
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],2)
        self.assertEqual(self.call('/api/ingestion/runs/'+run['id']+'/retry',{}).status_code,403)

    def test_snapshot_history_export_and_new_directory_restore_preserve_original_bytes(self):
        sid = self.source()
        self.call('/api/sources/'+sid+'/ingestion',{'enabled':True},user='admin',method='PUT')
        self.run_worker()
        client = self.clients['researcher']
        rid = client.get('/api/records').json['items'][0]['id']
        history = client.get('/api/history/record/'+rid).json['items'][0]
        self.assertEqual(history['actor_name'],'系统 · 公开来源采集')
        snapshot = client.get('/api/history/'+str(history['id'])).json['snapshot']
        self.assertEqual(json.loads(snapshot['raw_json'])['automatic_acquisition']['snapshots'][0]['bytes'],len(PAGE.encode()))
        with zipfile.ZipFile(io.BytesIO(client.get('/api/export/content').data)) as archive:
            exported = json.loads(archive.read('content.json'))
            record = next(r for r in exported['records'] if r['id']==rid)
            source_snapshot = record['automatic_acquisition']['snapshots'][0]
            self.assertEqual(archive.read(source_snapshot['path']),PAGE.encode())
            self.assertIn('网页说明快照',archive.read(record['path']).decode())
        from pathlib import Path
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        backup = Path(self.temp.name)/'backup.zip'
        with self.call('/api/backup',user='admin') as response:
            backup.write_bytes(response.data)
        directory = restore_backup(backup,Path(self.temp.name)/'restored')
        recovered = create_app(directory,testing=True).test_client()
        csrf = recovered.get('/api/session').json['csrf']
        recovered.post('/api/login',json=dict(username='researcher',password='LocalDemo2026!'),headers={'X-CSRF-Token':csrf})
        detail = recovered.get('/api/records/'+rid).json
        self.assertEqual(recovered.get(detail['automatic_acquisition']['snapshots'][0]['download_url']).data,PAGE.encode())

    def test_unchanged_poll_preserves_record_version_and_human_review(self):
        sid = self.source()
        self.call('/api/sources/'+sid+'/ingestion',{'enabled':True},user='admin',method='PUT')
        self.run_worker()
        rid = self.clients['researcher'].get('/api/records').json['items'][0]['id']
        before = self.clients['researcher'].get('/api/records/'+rid).json
        self.call('/api/sources/'+sid+'/ingestion/run',{},user='admin')
        self.run_worker()
        after = self.clients['researcher'].get('/api/records/'+rid).json
        self.assertEqual(after['version'],before['version'])
        self.assertEqual(len(after['automatic_acquisition']['snapshots']),1)

    def test_parallel_workers_and_restart_after_interrupted_article_are_idempotent(self):
        sid = self.source()
        self.call('/api/sources/'+sid+'/ingestion',{'enabled':True},user='admin',method='PUT')
        # A process death at the external response boundary leaves its leased
        # durable task, rather than changing application data through a backdoor.
        original = SourceSocket.sendall
        calls = []
        def interrupt(sock,data):
            if b'/rss.xml ' not in data:
                calls.append(data)
                if len(calls)==2:
                    raise SystemExit('synthetic process interruption')
            original(sock,data)
        with patch.object(SourceSocket,'sendall',interrupt):
            with self.assertRaises(SystemExit):
                self.run_worker()
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],1)
        self.assertEqual(self.run_worker()['runs'],0)
        self.assertEqual(self.run_worker('2026-10-27T12:03:00+00:00')['saved'],1)
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],2)
        self.call('/api/sources/'+sid+'/ingestion/run',{},user='admin')
        from platform_app.ingestion import run_pending
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]),patch('socket.create_connection',side_effect=lambda *a,**k:SourceSocket(b'')),patch('ssl.SSLContext.wrap_socket',side_effect=lambda sock,**k:sock):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _:run_pending(self.app.config['DATA_DIR']),range(2)))
        self.assertEqual(sum(r['runs'] for r in results),1)
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],2)

    def test_atomic_history_failure_has_no_formal_record_then_retry_and_hidden_duplicate_does_not_leak(self):
        sid = self.source()
        self.call('/api/sources/'+sid+'/ingestion',{'enabled':True},user='admin',method='PUT')
        with closing(sqlite3.connect(self.app.config['DATA_DIR']/'platform.sqlite3')) as db:
            db.execute("CREATE TRIGGER fail_auto_history BEFORE INSERT ON revisions WHEN NEW.target_type='record' BEGIN SELECT RAISE(ABORT,'synthetic disk failure'); END")
            db.commit()
        self.assertEqual(self.run_worker()['failed'],2)
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],0)
        with closing(sqlite3.connect(self.app.config['DATA_DIR']/'platform.sqlite3')) as db:
            db.execute('DROP TRIGGER fail_auto_history')
            db.commit()
        hidden = self.call('/api/records',dict(title='Private secret',kind='other',url='https://liia.lv/en/opinions/synthetic-101',visibility='restricted'),user='colleague').json['id']
        status=self.clients['admin'].get('/api/ingestion').json['items'][0]
        self.call('/api/ingestion/runs/'+status['runs'][0]['id']+'/retry',{},user='admin')
        self.assertEqual(self.run_worker()['blocked'],1)
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],1)
        data = self.clients['researcher'].get('/api/records').get_data(as_text=True)
        self.assertNotIn(hidden,data)
        self.assertNotIn('Private secret',data)

    def test_saved_entry_follows_manual_merge_and_preserves_survivor_fields(self):
        sid = self.source()
        self.call('/api/sources/'+sid+'/ingestion',{'enabled':True},user='admin',method='PUT')
        self.run_worker()
        before,other=self.clients['researcher'].get('/api/records').json['items']
        keep=other['id']
        self.call('/api/records/'+keep,dict(title='Human survivor',kind='other',version=other['version']),method='PUT')
        result=self.call('/api/merge',dict(type='record',keep_id=keep,duplicate_id=before['id'],keep_version=other['version']+1,duplicate_version=before['version'],confirmed=True),user='admin')
        self.assertEqual(result.status_code,200,result.json)
        self.call('/api/sources/'+sid+'/ingestion/run',{},user='admin')
        self.run_worker()
        detail=self.clients['researcher'].get('/api/records/'+keep).json
        self.assertEqual(detail['title'],'Human survivor')
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],1)

    def test_realistic_sidebar_label_and_void_tags_do_not_change_credit_or_page_boundary(self):
        sid=self.source()
        self.call('/api/sources/'+sid+'/ingestion',{'enabled':True},user='admin',method='PUT')
        page='<div class="article"><p>First<br/>Second<img src="/x"/>Third</p></div><p class="author"><span>Author</span><strong><a href="/fellow">Dana Duda</a></strong><a><img src="/portrait"/></a></p><nav>Outside navigation</nav>'
        with patch(__name__+'.PAGE',page):
            self.run_worker()
        rid=self.clients['researcher'].get('/api/records').json['items'][0]['id']
        detail=self.clients['researcher'].get('/api/records/'+rid).json
        self.assertEqual(detail['authors'],'Dana Duda')
        snapshot=detail['automatic_acquisition']['snapshots'][0]
        self.assertEqual(snapshot['page_text'],'First\nSecondThird')
        self.assertNotIn('Outside navigation',snapshot['page_text'])

    def test_invalid_feed_zero_items_and_rule_exclusions_have_distinct_coverage(self):
        sid=self.source()
        path='/api/sources/'+sid+'/ingestion'
        self.call(path,{'enabled':True},user='admin',method='PUT')
        with patch(__name__+'.FEED','not XML'):
            self.assertEqual(self.run_worker()['failed'],1)
        config=self.clients['admin'].get(path).json
        self.assertEqual(config['last_success'],'')
        self.assertEqual(config['runs'][0]['stage'],'feed')
        self.call('/api/ingestion/runs/'+config['runs'][0]['id']+'/retry',{},user='admin')
        with patch(__name__+'.FEED','<rss><channel/></rss>'):
            self.run_worker()
        config=self.clients['admin'].get(path).json
        self.assertTrue(config['last_success'])
        self.assertFalse(config['coverage']['coverage_complete'])
        self.assertIn('不证明来源没有更新',config['coverage']['zero_interpretation'])
        raw=self.clients['admin'].get('/api/ingestion/runs/'+config['runs'][0]['id']+'/rss')
        self.assertEqual(raw.data,b'<rss><channel/></rss>')
        self.assertEqual(self.clients['researcher'].get('/api/ingestion/runs/'+config['runs'][0]['id']+'/rss').status_code,403)
        self.call(path+'/run',{},user='admin')
        with patch(__name__+'.FEED',FEED.replace('Policy briefing','Job vacancy')):
            self.run_worker()
        config=self.clients['admin'].get(path).json
        self.assertEqual(config['runs'][0]['entries'][0]['stage'],'excluded')
        self.assertIn('事务通知',config['runs'][0]['entries'][0]['reason'])
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],1)

    def test_initial_window_does_not_silently_drop_later_discovered_old_article(self):
        sid=self.source()
        self.call('/api/sources/'+sid+'/ingestion',{'enabled':True},user='admin',method='PUT')
        old='<item><title>Already old at activation</title><link>https://liia.lv/en/opinions/old-at-start</link><pubDate>Mon, 01 Jan 2001 12:00:00 +0000</pubDate></item>'
        first=FEED.replace('</channel>',old+'</channel>')
        with patch(__name__+'.FEED',first):self.run_worker()
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],2)
        later=first.replace('</channel>','<item><title>Newly discovered old article</title><link>https://liia.lv/en/opinions/late-old</link><pubDate>Sat, 01 Jan 2000 12:00:00 +0000</pubDate></item></channel>')
        self.call('/api/sources/'+sid+'/ingestion/run',{},user='admin')
        with patch(__name__+'.FEED',later):self.run_worker()
        result=self.clients['researcher'].get('/api/records?q=Newly%20discovered').json
        self.assertEqual(result['total'],1)
        self.assertEqual(result['items'][0]['published_on'],'2000-01-01')
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],3)
