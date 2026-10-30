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
import re
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


def batch(root, env, action, *args):
    # Only fixed action/options are supplied; no user content is interpreted as shell code.
    result = subprocess.run([str(Path(env['SYSTEMROOT']) / 'System32/cmd.exe'), '/d', '/c',
        'call', action + '.bat', *args], cwd=root, env=env,
        capture_output=True, text=True, encoding='utf-8', timeout=150)
    assert result.returncode == 0, result.stdout + result.stderr
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
    assert seed['synthetic'] is False and seed['fictional_collaboration'] is True
    assert {x['username'] for x in admin.request('/api/members')['items']} == {'researcher', 'colleague', 'admin'}
    sources = client.request('/api/sources')['items']
    assert {x['name'] for x in sources if x['id'] in seed['source_ids']} == {'演示｜北岸公共研究所', '演示｜河港社会研究中心', '演示｜波罗的海协作评论'}
    assert {x['id'] for x in sources} == set(seed['source_ids'] + seed['public_batch']['source_ids'])
    people = client.request('/api/people')['items']
    assert {x['name'] for x in people} == {'演示｜安娜·河港', '演示｜马丁·北岸'}
    assert {x['id'] for x in people} == set(seed['person_ids'])
    records = client.request('/api/records?size=100')['items']
    assert len(records) == 62, len(records)
    assert all('演示' in x['title'] for x in records if x['id'] not in seed['public_batch']['article_ids'])
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
        assert client.request('/api/records/' + rid + '/bylines')['items'][0]['target_id'] in seed['person_ids']
    ingestion = admin.request('/api/ingestion')
    assert not ingestion['worker_heartbeat']
    assert all(not s['enabled'] and not s['runs'] for s in ingestion['items'])
    ai = admin.request('/api/admin/ai')
    assert ai['attempts'] == [] and not ai['worker_heartbeat'] and not ai['cap_units'] and ai['paused']
    assert ai['task_counts'] == {} and ai['blocked_reasons']
    return seed, workflow, journal


def verify_public_batch(client, admin, seed):
    from portable.public_batch import load_fixture, FIXTURE_SHA256
    fixture, batch = load_fixture(), seed['public_batch']
    assert batch['fixture_sha256'] == FIXTURE_SHA256
    assert len(batch['source_ids']) == 65 and len(batch['core_source_ids']) == 38
    collection = next(c for c in client.request('/api/collections')['items'] if c['id'] == batch['collection_id'])
    assert collection['name'] == '历史17国公开资料样本' and collection['visibility'] == 'shared'
    assert client.request('/api/records?size=100&collection=' + batch['collection_id'])['total'] == 56
    snapshots = {}
    for article in fixture['articles']:
        record = client.request('/api/records/' + batch['article_map'][article['id']])
        job = record['translations'][0]
        assert (record['original_title'], record['display_title']) == (article['original_title'], article['machine_title'])
        assert (record['abstract'], record['display_abstract']) == (article['abstract_original_preview'], article['abstract_machine_preview'])
        assert record['status'] == 'pending' and record['translation_origin'] == 'machine'
        assert not record['chinese_title'] and not record['chinese_abstract'] and not record['adopted_translation_id']
        assert not record['attachments'] and not record['linked_records'] and not record.get('collaboration_works')
        assert not record['body_html'] and not record['reading_access']['has_body']
        assert job['attempts'] == 0 and job['calls'] == [] and not job['can_adopt'] and not job['stale']
        provenance = job['preview_import']
        assert provenance['source_input_hash'] == article['translation_input_hash']
        assert provenance['source_version'] == article['translation_source_version']
        assert provenance['source_job_id'] == article['translation_id']
        assert provenance['alignment'] == 'independent_truncation' and provenance['full_content_excluded'] is True
        expected = sha(json.dumps([article['original_title'], article['abstract_original_preview']], ensure_ascii=False).encode())
        assert job['input_hash'] == expected == provenance['excerpt_input_hash']
        assert len(record['abstract'].split()) <= 20 and len(job['output_abstract']) <= 120
        snapshots[record['id']] = {key: record[key] for key in ['original_title', 'abstract', 'display_title', 'display_abstract', 'translations', 'preview_excerpt']}
    assert sum(bool(r['abstract']) for r in snapshots.values()) == 23
    assert client.request('/api/records?q=' + urllib.parse.quote('平台工作者'))['total'] == 1
    ai = admin.request('/api/admin/ai')
    assert ai['attempts'] == [] and ai['task_counts'] == {} and ai['paused'] and not ai['cap_units']
    return snapshots


