"""Review regressions for #75 through synthetic HTTP and real browser UI."""
import argparse
import json
import logging
import os
import re
import struct
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from platform_app.web import create_app
from platform_app.maintenance import create_backup, restore_backup
from scripts.check_reader_maintenance_browser import account, call, login, no_overflow
from scripts.check_topic_finals_browser import serve


def fixtures(context, base, suffix):
    account(context, base, 'researcher')
    pairs = {}
    for key, kind, editors in [('own', 'compilation', []), ('editor', 'research_report', ['colleague'])]:
        pairs[key] = [call(context, base, '/api/records', {'kind': kind, 'title': '个人合成重复 '+suffix+' '+key,
            'visibility': 'restricted', 'body_html': '<p>原有作者正文</p>', 'editors': editors}, expected=201)['id'] for _ in range(2)]
    pairs['public'] = [call(context, base, '/api/records', {'kind': 'report', 'title': '公共合成重复 '+suffix,
        'visibility': 'shared', 'sharing_confirmed': True}, expected=201)['id'] for _ in range(2)]
    account(context, base, 'colleague')
    pairs['other'] = [call(context, base, '/api/records', {'kind': 'compilation', 'title': '他人合成重复 '+suffix,
        'visibility': 'shared', 'sharing_confirmed': True}, expected=201)['id'] for _ in range(2)]
    account(context, base, 'researcher')
    return pairs


def legacy(page, base):
    requests = []
    def capture(req):
        if '/api/collaboration/works?' in req.url and 'scope=maintenance' in req.url:
            requests.append(req.url)
    page.on('request', capture)
    try:
        for route in ('collaboration?scope=maintenance', 'compilations?scope=maintenance'):
            page.goto(base+'/#'+route)
            expect(page.get_by_role('heading', name='此入口供资料管理员使用', exact=True)).to_be_visible(timeout=2500)
            page.get_by_role('button', name='返回研究界面', exact=True).click()
            expect(page.get_by_role('heading', name='编译协作', exact=True)).to_be_visible()
        assert not requests, requests
        page.goto(base+'/#collaboration?scope=all&q=保留查找')
        expect(page.get_by_role('heading', name='编译协作', exact=True)).to_be_visible()
        assert 'q=' in page.url
    finally:
        page.remove_listener('request', capture)


def source(page, base, evidence, suffix):
    account(page.context, base, 'admin'); page.reload()
    name='继续核对来源 '+suffix
    sid=call(page.context, base, '/api/sources', {'name': name, 'kind': 'institution'}, expected=201)['id']
    route='#maintenance-sources?q='+name+'&status=pending'
    page.goto(base+'/'+route)
    expect(page.get_by_role('heading', name='来源维护', exact=True)).to_be_visible()
    page.get_by_role('button', name='快速预览', exact=True).click()
    page.get_by_role('button', name='编辑来源', exact=True).click()
    page.get_by_label('显示名称 *', exact=True).fill(name+' 修订')
    page.get_by_role('button', name='保存修订', exact=True).click()
    expect(page.get_by_role('dialog', name='来源快速预览', exact=True)).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('#content h1')).to_have_text('来源维护', timeout=2500)
    expect(page.get_by_label('来源关键词', exact=True)).to_have_value(name)
    expect(page.get_by_label('核对状态', exact=True)).to_have_value('pending')
    expect(page.get_by_role('link', name=name+' 修订', exact=True)).to_be_visible()
    assert 'status=pending' in page.url and 'maintenance-sources?' in page.url
    no_overflow(page)
    page.screenshot(path=str(evidence/('source-refresh-'+suffix+'.png')), full_page=False)
    # The refreshed queue still permits the next review without leaving maintenance.
    page.get_by_role('button', name='快速预览', exact=True).click()
    page.get_by_text('历史与维护', exact=True).click()
    page.get_by_role('button', name='标记已核对', exact=True).click()
    page.get_by_role('dialog').get_by_role('combobox').select_option('metadata_only')
    page.get_by_role('dialog').get_by_role('textbox').fill('仅核对合成来源信息')
    page.get_by_role('button', name='记录核对', exact=True).click()
    assert page.request.get(base+'/api/sources/'+sid).json()['status']=='verified'
    page.keyboard.press('Escape')
    for old in ('collaboration', 'compilations'):
        page.goto(base+'/#'+old+'?scope=maintenance&q=保留查找')
        expect(page).to_have_url(re.compile('.*#maintenance-work\\?.*'))
        expect(page.get_by_role('heading', name='编译协作', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='维护查阅', exact=True)).to_be_visible()
        expect(page.get_by_label('主题或期刊', exact=True)).to_have_value('保留查找')
    account(page.context, base, 'researcher'); page.reload()
    page.goto(base+'/#library?feed=all')
    return sid


