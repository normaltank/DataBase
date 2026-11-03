"""Fresh synthetic HTTP/browser acceptance for #92; no collectors or real AI calls.

Run: python -B scripts/check_country_filters_browser.py --evidence-dir <new directory>
Requires Playwright and its Chromium for chrome.tabs verified 200% zoom.
"""
import argparse
import json
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))
from platform_app.web import create_app
from portable.demo_seed import seed, login, call


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    args = parser.parse_args()
    root = args.evidence_dir.resolve()
    if root.exists():
        parser.error('Use a new evidence directory; existing files are never reset.')
    root.mkdir(parents=True)
    app = create_app(root/'data', testing=True)
    seed(app)
    client=login(app,'researcher')
    sources=[]
    for i,value in enumerate(['Latvia','拉脱维亚','Germany']):
        sources.append(call(client,'/api/sources',{'name':f'合成92机构 {i}','kind':'institution','institution_types':['think_tank'], 'country':value,'country_evidence':'完全合成所在地证据'})['id'])
    for i,value in enumerate(['Latvia','拉脱维亚','LATVIA','Latvia|拉脱维亚','','Germany']):
        call(client,'/api/records',{'title':f'合成92筛选样本 {i}','kind':'report','countries':value,'source_id':sources[i%3],'abstract':'完全合成资料，只用于筛选体验。'})
    call(client,'/api/sources',{'name':'合成92国际期刊','kind':'journal','host_id':sources[0],'host_evidence':'完全合成主办证据','publisher_id':sources[2],'international_status':'yes','international_evidence':'完全合成国际定位'})
    person=call(client,'/api/people',{'name':'合成92作者','change_note':'完全合成人物主页'})['id']
    call(client,f'/api/people/{person}/employments',{'version':0,'change_note':'完全合成历史履历','items':[{'institution_id':sources[0],'role':'研究员','start_date':'1990','end_date':'2000','evidence':'完全合成历史履历'}]},method='PUT')
    record=call(client,'/api/records',{'title':'合成92作者日本作品','kind':'report','countries':'Japan'})['id']
    call(client,f'/api/records/{record}/bylines',{'version':0,'record_version':1,'change_note':'完全合成署名','items':[{'raw_name':'合成92作者','target_type':'person','target_id':person,'status':'confirmed','evidence':'完全合成人物主页'}]},method='PUT')
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}/'
    try:
        extension=root/'zoom-extension'
        extension.mkdir(exist_ok=True)
        (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Country acceptance actual zoom','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
        (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
        with sync_playwright() as p:
            executable=p.chromium.executable_path
            assert Path(executable).exists(),executable
            context=p.chromium.launch_persistent_context(str(root/'ui-profile'),executable_path=executable,headless=False,
                ignore_default_args=['--disable-extensions'],args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}'],
                viewport={'width':1440,'height':1000},accept_downloads=True)
            worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page=context.pages[0]
            page.set_default_timeout(15000)
            errors=[];results=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(base)
            page.get_by_role('button',name='研究员',exact=True).click()
            for width,zoom in [(1440,1),(1366,1),(390,1),(320,1),(1366,2)]:
                page.set_viewport_size({'width':width,'height':1000 if width>400 else 844})
                worker.evaluate("async ({base,zoom})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(t.id,zoom)}",{'base':base,'zoom':zoom})
                actual=worker.evaluate("async base=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));return chrome.tabs.getZoom(t.id)}",base)
                assert actual==zoom
                tag=f'{width}-{zoom}'
                page.goto(base+'#library?feed=all&q=合成92筛选')
                expect(page.locator('.library-row')).to_have_count(6)
                assert '已选' not in page.locator('.reading-more>summary').inner_text()
                assert '时间类型' not in page.locator('.reading-current').inner_text()
                facet=page.locator('.reading-facet').first
                facet.locator('summary').focus();page.keyboard.press('Enter')
                expect(facet).to_have_attribute('open','')
                page.locator('input[name=country][value=LV]').check()
                page.get_by_role('button',name='查找',exact=True).click()
                expect(page.locator('.library-row')).to_have_count(4)
                assert 'date_field=' not in page.url
                assert '已选' not in page.locator('.reading-more>summary').inner_text()
                expect(page.locator('.reading-facet summary').first).to_contain_text('拉脱维亚')
                page.locator('.reading-facet summary').first.click()
                expect(page.locator('input[name=country][value=DE]')).to_be_visible()
                page.locator('input[name=country][value=DE]').check()
                page.get_by_role('button',name='查找',exact=True).click()
                expect(page.locator('.library-row')).to_have_count(5)
                page.locator('.reading-facet summary').first.click()
                page.locator('input[name=country][value=LV]').uncheck()
                page.keyboard.press('Escape')
                expect(page.locator('.reading-facet summary').first).to_be_focused()
                page.get_by_role('button',name='查找',exact=True).click()
                expect(page.locator('.library-row')).to_have_count(1)
                reading_url=page.url
                page.locator('.record-title button').first.click()
                expect(page.locator('.library-reader')).to_be_visible()
                page.get_by_role('button',name='返回列表',exact=True).click()
                expect(page.locator('.library-row')).to_have_count(1)
                assert page.url==reading_url
                page.locator('.reading-more>summary').click()
                source=page.locator('.reading-facet').filter(has=page.locator('input[name=source_country]'))
                source.locator('summary').click()
                page.locator('input[name=source_country][value=DE]').check()
                page.get_by_role('button',name='应用筛选',exact=True).click()
                expect(page.locator('.library-row')).to_have_count(1)
                expect(page.locator('.reading-more>summary')).to_contain_text('已选 1 项')
                page.screenshot(path=str(root/f'library-{tag}.png'),full_page=True)
                page.goto(base+'#library?feed=all&q=合成92筛选&country=NeverCountry')
                expect(page.locator('.library-row')).to_have_count(0)
                page.locator('.reading-facet summary').first.click()
                expect(page.locator('input[name=country][value=nevercountry]')).to_be_checked()
                page.locator('input[name=country][value=nevercountry]').uncheck()
                page.get_by_role('button',name='查找',exact=True).click()
                expect(page.locator('.library-row')).to_have_count(6)
                page.get_by_role('button',name='重置筛选',exact=True).first.click()
                expect(page.get_by_role('textbox',name='资料关键词')).to_have_value('')
                assert 'feed=all' in page.url
                assert page.locator('.reading-current').count()==0
                page.goto(base+'#sources?group=institution&q=合成92')
                expect(page.get_by_label('机构国家',exact=True)).to_be_visible()
                page.get_by_label('机构类型',exact=True).select_option('think_tank')
                page.get_by_label('机构国家',exact=True).select_option('LV')
                expect(page.get_by_label('机构类型',exact=True)).to_have_value('think_tank')
                page.get_by_role('button',name='应用筛选',exact=True).click()
                expect(page.locator('.workbench-source-row')).to_have_count(2)
                sources_url=page.url
                page.locator('.workbench-source-row h2 a').first.click()
                expect(page.locator('.source-page')).to_be_visible()
                page.get_by_role('link',name='← 返回来源目录',exact=True).click()
                expect(page.locator('.workbench-source-row')).to_have_count(2)
                assert page.url==sources_url
                page.get_by_role('button',name='期刊',exact=True).click()
                expect(page.get_by_label('主办国别',exact=True)).to_have_value('LV')
                assert 'institution_type=' not in page.url
                page.get_by_label('国际定位',exact=True).select_option('yes')
                page.get_by_role('button',name='应用筛选',exact=True).click()
                expect(page.locator('.workbench-source-row')).to_have_count(1)
                page.screenshot(path=str(root/f'sources-{tag}.png'),full_page=True)
                page.goto(base+'#people?q=合成92')
                expect(page.locator('.workbench-person-row')).to_have_count(1)
                page.locator('.reading-facet summary').first.click()
                page.locator('input[name=employment_country][value=LV]').check()
                page.locator('.reading-facet summary').nth(1).click()
                page.locator('input[name=subject_country][value=JP]').check()
                page.get_by_role('button',name='查找',exact=True).click()
                expect(page.locator('.workbench-person-row')).to_have_count(1)
                people_url=page.url
                page.locator('.workbench-person-row h2 a').click()
                expect(page.locator('.person-page')).to_be_visible()
                page.get_by_role('link',name='← 返回作者目录',exact=True).click()
                expect(page.locator('.workbench-person-row')).to_have_count(1)
                assert page.url==people_url
                page.screenshot(path=str(root/f'people-{tag}.png'),full_page=True)
                layout=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
                assert layout['scroll']<=layout['width'],layout
                results.append({'width':width,'actual_zoom':actual,'layout':layout,'keyboard_expand_escape':True,'select_add_remove':True,
                                'zero_result_clear':True,'reading_return':True,'source_type_country_international':True,'people_two_dimensions_return':True})
            assert errors==[],errors
            (root/'ui-verification.json').write_text(json.dumps({'browser':executable,'results':results,'console_errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(results,ensure_ascii=False))
            context.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


if __name__ == '__main__':
    main()
