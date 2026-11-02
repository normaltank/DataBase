"""Country identities at authenticated HTTP list/export and archive boundaries."""
import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from platform_app.web import create_app


class CountryFilterTests(unittest.TestCase):
    def setUp(self):
        evidence = Path(tempfile.gettempdir())/'database-archive92-country-build-20261102'
        evidence.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='http-', dir=evidence)
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Path(self.temp.name)/'data', testing=True)
        self.clients = {}
        for user in ['researcher', 'colleague', 'admin']:
            client = self.app.test_client()
            csrf = client.get('/api/session').json['csrf']
            response = client.post('/api/login', json={'username':user, 'password':'LocalDemo2026!'}, headers={'X-CSRF-Token':csrf})
            self.assertEqual(response.status_code, 200)
            self.clients[user] = client

    def call(self, path, data=None, method='POST', user='researcher', status=200):
        client = self.clients[user]
        response = client.open(path, method=method, json=data or {}, headers={'X-CSRF-Token':client.get('/api/session').json['csrf']})
        self.assertEqual(response.status_code, status, response.json)
        return response.json

    def get(self, path, query=None, user='researcher'):
        response = self.clients[user].get(path, query_string=query or {})
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def record(self, **extra):
        return self.call('/api/records', {'title':'合成筛选样本', 'kind':'report', **extra}, status=201)['id']

    def source(self, country, **extra):
        count = self.get('/api/sources')['total']
        return self.call('/api/sources', {'name':f'合成机构 {count}', 'kind':'institution', 'country':country,
                         'country_evidence':'合成所在地依据', **extra}, status=201)['id']

    def test_record_alias_identity_count_exports_saved_search_and_raw_values(self):
        ids = [self.record(title=f'Alias {i}', countries=value) for i,value in enumerate(['Latvia', '拉脱维亚', 'LATVIA', 'Latvia|拉脱维亚', ''])]
        expected = set(ids[:4])
        for index,value in enumerate(['Latvia', 'LATVIA', '拉脱维亚', 'latvia']):
            query = {'country':value, 'size':100}
            result = self.get('/api/records', query)
            self.assertEqual({r['id'] for r in result['items']}, expected)
            self.assertEqual(result['facets']['country'], [{'value':'LV', 'label':'拉脱维亚', 'count':4}])
            exported = self.clients['researcher'].get('/api/export', query_string=query)
            rows = list(csv.DictReader(io.StringIO(exported.data.decode('utf-8-sig'))))
            self.assertEqual({r['稳定编号'] for r in rows}, expected)
            self.assertEqual({r['研究对象'] for r in rows}, {'Latvia','拉脱维亚','LATVIA','Latvia|拉脱维亚'})
            content = self.clients['researcher'].get('/api/export/content', query_string=query)
            with zipfile.ZipFile(io.BytesIO(content.data)) as archive:
                package = json.loads(archive.read('content.json'))
                self.assertEqual(set(package['selected_ids']), expected)
                self.assertEqual({r['countries'] for r in package['records']}, {'Latvia','拉脱维亚','LATVIA','Latvia|拉脱维亚'})
            client = self.clients['researcher']
            selected = client.post('/api/library/bulk/export', json={'ids':[r['id'] for r in result['items'] if r['id'] in {ids[0],ids[3]}]},
                                   headers={'X-CSRF-Token':client.get('/api/session').json['csrf']})
            self.assertEqual(selected.status_code,200)
            self.assertEqual({r['稳定编号'] for r in csv.DictReader(io.StringIO(selected.data.decode('utf-8-sig')))}, {ids[0],ids[3]})
            saved = self.call('/api/saved-searches', {'name':f'旧检索 {index}', 'conditions':{'country':value}}, status=201)
            self.assertEqual(self.get('/api/saved-searches/'+saved['id'])['conditions']['country'],value)
            self.assertEqual({r['id'] for r in self.get('/api/records', {'saved_search':saved['id']})['items']}, expected)
        self.assertEqual([r['id'] for r in self.get('/api/records', {'country':'__unknown__'})['items']], [ids[4]])
        self.assertEqual(self.get('/api/records', {'country':'UnlistedPlace'})['total'], 0)

    def test_source_country_combines_type_and_host_international_without_publisher_leak(self):
        latvia = self.source('Latvia|拉脱维亚', institution_types=['think_tank'])
        germany = self.source('Germany', institution_types=['think_tank'])
        unknown = self.source('', institution_types=['think_tank'])
        journal = self.source('', kind='journal', host_id=latvia, publisher_id=germany, host_evidence='合成主办依据', international_status='yes', international_evidence='合成国际定位')
        for alias in ['Latvia','拉脱维亚','latvia','LV']:
            result = self.get('/api/sources', {'group':'institution','institution_type':'think_tank','country':alias})
            self.assertEqual([r['id'] for r in result['items']], [latvia])
            self.assertEqual(result['facets']['country'], [{'value':'LV','label':'拉脱维亚','count':1}])
            self.assertEqual([r['id'] for r in self.get('/api/sources', {'group':'journal','country':alias,'international':'yes'})['items']], [journal])
        self.assertEqual(self.get('/api/sources', {'group':'journal','country':'Germany'})['total'], 0)
        self.assertEqual([r['id'] for r in self.get('/api/sources', {'group':'institution','country':'__pending__'})['items']], [unknown])
        record = self.record(source_id=latvia)
        for alias in ['Latvia','拉脱维亚','latvia']:
            self.assertEqual([r['id'] for r in self.get('/api/records', {'source_country':alias})['items']], [record])
        self.assertEqual(self.get('/api/sources', {'country':'NoSuchPlace'})['total'], 0)

    def person(self, name='合成作者'):
        return self.call('/api/people', {'name':name, 'change_note':'合成人物主页'}, status=201)['id']

    def employ(self, person, items):
        current = self.get(f'/api/people/{person}/employments')
        return self.call(f'/api/people/{person}/employments', {'version':current['version'], 'items':items,
                         'change_note':'核对合成履历'}, method='PUT')['items']

    def bylines(self, record, people, status='confirmed'):
        current = self.get(f'/api/records/{record}/bylines')
        return self.call(f'/api/records/{record}/bylines', {'version':current['version'], 'record_version':current['record_version'],
                         'change_note':'合成署名依据', 'items':[{'raw_name':'合成作者','target_type':'person','target_id':person,
                         'status':status,'evidence':'合成人物主页'} for person in people]}, method='PUT')['items']

    def test_people_two_country_dimensions_and_complete_works_before_pagination(self):
        writer, empty = self.person('Example Writer'), self.person('Example Empty')
        latvia, germany = self.source('LATVIA|拉脱维亚'), self.source('Germany')
        self.employ(writer, [{'institution_id':latvia,'role':'研究员','start_date':'1990','end_date':'2000','evidence':'合成历史履历'},
                             {'institution_id':germany,'role':'研究员','evidence':'合成日期未知履历'}])
        for i in range(21):
            self.bylines(self.record(title=f'Work {i:02}', countries='Japan' if i==0 else 'Latvia'), [writer,writer])
        result = self.get('/api/people', {'employment_country':'拉脱维亚','subject_country':'Japan','q':'Example','page_size':1})
        self.assertEqual([r['id'] for r in result['items']], [writer])
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['facets']['employment_country'], [{'value':'DE','label':'德国','count':1},{'value':'LV','label':'拉脱维亚','count':1}])
        self.assertEqual(result['facets']['subject_country'], [{'value':'LV','label':'拉脱维亚','count':1},{'value':'JP','label':'日本','count':1}])
        self.assertEqual(self.get('/api/people', {'employment_country':'Germany|Never','subject_country':'Japan|Never'})['total'], 1)
        self.assertEqual([r['id'] for r in self.get('/api/people', {'employment_country':'__unknown__'})['items']], [empty])
        self.assertEqual(self.get('/api/people', {'employment_country':'Never'})['total'], 0)

    def test_frozen_country_membership_survives_alias_later_edits_and_backup(self):
        first, later = self.record(countries='Latvia'), self.record(countries='Germany')
        batch = self.call('/api/reading-batches')
        query = {'batch':batch['id'], 'batch_scope':'all', 'country':'Latvia'}
        shown = self.get('/api/records', query)
        self.assertEqual([r['id'] for r in shown['items']], [first])
        self.call('/api/records/'+later, {'version':1,'countries':'拉脱维亚'}, method='PUT')
        alias = self.get('/api/records', {**query, 'country':'拉脱维亚'})
        self.assertEqual([r['id'] for r in alias['items']], [first])
        self.assertEqual(alias['reading_confirmation'], shown['reading_confirmation'])
        from platform_app.maintenance import restore_backup
        archive = Path(self.temp.name)/'backup.zip'
        client = self.clients['admin']
        response = client.post('/api/backup', json={}, headers={'X-CSRF-Token':client.get('/api/session').json['csrf']})
        self.assertEqual(response.status_code, 200)
        archive.write_bytes(response.data)
        response.close()
        restored = restore_backup(archive, Path(self.temp.name)/'restored')
        client = create_app(restored, testing=True).test_client()
        csrf = client.get('/api/session').json['csrf']
        client.post('/api/login', json={'username':'researcher','password':'LocalDemo2026!'}, headers={'X-CSRF-Token':csrf})
        again = client.get('/api/records', query_string={**query,'country':'LV'}).json
        self.assertEqual([r['id'] for r in again['items']], [first])
        self.assertEqual(again['reading_confirmation'], shown['reading_confirmation'])

    def test_unknown_spelling_regions_historical_terms_and_options_remain_independent(self):
        values = ['Yugoslavia','Socialist Republic of Macedonia','North Macedonia','Arctic','Asia','Western Balkans','EU','Serbia','LostTerritory']
        ids = [self.record(countries=value) for value in values]
        for value,rid in zip(values,ids):
            self.assertEqual([r['id'] for r in self.get('/api/records', {'country':value})['items']], [rid])
        person = self.person()
        self.bylines(ids[-1], [person])
        result = self.get('/api/people', {'subject_country':'LostTerritory'})
        self.assertEqual(result['facets']['subject_country'], [{'value':'lostterritory','label':'LostTerritory','count':1}])
        selected = self.get('/api/records', {'country':'North Macedonia'})
        self.assertEqual(selected['facets']['country'], [{'value':'MK','label':'北马其顿','count':1}])
        self.assertIn({'value':'RS','label':'塞尔维亚','count':1}, selected['facet_options']['country'])

    def test_people_private_origin_pending_removed_and_history_do_not_leak(self):
        person = self.person()
        source = self.source('Germany')
        employment = self.employ(person, [{'institution_id':source,'role':'研究员','evidence':'合成履历'}])
        self.employ(person, [])
        public = self.record(countries='Latvia', visibility='restricted')
        private = self.record(countries='Japan', visibility='restricted')
        pending = self.record(countries='France')
        removed = self.record(countries='Germany')
        self.bylines(private, [person])
        self.bylines(pending, [person], status='pending')
        self.bylines(removed, [person])
        self.bylines(removed, [])
        preview = self.call('/api/merge/preview', {'type':'record','keep_id':public,'duplicate_id':private}, user='admin')
        self.call('/api/merge', {'type':'record','keep_id':public,'duplicate_id':private,'keep_version':preview['keep']['version'],
                              'duplicate_version':preview['duplicate']['version'],'confirmed':True}, user='admin')
        current = self.get('/api/records/'+public)
        self.call('/api/records/'+public, {'version':current['version'],'visibility':'shared','sharing_confirmed':True}, method='PUT')
        for query in [{'subject_country':'Latvia'},{'subject_country':'Japan'},{'subject_country':'France'},{'subject_country':'Germany'},{'employment_country':'Germany'}]:
            self.assertEqual(self.get('/api/people',query,user='colleague')['total'], 0)
        self.assertEqual(self.get('/api/people',{'subject_country':'Latvia'})['total'], 1)
        self.assertEqual(self.get('/api/people',{'subject_country':'Japan'})['total'], 0)
        self.assertEqual(self.get('/api/people',{'subject_country':'__unknown__'},user='colleague')['total'], 1)

    def test_people_old_person_and_institution_ids_and_pages_count_current_people_once(self):
        keep, old = self.person('Current Person'), self.person('Old Person')
        source, old_source = self.source('Latvia'), self.source('LATVIA')
        self.employ(old, [{'institution_id':old_source,'role':'研究员','evidence':'合成履历'}])
        self.bylines(self.record(countries='Latvia|拉脱维亚'), [old,old])
        preview = self.call('/api/people/merge-preview', {'keep_id':keep,'duplicate_id':old})
        self.call('/api/people/merge', {'preview_id':preview['preview_id'],'idempotency_key':'country-merge','confirmed':True,
                  'evidence':'合成身份同一依据','choices':{'name':'keep','original_name':'keep','chinese_name':'keep','introduction':'keep','avatar':'keep'}})
        preview = self.call('/api/merge/preview', {'type':'source','keep_id':source,'duplicate_id':old_source}, user='admin')
        self.call('/api/merge', {'type':'source','keep_id':source,'duplicate_id':old_source,'keep_version':preview['keep']['version'],
                              'duplicate_version':preview['duplicate']['version'],'confirmed':True}, user='admin')
        for i in range(25):
            pid = self.person(f'Extra Person {i:02}')
            self.employ(pid,[{'institution_id':source,'role':'研究员','evidence':'合成履历'}])
        query = {'employment_country':'Latvia','subject_country':'Latvia','q':old}
        result = self.get('/api/people',query)
        self.assertEqual([r['id'] for r in result['items']], [keep])
        self.assertEqual(result['facets']['employment_country'], [{'value':'LV','label':'拉脱维亚','count':1}])
        first = self.get('/api/people',{'employment_country':'Latvia','page_size':24})
        second = self.get('/api/people',{'employment_country':'拉脱维亚','page_size':24,'page':2})
        self.assertEqual(first['total'], 26)
        self.assertEqual(second['total'], 26)
        self.assertEqual(len(first['items']), 24)
        self.assertEqual(len(second['items']), 2)
        self.assertEqual(len({r['id'] for r in first['items']+second['items']}),26)
        self.assertEqual(second['facets']['employment_country'], [{'value':'LV','label':'拉脱维亚','count':26}])

    def test_people_subject_countries_use_effective_machine_fallback_and_human_priority(self):
        from unittest.mock import patch, MagicMock
        from tests.test_ingestion import IngestionTests
        from tests.synthetic_ai import ENV
        from platform_app.automatic_processing import run_pending
        clock = patch('platform_app.store.now',return_value='2026-10-27T12:00:00+00:00')
        clock.start()
        self.addCleanup(clock.stop)
        source = self.source('',name='Synthetic LIIA',kind='think_tank',website='https://liia.lv/en/')
        self.call('/api/sources/'+source+'/ingestion', {'enabled':True}, user='admin', method='PUT')
        IngestionTests.run_worker(self)
        self.call('/api/admin/ai/config', {'cap':'1','currency':'USD'}, user='admin')
        record = self.get('/api/records')['items'][0]
        person = self.person()
        self.bylines(record['id'], [person])

        def respond(request, **kwargs):
            prompt = json.loads(request.data)
            material = json.loads(prompt['messages'][1]['content'])
            output = {'countries':[{'value':'Latvia','field':'title','quote':material['title'],'certainty':'supported'}],
                      'topics':[],'type':None} if 'Classify' in prompt['messages'][0]['content'] else {'title':'合成译题','abstract':''}
            response = MagicMock()
            response.__enter__.return_value = response
            response.geturl.return_value = request.full_url
            response.read.return_value = json.dumps({'model':'deepseek-flash','usage':{'prompt_tokens':23,'completion_tokens':7,'total_tokens':30},
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]}).encode()
            return response

        with patch.dict('os.environ',{**ENV,'DEEPSEEK_API_KEY':'synthetic-only'}), patch('urllib.request.OpenerDirector.open',side_effect=respond):
            run_pending(self.app.config['DATA_DIR'],limit=10)
        self.assertEqual(self.get('/api/people', {'subject_country':'拉脱维亚'})['total'],1)
        current = self.get('/api/records/'+record['id'])
        self.call('/api/records/'+record['id'], {'version':current['version'],'countries':'Germany'}, method='PUT')
        self.assertEqual(self.get('/api/people', {'subject_country':'Latvia'})['total'],0)
        self.assertEqual(self.get('/api/people', {'subject_country':'德国'})['total'],1)
        current = self.get('/api/records/'+record['id'])
        self.call('/api/records/'+record['id'], {'version':current['version'],'countries':'','title':'Changed public title'}, method='PUT')
        self.assertEqual(self.get('/api/people', {'subject_country':'Latvia'})['total'],1)
        self.call('/api/sources/'+source+'/ingestion', {'enabled':False}, user='admin', method='PUT')
        self.assertEqual(self.get('/api/people', {'subject_country':'Latvia'})['total'],0)


if __name__ == '__main__':
    unittest.main()