def personal(page, base, pairs, evidence, suffix, merge=True):
    account(page.context, base, 'researcher'); page.reload()
    page.goto(base+'/#library?feed=all')
    page.get_by_text('整理与导出', exact=True).click()
    expect(page.get_by_role('button', name='整理个人成果重复', exact=True)).to_be_visible(timeout=2500)
    page.get_by_role('button', name='整理个人成果重复', exact=True).click()
    expect(page.get_by_role('dialog', name='整理个人成果重复', exact=True)).to_be_visible()
    choices=page.get_by_label('保留的主记录', exact=True)
    ids=choices.locator('option').evaluate_all('(items)=>items.map(x=>x.value).filter(Boolean)')
    assert set(pairs['own']+pairs['editor']).issubset(ids), ids
    assert not set(pairs['public']+pairs['other']).intersection(ids), ids
    for pair in page.locator('[data-action="compare-duplicate"]').all():
        assert pair.get_attribute('data-keep') in ids and pair.get_attribute('data-duplicate') in ids
    no_overflow(page)
    page.screenshot(path=str(evidence/('personal-choices-'+suffix+'.png')), full_page=False)
    choices.select_option(pairs['own'][0])
    page.get_by_label('待合并记录', exact=True).select_option(pairs['own'][1])
    page.get_by_role('button', name='比较与查看影响', exact=True).focus()
    page.keyboard.press('Enter')
    expect(page.get_by_role('button', name='确认合并', exact=True)).to_be_visible()
    if merge:
        page.get_by_role('checkbox').check()
        page.get_by_role('button', name='确认合并', exact=True).focus()
        page.keyboard.press('Enter')
        expect(page.get_by_role('dialog', name='个人编译成果', exact=True)).to_be_visible()
        assert page.request.get(base+'/api/records/'+pairs['own'][1]).json()['id']==pairs['own'][0]
    page.keyboard.press('Escape')
    account(page.context, base, 'colleague'); page.reload()
    page.goto(base+'/#library?feed=all')
    page.get_by_text('整理与导出', exact=True).click()
    page.get_by_role('button', name='整理个人成果重复', exact=True).click()
    expect(page.get_by_role('dialog', name='整理个人成果重复', exact=True)).to_be_visible()
    ids=page.get_by_label('保留的主记录', exact=True).locator('option').evaluate_all('(items)=>items.map(x=>x.value).filter(Boolean)')
    assert set(pairs['editor']).issubset(ids), {'choices':ids,'expected':pairs['editor']}
    assert not set(pairs['own']+pairs['public']).intersection(ids), ids
    page.get_by_label('保留的主记录', exact=True).select_option(pairs['editor'][0])
    page.get_by_label('待合并记录', exact=True).select_option(pairs['editor'][1])
    page.get_by_role('button', name='比较与查看影响', exact=True).click()
    expect(page.get_by_role('button', name='确认合并', exact=True)).to_be_visible()
    if merge:
        page.get_by_role('checkbox').check()
        page.get_by_role('button', name='确认合并', exact=True).click()
        expect(page.get_by_role('dialog', name='个人研究报告', exact=True)).to_be_visible()
        assert page.request.get(base+'/api/records/'+pairs['editor'][1]).json()['id']==pairs['editor'][0]
    page.keyboard.press('Escape')
    account(page.context, base, 'researcher'); page.reload()
    page.goto(base+'/#library?feed=all')


