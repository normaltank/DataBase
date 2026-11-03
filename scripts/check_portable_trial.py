"""New portable admission checks shared by the local and explicit LAN ZIP checks.

Only freshly extracted synthetic package data is used. No provider is invoked.
"""
import http.cookiejar
import json
import os
import secrets
import socket
import subprocess
import urllib.error
from pathlib import Path
import argparse


def rejected(client, path, body=None, expected=403, **kwargs):
    try:
        client.request(path, body, **kwargs)
    except urllib.error.HTTPError as error:
        assert error.code == expected, (path, error.code, expected)
    else:
        raise AssertionError('Expected rejection: ' + path)


def practice(base):
    from check_portable_preview import HTTP
    first, second = HTTP(base), HTTP(base)
    a, b = first.request('/api/session'), second.request('/api/session')
    assert a['portable_trial'] and not a['demo_login']
    assert a['user']['temporary'] and b['user']['temporary']
    assert a['user']['id'] != b['user']['id']
    assert first.request('/api/session')['user']['id'] == a['user']['id']
    first.request('/api/trial/nickname', {'name': '合成试用者甲'}, method='PUT')
    assert first.request('/api/session')['user']['name'] == '合成试用者甲'
    single = first.request('/api/collaboration/topics', {'theme': '验收｜单人实践', 'participant_ids': []})['id']
    rejected(second, '/api/collaboration/topics/' + single, expected=404)
    tid = first.request('/api/collaboration/topics', {'theme': '验收｜双人实践', 'participant_ids': [b['user']['id']]})['id']
    prefix = '/api/collaboration/topics/' + tid
    def upload(client, stage, material=None, key='portable-trial-material'):
        data = {'request_id':key,'stage':stage,'token':client.request(prefix+'/handoffs')['token']}
        if material:
            data['material_ref']=material
        return client.request(prefix+'/handoffs',data,file=('合成练习.txt',b'SYNTHETIC portable trial report'))
    def decide(decision):
        board=first.request(prefix+'/handoffs')
        material=next(m for m in board['materials'] if m['status']=='pending')
        first.request(prefix+'/handoff-reviews',{'request_id':'portable-review-'+material['versions'][0]['id'],'token':board['token'],'version_ref':material['versions'][0]['ref'],'decision':decision})
    saved=upload(second,'selection')
    decide('returned')
    upload(second,'selection',saved['material_ref'],'portable-trial-revision')
    decide('approved')
    first.request(prefix+'/enter-compilation',{'request_id':'portable-direct-advance','stage_version':1,'topic_version':1})
    upload(second,'compilation',key='portable-compilation-material')
    decide('approved')
    board=first.request(prefix+'/handoffs')
    assert board['lead_id']==a['user']['id'] and board['materials'][0]['owner_id']==b['user']['id']
    assert first.request(board['materials'][0]['versions'][0]['file_url'],raw=True)==b'SYNTHETIC portable trial report'
    # One-person lead/author does not need a meeting or assignment.
    solo='/api/collaboration/topics/'+single
    own=first.request(solo+'/handoffs',{'request_id':'portable-solo-material','stage':'selection','token':first.request(solo+'/handoffs')['token']},file=('单人.txt',b'SYNTHETIC solo lead author'))
    board=first.request(solo+'/handoffs')
    first.request(solo+'/handoff-reviews',{'request_id':'portable-solo-review','token':board['token'],'version_ref':board['materials'][0]['versions'][0]['ref'],'decision':'approved'})
    first.request(solo+'/enter-compilation',{'request_id':'portable-solo-advance','stage_version':1,'topic_version':1})
    samples = [w for w in first.request('/api/collaboration/works?scope=all')['items'] if w.get('trial_sample')]
    assert any(w['business'] == 'topic' for w in samples)
    for sample in samples:
        if sample['business'] == 'topic':
            view = first.request('/api/collaboration/topics/' + sample['id'])
            assert not view['can_submit'] and not view['is_participant']
            assert view['lead_id'] != a['user']['id']
        else:
            assert not first.request('/api/collaboration/journals/' + sample['id'])['can_edit']
    rejected(first, '/api/backup', {})
    rejected(first, '/api/login', {'username': 'admin', 'password': 'LocalDemo2026!'})
    return first, second, tid, a['user']['id'], samples


