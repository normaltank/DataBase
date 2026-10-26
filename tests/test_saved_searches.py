"""Personal saved conditions through public HTTP and complete recovery boundaries."""
from contextlib import closing
import io
import tempfile
import unittest
from pathlib import Path
from platform_app.web import create_app

class SavedSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='saved-search-test-')
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Path(self.temp.name)/'data', testing=True)
        self.client = self.app.test_client()
        self.login('researcher')

    def login(self, name):
        return self.call('/api/login', {'username':name,'password':'LocalDemo2026!'})

    def call(self, path, body, method='POST', status=None):
        token = self.client.get('/api/session').json['csrf']
        response = self.client.open(path, method=method, json=body, headers={'X-CSRF-Token':token})
        self.assertEqual(response.status_code, status, response.json) if status else self.assertLess(response.status_code, 300, response.json)
        return response.json

    def save(self, name='Saved', **conditions):
        return self.call('/api/saved-searches', {'name':name,'conditions':conditions})

    def test_saved_conditions_survive_restart_and_query_current_records(self):
        self.call('/api/records', {'title':'Latvia old','kind':'report'})
        saved = self.save(q='Latvia', sort='title')
        self.assertEqual(saved['conditions'], {'q':'Latvia','sort':'title'})
        record = self.call('/api/records', {'title':'Latvia new','kind':'report'})
        query = self.client.get('/api/records', query_string={'saved_search':saved['id']}).json
        self.assertEqual((query['total'],query['page']), (2,1))
        current = self.client.get('/api/records/'+record['id']).json
        self.call('/api/records/'+record['id'], {**current,'title':'Changed'}, 'PUT')
        self.assertEqual(self.client.get('/api/records',query_string={'saved_search':saved['id']}).json['total'],1)
        self.client = create_app(Path(self.temp.name)/'data', testing=True).test_client()
        self.login('researcher')
        self.assertEqual(self.client.get('/api/saved-searches/'+saved['id']).json['name'],'Saved')

    def test_validation_duplicate_names_and_csrf(self):
        self.save(' Same ')
        self.call('/api/saved-searches', {'name':'same','conditions':{}},status=409)
        for name, value in [('',{}),('x'*121,{}),('Bad',{'unknown':'x'}),('Bad',{'favorite':'0'}),
                            ('Bad',{'sort':'typo'}),('Bad',{'kind':'typo'}),('Bad',{'status':'typo'}),
                            ('Bad',{'from':'2026-13-30'}),('Bad',{'from':'2026-01-02','to':'2026-01-01'})]:
            self.call('/api/saved-searches', {'name':name,'conditions':value},status=400)
        self.assertEqual(self.client.post('/api/saved-searches',json={'name':'CSRF','conditions':{}}).status_code,403)

    def test_manage_conflicts_and_account_isolation_including_admin(self):
        saved = self.save()
        path = '/api/saved-searches/'+saved['id']
        renamed = self.call(path, {'name':'Renamed','version':1},'PUT')
        self.assertEqual((renamed['name'],renamed['version']),('Renamed',2))
        self.call(path, {'name':'Lost','version':1},'PUT',409)
        self.call(path, {'version':1},'DELETE',409)
        self.assertEqual(self.client.get(path).json['name'],'Renamed')
        changed = self.call(path, {'conditions':{'favorite':'1'},'version':2},'PUT')
        self.assertEqual(changed['conditions'],{'favorite':'1'})
        for member in ['colleague','admin']:
            self.login(member)
            self.assertEqual(self.client.get('/api/saved-searches').json['total'],0)
            self.assertEqual(self.client.get(path).status_code,404)
            self.assertEqual(self.client.get('/api/records',query_string={'saved_search':saved['id']}).status_code,404)
            self.call(path,{'name':'Stolen','version':3},'PUT',404)
            self.call(path,{'version':3},'DELETE',404)
        self.login('researcher')
        self.call(path,{'version':3},'DELETE')
        self.assertEqual(self.client.get(path).status_code,404)

    def test_complete_backup_restores_ownership_and_old_backup_upgrades(self):
        from platform_app.maintenance import restore_backup
        saved = self.save('Personal',favorite='1')
        self.login('admin')
        token = self.client.get('/api/session').json['csrf']
        response = self.client.post('/api/backup',json={},headers={'X-CSRF-Token':token})
        archive = Path(self.temp.name)/'backup.zip'
        archive.write_bytes(response.data)
        response.close()
        target = Path(self.temp.name)/'restored'
        restore_backup(archive,target)
        self.client = create_app(target,testing=True).test_client()
        self.login('researcher')
        self.assertEqual(self.client.get('/api/saved-searches/'+saved['id']).json['conditions'],{'favorite':'1'})
        self.login('admin')
        self.assertEqual(self.client.get('/api/saved-searches').json['total'],0)
        # Actual frozen older database fixture, exercised through full backup and restore.
        import sqlite3
        from platform_app.maintenance import create_backup
        old = Path(self.temp.name)/'old'
        old.mkdir()
        (old/'uploads').mkdir()
        with closing(sqlite3.connect(old/'platform.sqlite3')) as db:
            db.executescript((Path(__file__).parent/'fixtures/person_delivery_v9.sql').read_text(encoding='utf-8'))
        import base64, json
        fixture = json.loads((Path(__file__).parent/'fixtures/person_delivery_v9.json').read_text(encoding='utf-8'))
        for name, info in fixture['files'].items():
            path = old/name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(base64.b64decode(info['base64']))
        old_target = Path(self.temp.name)/'old-restored' 
        restore_backup(create_backup(old),old_target)
        self.client = create_app(old_target,testing=True).test_client()
        self.login('researcher')
        self.assertEqual(self.save('After old restore')['version'],1)

    def test_empty_saved_scope_never_expands_and_scope_rechecks_permissions(self):
        self.assertEqual(self.client.get('/api/records?saved_search=').status_code,400)
        collection = self.call('/api/collections', {'name':'Shared scope','visibility':'shared'})['id']
        self.login('colleague')
        saved = self.save('Scoped',collection=collection)
        self.login('researcher')
        current = self.client.get('/api/collections/'+collection).json
        self.call('/api/collections/'+collection,{**current,'visibility':'private'},'PUT')
        self.login('colleague')
        self.assertEqual(self.client.get('/api/records',query_string={'saved_search':saved['id'],'collection':''}).status_code,404)
        self.assertEqual(self.client.get('/api/saved-searches/'+saved['id']).json['conditions'],{'collection':collection})
        self.call('/api/saved-searches/'+saved['id'],{'name':'Still retained','version':1},'PUT')

    def test_all_effective_filters_and_bounded_name_search(self):
        source = self.call('/api/sources',{'name':'Source scope','kind':'institution'})['id']
        collection = self.call('/api/collections',{'name':'Scope','visibility':'private'})['id']
        record = self.call('/api/records',{'title':'Latvia combined','kind':'report','source_id':source,
                           'language':'en','countries':'Latvia','published_on':'2026-10-01'})['id']
        self.call('/api/collections/'+collection+'/items',{'record_id':record})
        self.call('/api/favorites/'+record,{'saved':True})
        values = dict(q='Latvia',kind='report',source=source,source_section='published',source_group='institution',
                      language='en',country='Latvia',status='pending',**{'from':'2026-01-01','to':'2026-12-31'},
                      collection=collection,sort='title',favorite='1',editable='1')
        saved = self.save('All effective conditions',**values)
        self.assertEqual(saved['conditions'],values)
        found = self.client.get('/api/records',query_string={'saved_search':saved['id']}).json
        self.assertEqual([r['id'] for r in found['items']],[record])
        for i in range(14):self.save('Extra %02d'%i,q='Missing')
        first = self.client.get('/api/saved-searches?q=extra&size=12').json
        second = self.client.get('/api/saved-searches?q=extra&size=12&page=2').json
        self.assertEqual((first['total'],len(first['items']),len(second['items'])),(14,12,2))
        self.assertEqual(self.client.get('/api/saved-searches?q=effective').json['total'],1)
        self.assertEqual(self.client.get('/api/saved-searches?q='+'x'*121).status_code,400)
        self.assertEqual(self.client.get('/api/saved-searches?page=bad').status_code,400)

    def test_source_merge_uses_old_identifier_and_favorites_recheck(self):
        keep = self.call('/api/sources',{'name':'Keep','kind':'institution'})['id']
        old = self.call('/api/sources',{'name':'Old','kind':'institution'})['id']
        record = self.call('/api/records',{'title':'Dynamic favorites','kind':'report','source_id':old})['id']
        saved = self.save('Old source favorites',source=old,favorite='1')
        self.call('/api/favorites/'+record,{'saved':True})
        self.login('admin')
        self.call('/api/merge',{'type':'source','keep_id':keep,'duplicate_id':old,'keep_version':1,'duplicate_version':1,'confirmed':True})
        self.login('researcher')
        self.assertEqual(self.client.get('/api/records',query_string={'saved_search':saved['id']}).json['total'],1)
        self.call('/api/favorites/'+record,{'saved':False})
        self.assertEqual(self.client.get('/api/records',query_string={'saved_search':saved['id']}).json['total'],0)

if __name__=='__main__': unittest.main()

