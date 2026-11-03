"""Exercise an actual source ZIP through isolated native CLI/Waitress and HTTP.

Only synthetic temporary directories and processes started by this script are used.
"""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

from verify_server import verify_zip


def environment(folder):
    env = {k: os.environ[k] for k in ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'SYSTEMDRIVE') if k in os.environ}
    env.update(PATH=os.pathsep.join([str(Path(sys.executable).parent), '/usr/bin', '/bin']),
               TEMP=str(folder), TMP=str(folder), TMPDIR=str(folder), PYTHONDONTWRITEBYTECODE='1')
    return env


def check(package, evidence):
    result = {'package': verify_zip(package), 'checks': [], 'ok': False}
    evidence.mkdir(parents=True, exist_ok=False)
    root = evidence / '正式 发行源码'
    root.mkdir()
    with zipfile.ZipFile(package) as z:
        z.extractall(root)
    data, logs = evidence / '独立 数据', evidence / '日志'
    env = environment(evidence)
    password = 'Synthetic-' + secrets.token_hex(16)
    config = evidence / 'server.json'
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    assert port != 8848
    config.write_text(json.dumps({'data_dir': str(data), 'log_dir': str(logs), 'hosts': ['release.example.invalid'],
                                 'listen': f'127.0.0.1:{port}', 'trusted_proxy': '127.0.0.1'}), encoding='utf-8')
    base_command = [sys.executable, '-B', '-m', 'platform_app.deployment']

    def cli(action, stdin=None, extra=()):
        run = subprocess.run([*base_command, action, '--config', str(config), *(['--password-stdin'] if stdin else []), *extra], cwd=root, env=env,
                             input=stdin, capture_output=True, text=True, encoding='utf-8', timeout=120)
        assert run.returncode == 0, run.stderr + run.stdout
        return run.stdout

    processes = []
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))

    def request(path, body=None, headers=None, raw=False, csrf=True):
        h = {'Host': 'release.example.invalid', 'X-Forwarded-Proto': 'https'}
        if body is not None:
            h.update({'Content-Type': 'application/json'})
            if csrf:
                h['X-CSRF-Token'] = request('/api/session')['csrf']
        h.update(headers or {})
        req = urllib.request.Request(f'http://127.0.0.1:{port}' + path,
                data=json.dumps(body).encode() if body is not None else None, headers=h)
        # Secure cookies belong to the proxy's HTTPS origin. urllib talks plain HTTP
        # to the test's loopback backend, so attach only this isolated test jar.
        cookie = '; '.join(c.name + '=' + c.value for c in jar)
        if cookie:
            req.add_header('Cookie', cookie)
        with opener.open(req, timeout=30) as response:
            payload = response.read()
            return payload if raw else json.loads(payload)

    try:
        # An explicit private stdin pipe avoids exposing even synthetic passwords in process arguments.
        cli('init', password + '\n' + password + '\n', ('--username', 'operator', '--name', '合成管理员'))
        cli('import-public', password + '\n', ('--username', 'operator'))
        imported = cli('import-public', password + '\n', ('--username', 'operator'))
        assert len(json.loads(imported)['article_ids']) == 56
        result['checks'].append('CLI secure initialization; optional public import and idempotence')
        with (evidence / 'web.log').open('w', encoding='utf-8') as output:
            web = subprocess.Popen([*base_command, 'web', '--config', str(config)], cwd=root, env=env,
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=output)
        processes.append(web)
        for _ in range(200):
            try:
                if request('/health')['status'] == 'ok':
                    break
            except (OSError, ValueError):
                if web.poll() is not None:
                    raise AssertionError('Waitress failed; see web.log')
                time.sleep(.1)
        else:
            raise AssertionError('Waitress startup timeout')
        request('/api/login', {'username': 'operator', 'password': password})
        assert jar and all(cookie.secure for cookie in jar)
        assert [m['username'] for m in request('/api/members')['items']] == ['operator']
        assert not request('/api/session')['demo_login']
        for path, body, headers, expected, csrf in [('/health', None, {'Host': 'evil.invalid'}, 400, True),
                ('/health', None, {'X-Forwarded-Proto': 'http'}, 400, True),
                ('/health', None, {'X-Forwarded-Host': 'evil.invalid'}, 400, True),
                ('/api/logout', {}, {}, 403, False),
                ('/api/logout', {}, {'Origin': 'https://evil.invalid'}, 403, True)]:
            try:
                request(path, body, headers, csrf=csrf)
                raise AssertionError('Expected request rejection')
            except urllib.error.HTTPError as error:
                assert error.code == expected, (error.code, expected)
        result['checks'].append('real Waitress; HTTPS cookie/session; strict Host, scheme, Origin and CSRF')
        boundary = 'Release' + secrets.token_hex(8)
        raw = b'SYNTHETIC RELEASE ATTACHMENT\n'
        values = {'kind': 'report', 'title': '合成发行验收', 'visibility': 'shared', 'sharing_confirmed': True}
        payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="data"\r\n\r\n'.encode()
                   + json.dumps(values).encode() + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.txt"\r\nContent-Type: text/plain\r\n\r\n'.encode()
                   + raw + f'\r\n--{boundary}--\r\n'.encode())
        req = urllib.request.Request(f'http://127.0.0.1:{port}/api/records', data=payload,
            headers={'Host': 'release.example.invalid', 'X-Forwarded-Proto': 'https',
                     'X-CSRF-Token': request('/api/session')['csrf'], 'Cookie': '; '.join(c.name+'='+c.value for c in jar),
                     'Content-Type': 'multipart/form-data; boundary=' + boundary})
        with opener.open(req, timeout=30) as response:
            rid = json.load(response)['id']
        aid = request('/api/records/' + rid)['attachments'][0]['id']
        assert request('/api/attachments/' + aid, raw=True) == raw
        before = request('/api/records/' + rid)
        backup = evidence / '合成 完整备份.zip'
        backup.write_bytes(request('/api/backup', {}, raw=True))
        restored = evidence / '恢复 新目录'
        run = subprocess.run([sys.executable, '-B', '-m', 'platform_app.maintenance', '--restore', str(backup), '--target', str(restored)],
                              cwd=root, env=env, capture_output=True, text=True, timeout=60)
        assert run.returncode == 0, run.stderr
        assert (restored / 'platform.sqlite3').is_file()
        result['checks'].append('attachment roundtrip; full backup and validated fresh-directory restore')
        ai = request('/api/admin/ai')
        assert ai['paused'] and not ai['attempts']
        assert not request('/api/ingestion')['worker_heartbeat']
        with (evidence / 'worker.log').open('w', encoding='utf-8') as output:
            worker = subprocess.Popen([*base_command, 'worker', '--config', str(config)], cwd=root, env=env,
                                       stdin=subprocess.DEVNULL, stdout=output, stderr=output)
        processes.append(worker)
        for _ in range(200):
            status = json.loads(cli('worker-status'))
            if status.get('state') == 'running':
                break
            if worker.poll() is not None:
                raise AssertionError('Worker failed; see worker.log')
            time.sleep(.1)
        else:
            raise AssertionError('Worker heartbeat timeout')
        cli('worker-stop')
        worker.wait(timeout=60)
        assert worker.returncode == 0
        assert json.loads(cli('worker-status'))['state'] == 'stopped'
        assert request('/api/records/' + rid) == before
        assert not request('/api/admin/ai')['attempts']
        result['checks'].append('separate existing worker heartbeat/cooperative stop; Web stays alive; zero AI attempts')
        web.terminate()
        web.wait(timeout=15)
        values = json.loads(config.read_text(encoding='utf-8'))
        values['data_dir'] = str(restored)
        config.write_text(json.dumps(values), encoding='utf-8')
        jar.clear()
        with (evidence / 'restored-web.log').open('w', encoding='utf-8') as output:
            restored_web = subprocess.Popen([*base_command, 'web', '--config', str(config)], cwd=root, env=env,
                                            stdin=subprocess.DEVNULL, stdout=output, stderr=output)
        processes.append(restored_web)
        for _ in range(200):
            try:
                if request('/health')['status'] == 'ok':
                    break
            except OSError:
                if restored_web.poll() is not None:
                    raise AssertionError('Restored Waitress failed; see restored-web.log')
                time.sleep(.1)
        else:
            raise AssertionError('Restored Web startup timeout')
        request('/api/login', {'username': 'operator', 'password': password})
        restored_record = request('/api/records/' + rid)
        # Attachment search indexes are discardable derived caches, excluded from backups.
        for key in ('id', 'title', 'kind', 'version', 'visibility', 'owner_id', 'author_id', 'can_edit'):
            assert restored_record[key] == before[key], key
        assert request('/api/attachments/' + aid, raw=True) == raw
        assert not request('/api/admin/ai')['attempts']
        result['checks'].append('restored new directory starts real Waitress; account, record, attachment and zero-attempt state retained')
        result['ok'] = True
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        (evidence / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'evidence': str(evidence), 'checks': result['checks']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    evidence = args.evidence or Path(tempfile.gettempdir()) / ('database-server96-' + secrets.token_hex(6))
    check(args.package.resolve(), evidence.resolve())
