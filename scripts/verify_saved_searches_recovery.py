"""Verify a real old complete backup upgrades without changing prior table rows/files."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import zipfile
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from platform_app.maintenance import restore_backup
from platform_app.web import create_app


def snapshot(path):
    with closing(sqlite3.connect(path)) as db:
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name: sorted([list(row) for row in db.execute('SELECT * FROM "'+name+'"')],key=repr) for name in names}


def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--evidence-dir',type=Path,required=True);args=p.parse_args()
    args.evidence_dir.mkdir(parents=True,exist_ok=True)
    target=restore_backup(args.archive,args.evidence_dir/'restored')
    before=snapshot(target/'platform.sqlite3')
    app=create_app(target,testing=True);client=app.test_client()
    def call(path,body):
        csrf=client.get('/api/session').json['csrf'];response=client.post(path,json=body,headers={'X-CSRF-Token':csrf});assert response.status_code<300,response.json;return response
    call('/api/login',{'username':'researcher','password':'LocalDemo2026!'}).close()
    saved=call('/api/saved-searches',{'name':'Recovered personal query','conditions':{'favorite':'1'}}).json
    after=snapshot(target/'platform.sqlite3')
    for name,rows in before.items():
        if name=='settings':
            rows=[r for r in rows if r[0] not in {'schema_version','saved_searches_migration_backup'}];actual=[r for r in after[name] if r[0] not in {'schema_version','saved_searches_migration_backup'}]
        else:actual=after[name]
        assert rows==actual,name
    with zipfile.ZipFile(args.archive) as archive:
        for name in archive.namelist():
            if name.startswith(('uploads/','avatars/')):assert archive.read(name)==(target/name).read_bytes(),name
    call('/api/login',{'username':'admin','password':'LocalDemo2026!'}).close()
    response=call('/api/backup',{});backup=args.evidence_dir/'schema11.zip';backup.write_bytes(response.data);response.close()
    restored=restore_backup(backup,args.evidence_dir/'second-restored');client=create_app(restored,testing=True).test_client()
    call('/api/login',{'username':'researcher','password':'LocalDemo2026!'}).close()
    assert client.get('/api/saved-searches/'+saved['id']).json['conditions']=={'favorite':'1'}
    result={'old_tables_preserved':len(before),'new_schema':client.get('/health').json['schema'],'saved_search_restored':True,'archive':str(args.archive)}
    (args.evidence_dir/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(result)

if __name__=='__main__':main()
