"""Public HTTP and real browser #139 acceptance, isolated synthetic data only."""
import argparse
import json
import math
import subprocess
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

def main():
    expect.set_options(timeout=15000)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir',type=Path,required=True)
    parser.add_argument('--baseline-ui',action='store_true')
    args=parser.parse_args(); evidence=args.evidence_dir.resolve();evidence.mkdir(parents=True,exist_ok=False)
    app=create_app(evidence/'data',testing=True,embedded_worker=False); client=app.test_client()
    def call(path,values,method='POST'):
        csrf=client.get('/api/session').json['csrf']
        result=client.open(path,method=method,json=values,headers={'X-CSRF-Token':csrf})
        assert result.status_code in (200,201),result.json
        return result.json
    call('/api/login',{'username':'researcher','password':'LocalDemo2026!'})
    ids=[]
    for i in range(305):
        ids.append(call('/api/records',{'title':f'合成时间资料 {i:03}','kind':['report','policy','news'][i%3],'countries':'Latvia' if i<300 else 'Japan',
            'published_on':['1874','2001-02','2031-12-29',''][i%4], 'abstract':f'完全合成时间验收正文 {i:03}。'})['id'])
        if i%60==0: call('/api/records',{'title':'合成时间资料隐藏','kind':'report','countries':'Latvia','published_on':'1500','visibility':'restricted'})
    call('/api/login',{'username':'colleague','password':'LocalDemo2026!'})
    projection=client.get('/api/material-discovery?visual_window=1&q=合成时间资料').json
    assert (projection['total'],projection['timeline_window']['loaded'],projection['timeline_window']['has_more'])==(305,300,True)
    assert all(row['id'] in ids for row in projection['timeline_window']['items'])
    server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}/';checks=['HTTP window 305/300, has_more, no unauthorized IDs'];errors=[];requests=[]
    try:
        extension=evidence/'zoom-extension';extension.mkdir()
        (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Local acceptance zoom','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
        (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
        with sync_playwright() as p:
            context=p.chromium.launch_persistent_context(str(evidence/'profile'),headless=False,ignore_default_args=['--disable-extensions'],
                args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}'],viewport={'width':1366,'height':900})
            worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page=context.pages[0];page.set_default_timeout(15000);page.on('pageerror',lambda error:errors.append(str(error)));page.on('request',lambda req:requests.append(req.url))
            strict="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'"
            prefix="""window.timelineViolations=[];
document.addEventListener('securitypolicyviolation',e=>window.timelineViolations.push({directive:e.effectiveDirective,source:e.sourceFile,line:e.lineNumber}));
const strictMeta=document.createElement('meta');strictMeta.httpEquiv='Content-Security-Policy';strictMeta.content=POLICY;document.head.append(strictMeta);
const sentinel=document.createElement('i');sentinel.setAttribute('style','color:rgb(1, 2, 3)');document.body.append(sentinel);window.timelineStyleSentinel=getComputedStyle(sentinel).color!=='rgb(1, 2, 3)';sentinel.remove();
try{Function('return 1')();window.timelineEvalSentinel=false;}catch(e){window.timelineEvalSentinel=true;}
""".replace('POLICY',json.dumps(strict))
            loader=(ROOT/'static/visual-loader.js').read_text(encoding='utf-8')
            context.route('**/static/visual-loader.js',lambda route:route.fulfill(content_type='text/javascript',body=prefix+loader))
            if args.baseline_ui:
                baseline=subprocess.check_output(['git','show','f6dffda018992e32ab534651497ffa51dde73fd6:static/material-discovery.js'],cwd=ROOT).decode('utf-8')
                page.route('**/static/material-discovery.js',lambda route:route.fulfill(content_type='text/javascript',body=baseline))
            page.goto(base);page.get_by_role('button',name='协作同事',exact=True).click()
            url=base+'#library?feed=all&q=合成时间资料'
            page.goto(url);panel=page.locator('.material-discovery')
            expect(panel.locator('[data-material-globe] canvas')).to_be_visible()
            expect(panel.locator('[data-material-timeline] canvas')).to_have_count(0)
            before=page.url;panel.locator('[data-material-scene=time]').click();assert page.url==before
            expect(panel.locator('[data-material-globe] canvas')).to_have_count(0)
            expect(panel.locator('[data-material-timeline] canvas')).to_be_visible()
            expect(panel.locator('.material-window-scope')).to_contain_text('已加载 300 / 完整匹配 305')
            panel.locator('.material-time').screenshot(path=str(evidence/'initial-time-desktop.png'))
            assert page.evaluate('window.timelineStyleSentinel && window.timelineEvalSentinel')
            violations=page.evaluate('window.timelineViolations');assert violations and all(v['source'].endswith('/static/visual-loader.js') for v in violations),violations
            # Real ECharts brush: direct plot drag updates native fields, then apply.
            chart=panel.locator('.material-time-chart');chart.scroll_into_view_if_needed();b=chart.bounding_box()
            page.mouse.move(b['x']+b['width']*.36,b['y']+110);page.mouse.down();page.mouse.move(b['x']+b['width']*.77,b['y']+150,steps=12);page.mouse.up()
            expect(panel.locator('[data-material-range-status]')).to_contain_text('待应用范围')
            start=panel.locator('[data-material-from]').input_value();end=panel.locator('[data-material-to]').input_value()
            panel.locator('[data-material-apply]').click()
            expect(page).to_have_url(__import__('re').compile('from='+start+'-01-01'))
            query=parse_qs(urlsplit(page.url).fragment.split('?',1)[1]);assert query['to']==[end+'-12-31']
            expect(panel.locator('.material-scope')).to_contain_text('76 条')
            checks.append({'real_brush':[start,end],'URL_and_list':'76 records'})
            panel.locator('[data-material-clear=time]').click();expect(panel.locator('.material-scope')).to_contain_text('305 条')
            panel.locator('.material-native-years>summary').click()
            panel.locator('[data-material-year="2001"]').focus();page.keyboard.press('Enter')
            expect(panel.locator('.material-scope')).to_contain_text('76 条')
            expect(panel.locator('[data-material-year="2001"]')).to_be_focused()
            panel.locator('[data-material-clear=time]').click();expect(panel.locator('.material-scope')).to_contain_text('305 条')
            panel.locator('.material-native-years>summary').click()
            # Actual slider drag, not dispatchAction through DevTools.
            chart.scroll_into_view_if_needed();b=chart.bounding_box()
            page.mouse.move(b['x']+b['width']-25,b['y']+b['height']-20);page.mouse.down();page.mouse.move(b['x']+b['width']*.7,b['y']+b['height']-20,steps=10);page.mouse.up()
            expect(panel.locator('[data-material-range-status]')).to_contain_text('待应用范围')
            checks.append({'real_dataZoom_fields':[panel.locator('[data-material-from]').input_value(),panel.locator('[data-material-to]').input_value()]})
            panel.locator('[data-material-from]').fill('2001');panel.locator('[data-material-to]').fill('2001');panel.locator('[data-material-to]').press('Enter')
            expect(panel.locator('.material-scope')).to_contain_text('76 条')
            expect(panel.locator('[data-material-from]')).to_be_focused()
            panel.locator('[data-material-role]').select_option('collected')
            expect(panel.locator('.material-scope')).to_contain_text('0 条');assert 'date_field=collected' in page.url
            panel.locator('[data-material-clear=time]').click();expect(panel.locator('.material-scope')).to_contain_text('305 条')
            panel.locator('[data-material-role]').select_option('updated');expect(panel.locator('.material-scope')).to_contain_text('305 条')
            panel.locator('[data-material-role]').select_option('published');expect(panel.locator('.material-scope')).to_contain_text('305 条')
            panel.locator('[data-material-year=unknown]').click();expect(panel.locator('.material-scope')).to_contain_text('76 条')
            panel.locator('[data-material-clear=time]').click();expect(panel.locator('.material-scope')).to_contain_text('305 条')
            panel.locator('[data-material-from]').fill('1998');before=page.url
            panel.locator('[data-material-scene=country]').click();expect(panel.locator('[data-material-timeline] canvas')).to_have_count(0)
            expect(panel.locator('[data-material-globe] canvas')).to_be_visible();assert page.url==before
            panel.locator('[data-material-scene=time]').click();expect(panel.locator('[data-material-from]')).to_have_value('1998');assert page.url==before
            panel.locator('[data-material-scene=country]').click()
            panel.locator('.material-country-list [data-material-country=JP]').click();expect(panel.locator('.material-scope')).to_contain_text('5 条')
            panel.locator('[data-material-scene=time]').click()
            expect(panel.locator('.material-time')).to_contain_text('排除时间条件，共 5 条')
            checks.append('Scene switch disposes hidden graph; query and unapplied input preserved; country filter remains consistent')
            checks.append('Native single-year/Enter and all three roles, unknown and country change share query/list/URL')
            # One known record gives an independently projectable actual mesh point.
            page.goto(base+'#library?feed=all&q='+ids[0])
            expect(panel.locator('.material-window-scope')).to_contain_text('完整匹配 1 条')
            panel.locator('[data-material-lens]').click();lens=panel.locator('.material-time-lens canvas');expect(lens).to_be_visible();lens.scroll_into_view_if_needed();b=lens.bounding_box()
            panel.locator('.material-time').screenshot(path=str(evidence/'single-lens-desktop.png'))
            lens.scroll_into_view_if_needed();b=lens.bounding_box()
            fit=max(7.4,7/(math.tan(math.radians(20))*b['width']/b['height']))
            point=[0,1.5,-1.28];distance=fit*math.sqrt(1.0064);up=[0,1/math.sqrt(1.0064),-.08/math.sqrt(1.0064)];forward=[0,.08/math.sqrt(1.0064),1/math.sqrt(1.0064)]
            dot=lambda a,c:sum(x*y for x,y in zip(a,c));scale=b['height']/2/math.tan(math.radians(20))/(distance-dot(point,forward))
            with page.expect_response(lambda r:'/api/records/'+ids[0] in r.url and r.status==200):
                page.mouse.click(b['x']+b['width']/2,b['y']+b['height']/2-dot(point,up)*scale)
            expect(page.locator('.library-reader')).to_contain_text('合成时间资料 000')
            page.get_by_role('button',name='返回列表',exact=True).click()
            expect(panel.locator('[data-material-from]')).to_have_value('')
            checks.append('Independent projection -> real Three point click -> correct ID HTTP -> ordinary reader -> return')
            for width,zoom in [(1366,1),(390,1),(320,1),(1366,2)]:
                page.set_viewport_size({'width':width,'height':900 if width>400 else 844})
                worker.evaluate("async ({base,zoom})=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,zoom)}",{'base':base,'zoom':zoom})
                assert worker.evaluate("async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));return chrome.tabs.getZoom(tab.id)}",base)==zoom
                panel.locator('[data-material-from]').fill('1874');panel.locator('[data-material-to]').fill('1874');panel.locator('[data-material-apply]').focus();page.keyboard.press('Enter')
                expect(panel.locator('.material-scope')).to_contain_text('1 条')
                overflow=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})');assert overflow['scroll']<=overflow['width']+1,overflow
                controls=panel.locator('.material-time input,.material-time button,.material-time select').evaluate_all('(els)=>els.filter(e=>e.getClientRects().length).map(e=>({height:e.getBoundingClientRect().height,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,width:document.documentElement.clientWidth}))')
                assert all(c['left']>=0 and c['right']<=c['width']+1 for c in controls),controls
                if width<=390 or zoom==2: assert all(c['height']>=44 for c in controls),controls
                panel.locator('.material-time').screenshot(path=str(evidence/f'time-{width}-zoom-{zoom}.png'))
                checks.append({'width':width,'native_zoom':zoom,'keyboard_and_layout':'pass'})
            worker.evaluate("async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,1)}",base)
            page.set_viewport_size({'width':1366,'height':900});page.emulate_media(reduced_motion='reduce')
            page.goto(url);expect(panel.locator('.material-time-lens canvas')).to_be_visible()
            panel.screenshot(path=str(evidence/'multi-lens-desktop.png'))
            lens=panel.locator('.material-time-lens canvas');lens.scroll_into_view_if_needed();b=lens.bounding_box()
            known=[item for item in projection['timeline_window']['items'] if item['precision']!='unknown']
            target=known[26];groups=sorted({item['kind'] for item in projection['timeline_window']['items']})
            from datetime import date
            a=date.fromisoformat(target['date'] if target['precision']=='day' else target['date']+'-01' if target['precision']=='month' else target['date']+'-01-01')
            if target['precision']=='year':zdate=date(a.year+1,1,1)
            elif target['precision']=='month':zdate=date(a.year+int(a.month==12),a.month%12+1,1)
            else:zdate=date.fromordinal(a.toordinal()+1)
            px=-6+12*((a.toordinal()+zdate.toordinal())/2-date(1874,1,1).toordinal())/(date(2032,1,1)-date(1874,1,1)).days
            point=[px,1.5-groups.index(target['kind'])*3/(len(groups)-1)+(26%3)*.15,(26//3%9-4)*.32]
            fit=max(7.4,7/(math.tan(math.radians(20))*b['width']/b['height']));distance=fit*math.sqrt(1.0064)
            scale=b['height']/2/math.tan(math.radians(20))/(distance-dot(point,forward))
            with page.expect_response(lambda r:'/api/records/' in r.url and r.request.method=='GET' and r.status==200) as picked:
                page.mouse.click(b['x']+b['width']/2+point[0]*scale,b['y']+b['height']/2-dot(point,up)*scale)
            picked_record=picked.value.json();assert picked_record['id'] in {item['id'] for item in known}
            expect(page.locator('.library-reader')).to_contain_text(picked_record['title'])
            page.screenshot(path=str(evidence/'multi-lens-selected-reader.png'))
            page.get_by_role('button',name='返回列表',exact=True).click()
            expect(panel.locator('[data-material-time-status]')).to_contain_text('已选中：'+picked_record['title'])
            panel.screenshot(path=str(evidence/'multi-lens-selected.png'))
            checks.append({'multi_year_type_Three_pick':picked_record['id'],'title':picked_record['title']})
            page.goto(base+'#sources');expect(page.locator('.material-time-chart canvas')).to_have_count(0)
            page.goto(url);expect(panel.locator('.material-time-lens canvas')).to_be_visible()
            # Transient refresh failure retains exact input.
            panel.locator('[data-material-from]').fill('1993')
            page.route('**/api/material-discovery?**',lambda route:route.fulfill(status=503,json={'error':'合成网络故障'}),times=1)
            page.locator('.material-discovery>summary').click();page.locator('.material-discovery>summary').click()
            expect(panel.locator('[data-material-time-status]')).to_contain_text('读取失败')
            expect(panel.locator('[data-material-from]')).to_have_value('1993')
            page.goto(url+'x');page.goto(url);expect(panel.locator('.material-time-chart canvas')).to_be_visible()
            # Fresh page: actual ESM failure leaves equivalent native query live.
            fallback=context.new_page();fallback.route('**/static/vendor/visual/timeline.js',lambda route:route.abort());fallback.goto(url)
            fallback.locator('[data-material-scene=time]').click()
            expect(fallback.locator('[data-material-time-status]')).to_contain_text('时间图暂不可用')
            fallback.locator('[data-material-from]').fill('1874');fallback.locator('[data-material-to]').fill('1874');fallback.locator('[data-material-apply]').click()
            expect(fallback.locator('.material-scope')).to_contain_text('77 条')
            fallback.unroute('**/static/vendor/visual/timeline.js');fallback.locator('[data-material-time-retry]').click()
            expect(fallback.locator('.material-time-chart canvas')).to_be_visible()
            expect(fallback.locator('[data-material-from]')).to_have_value('1874');fallback.close()
            no_gl=p.chromium.launch(headless=True,args=['--disable-webgl']);no_page=no_gl.new_page();no_page.goto(base);no_page.get_by_role('button',name='协作同事',exact=True).click();no_page.goto(url)
            no_page.locator('[data-material-scene=time]').click();expect(no_page.locator('.material-time-chart canvas')).to_be_visible();no_page.locator('[data-material-lens]').click()
            expect(no_page.locator('[data-material-time-status]')).to_contain_text('时间透镜暂不可用');no_gl.close()
            checks.append('Reduced motion, navigation disposal, transient input preservation, ESM failure, WebGL failure')
            # A pending module after route departure cannot remount.
            late=context.new_page();held=[];late.route('**/static/vendor/visual/timeline.js',lambda route:held.append(route));late.goto(url)
            late.locator('[data-material-scene=time]').click()
            expect(late.locator('[data-material-time-status]')).to_contain_text('正在加载')
            late.goto(base+'#sources');assert held;held[0].fulfill(content_type='text/javascript',body=(ROOT/'static/vendor/visual/timeline.js').read_text(encoding='utf-8'))
            expect(late.locator('.material-time-chart')).to_have_count(0);late.close()
            identity=context.new_page();held_identity=[]
            identity.route('**/static/vendor/visual/timeline.js',lambda route:held_identity.append(route))
            identity.goto(url);identity.locator('[data-material-scene=time]').click()
            expect(identity.locator('[data-material-time-status]')).to_contain_text('正在加载')
            identity.get_by_role('button',name='退出登录',exact=True).click()
            expect(identity.get_by_role('button',name='协作同事',exact=True)).to_be_visible()
            assert held_identity;held_identity[0].fulfill(content_type='text/javascript',body=(ROOT/'static/vendor/visual/timeline.js').read_text(encoding='utf-8'))
            expect(identity.locator('.material-time-chart')).to_have_count(0);identity.close()
            page.goto(base);page.get_by_role('button',name='协作同事',exact=True).click()
            # Current permissions are rechecked at public reads, on next visible refresh.
            call('/api/login',{'username':'researcher','password':'LocalDemo2026!'})
            call('/api/records/'+ids[0],{'version':1,'visibility':'restricted'},method='PUT')
            page.goto(base+'#library?feed=all&q='+ids[0])
            page.locator('[data-material-scene=time]').click()
            expect(panel.locator('.material-window-scope')).to_contain_text('完整匹配 0 条')
            expect(panel.locator('[data-material-record]')).to_have_count(0)
            page.get_by_role('button',name='退出登录',exact=True).click();expect(page.locator('.material-time-chart')).to_have_count(0)
            checks.append('Late ESM cannot remount, revoked record absent after authenticated reread, logout disposes visuals')
            assert page.evaluate('window.timelineViolations')==violations,page.evaluate('window.timelineViolations')
            assert not errors,errors
            assert any('/static/vendor/visual/timeline.js' in req for req in requests)
            assert not any('fixture' in req or 'cdn.' in req for req in requests)
            context.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        (evidence/'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors,'base':base,'server_thread_closed':not thread.is_alive()},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':checks,'evidence':str(evidence),'server_thread_closed':not thread.is_alive()},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
