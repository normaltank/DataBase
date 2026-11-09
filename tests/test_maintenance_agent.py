import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_workflow as fixture
from tests.synthetic_ai import PRICE
from platform_app.web import create_app

class Reply(io.BytesIO):
    def __init__(self, value, url):
        super().__init__(json.dumps(value).encode()); self.url=url
    def geturl(self): return self.url

class MaintenanceAgentTests(unittest.TestCase):
    login=fixture.WorkflowTests.login
    call=fixture.WorkflowTests.call
    source=fixture.WorkflowTests.source
    record=fixture.WorkflowTests.record
    detail=fixture.WorkflowTests.detail
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=os.environ.get('DATABASE_TEST_TMP'))
        self.addCleanup(self.temp.cleanup)
        self.data_dir=Path(self.temp.name)/'data'
        self.app=create_app(self.data_dir, testing=True)
        self.clients={n:self.login(n) for n in ['researcher','colleague','admin']}
        self.price={**PRICE,'currency':'CNY'}
        env={'DEEPSEEK_API_KEY':'synthetic-secret','DEEPSEEK_BASE_URL':'https://provider.example','DEEPSEEK_MODEL':'deepseek-flash','DEEPSEEK_PRICING_JSON':json.dumps(self.price)}
        self.env=patch.dict(os.environ,env); self.env.start(); self.addCleanup(self.env.stop)
        self.call('/api/admin/ai/config',{'cap':'10','currency':'CNY'},user='admin')
        self.transport=patch('urllib.request.OpenerDirector.open',side_effect=self.respond)
        self.provider=self.transport.start();self.addCleanup(self.transport.stop)
        self.rounds=0;self.tool_results=[]
        self.rid=self.record(kind='journal_article',title='Baltic cooperation',authors='Alex Vale',url='https://article.example/paper',keywords='old label')
    def respond(self, request, *args, **kwargs):
        body=json.loads(request.data); url=request.full_url
        if url.endswith('/tools/search'):
            return Reply({'results':[{'title':'Alex Vale','url':'https://uni.example/alex','snippet':'Alex Vale studies Baltic cooperation.'}]},url)
        if url.endswith('/tools/fetch'):
            return Reply({'title':'Alex Vale','content':'Alex Vale is a lecturer at North University. North University is in Latvia. Baltic Review is hosted by North University. Baltic cooperation is authored by Alex Vale. DOI: 10.1234/baltic. ISSN: 1234-5679. ORCID: 0000-0002-1825-0097. The article affiliation of Alex Vale is South Research Institute.'},url)
        self.assertEqual(body['thinking'],{'type':'disabled'})
        self.assertIn('tools',body)
        self.tool_results=[json.loads(m['content']) for m in body['messages'] if m['role']=='tool']
        self.rounds+=1
        name,args=self.next_action()
        message={'role':'assistant','content':None,'tool_calls':[{'id':'call-'+str(self.rounds),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}
        return Reply({'id':'mock','model':'deepseek-flash','usage':{'prompt_tokens':30,'completion_tokens':20,'total_tokens':50},'choices':[{'finish_reason':'tool_calls','message':message}]},url)
    def next_action(self):
        result=self.tool_results[-1] if self.tool_results else {}
        if self.rounds==1:return 'search',{'query':'Alex Vale Baltic cooperation'}
        if self.rounds==2:
            self.assertIn('results',result)
            return 'fetch',{'url':'https://uni.example/alex'}
        evidence=next((x['evidence_id'] for x in reversed(self.tool_results) if x.get('method')=='deepseek-fetch-markdown'),'')
        basis={'evidence_id':evidence,'quote':'Alex Vale is a lecturer at North University.'}
        if self.rounds==3:return 'save_profile',{'target_type':'source','data':{'name':'North University','kind':'institution','country':'Latvia'},**basis}
        inst=next((x['object']['id'] for x in self.tool_results if x.get('object',{}).get('name')=='North University'),'')
        if self.rounds==4:return 'save_profile',{'target_type':'source','data':{'name':'Baltic Review','kind':'journal','host_id':inst,'host_evidence':'Baltic Review is hosted by North University.','issn':'1234-5679'},'evidence_id':evidence,'quote':'Baltic Review is hosted by North University.'}
        journal=next((x['object']['id'] for x in self.tool_results if x.get('object',{}).get('name')=='Baltic Review'),'')
        if self.rounds==5:return 'save_profile',{'target_type':'person','data':{'name':'Alex Vale','introduction_html':'<p>Alex Vale is a lecturer at North University.</p>','orcid':'0000-0002-1825-0097'},**basis}
        person=next((x['object']['id'] for x in self.tool_results if x.get('object',{}).get('name')=='Alex Vale'),'')
        if self.rounds==6:return 'save_record',{'id':self.rid,'version':1,'data':{'keywords':'Baltic cooperation','serial_id':journal,'doi':'10.1234/baltic'},'evidence_id':evidence,'quote':'Baltic cooperation is authored by Alex Vale.'}
        if self.rounds==7:return 'read',{'target_type':'record','id':self.rid}
        if self.rounds==8:return 'set_bylines',{'id':self.rid,'version':0,'record_version':2,'items':[{'raw_name':'Alex Vale','target_type':'person','target_id':person}],**basis}
        if self.rounds==9:return 'set_employments',{'id':person,'version':0,'items':[{'institution_id':inst,'role':'lecturer'}],**basis}
        if self.rounds==10:return 'read',{'target_type':'record','id':self.rid}
        if self.rounds==11:return 'read',{'target_type':'person','id':person}
        if self.rounds==12:return 'read',{'target_type':'source','id':inst}
        if self.rounds==13:return 'read',{'target_type':'source','id':journal}
        return 'finish',{'reason':'已保存作者、任职与刊物，已读取检查。'}
    def test_native_tools_write_formal_network_and_are_readable_after_restore(self):
        q=self.call('/api/maintenance/jobs',{'target_type':'record','target_id':self.rid,'request_id':'one'})
        self.assertEqual(q.status_code,201,q.json)
        jid=q.json['id']
        result=self.call('/api/admin/maintenance/run',user='admin')
        self.assertEqual(result.status_code,200,result.json)
        state=self.clients['researcher'].get('/api/maintenance/jobs/'+jid).json
        self.assertEqual(state['status'],'completed',state)
        record=self.detail(self.rid)
        self.assertEqual(record['keywords'],'Baltic cooperation')
        self.assertEqual(record['doi'],'10.1234/baltic')
        self.assertEqual(record['authors'],'Alex Vale')
        self.assertEqual(record['owner_id'],'researcher')
        self.assertEqual(record['visibility'],'shared')
        bylines=self.clients['researcher'].get('/api/records/'+self.rid+'/bylines').json['items']
        self.assertEqual(len(bylines),1)
        self.assertEqual(bylines[0]['status'],'confirmed')
        pid=bylines[0]['target_id']
        self.assertEqual(self.clients['researcher'].get('/api/people/'+pid).json['orcid'],'0000-0002-1825-0097')
        works=self.clients['researcher'].get('/api/people/'+pid+'/works').json
        self.assertEqual([w['id'] for w in works['items']],[self.rid])
        employments=self.clients['researcher'].get('/api/people/'+pid+'/employments').json
        self.assertEqual(employments['items'][0]['role'],'lecturer')
        self.assertEqual(self.clients['researcher'].get('/api/sources/'+record['serial_id']).json['issn'],'1234-5679')
        charges=self.clients['admin'].get('/api/admin/ai').json
        tools=[a for a in charges['attempts'] if a['task'].startswith('maintenance-tool:')]
        self.assertEqual([a['charged_units'] for a in tools],[5000,5000])
        self.assertTrue(all(s['status']=='completed' for s in state['steps']))
        self.assertEqual(self.call('/api/maintenance/jobs',{'target_type':'record','target_id':self.rid,'request_id':'one'}).json['id'],jid)
        from platform_app.maintenance import create_backup,restore_backup
        backup=create_backup(self.data_dir);restored=self.data_dir.parent/'restored';restore_backup(backup,restored)
        client=self.login('researcher',create_app(restored,testing=True))
        self.assertEqual(client.get('/api/maintenance/jobs/'+jid).json['status'],'completed')
        self.assertEqual(client.get('/api/records/'+self.rid+'/bylines').json['items'][0]['target_id'],pid)

    def queue(self, request_id='one'):
        response=self.call('/api/maintenance/jobs',{'target_type':'record','target_id':self.rid,'request_id':request_id})
        self.assertEqual(response.status_code,201,response.json)
        return response.json['id']

    def job(self,jid,client=None):
        return (client or self.clients['researcher']).get('/api/maintenance/jobs/'+jid).json

    def test_interrupt_after_model_response_resumes_pending_tool_without_duplicate_call(self):
        from platform_app.maintenance_agent import run_pending
        stop=threading.Event();normal=self.respond
        def interrupt(request,*args,**kwargs):
            value=normal(request,*args,**kwargs)
            if request.full_url.endswith('/chat/completions') and self.rounds==1:stop.set()
            return value
        self.provider.side_effect=interrupt
        jid=self.queue()
        self.assertEqual(run_pending(self.data_dir,stopping=stop.is_set),{'tasks':1,'completed':0})
        self.assertEqual(self.job(jid)['status'],'queued')
        self.assertEqual(self.job(jid)['steps'][0]['status'],'pending')
        app=create_app(self.data_dir,testing=True)
        stop.clear();self.provider.side_effect=normal
        self.assertEqual(run_pending(self.data_dir),{'tasks':1,'completed':1})
        client=self.login('researcher',app)
        self.assertEqual(self.job(jid,client)['turns'],14)
        self.assertEqual(len(client.get('/api/records/'+self.rid+'/bylines').json['items']),1)
        self.assertEqual(run_pending(self.data_dir),{'tasks':0,'completed':0})

    def test_unknown_search_preserves_reservation_across_resume_and_restore(self):
        normal=self.respond;requests=[]
        def timeout(request,*args,**kwargs):
            requests.append(request.full_url)
            if request.full_url.endswith('/tools/search'):raise TimeoutError('synthetic interruption')
            return normal(request,*args,**kwargs)
        self.provider.side_effect=timeout
        jid=self.queue()
        self.call('/api/admin/maintenance/run',user='admin')
        self.assertEqual(self.job(jid)['status'],'paused')
        charges=self.clients['admin'].get('/api/admin/ai').json
        self.assertEqual(charges['held_units'],5000)
        attempt=next(a for a in charges['attempts'] if a['task'].startswith('maintenance-tool:'))
        self.assertEqual(attempt['status'],'unknown')
        from platform_app.maintenance import create_backup,restore_backup
        restored=self.data_dir.parent/'restored'
        restore_backup(create_backup(self.data_dir),restored)
        app=create_app(restored,testing=True);admin=self.login('admin',app)
        self.assertEqual(admin.get('/api/admin/ai').json['held_units'],5000)
        self.call('/api/maintenance/jobs/'+jid+'/resume')
        self.call('/api/admin/maintenance/run',user='admin')
        self.assertEqual(requests.count('https://provider.example/v1/tools/search'),1)
        self.assertEqual(self.detail(self.rid)['keywords'],'old label')

    def test_private_and_internal_targets_are_rejected_before_provider(self):
        private=self.record(kind='journal_article',title='Private',visibility='restricted')
        internal=self.record(kind='research_report',title='Internal report')
        for rid in [private,internal]:
            result=self.call('/api/maintenance/jobs',{'target_type':'record','target_id':rid,'request_id':'no'})
            self.assertIn(result.status_code,[400,404])
        self.assertEqual(self.rounds,0)

    def test_search_budget_reservation_blocks_before_sending(self):
        self.env.stop()
        cheap={**self.price,'input_cache_hit_per_million':'0.000001','input_cache_miss_per_million':'0.000001','output_per_million':'0.000001'}
        env=patch.dict(os.environ,{'DEEPSEEK_API_KEY':'synthetic-secret','DEEPSEEK_BASE_URL':'https://provider.example','DEEPSEEK_PRICING_JSON':json.dumps(cheap)})
        env.start();self.addCleanup(env.stop)
        self.call('/api/admin/ai/config',{'cap':'0.004','currency':'CNY'},user='admin')
        jid=self.queue();self.call('/api/admin/maintenance/run',user='admin')
        self.assertEqual(self.job(jid)['status'],'paused')
        self.assertIn('额度',self.job(jid)['reason'])
        charges=self.clients['admin'].get('/api/admin/ai').json
        self.assertEqual(charges['held_units'],0)
        self.assertFalse(any(a['task'].startswith('maintenance-tool:') for a in charges['attempts']))

    def test_same_name_is_recalled_but_identity_is_not_merged_and_article_unit_is_not_employment(self):
        created=self.call('/api/people',{'name':'Alex Vale','introduction_html':'<p>Physicist at South Laboratory.</p>','change_note':'Independent synthetic identity'})
        self.assertEqual(created.status_code,201,created.json)
        unrelated=created.json['id']
        article_unit=self.source('South Research Institute','institution')
        normal=self.next_action
        def model():
            n=self.rounds
            if n==3:return 'find',{'target_type':'person','query':'Alex Vale'}
            if n==4:
                self.assertEqual(self.tool_results[-1]['items'][0]['id'],unrelated)
                self.assertIn('Physicist',self.tool_results[-1]['items'][0]['introduction_html'])
            if n>=4:self.rounds-=1
            try:
                if n==11:
                    bid=next(x['object']['bylines']['items'][0]['id'] for x in reversed(self.tool_results) if x.get('object',{}).get('bylines',{}).get('items'))
                    evidence=next(x['evidence_id'] for x in self.tool_results if x.get('method')=='deepseek-fetch-markdown')
                    return 'set_affiliations',{'id':self.rid,'version':0,'record_version':2,'byline_version':1,'items':[{'byline_id':bid,'institution_id':article_unit}],'evidence_id':evidence,'quote':'The article affiliation of Alex Vale is South Research Institute.'}
                if n>=12:self.rounds-=1
                return normal()
            finally:self.rounds=n
        self.next_action=model
        jid=self.queue();self.call('/api/admin/maintenance/run',user='admin')
        self.assertEqual(self.job(jid)['status'],'completed',self.job(jid))
        current=self.clients['researcher'].get('/api/records/'+self.rid+'/bylines').json['items']
        self.assertNotEqual(current[0]['target_id'],unrelated)
        self.assertTrue(current[0]['machine']);self.assertFalse(current[0]['human_checked'])
        self.assertEqual(self.clients['researcher'].get('/api/people/'+unrelated+'/works').json['total'],0)
        employments=self.clients['researcher'].get('/api/people/'+current[0]['target_id']+'/employments').json['items']
        self.assertEqual(len(employments),1)
        self.assertNotEqual(employments[0]['institution_id'],article_unit)
        units=self.clients['researcher'].get('/api/records/'+self.rid+'/affiliations').json['items']
        self.assertEqual(units[0]['institution_id'],article_unit)

    def test_empty_search_and_known_fetch_error_cost_zero(self):
        import urllib.error
        normal=self.respond
        def empty(request,*args,**kwargs):
            if request.full_url.endswith('/tools/search'):return Reply({'results':[]},request.full_url)
            if request.full_url.endswith('/tools/fetch'):raise urllib.error.HTTPError(request.full_url,404,'synthetic missing',{},None)
            return normal(request,*args,**kwargs)
        self.provider.side_effect=empty
        jid=self.queue();self.call('/api/admin/maintenance/run',user='admin')
        charges=self.clients['admin'].get('/api/admin/ai').json
        tools=[a for a in charges['attempts'] if a['task'].startswith('maintenance-tool:')]
        self.assertEqual(len(tools),2)
        self.assertEqual([a['charged_units'] for a in tools],[0,0])
        self.assertTrue(all(a['status']=='settled' for a in tools))
        self.assertEqual(self.job(jid)['status'],'failed')

    def test_nonempty_concurrent_update_is_read_again_before_correction(self):
        def model():
            evidence=next((x['evidence_id'] for x in self.tool_results if x.get('method')=='deepseek-fetch-markdown'),'')
            basis={'evidence_id':evidence,'quote':'Baltic cooperation is authored by Alex Vale.'}
            if self.rounds==1:return 'search',{'query':'Baltic cooperation'}
            if self.rounds==2:return 'fetch',{'url':'https://uni.example/alex'}
            if self.rounds==3:
                self.assertEqual(self.call('/api/records/'+self.rid,{'version':1,'keywords':'Concurrent field'},method='PUT').status_code,200)
                return 'save_record',{'id':self.rid,'version':1,'data':{'keywords':'Baltic cooperation'},**basis}
            if self.rounds==4:
                self.assertEqual(self.tool_results[-1]['error'],'version_conflict')
                return 'read',{'target_type':'record','id':self.rid}
            if self.rounds==5:
                self.assertEqual(self.tool_results[-1]['object']['keywords'],'Concurrent field')
                return 'save_record',{'id':self.rid,'version':2,'data':{'keywords':'Baltic cooperation'},**basis}
            if self.rounds==6:return 'read',{'target_type':'record','id':self.rid}
            return 'finish',{'reason':'重读后修正标签。'}
        self.next_action=model
        jid=self.queue();self.call('/api/admin/maintenance/run',user='admin')
        self.assertEqual(self.job(jid)['status'],'completed',self.job(jid))
        current=self.detail(self.rid)
        self.assertEqual(current['version'],3)
        self.assertEqual(current['keywords'],'Baltic cooperation')
        history=self.clients['researcher'].get('/api/history/record/'+self.rid).json['items']
        self.assertEqual(len(history),3)
        self.assertEqual(history[0]['actor_name'],'AI 自主维护')

    def test_related_record_access_change_blocks_observation_replay_and_history(self):
        from platform_app.maintenance_agent import run_pending
        source=self.source('Synthetic Public Journal')
        self.next_action=lambda:('find',{'target_type':'record','query':'Baltic cooperation'})
        response=self.call('/api/maintenance/jobs',{'target_type':'source','target_id':source,'request_id':'source-read'})
        jid=response.json['id']
        def stopping():
            return any(s['name']=='find' and s['status']=='completed' for s in self.job(jid)['steps'])
        self.assertEqual(run_pending(self.data_dir,stopping=stopping),{'tasks':1,'completed':0})
        before=self.clients['admin'].get('/api/admin/ai').json['attempts']
        changed=self.call('/api/records/'+self.rid,{'version':1,'visibility':'restricted'},method='PUT')
        self.assertEqual(changed.status_code,200,changed.json)
        self.assertEqual(self.clients['colleague'].get('/api/maintenance/jobs/'+jid).status_code,404)
        self.assertEqual(run_pending(self.data_dir),{'tasks':1,'completed':0})
        self.assertEqual(self.clients['admin'].get('/api/admin/ai').json['attempts'],before)
        self.assertEqual(self.clients['colleague'].get('/api/maintenance/jobs').json['items'],[])

if __name__=='__main__':unittest.main()
