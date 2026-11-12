"""Build a real schema30 fixture with fixed predecessor code, then upgrade it.

All fixture creation and observations use authenticated HTTP. Git extraction,
the old database and full backups stay in the requested local evidence folder.
"""
import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from platform_app.web import create_app
from platform_app.maintenance import restore_backup
from portable.demo_seed import login, call

PREDECESSOR = '83e3ace0c8d60a1bbd04ec575f03a6aa429010b9'
LEGACY_SETUP = r'''
import json,sys,io
from pathlib import Path
from platform_app.web import create_app
app=create_app(Path(sys.argv[1]),testing=True,embedded_worker=False)
client=app.test_client()
csrf=client.get('/api/session').json['csrf']
assert client.post('/api/login',json={'username':'researcher','password':'LocalDemo2026!'},headers={'X-CSRF-Token':csrf}).status_code==200
def save(path,data,method='POST',file=None):
    token=client.get('/api/session').json['csrf']
    kwargs={'headers':{'X-CSRF-Token':token}}
    if file:kwargs['data']={'data':json.dumps(data),'file':(io.BytesIO(file),'legacy.txt')}
    else:kwargs['json']=data
    r=client.open(path,method=method,**kwargs)
    assert r.status_code in (200,201),(r.status_code,r.json)
    return r.json
sid=save('/api/sources',{'name':'Synthetic legacy journal','kind':'journal','issn':'legacy / unclassified; do not split','notes':'Preserve legacy source text'})['id']
article=save('/api/records',{'title':'Synthetic legacy article','kind':'journal_article','serial_id':sid,'volume':'original volume text','issue':'original issue text','abstract':'Original legacy abstract','sharing_confirmed':True},file=b'legacy original bytes')['id']
draft=save('/api/records',{'title':'Synthetic legacy cross-issue manuscript','kind':'directory_translation','authors':'Legacy synthetic compiler','coverage':'2023—2025 cross-issue free text','body_html':'<h2>Original heading</h2><p>Unsplit legacy manuscript.</p>','related_source_ids':[sid]})['id']
personal=save('/api/records',{'title':'Synthetic legacy personal compilation','kind':'compilation','author_id':'researcher','body_html':'<p>Personal responsibility unchanged.</p>'})['id']
assert client.get('/health').json['schema']==30
out={'schema':30,'source':client.get('/api/sources/'+sid).json,'article':client.get('/api/records/'+article).json,'draft':client.get('/api/records/'+draft).json,'personal':client.get('/api/records/'+personal).json}
Path(sys.argv[2]).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args()
    out = args.evidence.resolve()
    out.mkdir(parents=True, exist_ok=False)
    legacy = out / 'legacy-code'
    legacy.mkdir()
    result = subprocess.run(['git', 'archive', '--format=zip', PREDECESSOR, 'platform_app', 'templates', 'static'], cwd=ROOT, capture_output=True, check=True)
    with zipfile.ZipFile(io.BytesIO(result.stdout)) as archive:
        archive.extractall(legacy)
    data, before_path = out / 'legacy-data', out / 'before.json'
    subprocess.run([sys.executable, '-c', LEGACY_SETUP, str(data), str(before_path)], cwd=legacy, check=True, capture_output=True)
    before = json.loads(before_path.read_text(encoding='utf-8'))
    app = create_app(data, testing=True, embedded_worker=False)
    client = login(app, 'researcher')
    colleague = login(app, 'colleague')
    sid = before['source']['id']
    assert client.get('/health').json['schema'] == 31
    assert client.get('/api/sources/' + sid).json['issn'] == 'legacy / unclassified; do not split'
    for kind in ['article', 'draft', 'personal']:
        old = before[kind]
        current = client.get('/api/records/' + old['id']).json
        for field in ['id', 'kind', 'version', 'body_html', 'coverage', 'authors', 'owner_id', 'author_id', 'author_confirmed', 'visibility', 'editors', 'volume', 'issue']:
            assert current[field] == old[field], (kind, field)
    journal = client.get('/api/journals/' + sid).json
    assert journal['profile']['version'] == 0 and not journal['issues'] and not journal['compilations']
    article = before['article']
    aid = article['attachments'][0]['id']
    with client.get('/api/attachments/' + aid) as response:
        assert response.data == b'legacy original bytes'
    draft_id = before['draft']['id']
    call(colleague, '/api/records/' + draft_id, {'version': before['draft']['version'], 'body_html': '<p>Legacy whole manuscript remains coeditable.</p>'}, method='PUT')
    csrf = colleague.get('/api/session').json['csrf']
    denied = colleague.put('/api/records/' + before['personal']['id'], json={'version': 1, 'body_html': 'forbidden'}, headers={'X-CSRF-Token': csrf})
    assert denied.status_code == 403
    call(client, '/api/journals/' + sid + '/profile', {'version': 0, 'print_issn': 'synthetic verified print label'}, method='PUT')
    assert client.get('/api/sources/' + sid).json['issn'] == 'legacy / unclassified; do not split'
    admin = login(app, 'admin')
    with admin.post('/api/backup', json={}, headers={'X-CSRF-Token': admin.get('/api/session').json['csrf']}) as response:
        assert response.status_code == 200
        backup = out / 'upgraded-complete.zip'
        backup.write_bytes(response.data)
    target = out / 'new-restored-data'
    restore_backup(backup, target)
    restored = login(create_app(target, testing=True, embedded_worker=False), 'researcher')
    assert restored.get('/api/journals/' + sid).json['profile']['print_issn'] == 'synthetic verified print label'
    with restored.get('/api/attachments/' + aid) as response:
        assert response.data == b'legacy original bytes'
    with restored.get('/api/export/content') as response:
        assert response.status_code == 200
        (out / 'readable-content.zip').write_bytes(response.data)
    report = {'predecessor_sha': PREDECESSOR, 'schema_before': 30, 'schema_after': 31,
              'stable_ids': True, 'unclassified_issn_preserved': True, 'no_inferred_issues': True,
              'whole_manuscript_coeditable': True, 'personal_authorization_preserved': True,
              'original_attachment_bytes_preserved': True, 'new_directory_restore': True, 'real_ai_calls': 0}
    (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
