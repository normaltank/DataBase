"""Source scope queries at the member HTTP and export boundaries (#28)."""
import csv
import io
import json
import tempfile
import unittest
import zipfile

from platform_app.web import create_app


class LibrarySourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='library-sources-')
        self.addCleanup(self.temp.cleanup)
        self.client = create_app(self.temp.name, testing=True).test_client()
        self.call('/api/login', dict(username='researcher', password='LocalDemo2026!'))

    def call(self, path, values, method='POST'):
        token = self.client.get('/api/session').json['csrf']
        result = self.client.open(path, method=method, json=values, headers={'X-CSRF-Token': token})
        self.assertLess(result.status_code, 300, result.json)
        return result.json

    def source(self, name, **values):
        return self.call('/api/sources', dict(name=name, kind='institution', **values))['id'] if 'kind' not in values else self.call('/api/sources', dict(name=name, **values))['id']

    def record(self, title, **values):
        return self.call('/api/records', dict(title=title, kind='report', **values))['id']

    def ids(self, **query):
        result = self.client.get('/api/records', query_string=query)
        self.assertEqual(result.status_code, 200, result.json)
        return {row['id'] for row in result.json['items']}

    def test_combination_matches_one_source_and_keeps_research_country_separate(self):
        lv = self.source('Latvian host', country='拉脱维亚', country_evidence='官方地址')
        ee = self.source('Estonian host', country='爱沙尼亚', country_evidence='官方地址')
        uk = self.source('Publisher', country='英国', country_evidence='官方地址')
        journal = self.source('Joint journal', kind='journal', host_id=lv+' | '+ee, publisher_id=uk,
                              host_evidence='联合主办声明', international_status='yes', international_evidence='国际办刊宗旨')
        foreign = self.source('Foreign journal', kind='journal', host_id=uk, host_evidence='主办声明')
        article = self.record('Journal work', serial_id=journal, countries='法国')
        general = self.record('General association', related_source_ids=[journal])
        cross_source = self.record('Cross source false positive', source_id=lv, serial_id=foreign)
        self.record('Institution work', source_id=lv)
        query = dict(source_group='journal', source_country='拉脱维亚', source_international='yes')
        self.assertEqual(self.ids(**query), {article, general})
        self.assertEqual(self.ids(**query, country='法国'), {article})
        self.assertEqual(self.ids(source_group='journal', source_country='英国'), {cross_source})
        self.assertEqual(self.ids(**{**query, 'source_country':'爱沙尼亚'}), {article, general})
        self.assertEqual(self.ids(**query, source=lv), set())

    def test_pending_publications_three_states_and_invalid_filters(self):
        host = self.source('Host', country='法国', country_evidence='官方地址')
        pending = self.source('Pending journal', kind='journal')
        local = self.source('Local journal', kind='journal', host_id=host, host_evidence='主办声明',
                            international_status='no', international_evidence='限定本国办刊')
        serial = self.source('Working papers', kind='serial', host_id=host, host_evidence='主办声明')
        unknown = self.record('Pending work', serial_id=pending)
        known = self.record('Local work', serial_id=local)
        paper = self.record('Working paper', related_source_ids=[serial])
        self.assertEqual(self.ids(source_country='__pending__'), {unknown})
        self.assertEqual(self.ids(source_international='unknown'), {unknown})
        self.assertEqual(self.ids(source_international='no'), {known})
        self.assertEqual(self.ids(source_group='publication', source_country='法国'), {paper})
        for path in ['/api/records', '/api/export', '/api/export/content']:
            for query in [dict(source_group='invalid'), dict(source_international='maybe'),
                          dict(source_group='institution', source_international='yes')]:
                self.assertEqual(self.client.get(path, query_string=query).status_code, 400)

    def test_exports_pagination_permissions_old_id_and_source_sections_share_scope(self):
        host = self.source('Host', country='法国')
        alias = self.source('Old host', country='法国')
        ids = {self.record('Public %02d' % i, source_id=host) for i in range(14)}
        self.record('Private', source_id=host, visibility='restricted')
        self.call('/api/logout', {})
        self.call('/api/login', dict(username='admin', password='LocalDemo2026!'))
        self.call('/api/merge', dict(type='source', keep_id=host, duplicate_id=alias,
                                     keep_version=1, duplicate_version=1, confirmed=True))
        self.call('/api/logout', {})
        self.call('/api/login', dict(username='colleague', password='LocalDemo2026!'))
        query = dict(source_group='institution', source_country='法国', source=alias, source_section='published')
        first = self.client.get('/api/records', query_string={**query, 'size':12}).json
        second = self.client.get('/api/records', query_string={**query, 'size':12, 'page':2}).json
        self.assertEqual((first['total'], len(first['items']), len(second['items'])), (14, 12, 2))
        self.assertEqual({r['id'] for r in first['items']+second['items']}, ids)
        csv_result = self.client.get('/api/export', query_string=query)
        self.assertEqual({r[0] for r in list(csv.reader(io.StringIO(csv_result.data.decode('utf-8-sig'))))[1:]}, ids)
        output = self.client.get('/api/export/content', query_string=query)
        self.assertEqual(output.status_code, 200, output.json if output.is_json else '')
        with zipfile.ZipFile(io.BytesIO(output.data)) as archive:
            payload = json.loads(archive.read('content.json'))
            self.assertEqual(set(payload['selected_ids']), ids)


if __name__ == '__main__':
    unittest.main()
