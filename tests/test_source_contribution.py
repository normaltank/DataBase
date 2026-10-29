"""Member contribution and admin handoff through the HTTP boundary."""
import unittest

from tests import test_workflow as workflow


class SourceContributionTests(unittest.TestCase):
    setUp = workflow.WorkflowTests.setUp
    login = workflow.WorkflowTests.login
    call = workflow.WorkflowTests.call

    def test_supported_source_stays_disabled_until_admin_explicitly_enables_it(self):
        created=self.call('/api/sources',{'name':'固定适配的合成LIIA','kind':'think_tank','website':'https://liia.lv/en/'})
        self.assertEqual(created.status_code,201)
        sid=created.json['id']
        url='/api/sources/'+sid
        detail=self.clients['researcher'].get(url).json
        self.assertEqual(detail['automatic_collection'],{'supported':True,'enabled':False})
        self.assertEqual(self.call(url+'/ingestion',{'enabled':True},method='PUT').status_code,403)
        self.assertEqual(self.call(url+'/ingestion',{'enabled':True},method='PUT',user='admin').status_code,200)
        enabled=self.clients['colleague'].get(url).json
        self.assertEqual(enabled['automatic_collection'],{'supported':True,'enabled':True})
        self.assertEqual((enabled['status'],enabled['scope_status']),('pending','candidate'))
        # Configuration alone starts no worker or external request in this fixture.
        self.assertEqual(self.clients['admin'].get('/api/admin/ai').json['attempts'],[])

    def test_duplicate_returns_the_existing_public_source_without_creating_another(self):
        payload = {'name': '成员推荐智库', 'kind': 'think_tank', 'website': 'https://example.org/think-tank'}
        created = self.call('/api/sources', payload)
        self.assertEqual(created.status_code, 201)
        duplicate = self.call('/api/sources', {**payload, 'name': '另一个名称'})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json['existing_source']['id'], created.json['id'])
        self.assertEqual(self.clients['admin'].get('/api/sources?status=pending').json['total'], 1)

    def test_candidate_review_and_collection_support_remain_separate(self):
        payload = {'name': '只有目录的推荐期刊', 'kind': 'journal', 'catalogue_url': 'https://example.org/issues', 'notes': '同事推荐，尚未核实'}
        created = self.call('/api/sources', payload)
        self.assertEqual(created.status_code, 201)
        sid = created.json['id']
        detail = self.clients['colleague'].get('/api/sources/'+sid).json
        self.assertEqual((detail['status'], detail['scope_status']), ('pending', 'candidate'))
        self.assertEqual(detail['automatic_collection'], {'supported': False, 'enabled': False})
        self.assertEqual(detail['website'], '')
        self.assertEqual(detail['host_id'], '')
        self.assertEqual(detail['issn'], '')
        history = self.clients['colleague'].get('/api/history/source/'+sid).json['items']
        self.assertEqual((history[0]['action'], history[0]['actor_name']), ('提交来源', '研究员 · 林'))
        self.assertEqual(self.call('/api/review/source/'+sid, {'version': detail['version']}).status_code, 403)
        self.assertEqual(self.clients['researcher'].get('/api/ingestion').status_code, 403)
        self.assertEqual(self.clients['researcher'].get('/api/admin/ai').status_code, 403)
        self.assertEqual(self.call('/api/sources/'+sid+'/ingestion', {'enabled': True}, user='admin', method='PUT').status_code, 422)
        review = self.call('/api/review/source/'+sid, {'version': 1, 'review_scope': 'metadata_only', 'review_note': '仅核对同事提供的合成目录信息'}, user='admin')
        self.assertEqual(review.status_code, 200)
        reviewed = self.clients['researcher'].get('/api/sources/'+sid).json
        self.assertEqual((reviewed['status'], reviewed['scope_status']), ('verified', 'candidate'))
        self.assertEqual(reviewed['automatic_collection'], {'supported': False, 'enabled': False})
        self.assertEqual(self.clients['admin'].get('/api/admin/ai').json['attempts'], [])


if __name__ == '__main__':
    unittest.main()
