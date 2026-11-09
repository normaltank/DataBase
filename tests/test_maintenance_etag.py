"""Conditional reads stay inside the authenticated HTTP representation boundary."""
import json
import unittest

from platform_app import store
from tests import test_maintenance_agent as fixture


class MaintenanceETagTests(unittest.TestCase):
    setUp = fixture.MaintenanceAgentTests.setUp
    login = fixture.MaintenanceAgentTests.login
    call = fixture.MaintenanceAgentTests.call
    source = fixture.MaintenanceAgentTests.source
    record = fixture.MaintenanceAgentTests.record
    queue = fixture.MaintenanceAgentTests.queue
    respond = fixture.MaintenanceAgentTests.respond
    next_action = fixture.MaintenanceAgentTests.next_action
    # Reuse only the synthetic setup/helpers, not the parent's test methods.
    def test_conditional_summary_detail_and_feedback_revalidate_before_304(self):
        jid = self.queue('conditional')
        urls = ['/api/maintenance/jobs?view=summary', '/api/maintenance/jobs/'+jid,
                '/api/maintenance/targets/record/'+self.rid]
        for url in urls:
            with self.subTest(url=url):
                client = self.clients['researcher']
                first = client.get(url)
                tag = first.headers.get('ETag')
                self.assertTrue(tag, 'An authenticated representation needs its own ETag')
                self.assertEqual(first.headers['Cache-Control'], 'no-store')
                cached = client.get(url, headers={'If-None-Match': 'W/'+tag})
                self.assertEqual(cached.status_code, 304)
                self.assertEqual(cached.data, b'')
                # Same visible content from a different actor is not the same tag.
                other = self.clients['colleague'].get(url, headers={'If-None-Match': tag})
                self.assertEqual(other.status_code, 200)
                self.assertNotEqual(other.headers['ETag'], tag)
                db = store.connect(self.data_dir/'platform.sqlite3')
                with db:
                    db.execute("UPDATE maintenance_jobs SET reason='Changed actual reason' WHERE id=?", (jid,))
                db.close()
                changed = client.get(url, headers={'If-None-Match': tag})
                self.assertEqual(changed.status_code, 200)
                self.assertNotEqual(changed.headers['ETag'], tag)
                db = store.connect(self.data_dir/'platform.sqlite3')
                with db:
                    db.execute("UPDATE maintenance_jobs SET reason='' WHERE id=?", (jid,))
                db.close()
        detail = self.clients['researcher'].get(urls[1])
        db = store.connect(self.data_dir/'platform.sqlite3')
        with db:
            db.execute("UPDATE records SET visibility='restricted' WHERE id=?", (self.rid,))
        db.close()
        self.assertEqual(self.clients['researcher'].get(urls[1], headers={'If-None-Match': detail.headers['ETag']}).status_code, 404)
        self.assertEqual(self.clients['researcher'].get(urls[2], headers={'If-None-Match': '*'}).status_code, 404)
        self.assertEqual(self.app.test_client().get(urls[1], headers={'If-None-Match': '*'}).status_code, 401)

    def test_dependency_revocation_changes_summary_and_forbids_selected_detail(self):
        source = self.source('Conditional source')
        jid = self.queue('dependency-conditional')
        db = store.connect(self.data_dir/'platform.sqlite3')
        with db:
            db.execute("UPDATE maintenance_jobs SET target_type='source',target_id=? WHERE id=?", (source, jid))
            db.execute('INSERT INTO maintenance_steps VALUES(?,?,1,?,?,?,?,?,?,?,?)',
                       ('conditional-step', jid, 'call', 'read', '{}', 'completed', json.dumps({'origin_record_id': self.rid}), '{}', store.now(), ''))
        db.close()
        summary = self.clients['researcher'].get('/api/maintenance/jobs?view=summary')
        detail = self.clients['researcher'].get('/api/maintenance/jobs/'+jid)
        db = store.connect(self.data_dir/'platform.sqlite3')
        with db:
            db.execute("UPDATE records SET visibility='restricted' WHERE id=?", (self.rid,))
        db.close()
        self.assertEqual(self.clients['researcher'].get('/api/maintenance/jobs/'+jid, headers={'If-None-Match': detail.headers['ETag']}).status_code, 404)
        response = self.clients['researcher'].get('/api/maintenance/jobs?view=summary', headers={'If-None-Match': summary.headers['ETag']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['items'], [])

    def test_same_account_role_and_active_status_are_rechecked(self):
        jid=self.queue('role-conditional')
        client=self.clients['admin']
        url='/api/maintenance/jobs/'+jid
        previous=client.get(url)
        db=store.connect(self.data_dir/'platform.sqlite3')
        with db:db.execute("UPDATE users SET role='researcher' WHERE id='admin'")
        db.close()
        current=client.get(url,headers={'If-None-Match':previous.headers['ETag']})
        self.assertEqual(current.status_code,200)
        self.assertNotEqual(current.headers['ETag'],previous.headers['ETag'])
        db=store.connect(self.data_dir/'platform.sqlite3')
        with db:db.execute("UPDATE users SET active=0 WHERE id='admin'")
        db.close()
        self.assertIn(client.get(url,headers={'If-None-Match':current.headers['ETag']}).status_code,(401,403))
