"""Isolated synthetic acceptance for #123; no real data, workers or external calls.

python scripts/check_material_discovery_browser.py --evidence-dir <new directory>
"""
import argparse
import json
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler

REPOSITORY=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPOSITORY))
from platform_app.web import create_app


class QuietHandler(WSGIRequestHandler):
    def log_request(self,*args,**kwargs):
        pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8894)
    args=parser.parse_args()
    root=args.evidence_dir.resolve()
    if root.exists():
        parser.error('Use a new evidence directory; existing state is never reset.')
    root.mkdir(parents=True)
    app=create_app(root/'data',testing=True,embedded_worker=False)
    client=app.test_client()

    def call(path,values,method='POST'):
        token=client.get('/api/session').json['csrf']
        response=client.open(path,method=method,json=values,headers={'X-CSRF-Token':token})
        assert response.status_code in [200,201],response.json
        return response.json

    call('/api/login',{'username':'researcher','password':'LocalDemo2026!'})
    source=call('/api/sources',{'name':'合成发现来源','kind':'institution'})['id']
    for i in range(26):
        country='Latvia|拉脱维亚'+('|Germany' if i<10 else '') if i<23 else ['Japan','','Yugoslavia|LostTerritory'][i-23]
        published='2020' if i<12 else '2021-02' if i<23 else '2022-03-04' if i==23 else ''
        call('/api/records',{'title':f'合成发现资料 {i:02}','kind':'report','source_id':source,
             'countries':country,'published_on':published,'abstract':'完全合成验收材料，非实际研究资料。'})
    call('/api/records',{'title':'合成发现隐藏资料','kind':'report','source_id':source,'countries':'Germany','visibility':'restricted'})
    server=make_server('127.0.0.1',args.port,app,threaded=True,request_handler=QuietHandler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}/'
    results=[]
    try:
        extension=root/'zoom-extension';extension.mkdir()
        (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Discovery acceptance zoom','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
        (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
        with sync_playwright() as p:
            context=p.chromium.launch_persistent_context(str(root/'profile'),executable_path=p.chromium.executable_path,
                headless=False,ignore_default_args=['--disable-extensions'],args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}'],
                viewport={'width':1366,'height':900})
            worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page=context.pages[0];page.set_default_timeout(15000)
            errors=[];requests=[];csp=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('console',lambda message:csp.append(message.text) if 'Content Security Policy' in message.text or 'style-src' in message.text else None)
            page.on('request',lambda request:requests.append(request.url))
            page.goto(base)
            page.get_by_role('button',name='协作同事',exact=True).click()
            url=base+'#library?feed=all&q=合成发现&source='+source+'&page=2'
            page.goto(url)
            expect(page.locator('.library-row')).to_have_count(6)
            panel=page.locator('.material-discovery')
            expect(panel).not_to_have_attribute('open','')
            assert not any('/api/material-discovery' in request for request in requests)
            page.screenshot(path=str(root/'folded-1366.png'),full_page=True)
            panel.locator('summary').focus();page.keyboard.press('Enter')
            expect(panel.locator('.material-scope')).to_contain_text('26 条')
            expect(panel.locator('.material-country-list [data-material-country=LV]')).to_contain_text('23')
            expect(panel.locator('.material-map')).to_have_attribute('viewBox','385 38 230 125')
            expect(panel.get_by_role('button',name='日本：1 条，筛选研究对象国',exact=True)).to_have_count(0)
            short=panel.locator('[data-material-year="2022"] rect').bounding_box()['width']
            long=panel.locator('[data-material-year="2020"] rect').bounding_box()['width']
            assert 0.08<short/long<0.09,{'one_article_bar':short,'twelve_article_bar':long}
            page.screenshot(path=str(root/'europe-1366.png'),full_page=True)
            panel.locator('path[data-material-country=LV]').click()
            expect(page.locator('.material-scope')).to_contain_text('23 条')
            query=parse_qs(urlsplit(page.url).fragment.split('?',1)[1])
            assert query['source']==[source] and query['q']==['合成发现'] and query['country']==['LV'] and 'page' not in query
            expect(page.locator('.material-country-list [data-material-country=LV]')).to_be_focused()
            page.get_by_role('button',name='清除研究对象国条件',exact=True).click()
            expect(page.locator('.material-scope')).to_contain_text('26 条')
            page.locator('[data-material-view=world]').click()
            expect(page.locator('.material-map')).to_have_attribute('viewBox','0 0 900 450')
            expect(panel.get_by_role('button',name='日本：1 条，筛选研究对象国',exact=True)).to_have_count(1)
            page.screenshot(path=str(root/'world-1366.png'),full_page=True)
            page.locator('.material-country-list [data-material-country="historic:yugoslavia"]').click()
            expect(page.locator('.material-scope')).to_contain_text('1 条')
            page.get_by_role('button',name='清除研究对象国条件',exact=True).click()
            expect(page.locator('.material-scope')).to_contain_text('26 条')
            page.locator('[data-material-year="2020"]').click()
            expect(page.locator('.material-scope')).to_contain_text('12 条')
            expect(page.locator('.material-time')).to_contain_text('仅年份 12 条')
            assert 'from=2020-01-01' in page.url and 'to=2020-12-31' in page.url
            page.get_by_role('button',name='清除时间条件',exact=True).click()
            expect(page.locator('.material-scope')).to_contain_text('26 条')
            page.locator('[data-material-role]').select_option('collected')
            expect(page.locator('.material-time')).to_contain_text('精确到日 26 条')
            page.locator('.material-year').first.click()
            expect(page.locator('.material-scope')).to_contain_text('26 条')
            assert 'date_field=collected' in page.url
            page.get_by_role('button',name='清除时间条件',exact=True).click()
            expect(page.locator('.material-scope')).to_contain_text('26 条')
            page.locator('[data-material-role]').select_option('published')
            page.locator('[data-material-year=unknown]').click()
            expect(page.locator('.material-scope')).to_contain_text('2 条')
            assert 'date_unknown=1' in page.url and 'from=' not in page.url
            page.get_by_role('button',name='清除时间条件',exact=True).click()
            expect(page.locator('.material-scope')).to_contain_text('26 条')
            results.append('Country map/text, year/unknown and clear preserve source/query and clear page; keyboard focus restored')
            for width,zoom in [(1366,1),(390,1),(320,1),(1366,2)]:
                page.set_viewport_size({'width':width,'height':900 if width>400 else 844})
                worker.evaluate("async ({base,zoom})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(t.id,zoom)}",{'base':base,'zoom':zoom})
                actual=worker.evaluate("async base=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));return chrome.tabs.getZoom(t.id)}",base)
                assert actual==zoom
                page.locator('[data-material-view=europe]').click()
                expect(page.locator('.material-scope')).to_contain_text('26 条')
                overflow=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
                assert overflow['scroll']<=overflow['width']+1,overflow
                page.screenshot(path=str(root/f'europe-{width}-zoom-{zoom}.png'),full_page=True)
                page.screenshot(path=str(root/f'viewport-{width}-zoom-{zoom}.png'))
                page.locator('.material-discovery').screenshot(path=str(root/f'panel-{width}-zoom-{zoom}.png'))
                controls=page.locator('.material-discovery button,.material-discovery select').evaluate_all('(elements)=>elements.map(el=>({text:el.textContent,x:el.getBoundingClientRect().x,right:el.getBoundingClientRect().right,width:innerWidth}))')
                assert all(control['x']>=0 and control['right']<=control['width'] for control in controls),controls
                control=page.locator('.material-country-list [data-material-country=LV]')
                control.focus();page.keyboard.press('Enter')
                expect(page.locator('.material-scope')).to_contain_text('23 条')
                expect(page.locator('.material-country-list [data-material-country=LV]')).to_be_focused()
                page.get_by_role('button',name='清除研究对象国条件',exact=True).click()
                expect(page.locator('.material-scope')).to_contain_text('26 条')
                results.append({'viewport':width,'chrome_zoom':actual,'layout':overflow,'keyboard_country_filter':'pass'})
            page.locator('[data-material-role]').select_option('updated')
            expect(page.locator('.material-time')).to_contain_text('精确到日 26 条')
            page.locator('.material-year').first.click()
            expect(page.locator('.material-scope')).to_contain_text('26 条')
            assert 'date_field=updated' in page.url
            page.get_by_role('button',name='清除时间条件',exact=True).click()
            expect(page.locator('.material-scope')).to_contain_text('26 条')
            page.route('**/api/material-discovery?**',lambda route:route.fulfill(status=503,json={'error':'合成网络失败'}),times=1)
            page.locator('.material-discovery>summary').click()
            page.locator('.material-discovery>summary').click()
            expect(page.locator('.material-discovery [role=alert]')).to_contain_text('合成网络失败')
            page.get_by_role('button',name='重新读取分布').click()
            expect(page.locator('.material-scope')).to_contain_text('26 条')
            results.append('HTTP failure displayed with working retry')
            held=[]
            page.route('**/api/material-discovery?**',lambda route:held.append(route),times=1)
            page.locator('.material-discovery>summary').click()
            page.locator('.material-discovery>summary').click()
            expect(page.locator('[data-material-distribution]')).to_contain_text('正在读取')
            page.wait_for_timeout(100)
            page.evaluate("location.hash='#sources'")
            expect(page.locator('.material-discovery')).to_have_count(0)
            assert held
            held[0].fulfill(status=200,json={'total':999,'countries':[],'dates':{}})
            page.wait_for_timeout(200)
            expect(page.locator('.material-discovery')).to_have_count(0)
            results.append('Late response after route switch discarded')
            assert not errors,errors
            assert not csp,csp
            results.append({'bar_ratio_one_to_twelve':short/long,'csp_errors':csp})
            (root/'results.json').write_text(json.dumps({'checks':results,'page_errors':errors,'base':base},ensure_ascii=False,indent=2),encoding='utf-8')
            context.close()
    finally:
        server.shutdown();server.server_close()
    print(json.dumps({'evidence':str(root),'checks':results},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
