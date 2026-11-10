"""Isolated DOM→Flask selection flow; no listening port, worker or provider.

Requires Node and jsdom (NODE_PATH may point to a temporary dependency install).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_app.web import create_app


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="selection108-http-") as temporary:
        app = create_app(Path(temporary) / "data", testing=True, embedded_worker=False)
        client = app.test_client()
        csrf = client.get('/api/session').json['csrf']
        headers = {'X-CSRF-Token': csrf}
        result = client.post('/api/login', json={'username': 'admin', 'password': 'LocalDemo2026!'}, headers=headers)
        assert result.status_code == 200, result.json
        headers = {'X-CSRF-Token': client.get('/api/session').json['csrf']}
        for i in range(21):
            result = client.post('/api/sources', json={'kind': 'institution', 'name': f'SELECTION108 source {i}', 'website': f'https://source{i}.example/'}, headers=headers)
            assert result.status_code == 201, result.json
        for title in ['SELECTION108 first', 'SELECTION108 second']:
            result = client.post('/api/records', json={'kind': 'report', 'title': title, 'doi': '10.5555/' + title.split()[-1]}, headers=headers)
            assert result.status_code == 201, result.json
        admin = app.test_client()
        token = admin.get('/api/session').json['csrf']
        assert admin.post('/api/login', json={'username': 'admin', 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': token}).status_code == 200
        token = admin.get('/api/session').json['csrf']
        qualifications = admin.get('/api/collaboration/qualifications').json['items']
        q = next(q for q in qualifications if q['id'] == 'admin')
        assert admin.put('/api/collaboration/qualifications/admin', json={'version': q['version'], 'enabled': True}, headers={'X-CSRF-Token': token}).status_code == 200
        # Existing author-created fixtures supply actual pending candidates with
        # zero network/model calls; all decisions below still use public HTTP.
        from portable.demo_seed import seed_profile_examples
        members = []
        for username in ['researcher', 'colleague']:
            member = app.test_client()
            csrf = member.get('/api/session').json['csrf']
            assert member.post('/api/login', json={'username': username, 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf}).status_code == 200
            members.append(member)
        people = []
        for name in ['演示｜SELECTION108·甲', '演示｜SELECTION108·乙']:
            result = client.post('/api/people', json={'name': name, 'change_note': '完全虚构的选择交互合成验证'}, headers=headers)
            assert result.status_code == 201, result.json
            people.append(result.json['id'])
        seed_profile_examples(app, people, *members)
        # Large member lists are synthetic fixtures, not real member accounts.
        # Public topic requests below verify the persisted limit independently.
        from platform_app.store import connect
        db = connect(app.config['DATA_DIR'] / 'platform.sqlite3')
        try:
            with db:
                for i in range(201):
                    db.execute('INSERT INTO users(id,username,name,password_hash,role) VALUES (?,?,?,?,?)',
                               (f'limit-member-{i}', f'limit-member-{i}',
                                f'LIMIT INCLUDED {i:03}' if i < 200 else 'LIMIT EXTRA 200',
                                'synthetic-no-login', 'researcher'))
        finally:
            db.close()
        result = client.post('/api/members', json={'username': 'batch-other', 'name': 'Synthetic second admin',
                             'password': 'LocalDemo2026!', 'role': 'admin'}, headers=headers)
        assert result.status_code == 201, result.json
        for name, site in [('BATCH LIIA', 'https://liia.lv/en/'), ('BATCH GSSC', 'https://www.gssc.lt/en/')]:
            result = client.post('/api/sources', json={'kind': 'think_tank', 'name': name, 'website': site}, headers=headers)
            assert result.status_code == 201, result.json
        environment = {**os.environ, 'SELECTION108_PERSON_ID': people[0]}
        child = subprocess.Popen(['node', str(root / 'scripts/check_selection_http.js')], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', env=environment)
        summary = None
        try:
            for line in child.stdout:
                request = json.loads(line)
                if request.get('done'):
                    summary = request
                    break
                current_headers = {'X-CSRF-Token': client.get('/api/session').json['csrf']}
                response = client.open(request['url'], method=request['method'], json=request.get('body'), headers=request.get('headers', current_headers))
                child.stdin.write(json.dumps({'id': request['id'], 'status': response.status_code, 'body': response.json, 'headers': dict(response.headers)}) + '\n')
                child.stdin.flush()
            child.wait(timeout=10)
            assert child.returncode == 0 and summary, child.stderr.read()
            print(json.dumps(summary, ensure_ascii=False))
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)


if __name__ == '__main__':
    main()
