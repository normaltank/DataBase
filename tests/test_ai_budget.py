import json
import os
import ssl
import subprocess
import sys
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
    before_reply = None
    def do_POST(self):
        self.__class__.requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        if self.before_reply: type(self).before_reply()
        body = {'model':'deepseek-flash','id':'synthetic-1','usage':{'prompt_tokens':23,'completion_tokens':7,'total_tokens':30,
                'prompt_cache_hit_tokens':3,'prompt_cache_miss_tokens':20},
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'title':'合成译题','abstract':''})}}]}
        if self.mode == 'missing': body.pop('usage')
        if self.mode == 'contradictory': body['usage']['prompt_tokens_details']={'cached_tokens':4}
        if self.mode == 'overbound': body['usage'].update(completion_tokens=7000,total_tokens=7023)
        if self.mode == 'model': body['model']='unpriced-model'
        if self.mode == 'negative': body['usage']['prompt_cache_hit_tokens']=-1
        if self.mode == 'failed': body['choices'][0]['finish_reason']='length'
        raw=json.dumps(body).encode()
        try:
            self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    def log_message(self,*args): pass

from tests import test_translation as translation_tests


class AIBudgetTests(unittest.TestCase):
    setUp = translation_tests.workflow_tests.WorkflowTests.setUp
    login = translation_tests.TranslationTests.login
    call = translation_tests.TranslationTests.call
    get = translation_tests.TranslationTests.get
    record = translation_tests.TranslationTests.record
    detail = translation_tests.TranslationTests.detail
    provider = translation_tests.TranslationTests.provider

    def synthetic(self):
        Provider.requests=[];Provider.mode='ok';Provider.before_reply=None
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

    def test_failed_complete_response_still_charged_and_retries_are_input_bounded(self):
        self.synthetic();Provider.mode='failed'
        rid=self.record(title='Failed but billed')
        for index,clock in enumerate(['2026-10-28T00:00:00+00:00','2026-10-28T00:01:00+00:00','2026-10-28T00:03:00+00:00']):
            with patch('platform_app.ai_gateway.now',return_value=clock):
                self.assertEqual(self.run_job(rid,'attempt-'+str(index)).json['status'],'failed')
        self.assertEqual(len(Provider.requests),3)
        self.assertEqual(self.get('/api/admin/ai','admin').json['charged_units'],75)
        with patch('platform_app.ai_gateway.now',return_value='2026-10-28T00:10:00+00:00'):
            self.assertEqual(self.run_job(rid,'fourth-new-request').json['status'],'failed')
        self.assertEqual(len(Provider.requests),3)

    def test_conflicting_usage_and_unpriced_model_keep_full_hold(self):
        self.synthetic()
        for index,mode in enumerate(['contradictory','overbound','model','negative']):
            Provider.mode=mode
            rid=self.record(title='Usage check '+mode)
            self.assertEqual(self.run_job(rid,'invalid-'+mode).json['status'],'failed')
            state=self.get('/api/admin/ai','admin').json
            self.assertGreater(state['held_units'],0)
            self.assertEqual(state['attempts'][0]['status'],'unknown')
            self.assertEqual(len(Provider.requests),index+1)
            self.call('/api/admin/ai/attempts/'+state['attempts'][0]['id']+'/resolve',{'charged':'0','basis':'Synthetic provider confirms no invoice for this case'},user='admin')

    def test_frozen_month_price_and_currency_cannot_rewrite_old_attempt(self):
        self.synthetic()
        clock={'value':'2026-10-31T23:59:59+00:00'}
        newprice={**PRICE,'version':'synthetic-price-v2','output_per_million':'4'}
        def rollover():
            clock['value']='2026-11-01T00:00:01+00:00'
            os.environ['DEEPSEEK_PRICING_JSON']=json.dumps(newprice)
            Provider.before_reply=None
        Provider.before_reply=rollover
        with patch('platform_app.ai_gateway.now',side_effect=lambda:clock['value']):
            first=self.record(title='Cross-month request')
            self.assertEqual(self.run_job(first).json['status'],'succeeded')
            state=self.get('/api/admin/ai','admin').json
            self.assertEqual(state['months'][0],{'month':'2026-10','currency':'USD','charged_units':25,'held_units':0})
            second=self.record(title='New price request')
            self.assertEqual(self.run_job(second,'new-price').json['status'],'succeeded')
            self.assertEqual(self.get('/api/admin/ai','admin').json['charged_units'],39)
            self.assertEqual(self.call('/api/admin/ai/config',{'cap':'1','currency':'EUR'},user='admin').status_code,409)
        self.assertEqual(len(Provider.requests),2)

    def test_backup_new_directory_retains_unknown_and_rejects_underreserved_ledger(self):
        self.synthetic();Provider.mode='missing'
        rid=self.record(title='Restore unknown')
        self.run_job(rid)
        from platform_app.maintenance import create_backup,restore_backup
        from platform_app.web import create_app
        from platform_app.store import connect
        restored=restore_backup(create_backup(self.data_dir),self.data_dir.parent/'restored-ai')
        app=create_app(restored,testing=True)
        self.clients={name:self.login(name,app) for name in self.clients}
        self.assertEqual(self.run_job(rid,'after-restore').json['status'],'failed')
        self.assertEqual(len(Provider.requests),1)
        self.assertGreater(self.get('/api/admin/ai','admin').json['held_units'],0)
        with closing(connect(self.data_dir/'platform.sqlite3')) as db,db:
            db.execute('UPDATE ai_attempts SET reserved_units=1')
        with self.assertRaises(ValueError):
            restore_backup(create_backup(self.data_dir),self.data_dir.parent/'bad-ai')

    def test_concurrent_manual_and_other_task_share_cap_without_holding_write_lock(self):
        self.synthetic()
        entered,release=threading.Event(),threading.Event()
        self.addCleanup(release.set)
        def hold(): entered.set();release.wait(10)
        Provider.before_reply=hold
        self.call('/api/admin/ai/config',{'cap':'0.020000','currency':'USD'},user='admin')
        rid=self.record(title='Concurrent public original')
        jid=self.call(f'/api/records/{rid}/translations',{'version':1,'request_id':'concurrent'}).json['id']
        token=self.clients['researcher'].get('/api/session').json['csrf']
        result=[]
        thread=threading.Thread(target=lambda:result.append(self.clients['researcher'].post(f'/api/translations/{jid}/run',json={},headers={'X-CSRF-Token':token})),daemon=True)
        thread.start();self.assertTrue(entered.wait(5))
        try:
            state=self.get('/api/admin/ai','admin').json
            self.assertGreater(state['held_units'],12000)
            # The supplier is blocked, but another administrator write succeeds immediately.
            self.assertEqual(self.call('/api/admin/ai/pause',{'paused':False},user='admin').status_code,200)
            from platform_app import ai_gateway
            from platform_app.store import connect
            with closing(connect(self.data_dir/'platform.sqlite3')) as db:
                with self.assertRaisesRegex(ValueError,'额度不足'):
                    ai_gateway.request_json(db,scope='other-public',task='summary-v1',messages=[{'role':'user','content':'Other synthetic input'}],validate=lambda v:v,authorized=lambda:True)
            self.assertEqual(len(Provider.requests),1)
        finally:
            release.set();thread.join(5)
        self.assertEqual(result[0].json['status'],'succeeded')
        self.assertEqual(self.get('/api/admin/ai','admin').json['charged_units'],25)

    def test_sent_process_interruption_never_blindly_resends_after_restart(self):
        self.synthetic()
        entered,release=threading.Event(),threading.Event()
        self.addCleanup(release.set)
        Provider.before_reply=lambda:(entered.set(),release.wait(10))
        rid=self.record(title='Crash after supplier accepted')
        script="""import sys,ssl
from platform_app.store import connect
from platform_app.translations import request_translation
ssl.SSLContext.wrap_socket=lambda context,sock,*a,**k:sock
with connect(sys.argv[1]) as db:
 request_translation(db,sys.argv[2],'Crash after supplier accepted','',lambda:True)
"""
        process=subprocess.Popen([sys.executable,'-c',script,str(self.data_dir/'platform.sqlite3'),rid],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.addCleanup(lambda:process.poll() is None and process.kill())
        self.assertTrue(entered.wait(5))
        process.terminate();process.wait(5)
        release.set()
        from platform_app.web import create_app
        app=create_app(self.data_dir,testing=True)
        self.clients={name:self.login(name,app) for name in self.clients}
        self.assertEqual(self.run_job(rid,'crash-retry').json['status'],'failed')
        state=self.get('/api/admin/ai','admin').json
        self.assertGreater(state['held_units'],0)
        self.assertEqual(len(state['attempts']),1)
        self.assertEqual(len(Provider.requests),1)

    def test_permission_change_after_send_preserves_hold_and_hides_output(self):
        self.synthetic()
        rid=self.record(title='Permissions change during supplier call')
        jid=self.call(f'/api/records/{rid}/translations',{'version':1,'request_id':'revoke'},user='colleague').json['id']
        def revoke():
            self.assertEqual(self.call(f'/api/records/{rid}',{'version':1,'visibility':'restricted'},method='PUT').status_code,200)
        Provider.before_reply=revoke
        result=self.call(f'/api/translations/{jid}/run',user='colleague')
        self.assertEqual(result.status_code,404)
        state=self.get('/api/admin/ai','admin').json
        self.assertEqual(state['attempts'][0]['status'],'unknown')
        self.assertGreater(state['held_units'],0)
        self.assertEqual(self.detail(rid)['translations'][0]['output_title'],'')
        self.assertEqual(len(Provider.requests),1)

    def test_proven_not_sent_releases_reservation_and_keeps_attempt(self):
        self.synthetic()
        from platform_app import ai_gateway
        from platform_app.store import connect
        checks=iter([True,False])
        with closing(connect(self.data_dir/'platform.sqlite3')) as db:
            with self.assertRaisesRegex(ValueError,'未发送'):
                ai_gateway.request_json(db,scope='public-input',task='classification-v1',messages=[{'role':'user','content':'Synthetic'}],validate=lambda v:v,authorized=lambda:next(checks))
        state=self.get('/api/admin/ai','admin').json
        self.assertEqual(state['held_units'],0)
        self.assertEqual(state['attempts'][0]['status'],'released')
        self.assertEqual(len(Provider.requests),0)

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
