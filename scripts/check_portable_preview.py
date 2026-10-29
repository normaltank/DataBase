"""Release-specific public CLI/HTTP checks on fresh Chinese-space-path copies.

Does not import application internals or inspect a real data directory.
"""
import argparse
import hashlib
import http.cookiejar
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request
import uuid
import zipfile

from verify_portable import verify_directory, verify_zip


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class HTTP:
    def __init__(self, base, jar=None):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(jar if jar is not None else http.cookiejar.CookieJar()))

    def request(self, path, data=None, file=None, method=None, raw=False):
        headers = {}
        body = None
        if data is not None or file:
            headers['X-CSRF-Token'] = self.request('/api/session')['csrf']
            if file:
                boundary = 'Preview' + uuid.uuid4().hex
                filename, content = file
                parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="data"\r\n\r\n'.encode(),
                    json.dumps(data or {}, ensure_ascii=False).encode('utf-8'),
                    f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode('utf-8'),
                    content, f'\r\n--{boundary}--\r\n'.encode()]
                body = b''.join(parts)
                headers['Content-Type'] = 'multipart/form-data; boundary=' + boundary
            else:
                headers['Content-Type'] = 'application/json'
                body = json.dumps(data).encode('utf-8')
        request = urllib.request.Request(self.base + path, data=body, headers=headers,
                                         method=method or ('POST' if body is not None else 'GET'))
        with self.opener.open(request, timeout=30) as response:
            content = response.read()
            return content if raw else json.loads(content)

    def login(self, name):
        return self.request('/api/login', {'username': name, 'password': 'LocalDemo2026!'})


def environment(evidence):
    env = {name: os.environ[name] for name in ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'SYSTEMDRIVE') if name in os.environ}
    # These are explicit fake probes. No real inherited settings are read.
    env.update(PATH='', TEMP=str(evidence), TMP=str(evidence), PYTHONPATH=str(evidence / 'fake-modules'),
        PYTHONHOME=str(evidence / 'fake-python'), RESEARCH_DATA_DIR=str(evidence / 'forbidden-data'),
        DEEPSEEK_API_KEY='FAKE_PORTABLE_TEST_ONLY', DS_API_KEY='FAKE_PORTABLE_TEST_ONLY',
        HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9',
        SSL_CERT_FILE=str(evidence / 'not-a-certificate'))
    return env


def command(root, env, *args):
    result = subprocess.run([str(root / 'runtime/python.exe'), '-I', '-B',
        str(root / 'portable/launch.py'), *args], env=env, cwd=root, capture_output=True,
        text=True, encoding='utf-8', timeout=150)
    if result.returncode:
        raise AssertionError(f'Portable CLI {args} failed: {result.stdout} {result.stderr}')
    return result.stdout.strip()


def originals(data):
    return {p.relative_to(data).as_posix(): sha(p.read_bytes())
            for folder in ('uploads', 'handoffs', 'avatars') for p in (data / folder).glob('*') if p.is_file()}


def docx():
    # Minimal standards-based OPC/WordprocessingML test fixture, not a report/template.
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('_rels/.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/document.xml', '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>DEMO PortableDocxIndexProbe synthetic original only</w:t></w:r></w:p><w:sectPr/></w:body></w:document>')
    return out.getvalue()


