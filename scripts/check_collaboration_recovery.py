"""Independent schema19 upgrade and new-directory recovery rehearsal.

The frozen baseline is extracted to Temp; it creates synthetic reports through
HTTP only. No user's data directory, template or ingestion entrypoint is used.
"""
import hashlib
import io
import json
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

BASELINE = "dddf4a6cf25b55c13bdd34d679292bdc1e3f46f9"

SEED = r'''
import io,json,sys
from pathlib import Path
from platform_app.web import create_app
app=create_app(Path(sys.argv[1]),testing=True)
c=app.test_client()
csrf=c.get('/api/session').json['csrf']
r=c.post('/api/login',json={'username':'researcher','password':'LocalDemo2026!'},headers={'X-CSRF-Token':csrf})
csrf=r.json['csrf']
r=c.post('/api/records',data={'data':json.dumps({'kind':'compilation','title':'旧版独立编译成果','body_html':'<p>迁移前作者正文</p>','sharing_confirmed':True}),'file':(io.BytesIO(b'legacy-original-one'),'legacy-one.txt')},headers={'X-CSRF-Token':csrf})
assert r.status_code==201,r.json
rid=r.json['id']
r=c.put('/api/records/'+rid,data={'data':json.dumps({'version':1,'body_html':'<p>迁移前第二版正文</p>','sharing_confirmed':True}),'file':(io.BytesIO(b'%PDF-1.4\nlegacy-original-two'),'legacy-two.pdf')},headers={'X-CSRF-Token':csrf})
assert r.status_code==200,r.json
payload={'schema':c.get('/health').json['schema'],'record':c.get('/api/records/'+rid).json,'history':c.get('/api/history/record/'+rid).json}
Path(sys.argv[2]).write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
'''


def login(app, name):
    c = app.test_client()
    csrf = c.get('/api/session').json['csrf']
    response = c.post('/api/login', json={'username': name, 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf})
    assert response.status_code == 200
    return c


def stored_record(payload):
    # Derived text indexes are rebuilt separately after portable recovery.
    result = json.loads(json.dumps(payload))
    for attached in result['attachments']:
        attached.pop('index', None)
    return result


def call(client, path, payload, file=None, method='POST'):
    headers = {'X-CSRF-Token': client.get('/api/session').json['csrf']}
    return client.open(path, method=method, headers=headers, **({'data': {'data': json.dumps(payload), 'file': (io.BytesIO(file), 'candidate.docx')}} if file else {'json': payload}))


