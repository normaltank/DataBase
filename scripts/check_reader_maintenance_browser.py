"""Synthetic public HTTP and real Chromium checks for #75; never production data."""
import argparse
import base64
import json
import logging
import os
import struct
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from platform_app.web import create_app
from platform_app.maintenance import create_backup, restore_backup
from scripts.check_topic_finals_browser import serve
from scripts.check_collaboration_library_browser import login
from scripts.check_collaboration_browser import no_overflow


def nav(page, label):
    expect(page.get_by_role('button',name='退出登录',exact=True)).to_be_visible()
    button=page.get_by_role('button',name='打开导航',exact=True)
    if button.is_visible():
        button.click()
    page.get_by_role('navigation',name='主导航',exact=True).get_by_role('button',name=label,exact=True).click()


def call(context, base, path, data=None, method='POST', expected=200):
    request=getattr(context,'request',context)
    csrf = request.get(base+'/api/session').json()['csrf']
    response = request.fetch(base+path, method=method, data=data, headers={'X-CSRF-Token': csrf})
    assert response.status == expected, (path, response.status, response.text())
    return response.json()


def account(context, base, name):
    return call(context, base, '/api/login', {'username': name, 'password': 'LocalDemo2026!'})


def check_business(page,base,admin):
    q=next(x for x in admin.get(base+'/api/collaboration/qualifications').json()['items'] if x['id']=='researcher')
    call(admin,base,'/api/collaboration/qualifications/researcher',{'version':q['version'],'enabled':True},method='PUT')
    page.goto(base+'/#collaboration')
    page.get_by_role('button',name='开启一期主题',exact=True).click()
    page.get_by_label('本期主题 *',exact=True).fill('研究端业务负责人合成主题')
    page.get_by_role('button',name='保存本期信息',exact=True).click()
    expect(page.get_by_role('heading',name='研究端业务负责人合成主题',exact=True)).to_be_visible()
    expect(page.get_by_role('button',name='维护本期信息',exact=True)).to_be_visible()
    expect(page.get_by_role('button',name='记录会议决定',exact=True)).to_be_visible()
    tid=page.url.split('id=')[1]
    assert admin.get(base+'/api/collaboration/topics/'+tid).json()['can_manage'] is False
    q=next(x for x in admin.get(base+'/api/collaboration/qualifications').json()['items'] if x['id']=='researcher')
    call(admin,base,'/api/collaboration/qualifications/researcher',{'version':q['version'],'enabled':False},method='PUT')
    page.reload()
    expect(page.get_by_role('button',name='维护本期信息',exact=True)).to_have_count(0)
    expect(page.get_by_role('button',name='记录会议决定',exact=True)).to_have_count(0)
    note=call(page.context,base,'/api/records',{'kind':'research_note','title':'旧研究笔记合成回归','body_html':'<p>共同编辑的旧笔记</p>','visibility':'shared','sharing_confirmed':True},expected=201)['id']
    report=call(page.context,base,'/api/records',{'kind':'compilation','title':'旧个人报告合成回归','body_html':'<p>仅作者授权正文</p>','visibility':'shared','sharing_confirmed':True},expected=201)['id']
    assert admin.get(base+'/api/records/'+report).json()['can_edit'] is False
    return {'topic':tid,'note':note,'report':report}


