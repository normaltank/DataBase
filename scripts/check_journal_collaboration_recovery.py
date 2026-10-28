"""Actual schema21 application -> journal22, rollback and new-directory restore.

Only frozen public code and newly synthesized files are used. Pass the actual
integrated #70 commit, never an already upgraded private test directory.
"""
import argparse
import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_app.web import create_app
from platform_app.maintenance import restore_backup
from scripts.check_collaboration_recovery import login, stored_record

SEED = r'''
import io,json,sys
from pathlib import Path
from platform_app.web import create_app
app=create_app(Path(sys.argv[1]),testing=True)
def login(name):
    c=app.test_client()
    csrf=c.get('/api/session').json['csrf']
    r=c.post('/api/login',json={'username':name,'password':'LocalDemo2026!'},headers={'X-CSRF-Token':csrf})
    assert r.status_code==200,r.json
    return c
def call(c,path,data,raw=None,method='POST'):
    opts={'headers':{'X-CSRF-Token':c.get('/api/session').json['csrf']}}
    if raw is None:opts['json']=data
    else:opts['data']={'data':json.dumps(data),'file':(io.BytesIO(raw),'synthetic.txt')}
    r=c.open(path,method=method,**opts)
    assert r.status_code in (200,201),(path,r.status_code,r.json)
    return r.json
a,admin=login('researcher'),login('admin')
rid=call(a,'/api/records',{'kind':'compilation','title':'迁移前独立成果','body_html':'<p>原有作者正文</p>','sharing_confirmed':True},b'legacy journal attachment')['id']
call(a,'/api/records/'+rid,{'version':1,'body_html':'<p>原有第二版正文</p>'},method='PUT')
call(admin,'/api/collaboration/qualifications/researcher',{'version':0,'enabled':True},method='PUT')
tid=call(a,'/api/collaboration/topics',{'theme':'既存主题与候选','participant_ids':['colleague']})['id']
call(a,f'/api/collaboration/topics/{tid}/candidates',{'version':0,'topic_version':1,'request_id':'legacy-topic-candidate','note':'保留主题原件'},b'legacy topic candidate')
payload={'schema':a.get('/health').json['schema'],'record':a.get('/api/records/'+rid).json,'history':a.get('/api/history/record/'+rid).json,'topic_id':tid}
Path(sys.argv[2]).write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
'''


