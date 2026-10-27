"""Fixed-source discovery through authenticated HTTP and public socket boundary."""
import unittest
import io
import json
import zipfile
import ssl
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

from tests import test_assisted_intake as base

FEED = '''<rss version="2.0"><channel><title>Synthetic Opinions</title>
<item><title>Policy briefing</title><link>https://liia.lv/en/opinions/synthetic-101</link><guid>one</guid><pubDate>Tue, 27 Oct 2026 00:30:00 +0300</pubDate><description>&lt;p&gt;Series introduction only&lt;/p&gt;</description></item>
<item><title>Broadcast introduction</title><link>https://www.liia.lv/en/opinions/synthetic-102</link><guid>two</guid><pubDate>Mon, 28 Sep 2026 23:30:00 -0300</pubDate><description>.</description></item>
</channel></rss>'''


class DiscoveryTests(unittest.TestCase):
    setUp = base.AssistedIntakeTests.setUp
    call = base.AssistedIntakeTests.call

    def source(self, **values):
        return self.call('/api/sources', dict(name='Synthetic LIIA', kind='think_tank', website='https://liia.lv/en/') | values).json['id']

    def discover(self, sid, xml=FEED, **kwargs):
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), \
             patch('socket.create_connection', side_effect=lambda *a, **k: base.PublicSocket(xml.encode(), content_type='application/xml', **kwargs)), \
             patch('ssl.SSLContext.wrap_socket', side_effect=lambda sock, **kwargs: sock), \
             patch('platform_app.store.now', return_value='2026-10-27T12:00:00+00:00'):
            return self.call('/api/sources/'+sid+'/discovery', {})

    def test_fixed_feed_preview_is_read_only_and_save_keeps_description_separate(self):
        sid = self.source()
        client = self.clients['researcher']
        before = client.get('/api/records').json['total']
        result = self.discover(sid)
        self.assertEqual(result.status_code, 200, result.json)
        preview = result.json
        self.assertEqual(preview['window'], {'start':'2026-09-28', 'end':'2026-10-27'})
        self.assertEqual(client.get('/api/records').json['total'], before)
        first, second = preview['items']
        self.assertEqual(first['fields'], dict(kind='other', title='Policy briefing', url='https://liia.lv/en/opinions/synthetic-101', published_on='2026-10-27', source_id=sid))
        self.assertEqual(first['description'], 'Series introduction only')
        self.assertEqual(second['description'], '')
        self.assertEqual(second['fields']['published_on'], '2026-09-28')
        saved = self.call('/api/records', {**first['fields'], 'title':'Human title', 'abstract':'Human checked summary', 'discovery_token':first['token']})
        self.assertEqual(saved.status_code, 201, saved.json)
        detail = client.get('/api/records/'+saved.json['id']).json
        evidence = detail['discovery_evidence'][0]
        self.assertEqual(evidence['raw']['description'], '<p>Series introduction only</p>')
        self.assertEqual(evidence['raw']['pubDate'], 'Tue, 27 Oct 2026 00:30:00 +0300')
        self.assertEqual(evidence['saved_fields']['abstract'], 'Human checked summary')
        self.assertEqual(evidence['fields']['title'], 'Policy briefing')
        self.assertEqual(detail['status'], 'pending')

    def test_window_exclusions_order_guid_and_untrusted_links_are_reported(self):
        sid = self.source()
        additions = '''
<item><title>Old</title><link>https://liia.lv/en/opinions/old</link><pubDate>Sun, 27 Sep 2026 23:59:00 -0300</pubDate></item>
<item><title>Tomorrow</title><link>https://liia.lv/en/opinions/future</link><pubDate>Wed, 28 Oct 2026 00:00:00 +1300</pubDate></item>
<item><title>No date</title><link>https://liia.lv/en/opinions/missing</link></item>
<item><title>Bad date</title><pubDate>yesterday</pubDate></item>
<item><title>No timezone</title><pubDate>Tue, 27 Oct 2026 12:00:00</pubDate></item>
<item><title>Another GUID</title><link>https://liia.lv/en/opinions/third</link><guid>one</guid><pubDate>Mon, 26 Oct 2026 12:00:00 +0000</pubDate></item>
<item><title>Duplicate URL</title><link>https://www.liia.lv/en/opinions/synthetic-101#fragment</link><pubDate>Mon, 26 Oct 2026 12:00:00 +0000</pubDate></item>
'''
        for bad in ['http://liia.lv/en/opinions/a', 'https://liia.lv.evil.test/en/opinions/a',
                    'https://liia.lv/en/opinions/../secret', 'https://liia.lv/en/opinions/a?url=http://localhost',
                    'https://liia.lv/en/opinions/a.pdf', 'https://liia.lv:444/en/opinions/a', 'javascript:alert(1)']:
            additions += '<item><title>Untrusted</title><link>'+bad+'</link><pubDate>Mon, 26 Oct 2026 12:00:00 +0000</pubDate></item>'
        result = self.discover(sid, FEED.replace('</channel>', additions+'</channel>'))
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual([i['fields']['title'] for i in result.json['items']], ['Policy briefing','Broadcast introduction','Another GUID'])
        self.assertEqual(result.json['counts'], dict(missing_date=1, invalid_date=2, outside_window=1, future=1, invalid_item=7, duplicate_url=1, duplicate_guid=1))
        self.assertEqual(result.json['earliest'], '2026-09-27')
        self.assertIn('可能遗漏', ''.join(result.json['warnings']))

    def test_duplicate_preview_aliases_race_and_private_metadata(self):
        sid = self.source()
        item = self.discover(sid).json['items'][0]
        hidden = self.call('/api/records', dict(title='Hidden title never disclosed', kind='other', url='https://www.liia.lv/en/opinions/synthetic-101#section', visibility='restricted'), user='colleague').json['id']
        again = self.discover(sid).json['items'][0]
        self.assertTrue(again['blocked'])
        self.assertEqual(again['duplicates'], [])
        status = self.call('/api/discovery/status', {'token':item['token']})
        self.assertTrue(status.json['blocked'])
        save = self.call('/api/records', {**item['fields'], 'discovery_token':item['token']})
        self.assertEqual(save.status_code, 409, save.json)
        for response in [status, save]:
            self.assertNotIn(hidden, response.get_data(as_text=True))
            self.assertNotIn('Hidden title', response.get_data(as_text=True))

    def test_saved_entry_is_idempotent_after_edit_repreview_and_merge(self):
        sid = self.source()
        item = self.discover(sid).json['items'][0]
        values = {**item['fields'], 'discovery_token':item['token']}
        rid = self.call('/api/records', values).json['id']
        self.assertEqual(self.call('/api/records', values | {'url':'','title':'Changed retry'}).status_code, 409)
        again = self.discover(sid).json['items'][0]
        self.assertEqual(again['saved'], rid)
        survivor = self.call('/api/records', dict(title='Manually retained',kind='other')).json['id']
        merged = self.call('/api/merge', dict(type='record',keep_id=survivor,duplicate_id=rid,keep_version=1,duplicate_version=1,confirmed=True),user='admin')
        self.assertEqual(merged.status_code, 200, merged.json)
        self.assertEqual(self.call('/api/records', values | {'url':''}).status_code, 409)
        self.assertEqual(self.call('/api/discovery/status', {'token':again['token']}).json, dict(saved=True,id=survivor,title='Manually retained'))

    def test_fixed_source_parameters_authentication_csrf_and_signature(self):
        sid = self.source()
        other = self.source(name='Other synthetic source',website='https://example.org/')
        self.assertTrue(self.clients['researcher'].get('/api/sources/'+sid).json['discovery_supported'])
        self.assertFalse(self.clients['researcher'].get('/api/sources/'+other).json.get('discovery_supported', False))
        for source in [other, 'unknown']:
            self.assertEqual(self.call('/api/sources/'+source+'/discovery', {}).status_code, 422)
        self.assertEqual(self.call('/api/sources/'+sid+'/discovery', {'url':'https://evil.test'}).status_code, 400)
        self.assertEqual(self.app.test_client().post('/api/sources/'+sid+'/discovery').status_code, 401)
        self.assertEqual(self.clients['researcher'].post('/api/sources/'+sid+'/discovery').status_code, 403)
        item = self.discover(sid).json['items'][0]
        values = {**item['fields'], 'discovery_token':item['token']}
        self.assertEqual(self.call('/api/records', values | {'discovery_token':item['token']+'x'}).status_code, 400)
        self.assertEqual(self.call('/api/records', values, user='colleague').status_code, 403)
        self.assertEqual(self.call('/api/discovery/status', {'token':item['token']}, user='colleague').status_code, 403)
        for kind in ['research_report','compilation','research_note','directory_translation']:
            self.assertEqual(self.call('/api/records', values | {'kind':kind,'coverage':'2026'}).status_code, 400)
        self.assertEqual(self.call('/api/members/researcher', {'active':False}, user='admin', method='PUT').status_code, 200)
        self.assertEqual(self.discover(sid).status_code, 401)
        self.assertEqual(self.call('/api/records', values).status_code, 401)

    def test_xml_bounds_failures_and_article_mime_boundary(self):
        sid = self.source()
        for xml in ['<rss>', '<!DOCTYPE rss><rss><channel/></rss>', '<!DOCTYPE rss [<!ENTITY a "expansion">]><rss><channel/></rss>',
                    '<rss><channel>'+('<item/>'*101)+'</channel></rss>', '<feed/>']:
            with self.subTest(xml=xml[:40]):
                self.assertEqual(self.discover(sid, xml).status_code, 422)
        for status in ['403 Forbidden','406 Not Acceptable']:
            result = self.discover(sid, status=status)
            self.assertEqual(result.status_code, 422)
            self.assertIn(status[:3], result.json['error'])
        # Existing single-article reader must still reject XML.
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]), patch('socket.create_connection',return_value=base.PublicSocket(FEED.encode(),'application/xml')), patch('ssl.SSLContext.wrap_socket',side_effect=lambda sock,**k:sock):
            self.assertEqual(self.call('/api/intake/preview', {'input':'https://liia.lv/en/opinions/synthetic-101'}).status_code, 422)

    def test_public_network_dns_peer_redirect_size_deadline_and_shared_capacity(self):
        from tests.test_intake_deadline import SlowSocket
        sid = self.source()
        path = '/api/sources/'+sid+'/discovery'
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            self.assertEqual(self.call(path).status_code,422)
        class WrongPeer(base.PublicSocket):
            def getpeername(self):
                return ('127.0.0.1',443)
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]),patch('socket.create_connection',return_value=WrongPeer(FEED.encode(),'application/xml')):
            self.assertEqual(self.call(path).status_code,422)
        for target in ['http://127.0.0.1/private','https://evil.test/en/opinions/rss.xml','https://liia.lv:444/en/opinions/rss.xml']:
            with self.subTest(redirect=target):
                self.assertEqual(self.discover(sid,status='302 Found',headers='Location: '+target+'\r\n').status_code,422)
        self.assertEqual(self.discover(sid,'x'*(1024*1024+1)).status_code,422)
        context=ssl.create_default_context()
        with patch('platform_app.intake.MAX_SECONDS',.10),patch('ssl.create_default_context',return_value=context),patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]),patch('socket.create_connection',side_effect=lambda *a,**k:SlowSocket()),patch('ssl.SSLContext.wrap_socket',side_effect=lambda sock,**k:sock):
            for _ in range(5):
                started=time.monotonic()
                response=self.call(path)
                self.assertEqual(response.status_code,422,response.json)
                self.assertIn('超时',response.json['error'])
                self.assertLess(time.monotonic()-started,.5)
        entered=threading.Barrier(5);release=threading.Event();responses=[]
        class WaitingSocket(base.PublicSocket):
            def makefile(self,*a,**k):
                entered.wait(5);release.wait(5)
                return super().makefile(*a,**k)
        def run():
            client=self.app.test_client()
            csrf=client.get('/api/session').json['csrf']
            csrf=client.post('/api/login',json=dict(username='researcher',password='LocalDemo2026!'),headers={'X-CSRF-Token':csrf}).json['csrf']
            responses.append(client.post(path,json={},headers={'X-CSRF-Token':csrf}).status_code)
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]),patch('socket.create_connection',side_effect=lambda *a,**k:WaitingSocket(FEED.encode(),'application/xml')),patch('ssl.SSLContext.wrap_socket',side_effect=lambda sock,**k:sock):
            workers=[threading.Thread(target=run) for _ in range(4)]
            for worker in workers:worker.start()
            entered.wait(5)
            try:
                self.assertEqual(self.call(path).status_code,429)
                self.assertEqual(self.call('/api/intake/preview',{'input':'https://example.org/article'}).status_code,429)
            finally:
                release.set()
                for worker in workers:worker.join()
        self.assertEqual(responses,[200]*4)

    def test_history_export_backup_and_late_validation_failure_preserve_evidence(self):
        from platform_app.maintenance import restore_backup
        from platform_app.web import create_app
        sid = self.source()
        item = self.discover(sid).json['items'][0]
        values = {**item['fields'], 'discovery_token':item['token']}
        before = self.clients['researcher'].get('/api/records').json['total']
        # Byline evidence validation is deliberately after the record INSERT.
        bad = self.call('/api/records',values | {'intake_bylines':[{'raw_name':'Unconfirmed','status':'confirmed','target_type':'person','target_id':'missing'}]})
        self.assertEqual(bad.status_code, 400, bad.json)
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'], before)
        # Inject a storage failure on the final history write, then observe only
        # the public record list and retry behavior. This is a temporary DB.
        with closing(sqlite3.connect(Path(self.temp.name)/'data'/'platform.sqlite3')) as db:
            db.execute("CREATE TRIGGER fail_discovery_history BEFORE INSERT ON revisions WHEN NEW.target_type='record' BEGIN SELECT RAISE(ABORT,'synthetic final write'); END")
            db.commit()
        self.assertEqual(self.call('/api/records',values).status_code,409)
        self.assertEqual(self.clients['researcher'].get('/api/records').json['total'],before)
        with closing(sqlite3.connect(Path(self.temp.name)/'data'/'platform.sqlite3')) as db:
            db.execute('DROP TRIGGER fail_discovery_history')
            db.commit()
        rid = self.call('/api/records', values).json['id']
        client = self.clients['researcher']
        detail = client.get('/api/records/'+rid).json
        history = client.get('/api/history/record/'+rid).json['items'][0]
        snapshot = client.get('/api/history/'+str(history['id'])).json['snapshot']
        self.assertEqual(json.loads(snapshot['raw_json'])['discovery_evidence'], detail['discovery_evidence'])
        exported = client.get('/api/export/content')
        export_path=Path(self.temp.name)/'content.zip'
        export_path.write_bytes(exported.data)
        checked=subprocess.run([sys.executable,'scripts/verify_content_export.py',str(export_path)],capture_output=True,text=True)
        self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)
        with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
            content = json.loads(archive.read('content.json'))
            actual = next(r for r in content['records'] if r['id']==rid)
            self.assertEqual(actual['discovery_evidence'], detail['discovery_evidence'])
            self.assertTrue(any('来源发现依据' in archive.read(n).decode() for n in archive.namelist() if n.startswith('records/') and n.endswith('.html')))
        path = Path(self.temp.name)/'backup.zip'
        with self.call('/api/backup',user='admin') as backup:
            path.write_bytes(backup.data)
        directory = restore_backup(path,Path(self.temp.name)/'new-directory')
        recovered = create_app(directory,testing=True).test_client()
        csrf=recovered.get('/api/session').json['csrf']
        self.assertEqual(recovered.post('/api/login',json=dict(username='researcher',password='LocalDemo2026!'),headers={'X-CSRF-Token':csrf}).status_code,200)
        self.assertEqual(recovered.get('/api/records/'+rid).json['discovery_evidence'],detail['discovery_evidence'])


if __name__ == '__main__':
    unittest.main()