def restore(one, two, env, evidence, admin):
    backup = evidence / 'trial-synthetic-backup.zip'
    backup.write_bytes(admin.request('/api/backup', {}, raw=True))
    clean_env = {k: v for k, v in env.items() if k in {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'SYSTEMDRIVE', 'PATH', 'TEMP', 'TMP'}}
    run = subprocess.run([str(two / 'runtime/python.exe'), '-I', '-B', '-m', 'platform_app.maintenance',
                          '--restore', str(backup), '--target', str(two / 'data')], cwd=two, env=clean_env,
                         capture_output=True, text=True, encoding='utf-8', timeout=90)
    assert run.returncode == 0, run.stderr


def preview(one, two, env, evidence, base, browser=False):
    from check_portable_preview import HTTP, batch, originals
    first, second, tid, uid, samples = practice(base)
    admin = HTTP(base)
    admin.request('/api/trial/host', {})
    assert admin.request('/api/session')['user']['host_maintenance']
    assert admin.request('/api/admin/ai')['paused'] and not admin.request('/api/admin/ai')['attempts']
    before = originals(one / 'data')
    restore(one, two, env, evidence, admin)
    other_base = batch(two, env, 'start', '--no-browser')
    reader = HTTP(other_base)
    assert reader.request('/api/session')['user']['id'] != uid
    rejected(reader, '/api/collaboration/topics/' + tid, expected=404)
    assert len([w for w in reader.request('/api/collaboration/works?scope=all')['items'] if w.get('trial_sample')]) == len(samples)
    assert originals(two / 'data') == before
    # One browser cookie jar can visit two copies without replacing either identity.
    shared = http.cookiejar.CookieJar()
    left, right = HTTP(base, shared), HTTP(other_base, shared)
    left_uid, right_uid = left.request('/api/session')['user']['id'], right.request('/api/session')['user']['id']
    assert left_uid != right_uid and left.request('/api/session')['user']['id'] == left_uid
    right.request('/api/logout', {})
    assert right.request('/api/session')['user'] is None
    assert left.request('/api/session')['user']['id'] == left_uid
    batch(one, env, 'stop')
    assert batch(one, env, 'start', '--no-browser') == base
    assert first.request('/api/session')['user']['id'] == uid
    assert second.request('/api/collaboration/topics/' + tid)['id'] == tid
    assert originals(one / 'data') == before
    checks = ['portable trial: two independent persistent identities; nickname; single and multiplayer periods; actual upload and original authorship; read-only seed samples',
              'local-only maintenance admission; demo password rejected; zero provider attempts; full backup into new copy preserves samples and originals without transferring private practice',
              'same-cookie-jar copy isolation; logout isolation; normal stop/restart reuses identity and port']
    if browser:
        browser_admission(base, evidence)
        checks.append('actual Chromium: independent admission, nickname, create practice and upload; no page errors (single viewport)')
    return checks


