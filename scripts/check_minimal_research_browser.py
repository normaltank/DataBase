"""#146: public HTTP, real Chromium, synthetic data and a random isolated port.

Use --serve for an interactive preview (demo logins only; embedded worker off).
Every test action uses rendered UI or the application's public HTTP API.
"""
import argparse
import json
import math
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from platform_app.web import create_app

class Quiet(WSGIRequestHandler):
    def log_request(self,*args,**kwargs): pass

def pick_country(page,lon,lat):
    box=page.locator('[data-material-globe] canvas').bounding_box()
    lon,lat,view_lon,view_lat=map(math.radians,(lon,lat,22,45))
    point=[2.5*math.cos(lat)*math.sin(lon),2.5*math.sin(lat),2.5*math.cos(lat)*math.cos(lon)]
    dot=lambda a,b:sum(x*y for x,y in zip(a,b))
    right=[math.cos(view_lon),0,-math.sin(view_lon)]
    up=[-math.sin(view_lat)*math.sin(view_lon),math.cos(view_lat),-math.sin(view_lat)*math.cos(view_lon)]
    forward=[math.cos(view_lat)*math.sin(view_lon),math.sin(view_lat),math.cos(view_lat)*math.cos(view_lon)]
    scale=box['height']/2/math.tan(math.radians(20))/(8.6-dot(point,forward))
    page.mouse.click(box['x']+box['width']/2+dot(point,right)*scale,box['y']+box['height']/2-dot(point,up)*scale)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--serve',action='store_true')
    parser.add_argument('--case',choices=['all','saved'],default='all')
    args=parser.parse_args();out=args.evidence.resolve();out.mkdir(parents=True,exist_ok=False)
    app=create_app(out/'synthetic-data',testing=True,embedded_worker=False);client=app.test_client()
    def post(path,values,method='POST'):
        response=client.open(path,method=method,json=values,headers={'X-CSRF-Token':client.get('/api/session').json['csrf']})
        assert response.status_code in (200,201),response.json
        return response.json
    post('/api/login',{'username':'admin','password':'LocalDemo2026!'})
    source=post('/api/sources',{'name':'合成 · 区域政策研究所','kind':'institution','country':'Latvia'})['id']
    ids=[]
    for i in range(12):
        ids.append(post('/api/records',{'title':f'合成探索资料 {i:02} · 区域政策研究','kind':'report','source_id':source,'countries':'Latvia' if i%2==0 else 'Germany','published_on':str(2020+i%4),'body_html':'<h2>合成研究材料</h2>'+('<p>本段仅用于界面验证，原始材料与研究结论应分别记录。</p>'*50)})['id'])
    server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    result={'base':f'http://127.0.0.1:{server.server_port}','worker':False,'paid_calls':0,'checks':[]};errors=[]
    print(result['base']+'/#library?feed=all&q=合成探索',flush=True)
    try:
        if args.serve:
            print('Synthetic preview ready. Ctrl+C to stop.',flush=True)
            threading.Event().wait()
            return
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1440,'height':960},reduced_motion='reduce')
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(result['base']+'/#library?feed=all&q=合成探索')
            page.get_by_role('button',name='研究员',exact=True).click()
            panel=page.locator('.material-discovery');expect(panel.locator('canvas')).to_be_visible()
            token=page.request.get(result['base']+'/api/session').json()['csrf']
            saved=page.request.post(result['base']+'/api/saved-searches',data={'name':'合成 · 固定来源检索','conditions':{'feed':'all','q':'合成探索','source':source,'sort':'title'}},headers={'X-CSRF-Token':token}).json()
            page.goto(result['base']+'/#library?saved_search='+saved['id'])
            # This navigation changes source/sort and may replace the old shell.
            # Its visible canvas is not the saved-query canvas until the named
            # query has rendered; subsequent interactions must retain this one.
            expect(page.locator('.saved-search-bar strong')).to_have_text('检索：'+saved['name'])
            expect(panel.locator('[data-material-globe] canvas')).to_be_visible()
            saved_canvas=panel.locator('[data-material-globe] canvas').element_handle()
            panel.locator('.material-country-list [data-material-country=LV]').click()
            expect(page.locator('.library-row')).to_have_count(6)
            assert saved_canvas.evaluate('(e)=>e.isConnected'),'Saved-search country selection disconnected the canvas'
            selected_url=page.url
            assert parse_qs(urlsplit(page.url).fragment.split('?',1)[1])['source']==[source]
            panel.locator('[data-material-clear=country]').click();expect(page.locator('.library-row')).to_have_count(12)
            assert saved_canvas.evaluate('(e)=>e.isConnected')
            page.go_back();expect(panel.locator('.material-country-list [data-material-country=LV]')).to_have_attribute('aria-pressed','true')
            page.go_back();expect(page.locator('.library-row')).to_have_count(12)
            assert saved_canvas.evaluate('(e)=>e.isConnected'),'Returning to the saved URL disconnected the canvas'
            assert 'saved_search=' in page.url
            page.go_forward();expect(page.locator('.library-row')).to_have_count(6)
            page.locator('.library-row .title-button').first.click();expect(page.locator('.library-reader .detail-title')).to_be_visible()
            page.get_by_role('button',name='返回探索与结果',exact=True).click();assert saved_canvas.evaluate('(e)=>e.isConnected')
            assert page.url==selected_url
            result['checks'].append('saved-search resolution keeps source/sort/query, same canvas on select/clear/history/reader return')
            if args.case=='saved':
                browser.close();return
            page.goto(result['base']+'/#library?feed=all&q=合成探索');expect(panel.locator('[data-material-globe] canvas')).to_be_visible()
            result['layout']=page.evaluate('''()=>{const b=s=>document.querySelector(s).getBoundingClientRect();return {work:b('.material-workspace').width,explore:b('.material-discovery').width,canvas:b('[data-material-globe] canvas').width,canvasHeight:b('[data-material-globe] canvas').height}}''')
            page.screenshot(path=str(out/'desktop.png'))
            canvas=panel.locator('canvas').element_handle()
            page.evaluate('''()=>{window.countryContinuity={removed:0};const canvas=document.querySelector('[data-material-globe] canvas');new MutationObserver(()=>{if(!canvas.isConnected)window.countryContinuity.removed++}).observe(document.querySelector('#app'),{subtree:true,childList:true})}''')
            held=[]
            def hold(route): held.append(route)
            page.route('**/api/records?*country=LV*',hold)
            panel.locator('.material-country-list [data-material-country=LV]').click()
            expect(page.locator('[data-library-query-status]')).to_contain_text('正在更新')
            expect(page.locator('.library-row')).to_have_count(12)
            assert canvas.evaluate('(e)=>e.isConnected')
            # A second click is accepted while the first public HTTP response waits.
            panel.locator('.material-country-list [data-material-country=DE]').click()
            expect(page.locator('.library-row')).to_have_count(6)
            expect(panel.locator('.material-scope')).to_contain_text('6 条')
            expect(panel.locator('.material-country-list [data-material-country=DE]')).to_be_focused()
            assert held,'First country request was not intercepted'
            for route in held:route.fulfill(response=route.fetch())
            page.unroute('**/api/records?*country=LV*',hold)
            expect(page.locator('[data-library-query-status]')).to_have_text('')
            assert all(int(row.get_attribute('data-library-record') in ids[1::2]) for row in page.locator('.library-row').all())
            assert parse_qs(urlsplit(page.url).fragment.split('?',1)[1])['country']==['DE']
            result['canvas_connected']=canvas.evaluate('(e)=>e.isConnected');result['continuity']=page.evaluate('window.countryContinuity')
            assert result['canvas_connected'] and result['continuity']['removed']==0, result
            assert result['layout']['explore']/result['layout']['work']>=.5,result['layout']
            result['checks'].append('slow request keeps canvas and old rows; rapid LV→DE ignores late LV; URL/focus stay DE')
            page.go_back();expect(panel.locator('.material-country-list [data-material-country=LV]')).to_have_attribute('aria-pressed','true')
            page.go_forward();expect(panel.locator('.material-country-list [data-material-country=DE]')).to_have_attribute('aria-pressed','true')
            assert canvas.evaluate('(e)=>e.isConnected')
            result['checks'].append('browser back/forward reuse the same canvas')
            fail=lambda route:route.abort('failed')
            page.route('**/api/records?*country=LV*',fail)
            panel.locator('.material-country-list [data-material-country=LV]').click()
            expect(page.locator('[data-library-query-status]')).to_contain_text('无法更新')
            assert canvas.evaluate('(e)=>e.isConnected')
            expect(page.locator('.library-row')).to_have_count(6)
            page.unroute('**/api/records?*country=LV*',fail)
            page.get_by_role('button',name='重试当前查询',exact=True).click()
            expect(page.locator('[data-library-query-status]')).to_have_text('')
            result['checks'].append('failed query retains content and exposes retry for current URL')
            panel.locator('[data-material-scene=time]').click();expect(panel.locator('[data-material-timeline] canvas')).to_be_visible()
            panel.locator('[data-material-from]').fill('2019');panel.locator('[data-material-to]').fill('2025')
            panel.locator('[data-material-scene=country]').click();expect(panel.locator('[data-material-globe] canvas')).to_be_visible()
            panel.locator('.material-country-list [data-material-country=DE]').click()
            expect(panel.locator('.material-scope')).to_contain_text('6 条')
            expect(panel.locator('[data-material-from]')).to_have_value('2019');expect(panel.locator('[data-material-to]')).to_have_value('2025')
            panel.locator('[data-material-flat]').click();expect(panel.locator('.material-map')).to_be_visible()
            panel.locator('.material-country-list [data-material-country=LV]').click()
            expect(panel.locator('.material-scope')).to_contain_text('6 条')
            expect(panel.locator('.material-map')).to_be_visible();expect(panel.locator('[data-material-flat]')).to_have_attribute('aria-pressed','true')
            panel.locator('[data-material-flat]').click();expect(panel.locator('[data-material-globe] canvas')).to_be_visible()
            result['checks'].append('unapplied year draft, flat/text entry survive country changes')
            canvas=panel.locator('[data-material-globe] canvas').element_handle()
            row=page.locator('.library-row .title-button').first;row.click()
            expect(page.locator('.library-reader .detail-title')).to_be_visible()
            expect(panel).not_to_be_visible()
            result['reading_layout']=page.evaluate('''()=>{const b=s=>document.querySelector(s).getBoundingClientRect();return {work:b('.material-workspace').width,reader:b('.library-reader').width,list:b('.record-list').width}}''')
            assert result['reading_layout']['reader']/result['reading_layout']['work']>.65,result['reading_layout']
            page.screenshot(path=str(out/'reading-desktop.png'))
            page.get_by_role('button',name='返回探索与结果',exact=True).click();expect(panel).to_be_visible()
            assert canvas.evaluate('(e)=>e.isConnected')
            expect(panel.locator('[data-material-from]')).to_have_value('2019')
            panel.locator('[data-material-clear=country]').click();expect(page.locator('.library-row')).to_have_count(12)
            result['checks'].append('reading gives prose >65%; return restores same canvas, draft and query; clear restores all results')
            pick_country(page,24,57)
            expect(panel.locator('.material-country-list [data-material-country=LV]')).to_have_attribute('aria-pressed','true')
            pick_country(page,10,51)
            expect(panel.locator('.material-country-list [data-material-country=DE]')).to_have_attribute('aria-pressed','true')
            assert canvas.evaluate('(e)=>e.isConnected')
            panel.locator('[data-material-clear=country]').click();expect(page.locator('.library-row')).to_have_count(12)
            result['checks'].append('two real 3D raycast clicks after query/scene changes still drive LV→DE on the same canvas')
            panel.locator('[data-material-scene=time]').click();expect(panel.locator('[data-material-timeline] canvas')).to_be_visible()
            page.screenshot(path=str(out/'time-desktop.png'))
            panel.locator('[data-material-apply]').click();expect(page.locator('.reading-current')).to_contain_text('2019-01-01')
            panel.locator('[data-material-clear=time]').click();expect(page.locator('.reading-current')).not_to_contain_text('2019-01-01')
            panel.locator('[data-material-scene=country]').click()
            page.set_viewport_size({'width':1280,'height':720})
            expect(panel.locator('.material-country-list [data-material-country=LV]')).to_be_in_viewport()
            page.screenshot(path=str(out/'laptop-1280.png'))
            page.set_viewport_size({'width':1440,'height':960})
            # A fresh mobile visit starts with results; exploration is an explicit disclosure.
            mobile=browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
            mobile.goto(result['base']+'/#library?feed=all&q=合成探索');mobile.get_by_role('button',name='研究员',exact=True).click()
            expect(mobile.locator('.material-discovery')).not_to_have_attribute('open','')
            expect(mobile.locator('.library-row').first).to_be_visible();mobile.screenshot(path=str(out/'390.png'))
            for width in (390,320):
                mobile.set_viewport_size({'width':width,'height':844})
                assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                if not mobile.locator('.material-discovery').get_attribute('open')=='':mobile.locator('.material-discovery>summary').click()
                expect(mobile.locator('[data-material-globe] canvas')).to_be_visible()
                mobile.screenshot(path=str(out/f'explore-{width}.png'))
                mobile.locator('.material-discovery>summary').click()
                mobile.locator('.library-row .title-button').first.click();expect(mobile.locator('.library-reader .detail-title')).to_be_visible()
                assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                mobile.screenshot(path=str(out/f'reading-{width}.png'))
                mobile.get_by_role('button',name='返回探索与结果',exact=True).click()
            mobile.close()
            # Chromium's real browser zoom through a local extension, matching existing acceptance scripts.
            extension=out/'zoom-extension';extension.mkdir()
            (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Synthetic acceptance zoom','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
            (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
            zoom=p.chromium.launch_persistent_context(str(out/'zoom-profile'),headless=False,ignore_default_args=['--disable-extensions'],args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}'],viewport={'width':1366,'height':900})
            worker=zoom.service_workers[0] if zoom.service_workers else zoom.wait_for_event('serviceworker')
            zp=zoom.pages[0];zp.goto(result['base']+'/#library?feed=all&q=合成探索');zp.get_by_role('button',name='研究员',exact=True).click()
            worker.evaluate('''async()=>{const tabs=await chrome.tabs.query({});const tab=tabs.find(t=>t.url.startsWith('http://127.0.0.1:'));await chrome.tabs.setZoom(tab.id,2)}''')
            expect(zp.locator('.library-row').first).to_be_visible();assert zp.evaluate('document.documentElement.scrollWidth<=innerWidth')
            zp.screenshot(path=str(out/'zoom-200.png'));result['zoom_inner_width']=zp.evaluate('innerWidth');zoom.close()
            result['checks'].append('390/320 results, exploration and reader fit; actual Chrome 200% zoom fits')
            # Denial of a formerly visible record removes its old body on focus revalidation.
            page.locator('.library-row .title-button').first.click();expect(page.locator('.library-reader .detail-title')).to_be_visible()
            denied_id=page.locator('.library-current').get_attribute('data-library-record')
            record=client.get('/api/records/'+denied_id).json
            post('/api/records/'+denied_id,{'version':record['version'],'visibility':'restricted','allowed_user_ids':[]},'PUT')
            page.evaluate('window.dispatchEvent(new Event("focus"))')
            expect(page.locator('.library-reader')).not_to_be_visible()
            expect(page.locator(f'.library-row[data-library-record="{denied_id}"]')).to_have_count(0)
            result['checks'].append('confirmed record permission loss closes reader and removes row')
            # Cross-account session replacement must not leave the former reader or graph.
            page.locator('.library-row .title-button').first.click();expect(page.locator('.library-reader .detail-title')).to_be_visible()
            session=page.request.get(result['base']+'/api/session').json()
            page.request.post(result['base']+'/api/logout',data={},headers={'X-CSRF-Token':session['csrf']})
            session=page.request.get(result['base']+'/api/session').json()
            page.request.post(result['base']+'/api/login',data={'username':'colleague','password':'LocalDemo2026!'},headers={'X-CSRF-Token':session['csrf']})
            page.evaluate('window.dispatchEvent(new Event("focus"))')
            expect(page.locator('.desk-account')).to_contain_text('周')
            expect(page.locator('.library-reader')).not_to_be_visible()
            result['checks'].append('account change revalidates and discards prior reader/graph state')
            for route,name in (('sources','sources'),('collaboration','collaboration')):
                page.goto(result['base']+'/#'+route);expect(page.locator('#content h1').first).to_be_visible();page.screenshot(path=str(out/(name+'-desktop.png')))
            assert not errors,errors
            result['errors']=errors;browser.close()
    finally:
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        server.shutdown();server.server_close();thread.join(5)
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
