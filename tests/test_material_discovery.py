"""Material discovery at the authenticated, complete-query HTTP boundary."""
import csv
import io
import tempfile
import unittest
from pathlib import Path
from platform_app.web import create_app


class MaterialDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='material-discovery-')
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Path(self.temp.name)/'data', testing=True, embedded_worker=False)
        self.client = self.app.test_client()
        self.login()

    def call(self, path, values=None, method='POST', status=200):
        token = self.client.get('/api/session').json['csrf']
        result = self.client.open(path, method=method, json=values or {}, headers={'X-CSRF-Token':token})
        self.assertEqual(result.status_code, status, result.json)
        return result.json

    def login(self, name='researcher'):
        self.call('/api/login', {'username':name,'password':'LocalDemo2026!'})

    def record(self, **values):
        return self.call('/api/records', {'title':'合成发现样本','kind':'report', **values}, status=201)['id']

    def get(self, query=None):
        result = self.client.get('/api/material-discovery', query_string=query or {})
        self.assertEqual(result.status_code, 200, result.json)
        return result.json

    def test_complete_query_country_aliases_multiple_unknown_and_historical_values(self):
        for i in range(23):
            self.record(title=f'目标 {i}', countries='Latvia|拉脱维亚|Germany', published_on='2020')
        self.record(title='目标 unknown')
        self.record(title='目标 history', countries='Yugoslavia|LostTerritory', published_on='2021-02')
        self.record(title='其他', countries='Japan')
        self.record(title='目标 secret', countries='Japan', visibility='restricted')
        self.login('colleague')
        query={'q':'目标','size':1,'page':2}
        result=self.get(query)
        self.assertEqual(result['total'],25)
        self.assertEqual({r['value']:r['count'] for r in result['countries']},
                         {'LV':23,'DE':23,'__unknown__':1,'historic:yugoslavia':1,'lostterritory':1})
        self.assertEqual(self.client.get('/api/records',query_string=query).json['total'],25)
        rows=list(csv.DictReader(io.StringIO(self.client.get('/api/export',query_string=query).data.decode('utf-8-sig'))))
        self.assertEqual(len(rows),25)
        filtered=self.get({'q':'目标','country':'LATVIA'})
        self.assertEqual(filtered['total'],23)
        self.assertEqual({r['value'] for r in filtered['countries']},{'LV','DE'})

    def test_date_roles_precision_unknown_and_existing_year_filters(self):
        self.record(published_on='1999')
        self.record(published_on='1999-03')
        self.record(published_on='2000-03-04')
        self.record()
        result=self.get()
        self.assertEqual(result['dates']['published'], {
            'years':[{'year':'2000','count':1},{'year':'1999','count':2}],
            'unknown':1,'precision':{'year':1,'month':1,'day':1}})
        for role in ['collected','updated']:
            self.assertEqual(sum(y['count'] for y in result['dates'][role]['years']),4)
            self.assertEqual(result['dates'][role]['unknown'],0)
        year=self.get({'from':'1999-01-01','to':'1999-12-31'})
        self.assertEqual(year['total'],2)
        self.assertEqual(year['dates']['published']['precision'],{'year':1,'month':1,'day':0})
        unknown=self.get({'date_unknown':'1'})
        self.assertEqual(unknown['total'],1)
        self.assertEqual(unknown['dates']['published']['unknown'],1)

    def test_saved_scope_frozen_membership_late_edits_and_live_revoke(self):
        first=self.record(title='固定查询 A', countries='Latvia', published_on='2010')
        later=self.record(title='其他 B', countries='Germany', published_on='2011')
        hidden=self.record(title='固定查询 hidden', countries='Japan', visibility='restricted')
        self.login('colleague')
        saved=self.call('/api/saved-searches', {'name':'合成查询','conditions':{'q':'固定查询'}},status=201)
        batch=self.call('/api/reading-batches')
        query={'saved_search':saved['id'],'batch':batch['id'],'batch_scope':'all','q':'其他'}
        shown=self.client.get('/api/records',query_string=query).json
        self.assertEqual([r['id'] for r in shown['items']],[first])
        self.assertEqual(self.get(query)['reading_confirmation'],shown['reading_confirmation'])
        self.login()
        self.call('/api/records/'+later,{'version':1,'title':'固定查询 B'},method='PUT')
        self.record(title='固定查询 late',countries='Japan')
        self.login('colleague')
        self.assertEqual(self.get(query)['total'],1)
        self.assertEqual(self.get(query)['countries'],[{'value':'LV','label':'拉脱维亚','count':1}])
        self.login()
        self.call('/api/records/'+first,{'version':1,'visibility':'restricted'},method='PUT')
        self.login('colleague')
        self.assertEqual(self.get(query)['total'],0)
        self.assertEqual(self.get(query)['countries'],[])
        self.assertEqual(self.client.get('/api/export',query_string=query).data.decode('utf-8-sig').count(first),0)
        self.call('/api/logout')
        self.assertEqual(self.client.get('/api/material-discovery').status_code,401)

