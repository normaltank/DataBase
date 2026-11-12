"""Actual Windows ZIP LAN HTTP acceptance on this host's nonloopback IPv4.

This does not prove connectivity between campus devices or change Windows firewall.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile

from check_portable_preview import HTTP, command, environment
from verify_portable import verify_zip


def check(package, evidence):
    inventory = verify_zip(package)
    evidence.mkdir(parents=True, exist_ok=False)
    one, two = evidence / '校园 演示一', evidence / '恢复 演示二'
    with zipfile.ZipFile(package) as z:
        z.extractall(one)
        z.extractall(two)
    env = environment(evidence)
    result = {'inventory': inventory, 'checks': [], 'ok': False}
    password = 'Synthetic-' + secrets.token_hex(16)

    def configure(root):
        run = subprocess.run([str(root / 'runtime/python.exe'), '-I', '-B', str(root / 'portable/launch.py'), 'lan-configure', '--password-stdin'],
            cwd=root, env=env, input=password+'\n'+password+'\n', capture_output=True, text=True, encoding='utf-8', timeout=150)
        assert run.returncode == 0, run.stdout + run.stderr

    def rejected(client, path, body=None, headers=None, expected=403):
        try:
            client.request(path, body, extra_headers=headers)
            raise AssertionError('Expected rejection: ' + path)
        except urllib.error.HTTPError as error:
            assert error.code == expected, (error.code, expected)

    try:
        local = command(one, env, 'start', '--no-browser')
        if HTTP(local).request('/api/session').get('portable_trial'):
            from check_portable_trial import lan
            lan(one, two, env, evidence, result)
            print(json.dumps({'ok': True, 'evidence': str(evidence), 'checks': result['checks']}, ensure_ascii=False))
            return
        assert HTTP(local).request('/api/session')['demo_login']
        command(one, env, 'stop')
        configure(one)
        command(one, env, 'lan-start', '--no-browser')
        state = json.loads((one / '.portable/server.json').read_text(encoding='utf-8'))
        assert state['mode'] == 'lan' and state['urls'] and state['port'] != 8848
        base = state['urls'][0]
        admin = HTTP(base)
        admin.login('admin', password)
        assert not admin.request('/api/session')['demo_login']
        assert b'data-demo-login="false"' in admin.request('/', raw=True)
        rejected(HTTP(base), '/api/login', {'username': 'researcher', 'password': 'LocalDemo2026!'}, expected=401)
        for username in ('member-one', 'member-two'):
            admin.request('/api/members', {'username': username, 'name': username, 'role': 'researcher', 'password': password})
        first, second = HTTP(base), HTTP(base)
        first.login('member-one', password)
        second.login('member-two', password)
        private = first.request('/api/records', {'kind': 'research_report', 'title': 'LAN 合成私人材料', 'visibility': 'restricted', 'sharing_confirmed': True}, file=('合成.txt', b'SYNTHETIC LAN PRIVATE'))['id']
        rejected(second, '/api/records/' + private, expected=404)
        personal = admin.request('/api/records/' + private)
        assert not personal['can_edit']
        try:
            admin.request('/api/records/' + private, {'version': personal['version'], 'title': '不应覆盖'}, method='PUT')
            raise AssertionError('Administrator must not edit personal author-controlled content')
        except urllib.error.HTTPError as error:
            assert error.code == 403
        shared = first.request('/api/records', {'kind': 'report', 'title': 'LAN 合成共享材料', 'visibility': 'shared', 'sharing_confirmed': True}, file=('合成共享.txt', b'SYNTHETIC LAN SHARED'))['id']
        detail = second.request('/api/records/' + shared)
        assert second.request('/api/attachments/' + detail['attachments'][0]['id'], raw=True) == b'SYNTHETIC LAN SHARED'
        result['checks'].append('actual host IPv4 LAN login; default credentials disabled; two independent members; private visibility and shared attachment')
        rejected(admin, '/health', headers={'Host': 'evil.invalid'}, expected=400)
        rejected(admin, '/health', headers={'X-Forwarded-Proto': 'https'}, expected=400)
        rejected(admin, '/api/logout', {}, {'Origin': 'http://evil.invalid'})
        rejected(admin, '/api/logout', {}, {'X-CSRF-Token': ''})
        rejected(admin, '/__portable/stop', {}, {'X-Portable-Token': state['token']}, expected=404)
        assert HTTP(base).request('/health')['status'] == 'ok'
        assert admin.request('/api/admin/ai')['paused'] and not admin.request('/api/admin/ai')['attempts']
        assert not admin.request('/api/ingestion')['worker_heartbeat']
        backup = evidence / 'LAN 合成备份.zip'
        backup.write_bytes(admin.request('/api/backup', {}, raw=True))
        result['checks'].append('Host/forwarding/Origin/CSRF; even token-authenticated remote stop rejected; no background/AI attempts')
        command(one, env, 'stop')
        command(one, env, 'lan-start', '--no-browser')
        restarted = json.loads((one / '.portable/server.json').read_text(encoding='utf-8'))
        assert restarted['port'] == state['port']
        again = HTTP(restarted['urls'][0])
        again.login('member-one', password)
        assert again.request('/api/records/' + private)['id'] == private
        command(one, env, 'stop')
        # An owned conflicting socket must survive launcher fallback and stop.
        with socket.socket() as conflict:
            if os.name == 'nt':
                conflict.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            conflict.bind(('0.0.0.0', state['port']))
            conflict.listen()
            command(one, env, 'lan-start', '--no-browser')
            alternate = json.loads((one / '.portable/server.json').read_text(encoding='utf-8'))
            assert alternate['port'] != state['port'] and alternate['port'] != 8848
            command(one, env, 'stop')
            assert conflict.fileno() >= 0
        local = command(one, env, 'start', '--no-browser')
        assert not HTTP(local).request('/api/session')['demo_login']
        HTTP(local).login('admin', password)
        command(one, env, 'stop')
        run = subprocess.run([str(two / 'runtime/python.exe'), '-I', '-B', '-m', 'platform_app.maintenance',
                              '--restore', str(backup), '--target', str(two / 'data')], cwd=two,
            env={k:v for k,v in env.items() if k in {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'SYSTEMDRIVE', 'PATH', 'TEMP', 'TMP'}},
            capture_output=True, text=True, encoding='utf-8', timeout=90)
        assert run.returncode == 0, run.stderr
        configure(two)
        command(two, env, 'lan-start', '--no-browser')
        restored = json.loads((two / '.portable/server.json').read_text(encoding='utf-8'))
        reader = HTTP(restored['urls'][0])
        reader.login('member-two', password)
        assert reader.request('/api/records/' + shared)['id'] == shared
        assert reader.request('/api/attachments/' + detail['attachments'][0]['id'], raw=True) == b'SYNTHETIC LAN SHARED'
        result['checks'].append('stable restart and port-conflict fallback; own-process stop; local mode keeps protected accounts; full backup restored to new copy')
        result['ok'] = True
    finally:
        for root in (one, two):
            try:
                command(root, env, 'stop')
            except Exception as error:
                result.setdefault('cleanup_errors', []).append(str(error))
        (evidence / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'evidence': str(evidence), 'checks': result['checks']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    check(args.package.resolve(), (args.evidence or Path(tempfile.gettempdir()) / ('database-lan98-' + secrets.token_hex(6))).resolve())
