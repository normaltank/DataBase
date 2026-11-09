"""Isolated public-HTTP/browser acceptance for #138. No real data or AI worker."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from platform_app.web import create_app


class Quiet(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--baseline-ui', action='store_true', help='Reproduce the red entry check against the fixed pre-integration UI.')
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    app = create_app(evidence/'data', testing=True, embedded_worker=False)
    client = app.test_client()

    def call(path, values, method='POST'):
        token = client.get('/api/session').json['csrf']
        response = client.open(path, method=method, json=values, headers={'X-CSRF-Token':token})
        assert response.status_code in (200, 201), response.json
        return response.json

    call('/api/login', {'username':'researcher', 'password':'LocalDemo2026!'})
    source = call('/api/sources', {'name':'合成地球来源', 'kind':'institution', 'country':'Japan'})['id']
    for i in range(26):
        country = 'Latvia|拉脱维亚'+('|Germany' if i < 10 else '') if i < 23 else ['Japan', '', 'Yugoslavia|LostTerritory'][i-23]
        call('/api/records', {'title':f'合成地球资料 {i:02}', 'kind':'report', 'source_id':source,
                            'countries':country, 'published_on':'2020', 'abstract':'完全合成验收材料，非实际研究资料。'})
    call('/api/records', {'title':'合成地球隐藏', 'kind':'report', 'countries':'Japan', 'visibility':'restricted'})
    server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}/'
    checks, errors, violations, requests = [], [], [], []
    try:
        extension = evidence/'zoom-extension'; extension.mkdir()
        (extension/'manifest.json').write_text(json.dumps({'manifest_version':3, 'name':'Local acceptance zoom', 'version':'1.0', 'permissions':['tabs'], 'background':{'service_worker':'worker.js'}}))
        (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(evidence/'profile'), headless=False,
                ignore_default_args=['--disable-extensions'], args=['--headless=new', f'--disable-extensions-except={extension}', f'--load-extension={extension}'],
                viewport={'width':1366, 'height':900})
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page = context.pages[0]; page.set_default_timeout(15000)
            page.on('pageerror', lambda error:errors.append(str(error)))
            page.on('request', lambda request:requests.append(request.url))
            # This external script is loaded normally. A runtime strict meta intersects
            # the response policy even when AdGuard rewrites the original response.
            strict = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'"
            original = (ROOT/'static/visual-loader.js').read_text(encoding='utf-8')
            prefix = """window.globePolicyViolations=[];
