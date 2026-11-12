"""Journal archive workflows at the authenticated public HTTP boundary."""
import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from platform_app.web import create_app


class JournalArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='journal-archive-')
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(self.temp.name, testing=True, embedded_worker=False)
        self.clients = {uid: self.login(uid) for uid in ['researcher', 'colleague', 'admin']}
        self.journal = self.call('/api/sources', {'name': 'Synthetic archive journal', 'kind': 'journal', 'issn': 'old unclassified identifier'}).json['id']
        self.base = '/api/journals/' + self.journal

    def login(self, uid, app=None):
        client = (app or self.app).test_client()
        csrf = client.get('/api/session').json['csrf']
        self.assertEqual(client.post('/api/login', json={'username': uid, 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf}).status_code, 200)
        return client

    def call(self, path, payload, method='POST', user='researcher'):
        client = self.clients[user]
        csrf = client.get('/api/session').json['csrf']
        return client.open(path, method=method, json=payload, headers={'X-CSRF-Token': csrf})

    def get(self, path, user='researcher'):
        response = self.clients[user].get(path)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def test_profile_keeps_precise_identifiers_versioned_metrics_and_unknown_values(self):
        profile = self.get(self.base)['profile']
        data = {'version': profile['version'], 'founded': '1980年代', 'frequency': '每年四期；旧周期不详',
                'frequency_evidence': 'Synthetic frequency statement', 'print_issn': '1111-1111',
                'electronic_issn': '2222-2222', 'publisher_text': 'Unlinked synthetic publisher',
                'metrics': [
                    {'id': 'metric-regular', 'kind': 'impact_factor', 'name': '普通影响因子', 'value': '0', 'year': '2024', 'released_year': '2025', 'evidence': 'Synthetic metric evidence'},
                    {'id': 'metric-five', 'kind': 'five_year', 'name': '五年影响因子', 'value': '2.5', 'year': '2024', 'evidence': 'Synthetic five year evidence'},
                    {'id': 'metric-unknown', 'kind': 'original', 'name': '未明口径', 'value': '', 'year': '', 'raw_label': 'SSCI 2/3 区', 'evidence': 'Unverified synthetic label'}],
                'rankings': [{'id': 'ranking-2024', 'year': '2024', 'edition': '合成修订版', 'evidence': 'Synthetic ranking evidence', 'subjects': [
                    {'level': 'major', 'original_name': 'Synthetic studies', 'chinese_name': '合成学科', 'quartile': '2'},
                    {'level': 'minor', 'original_name': 'Synthetic A', 'chinese_name': '', 'quartile': '2'},
                    {'level': 'minor', 'original_name': 'Synthetic B', 'chinese_name': '', 'quartile': '3'}]}],
                'indexing': 'SSCI 收录，原标注待核实'}
        response = self.call(self.base + '/profile', data, 'PUT')
        self.assertEqual(response.status_code, 200, response.json)
        saved = self.get(self.base)
        self.assertEqual(saved['profile']['metrics'][0]['value'], '0')
        self.assertEqual(saved['profile']['metrics'][2]['year'], '')
        self.assertEqual(saved['profile']['rankings'][0]['subjects'][2]['quartile'], '3')
        self.assertEqual(self.get('/api/sources/' + self.journal)['issn'], 'old unclassified identifier')
        stale = self.call(self.base + '/profile', data, 'PUT', 'colleague')
        self.assertEqual(stale.status_code, 409)
        changed = {**data, 'version': saved['profile']['version'], 'founded': '1982'}
        self.assertEqual(self.call(self.base + '/profile', changed, 'PUT', 'colleague').status_code, 200)
        history = self.get(self.base + '/profile/history')['items']
        self.assertEqual(history[1]['snapshot']['founded'], '1980年代')
        self.assertEqual(history[0]['actor_id'], 'colleague')
        institution = self.call('/api/sources', {'name': 'Synthetic institution', 'kind': 'institution'}).json['id']
        self.assertEqual(self.clients['researcher'].get('/api/journals/' + institution).status_code, 404)


if __name__ == '__main__':
    unittest.main()
