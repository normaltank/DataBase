import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from platform_app.maintenance import create_backup, restore_backup
from platform_app.store import SCHEMA, connect, initialize
from platform_app.web import create_app


class SourceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="source-catalog-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.app = create_app(self.data, testing=True)
        self.client = self.app.test_client()
        csrf = self.client.get('/api/session').json['csrf']
        self.client.post('/api/login', json={'username': 'admin', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf})

    def call(self, path, body, method='POST'):
        token = self.client.get('/api/session').json['csrf']
        return self.client.open(path, method=method, json=body, headers={'X-CSRF-Token': token})

    def source(self, name, **values):
        r = self.call('/api/sources', dict(name=name, kind='institution', **values)) if 'kind' not in values else self.call('/api/sources', dict(name=name, **values))
        self.assertEqual(r.status_code, 201, r.json)
        return r.json['id']

    def detail(self, sid):
        return self.client.get('/api/sources/' + sid).json

    def edit(self, sid, **values):
        return self.call('/api/sources/' + sid, dict(version=self.detail(sid)['version'], **values), 'PUT')

    def relation(self, target, kind='part_of'):
        return dict(type=kind, target_id=target, evidence='官方组织目录 https://example.org/structure', checked_on='2026-10-21')

    def test_country_multihost_international_combination_and_publisher_separation(self):
        lv = self.source('拉脱维亚机构', country='拉脱维亚', country_evidence='官网地址登记')
        ee = self.source('爱沙尼亚机构', country='爱沙尼亚', country_evidence='官网地址登记')
        uk = self.source('出版服务机构', country='英国', country_evidence='官网地址登记')
        j = self.source('联合期刊', kind='journal', host_id=lv+' | '+ee, publisher_id=uk,
                        host_evidence='办刊声明列出两家主办方', international_status='yes', international_evidence='期刊宗旨明确国际办刊')
        d = self.detail(j)
        self.assertEqual(set(d['national_countries']), {'拉脱维亚', '爱沙尼亚'})
        self.assertEqual(d['publisher_countries'], ['英国'])
        self.assertEqual(len(d['country_basis']), 2)
        for country in ['拉脱维亚', '爱沙尼亚']:
            r = self.client.get('/api/sources', query_string={'group':'journal','country':country,'international':'yes'}).json
            self.assertEqual([s['id'] for s in r['items']], [j])
        self.assertEqual(self.client.get('/api/sources?country=英国').json['total'], 0)

    def test_unknown_is_not_no_and_missing_or_conflicting_hosts_stay_pending(self):
        host = self.source('国家缺少依据', country='拉脱维亚')
        j = self.source('未知期刊', kind='journal', host_id=host, host_evidence='登记主办关系')
        self.assertEqual(self.detail(j)['national_status'], 'pending')
        self.assertEqual(self.client.get('/api/sources?international=no').json['total'], 0)
        self.assertEqual(self.client.get('/api/sources?international=unknown').json['total'], 1)
        self.assertEqual(self.client.get('/api/sources?country=__pending__').json['total'], 1)
        self.edit(host, country_evidence='官方地址')
        self.assertEqual(self.detail(j)['national_status'], 'recorded')
        self.edit(j, host_country_status='pending')
        self.assertEqual(self.detail(j)['national_countries'], [])
        self.assertEqual(self.detail(j)['candidate_countries'], ['拉脱维亚'])
        self.assertEqual(self.edit(j, international_status='no').status_code, 400)
        self.assertEqual(self.edit(j, international_status='yes').status_code, 400)
        self.assertEqual(self.edit(j, international_status='no', international_evidence='明确的本国限定办刊声明').status_code, 200)
        self.assertEqual(self.client.get('/api/sources?international=no').json['total'], 1)

    def test_country_or_host_change_without_replacement_evidence_invalidates_basis(self):
        a = self.source('机构A', country='拉脱维亚', country_evidence='原地址')
        b = self.source('机构B', country='爱沙尼亚', country_evidence='另一地址')
        j = self.source('期刊', kind='journal', host_id=a, host_evidence='原主办声明')
        self.edit(a, country='英国')
        self.assertEqual(self.detail(j)['national_status'], 'pending')
        self.edit(j, host_id=b)
        self.assertEqual(self.detail(j)['host_evidence'], '')
        self.assertEqual(self.detail(j)['national_status'], 'pending')
        self.edit(a,country_evidence='英国地址依据')
        self.edit(a,country='法国',country_evidence='英国地址依据')
        self.assertEqual(self.detail(a)['country_evidence'],'')
        self.edit(j,host_evidence='B 的主办声明')
        self.edit(j,host_id=a,host_evidence='B 的主办声明')
        self.assertEqual(self.detail(j)['host_evidence'],'')

    def test_original_classification_and_explicit_upstream_role_pending(self):
        from platform_app.source_catalog import initial_metadata
        row=dict(id='SER-OLD',kind='journal',host_id='SRC-A',raw_json=json.dumps(dict(
            host_institution_source_id='SRC-A',publisher_relationship='Publisher, host and platform role are pending production-side verification.')))
        self.assertEqual(initial_metadata(row)['host_country_status'],'pending')
        sid=self.source('工作论文',kind='serial',classification='working_paper_series')
        self.edit(sid,name='更新显示名称')
        self.assertEqual(self.detail(sid)['classification'],'working_paper_series')

    def test_groups_types_and_portals_preserve_identity(self):
        child = self.source('子机构', institution_types=['think_tank','research_institute'])
        old = self.source('旧出版物', kind='registry_publication')
        portal = self.source('门户', kind='portal')
        self.assertEqual(self.client.get('/api/sources?group=institution&institution_type=think_tank').json['items'][0]['id'], child)
        self.assertEqual(self.client.get('/api/sources?group=publication').json['items'][0]['id'], old)
        self.assertNotIn(portal, [s['id'] for s in self.client.get('/api/sources?directory=1').json['items']])
        self.assertEqual(self.client.get('/api/sources?group=maintenance').json['items'][0]['id'], portal)
        self.assertEqual(self.detail(portal)['id'], portal)
        self.assertEqual(self.edit(child, issn='1234-5678').status_code, 400)
        self.assertEqual(self.edit(child, international_status='yes',international_evidence='无关声明').status_code, 400)

    def test_type_correction_preserves_identity_applicable_fields_and_history(self):
        host = self.source('高校', institution_types=['university'])
        sid = self.source('登记类型有误的刊物', kind='serial', classification='working_paper_series',
                          host_id=host, host_evidence='既有主办依据', issn='1234-5678')
        self.assertEqual(self.edit(sid, kind='journal', international_status='yes', international_evidence='国际办刊声明').status_code, 200)
        journal = self.detail(sid)
        self.assertEqual((journal['id'], journal['issn'], journal['host_id'], journal['classification']),
                         (sid, '1234-5678', host, 'working_paper_series'))
        historic = self.client.get('/api/history/source/' + sid).json['items'][0]['id']
        self.assertEqual(self.edit(sid, kind='serial').status_code, 200)
        self.assertEqual(self.detail(sid)['international_status'], 'unknown')
        self.assertEqual(self.detail(sid)['international_evidence'], '')
        self.assertEqual(self.call(f'/api/history/{historic}/restore', {'version':self.detail(sid)['version']}).status_code, 200)
        self.assertEqual(self.detail(sid)['international_status'], 'yes')
        self.assertEqual(self.edit(host, kind='portal').status_code, 400)
        self.assertEqual(self.edit(sid, kind='institution').status_code, 200)
        for key in ['issn', 'host_id', 'publisher_id', 'host_evidence', 'international_evidence']:
            self.assertEqual(self.detail(sid)[key], '')
        self.assertEqual(self.edit(host, kind='portal').status_code, 200)
        self.assertEqual(self.detail(host)['institution_types'], [])
        self.edit(sid, relationships=[self.relation(self.source('上级机构'))])
        self.assertEqual(self.edit(sid, kind='journal').status_code, 400)

    def test_directed_links_multiple_founders_and_two_way_browsing(self):
        university, faculty, child, other = [self.source(n) for n in ['大学','学院','智库','共同设立方']]
        self.assertEqual(self.edit(faculty, relationships=[self.relation(university)]).status_code, 200)
        self.assertEqual(self.edit(child, institution_types=['think_tank'], relationships=[self.relation(faculty),self.relation(university,'established_by'),self.relation(other,'established_by'),self.relation(other,'funded_by')]).status_code, 200)
        self.assertEqual(self.detail(faculty)['related_from'][0]['source_id'], child)
        self.assertIn(faculty,[r['source_id'] for r in self.detail(university)['related_from']])
        self.assertEqual(len(self.detail(child)['relationships']),4)
        self.assertEqual(self.client.get('/api/sources?institution_type=think_tank').json['items'][0]['id'],child)

    def test_cycles_self_links_invalid_targets_duplicates_and_missing_evidence(self):
        a,b,c=[self.source(n) for n in ['机构甲','机构乙','机构丙']]
        j=self.source('期刊目标',kind='journal')
        self.edit(a,relationships=[self.relation(b)])
        self.edit(b,relationships=[self.relation(c)])
        for relations in [[self.relation(a)], [self.relation(c)], [self.relation(j)], [self.relation(b),self.relation(b)], [dict(self.relation(b),evidence='')]]:
            r=self.edit(c,relationships=relations)
            self.assertEqual(r.status_code,400,r.json)
        self.assertEqual(self.detail(c)['relationships'],[])
        self.edit(c,relationships=[self.relation(a,'cooperates_with')])
        self.assertEqual(self.edit(a,relationships=[self.relation(c,'cooperates_with')]).status_code,400)
        self.assertEqual(self.edit(b,kind='journal').status_code,400)

    def test_history_restore_and_conflict_check_including_new_graph_cycles(self):
        a,b=[self.source(n) for n in ['A','B']]
        self.edit(a,relationships=[self.relation(b)],institution_types=['think_tank'])
        historic=self.client.get('/api/history/source/'+a).json['items'][0]['id']
        version=self.detail(a)['version']
        self.edit(a,relationships=[])
        stale=self.call('/api/sources/'+a,{'version':version,'name':'过时编辑'},'PUT')
        self.assertEqual(stale.status_code,409)
        self.edit(b,relationships=[self.relation(a)])
        r=self.call(f'/api/history/{historic}/restore',{'version':self.detail(a)['version']})
        self.assertEqual(r.status_code,400,r.json)
        self.assertEqual(self.detail(a)['relationships'],[])
        self.edit(b,relationships=[])
        r=self.call(f'/api/history/{historic}/restore',{'version':self.detail(a)['version']})
        self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.detail(a)['relationships'][0]['target_id'],b)
        self.assertEqual(self.detail(a)['institution_types'],['think_tank'])
        self.assertEqual(self.detail(a)['status'],'pending')

    def test_legacy_snapshot_without_new_fields_preserves_new_metadata(self):
        a=self.source('原名称',country='拉脱维亚',country_evidence='机构依据',institution_types=['think_tank'])
        historic=self.client.get('/api/history/source/'+a).json['items'][0]['id']
        db=connect(self.data/'platform.sqlite3')
        with db:
            snapshot=json.loads(db.execute('SELECT snapshot_json FROM revisions WHERE id=?',(historic,)).fetchone()[0])
            from platform_app.source_catalog import DEFAULTS
            for key in DEFAULTS:snapshot.pop(key,None)
            db.execute('UPDATE revisions SET snapshot_json=? WHERE id=?',(json.dumps(snapshot),historic))
        db.close()
        self.edit(a,name='新名称',institution_types=['research_institute'])
        self.assertEqual(self.call(f'/api/history/{historic}/restore',{'version':2}).status_code,200)
        self.assertEqual(self.detail(a)['name'],'原名称')
        self.assertEqual(self.detail(a)['institution_types'],['research_institute'])

    def test_backup_restore_preserves_source_metadata_and_links(self):
        a,b=[self.source(n,country='拉脱维亚',country_evidence='机构官网') for n in ['机构1','机构2']]
        self.edit(a,relationships=[self.relation(b,'cooperates_with')])
        self.source('国际期刊',kind='journal',host_id=a,host_evidence='主办说明',international_status='yes',international_evidence='国际办刊定位声明')
        backup=create_backup(self.data)
        target=restore_backup(backup,self.root/'restored')
        first,second=connect(self.data/'platform.sqlite3'),connect(target/'platform.sqlite3')
        for table in ['sources','revisions','settings']:
            self.assertEqual([tuple(r) for r in first.execute('SELECT * FROM '+table)],[tuple(r) for r in second.execute('SELECT * FROM '+table)])
        first.close();second.close()

    def test_v1_migration_backs_up_is_idempotent_and_preserves_old_content(self):
        old=self.root/'legacy';old.mkdir()
        db=sqlite3.connect(old/'platform.sqlite3');db.executescript(SCHEMA)
        db.execute("INSERT INTO settings VALUES ('schema_version','1')")
        raw=json.dumps({'location':'Riga, Latvia','official_website':'https://example.org'})
        db.execute("INSERT INTO sources(id,name,kind,country,notes,version,raw_json,created_at,updated_at) VALUES ('KEPT-ID','人工名称','institution','拉脱维亚','人工备注',7,?,'old','old')",(raw,))
        db.commit();db.close()
        initialize(old)
        db=connect(old/'platform.sqlite3')
        row=dict(db.execute('SELECT * FROM sources').fetchone())
        self.assertEqual((row['id'],row['name'],row['notes']),('KEPT-ID','人工名称','人工备注'))
        self.assertEqual(row['version'],8)
        self.assertTrue(row['country_evidence'])
        revisions=db.execute('SELECT count(*) FROM revisions').fetchone()[0]
        original_backup=db.execute("SELECT value FROM settings WHERE key='source_catalog_migration_backup'").fetchone()[0]
        archive_count=len(list((old/'backups').glob('*.zip')))
        db.close()
        initialize(old)
        db=connect(old/'platform.sqlite3')
        self.assertEqual(db.execute('SELECT version FROM sources').fetchone()[0],8)
        self.assertEqual(db.execute('SELECT count(*) FROM revisions').fetchone()[0],revisions)
        db.close()
        archives=list((old/'backups').glob('*.zip'));self.assertEqual(len(archives),archive_count)
        self.assertGreaterEqual(len(archives),2)
        restored=restore_backup(original_backup,self.root/'legacy-restored')
        db=connect(restored/'platform.sqlite3')
        self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0],'1')
        self.assertEqual(db.execute('SELECT version FROM sources').fetchone()[0],7)
        db.close();initialize(restored)
        db=connect(restored/'platform.sqlite3')
        self.assertEqual(db.execute('SELECT name FROM sources').fetchone()[0],'人工名称');db.close()


if __name__=='__main__':
    unittest.main()
