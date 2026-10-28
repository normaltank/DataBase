import json
import os
import ssl
import threading
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

PRICE = {'version':'synthetic-price-v1','model':'deepseek-flash','currency':'USD',
         'input_cache_hit_per_million':'0.02','input_cache_miss_per_million':'0.5','output_per_million':'2'}

class Provider(BaseHTTPRequestHandler):
    requests = []
    mode = 'ok'
    def do_POST(self):
        self.__class__.requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        body = {'model':'deepseek-flash','id':'synthetic-1','usage':{'prompt_tokens':23,'completion_tokens':7,'total_tokens':30,
                'prompt_cache_hit_tokens':3,'prompt_cache_miss_tokens':20},
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'title':'合成译题','abstract':''})}}]}
        if self.mode == 'missing': body.pop('usage')
        if self.mode == 'failed': body['choices'][0]['finish_reason']='length'
        raw=json.dumps(body).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def log_message(self,*args): pass

from tests import test_translation as translation_tests


class AIBudgetTests(unittest.TestCase):
    setUp = translation_tests.TranslationTests.setUp
    login = translation_tests.TranslationTests.login
    call = translation_tests.TranslationTests.call
    get = translation_tests.TranslationTests.get
    record = translation_tests.TranslationTests.record
    detail = translation_tests.TranslationTests.detail
    provider = translation_tests.TranslationTests.provider

    def synthetic(self):
        Provider.requests=[];Provider.mode='ok'
        server=ThreadingHTTPServer(('127.0.0.1',0),Provider)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        env=patch.dict(os.environ, {'DEEPSEEK_API_KEY':'synthetic-secret','DEEPSEEK_BASE_URL':f'https://127.0.0.1:{server.server_port}',
                                   'DEEPSEEK_PRICING_JSON':json.dumps(PRICE),'DEEPSEEK_MODEL':'deepseek-flash'})
        env.start();self.addCleanup(env.stop)
        # Real HTTP framing to an independent local server. Only the synthetic loopback TLS socket is replaced.
        tls=patch.object(ssl.SSLContext,'wrap_socket',lambda context,sock,*a,**k:sock)
        tls.start();self.addCleanup(tls.stop)
        result=self.call('/api/admin/ai/config',{'cap':'1','currency':'USD'},user='admin')
        self.assertEqual(result.status_code,200,result.json)
        return server

    def run_job(self, rid, request_id='first'):
        result=self.call(f'/api/records/{rid}/translations',{'version':1,'request_id':request_id})
        self.assertEqual(result.status_code,201,result.json)
        return self.call(f"/api/translations/{result.json['id']}/run")

    def test_success_cost_uses_reported_cache_and_same_input_reuses(self):
        self.synthetic()
        rid=self.record(title='Synthetic public input')
        first=self.run_job(rid)
        self.assertEqual(first.json['status'],'succeeded',first.json)
        state=self.get('/api/admin/ai','admin').json
        self.assertEqual(state['charged_units'],25)
        self.assertEqual(state['held_units'],0)
        self.assertEqual(self.run_job(rid,'different-request').json['status'],'succeeded')
        self.assertEqual(len(Provider.requests),1)
        self.assertEqual(Provider.requests[0]['thinking'],{'type':'disabled'})

    def test_unknown_survives_restart_blocks_new_request_and_other_input(self):
        self.synthetic();Provider.mode='missing'
        rid=self.record(title='Unknown usage input')
        self.assertEqual(self.run_job(rid).json['status'],'failed')
        held=self.get('/api/admin/ai','admin').json['held_units']
        self.assertGreater(held,0)
        from platform_app.web import create_app
        self.app=create_app(self.data_dir,testing=True)
        self.clients={name:self.login(name) for name in self.clients}
        self.assertEqual(self.run_job(rid,'second-request').json['status'],'failed')
        other=self.record(title='Other input while usage unknown')
        self.assertEqual(self.run_job(other,'other-input').json['status'],'failed')
        self.assertEqual(len(Provider.requests),1)
        self.assertEqual(self.get('/api/admin/ai','admin').json['held_units'],held)

    def test_task_types_share_the_public_gateway_and_persistent_ledger(self):
        self.synthetic()
        from platform_app import ai_gateway
        from platform_app.store import connect
        with closing(connect(self.data_dir/'platform.sqlite3')) as db:
            for task in ['classification-v1','summary-v1','fulltext-v1']:
                result,evidence=ai_gateway.request_json(db,scope='synthetic-public',task=task,
                    messages=[{'role':'system','content':'Synthetic instructions'},{'role':'user','content':'Synthetic public input'}],
                    validate=lambda value:value,authorized=lambda:True)
                self.assertEqual(result['title'],'合成译题')
                self.assertTrue(evidence['attempt_id'])
        self.assertEqual(len(Provider.requests),3)
        self.assertEqual(self.get('/api/admin/ai','admin').json['charged_units'],75)

    def test_admin_reconciles_unknown_with_basis_without_deleting_history(self):
        self.synthetic();Provider.mode='missing'
        rid=self.record(title='Reconcile unknown')
        self.run_job(rid)
        state=self.get('/api/admin/ai','admin').json
        aid=state['attempts'][0]['id']
        path=f'/api/admin/ai/attempts/{aid}/resolve'
        self.assertEqual(self.call(path,{'charged':'0.000025','basis':''},user='admin').status_code,400)
        result=self.call(path,{'charged':'0.000025','basis':'Synthetic invoice confirms 25 micro USD'},user='admin')
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['held_units'],0)
        self.assertEqual(result.json['charged_units'],25)
        self.assertEqual(len(result.json['attempts']),1)
        self.assertEqual(result.json['events'][0]['basis'],'Synthetic invoice confirms 25 micro USD')
        self.assertEqual(self.call(path,{'charged':'0','basis':'change history'},user='admin').status_code,409)
        self.assertEqual(self.call(path,{'charged':'0','basis':'member cannot'},user='researcher').status_code,403)

    def test_admin_persists_cap_and_members_cannot_change_it(self):
        result = self.call('/api/admin/ai/config', {'cap':'0.125','currency':'USD'}, user='admin')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['cap_units'], 125000)
        self.assertEqual(self.get('/api/admin/ai', 'admin').json['currency'], 'USD')
        self.assertEqual(self.call('/api/admin/ai/config', {'cap':'5','currency':'USD'}).status_code, 403)
        self.assertEqual(self.clients['admin'].post('/api/admin/ai/config', json={'cap':'5','currency':'USD'}).status_code, 403)

    def test_missing_month_cap_blocks_even_explicit_translation(self):
        rid = self.record(title='Public original')
        jid = self.call(f'/api/records/{rid}/translations', {'version':1,'request_id':'budget-gate'}).json['id']
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY':'synthetic-secret', 'AI_MONTHLY_CAP':'', 'DEEPSEEK_PRICING_JSON':'{}'}):
            with patch('urllib.request.OpenerDirector.open', return_value=self.provider('译题','')) as network:
                result = self.call(f'/api/translations/{jid}/run')
        self.assertEqual(result.json['status'], 'failed')
        network.assert_not_called()
        state = self.get('/api/admin/ai', user='admin')
        self.assertEqual(state.status_code, 200)
        self.assertEqual(state.json['held_units'], 0)