def lan(one, two, env, evidence, result):
    from check_portable_preview import HTTP, command
    command(one, env, 'stop')
    command(one, env, 'lan-configure')  # No input or account/password mutations.
    command(one, env, 'lan-start', '--no-browser')
    state = json.loads((one / '.portable/server.json').read_text(encoding='utf-8'))
    assert state['urls'] and all('127.0.0.1' not in url for url in state['urls'])
    base, local = state['urls'][0], f"http://127.0.0.1:{state['port']}"
    first, second, tid, uid, samples = practice(base)
    rejected(first, '/api/trial/host', {})
    rejected(first, '/__portable/stop', {}, extra_headers={'X-Portable-Token': state['token']}, expected=404)
    rejected(first, '/health', extra_headers={'X-Forwarded-For': '127.0.0.1'}, expected=400)
    rejected(first, '/api/logout', {}, extra_headers={'Origin': 'http://evil.invalid'})
    host_jar = http.cookiejar.CookieJar()
    admin = HTTP(local, host_jar)
    admin.request('/api/trial/host', {})
    assert admin.request('/api/admin/ai')['paused'] and not admin.request('/api/admin/ai')['attempts']
    # Even the real maintenance cookie cannot be replayed over the LAN address.
    host_cookie = '; '.join(cookie.name + '=' + cookie.value for cookie in host_jar)
    rejected(HTTP(base), '/api/members', extra_headers={'Cookie': host_cookie})
    restore(one, two, env, evidence, admin)
    command(one, env, 'stop')
    command(one, env, 'lan-start', '--no-browser')
    assert json.loads((one / '.portable/server.json').read_text(encoding='utf-8'))['port'] == state['port']
    assert first.request('/api/session')['user']['id'] == uid
    assert second.request('/api/collaboration/topics/' + tid)['id'] == tid
    command(one, env, 'stop')
    with socket.socket() as conflict:
        conflict.bind(('127.0.0.1', state['port']))
        conflict.listen()
        command(one, env, 'lan-start', '--no-browser')
        alternate = json.loads((one / '.portable/server.json').read_text(encoding='utf-8'))
        assert alternate['port'] != state['port'] and alternate['port'] != 8848
        command(one, env, 'stop')
        assert conflict.fileno() >= 0
    command(two, env, 'lan-start', '--no-browser')
    recovered = json.loads((two / '.portable/server.json').read_text(encoding='utf-8'))
    reader = HTTP(recovered['urls'][0])
    reader.request('/api/session')
    assert len([w for w in reader.request('/api/collaboration/works?scope=all')['items'] if w.get('trial_sample')]) == len(samples)
    rejected(reader, '/api/collaboration/topics/' + tid, expected=404)
    result['checks'].extend(['actual host IPv4: password-free LAN configuration/admission; independent identities, period creation/upload; read-only samples',
                             'loopback maintenance versus LAN visitor and replayed-cookie boundary; CSRF/Origin/forwarding and stop control; zero provider attempts',
                             'stable port/identity on restart; owned port conflict fallback; backup to new directory preserves private period access and seed visibility'])
    result['ok'] = True


def browser_admission(base, evidence):
    from playwright.sync_api import sync_playwright, expect
    errors = []
    with sync_playwright() as runtime:
        executable = os.environ.get('DATABASE_BROWSER_EXECUTABLE')
        browser = runtime.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
        contexts = [browser.new_context(viewport={'width': 1366, 'height': 900}) for _ in range(2)]
        try:
            pages = [c.new_page() for c in contexts]
            for page in pages:
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base)
                expect(page.get_by_role('heading', name='从自己的实践开始')).to_be_visible()
            accounts = [c.request.get(base + '/api/session').json()['user']['id'] for c in contexts]
            assert accounts[0] != accounts[1]
            page = pages[0]
            page.get_by_role('button', name='修改我的称呼', exact=True).click()
            page.get_by_label('我的临时称呼').fill('浏览器合成甲')
            page.get_by_role('button', name='保存称呼', exact=True).click()
            expect(page.get_by_role('button', name='浏览器合成甲', exact=True)).to_be_visible()
            page.goto(base + '/#collaboration')
            page.get_by_role('button', name='开启我的练习主题', exact=True).click()
            page.get_by_label('本期主题').fill('浏览器合成练习 ' + secrets.token_hex(4))
            page.get_by_role('button', name='保存本期信息', exact=True).click()
            expect(page.locator('[data-form=handoff-upload]')).to_be_visible()
            page.get_by_label('文件', exact=True).set_input_files({'name': '浏览器合成.txt', 'mimeType': 'text/plain', 'buffer': b'SYNTHETIC browser report'})
            page.get_by_role('button', name='上传材料', exact=True).click()
            expect(page.locator('[data-material-ref]')).to_be_visible()
            expect(page.get_by_text('待审', exact=True)).to_be_visible()
            page.get_by_role('button', name='进入编译', exact=True).click()
            page.locator('[data-form=topic-stage-enter]').get_by_role('button', name='进入编译', exact=True).click()
            expect(page.locator('.workbench-detail-meta')).to_contain_text('编译阶段')
            page.screenshot(path=str(evidence / 'trial-browser-admission.png'), full_page=True)
            assert not errors, errors
        finally:
            for context in contexts:
                context.close()
            browser.close()


