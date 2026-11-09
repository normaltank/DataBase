"""Public HTTP summary contract; synthetic SQL records, no provider calls."""
import json
import sqlite3
import unittest
from unittest.mock import patch

from platform_app import store
from tests import test_maintenance_agent as fixture


class MaintenanceSummaryTests(unittest.TestCase):
    setUp=fixture.MaintenanceAgentTests.setUp
    login=fixture.MaintenanceAgentTests.login
    call=fixture.MaintenanceAgentTests.call
    source=fixture.MaintenanceAgentTests.source
    record=fixture.MaintenanceAgentTests.record
    detail=fixture.MaintenanceAgentTests.detail
    queue=fixture.MaintenanceAgentTests.queue
    respond=fixture.MaintenanceAgentTests.respond
    next_action=fixture.MaintenanceAgentTests.next_action
    def test_summary_is_a_permission_window_and_never_loads_full_observations(self):
        source = self.source('Synthetic trace journal')
        jid = self.queue('long-observation')
        private = self.record(title='Private synthetic dependency', visibility='restricted')
        db = store.connect(self.data_dir/'platform.sqlite3')
        with db:
            template = dict(db.execute('SELECT * FROM maintenance_jobs WHERE id=?', (jid,)).fetchone())
            for n in range(107):
                row = {**template, 'id': f'allowed-{n:03}', 'request_id': f'allowed-{n}', 'created_at': f'2026-10-01T00:{n//60:02}:{n%60:02}+00:00'}
                db.execute(f"INSERT INTO maintenance_jobs ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", list(row.values()))
            # More than a window of newer jobs whose target is no longer public.
            for n in range(120):
                row = {**template, 'id': f'private-{n}', 'request_id': f'private-{n}', 'target_id': private}
                db.execute(f"INSERT INTO maintenance_jobs ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", list(row.values()))
            long = 'SYNTHETIC_FULL_OBSERVATION_' * 2000
            db.execute("INSERT INTO maintenance_steps VALUES(?,?,1,'call','read',?,'completed',?,?,?,'')", ('long-step', jid, json.dumps({'query': long}), json.dumps({'object': {'id': self.rid}, 'text': long}), json.dumps({'context': long}), store.now()))
            db.execute("INSERT INTO maintenance_evidence VALUES('long-evidence',?,?,'https://synthetic.example','fetch',?,?,?,?)", (jid, 'long-step', long, '0'*64, long, store.now()))
            # Public source task depending on now private material must disappear too.
            db.execute('UPDATE maintenance_jobs SET target_type=\'source\',target_id=? WHERE id=?', (source,jid))
            db.execute('UPDATE maintenance_steps SET result_json=? WHERE id=?', (json.dumps({'nested': [{'origin_record_id':private}], 'text':long}), 'long-step'))
        db.close()
        reads=[]
        connect=store.connect
        def observed(path):
            connection=connect(path)
            def authorizer(action, table, column, *_):
                if action==sqlite3.SQLITE_READ: reads.append((table,column))
                return sqlite3.SQLITE_OK
            connection.set_authorizer(authorizer)
            return connection
        with patch('platform_app.store.connect', side_effect=observed):
            response=self.clients['colleague'].get('/api/maintenance/jobs?view=summary')
        self.assertEqual(response.status_code,200,response.json)
        result=response.json
        self.assertEqual(len(result['items']),100)
        self.assertEqual(result['items'][0]['id'],'allowed-106')
        self.assertEqual(result['items'][-1]['id'],'allowed-007')
        self.assertTrue(result['window']['has_more'])
        self.assertEqual(result['window']['limit'],100)
        self.assertNotIn('SYNTHETIC_FULL_OBSERVATION',response.get_data(as_text=True))
        self.assertNotIn(('maintenance_evidence','text'),reads)
        self.assertNotIn(('maintenance_evidence','raw'),reads)
        self.assertNotIn(('maintenance_steps','arguments_json'),reads)
        self.assertNotIn(('maintenance_steps','ai_json'),reads)
        self.assertNotIn(('maintenance_jobs','messages_json'),reads)
        self.assertNotIn(('records','body_html'),reads)
        self.assertEqual(self.clients['colleague'].get('/api/maintenance/jobs/'+jid).status_code,404)
        full=self.clients['researcher'].get('/api/maintenance/jobs/'+jid)
        # The target is public but dependency rules intentionally exclude private records for everyone.
        self.assertEqual(full.status_code,404)
        db=store.connect(self.data_dir/'platform.sqlite3')
        with db:
            db.execute("DELETE FROM maintenance_jobs WHERE id IN ('allowed-000','allowed-001','allowed-002','allowed-003','allowed-004','allowed-005','allowed-006')")
        db.close()
        exactly=self.clients['colleague'].get('/api/maintenance/jobs?view=summary').json
        self.assertEqual(len(exactly['items']),100)
        self.assertFalse(exactly['window']['has_more'],'Private tasks must not influence has_more')

    def test_summary_zero_and_default_full_compatibility(self):
        self.assertEqual(self.clients['researcher'].get('/api/maintenance/jobs?view=summary').json['window']['has_more'],False)
        jid=self.queue('compatibility')
        full=self.clients['researcher'].get('/api/maintenance/jobs').json
        self.assertEqual(full['items'][0]['id'],jid)
        self.assertIn('steps',full['items'][0])
        self.assertIn('evidence',full['items'][0])
        brief=self.clients['researcher'].get('/api/maintenance/jobs?view=summary').json
        self.assertEqual(brief['items'][0]['step_count'],0)
        self.assertNotIn('steps',brief['items'][0])
        self.assertFalse(brief['window']['has_more'])

    def test_former_public_target_read_becomes_unavailable_for_owner_and_admin(self):
        jid=self.queue('target-revocation')
        response=self.call('/api/records/'+self.rid,{'version':1,'visibility':'restricted'},method='PUT')
        self.assertEqual(response.status_code,200,response.json)
        for actor in ['researcher','colleague','admin']:
            self.assertEqual(self.clients[actor].get('/api/maintenance/jobs/'+jid).status_code,404)
            self.assertEqual(self.clients[actor].get('/api/maintenance/jobs?view=summary').json['items'],[])