def call(client, path, payload, raw=None, method='POST'):
    headers={'X-CSRF-Token':client.get('/api/session').json['csrf']}
    return client.open(path,method=method,headers=headers,**({'json':payload} if raw is None else {'data':{'data':json.dumps(payload),'file':(io.BytesIO(raw),'journal-original.txt')}}))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline',required=True,help='Integrated #70 commit producing real schema21')
    baseline=parser.parse_args().baseline
    root=Path(__file__).resolve().parents[1]
    evidence=Path(tempfile.mkdtemp(prefix='database-journal-recovery-'))
    archive=evidence/'schema21-source.zip'
    subprocess.run(['git','archive',baseline,'platform_app','-o',str(archive)],cwd=root,check=True,capture_output=True)
    source=evidence/'schema21-source'
    with zipfile.ZipFile(archive) as z:z.extractall(source)
    data=evidence/'data'
    subprocess.run([sys.executable,'-c',SEED,str(data),str(evidence/'before.json')],cwd=source,check=True,capture_output=True)
    before=json.loads((evidence/'before.json').read_text(encoding='utf-8'))
    assert before['schema']==21,before['schema']
    # Failure after all DDL must roll back to the actual prior schema.
    failed=evidence/'failed-upgrade'
    shutil.copytree(data,failed)
    with closing(sqlite3.connect(failed/'platform.sqlite3')) as db,db:
        db.execute("CREATE TRIGGER fail_journal_migration BEFORE UPDATE ON settings WHEN OLD.key='schema_version' AND NEW.value='22' BEGIN SELECT RAISE(ABORT,'synthetic journal migration failure'); END")
    try:create_app(failed,testing=True)
    except sqlite3.IntegrityError:pass
    else:raise AssertionError('Migration failure was accepted')
    with closing(sqlite3.connect(failed/'platform.sqlite3')) as db,db:
        assert db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]=='21'
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='journal_works'").fetchone()
        db.execute('DROP TRIGGER fail_journal_migration')
    assert login(create_app(failed,testing=True),'researcher').get('/health').json['schema']==22
    app=create_app(data,testing=True)
    author,admin=login(app,'researcher'),login(app,'admin')
    assert author.get('/health').json['schema']==22
    rid=before['record']['id']
    assert author.get('/api/records/'+rid).json==before['record']
    assert author.get('/api/history/record/'+rid).json==before['history']
    with closing(sqlite3.connect(data/'platform.sqlite3')) as db:
        prebackup=Path(db.execute("SELECT value FROM settings WHERE key='journal_collaboration_migration_backup'").fetchone()[0])
    previous=restore_backup(prebackup,evidence/'preupgrade-restored')
    with closing(sqlite3.connect(previous/'platform.sqlite3')) as db:
        assert db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]=='21'
    assert stored_record(login(create_app(previous,testing=True),'researcher').get('/api/records/'+rid).json)==stored_record(before['record'])
    response=call(author,'/api/collaboration/journals',{'journal_name':'未建档合成期刊','coverage':'2024—2026跨期','source_clue':'https://example.invalid/synthetic','record_id':rid})
    assert response.status_code==201,response.json
    wid=response.json['id'];path='/api/collaboration/journals/'+wid
    expected=[b'journal manuscript one',b'journal product two']
    for version,raw in enumerate(expected,1):
        response=call(author,path+'/submissions',{'version':version,'request_id':'journal-recovery-'+str(version),'material_kind':'product' if version==2 else 'manuscript','note':'独立原件'},raw)
        assert response.status_code==201,response.json
    detail=author.get(path).json
    response=call(author,path+'/product',{'version':3,'submission_id':detail['submissions'][0]['id'],'note':'实际采用此原件','request_id':'journal-recovery-product'})
    assert response.status_code==200,response.json
    before_restore=author.get(path).json
    with call(admin,'/api/backup',{}) as response:
        full=evidence/'full.zip';full.write_bytes(response.data)
    target=evidence/'new-restored-directory'
    subprocess.run([sys.executable,'-m','platform_app.maintenance','--restore',str(full),'--target',str(target)],cwd=root,check=True,capture_output=True)
    restored=login(create_app(target,testing=True),'admin')
    detail=restored.get(path).json
    assert detail['current_product_id']==before_restore['current_product_id']
    assert len(restored.get(path+'/history').json['items'])==4
    hashes=[]
    for item,raw in zip(detail['submissions'],reversed(expected)):
        with restored.get(item['file_url']) as response:assert response.data==raw
        digest=hashlib.sha256(raw).hexdigest()
        assert item['sha256']==digest;hashes.append(digest)
    for item in restored.get('/api/collaboration/topics/'+before['topic_id']+'/candidates').json['items']:
        with restored.get(item['file_url']) as response:assert response.data==b'legacy topic candidate'
    assert stored_record(restored.get('/api/records/'+rid).json)==stored_record(before['record'])
    with restored.get('/api/attachments/'+before['record']['attachments'][0]['id']) as response:assert response.data==b'legacy journal attachment'
    result={'baseline':baseline,'schema_before':21,'schema_after':22,'preupgrade_backup_restored':True,'migration_failure_rolled_back_and_retry_ok':True,'old_record_history_and_attachment_bytes':True,'topic_original_retained':True,'journal_original_sha256':hashes,'product_and_four_events_restored':True,'target_was_new_directory':True}
    (evidence/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'evidence':str(evidence),**result},ensure_ascii=False))


if __name__=='__main__':main()
