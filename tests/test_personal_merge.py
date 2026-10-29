"""Personal merge discovery and execution retain author ACL through public HTTP."""
import unittest
from contextlib import closing

from tests import test_workflow as workflow
from platform_app.store import connect


class PersonalMergeTests(unittest.TestCase):
    setUp = workflow.WorkflowTests.setUp
    login = workflow.WorkflowTests.login
    call = workflow.WorkflowTests.call

    def pair(self, kind='compilation', user='researcher', **extra):
        ids=[]
        for _ in range(2):
            result=self.call('/api/records', {'kind':kind, 'title':'合成重复成果', 'visibility':'shared',
                'sharing_confirmed':True, **extra}, user=user)
            self.assertEqual(result.status_code,201,result.json)
            ids.append(result.json['id'])
        return ids

    def test_personal_candidates_and_merges_follow_author_and_editor_authorization(self):
        own=self.pair()
        granted=self.pair('research_report',editors=['colleague'])
        public=self.pair('report')
        other=self.pair(user='colleague')
        for actor, allowed, blocked in [('researcher',own+granted,public+other), ('colleague',granted+other,public+own), ('admin',[],own+granted+public+other)]:
            with self.subTest(actor=actor):
                listing=self.clients[actor].get('/api/records?kind=compilation|research_report&editable=1&size=100').json
                self.assertEqual({r['id'] for r in listing['items']},set(allowed))
                duplicate=self.clients[actor].get('/api/duplicates?type=record&scope=personal').json
                found={r[side]['id'] for r in duplicate['items'] for side in ['keep','duplicate']}
                self.assertTrue(found.issubset(allowed),found)
                self.assertFalse(found.intersection(blocked))
        for actor, pair in [('researcher',own),('colleague',granted)]:
            payload={'type':'record','keep_id':pair[0],'duplicate_id':pair[1]}
            preview=self.call('/api/merge/preview',payload,user=actor)
            self.assertTrue(preview.json['allowed'],preview.json)
            done=self.call('/api/merge',{**payload,'keep_version':1,'duplicate_version':1,'confirmed':True},user=actor)
            self.assertEqual(done.status_code,200,done.json)
            self.assertEqual(self.clients[actor].get('/api/records/'+pair[1]).json['id'],pair[0])
        for pair in [public,other]:
            payload={'type':'record','keep_id':pair[0],'duplicate_id':pair[1]}
            self.assertFalse(self.call('/api/merge/preview',payload).json['allowed'])
            self.assertEqual(self.call('/api/merge',{**payload,'keep_version':1,'duplicate_version':1,'confirmed':True}).status_code,403)
            self.assertEqual(self.clients['researcher'].get('/api/records/'+pair[1]).json['id'],pair[1])
        # Public merging is still available to administrators through maintenance.
        payload={'type':'record','keep_id':public[0],'duplicate_id':public[1]}
        self.assertTrue(self.call('/api/merge/preview',payload,user='admin').json['allowed'])

    def test_personal_search_and_paging_filter_before_the_public_scan_limit(self):
        seed=self.pair('report')[0]
        # Arrange a large unrelated synthetic corpus only. Observe discovery via HTTP.
        with closing(connect(self.data_dir/'platform.sqlite3')) as db, db:
            columns=[row[1] for row in db.execute('PRAGMA table_info(records)')]
            projection=','.join('?' if column=='id' else column for column in columns)
            db.executemany('INSERT INTO records SELECT '+projection+' FROM records WHERE id=?',
                           [(f'FIXTURE-PUBLIC-{i:04d}',seed) for i in range(2000)])
        own=self.pair()
        query='/api/records?kind=compilation|research_report&editable=1&size=1'
        pages=[self.clients['researcher'].get(query+'&page='+str(page)).json for page in [1,2]]
        self.assertEqual([page['total'] for page in pages],[2,2])
        self.assertEqual({r['id'] for page in pages for r in page['items']},set(own))
        searched=self.clients['researcher'].get(query+'&q='+own[1]).json
        self.assertEqual([r['id'] for r in searched['items']],[own[1]])
        pairs=self.clients['researcher'].get('/api/duplicates?type=record&scope=personal').json['items']
        self.assertEqual({r[side]['id'] for r in pairs for side in ['keep','duplicate']},set(own))


if __name__=='__main__':
    unittest.main()
