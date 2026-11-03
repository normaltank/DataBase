"""Collection selection HTTP seams; isolated data and controlled public transport only."""
import unittest
from unittest.mock import patch
from tests import test_ingestion as ingestion_tests


class IngestionSelectionTests(unittest.TestCase):
    setUp = ingestion_tests.IngestionTests.setUp
    call = ingestion_tests.IngestionTests.call
    source = ingestion_tests.IngestionTests.source
    run_worker = ingestion_tests.IngestionTests.run_worker

    def test_same_poll_request_after_completion_and_restart_does_not_queue_again(self):
        sid = self.source()
        path = '/api/sources/' + sid + '/ingestion'
        self.assertEqual(self.call(path, {'enabled': True}, user='admin', method='PUT').status_code, 200)
        first = self.call(path + '/run', {'request_id': 'lost-response-107'}, user='admin')
        self.assertEqual(first.status_code, 200, first.json)
        run_id = first.json['runs'][0]['id']
        self.assertEqual(self.run_worker()['saved'], 2)
        from platform_app.web import create_app
        client = create_app(self.app.config['DATA_DIR'], testing=True, embedded_worker=False).test_client()
        csrf = client.get('/api/session').json['csrf']
        csrf = client.post('/api/login', json={'username': 'admin', 'password': 'LocalDemo2026!'},
                           headers={'X-CSRF-Token': csrf}).json['csrf']
        replay = client.post(path + '/run', json={'request_id': 'lost-response-107'}, headers={'X-CSRF-Token': csrf})
        self.assertEqual(replay.status_code, 200, replay.json)
        self.assertEqual([(r['id'], r['status']) for r in replay.json['runs']], [(run_id, 'succeeded')])
        new = client.post(path + '/run', json={'request_id': 'new-intent-107'}, headers={'X-CSRF-Token': csrf})
        self.assertEqual(len(new.json['runs']), 2)

    def test_selected_sources_keep_individual_parameters_and_retry_after_partial_failure(self):
        first = self.source()
        second = self.call('/api/sources', dict(name='Synthetic GSSC', kind='think_tank', website='https://www.gssc.lt/en/')).json['id']
        third = self.call('/api/sources', dict(name='Synthetic CJIR', kind='journal', website='https://cjir.iir.cz/')).json['id']
        paths = ['/api/sources/' + sid + '/ingestion' for sid in (first, second, third)]
        selected = [dict(enabled=True, frequency_hours=11, inclusion_rule='all_opinions', backfill_days=60),
                    dict(enabled=True, frequency_hours=13, inclusion_rule='research_only', backfill_days=90)]
        self.assertEqual(self.call(paths[0], selected[0], user='admin', method='PUT').status_code, 200)
        invalid = {**selected[1], 'frequency_hours': 0}
        self.assertEqual(self.call(paths[1], invalid, user='admin', method='PUT').status_code, 400)
        self.assertEqual(self.clients['admin'].get(paths[1]).json['frequency_hours'], 24)
        self.assertEqual(self.call(paths[1], selected[1], user='admin', method='PUT').status_code, 200)
        for path, expected in zip(paths, selected):
            actual = self.clients['admin'].get(path).json
            self.assertEqual({key: actual[key] for key in expected}, expected)
            first_run = self.call(path + '/run', {'request_id': 'batch-107'}, user='admin')
            duplicate = self.call(path + '/run', {'request_id': 'batch-107'}, user='admin')
            self.assertEqual([r['id'] for r in first_run.json['runs']], [r['id'] for r in duplicate.json['runs']])
            self.assertEqual(len(duplicate.json['runs']), 1)
        self.assertFalse(self.clients['admin'].get(paths[2]).json['enabled'])
        self.assertEqual(self.clients['admin'].get(paths[2]).json['runs'], [])
        for path, original in zip(paths, selected):
            self.assertEqual(self.call(path, {**original, 'enabled': False}, user='admin', method='PUT').status_code, 200)
            disabled = self.clients['admin'].get(path).json
            self.assertFalse(disabled['enabled'])
            self.assertEqual(disabled['backfill_days'], original['backfill_days'])
            self.assertEqual(self.call(path + '/run', {'request_id': 'new-107'}, user='admin').status_code, 409)

    def test_support_and_authority_are_still_enforced_for_each_selected_source(self):
        sid = self.source()
        unsupported = self.call('/api/sources', dict(name='Synthetic unsupported', kind='think_tank', website='https://example.org/')).json['id']
        status = self.clients['admin'].get('/api/ingestion').json
        self.assertIn(sid, [s['source_id'] for s in status['items']])
        unavailable = next(s for s in status['unavailable'] if s['source_id'] == unsupported)
        self.assertIn('尚未接入', unavailable['reason'])
        for target in (sid, unsupported):
            path = '/api/sources/' + target + '/ingestion'
            self.assertEqual(self.call(path, {'enabled': True}, method='PUT').status_code, 403)
        path = '/api/sources/' + unsupported + '/ingestion'
        self.assertEqual(self.call(path, {'enabled': True}, user='admin', method='PUT').status_code, 422)
        self.assertEqual(self.call(path + '/run', {'request_id': 'unsupported-107'}, user='admin').status_code, 422)
        for bad in ('', 'x' * 101, 17):
            self.assertEqual(self.call('/api/sources/' + sid + '/ingestion/run', {'request_id': bad}, user='admin').status_code, 400)

    def test_lost_retry_response_can_be_replayed_after_worker_finishes(self):
        sid = self.source()
        path = '/api/sources/' + sid + '/ingestion'
        self.call(path, {'enabled': True}, user='admin', method='PUT')
        with patch.object(ingestion_tests.SourceSocket, 'fail_article', True):
            self.assertEqual(self.run_worker()['failed'], 2)
        run_id = self.clients['admin'].get(path).json['runs'][0]['id']
        retry_path = '/api/ingestion/runs/' + run_id + '/retry'
        first = self.call(retry_path, {'request_id': 'retry-lost-107'}, user='admin')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.run_worker()['saved'], 2)
        replay = self.call(retry_path, {'request_id': 'retry-lost-107'}, user='admin')
        self.assertEqual(replay.status_code, 200, replay.json)
        self.assertEqual([(r['id'], r['status']) for r in replay.json['runs']], [(run_id, 'succeeded')])