def browser_check(base, second_base, evidence, seed):
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
            if page.get_by_role('button', name=re.compile(r'^退出(?:登录)?$')).count():
                page.get_by_role('button', name=re.compile(r'^退出(?:登录)?$')).click()
            page.get_by_label('账号', exact=True).fill(name)
            page.get_by_label('密码', exact=True).fill('LocalDemo2026!')
            page.get_by_role('button', name='查看资料', exact=True).click()
            expect(page.get_by_role('heading', name='编译协作', exact=True)).to_be_visible()
            page.screenshot(path=str(evidence / f'browser-{name}.png'), full_page=True)
            page.get_by_role('button', name=re.compile(r'^退出(?:登录)?$')).click()
            expect(page.get_by_label('账号', exact=True)).to_be_visible()
        # A single real browser context shares cookies between both localhost ports.
        page.goto(base)
        page.get_by_label('账号', exact=True).fill('researcher')
        page.get_by_label('密码', exact=True).fill('LocalDemo2026!')
        page.get_by_role('button', name='查看资料', exact=True).click()
        expect(page.get_by_role('heading', name='编译协作', exact=True)).to_be_visible()
        batch = seed['public_batch']
        page.goto(base + '/#library?feed=all&collection=' + batch['collection_id'])
        expect(page.locator('.record-title button').first).to_be_visible()
        assert page.evaluate("async()=> (await(await fetch('/api/records?size=100&collection=' + " + json.dumps(batch['collection_id']) + ")).json()).total") == 56
        page.goto(base + '/#library?feed=all&q=' + urllib.parse.quote('平台工作者'))
        expect(page.locator('.record-title button')).to_have_count(1)
        page.locator('.record-title button').click()
        reader = page.locator('.library-reader')
        expect(reader.get_by_text('机器中文 · 尚未人工校订', exact=True)).to_be_visible()
        expect(reader.get_by_role('heading', name='中文摘要节选', exact=True)).to_be_visible()
        expect(reader.get_by_text(re.compile('原摘要与历史机器译文独立截取'))).to_be_visible()
        reader.get_by_role('button', name='原文', exact=True).click()
        expect(reader.locator('[data-reading-abstract="original"] h3')).to_have_text('原文摘要节选')
        for width in [1366, 390]:
            page.set_viewport_size({'width': width, 'height': 900})
            page.screenshot(path=str(evidence / f'public-preview-{width}.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        page.set_viewport_size({'width': 1366, 'height': 900})
        page.goto(base)
        expect(page.get_by_role('heading', name='编译协作', exact=True)).to_be_visible()
        peer = context.new_page()
        peer.on('pageerror', lambda error: errors.append(str(error)))
        peer.goto(second_base)
        expect(peer.get_by_label('账号', exact=True)).to_be_visible()
        peer.get_by_label('账号', exact=True).fill('colleague')
        peer.get_by_label('密码', exact=True).fill('LocalDemo2026!')
        peer.get_by_role('button', name='查看资料', exact=True).click()
        expect(peer.get_by_role('heading', name='编译协作', exact=True)).to_be_visible()
        session = "async()=> (await(await fetch('/api/session')).json()).user.id"
        assert page.evaluate(session) == 'researcher'
        assert peer.evaluate(session) == 'colleague'
        assert len({cookie['name'] for cookie in context.cookies() if cookie['name'].startswith('preview_')}) == 2
        peer.get_by_role('button', name=re.compile(r'^退出(?:登录)?$')).click()
        expect(peer.get_by_label('账号', exact=True)).to_be_visible()
        page.reload()
        expect(page.get_by_role('heading', name='编译协作', exact=True)).to_be_visible()
        assert page.evaluate(session) == 'researcher'
        page.screenshot(path=str(evidence / 'browser-shared-context.png'), full_page=True)
        assert not errors, errors
        browser.close()


def continue_work(researcher, lead, admin, seed):
    """Continue the supplied unfinished work over the real embedded HTTP server."""
    source = researcher.request('/api/sources', {'name': '演示｜验收贡献来源',
        'kind': 'institution', 'website': 'https://example.invalid/acceptance/source'})['id']
    detail = lead.request('/api/sources/' + source)
    assert (detail['status'], detail['scope_status']) == ('pending', 'candidate')
    assert detail['automatic_collection'] == {'supported': False, 'enabled': False}
    admin.request('/api/review/source/' + source, {'version': detail['version'],
        'review_scope': 'metadata_only', 'review_note': '只核对合成演示来源，不确认任何真实研究事实'})
    assert researcher.request('/api/sources/' + source)['status'] == 'verified'

    prefix = '/api/collaboration/topics/' + seed['active_topic']
    candidate = researcher.request(prefix + '/candidates', {'request_id': 'http-candidate-2',
        'version': 1, 'topic_version': 1, 'note': '真实HTTP提交继续演示'},
        file=('验收候选-v2.txt', b'DEMO HTTP candidate v2'))['id']
    lead.request(prefix + '/meetings', {'request_id': 'http-meeting', 'version': 0,
        'topic_version': 1, 'note': '负责人实际接续研究员候选v2', 'assignments': [{
            'title': '演示｜验收继续编译', 'candidate_id': candidate,
            'candidate_item': '第1项', 'record_id': seed['article_ids'][1],
            'author_id': 'researcher', 'country': '拉脱维亚'}]},
        file=('验收会议.txt', b'DEMO HTTP meeting adopts candidate v2'))
    assignment = prefix + '/assignments/' + researcher.request(prefix + '/workflow')['assignments'][0]['id']
    first = researcher.request(assignment + '/submissions', {'request_id': 'http-draft-1',
        'version': 0, 'topic_version': 1, 'meeting_version': 1},
        file=('验收初稿.txt', b'DEMO HTTP manuscript v1'))['id']
    lead.request(assignment + '/returns', {'request_id': 'http-return', 'submission_id': first,
        'topic_version': 1, 'meeting_version': 1, 'note': '演示审稿：补齐第1段出处'})
    revised = b'DEMO HTTP revised manuscript v2; synthetic paragraph 1'
    second = researcher.request(assignment + '/submissions', {'request_id': 'http-draft-2',
        'version': 1, 'topic_version': 1, 'meeting_version': 1},
        file=('验收返修.txt', revised))['id']
    final = lead.request(assignment + '/finals', {'request_id': 'http-final',
        'submission_id': second, 'version': 2, 'topic_version': 1, 'meeting_version': 1,
        'status': 'pending', 'visibility': 'shared', 'sharing_confirmed': True})
    researcher.request('/api/records/' + final['record_id'] + '/author', {'version': 1, 'confirm': True})
    researcher.request(prefix + '/summaries', {'request_id': 'http-summary', 'version': 0,
        'topic_version': 1, 'author_id': 'researcher', 'final_ids': [final['id']]},
        file=('验收汇总.txt', b'DEMO HTTP summary adopts exact revised manuscript v2'))
    workflow = researcher.request(prefix + '/workflow')
    row = workflow['assignments'][0]
    assert [s['version'] for s in row['submissions']] == [2, 1]
    assert row['returns'][0]['submission_id'] == first
    assert workflow['summaries'][0]['adoptions'][0]['submission_id'] == second
    assert researcher.request(row['submissions'][0]['file_url'], raw=True) == revised

    path = '/api/collaboration/journals/' + seed['journal']
    previous = researcher.request(path)
    current = lead.request(path + '/submissions', {'version': previous['version'],
        'request_id': 'http-journal', 'material_kind': 'product'},
        file=('验收期刊-v3.txt', b'DEMO HTTP shared journal product v3'))['id']
    journal = researcher.request(path)
    assert journal['current_product_id'] == previous['current_product_id']
    researcher.request(path + '/product', {'version': journal['version'], 'submission_id': current})
    journal = researcher.request(path)
    assert journal['current_product_id'] == current
    assert researcher.request(journal['submissions'][0]['file_url'], raw=True) == b'DEMO HTTP shared journal product v3'
    return workflow, journal


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
        base = batch(one, env, 'start', '--no-browser')
        assert base != 'http://127.0.0.1:8848'
        assert batch(one, env, 'start', '--no-browser') == base
        jar = http.cookiejar.CookieJar()
        researcher = HTTP(base, jar)
        researcher.login('researcher')
        admin = HTTP(base)
        admin.login('admin')
        lead = HTTP(base)
        lead.login('colleague')
        assert lead.request('/api/session')['user']['role'] == 'researcher'
        seed, workflow, journal = verify_seed(one, researcher, admin)
        public_snapshots = verify_public_batch(researcher, admin, seed)
        result['checks'].append('public preview: 65 sources / 38 core; shared collection with 56 machine titles, 23 independent abstract excerpts / 33 title-only; historical provenance and separate input hashes; zero local calls/tasks/fees')
        result['checks'].append('first start: exact synthetic account/source/person/record/original inventory; role login; avatar; PDF/TXT parser; exact topic v2 adoption; independent journal v2')
        active_workflow, journal = continue_work(researcher, lead, admin, seed)
        result['checks'].append('real HTTP continuation: member source contribution/admin metadata review; candidate v2/lead meeting/return/revision/exact final/summary; shared journal v3 explicitly adopted')
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
        second_base = batch(two, env, 'start', '--no-browser')
        assert second_base != base
        peer = HTTP(second_base, jar)
        peer.login('colleague')
        assert researcher.request('/api/session')['user']['id'] == 'researcher'
        assert peer.request('/api/session')['user']['id'] == 'colleague'
        assert len({cookie.name for cookie in jar if cookie.name.startswith('preview_')}) == 2
        peer.request('/api/logout', {})
        assert researcher.request('/api/session')['user']['id'] == 'researcher'
        peer.login('colleague')
        restored_reader = HTTP(second_base)
        restored_reader.login('researcher')
        assert restored_reader.request('/api/collaboration/topics/' + seed['complete_topic'] + '/workflow') == workflow
        assert restored_reader.request('/api/collaboration/topics/' + seed['active_topic'] + '/workflow') == active_workflow
        assert restored_reader.request('/api/collaboration/journals/' + seed['journal']) == journal
        restored_admin = HTTP(second_base)
        restored_admin.login('admin')
        assert verify_public_batch(restored_reader, restored_admin, seed) == public_snapshots
        assert originals(two / 'data') == before
        result['checks'].append('materials/content export; standards-based DOCX indexing/search; full backup CLI restore; same-cookie-jar simultaneous instances')
        previous_state = json.loads((one / '.portable/server.json').read_text(encoding='utf-8'))
        batch(one, env, 'stop')
        batch(one, env, 'stop')
        assert peer.request('/health')['status'] == 'ok'
        assert originals(one / 'data') == before
        database_hash = sha((one / 'data/platform.sqlite3').read_bytes())
        # Stale state with an unrelated port/token must not kill that server.
        (one / '.portable/server.json').write_text(json.dumps({'identity': previous_state['identity'],
            'port': int(second_base.rsplit(':', 1)[1]), 'token': '0' * 64, 'instance': 'stale'}), encoding='utf-8')
        assert batch(one, env, 'start', '--no-browser') == base
        assert sha((one / 'data/platform.sqlite3').read_bytes()) == database_hash
        assert originals(one / 'data') == before
        assert researcher.request('/api/records/' + rid)['id'] == rid
        assert researcher.request('/api/session')['user']['id'] == 'researcher'
        assert peer.request('/api/session')['user']['id'] == 'colleague'
        assert not (evidence / 'forbidden-data').exists()
        assert not admin.request('/api/ingestion')['worker_heartbeat']
        assert not admin.request('/api/admin/ai')['attempts']
        assert not admin.request('/api/admin/ai')['worker_heartbeat']
        if baseline8848:
            assert HTTP('http://127.0.0.1:8848').request('/health') == baseline8848
        result['checks'].append('restart preserves database/original hashes and added upload; old port reused; stale state safe; stopping one leaves other and 8848 healthy')
        if args.browser:
            browser_check(base, second_base, evidence, seed)
            result['checks'].append('real Chromium: all three responsibilities; same browser context authenticates both copies independently and logout stays isolated; no page errors')
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
