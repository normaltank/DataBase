import tempfile
import unittest
from platform_app.web import create_app

class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='candidates-')
        self.addCleanup(self.temp.cleanup)
        self.client = create_app(self.temp.name, testing=True).test_client()
        self.post('/api/login', {'username':'researcher','password':'LocalDemo2026!'})
    def post(self, path, body):
        token=self.client.get('/api/session').json['csrf']
        r=self.client.post(path,json=body,headers={'X-CSRF-Token':token})
        self.assertLess(r.status_code,300,r.json)
        return r.json
    def test_original_candidates_filter_before_paging_and_save(self):
        for n in range(16):
            self.post('/api/records',dict(title=f'Match note {n}',kind='research_note',author_id='researcher',published_on='2026-01-01'))
        originals=[self.post('/api/records',dict(title=f'Match original {n:02}',kind='report',published_on='2020-01-01'))['id'] for n in range(18)]
        r=self.client.get('/api/record-candidates',query_string={'purpose':'original','q':'Match','size':15,'exclude':originals[0]})
        self.assertEqual(r.status_code,200,r.json)
        self.assertEqual((r.json['total'],len(r.json['items'])),(17,15))
        second=self.client.get('/api/record-candidates',query_string={'purpose':'original','q':'Match','size':15,'exclude':originals[0],'page':2}).json
        self.assertEqual(len(second['items']),2)
        selected=[r.json['items'][0]['id'],second['items'][0]['id']]
        report=self.post('/api/records',dict(title='Selected references',kind='compilation',author_id='researcher',linked_ids=selected))['id']
        self.assertEqual({x['id'] for x in self.client.get('/api/records/'+report).json['linked_records']},set(selected))

    def test_collection_candidates_exclude_members_and_permissions_before_paging(self):
        ids=[self.post('/api/records',dict(title=f'Topic {n:02}',kind='report'))['id'] for n in range(40)]
        self.post('/api/records',dict(title='Topic private',kind='research_note',author_id='researcher',visibility='restricted'))
        topic=self.post('/api/collections',dict(name='Synthetic topic',visibility='shared'))['id']
        for rid in ids[:9]:
            self.post('/api/collections/'+topic+'/items',{'record_id':rid})
        self.post('/api/logout',{})
        self.post('/api/login',{'username':'colleague','password':'LocalDemo2026!'})
        query=dict(purpose='collection',target_collection=topic,q='Topic',size=30,sort='title')
        first=self.client.get('/api/record-candidates',query_string=query).json
        last=self.client.get('/api/record-candidates',query_string={**query,'page':2}).json
        self.assertEqual((first['total'],len(first['items']),len(last['items'])),(31,30,1))
        self.assertEqual({r['id'] for r in first['items']+last['items']},set(ids[9:]))
        chosen=last['items'][0]['id']
        self.post('/api/collections/'+topic+'/items',{'record_id':chosen})
        after=self.client.get('/api/record-candidates',query_string={**query,'page':2}).json
        self.assertEqual((after['total'],after['page'],len(after['items'])),(30,1,30))
        self.assertIn(chosen,{r['id'] for r in self.client.get('/api/collections/'+topic).json['items']})
        zero=self.client.get('/api/record-candidates',query_string={**query,'q':'NoSuchMatch'}).json
        self.assertEqual((zero['total'],zero['page'],zero['items']),(0,1,[]))