document.addEventListener('securitypolicyviolation',e=>window.globePolicyViolations.push({directive:e.effectiveDirective,blocked:e.blockedURI,source:e.sourceFile,line:e.lineNumber}));
const strictMeta=document.createElement('meta');strictMeta.httpEquiv='Content-Security-Policy';strictMeta.content=POLICY;document.head.append(strictMeta);
const sentinel=document.createElement('i');sentinel.setAttribute('style','color:rgb(1, 2, 3)');document.body.append(sentinel);
window.globeStyleSentinel=getComputedStyle(sentinel).color!=='rgb(1, 2, 3)';sentinel.remove();
try{Function('return 1')();window.globeEvalSentinel=false;}catch(e){window.globeEvalSentinel=true;}
""".replace('POLICY', json.dumps(strict))
            page.route('**/static/visual-loader.js', lambda route:route.fulfill(content_type='text/javascript', body=prefix+original))
            if args.baseline_ui:
                baseline=subprocess.check_output(['git','show','788adf579f22f84d230989d4cc596bee759d977a:static/material-discovery.js'],cwd=ROOT).decode('utf-8')
                page.route('**/static/material-discovery.js',lambda route:route.fulfill(content_type='text/javascript',body=baseline))
            page.goto(base)
            page.get_by_role('button', name='协作同事', exact=True).click()
            url = base+'#library?feed=all&q=合成地球&source='+source+'&page=2'
            page.goto(url)
            panel = page.locator('.material-discovery')
            expect(panel).to_have_attribute('open', '')
            expect(panel.locator('.material-scope')).to_contain_text('26 条')
            expect(panel.locator('[data-material-globe] canvas')).to_be_visible()
            expect(panel.locator('[data-material-globe-status]')).to_contain_text('拖动旋转')
            assert page.evaluate('window.globeStyleSentinel && window.globeEvalSentinel')
            initial_violations = page.evaluate('window.globePolicyViolations')
            assert initial_violations and all(v['source'].endswith('/static/visual-loader.js') for v in initial_violations), initial_violations
            checks.append({'strict_policy':strict, 'style_and_eval_sentinels_blocked':True, 'intentional_violations':initial_violations})
            assert any('/static/vendor/visual/globe.js' in request for request in requests)
            assert not any('/fixture' in request or 'cdn.' in request for request in requests)
            # Independent camera projection of 24E, 57N, then a real pointer click.
            canvas = panel.locator('[data-material-globe] canvas'); canvas.scroll_into_view_if_needed()
            bounds = canvas.bounding_box()
            lon, lat, view_lon, view_lat = map(math.radians, (24, 57, 22, 45))
            point = [2.5*math.cos(lat)*math.sin(lon), 2.5*math.sin(lat), 2.5*math.cos(lat)*math.cos(lon)]
            dot = lambda a,b:sum(x*y for x,y in zip(a,b))
            right = [math.cos(view_lon), 0, -math.sin(view_lon)]
            up = [-math.sin(view_lat)*math.sin(view_lon), math.cos(view_lat), -math.sin(view_lat)*math.cos(view_lon)]
            forward = [math.cos(view_lat)*math.sin(view_lon), math.sin(view_lat), math.cos(view_lat)*math.cos(view_lon)]
            scale = bounds['height']/2/math.tan(math.radians(20))/(8.6-dot(point,forward))
            page.mouse.click(bounds['x']+bounds['width']/2+dot(point,right)*scale, bounds['y']+bounds['height']/2-dot(point,up)*scale)
            expect(page.locator('.material-scope')).to_contain_text('23 条')
            expect(page.locator('.results-head')).to_contain_text('23')
            expect(page.locator('.library-row')).to_have_count(20)
            assert any('/api/records?' in request and 'country=LV' in request for request in requests)
            query = parse_qs(urlsplit(page.url).fragment.split('?',1)[1])
            assert query['country']==['LV'] and query['source']==[source] and query['q']==['合成地球'] and 'page' not in query, query
            expect(page.locator('.material-context')).to_contain_text('共 26 条')
            checks.append('Real Three globe country click -> same query HTTP/list: LV 23; context 26; source/query retained; page cleared')
            # Exploration presentation changes must preserve the applied query.
            before=page.url
            page.locator('[data-material-scene=time]').click()
            expect(page.locator('[data-material-timeline] canvas')).to_be_visible()
            expect(page.locator('[data-material-globe] canvas')).to_have_count(0)
            expect(page.locator('.material-time')).to_contain_text('排除时间条件，共 23 条')
            page.locator('[data-material-role]').select_option('collected')
            expect(page.locator('.material-scope')).to_contain_text('23 条')
            page.locator('[data-material-role]').select_option('published')
            page.locator('[data-material-scene=country]').click()
            expect(page.locator('[data-material-timeline] canvas')).to_have_count(0)
            expect(page.locator('[data-material-globe] canvas')).to_be_visible()
            assert parse_qs(urlsplit(page.url).fragment.split('?',1)[1])['country']==['LV']
            expect(page.locator('.material-country-list [data-material-country=LV]')).to_have_attribute('aria-pressed','true')
            checks.append('Country -> time/role -> country preserves LV/source/query and disposes hidden scene')
            page.get_by_role('button', name='清除研究对象国条件', exact=True).click()
            expect(page.locator('.material-scope')).to_contain_text('26 条')
            page.locator('.material-country-list [data-material-country="__unknown__"]').click()
            expect(page.locator('.material-scope')).to_contain_text('1 条')
            page.get_by_role('button', name='清除研究对象国条件', exact=True).click()
            expect(page.locator('.material-scope')).to_contain_text('26 条')
            for width, zoom in [(1366,1),(390,1),(320,1),(1366,2)]:
                page.set_viewport_size({'width':width,'height':900 if width>400 else 844})
                worker.evaluate("async ({base,zoom})=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,zoom)}", {'base':base,'zoom':zoom})
                actual = worker.evaluate("async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));return chrome.tabs.getZoom(tab.id)}", base)
                assert actual==zoom
                button = page.locator('.material-country-list [data-material-country=LV]')
                button.focus();page.keyboard.press('Enter')
                expect(page.locator('.material-scope')).to_contain_text('23 条')
                expect(button).to_be_focused()
                page.get_by_role('button', name='清除研究对象国条件', exact=True).click()
                expect(page.locator('.material-scope')).to_contain_text('26 条')
                overflow=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
                assert overflow['scroll']<=overflow['width']+1,overflow
                controls=panel.locator('button,select').evaluate_all('(els)=>els.filter(el=>el.getClientRects().length).map(el=>({text:el.textContent,left:el.getBoundingClientRect().left,right:el.getBoundingClientRect().right,height:el.getBoundingClientRect().height,width:document.documentElement.clientWidth}))')
                assert all(c['left']>=0 and c['right']<=c['width']+1 for c in controls),controls
                if width<=390 or zoom==2:
                    assert all(c['height']>=44 for c in controls),controls
                panel.scroll_into_view_if_needed()
                page.screenshot(path=str(evidence/f'viewport-{width}-zoom-{zoom}.png'))
                panel.screenshot(path=str(evidence/f'panel-{width}-zoom-{zoom}.png'))
                checks.append({'viewport':width,'native_zoom':actual,'layout':overflow,'keyboard_filter':'pass'})
            worker.evaluate("async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,1)}", base)
            page.set_viewport_size({'width':1366,'height':900})
            page.emulate_media(reduced_motion='reduce')
            page.locator('[data-material-view=world]').click()
            expect(page.locator('[data-material-globe] canvas')).to_be_visible()
            # Opening existing record uses the actual ordinary reader.
            page.locator('.library-row').first.get_by_role('button').first.click()
            expect(page.get_by_text('完全合成验收材料，非实际研究资料。',exact=False).first).to_be_visible()
            page.goto(base+'#sources')
            expect(page.locator('[data-material-globe] canvas')).to_have_count(0)
            page.goto(url)
            expect(page.locator('[data-material-globe] canvas')).to_be_visible()
            page.get_by_role('button',name='平面地图',exact=True).click()
            expect(page.locator('.material-map')).to_be_visible()
            expect(page.locator('[data-material-globe] canvas')).to_have_count(0)
            checks.append('Ordinary reader shows the synthetic abstract; route navigation and flat-map mode dispose globe; reduced motion remains usable')
            # A blocked real ESM load in a fresh page must leave text filtering live.
            fallback = context.new_page()
            fallback.route('**/static/vendor/visual/globe.js',lambda route:route.abort())
            fallback.goto(url)
            expect(fallback.locator('[data-material-globe-status]')).to_contain_text('地球暂不可用')
            fallback.locator('.material-country-list [data-material-country=JP]').click()
            expect(fallback.locator('.material-scope')).to_contain_text('1 条')
            fallback.unroute('**/static/vendor/visual/globe.js')
            fallback.get_by_role('button',name='重试地球',exact=True).click()
            expect(fallback.locator('[data-material-globe] canvas')).to_be_visible()
            fallback.close()
            # Browser without WebGL, normal external entry scripts, same text task.
            no_gl = p.chromium.launch(headless=True,args=['--disable-webgl'])
            no_page = no_gl.new_page();no_page.goto(base)
            no_page.get_by_role('button',name='协作同事',exact=True).click();no_page.goto(url)
            expect(no_page.locator('[data-material-globe-status]')).to_contain_text('地球暂不可用')
            no_page.locator('.material-country-list [data-material-country=LV]').click()
            expect(no_page.locator('.material-scope')).to_contain_text('23 条')
            no_gl.close()
            checks.append('Blocked ESM and disabled WebGL preserve working country text query')
            call('/api/records', {'title':'合成地球新增', 'kind':'report', 'source_id':source, 'countries':'Latvia'})
            page.goto(url)
            expect(page.locator('.material-scope')).to_contain_text('27 条')
            expect(page.locator('.material-country-list [data-material-country=LV]')).to_contain_text('24')
            held=[]
            page.route('**/api/material-discovery?**',lambda route:held.append(route),times=1)
            page.locator('.material-discovery>summary').click()
            expect(page.locator('[data-material-globe] canvas')).to_have_count(0)
            page.locator('.material-discovery>summary').click()
            expect(page.locator('.material-scope')).to_contain_text('27 条')
            expect(page.locator('[data-material-globe] canvas')).to_have_count(0)
            page.goto(base+'#sources')
            expect(page.locator('.material-discovery')).to_have_count(0)
            assert held
            held[0].fulfill(status=200,json={'total':999,'countries':[],'dates':{}})
            expect(page.locator('.material-discovery')).to_have_count(0)
            checks.append('New HTTP record updates globe counts; folding disposes canvas; late distribution after navigation cannot remount')
            final_violations=page.evaluate('window.globePolicyViolations')
            assert final_violations==initial_violations,final_violations
            assert not errors,errors
            context.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        (evidence/'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors,'base':base,'server_thread_closed':not thread.is_alive()},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'evidence':str(evidence),'checks':checks,'server_thread_closed':not thread.is_alive()},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