def single_copy(root, evidence, browser=False):
    """Primary smoke check: one fixed executable path and loopback listener only."""
    from check_portable_preview import HTTP, command, environment, originals
    evidence.mkdir(parents=True, exist_ok=False)
    env = environment(evidence)
    result = {'ok': False, 'checks': [], 'listener': 'loopback only', 'runtime_paths': 1}
    try:
        base = command(root, env, 'start', '--no-browser')
        assert base.startswith('http://127.0.0.1:') and not base.endswith(':8848')
        first, second, tid, uid, samples = practice(base)
        admin = HTTP(base)
        admin.request('/api/trial/host', {})
        ai = admin.request('/api/admin/ai')
        assert ai['paused'] and not ai['attempts']
        backup = evidence / 'trial-synthetic-backup.zip'
        backup.write_bytes(admin.request('/api/backup', {}, raw=True))
        before = originals(root / 'data')
        target = evidence / 'restored-data'
        clean_env = {k: v for k, v in env.items() if k in {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'SYSTEMDRIVE', 'PATH', 'TEMP', 'TMP'}}
        restored = subprocess.run([str(root / 'runtime/python.exe'), '-I', '-B', '-m', 'platform_app.maintenance',
                                   '--restore', str(backup), '--target', str(target)], cwd=root, env=clean_env,
                                  capture_output=True, text=True, encoding='utf-8', timeout=90)
        assert restored.returncode == 0, restored.stderr
        assert originals(target) == before
        # The same executable opens restored data without listening on any interface.
        source_check = '''
import json, sys
from platform_app.web import create_app
app=create_app(sys.argv[1], testing=True, embedded_worker=False, portable_trial=True)
remote=app.test_client()
r=remote.get('/api/session', environ_overrides={'REMOTE_ADDR':'192.0.2.8'})
assert r.json['user']['temporary'] and r.json['user']['role']=='researcher'
csrf={'X-CSRF-Token':r.json['csrf']}
assert remote.post('/api/trial/host',json={},headers=csrf,environ_overrides={'REMOTE_ADDR':'192.0.2.8'}).status_code==403
assert remote.get('/api/collaboration/topics/'+sys.argv[2]).status_code==404
works=remote.get('/api/collaboration/works?scope=all').json['items']
assert len([w for w in works if w.get('trial_sample')])==int(sys.argv[3])
host=app.test_client()
csrf={'X-CSRF-Token':host.get('/api/session').json['csrf']}
assert host.post('/api/trial/host',json={},headers=csrf,environ_overrides={'REMOTE_ADDR':'127.0.0.1'}).status_code==200
assert host.get('/api/members',environ_overrides={'REMOTE_ADDR':'192.0.2.8'}).status_code==403
print(json.dumps({'ok':True,'source_boundary':'synthetic HTTP remote address; no listener'}))
'''
        checked = subprocess.run([str(root / 'runtime/python.exe'), '-I', '-B', '-c', source_check,
                                  str(target), tid, str(len(samples))], cwd=root, env=clean_env,
                                 capture_output=True, text=True, encoding='utf-8', timeout=60)
        assert checked.returncode == 0, checked.stderr
        result['restored_http'] = json.loads(checked.stdout)
        command(root, env, 'stop')
        assert command(root, env, 'start', '--no-browser') == base
        assert first.request('/api/session')['user']['id'] == uid
        assert second.request('/api/collaboration/topics/' + tid)['id'] == tid
        assert originals(root / 'data') == before
        result['checks'] = ['two automatic identities; nickname; single/multiplayer create/upload; seed read-only and original ownership',
                            'single runtime path; loopback-only native start/restart; stable port/identity and originals',
                            'backup/new-directory restore; synthetic HTTP source address host/LAN and private-content boundary; zero provider attempts']
        if browser:
            browser_admission(base, evidence)
            result['checks'].append('actual Chromium admission/create/upload (single viewport)')
        result['ok'] = True
    finally:
        try:
            command(root, env, 'stop')
        except Exception as error:
            result['cleanup_error'] = str(error)
            result['ok'] = False
        (evidence / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    assert result['ok'], 'See the evidence result for cleanup failure.'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Smoke-test one explicitly selected synthetic portable extraction; no LAN listener or second runtime path.')
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--browser', action='store_true')
    args = parser.parse_args()
    single_copy(args.root.resolve(), args.evidence.resolve(), args.browser)