def late_refresh(page, base):
    """An old administrator response cannot repaint the next member's page."""
    account(page.context,base,'admin'); page.reload()
    sid=call(page.context,base,'/api/sources',{'kind':'institution','name':'账号切换迟到合成来源'},expected=201)['id']
    page.goto(base+'/#maintenance-sources?q=账号切换迟到合成来源&status=pending')
    page.get_by_role('button',name='快速预览',exact=True).click()
    page.get_by_role('button',name='编辑来源',exact=True).click()
    pending=[]
    def hold(route):
        pending.append((route,route.fetch()))
    pattern=re.compile(r'/api/sources\?')
    page.route(pattern,hold)
    try:
        page.get_by_role('button',name='保存修订',exact=True).click()
        expect(page.get_by_role('dialog')).to_have_count(0)
        assert pending, 'Background source refresh must be held before changing account'
        page.get_by_role('button',name='退出登录',exact=True).click()
        page.get_by_role('button',name='研究员',exact=True).click()
        expect(page.get_by_role('heading',name='此入口供资料管理员使用',exact=True)).to_be_visible()
        for route,response in pending:
            route.fulfill(response=response)
        pending.clear()
        page.wait_for_load_state('networkidle')
        expect(page.get_by_role('dialog')).to_have_count(0)
        expect(page.get_by_label('来源关键词',exact=True)).to_have_count(0)
        expect(page.get_by_role('heading',name='此入口供资料管理员使用',exact=True)).to_be_visible()
    finally:
        for route,response in pending:
            route.fulfill(response=response)
        page.unroute(pattern,hold)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--red', action='store_true')
    parser.add_argument('--late-only', action='store_true')
    args=parser.parse_args()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    evidence=Path(tempfile.mkdtemp(prefix='database-reader-maintenance-75-fixes-'))
    (Path(tempfile.gettempdir())/'database-reader-maintenance-75-fixes-latest.txt').write_text(str(evidence), encoding='utf-8')
    print(json.dumps({'evidence':str(evidence)}), flush=True)
    app=create_app(evidence/'data', testing=True)
    servers=[serve(app)]
    results=[]
    try:
        with sync_playwright() as p:
            ext=evidence/'zoom-extension'; ext.mkdir()
            (ext/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Actual zoom verification','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}), encoding='utf-8')
            (ext/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});', encoding='utf-8')
            browser=p.chromium.launch_persistent_context(str(evidence/'profile'), executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None, headless=False, ignore_default_args=['--disable-extensions'], args=['--headless=new',f'--disable-extensions-except={ext}',f'--load-extension={ext}'], viewport={'width':1366,'height':900})
            worker=browser.service_workers[0] if browser.service_workers else browser.wait_for_event('serviceworker')
            page=browser.pages[0]; base=servers[0][2]
            errors=[]; page.on('pageerror', lambda error: errors.append(str(error)))
            login(page, base, 'researcher')
            if args.late_only:
                late_refresh(page,base)
                results.append({'late_account_refresh':True})
                browser.close()
                return
            for width, zoom in ([(1366,1)] if args.red else [(1366,1),(390,1),(1366,2)]):
                suffix=f'{width}-{zoom}'
                page.set_viewport_size({'width':width,'height':900})
                worker.evaluate("async ({base,zoom})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(t.id,zoom)}", {'base':base,'zoom':zoom})
                actual=worker.evaluate("async base=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));return chrome.tabs.getZoom(t.id)}", base)
                assert actual==zoom
                pairs=fixtures(browser, base, suffix)
                for name, check in [('legacy', lambda: legacy(page,base)), ('source', lambda: source(page,base,evidence,suffix)), ('personal', lambda: personal(page,base,pairs,evidence,suffix))]:
                    account(browser,base,'researcher'); page.reload(); page.goto(base+'/#library?feed=all')
                    try:
                        value=check(); results.append({'case':name,'width':width,'zoom':actual,'passed':True,'value':value})
                    except Exception as error:
                        page.screenshot(path=str(evidence/(name+'-failure-'+suffix+'.png')), full_page=False)
                        results.append({'case':name,'width':width,'zoom':actual,'passed':False,'error':str(error)})
                        if not args.red:
                            raise
                metrics=page.evaluate('({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})')
                screenshot=evidence/('viewport-'+suffix+'.png')
                page.screenshot(path=str(screenshot),full_page=False,scale='css')
                pixels=struct.unpack('>II',screenshot.read_bytes()[16:24])
                results.append({'metrics':metrics,'zoom':actual,'zoom_method':'chrome.tabs.setZoom/getZoom','screenshot_pixels':pixels,'browser_user_agent':page.evaluate('navigator.userAgent')})
            if not args.red:
                late_refresh(page,base)
                results.append({'late_account_refresh':True})
                pairs=fixtures(browser,base,'restore')
                backup=create_backup(evidence/'data'); target=evidence/'new-directory-restored'
                assert not target.exists(); restore_backup(backup,target)
                restored=create_app(target,testing=True); servers.append(serve(restored)); restored_base=servers[-1][2]
                account(browser,restored_base,'researcher')
                assert browser.request.get(restored_base+'/health').json()['schema']==23
                for rid in pairs['own']+pairs['editor']:
                    assert browser.request.get(restored_base+'/api/records/'+rid).json()['body_html']=='<p>原有作者正文</p>'
                assert browser.request.get(restored_base+'/api/ingestion').status==403
                source_ids=[r['value'] for r in results if r.get('case')=='source']
                for sid in source_ids:
                    detail=browser.request.get(restored_base+'/api/sources/'+sid).json()
                    assert detail['status']=='verified' and detail['scope_status']=='candidate'
                    assert not detail['automatic_collection']['enabled']
                    assert len(browser.request.get(restored_base+'/api/history/source/'+sid).json()['items'])>=3
                page.goto(restored_base+'/#library?feed=all')
                personal(page,restored_base,pairs,evidence,'restored',merge=True)
                legacy(page,restored_base)
                account(browser,restored_base,'admin')
                page.reload()
                assert browser.request.get(restored_base+'/api/records/'+pairs['own'][0]).json()['can_edit'] is False
                assert browser.request.get(restored_base+'/api/admin/ai').json()['attempts']==[]
                page.goto(restored_base+'/#maintenance-sources?status=all')
                expect(page.get_by_role('heading',name='来源维护',exact=True)).to_be_visible()
                results.append({'restored_schema':23,'source_ids':source_ids,'personal_merge':True})
            assert not errors, errors
            browser.close()
    finally:
        for server,thread,_ in servers:
            server.shutdown(); thread.join(); server.server_close()
        (evidence/'results.json').write_text(json.dumps({'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False),flush=True)
    assert all(item.get('passed',True) for item in results), 'Review regressions reproduced'


if __name__=='__main__':
    main()
