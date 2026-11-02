"""Frozen schema23 -> 24, preserving legacy source/history/account permissions."""
import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from platform_app.web import create_app
from platform_app.maintenance import create_backup, restore_backup

BASELINE = 'ed4d1fc5a617f48040fc015e4e7c396f221fa1b0'


def login(app, name):
    client = app.test_client()
    csrf = client.get('/api/session').json['csrf']
    response = client.post('/api/login', json={'username': name, 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf})
    assert response.status_code == 200
    return client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence
    evidence.mkdir(parents=True, exist_ok=True)
    frozen = evidence / 'schema23-source'
    if frozen.exists(): raise ValueError('Use a new evidence directory to preserve prior runs.')
    archive = evidence / 'schema23-source.zip'
    subprocess.run(['git', 'archive', BASELINE, '-o', str(archive)], cwd=ROOT, check=True)
    with zipfile.ZipFile(archive) as source: source.extractall(frozen)
    data = evidence / 'data'
    seed = '''import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from platform_app.web import create_app
app=create_app(Path(sys.argv[2]),testing=True)
client=app.test_client()
csrf=client.get('/api/session').json['csrf']
auth=client.post('/api/login',json={'username':'researcher','password':'LocalDemo2026!'},headers={'X-CSRF-Token':csrf}).json
h={'X-CSRF-Token':auth['csrf']}
sid=client.post('/api/sources',json={'name':'Legacy synthetic source','kind':'institution','location':'Legacy place','country':'Latvia','country_evidence':'Synthetic original country basis'},headers=h).json['id']
client.put('/api/sources/'+sid,json={'version':1,'research_scope':'Human legacy scope'},headers=h)
rid=client.post('/api/records',json={'title':'Legacy personal report','kind':'research_report','sharing_confirmed':True,'body_html':'<p>Legacy original report body.</p>'},headers=h).json['id']
print(json.dumps({'source_id':sid,'record_id':rid,'schema':client.get('/health').json['schema'],'source':client.get('/api/sources/'+sid).json,'history':client.get('/api/history/source/'+sid).json}))
'''
    seeded = subprocess.run([sys.executable, '-B', '-c', seed, str(frozen), str(data)], cwd=evidence,
                            check=True, capture_output=True, text=True, encoding='utf-8')
    expected = json.loads(seeded.stdout)
    assert expected['schema'] == 23
    app = create_app(data, testing=True)
    author, colleague = login(app, 'researcher'), login(app, 'colleague')
    assert author.get('/health').json['schema'] == 24
    sid, rid = expected['source_id'], expected['record_id']
    source = author.get('/api/sources/' + sid).json
    assert source == expected['source']
    assert author.get('/api/history/source/' + sid).json == expected['history']
    assert colleague.get('/api/records/' + rid).json['can_edit'] is False
    assert author.get('/api/records/' + rid).json['body_html'] == '<p>Legacy original report body.</p>'
    assert author.get('/api/sources/' + sid + '/suggestions').json['candidates'] == []
    backups = list((data / 'backups').glob('*.zip'))
    versions = []
    for index, backup in enumerate(backups):
        with zipfile.ZipFile(backup) as package:
            import sqlite3
            dbpath = evidence / ('backup-' + str(index) + '.sqlite3')
            dbpath.write_bytes(package.read('platform.sqlite3'))
            db = sqlite3.connect(dbpath)
            version = int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0])
            db.close()
        if version == 23:
            previous = evidence / 'restored-pre-upgrade'
            restore_backup(backup, previous)
            assert login(create_app(previous, testing=True), 'researcher').get('/api/sources/' + sid).json['research_scope'] == 'Human legacy scope'
        versions.append(version)
    assert versions.count(23) == 1, versions
    complete = create_backup(data)
    target = evidence / 'restored-new-directory'
    restore_backup(complete, target)
    restored = login(create_app(target, testing=True), 'colleague')
    assert restored.get('/api/sources/' + sid).json == source
    assert restored.get('/api/records/' + rid).json['can_edit'] is False
    result = {'baseline': BASELINE, 'schema_before': 23, 'schema_after': 24, 'legacy_source_and_history_unchanged': True,
              'legacy_personal_permission_preserved': True, 'preupgrade23_backup_restored': True, 'new_directory_restore': True}
    (evidence / 'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__': main()
