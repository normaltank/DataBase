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
        # Newly created related profiles can receive their own maintenance pass;
        # discovery must not requeue the article or replay its settled requests.
        calls=self.provider.call_count
        self.assertEqual(run_pending(self.data_dir,limit=0),{'tasks':0,'completed':0})
        self.assertEqual(self.provider.call_count,calls)
        article_jobs=[job for job in client.get('/api/maintenance/jobs').json['items'] if job['target_type']=='record' and job['target_id']==self.rid]
        self.assertEqual([job['id'] for job in article_jobs],[jid])

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

    def test_long_persisted_observations_resume_without_refetch_and_tail_evidence_can_be_saved(self):
        from platform_app.maintenance_agent import run_pending
        from platform_app.maintenance import create_backup, restore_backup
        text = 'Unrelated public archive text. ' * 5600 + '\nIndependent finding: Baltic cooperation concerns Latvia.'
        requests = []; bodies = []; evidence = ''; turn = 0
        def supplier(request, *args, **kwargs):
            nonlocal turn, evidence
            body = json.loads(request.data); requests.append(request.full_url)
            if request.full_url.endswith('/tools/search'):
                return Reply({'results': [{'title': 'Public archive', 'url': 'https://uni.example/archive',
                    'snippet': 'Baltic cooperation public archive', 'content': text}]}, request.full_url)
            if request.full_url.endswith('/tools/fetch'):
                return Reply({'title': 'Public archive', 'content': text}, request.full_url)
            bodies.append(body); turn += 1
            self.assertLess(len(json.dumps(body, ensure_ascii=True)), 110000)
            observations = [json.loads(m['content']) for m in body['messages'] if m['role'] == 'tool']
            if turn == 1: name, args = 'search', {'query': 'Baltic cooperation archive'}
            elif turn == 2: name, args = 'fetch', {'url': 'https://uni.example/archive'}
            elif turn == 3:
                value = observations[-1]; evidence = value['evidence_id']
                self.assertEqual(value['url'], 'https://uni.example/archive')
                self.assertEqual(value['text_length'], len(text)); self.assertEqual(len(value['sha256']), 64)
                name, args = 'read_evidence', {'evidence_id': evidence, 'query': 'Independent finding'}
            elif turn == 4:
                self.assertIn('Independent finding: Baltic cooperation concerns Latvia.', observations[-1]['text'])
                self.assertGreater(observations[-1]['offset'], 160000)
                name, args = 'save_record', {'id': self.rid, 'version': 1, 'data': {'countries': 'Latvia'},
                    'evidence_id': evidence, 'quote': 'Independent finding: Baltic cooperation concerns Latvia.'}
            elif turn == 5: name, args = 'read', {'target_type': 'record', 'id': self.rid}
            else: name, args = 'finish', {'reason': '已按公开材料整理研究对象国。'}
            message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'long-'+str(turn),
                'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
            return Reply({'model': 'deepseek-flash', 'usage': {'prompt_tokens': 30, 'completion_tokens': 20, 'total_tokens': 50},
                'choices': [{'finish_reason': 'tool_calls', 'message': message}]}, request.full_url)
        self.provider.side_effect = supplier
        jid = self.queue('long-observation')
        def stopping():
            return any(s['name'] == 'fetch' and s['status'] == 'completed' for s in self.job(jid)['steps'])
        self.assertEqual(run_pending(self.data_dir, stopping=stopping), {'tasks': 1, 'completed': 0})
        # This is the pre-fix persisted shape: full paid observations in the
        # conversation. Restoring must project it before the next model turn.
        before = self.job(jid)
        self.assertEqual(next(e['text'] for e in before['evidence'] if e['method'] == 'deepseek-fetch-markdown'), text)
        restored = self.data_dir.parent/'long-restored'
        restore_backup(create_backup(self.data_dir), restored)
        client = self.login('researcher', create_app(restored, testing=True))
        resumed=run_pending(restored)
        self.assertEqual(resumed, {'tasks': 1, 'completed': 1}, {k:v for k,v in self.job(jid, client).items() if k not in {'evidence','steps'}})
        self.assertEqual(self.job(jid, client)['status'], 'completed')
        self.assertEqual(client.get('/api/records/'+self.rid).json['countries'], 'Latvia')
        self.assertEqual(requests.count('https://provider.example/v1/tools/search'), 1)
        self.assertEqual(requests.count('https://provider.example/v1/tools/fetch'), 1)
        self.assertEqual(self.job(jid, client)['evidence'], before['evidence'])
        restore_backup(create_backup(restored), self.data_dir.parent/'long-final-restored')

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

    def test_long_current_profile_can_be_read_in_pages_and_saved_without_repeating_full_fields(self):
        intro='<p>'+('A public biographical detail. '*5600)+' Last archival detail.</p>'
        created=self.call('/api/people',{'name':'Alex Vale','introduction_html':intro,'change_note':'Synthetic long public profile'})
        self.assertEqual(created.status_code,201,created.json)
        pid=created.json['id'];normal=self.respond
        def supplier(request,*args,**kwargs):
            if not request.full_url.endswith('/chat/completions'):return normal(request,*args,**kwargs)
            body=json.loads(request.data)
            self.assertLess(len(json.dumps(body,ensure_ascii=True)),110000)
            return normal(request,*args,**kwargs)
        def model():
            if self.rounds==1:return 'fetch',{'url':'https://uni.example/alex'}
            evidence=next(x['evidence_id'] for x in self.tool_results if x.get('method')=='deepseek-fetch-markdown')
            if self.rounds==2:return 'save_profile',{'target_type':'person','id':pid,'version':1,'data':{'chinese_name':'亚历克斯'},'evidence_id':evidence,'quote':'Alex Vale is a lecturer at North University.'}
            if self.rounds==3:
                self.assertEqual(self.tool_results[-1]['object']['version'],2)
                self.assertNotIn('before',self.tool_results[-1]);self.assertNotIn('changes',self.tool_results[-1])
                return 'read_field',{'target_type':'person','id':pid,'field':'introduction_html','offset':len(intro)-100,'limit':100}
            if self.rounds==4:
                self.assertIn('Last archival detail.',self.tool_results[-1]['text'])
                self.assertIsNone(self.tool_results[-1]['next_offset'])
                return 'read',{'target_type':'person','id':pid}
            return 'finish',{'reason':'已更新姓名，保留完整介绍。'}
        self.next_action=model;self.provider.side_effect=supplier
        q=self.call('/api/maintenance/jobs',{'target_type':'person','target_id':pid,'request_id':'long-profile'})
        self.call('/api/admin/maintenance/run',user='admin')
        state=self.job(q.json['id'])
        self.assertEqual(state['status'],'completed',state['reason'])
        current=self.clients['researcher'].get('/api/people/'+pid).json
        self.assertEqual(current['introduction_html'],intro)
        self.assertEqual(current['chinese_name'],'亚历克斯')

    def test_relationship_field_can_be_read_completely_before_replacing_one_of_ten_bylines(self):
        original=self.call('/api/people',{'name':'Original Author','change_note':'Synthetic identity'}).json['id']
        correct=self.call('/api/people',{'name':'Correct Author','change_note':'Independent synthetic identity'}).json['id']
        rows=[{'raw_name':f'Synthetic Author {i}','target_type':'person','target_id':original,'status':'confirmed','evidence':'Synthetic source https://uni.example/archive'} for i in range(10)]
        saved=self.call('/api/records/'+self.rid+'/bylines',{'version':0,'record_version':1,'items':rows,'change_note':'Synthetic ten authors'},method='PUT')
        self.assertEqual(saved.status_code,200,saved.json)
        self.call('/api/records/'+self.rid,{'version':1,'abstract':'Long public abstract. '*1000},method='PUT')
        expected=self.clients['researcher'].get('/api/records/'+self.rid+'/bylines').json['items']
        pieces=[];normal=self.respond
        def model():
            if self.rounds==1:return 'fetch',{'url':'https://uni.example/alex'}
            evidence=next(x['evidence_id'] for x in self.tool_results if x.get('method')=='deepseek-fetch-markdown')
            if self.rounds==2:return 'read',{'target_type':'record','id':self.rid}
            if self.rounds==3:
                relation=self.tool_results[-1]['object']['bylines']
                self.assertNotIn('omitted_items',json.dumps(relation))
                return 'read_field',{'target_type':'record','id':self.rid,'field':'bylines'}
            last=self.tool_results[-1]
            if last.get('field')=='bylines':
                self.assertNotIn('error',last)
                self.assertEqual(last['offset'],sum(len(p) for p in pieces))
                pieces.append(last['text'])
                if last['next_offset'] is not None:return 'read_field',{'target_type':'record','id':self.rid,'field':'bylines','offset':last['next_offset']}
                complete=json.loads(''.join(pieces))
                self.assertEqual([r['id'] for r in complete['items']],[r['id'] for r in expected])
                items=[{k:r[k] for k in ['id','raw_name','target_type','target_id']} for r in complete['items']]
                items[0]['target_id']=correct
                return 'set_bylines',{'id':self.rid,'version':complete['version'],'record_version':2,'items':items,'evidence_id':evidence,'quote':'Alex Vale is a lecturer at North University.'}
            if last.get('changed_target'):return 'read',{'target_type':'record','id':self.rid}
            return 'finish',{'reason':'已纠正一项，保留其他九项署名。'}
        self.next_action=model
        jid=self.queue('ten-bylines');self.call('/api/admin/maintenance/run',user='admin')
        self.assertEqual(self.job(jid)['status'],'completed',self.job(jid)['reason'])
        current=self.clients['researcher'].get('/api/records/'+self.rid+'/bylines').json['items']
        self.assertEqual([r['id'] for r in current],[r['id'] for r in expected])
        self.assertEqual([r['target_id'] for r in current],[correct]+[original]*9)

    def test_evidence_page_cursors_cover_exact_chinese_text_sent_to_model(self):
        text='公开资料段落'*700;pieces=[];normal=self.respond;sent_pages={}
        def supplier(request,*args,**kwargs):
            if request.full_url.endswith('/tools/fetch'):return Reply({'content':text},request.full_url)
            if request.full_url.endswith('/chat/completions'):
                for message in json.loads(request.data)['messages']:
                    if message['role']!='tool':continue
                    value=json.loads(message['content'])
                    if 'text' not in value or 'offset' not in value:continue
                    key=message['tool_call_id']
                    if key in sent_pages:self.assertEqual(value,sent_pages[key],'older pages retain the exact text and cursor already delivered')
                    sent_pages[key]=value
            return normal(request,*args,**kwargs)
        def model():
            if self.rounds==1:return 'fetch',{'url':'https://uni.example/alex'}
            evidence=next(x['evidence_id'] for x in self.tool_results if x.get('method')=='deepseek-fetch-markdown')
            last=self.tool_results[-1]
            if self.rounds==2:return 'read_evidence',{'evidence_id':evidence,'offset':0,'limit':4500}
            if 'offset' in last:
                self.assertEqual(last['offset'],sum(len(p) for p in pieces))
                self.assertEqual(last['text'],text[last['offset']:last['offset']+len(last['text'])])
                pieces.append(last['text'])
                if last['next_offset'] is not None:return 'read_evidence',{'evidence_id':evidence,'offset':last['next_offset'],'limit':4500}
                self.assertEqual(''.join(pieces),text)
                return 'read',{'target_type':'record','id':self.rid}
            return 'finish',{'reason':'资料已读取，暂无有据改动。'}
        self.next_action=model;self.provider.side_effect=supplier
        jid=self.queue('chinese-pages');self.call('/api/admin/maintenance/run',user='admin')
        self.assertEqual(self.job(jid)['status'],'completed',self.job(jid)['reason'])
        self.assertEqual(''.join(pieces),text)

    def test_exhausted_job_explicitly_continues_once_with_old_evidence_and_current_instructions(self):
        import hashlib,sqlite3,zipfile
        from platform_app.maintenance import create_backup,restore_backup
        from platform_app.maintenance_agent import run_pending
        self.next_action=lambda:('fetch',{'url':'https://uni.example/alex'}) if self.rounds==1 else ('read',{'target_type':'record','id':self.rid})
        jid=self.queue('exhausted-old-job');run_pending(self.data_dir)
        before=self.job(jid)
        self.assertEqual((before['status'],before['turns']),('failed',24))
        charges=self.clients['admin'].get('/api/admin/ai').json['attempts']
        # A valid old backup can contain the instructions frozen at job creation.
        # Change only that historical prompt in this synthetic fixture, preserving
        # the actual paid observations, call order, steps and ledger.
        backup=create_backup(self.data_dir)
        with zipfile.ZipFile(backup) as archive:files={n:archive.read(n) for n in archive.namelist()}
        database=self.data_dir.parent/'legacy-prompt.sqlite3';database.write_bytes(files['platform.sqlite3'])
        db=sqlite3.connect(database)
        with db:
            messages=json.loads(db.execute('SELECT messages_json FROM maintenance_jobs WHERE id=?',(jid,)).fetchone()[0])
            messages[0]['content']='Historical instructions: survey all unknowns before writing.'
            db.execute('UPDATE maintenance_jobs SET messages_json=? WHERE id=?',(json.dumps(messages),jid))
        db.close();files['platform.sqlite3']=database.read_bytes()
        manifest=json.loads(files['manifest.json']);manifest['files']['platform.sqlite3']={'bytes':len(files['platform.sqlite3']),'sha256':hashlib.sha256(files['platform.sqlite3']).hexdigest()};files['manifest.json']=json.dumps(manifest).encode()
        legacy=self.data_dir.parent/'legacy.zip'
        with zipfile.ZipFile(legacy,'w') as archive:
            for name,value in files.items():archive.writestr(name,value)
        restored=self.data_dir.parent/'continued';restore_backup(legacy,restored)
        self.data_dir=restored;self.app=create_app(restored,testing=True)
        self.clients={n:self.login(n) for n in ['researcher','colleague','admin']}
        response=self.call('/api/maintenance/jobs/'+jid+'/resume')
        self.assertEqual(response.status_code,200,response.json)
        grant=response.json['continuation']
        self.assertEqual((grant['from_turns'],grant['limit'],grant['actor_id']),(24,48,'researcher'))
        self.assertEqual(response.json['turns'],24)
        self.assertEqual(self.call('/api/maintenance/jobs/'+jid+'/resume').json['continuation'],grant)
        self.assertEqual(self.clients['admin'].get('/api/admin/ai').json['attempts'],charges)
        restore_backup(create_backup(restored),restored.parent/'granted-restored')
        normal=self.respond
        def supplier(request,*args,**kwargs):
            self.assertFalse(request.full_url.endswith('/tools/search') or request.full_url.endswith('/tools/fetch'))
            body=json.loads(request.data);self.assertIn('Work incrementally',body['messages'][0]['content'])
            self.assertNotIn('Historical instructions',body['messages'][0]['content'])
            return normal(request,*args,**kwargs)
        def model():
            evidence=next(x['evidence_id'] for x in self.tool_results if x.get('method')=='deepseek-fetch-markdown')
            if self.rounds==25:return 'save_record',{'id':self.rid,'version':1,'data':{'countries':'Latvia'},'evidence_id':evidence,'quote':'North University is in Latvia.'}
            if self.rounds==26:return 'read',{'target_type':'record','id':self.rid}
            return 'finish',{'reason':'保存有据字段，其余未知项留缺。'}
        self.next_action=model;self.provider.side_effect=supplier
        self.assertEqual(run_pending(restored),{'tasks':1,'completed':1})
        final=self.job(jid)
        self.assertEqual(final['turns'],27);self.assertEqual(final['steps'][:24],before['steps'])
        self.assertEqual(final['evidence'],before['evidence']);self.assertEqual(final['continuation'],grant)
        self.assertEqual(self.detail(self.rid)['countries'],'Latvia')
        restore_backup(create_backup(restored),restored.parent/'continued-final-restored')

    def test_continuation_cannot_renew_past_absolute_limit_or_restore_tampered_authorization(self):
        import hashlib,sqlite3,zipfile
        from platform_app.maintenance import create_backup,restore_backup
        from platform_app.maintenance_agent import run_pending
        self.next_action=lambda:('read',{'target_type':'record','id':self.rid})
        jid=self.queue('absolute-limit');run_pending(self.data_dir)
        self.assertEqual(self.job(jid)['turns'],24)
        self.assertEqual(self.call('/api/maintenance/jobs/'+jid+'/resume').status_code,200)
        run_pending(self.data_dir);self.assertEqual(self.job(jid)['turns'],48)
        charges=self.clients['admin'].get('/api/admin/ai').json['attempts']
        self.assertEqual(self.call('/api/maintenance/jobs/'+jid+'/resume').status_code,409)
        self.assertEqual(self.clients['admin'].get('/api/admin/ai').json['attempts'],charges)
        backup=create_backup(self.data_dir)
        with zipfile.ZipFile(backup) as archive:files={n:archive.read(n) for n in archive.namelist()}
        database=self.data_dir.parent/'bad-grant.sqlite3';database.write_bytes(files['platform.sqlite3']);db=sqlite3.connect(database)
        with db:
            grant=json.loads(db.execute('SELECT value FROM settings WHERE key=?',('maintenance_continuation:'+jid,)).fetchone()[0]);grant['limit']=72
            db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(grant),'maintenance_continuation:'+jid))
        db.close();files['platform.sqlite3']=database.read_bytes();manifest=json.loads(files['manifest.json']);manifest['files']['platform.sqlite3']={'bytes':len(files['platform.sqlite3']),'sha256':hashlib.sha256(files['platform.sqlite3']).hexdigest()};files['manifest.json']=json.dumps(manifest).encode()
        bad=self.data_dir.parent/'bad-grant.zip'
        with zipfile.ZipFile(bad,'w') as archive:
            for name,value in files.items():archive.writestr(name,value)
        with self.assertRaisesRegex(ValueError,'AI维护'):restore_backup(bad,self.data_dir.parent/'must-not-restore')

    def test_latest_progress_after_36_read_only_turns_guides_a_partial_save_before_more_pages(self):
        from platform_app.maintenance_agent import run_pending
        phase={'react':False};progress={};normal=self.respond
        def model():
            evidence=next((x['evidence_id'] for x in self.tool_results if x.get('method')=='deepseek-fetch-markdown'),'')
            if not phase['react']:
                if not evidence:return 'fetch',{'url':'https://uni.example/alex'}
                return 'read_evidence',{'evidence_id':evidence,'query':'Baltic cooperation'}
            self.assertEqual(progress['turn_limit'],48)
            if progress['saved_changes']==0:
                self.assertEqual(progress['phase'],'save_supported_partial_result_or_finish')
                self.assertGreaterEqual(progress['consecutive_read_only_steps'],36)
                self.assertEqual(progress['remaining_turns'],12)
                self.assertTrue(progress['available_evidence'])
                return 'save_record',{'id':self.rid,'version':1,'data':{'keywords':'波罗的海合作'},'evidence_id':evidence,'quote':'Baltic cooperation is authored by Alex Vale.'}
            if progress['phase']=='read_back_saved_changes':return 'read',{'target_type':'record','id':self.rid}
            return 'finish',{'reason':'已保存有据标签，未知编号留缺。'}
        def supplier(request,*args,**kwargs):
            nonlocal progress
            if phase['react'] and request.full_url.endswith('/chat/completions'):
                body=json.loads(request.data)
                self.assertEqual(body['messages'][-1]['role'],'user')
                progress=json.loads(body['messages'][-1]['content'])['maintenance_progress']
            return normal(request,*args,**kwargs)
        self.next_action=model;self.provider.side_effect=supplier
        jid=self.queue('readonly-trace');run_pending(self.data_dir)
        self.assertEqual(self.job(jid)['turns'],24)
        self.call('/api/maintenance/jobs/'+jid+'/resume')
        run_pending(self.data_dir,stopping=lambda:self.rounds>=36)
        self.assertEqual(self.job(jid)['turns'],36)
        self.assertEqual(self.detail(self.rid)['keywords'],'old label')
        before=sum(s['name'] in {'fetch','search'} for s in self.job(jid)['steps'])
        phase['react']=True
        self.assertEqual(run_pending(self.data_dir),{'tasks':1,'completed':1})
        final=self.job(jid)
        self.assertEqual(final['turns'],39)
        self.assertEqual(self.detail(self.rid)['keywords'],'波罗的海合作')
        self.assertEqual(sum(s['name'] in {'fetch','search'} for s in final['steps']),before)

    def profile_sources_flow(self,request_id,*,array_first=False):
        urls=['https://uni.example/alex','https://uni.example/alex/cv'];saved=[];normal=self.respond
        def supplier(request,*args,**kwargs):
            if request.full_url.endswith('/chat/completions'):
                body=json.loads(request.data)
                tool=next(t['function'] for t in body['tools'] if t['function']['name']=='save_profile')
                field=tool['parameters']['properties']['data']['properties']['sources']
                self.assertEqual(field['type'],'string');self.assertEqual(field['maxLength'],40000)
            if request.full_url.endswith('/tools/fetch'):
                return Reply({'content':'Alex Vale is a lecturer at North University. Public pages: '+', '.join(urls)},request.full_url)
            return normal(request,*args,**kwargs)
        def model():
            last=self.tool_results[-1] if self.tool_results else {}
            if self.rounds==1:return 'fetch',{'url':urls[0]}
            evidence=next(x['evidence_id'] for x in self.tool_results if x.get('method')=='deepseek-fetch-markdown')
            if self.rounds==2 or array_first and self.rounds==3:
                if self.rounds==3:
                    self.assertIn('data.sources',last['error']);self.assertIn('换行',last['error']);self.assertIn('全部出处',last['error'])
                    self.assertEqual(self.clients['researcher'].get('/api/people').json['total'],0)
                sources=urls if array_first and self.rounds==2 else '\n'.join(urls)
                return 'save_profile',{'target_type':'person','data':{'name':'Alex Vale','sources':sources},'evidence_id':evidence,'quote':'Alex Vale is a lecturer at North University.'}
            if last.get('changed_target'):
                saved.append(last['object']['id'])
                return 'read',{'target_type':'person','id':saved[-1]}
            if last.get('object',{}).get('id')!=self.rid:return 'read',{'target_type':'record','id':self.rid}
            return 'finish',{'reason':'已保存人物与全部出处。'}
        self.next_action=model;self.provider.side_effect=supplier
        jid=self.queue(request_id);self.call('/api/admin/maintenance/run',user='admin')
        state=self.job(jid);self.assertEqual(state['status'],'completed',state['reason'])
        self.assertEqual(len(saved),1)
        current=self.clients['researcher'].get('/api/people/'+saved[0]).json
        self.assertEqual(current['sources'],'\n'.join(urls))
        attempts=[s for s in state['steps'] if s['name']=='save_profile']
        self.assertEqual(len(attempts),2 if array_first else 1)
        self.assertEqual(sum(bool(s['result'].get('changed_target')) for s in attempts),1)

    def test_person_sources_contract_reaches_provider_and_newline_references_save_first_time(self):
        self.profile_sources_flow('typed-person-sources')

    def test_person_sources_array_error_preserves_all_references_for_explicit_retry(self):
        self.profile_sources_flow('retry-person-sources',array_first=True)

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
