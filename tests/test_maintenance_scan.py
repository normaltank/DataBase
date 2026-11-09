"""HTTP submissions and actual bounded background maintenance, with synthetic transport."""
import unittest
import io
import json
from unittest.mock import patch

from tests import test_maintenance_agent as fixture


class MaintenanceScanTests(unittest.TestCase):
    setUp = fixture.MaintenanceAgentTests.setUp
    login = fixture.MaintenanceAgentTests.login
    call = fixture.MaintenanceAgentTests.call
    source = fixture.MaintenanceAgentTests.source
    record = fixture.MaintenanceAgentTests.record
    detail = fixture.MaintenanceAgentTests.detail
    respond = fixture.MaintenanceAgentTests.respond
    next_action = fixture.MaintenanceAgentTests.next_action

    def jobs(self):
        return self.clients['researcher'].get('/api/maintenance/jobs').json['items']

    def inspect_only(self):
        def action():
            request = json.loads(self.provider.call_args.args[0].data)
            goal = json.loads(request['messages'][1]['content'])['goal']
            kind = 'record' if 'bylines' in goal else 'person' if 'employments' in goal else 'source'
            if not self.tool_results:
                return 'read', {'target_type': kind, 'id': goal['id']}
            return 'finish', {'reason': '已核对当前公开内容，暂缺的编号留空。'}
        self.next_action = action

    def test_overview_distinguishes_missing_configuration_and_pause(self):
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': ''}):
            overview = self.clients['researcher'].get('/api/maintenance/jobs').json['overview']
        self.assertEqual(overview['status'], 'needs_configuration')
        self.call('/api/admin/ai/pause', {'paused': True}, user='admin')
        overview = self.clients['researcher'].get('/api/maintenance/jobs').json['overview']
        self.assertEqual(overview['status'], 'paused')
        self.assertIn('管理员已暂停', overview['reason'])

    def test_overview_reports_portable_worker_failure_even_with_recent_heartbeat(self):
        from platform_app.maintenance_agent import run_pending
        run_pending(self.data_dir, limit=0)
        self.app.config['PORTABLE_AI_STATUS'] = lambda: {'configured': True, 'enabled': True,
            'worker_state': 'failed', 'worker_reason': '后台已停止，请重新启动。'}
        overview = self.clients['researcher'].get('/api/maintenance/jobs').json['overview']
        self.assertEqual(overview['status'], 'paused')
        self.assertEqual(overview['reason'], '后台已停止，请重新启动。')

    def test_ordinary_submission_is_maintained_without_opening_a_reader(self):
        response = self.call('/api/admin/maintenance/run', user='admin')
        self.assertEqual(response.json['completed'], 1)
        job = next(item for item in self.jobs() if item['target_id'] == self.rid)
        self.assertEqual(job['status'], 'completed')
        record = self.detail(self.rid)
        self.assertEqual(record['keywords'], 'Baltic cooperation')
        authors = self.clients['researcher'].get('/api/records/'+self.rid+'/bylines').json
        self.assertEqual(len(authors['items']), 1)
        self.assertEqual(authors['items'][0]['status'], 'confirmed')

    def test_restart_preserves_completed_article_and_related_profiles_continue_once(self):
        from platform_app.maintenance_agent import run_pending
        from platform_app.web import create_app
        self.call('/api/admin/maintenance/run', user='admin')
        first = next(job for job in self.jobs() if job['target_id'] == self.rid)
        self.inspect_only()
        create_app(self.data_dir, testing=True)
        run_pending(self.data_dir, limit=10)
        after = self.jobs()
        self.assertEqual([job['id'] for job in after if job['target_id'] == self.rid], [first['id']])
        self.assertEqual(len(after), 4)
        self.assertTrue(all(job['status'] == 'completed' for job in after), after)
        calls = self.provider.call_count
        for _ in range(3):
            run_pending(self.data_dir, limit=10)
        self.assertEqual(self.provider.call_count, calls)
        self.assertEqual(len(self.jobs()), 4)
        from platform_app.maintenance import create_backup, restore_backup
        restored = self.data_dir.parent/'restored'
        restore_backup(create_backup(self.data_dir), restored)
        create_app(restored, testing=True)
        run_pending(restored, limit=10)
        self.assertEqual(self.provider.call_count, calls)

    def test_actual_worker_dispatches_an_ordinary_submission_without_reader(self):
        from contextlib import redirect_stdout
        from platform_app.ingestion import run_worker
        self.inspect_only()
        output = io.StringIO()
        with redirect_stdout(output):
            run_worker(self.data_dir, once=True)
        self.assertEqual(json.loads(output.getvalue())['maintenance']['completed'], 1)
        self.assertEqual(self.jobs()[0]['status'], 'completed')

    def test_changed_version_and_monthly_review_enqueue_once_each(self):
        from platform_app.maintenance_agent import run_pending
        self.inspect_only()
        with patch('platform_app.store.now', return_value='2026-11-10T12:00:00+00:00'):
            run_pending(self.data_dir, limit=10)
            count = self.provider.call_count
            run_pending(self.data_dir, limit=10)
            self.assertEqual(self.provider.call_count, count)
            self.assertEqual(self.call('/api/records/'+self.rid, {'version': 1, 'keywords': 'changed'}, method='PUT').status_code, 200)
            run_pending(self.data_dir, limit=10)
            self.assertEqual(len(self.jobs()), 2)
        with patch('platform_app.store.now', return_value='2026-12-11T12:00:00+00:00'):
            run_pending(self.data_dir, limit=10)
            run_pending(self.data_dir, limit=10)
            self.assertEqual(len(self.jobs()), 3)
            self.assertTrue(all(job['status'] == 'completed' for job in self.jobs()))

    def test_budget_pause_and_new_configuration_resume_same_job_after_restart(self):
        from platform_app.maintenance_agent import run_pending
        from platform_app.web import create_app
        self.inspect_only()
        self.call('/api/admin/ai/config', {'cap': '0.000001', 'currency': 'CNY'}, user='admin')
        with patch('platform_app.store.now', return_value='2026-11-10T12:00:00+00:00'):
            run_pending(self.data_dir)
            first = self.jobs()[0]
            self.assertEqual(first['status'], 'paused')
            self.assertEqual(self.provider.call_count, 0)
            self.assertEqual(self.clients['researcher'].get('/api/maintenance/jobs').json['overview']['status'], 'paused')
        self.call('/api/admin/ai/config', {'cap': '10', 'currency': 'CNY'}, user='admin')
        create_app(self.data_dir, testing=True)
        with patch('platform_app.store.now', return_value='2026-11-10T12:02:00+00:00'):
            run_pending(self.data_dir)
        self.assertEqual([(job['id'], job['status']) for job in self.jobs()], [(first['id'], 'completed')])

    def test_old_external_reports_and_profiles_exclude_private_content_and_notes(self):
        from platform_app.maintenance_agent import run_pending
        from platform_app.web import create_app
        report = self.record(kind='report', title='Public institution report')
        private = self.record(kind='report', title='SECRET PRIVATE', visibility='restricted')
        internal = self.record(kind='research_report', title='SECRET MEMBER REPORT', sharing_confirmed=True)
        person = self.call('/api/people', {'name': 'Public Scholar', 'change_note': 'public profile'}).json['id']
        source = self.source(name='Public Institute', kind='institution', notes='SECRET INTERNAL NOTES')
        self.inspect_only()
        create_app(self.data_dir, testing=True)
        run_pending(self.data_dir, limit=10)
        ids = {job['target_id'] for job in self.jobs()}
        self.assertTrue({self.rid, report, person, source} <= ids)
        self.assertTrue({private, internal}.isdisjoint(ids))
        requests = '\n'.join(call.args[0].data.decode() for call in self.provider.call_args_list)
        self.assertNotIn('SECRET', requests)
        source_detail = self.clients['researcher'].get('/api/sources/'+source).json
        self.assertEqual(source_detail['notes'], 'SECRET INTERNAL NOTES')

    def test_article_backlog_does_not_starve_people_and_sources(self):
        from platform_app.maintenance_agent import run_pending
        for index in range(11):
            self.record(kind='report', title='Backlog '+str(index))
        person = self.call('/api/people', {'name': 'Queued Scholar', 'change_note': 'public'}).json['id']
        source = self.source(name='Queued Journal')
        run_pending(self.data_dir, limit=0)
        ids = {job['target_id'] for job in self.jobs()}
        self.assertTrue({person, source} <= ids)
        self.assertEqual(self.provider.call_count, 0)

    def test_new_collection_uses_agent_without_automatic_legacy_candidates(self):
        from tests.test_ingestion import IngestionTests
        from platform_app.maintenance_agent import run_pending
        sid = self.source(name='Synthetic LIIA', kind='think_tank', website='https://liia.lv/en/')
        with patch('platform_app.store.now', return_value='2026-10-27T12:00:00+00:00'):
            self.assertEqual(self.call('/api/sources/'+sid+'/ingestion', {'enabled': True}, user='admin', method='PUT').status_code, 200)
            self.assertEqual(IngestionTests.run_worker(self)['saved'], 2)
        legacy = self.clients['admin'].get('/api/admin/ai').json['tasks']
        self.assertEqual([task for task in legacy if task['task'] == 'record-authors-v1'], [])
        self.inspect_only()
        run_pending(self.data_dir, limit=10)
        collected = self.clients['researcher'].get('/api/records?source='+sid).json['items']
        self.assertEqual(len(collected), 2)
        completed = {job['target_id'] for job in self.jobs() if job['status'] == 'completed'}
        self.assertTrue({record['id'] for record in collected} <= completed)

    def test_ris_and_web_intake_save_into_the_same_automatic_path(self):
        from tests.test_assisted_intake import AssistedIntakeTests
        from platform_app.maintenance_agent import run_pending
        client = self.clients['researcher']
        csrf = client.get('/api/session').json['csrf']
        preview = client.post('/api/ris/preview', data={'file': (io.BytesIO(b'TY  - JOUR\nTI  - Public RIS article\nUR  - https://public.example/ris\nER  -\n'), 'public.ris')}, headers={'X-CSRF-Token': csrf})
        item = preview.json['items'][0]
        ris = self.call('/api/records', {**item['fields'], 'ris_token': item['token']})
        self.assertEqual(ris.status_code, 201, ris.json)
        web = AssistedIntakeTests.preview(self, '<title>Public web article</title>', 'https://public.example/web')
        self.assertEqual(web.status_code, 200, web.json)
        saved = self.call('/api/records', {**web.json['fields'], 'intake_token': web.json['token']})
        self.assertEqual(saved.status_code, 201, saved.json)
        self.inspect_only()
        run_pending(self.data_dir, limit=10)
        completed = {job['target_id'] for job in self.jobs() if job['status'] == 'completed'}
        self.assertTrue({ris.json['id'], saved.json['id']} <= completed)

    def test_legacy_automatic_queue_retires_but_explicit_suggestion_remains_available(self):
        from platform_app.archive_suggestions import run_pending
        for request in ['ingestion-new:historical:'+self.rid, 'explicit-legacy-request']:
            response = self.call('/api/archive-jobs', {'record_ids': [self.rid], 'request_id': request})
            self.assertEqual(response.status_code, 201, response.json)
        run_pending(self.data_dir, limit=0)
        jobs = self.clients['researcher'].get('/api/records/'+self.rid+'/suggestions').json['jobs']
        self.assertEqual(sorted(job['status'] for job in jobs), ['cancelled', 'queued'])
        self.assertEqual(self.provider.call_count, 0)


if __name__ == '__main__':
    unittest.main()