def verify_seed(root, client, admin):
    seed = json.loads((root / 'data/demo-seed.json').read_text(encoding='utf-8'))
    assert seed['synthetic'] is True
    assert {x['username'] for x in admin.request('/api/members')['items']} == {'researcher', 'colleague', 'admin'}
    sources = client.request('/api/sources')['items']
    assert {x['name'] for x in sources} == {'演示｜北岸公共研究所', '演示｜河港社会研究中心', '演示｜波罗的海协作评论'}
    assert {x['id'] for x in sources} == set(seed['source_ids'])
    people = client.request('/api/people')['items']
    assert {x['name'] for x in people} == {'演示｜安娜·河港', '演示｜马丁·北岸'}
    assert {x['id'] for x in people} == set(seed['person_ids'])
    records = client.request('/api/records')['items']
    assert len(records) == 6, len(records)
    assert all('演示' in x['title'] for x in records), records
    assert len(seed['files']) == 11
    for file in seed['files']:
        content = client.request(file['url'], raw=True)
        assert sha(content) == file['sha256'] and len(content) == file['bytes']
    original_hashes = {
        '8aed2928d8a757236ee73cfa20746c357c6b76b9caffcc4fa8f66473a56bef3e',
        '981a0811216f05cca87ee29af7453b06de77de1f88c6fbfb7cdc7206cb4bfae7',
        '6a3a461ed1b863e92501c58f4de7c718fa7a880f95aa8b66ad58ab7dd12bb50f',
        '1e60efc139bfee17e309b99b18c31af6e7eda75c4af94b1f994672a5b0465ebd',
        '7a8e8748ea1698ee00f2a2143ed1d7ebe14ed7e15f12d214a696dcbb2800de0d',
        '7741f4bccc1af656846497bfdadf9b69e2fceea7bf7e68cb249643a9b2df5748',
        '46f9f62d0a71bec7f22b386155ba1207fcee7f2b8322277d46bdb394c65807c9',
        'd3faf5703f5603f02224d16214a7bcc84ccaa99ce2d39048bab60b26df19a319',
        '96b7f0e91449b62639ebe7b9e9045a50f3fa9395c03c5c368473a36a7e5480b2',
        '5ade15e130d9041879060dfda9a802539c4dcb7c31c2723a8317fc82ff6029cc',
        '409fd91477fefd63f373c4a8cf4c3954da9051518a0422c15209d98ace36221c',
    }
    assert {f['sha256'] for f in seed['files']} == original_hashes
    on_disk = originals(root / 'data')
    assert len(on_disk) == 12, on_disk
    assert {h for p, h in on_disk.items() if not p.startswith('avatars/')} == original_hashes
    person = client.request('/api/people/' + seed['person_ids'][0])
    avatar = client.request(person['avatar']['url'], raw=True)
    assert avatar.startswith(b'\x89PNG\r\n\x1a\n') and sha(avatar) == person['avatar']['sha256']
    workflow = client.request('/api/collaboration/topics/' + seed['complete_topic'] + '/workflow')
    a = workflow['assignments'][0]
    assert a['status'] == 'final' and [s['version'] for s in a['submissions']] == [2, 1]
    assert a['returns'][0]['submission_id'] == a['submissions'][1]['id']
    assert workflow['summaries'][0]['adoptions'][0]['submission_id'] == a['submissions'][0]['id']
    journal = client.request('/api/collaboration/journals/' + seed['journal'])
    assert [s['version'] for s in journal['submissions']] == [2, 1]
    assert journal['current_product_id'] == journal['submissions'][0]['id']
    for rid in seed['article_ids']:
        record = client.request('/api/records/' + rid)
        assert record['url'].startswith('https://example.invalid/')
        assert record['chinese_title'] and record['chinese_abstract']
        assert record['attachments'][0]['index']['status'] == 'ready'
    assert admin.request('/api/ingestion').get('heartbeat') in (None, '')
    return seed, workflow, journal