def check_source(page, base, suffix, evidence):
    nav(page, '档案')
    expect(page.get_by_role('button', name='整理重复', exact=True)).to_have_count(0)
    page.get_by_role('button', name='提供采集来源', exact=True).click()
    expect(page.get_by_role('dialog', name='提供采集来源', exact=True)).to_be_visible()
    for label in ('机构国家依据', '主办关系依据', '来源介绍', 'ISSN', '收录范围'):
        expect(page.get_by_role('dialog').get_by_label(label, exact=True)).to_have_count(0)
    name='合成推荐智库 '+suffix
    website='https://example.org/'+suffix+'/'+'long-path-'*35
    page.get_by_label('来源名称 *', exact=True).fill(name)
    page.get_by_role('dialog').get_by_label('来源类型', exact=True).select_option('think_tank')
    page.get_by_text('补充国家与推荐理由（可选）',exact=True).click()
    page.get_by_label('推荐说明（可选）', exact=True).fill('推荐公开栏目，缺项留空。')
    # Validation and a real HTTP save failure preserve the same editor.
    page.get_by_role('button', name='保存候选来源', exact=True).click()
    expect(page.get_by_role('alert')).to_contain_text('请提供')
    expect(page.get_by_label('来源名称 *', exact=True)).to_have_value(name)
    page.get_by_label('官方网站', exact=True).fill(website)
    page.route('**/api/sources', lambda route: route.fulfill(status=503, content_type='application/json', body='{"error":"合成保存暂不可用"}') if route.request.method=='POST' else route.continue_())
    page.get_by_role('button', name='保存候选来源', exact=True).click()
    expect(page.get_by_role('alert')).to_contain_text('合成保存暂不可用')
    expect(page.get_by_label('官方网站', exact=True)).to_have_value(website)
    page.unroute('**/api/sources')
    page.get_by_role('button', name='关闭并保留草稿', exact=True).click()
    page.get_by_role('button', name='提供采集来源', exact=True).click()
    page.get_by_role('button', name='恢复草稿', exact=True).click()
    expect(page.get_by_role('dialog').get_by_label('来源类型', exact=True)).to_have_value('think_tank')
    expect(page.get_by_label('官方网站', exact=True)).to_have_value(website)
    expect(page.get_by_label('机构国家依据', exact=True)).to_have_count(0)
    no_overflow(page)
    expect(page.locator('#toast')).not_to_have_class('show')
    page.screenshot(path=str(evidence/('contribution-form-'+suffix+'.png')), full_page=False, scale='css')
    page.get_by_role('button', name='保存候选来源', exact=True).focus()
    page.keyboard.press('Enter')
    expect(page.get_by_role('heading', name=name, exact=True)).to_be_visible()
    expect(page.get_by_text('尚未接入持续采集', exact=True)).to_be_visible()
    no_overflow(page)
    metrics=page.evaluate('({css_width:innerWidth,css_height:innerHeight,dpr:devicePixelRatio,document_scroll_width:document.documentElement.scrollWidth,document_client_width:document.documentElement.clientWidth,body_scroll_width:document.body.scrollWidth})')
    # Chromium full-page capture at browser zoom can clip the physical right half.
    # At 200% retain an unmodified viewport screenshot instead.
    expect(page.locator('#toast')).not_to_have_class('show')
    page.screenshot(path=str(evidence/('source-'+suffix+'.png')), full_page=not suffix.endswith('-2'), scale='css')
    if suffix.endswith('-2'):
        page.screenshot(path=str(evidence/'zoom-viewport.png'), full_page=False, scale='css')
        screenshot_session=page.context.new_cdp_session(page)
        physical=screenshot_session.send('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
        (evidence/'zoom-physical.png').write_bytes(base64.b64decode(physical['data']))
        screenshot_session.detach()
    sid=page.url.split('id=')[1].split('&')[0]
    detail=page.request.get(base+'/api/sources/'+sid).json()
    assert (detail['kind'], detail['institution_types'], detail['scope_status'], detail['status']) == ('think_tank', ['think_tank'], 'candidate', 'pending')
    assert detail['website']==website and detail['country']==''
    assert detail['automatic_collection']=={'supported': False, 'enabled': False}
    assert page.request.get(base+'/api/history/source/'+sid).json()['items'][0]['action']=='提交来源'
    # Name duplicate supplies an existing archive destination without discarding input.
    nav(page, '档案')
    page.get_by_role('button', name='提供采集来源', exact=True).click()
    page.get_by_label('来源名称 *', exact=True).fill(name)
    page.get_by_label('官方网站', exact=True).fill('https://example.org/different-'+suffix)
    page.get_by_role('button', name='保存候选来源', exact=True).click()
    expect(page.get_by_role('alert')).to_contain_text('已登记')
    expect(page.get_by_label('来源名称 *', exact=True)).to_have_value(name)
    expect(page.get_by_role('dialog').get_by_role('link', name=name, exact=True)).to_have_attribute('href', '#sources?id='+sid)
    page.get_by_role('button', name='保留草稿并查看已有来源', exact=True).click()
    expect(page.get_by_role('heading',name=name,exact=True)).to_be_visible()
    nav(page,'档案')
    page.get_by_role('button',name='提供采集来源',exact=True).click()
    page.get_by_role('button',name='恢复草稿',exact=True).click()
    expect(page.get_by_label('来源名称 *',exact=True)).to_have_value(name)
    expect(page.get_by_label('官方网站',exact=True)).to_have_value('https://example.org/different-'+suffix)
    page.get_by_role('button',name='关闭并保留草稿',exact=True).click()
    # A separate journal contribution does not manufacture an institution or ISSN.
    page.get_by_role('button', name='提供采集来源', exact=True).click()
    page.get_by_role('button', name='舍弃这份草稿', exact=True).click()
    journal='合成推荐期刊 '+suffix
    page.get_by_label('来源名称 *', exact=True).fill(journal)
    page.get_by_role('dialog').get_by_label('来源类型', exact=True).select_option('journal')
    page.get_by_label('资料目录网址', exact=True).fill('https://example.org/issues/'+suffix)
    page.get_by_text('补充国家与推荐理由（可选）',exact=True).click()
    page.get_by_label('国家线索（可选）', exact=True).fill('线索待确认')
    page.get_by_role('button', name='保存候选来源', exact=True).click()
    expect(page.get_by_role('heading', name=journal, exact=True)).to_be_visible()
    jid=page.url.split('id=')[1].split('&')[0]
    saved=page.request.get(base+'/api/sources/'+jid).json()
    assert saved['host_id']==saved['issn']==saved['website']=='' and saved['national_status']=='pending'
    return sid, jid, metrics


def check_interfaces(page, base, download_dir=None):
    denied=[]
    page.on('request', lambda req: denied.append(req.url) if any(part in req.url for part in ('/api/admin/', '/api/ingestion', '/api/members', '/api/collaboration/qualifications')) else None)
    for route in ('system', 'review', 'maintenance-sources', 'maintenance-ingestion', 'maintenance-members', 'sources?group=maintenance'):
        page.goto(base+'/#'+route)
        expect(page.get_by_role('heading', name='此入口供资料管理员使用', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='维护界面', exact=True)).to_have_count(0)
    assert denied==[], denied
    page.get_by_role('button', name='打开我的', exact=True).click()
    expect(page.get_by_role('heading', name='个人账号与导出', exact=True)).to_be_visible()
    page.get_by_role('button', name='修改我的密码', exact=True).click()
    expect(page.get_by_role('dialog', name='修改我的密码', exact=True)).to_be_visible()
    page.keyboard.press('Escape')
    with page.expect_download() as download:
        page.get_by_role('button', name='导出可见内容', exact=True).click()
    assert download.value.failure() is None
    downloaded=Path(download.value.path()) if download_dir is None else download_dir/download.value.suggested_filename
    assert downloaded.stat().st_size > 0
    no_overflow(page)


def check_admin(page, base, name, evidence, suffix):
    page.get_by_role('button', name='退出登录', exact=True).click()
    page.get_by_role('button', name='资料管理员', exact=True).click()
    nav(page, '编译协作')
    expect(page.get_by_role('heading', name='编译协作', exact=True)).to_be_visible()
    expect(page.get_by_role('button', name='负责人资格', exact=True)).to_have_count(0)
    expect(page.get_by_role('button', name='维护查阅', exact=True)).to_have_count(0)
    sid=next(s['id'] for s in page.request.get(base+'/api/sources').json()['items'] if s['name']==name)
    page.goto(base+'/#sources?id='+sid)
    expect(page.get_by_role('heading',name=name,exact=True)).to_be_visible()
    expect(page.get_by_role('button',name='编辑来源',exact=True)).to_be_visible()
    expect(page.get_by_role('button',name='标记已核对',exact=True)).to_have_count(0)
    expect(page.get_by_role('button',name='整理重复来源',exact=True)).to_have_count(0)
    page.goto(base+'/#library?feed=all&q=旧研究笔记合成回归')
    page.get_by_role('button',name='旧研究笔记合成回归',exact=True).click()
    page.get_by_text('整理、编辑与核对',exact=True).click()
    expect(page.get_by_role('button',name='编辑内容',exact=True)).to_be_visible()
    expect(page.get_by_role('button',name='标记已核对',exact=True)).to_have_count(0)
    page.keyboard.press('Escape')
    nav(page, '维护界面')
    expect(page.get_by_role('heading', name='维护总览', exact=True)).to_be_visible()
    nav(page, '来源维护')
    no_overflow(page)
    expect(page.locator('#toast')).not_to_have_class('show')
    page.screenshot(path=str(evidence/('maintenance-pending-'+suffix+'.png')),full_page=False,scale='css')
    page.get_by_label('来源关键词', exact=True).fill(name)
    page.get_by_role('button', name='查找来源', exact=True).click()
    page.get_by_role('link', name=name, exact=True).click()
    expect(page.get_by_role('heading', name=name, exact=True)).to_be_visible()
    page.get_by_text('历史与维护', exact=True).click()
    page.get_by_role('button', name='标记已核对', exact=True).click()
    page.get_by_role('dialog').get_by_role('combobox').select_option('metadata_only')
    page.get_by_role('dialog').get_by_role('textbox').fill('仅核对合成来源登记，未接入自动采集。')
    page.get_by_role('button', name='记录核对', exact=True).click()
    expect(page.get_by_text('当前版本 2 · 已核对。', exact=False).first).to_be_visible()
    assert '#maintenance-sources?' in page.url
    nav(page,'来源维护')
    page.get_by_label('来源关键词',exact=True).fill('合成不存在的来源')
    page.get_by_role('button',name='查找来源',exact=True).click()
    expect(page.get_by_role('heading',name='暂无匹配来源',exact=True)).to_be_visible()
    no_overflow(page)
    page.get_by_label('来源关键词',exact=True).fill(name)
    page.get_by_role('combobox').select_option('all')
    page.get_by_role('button',name='查找来源',exact=True).click()
    expect(page.get_by_role('link',name=name,exact=True)).to_be_visible()
    nav(page, '自动采集')
    expect(page.get_by_role('heading', name='公开来源自动采集', exact=True)).to_be_visible()
    nav(page, '中文处理与费用')
    expect(page.get_by_role('heading', name='AI 费用', exact=True)).to_be_visible()
    nav(page, '账号与负责人资格')
    page.get_by_role('button', name='负责人资格', exact=True).click()
    expect(page.get_by_role('dialog', name='负责人资格登记', exact=True)).to_be_visible()
    page.keyboard.press('Escape')
    nav(page, '完整备份')
    expect(page.get_by_role('button', name='下载完整备份', exact=True)).to_be_visible()
    no_overflow(page)
    nav(page, '返回研究界面')
    expect(page.get_by_role('heading', name='编译协作', exact=True)).to_be_visible()
    # Same tab changes account while holding a former maintenance address.
    page.goto(base+'/#maintenance-sources')
    expect(page.get_by_role('heading', name='来源维护', exact=True)).to_be_visible()
    page.get_by_role('button', name='退出登录', exact=True).click()
    page.get_by_role('button', name='协作同事', exact=True).click()
    expect(page.get_by_role('heading', name='此入口供资料管理员使用', exact=True)).to_be_visible()
    expect(page.get_by_role('button', name='维护界面', exact=True)).to_have_count(0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--red', action='store_true')
    args = parser.parse_args()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    evidence = Path(tempfile.mkdtemp(prefix='database-reader-maintenance-75-'))
    (Path(tempfile.gettempdir()) / 'database-reader-maintenance-75-latest.txt').write_text(str(evidence), encoding='utf-8')
    print(json.dumps({'evidence': str(evidence)}), flush=True)
    app = create_app(evidence / 'data', testing=True)
    server, thread, base = serve(app)
    restored_server = None
    try:
        with sync_playwright() as p:
            extension=evidence/'zoom-extension';extension.mkdir()
            (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Synthetic actual zoom','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}),encoding='utf-8')
            (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});',encoding='utf-8')
            browser = p.chromium.launch_persistent_context(str(evidence/'profile'), executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None, headless=False, ignore_default_args=['--disable-extensions'], args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}'], viewport={'width':1366,'height':900}, accept_downloads=True)
            worker=browser.service_workers[0] if browser.service_workers else browser.wait_for_event('serviceworker')
            page = browser.pages[0]
            errors=[]
            def page_error(error):
                errors.append(str(error));print('BROWSER_ERROR: '+str(error),flush=True)
            page.on('pageerror',page_error)
            login(page, base, 'researcher')
            if args.red:
                # Observe both gaps before changing application code.
                old_menu = page.get_by_role('button', name='管理', exact=True).count()
                nav(page, '档案')
                page.get_by_role('button', name='提交来源', exact=True).click()
                heavy_fields = page.get_by_label('机构国家依据', exact=True).count()
                page.screenshot(path=str(evidence / 'before-heavy-form.png'), full_page=True)
                result = {'researcher_management_menu': old_menu, 'country_evidence_fields': heavy_fields}
                (evidence / 'red.json').write_text(json.dumps(result), encoding='utf-8')
                print(json.dumps(result), flush=True)
                assert old_menu == 0 and heavy_fields == 0, 'Researcher sees management navigation and the heavy source form'
            else:
                results=[]
                admin=p.request.new_context(base_url=base)
                account(admin,base,'admin')
                work=check_business(page,base,admin)
                for width,zoom in ((1366,1),(390,1),(1366,2)):
                    page.set_viewport_size({'width':width,'height':900})
                    worker.evaluate("async ({url,zoom})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,zoom)}",{'url':base,'zoom':zoom})
                    assert worker.evaluate("async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));return chrome.tabs.getZoom(t.id)}",base)==zoom
                    if results:
                        page.get_by_role('button',name='退出登录',exact=True).click()
                        page.get_by_role('button',name='研究员',exact=True).click()
                    check_interfaces(page,base)
                    sid,jid,dimensions=check_source(page,base,f'{width}-{zoom}',evidence)
                    check_admin(page,base,'合成推荐智库 '+f'{width}-{zoom}',evidence,f'{width}-{zoom}')
                    pixels=struct.unpack('>II',(evidence/f'source-{width}-{zoom}.png').read_bytes()[16:24])
                    results.append({'width':width,'actual_zoom':zoom,'zoom_method':'chrome.tabs.setZoom verified by chrome.tabs.getZoom','browser_metrics':dimensions,'screenshot_pixels':pixels,'institution':sid,'journal':jid})
                assert admin.get(base+'/api/admin/ai').json()['attempts']==[]
                backup=create_backup(evidence/'data')
                target=evidence/'new-directory-restored'
                assert not target.exists()
                restore_backup(backup,target)
                restored=create_app(target,testing=True)
                restored_server,restored_thread,restored_base=serve(restored)
                restored_context=p.request.new_context(base_url=restored_base)
                account(restored_context,restored_base,'researcher')
                assert restored_context.get(restored_base+'/health').json()['schema']==23
                assert restored_context.get(restored_base+'/api/records/'+work['note']).json()['body_html']=='<p>共同编辑的旧笔记</p>'
                assert restored_context.get(restored_base+'/api/collaboration/topics/'+work['topic']).json()['can_manage'] is False
                assert restored_context.get(restored_base+'/api/ingestion').status==403
                restored_admin=p.request.new_context(base_url=restored_base)
                account(restored_admin,restored_base,'admin')
                assert restored_admin.get(restored_base+'/api/records/'+work['report']).json()['can_edit'] is False
                assert restored_admin.get(restored_base+'/api/admin/ai').json()['attempts']==[]
                restored_admin.dispose()
                for item in results:
                    for key in ('institution','journal'):
                        detail=restored_context.get(restored_base+'/api/sources/'+item[key]).json()
                        assert detail['scope_status']=='candidate' and not detail['automatic_collection']['enabled']
                        assert restored_context.get(restored_base+'/api/history/source/'+item[key]).json()['items'][-1]['action']=='提交来源'
                browser.clear_cookies()
                login(page,restored_base,'researcher')
                page.goto(restored_base+'/#sources?id='+results[0]['journal'])
                expect(page.get_by_role('heading',name='合成推荐期刊 1366-1',exact=True)).to_be_visible()
                expect(page.get_by_text('尚未接入持续采集',exact=True)).to_be_visible()
                no_overflow(page)
                assert not errors,errors
                (evidence/'results.json').write_text(json.dumps({'scenarios':results,'errors':errors,'restored_schema':23,'work':work},ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({'passed':results,'restored_schema':23}),flush=True)
                restored_context.dispose();admin.dispose()
            browser.close()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
        if restored_server:
            restored_server.shutdown();restored_thread.join();restored_server.server_close()


if __name__ == '__main__':
    main()
