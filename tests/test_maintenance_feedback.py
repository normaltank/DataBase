"""Feedback acceptance through HTTP and the real bounded worker, synthetic provider only."""
import json
import threading
import unittest
from tests import test_maintenance_agent as agent_fixture
from platform_app.maintenance_agent import run_pending
from platform_app.web import create_app


class MaintenanceFeedbackTests(unittest.TestCase):
    setUp=agent_fixture.MaintenanceAgentTests.setUp
    login=agent_fixture.MaintenanceAgentTests.login
    call=agent_fixture.MaintenanceAgentTests.call
    source=agent_fixture.MaintenanceAgentTests.source
    record=agent_fixture.MaintenanceAgentTests.record
    detail=agent_fixture.MaintenanceAgentTests.detail
    respond=agent_fixture.MaintenanceAgentTests.respond
    next_action=agent_fixture.MaintenanceAgentTests.next_action
    job=agent_fixture.MaintenanceAgentTests.job
    queue=agent_fixture.MaintenanceAgentTests.queue

    def feedback(self,text='作者认错了，应为研究波罗的海的 Alex Vale。',request_id='feedback'):
        response=self.call('/api/maintenance/jobs',{'target_type':'record','target_id':self.rid,'request_id':request_id,'feedback':text})
        self.assertEqual(response.status_code,201,response.json)
        return response.json['id']

    def test_feedback_preempts_saved_old_context_and_keeps_history_after_restart(self):
        stop=threading.Event();normal=self.respond
        def interrupt(request,*args,**kwargs):
            value=normal(request,*args,**kwargs)
            if request.full_url.endswith('/chat/completions'):stop.set()
            return value
        self.provider.side_effect=interrupt
        old=self.queue('old')
        run_pending(self.data_dir,stopping=stop.is_set)
        self.assertEqual(self.job(old)['steps'][0]['status'],'pending')
        fresh=self.feedback()
        self.assertEqual(self.job(old)['status'],'cancelled')
        self.assertEqual(self.job(fresh)['priority'],100)
        self.call('/api/maintenance/jobs/'+old+'/resume')
        self.assertEqual(self.job(old)['status'],'cancelled')
        client=self.login('researcher',create_app(self.data_dir,testing=True))
        history=client.get('/api/maintenance/targets/record/'+self.rid)
        self.assertEqual(history.status_code,200,history.json)
        self.assertEqual([j['id'] for j in history.json['items']],[fresh,old])
        self.assertEqual(history.json['items'][1]['steps'][0]['status'],'pending')

    def test_feedback_requires_actual_new_investigation_before_completion(self):
        def model():
            if self.rounds==1:return 'read',{'target_type':'record','id':self.rid}
            if self.rounds==2:return 'finish',{'reason':'看起来没有问题。'}
            if self.rounds==3:
                self.assertIn('重新查证',self.tool_results[-1]['error'])
                return 'fetch',{'url':'https://uni.example/alex'}
            if self.rounds==4:return 'read',{'target_type':'record','id':self.rid}
            return 'finish',{'reason':'已对照公开资料，保留现有内容。'}
        self.next_action=model
        jid=self.feedback()
        run_pending(self.data_dir)
        self.assertEqual(self.job(jid)['status'],'completed',self.job(jid))
        self.assertEqual(len(self.job(jid)['evidence']),1)

    def prepare_wrong_identity(self):
        wrong=self.call('/api/people',{'name':'Alex Vale','introduction_html':'<p>物理学家。</p>','change_note':'合成真值：另一位同名人物'}).json['id']
        correct=self.call('/api/people',{'name':'Alex Vale','introduction_html':'<p>错误简介。</p>','change_note':'合成待纠正档案'}).json['id']
        response=self.call('/api/records/'+self.rid+'/bylines',{'version':0,'record_version':1,'items':[{'raw_name':'Alex Vale','target_type':'person','target_id':wrong,'status':'confirmed','evidence':'旧误认'}],'change_note':'合成旧误认'},method='PUT')
        self.assertEqual(response.status_code,200,response.json)
        return wrong,correct

    def correction_provider(self,correct,feedback):
        normal=self.respond
        def model():
            result=self.tool_results[-1] if self.tool_results else {}
            evidence=next((x['evidence_id'] for x in self.tool_results if x.get('method')=='deepseek-fetch-markdown'),'')
            basis={'evidence_id':evidence,'quote':'Alex Vale is a lecturer at North University.'}
            n=self.rounds
            if n==1:return 'search',{'query':'Alex Vale Baltic cooperation identity'}
            if n==2:return 'fetch',{'url':'https://uni.example/alex'}
            if n==3:return 'read',{'target_type':'record','id':self.rid}
            if n==4:return 'save_record',{'id':self.rid,'version':result['object']['version'],'data':{'keywords':'波罗的海合作'},**basis}
            if n==5:
                obj=result['object'];old=obj['bylines']['items'][0]
                return 'set_bylines',{'id':self.rid,'version':obj['bylines']['version'],'record_version':obj['version'],'items':[{'id':old['id'],'raw_name':old['raw_name'],'target_type':'person','target_id':correct}],**basis}
            if n==6:return 'read',{'target_type':'person','id':correct}
            if n==7:return 'save_profile',{'target_type':'person','id':correct,'version':result['object']['version'],'data':{'introduction_html':'<p>研究波罗的海合作的大学讲师。</p>'},**basis}
            if n==8:return 'read',{'target_type':'person','id':correct}
            if n==9:return 'read',{'target_type':'record','id':self.rid}
            return 'finish',{'reason':'已改正作者归属、标签与人物简介。'}
        def respond(request,*args,**kwargs):
            if request.full_url.endswith('/chat/completions'):
                body=json.loads(request.data)
                context=json.loads(next(m['content'] for m in body['messages'] if m['role']=='user'))
                self.assertIn(feedback,context['feedback'])
            return normal(request,*args,**kwargs)
        self.next_action=model
        return respond

    def test_feedback_corrects_formal_byline_nonempty_fields_and_future_maintenance(self):
        wrong,correct=self.prepare_wrong_identity()
        text='此文作者是研究波罗的海的讲师，不是物理学家；标签和简介也错了。'
        self.provider.side_effect=self.correction_provider(correct,text)
        jid=self.feedback(text)
        run_pending(self.data_dir)
        state=self.job(jid)
        self.assertEqual(state['status'],'completed',state)
        self.assertEqual(self.detail(self.rid)['keywords'],'波罗的海合作')
        self.assertEqual(self.detail(self.rid)['authors'],'Alex Vale')
        byline=self.clients['researcher'].get('/api/records/'+self.rid+'/bylines').json['items'][0]
        self.assertEqual(byline['target_id'],correct)
        self.assertEqual(byline['raw_name'],'Alex Vale')
        self.assertTrue(byline['machine'])
        self.assertEqual(self.clients['researcher'].get('/api/people/'+wrong+'/works').json['total'],0)
        self.assertEqual(self.clients['researcher'].get('/api/people/'+correct+'/works').json['items'][0]['id'],self.rid)
        self.assertIn('大学讲师',self.clients['researcher'].get('/api/people/'+correct).json['introduction_html'])
        change=next(s['result']['changes'] for s in state['steps'] if s['name']=='save_record')
        self.assertEqual(change['keywords'],{'before':'old label','after':'波罗的海合作'})
        self.assertTrue(state['evidence'])
        # Reopening the application and an ordinary follow-up job must carry the
        # original correction, rather than resetting to the pre-feedback context.
        self.app=create_app(self.data_dir,testing=True)
        self.clients={n:self.login(n) for n in ['researcher','colleague','admin']}
        self.rounds=0
        followup=self.queue('later-maintenance')
        run_pending(self.data_dir)
        self.assertEqual(self.job(followup)['status'],'completed',self.job(followup))
        self.assertEqual(self.clients['researcher'].get('/api/records/'+self.rid+'/bylines').json['items'][0]['target_id'],correct)
        self.rounds=0
        related=self.call('/api/maintenance/jobs',{'target_type':'person','target_id':correct,'request_id':'later-profile'}).json['id']
        run_pending(self.data_dir)
        self.assertEqual(self.job(related)['status'],'completed',self.job(related))

    def test_feedback_invalidates_running_response_before_it_can_replay_tools(self):
        old=self.queue('in-flight');normal=self.respond;fresh=[]
        def during_response(request,*args,**kwargs):
            value=normal(request,*args,**kwargs)
            if request.full_url.endswith('/chat/completions') and not fresh:
                fresh.append(self.feedback(request_id='new-in-flight'))
            return value
        self.provider.side_effect=during_response
        run_pending(self.data_dir)
        self.assertEqual(self.job(old)['status'],'cancelled')
        self.assertEqual(self.job(old)['steps'],[])
        self.assertEqual(self.job(fresh[0])['status'],'queued')
        self.assertEqual(self.detail(self.rid)['keywords'],'old label')

    def test_feedback_replaces_paused_unknown_request_without_replay_after_restore(self):
        from platform_app.maintenance import create_backup,restore_backup
        normal=self.respond;searches=[]
        def unknown(request,*args,**kwargs):
            if request.full_url.endswith('/tools/search'):
                searches.append(request.full_url)
                raise TimeoutError('合成未知响应')
            return normal(request,*args,**kwargs)
        self.provider.side_effect=unknown
        old=self.queue('paused');run_pending(self.data_dir)
        self.assertEqual(self.job(old)['status'],'paused')
        fresh=self.feedback()
        self.assertEqual(self.job(old)['status'],'cancelled')
        restored=self.data_dir.parent/'restored-feedback'
        restore_backup(create_backup(self.data_dir),restored)
        self.app=create_app(restored,testing=True)
        self.clients={n:self.login(n) for n in ['researcher','colleague','admin']}
        self.call('/api/maintenance/jobs/'+old+'/resume')
        self.assertEqual(self.job(old)['status'],'cancelled')
        self.assertEqual(self.job(old)['steps'][0]['status'],'pending')
        self.assertEqual(self.job(fresh)['feedback'],'作者认错了，应为研究波罗的海的 Alex Vale。')
        self.assertEqual(self.clients['admin'].get('/api/admin/ai').json['held_units'],5000)
        self.assertEqual(len(searches),1)

    def test_related_feedback_is_not_replayed_after_its_article_becomes_private(self):
        _,correct=self.prepare_wrong_identity();text='合成公开纠错说明-保密边界'
        self.provider.side_effect=self.correction_provider(correct,text)
        jid=self.feedback(text);run_pending(self.data_dir)
        self.assertEqual(self.job(jid)['status'],'completed')
        changed=self.call('/api/records/'+self.rid,{'version':2,'visibility':'restricted'},method='PUT')
        self.assertEqual(changed.status_code,200,changed.json)
        self.rounds=0;normal=self.respond
        self.next_action=lambda:('read',{'target_type':'person','id':correct}) if self.rounds==1 else ('finish',{'reason':'档案保持现状。'})
        def no_private_feedback(request,*args,**kwargs):
            if request.full_url.endswith('/chat/completions'):
                self.assertNotIn(text,json.dumps(json.loads(request.data),ensure_ascii=False))
            return normal(request,*args,**kwargs)
        self.provider.side_effect=no_private_feedback
        following=self.call('/api/maintenance/jobs',{'target_type':'person','target_id':correct,'request_id':'after-private'}).json['id']
        run_pending(self.data_dir)
        self.assertEqual(self.job(following)['status'],'completed',self.job(following))

    def test_feedback_cannot_expose_private_or_internal_material(self):
        for rid in [self.record(visibility='restricted'),self.record(kind='research_report')]:
            response=self.call('/api/maintenance/jobs',{'target_type':'record','target_id':rid,'request_id':'denied','feedback':'请改正'},user='colleague')
            self.assertIn(response.status_code,[400,404])
            self.assertIn(self.clients['colleague'].get('/api/maintenance/targets/record/'+rid).status_code,[400,404])
        self.assertEqual(self.rounds,0)


if __name__=='__main__':unittest.main()