def browser_check(base, evidence):
    from playwright.sync_api import sync_playwright, expect
    errors = []
    with sync_playwright() as p:
        executable = os.environ.get('DATABASE_BROWSER_EXECUTABLE')
        browser = p.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
        context = browser.new_context(viewport={'width': 1366, 'height': 900}, accept_downloads=True)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        for name in ('researcher', 'colleague', 'admin'):
            page.goto(base)
            if page.get_by_role('button', name='退出', exact=True).count():
                page.get_by_role('button', name='退出', exact=True).click()
            page.get_by_label('账号', exact=True).fill(name)
            page.get_by_label('密码', exact=True).fill('LocalDemo2026!')
            page.get_by_role('button', name='查看资料', exact=True).click()
            expect(page.get_by_role('heading', name='编译协作', exact=True)).to_be_visible()
            page.screenshot(path=str(evidence / f'browser-{name}.png'), full_page=True)
            page.evaluate("async()=>{const s=await(await fetch('/api/session')).json();await fetch('/api/logout',{method:'POST',headers:{'X-CSRF-Token':s.csrf,'Content-Type':'application/json'},body:'{}'});location.reload()}")
            expect(page.get_by_label('账号', exact=True)).to_be_visible()
        assert not errors, errors
        browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--preparation', action='store_true')
    parser.add_argument('--browser', action='store_true')
    args = parser.parse_args()
    evidence = Path(tempfile.mkdtemp(prefix='知汇 便携验收 '))
    print(json.dumps({'evidence': str(evidence)}, ensure_ascii=False), flush=True)
    (Path(tempfile.gettempdir()) / 'database-portable78-latest.txt').write_text(str(evidence), encoding='utf-8')
    one, two = evidence / '演示 一', evidence / '演示 二'
    if args.package.is_file():
        inventory = verify_zip(args.package)
        with zipfile.ZipFile(args.package) as z:
            z.extractall(one)
            z.extractall(two)
    else:
        inventory = verify_directory(args.package, not args.preparation)
        shutil.copytree(args.package, one)
        shutil.copytree(args.package, two)
    env = environment(evidence)
    baseline8848 = None
    try:
        baseline8848 = HTTP('http://127.0.0.1:8848').request('/health')
    except OSError:
        pass
    result = {'inventory': inventory, 'host': 'Windows actual host; no clean VM', 'checks': []}
    try:
        diagnostic = json.loads(command(one, env, 'diagnose'))
        assert diagnostic['isolated'] == 1
        assert all(Path(p).is_relative_to(one) for p in diagnostic['paths'] + diagnostic['modules'])
        assert not set(diagnostic['environment_keys']) & {'RESEARCH_DATA_DIR', 'PYTHONPATH', 'PYTHONHOME', 'DEEPSEEK_API_KEY', 'DS_API_KEY', 'HTTP_PROXY', 'HTTPS_PROXY', 'SSL_CERT_FILE'}
        result['diagnostic'] = diagnostic
        base = command(one, env, 'start', '--no-browser')
        assert base != 'http://127.0.0.1:8848'
        assert command(one, env, 'start', '--no-browser') == base
        jar = http.cookiejar.CookieJar()
        researcher = HTTP(base, jar)
        researcher.login('researcher')
        admin = HTTP(base)
        admin.login('admin')
        lead = HTTP(base)
        lead.login('colleague')
        assert lead.request('/api/session')['user']['role'] == 'researcher'
        seed, workflow, journal = verify_seed(one, researcher, admin)
        result['checks'].append('first start: exact synthetic account/source/person/record/original inventory; role login; avatar; PDF/TXT parser; exact topic v2 adoption; independent journal v2')
        for kind, wid in [('topic', seed['complete_topic']), ('journal', seed['journal'])]:
            raw = researcher.request(f'/api/collaboration/materials/{kind}/{wid}?scope=all', raw=True)
            path = evidence / f'{kind}-materials.zip'
            path.write_bytes(raw)
            from verify_work_materials import verify
            verify(path)
        export = researcher.request('/api/export/content', raw=True)
        with zipfile.ZipFile(io.BytesIO(export)) as z:
            assert 'content.json' in z.namelist()
        raw_docx = docx()
        rid = researcher.request('/api/records', {'title': '演示｜验收新增DOCX', 'kind': 'report',
            'sharing_confirmed': True}, file=('演示索引.docx', raw_docx))['id']
        detail = researcher.request('/api/records/' + rid)
        assert detail['attachments'][0]['index']['status'] == 'ready'
        assert researcher.request('/api/records?q=PortableDocxIndexProbe')['total'] == 1
        assert researcher.request('/api/attachments/' + detail['attachments'][0]['id'], raw=True) == raw_docx
        before = originals(one / 'data')
        backup = evidence / 'synthetic-full-backup.zip'
        backup.write_bytes(admin.request('/api/backup', {}, raw=True))
        restored = subprocess.run([str(two / 'runtime/python.exe'), '-I', '-B', '-m', 'platform_app.maintenance',
            '--restore', str(backup), '--target', str(two / 'data')], cwd=two, env={k:v for k,v in env.items()
            if k in {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'SYSTEMDRIVE', 'PATH', 'TEMP', 'TMP'}},
            capture_output=True, text=True, encoding='utf-8', timeout=60)
        assert restored.returncode == 0, restored.stderr
        second_base = command(two, env, 'start', '--no-browser')
        assert second_base != base
        peer = HTTP(second_base, jar)
        peer.login('colleague')
        assert researcher.request('/api/session')['user']['id'] == 'researcher'
        assert peer.request('/api/session')['user']['id'] == 'colleague'
        restored_reader = HTTP(second_base)
        restored_reader.login('researcher')
        assert restored_reader.request('/api/collaboration/topics/' + seed['complete_topic'] + '/workflow') == workflow
        assert restored_reader.request('/api/collaboration/journals/' + seed['journal']) == journal
        assert originals(two / 'data') == before
        result['checks'].append('materials/content export; standards-based DOCX indexing/search; full backup CLI restore; same-cookie-jar simultaneous instances')
        previous_state = json.loads((one / '.portable/server.json').read_text(encoding='utf-8'))
        command(one, env, 'stop')
        assert peer.request('/health')['status'] == 'ok'
        assert originals(one / 'data') == before
        database_hash = sha((one / 'data/platform.sqlite3').read_bytes())
        # Stale state with an unrelated port/token must not kill that server.
        (one / '.portable/server.json').write_text(json.dumps({'identity': previous_state['identity'],
            'port': int(second_base.rsplit(':', 1)[1]), 'token': '0' * 64, 'instance': 'stale'}), encoding='utf-8')
        assert command(one, env, 'start', '--no-browser') == base
        assert sha((one / 'data/platform.sqlite3').read_bytes()) == database_hash
        assert originals(one / 'data') == before
        researcher.login('researcher')
        assert researcher.request('/api/records/' + rid)['id'] == rid
        assert researcher.request('/api/session')['user']['id'] == 'researcher'
        assert peer.request('/api/session')['user']['id'] == 'colleague'
        assert not (evidence / 'forbidden-data').exists()
        if baseline8848:
            assert HTTP('http://127.0.0.1:8848').request('/health') == baseline8848
        result['checks'].append('restart preserves database/original hashes and added upload; old port reused; stale state safe; stopping one leaves other and 8848 healthy')
        if args.browser:
            browser_check(base, evidence)
            result['checks'].append('real Chromium: all three role login and collaboration rendering; no page errors')
        result['ok'] = True
    finally:
        for root in (one, two):
            if root.exists():
                try:
                    command(root, env, 'stop')
                except Exception as error:
                    result.setdefault('cleanup_errors', []).append(str(error))
        (evidence / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': result['ok'], 'evidence': str(evidence), 'checks': result['checks']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