def corrupt_archive(files, destination, mutation=None, missing=None, wrong_hash=False):
    files = dict(files)
    manifest = json.loads(files['manifest.json'])
    if mutation:
        database = destination.with_suffix('.sqlite3')
        database.write_bytes(files['platform.sqlite3'])
        with closing(sqlite3.connect(database)) as db, db:
            db.execute(mutation)
        files['platform.sqlite3'] = database.read_bytes()
        manifest['files']['platform.sqlite3'] = {'sha256': hashlib.sha256(files['platform.sqlite3']).hexdigest(), 'bytes': len(files['platform.sqlite3'])}
    if missing:
        files.pop(missing)
        manifest['files'].pop(missing)
    if wrong_hash:
        key = next(n for n in files if n.startswith('handoffs/'))
        files[key] = b'wrong original bytes'
        manifest['files'][key] = {'sha256': hashlib.sha256(files[key]).hexdigest(), 'bytes': len(files[key])}
    files['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(destination, 'w') as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def main():
    root = Path(__file__).resolve().parents[1]
    evidence = Path(tempfile.mkdtemp(prefix='database-collaboration-recovery-'))
    archive, legacy = evidence / 'schema19-source.zip', evidence / 'legacy-source'
    subprocess.run(['git', 'archive', BASELINE, 'platform_app', '-o', str(archive)], cwd=root, check=True, capture_output=True)
    with zipfile.ZipFile(archive) as source:
        source.extractall(legacy)
    data = evidence / 'data'
    subprocess.run([sys.executable, '-c', SEED, str(data), str(evidence / 'before.json')], cwd=legacy, check=True, capture_output=True)
    before = json.loads((evidence / 'before.json').read_text(encoding='utf-8'))
    assert before['schema'] == 19
    upgraded = create_app(data, testing=True)
    author, admin = login(upgraded, 'researcher'), login(upgraded, 'admin')
    assert author.get('/health').json['schema'] == 20
    rid = before['record']['id']
    assert author.get('/api/records/' + rid).json == before['record']
    assert author.get('/api/history/record/' + rid).json == before['history']
    for item in before['record']['attachments']:
        with author.get('/api/attachments/' + item['id']) as response:
            assert response.data == (b'legacy-original-one' if item['name'].endswith('.txt') else b'%PDF-1.4\nlegacy-original-two')
    with closing(sqlite3.connect(data / 'platform.sqlite3')) as db:
        migration_backup = Path(db.execute("SELECT value FROM settings WHERE key='collaboration_migration_backup'").fetchone()[0])
    previous = restore_backup(migration_backup, evidence / 'before-migration-restored')
    with closing(sqlite3.connect(previous / 'platform.sqlite3')) as db:
        assert db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0] == '19'
    assert stored_record(login(create_app(previous, testing=True), 'researcher').get('/api/records/' + rid).json) == stored_record(before['record'])
    assert call(admin, '/api/collaboration/qualifications/researcher', {'version': 0, 'enabled': True}, method='PUT').status_code == 200
    topic = call(author, '/api/collaboration/topics', {'theme': '恢复演练主题', 'participant_ids': ['colleague']}).json['id']
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as candidate:
        candidate.writestr('word/document.xml', '<document>synthetic recovery candidate</document>')
    original = stream.getvalue()
    for version in range(2):
        result = call(author, f'/api/collaboration/topics/{topic}/candidates', {'request_id': f'recovery-{version}', 'version': version, 'topic_version': 1, 'note': f'恢复原件{version}'}, original)
        assert result.status_code == 201
    with call(admin, '/api/backup', {}) as response:
        full = evidence / 'full.zip'
        full.write_bytes(response.data)
    recovered = evidence / 'new-directory-restored'
    subprocess.run([sys.executable, '-m', 'platform_app.maintenance', '--restore', str(full), '--target', str(recovered)], cwd=root, check=True, capture_output=True)
    restored = create_app(recovered, testing=True)
    peer = login(restored, 'colleague')
    submissions = peer.get(f'/api/collaboration/topics/{topic}/candidates').json['items']
    assert [s['version'] for s in submissions] == [2, 1]
    for item in submissions:
        with peer.get(item['file_url']) as response:
            assert response.data == original
    with zipfile.ZipFile(full) as z:
        files = {name: z.read(name) for name in z.namelist()}
    cases = [
        {'missing': next(n for n in files if n.startswith('handoffs/'))},
        {'wrong_hash': True},
        {'mutation': "UPDATE topic_candidates SET file_id='nonexistent' WHERE version=2"},
        {'mutation': "DELETE FROM qualification_events"},
        {'mutation': "UPDATE topic_participants SET active=0 WHERE member_id='researcher'"},
    ]
    for index, case in enumerate(cases):
        corrupt, target = evidence / f'corrupt-{index}.zip', evidence / f'rejected-{index}'
        corrupt_archive(files, corrupt, **case)
        try:
            restore_backup(corrupt, target)
        except ValueError:
            pass
        else:
            raise AssertionError(f'Corrupt case {index} was accepted')
        assert not target.exists()
    assert login(create_app(data, testing=True), 'researcher').get('/api/records/' + rid).json == before['record']
    result = {'baseline': BASELINE, 'schema_before': 19, 'schema_after': 20, 'preupgrade_backup_restored': True, 'old_record_history_and_attachment_bytes': True, 'candidate_versions_restored': 2, 'corrupt_archives_rejected': len(cases), 'original_directory_unchanged': True}
    (evidence / 'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'evidence': str(evidence), **result}))


if __name__ == '__main__':
    main()
