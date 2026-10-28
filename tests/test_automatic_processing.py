"""Automatic public-material processing at the worker and member HTTP boundaries."""
import json
import unittest
from unittest.mock import patch, MagicMock
from tests.test_ingestion import IngestionTests
from tests.synthetic_ai import ENV


class AutomaticProcessingTests(unittest.TestCase):
    # Reuse acquisition fixture helpers, without inheriting its test cases.
    setUp = IngestionTests.setUp
    call = IngestionTests.call
    source = IngestionTests.source
    run_worker = IngestionTests.run_worker

    def test_classification_requires_verbatim_input_evidence_and_does_not_change_record_kind(self):
        sid=self.source()
        self.call('/api/sources/'+sid+'/ingestion',{'enabled':True},user='admin',method='PUT')
        self.run_worker()
        self.call('/api/admin/ai/config',{'cap':'1','currency':'USD'},user='admin')
        from platform_app.automatic_processing import run_pending
        def respond(request, **kwargs):
            value=json.loads(request.data)
            classification='Classify' in value['messages'][0]['content']
            source=json.loads(value['messages'][1]['content'])
            output=({'countries':[], 'topics':[{'value':'能源','field':'title','quote':source['title'],'certainty':'supported'}],
                     'type':None} if classification else {'title':'自动能源译题','abstract':''})
            response=MagicMock();response.__enter__.return_value=response;response.geturl.return_value=request.full_url
            response.read.return_value=json.dumps({'model':'deepseek-flash','usage':{'prompt_tokens':23,'completion_tokens':7,'total_tokens':30},'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]}).encode()
            return response
        with patch.dict('os.environ',{**ENV,'DEEPSEEK_API_KEY':'synthetic-only'}),patch('urllib.request.OpenerDirector.open',side_effect=respond):
            run_pending(self.app.config['DATA_DIR'],limit=10)
        items=self.clients['researcher'].get('/api/records?topic=能源').json['items']
        self.assertEqual(len(items),2)
        detail=self.clients['researcher'].get('/api/records/'+items[0]['id']).json
        self.assertEqual(detail['countries'],'')
        self.assertEqual(detail['kind'],'other')
        self.assertEqual(detail['machine_classification']['topics'][0]['certainty'],'supported')
        self.assertEqual(detail['machine_classification']['countries'],[])

    def test_public_title_is_translated_by_worker_and_searchable_without_inventing_abstract(self):
        sid = self.source()
        self.call('/api/sources/'+sid+'/ingestion', {'enabled':True}, user='admin', method='PUT')
        self.run_worker()
        self.call('/api/admin/ai/config', {'cap':'1','currency':'USD'}, user='admin')
        provider = MagicMock()
        provider.__enter__.return_value = provider
        provider.geturl.return_value = 'https://api.deepseek.com/chat/completions'
        provider.read.return_value = json.dumps({'model':'deepseek-flash',
            'usage':{'prompt_tokens':23,'completion_tokens':7,'total_tokens':30},
            'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'title':'自动能源译题','abstract':''})}}]}).encode()
        from platform_app.automatic_processing import run_pending
        with patch.dict('os.environ', {**ENV,'DEEPSEEK_API_KEY':'synthetic-only'}), patch('urllib.request.OpenerDirector.open',return_value=provider) as sent:
            self.assertEqual(run_pending(self.app.config['DATA_DIR'],limit=2)['succeeded'],2)
            self.assertEqual(run_pending(self.app.config['DATA_DIR'],limit=2)['succeeded'],0)
            self.assertEqual(sent.call_count,4)  # Classification rejects translation-shaped replies.
        items = self.clients['researcher'].get('/api/records?q=自动能源').json['items']
        self.assertEqual(len(items),2)
        detail = self.clients['researcher'].get('/api/records/'+items[0]['id']).json
        self.assertEqual(detail['display_title'],'自动能源译题')
        self.assertEqual(detail['translation_origin'],'machine')
        self.assertEqual(detail['abstract'],'')
        self.assertEqual(detail['display_abstract'],'')
        self.assertEqual(detail['status'],'pending')
        self.assertFalse(detail['reading_access']['has_body'])
