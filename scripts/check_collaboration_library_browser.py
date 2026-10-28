"""Fresh schema23 source, restart, new-directory restore and real Chromium UI.

Only synthetic Temp files, frozen public code and dynamically allocated ports.
Uses chrome.tabs.setZoom for actual 200% browser zoom.
"""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from platform_app.web import create_app
from platform_app.maintenance import create_backup
from scripts.check_journal_collaboration_recovery import SEED as OLD_SEED
from scripts.check_topic_finals_browser import serve
from scripts.check_collaboration_browser import no_overflow
from scripts.check_collaboration_recovery import login as account
from scripts.verify_work_materials import verify

LONG_NAME = '合成长原件_' + '多国工作稿件' * 20 + '.txt'
SEED = OLD_SEED.replace("'synthetic.txt'", repr(LONG_NAME)) + r'''
wid=call(a,'/api/collaboration/journals',{'journal_name':'独立期刊复用','coverage':'2025—2026跨期','record_id':rid})['id']
js=call(a,f'/api/collaboration/journals/{wid}/submissions',{'version':1,'request_id':'journal-product-one','material_kind':'product','note':'旧版成品'},b'journal original product')['id']
call(a,f'/api/collaboration/journals/{wid}/product',{'version':2,'submission_id':js,'note':'实际采用'})
call(a,f'/api/collaboration/journals/{wid}/submissions',{'version':3,'request_id':'journal-later-draft','material_kind':'manuscript'},b'journal later original')
note=call(a,'/api/records',{'kind':'research_note','title':'旧研究笔记独立保留','body_html':'<p>旧笔记正文与出处</p>','visibility':'shared','sharing_confirmed':True})['id']
directory=call(a,'/api/records',{'kind':'directory_translation','title':'旧独立跨期译稿','authors':'合成编译者','publication_title':'旧跨期刊名','coverage':'2024—2025','body_html':'<p>旧跨期目录</p>','visibility':'shared','sharing_confirmed':True})['id']
active=call(a,'/api/collaboration/topics',{'theme':'中心成果查找与复用','participant_ids':['colleague']})['id']
call(a,f'/api/collaboration/topics/{active}/meetings',{'version':0,'topic_version':1,'request_id':'active-meeting-one','note':'实际会议决定','assignments':[{'title':'多国编译成果','author_id':'researcher','country':'拉脱维亚、波兰'}]})
assignment=a.get(f'/api/collaboration/topics/{active}/workflow').json['assignments'][0]['id']
sub=call(a,f'/api/collaboration/topics/{active}/assignments/{assignment}/submissions',{'version':0,'topic_version':1,'meeting_version':1,'request_id':'active-manuscript-1'},b'exact adopted topic original')['id']
final=call(a,f'/api/collaboration/topics/{active}/assignments/{assignment}/finals',{'version':1,'topic_version':1,'meeting_version':1,'submission_id':sub,'status':'pending','request_id':'active-final-1','visibility':'shared','sharing_confirmed':True})
summary=call(a,f'/api/collaboration/topics/{active}/summaries',{'version':0,'topic_version':1,'author_id':'researcher','final_ids':[final['id']],'request_id':'active-summary-1'},b'exact assembled issue original')
call(a,f'/api/collaboration/topics/{active}/assignments/{assignment}/submissions',{'version':1,'topic_version':1,'meeting_version':1,'request_id':'active-manuscript-2'},b'later unadopted original')
payload.update(active=active,assignment=assignment,final=final,summary=summary,note=note,directory=directory,journal_id=wid,journal=a.get('/api/collaboration/journals/'+wid).json,active_workflow=a.get('/api/collaboration/topics/'+active+'/workflow').json,qualifications=admin.get('/api/collaboration/qualifications').json)
Path(sys.argv[2]).write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
'''


def nav(page, label):
    button = page.get_by_role('button', name='打开导航', exact=True)
    if button.is_visible():
        button.click()
    page.get_by_role('button', name=label, exact=True).click()


def login(page, base, name):
    page.goto(base)
    page.get_by_label('账号', exact=True).fill(name)
    page.get_by_label('密码', exact=True).fill('LocalDemo2026!')
    page.get_by_role('button', name='查看资料', exact=True).click()
    expect(page.get_by_role('heading', name='编译协作', exact=True)).to_be_visible()


def check_http(app, before, evidence, suffix):
    lead, peer, admin = [account(app, name) for name in ('researcher', 'colleague', 'admin')]
    assert lead.get('/health').json['schema'] == 23
    assert admin.get('/api/collaboration/qualifications').json == before['qualifications']
    assert lead.get('/api/collaboration/topics/' + before['active'] + '/workflow').json == before['active_workflow']
    assert lead.get('/api/collaboration/journals/' + before['journal_id']).json == before['journal']
    assert lead.get('/api/history/record/' + before['record']['id']).json == before['history']
    assert peer.get('/api/history/record/' + before['record']['id']).status_code == 403
    with peer.get('/api/attachments/' + before['record']['attachment_ids'][0]) as r:
        assert r.data == b'legacy journal attachment'
    for old in before['topic_files']:
        with lead.get(old['url']) as r:
            assert r.data == old['raw'].encode()
    assert peer.get('/api/records/' + before['note']).json['body_html'] == '<p>旧笔记正文与出处</p>'
    assert peer.get('/api/records/' + before['directory']).json['coverage'] == '2024—2025'
    hashes = {}
    for business, wid in [('topic', before['active']), ('journal', before['journal_id'])]:
        for scope in ('all', 'products', 'process'):
            with lead.get(f'/api/collaboration/materials/{business}/{wid}?scope={scope}') as response:
                assert response.status_code == 200, response.json
                path = evidence / f'{suffix}-{business}-{scope}.zip'
                path.write_bytes(response.data)
                verify(path)
                with zipfile.ZipFile(path) as z:
                    m = json.loads(z.read('manifest.json'))
                    hashes[business + scope] = sorted((f['file_id'], f['sha256']) for f in m['files'])
    return hashes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', default='0e327ab3fcc2c30f02c3e487f60cf8d0158a6d0c')
    args = parser.parse_args()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    root = Path(__file__).resolve().parents[1]
    evidence = Path(tempfile.mkdtemp(prefix='database-collaboration-library-'))
    (Path(tempfile.gettempdir()) / 'database-collaboration-library-latest.txt').write_text(str(evidence), encoding='utf-8')
    print(json.dumps({'evidence': str(evidence)}), flush=True)
    frozen, source, data = evidence / 'schema23-source.zip', evidence / 'schema23-source', evidence / 'data'
    subprocess.run(['git', 'archive', args.baseline, 'platform_app', '-o', str(frozen)], cwd=root, check=True, capture_output=True)
    with zipfile.ZipFile(frozen) as z:
        z.extractall(source)
    seeded = subprocess.run([sys.executable, '-c', SEED, str(data), str(evidence / 'before.json')], cwd=source, capture_output=True, text=True, encoding='utf-8')
    assert seeded.returncode == 0, seeded.stderr
    before = json.loads((evidence / 'before.json').read_text(encoding='utf-8'))
    assert before['schema'] == 23
    sqlite_before = hashlib.sha256((data / 'platform.sqlite3').read_bytes()).hexdigest()
    app = create_app(data, testing=True)
    assert hashlib.sha256((data / 'platform.sqlite3').read_bytes()).hexdigest() == sqlite_before, 'Read-only feature changed old database on startup'
    expected = check_http(app, before, evidence, 'restart')
    # Backup and CLI restore to an absent directory, then HTTP and real browser.
    backup = create_backup(data)
    restored = evidence / 'new-directory-restored'
    subprocess.run([sys.executable, '-m', 'platform_app.maintenance', '--restore', str(backup), '--target', str(restored)], cwd=root, check=True, capture_output=True)
    recovered = create_app(restored, testing=True)
    assert check_http(recovered, before, evidence, 'restored') == expected
    extension = evidence / 'zoom-extension'
    extension.mkdir()
    (extension / 'manifest.json').write_text(json.dumps({'manifest_version': 3, 'name': 'Synthetic actual zoom check', 'version': '1.0', 'permissions': ['tabs'], 'background': {'service_worker': 'worker.js'}}))
    (extension / 'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
    server, thread, base = serve(app)
    restored_server, restored_thread, restored_base = serve(recovered)
    results, errors = [], []
    try:
        with sync_playwright() as p:
            executable = os.environ.get('DATABASE_BROWSER_EXECUTABLE')
            context = p.chromium.launch_persistent_context(str(evidence / 'profile'), headless=False,
                **({'executable_path': executable} if executable else {}), ignore_default_args=['--disable-extensions'],
                args=['--headless=new', f'--disable-extensions-except={extension}', f'--load-extension={extension}'], viewport={'width': 1366, 'height': 900}, accept_downloads=True)
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page = context.pages[0]
            page.on('pageerror', lambda error: errors.append(str(error)))
            for width, zoom in ((1366, 1), (390, 1), (1366, 2)):
                page.set_viewport_size({'width': width, 'height': 900})
                page.goto(base)
                worker.evaluate("async ({url,zoom})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,zoom)}", {'url': base, 'zoom': zoom})
                actual_zoom = worker.evaluate("async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));return chrome.tabs.getZoom(t.id)}", base)
                assert actual_zoom == zoom
                login(page, base, 'researcher')
                page.get_by_label('主题或期刊', exact=True).fill('中心成果')
                page.get_by_text('国家分工、参与人与时间', exact=True).click()
                page.get_by_label('国家分工', exact=True).fill('拉脱维亚')
                page.get_by_label('参与人', exact=True).fill('researcher')
                page.get_by_role('button', name='查找工作', exact=True).focus()
                page.keyboard.press('Enter')
                expect(page.locator('[data-work-id]')).to_have_count(1)
                saved_hash = page.evaluate('location.hash')
                page.get_by_role('button', name='中心成果查找与复用', exact=True).click()
                expect(page.get_by_role('heading', name='中心成果查找与复用', exact=True)).to_be_visible()
                page.get_by_text('完整文件名', exact=True).first.click()
                expect(page.get_by_text(LONG_NAME, exact=True).first).to_be_visible()
                page.get_by_text('核对采用的 1 篇具体定稿版本', exact=True).click()
                with page.expect_download() as download:
                    page.get_by_role('link', name='下载所采用的定稿 v1', exact=True).click()
                assert Path(download.value.path()).read_bytes() == b'exact adopted topic original'
                assert download.value.suggested_filename == LONG_NAME
                page.get_by_text('下载本期材料包', exact=True).click()
                with page.expect_download() as download:
                    page.get_by_role('link', name='成果原件', exact=True).click()
                package = evidence / f'ui-topic-{width}-{zoom}.zip'
                download.value.save_as(package)
                assert verify(package) == 2
                no_overflow(page)
                page.get_by_role('button', name='← 返回主题工作', exact=True).click()
                expect(page.get_by_label('主题或期刊', exact=True)).to_have_value('中心成果')
                assert page.evaluate('location.hash') == saved_hash
                nav(page, '中心成果')
                expect(page.locator('[data-work-id="'+before['active']+'"]')).to_be_visible()
                page.get_by_role('button', name='期刊编译', exact=True).click()
                page.get_by_role('button', name='独立期刊复用 · 2025—2026跨期', exact=True).click()
                page.get_by_text('期刊工作与成品采用历史', exact=True).click()
                page.get_by_role('button', name='读取期刊历史', exact=True).click()
                expect(page.get_by_text('工作 v3 · 采用为当前成品：实际采用', exact=True)).to_be_visible()
                page.get_by_text('下载本期材料包', exact=True).click()
                with page.expect_download() as download:
                    page.get_by_role('link', name='全部已提交材料', exact=True).click()
                package = evidence / f'ui-journal-{width}-{zoom}.zip'
                download.value.save_as(package)
                assert verify(package) == 2
                page.get_by_role('button', name='← 返回中心成果', exact=True).click()
                expect(page.get_by_role('heading', name='中心成果', exact=True)).to_be_visible()
                layout = no_overflow(page)
                layout['client_width'] = page.evaluate('document.documentElement.clientWidth')
                bounds = page.evaluate("[...document.querySelectorAll('.work-discovery input,.work-discovery button,.work-discovery h1,.work-discovery h2')].filter(e=>e.getClientRects().length).map(e=>({tag:e.tagName,text:e.textContent,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right})).filter(r=>r.left < -1 || r.right > document.documentElement.clientWidth+1)")
                assert not bounds, bounds
                page.screenshot(path=str(evidence / f'products-{width}-{zoom}.png'), full_page=True)
                page.screenshot(path=str(evidence / f'viewport-{width}-{zoom}.png'), full_page=False)
                page.get_by_role('button', name='独立成果与跨期译稿', exact=True).click()
                expect(page.get_by_role('heading', name='独立成果与跨期译稿', exact=True)).to_be_visible()
                page.get_by_role('button', name='全部资料与旧研究积累', exact=True).click()
                expect(page.get_by_role('button', name='旧研究笔记独立保留', exact=True)).to_be_visible()
                page.goto(base+'/#compilations?kind=research_note&q=旧研究笔记')
                expect(page.get_by_role('button', name='旧研究笔记独立保留', exact=True)).to_be_visible()
                assert page.evaluate('location.hash').startswith('#library?')
                page.goto(base+'/#collaboration?q=不存在的合成工作')
                expect(page.get_by_role('heading', name='当前范围暂无工作', exact=True)).to_be_visible()
                page.goto(base+'/#collaboration?id=missing-synthetic')
                expect(page.get_by_role('button', name='返回工作查找', exact=True)).to_be_visible()
                page.get_by_role('button', name='返回工作查找', exact=True).click()
                expect(page.get_by_role('heading', name='编译协作', exact=True)).to_be_visible()
                page.get_by_role('button', name='退出登录', exact=True).click()
                results.append({'width': width, 'actual_zoom': actual_zoom, 'layout': layout, 'client_width': layout['client_width'], 'out_of_bounds_controls': bounds, 'long_filename_and_original_download': True,  'keyboard_search': True, 'topic_and_journal_download': True, 'filtered_return': True, 'old_notes_preserve_query': True, 'empty_and_error_return': True})
            login(page, base, 'admin')
            page.get_by_role('button', name='维护查阅', exact=True).click()
            page.get_by_role('button', name='中心成果查找与复用', exact=True).click()
            assert page.get_by_role('button', name='确认当前稿件定稿', exact=True).count() == 0
            assert page.get_by_role('button', name='提交整期汇总', exact=True).count() == 0
            page.get_by_role('button', name='退出登录', exact=True).click()
            page.goto(restored_base)
            worker.evaluate("async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,1)}", restored_base)
            login(page, restored_base, 'colleague')
            nav(page, '中心成果')
            page.get_by_role('button', name='中心成果查找与复用', exact=True).click()
            page.get_by_text('下载本期材料包', exact=True).click()
            with page.expect_download() as download:
                page.get_by_role('link', name='全部已提交材料', exact=True).click()
            package = evidence / 'restored-browser-all.zip'
            download.value.save_as(package)
            assert verify(package) == 3
            page.screenshot(path=str(evidence / 'restored-browser.png'), full_page=True)
            assert not errors, errors
            context.close()
    finally:
        for service, worker_thread in [(server, thread), (restored_server, restored_thread)]:
            service.shutdown()
            worker_thread.join(timeout=5)
            service.server_close()
        (evidence / 'results.json').write_text(json.dumps({'baseline': args.baseline, 'schema_before': 23, 'schema_after': 23, 'startup_database_unchanged': True, 'new_directory_cli_restore_http': True, 'results': results, 'page_errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'evidence': str(evidence), 'results': results, 'restored_browser_download': True, 'page_errors': errors}, ensure_ascii=False))


if __name__ == '__main__':
    main()
