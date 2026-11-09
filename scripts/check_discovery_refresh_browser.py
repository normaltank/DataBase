"""Public-route regression for #134 refresh, retained interaction and visibility.

Visibility here is a controlled DOM component test, not OS/native tab evidence.
All records, accounts and the random-port server belong to this isolated run.
"""
import argparse
import json
import io
import math
import shutil
import sys
import threading
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright
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
    parser.add_argument('--case', choices=['focus', 'changed', 'stale', 'lifecycle', 'labels', 'security', 'network', 'all'], default='all')
    args = parser.parse_args()
    out = args.evidence_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    app = create_app(out/'data', testing=True, embedded_worker=False)
    client = app.test_client()

    def call(path, data):
        csrf = client.get('/api/session').json['csrf']
        result = client.post(path, json=data, headers={'X-CSRF-Token': csrf})
        assert result.status_code in (200, 201), result.json
        return result.json

    call('/api/login', {'username': 'researcher', 'password': 'LocalDemo2026!'})
    source = call('/api/sources', {'name':'合成刷新来源', 'kind':'institution'})['id']
    ids = []
    for year in ['1990', '2001', '2021']:
        ids.append(call('/api/records', {'title': '合成刷新验收 '+year, 'kind': 'report',
                             'source_id':source, 'countries': 'Latvia', 'published_on': year})['id'])
    server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
    assert server.server_port not in {6430, 3435, 3436}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}/'
    checks = []
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1366, 'height': 900})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base)
            page.get_by_role('button', name='协作同事', exact=True).click()
            page.goto(base+'#library?feed=all&q=合成刷新验收')
            panel = page.locator('.material-discovery')
            expect(panel.locator('[data-material-globe] canvas')).to_be_visible()
            panel.locator('[data-material-scene=time]').click()
            expect(panel.locator('.material-time-chart canvas')).to_be_visible()
            panel.locator('[data-material-lens]').click()
            lens = panel.locator('.material-time-lens canvas')
            expect(lens).to_be_visible()

            def same_scene(first,second):
                # Ignore the one-pixel screenshot clip boundary, which can include
                # a neighbouring control's focus border; all chart pixels must match.
                a=Image.open(io.BytesIO(first)).convert('RGB');b=Image.open(io.BytesIO(second)).convert('RGB')
                return a.size==b.size and a.crop((1,1,a.width-1,a.height-1)).tobytes()==b.crop((1,1,b.width-1,b.height-1)).tobytes()

            def focus_refresh():
                expect(panel).not_to_have_attribute('aria-busy','true')
                page.evaluate("window.dispatchEvent(new Event('focus'))")

            def rotate():
                lens.scroll_into_view_if_needed()
                b = lens.bounding_box()
                page.mouse.move(b['x']+b['width']*.45, b['y']+b['height']*.5)
                page.mouse.down()
                page.mouse.move(b['x']+b['width']*.55, b['y']+b['height']*.62, steps=12)
                page.mouse.up()
                page.wait_for_timeout(150)

            def brush():
                chart = panel.locator('.material-time-chart')
                chart.scroll_into_view_if_needed()
                b = chart.bounding_box()
                page.mouse.move(b['x']+b['width']*.35, b['y']+100)
                page.mouse.down()
                page.mouse.move(b['x']+b['width']*.7, b['y']+140, steps=12)
                page.mouse.up()
                expect(panel.locator('[data-material-range-status]')).to_contain_text('待应用范围')

            if args.case in ('focus', 'all'):
                rotate()
                chart = panel.locator('.material-time-chart')
                chart.scroll_into_view_if_needed();b=chart.bounding_box()
                page.mouse.move(b['x']+b['width']-25,b['y']+b['height']-20)
                page.mouse.down();page.mouse.move(b['x']+b['width']*.72,b['y']+b['height']-20,steps=10);page.mouse.up()
                expect(panel.locator('[data-material-range-status]')).to_contain_text('待应用范围')
                page.mouse.move(10,10)
                page.wait_for_timeout(150)
                before_chart = chart.screenshot()
                before = lens.screenshot()
                field = panel.locator('[data-material-from]')
                field.fill('1998')
                field.focus()
                field.evaluate('e=>window.refreshField=e')
                lens.evaluate('e=>window.refreshCanvas=e')
                with page.expect_response(lambda r: '/api/material-discovery?' in r.url and r.status == 200):
                    focus_refresh()
                page.wait_for_timeout(200)
                assert field.evaluate('e=>e===window.refreshField && e===document.activeElement'), 'refresh replaced focused input'
                assert lens.evaluate('e=>e===window.refreshCanvas'), 'refresh replaced the exploration canvas'
                expect(field).to_have_value('1998')
                assert same_scene(lens.screenshot(),before), 'unchanged refresh changed rotated camera'
                page.mouse.move(10,10)
                page.wait_for_timeout(150)
                chart_after=chart.screenshot()
                (out/'zoom-before.png').write_bytes(before_chart)
                (out/'zoom-after.png').write_bytes(chart_after)
                assert same_scene(chart_after,before_chart), 'unchanged refresh changed chart zoom'
                checks.append('No-change authorized focus reread retains same focused input, draft, canvas, rotated lens and actual mouse-adjusted chart zoom')

            if args.case in ('changed', 'all'):
                call('/api/records', {'title':'合成刷新验收 新记录', 'kind':'report', 'countries':'Latvia','published_on':'2001'})
                field = panel.locator('[data-material-from]')
                field.evaluate('e=>window.changedField=e')
                lens.evaluate('e=>window.changedCanvas=e')
                held = []
                page.route('**/api/material-discovery?**',lambda route:held.append(route),times=1)
                panel.locator('[data-material-retry]').click()
                page.wait_for_timeout(150)
                assert held
                field.fill('1999');field.focus()
                held[0].fulfill(response=held[0].fetch())
                expect(panel.locator('.material-scope')).to_contain_text('4 条')
                assert field.evaluate('e=>e===window.changedField && e===document.activeElement')
                assert lens.evaluate('e=>e===window.changedCanvas')
                expect(field).to_have_value('1999')
                checks.append('Changed authorized data updates native totals in place and retains input edited while request was in flight')
                # Synchronize the ordinary list too before testing a later focus event.
                # Its independent permission/count check correctly reloads a changed list.
                page.reload()
                expect(panel.locator('[data-material-globe] canvas')).to_be_visible()
                panel.locator('[data-material-scene=time]').click()
                panel.locator('[data-material-lens]').click()
                expect(lens).to_be_visible()

            if args.case in ('stale', 'all'):
                page.route('**/api/material-discovery?**', lambda route: route.fulfill(status=503, json={'error':'合成断网'}), times=1)
                focus_refresh()
                expect(panel.locator('[data-material-time-status]')).to_contain_text('读取失败')
                brush()
                panel.locator('[data-material-retry]').click()
                expect(panel.locator('[data-material-time-status]')).not_to_contain_text('读取失败')
                checks.append('Transient failed reread retains real ECharts mouse brush, then recovers')
                # Retained globe still performs a real country-boundary mouse selection.
                panel.locator('[data-material-scene=country]').click()
                globe = panel.locator('[data-material-globe] canvas')
                expect(globe).to_be_visible()
                panel.locator('[data-material-view=europe]').click()
                page.route('**/api/material-discovery?**',lambda route:route.fulfill(status=503,json={'error':'合成断网'}),times=1)
                panel.locator('[data-material-retry]').click()
                expect(panel.locator('[data-material-globe-status]')).to_contain_text('读取失败')
                globe.scroll_into_view_if_needed();b=globe.bounding_box()
                lon,lat,vlon,vlat=map(math.radians,(24,57,22,45))
                point=[2.5*math.cos(lat)*math.sin(lon),2.5*math.sin(lat),2.5*math.cos(lat)*math.cos(lon)]
                right=[math.cos(vlon),0,-math.sin(vlon)]
                up=[-math.sin(vlat)*math.sin(vlon),math.cos(vlat),-math.sin(vlat)*math.cos(vlon)]
                forward=[math.cos(vlat)*math.sin(vlon),math.sin(vlat),math.cos(vlat)*math.cos(vlon)]
                dot=lambda a,c:sum(x*y for x,y in zip(a,c))
                scale=b['height']/2/math.tan(math.radians(20))/(8.6-dot(point,forward))
                page.mouse.click(b['x']+b['width']/2+dot(point,right)*scale,b['y']+b['height']/2-dot(point,up)*scale)
                expect(page).to_have_url(__import__('re').compile('country=LV'))
                # Independently project the one real year-precision block after another failure.
                page.goto(base+'#library?feed=all&q='+ids[0])
                expect(panel.locator('[data-material-scene=time]')).to_be_visible()
                panel.locator('[data-material-scene=time]').click()
                expect(lens).to_be_visible()
                panel.locator('[data-material-camera-reset]').click()
                page.route('**/api/material-discovery?**',lambda route:route.fulfill(status=503,json={'error':'合成断网'}),times=1)
                panel.locator('[data-material-retry]').click()
                expect(panel.locator('[data-material-time-status]')).to_contain_text('读取失败')
                lens.scroll_into_view_if_needed();b=lens.bounding_box()
                fit=max(7.4,7/(math.tan(math.radians(20))*b['width']/b['height']))
                up=[0,1/math.sqrt(1.0064),-.08/math.sqrt(1.0064)]
                forward=[0,.08/math.sqrt(1.0064),1/math.sqrt(1.0064)]
                scale=b['height']/2/math.tan(math.radians(20))/(fit*math.sqrt(1.0064)-dot([0,1.5,-1.28],forward))
                with page.expect_response(lambda r:'/api/records/'+ids[0] in r.url and r.status==200):
                    page.mouse.click(b['x']+b['width']/2,b['y']+b['height']/2-dot([0,1.5,-1.28],up)*scale)
                expect(page.locator('.library-reader')).to_contain_text('合成刷新验收 1990')
                page.get_by_role('button',name='返回列表',exact=True).click()
                panel.locator('[data-material-retry]').click()
                expect(panel.locator('[data-material-time-status]')).not_to_contain_text('读取失败')
                checks.append('After separate failed reads: real globe country click changes query; real lens block click opens the matching existing reader')

            if args.case in ('lifecycle', 'all'):
                rotate()
                before = lens.screenshot()
                # Explicit controlled-DOM component test. No claim about native OS visibility.
                page.evaluate("""()=>{window.controlledHidden=false;
                    Object.defineProperty(document,'hidden',{configurable:true,get:()=>window.controlledHidden});
                    window.lostContexts=0;document.querySelector('.material-time-lens canvas').addEventListener('webglcontextlost',()=>window.lostContexts++);
                    window.controlledHidden=true;document.dispatchEvent(new Event('visibilitychange'));}""")
                expect(panel.locator('[data-material-timeline] canvas')).to_have_count(0)
                page.wait_for_function('window.lostContexts===1')
                for cycle in range(3):
                    held = []
                    page.route('**/api/material-discovery?**', lambda route: held.append(route), times=1)
                    with page.expect_response(lambda r: '/api/material-discovery?' in r.url and r.status == 200):
                        page.evaluate("window.controlledHidden=false;document.dispatchEvent(new Event('visibilitychange'))")
                        page.wait_for_timeout(150)
                        assert held, 'resume must reauthorize through the HTTP read'
                        expect(panel.locator('[data-material-timeline] canvas')).to_have_count(0)
                        held[0].fulfill(response=held[0].fetch())
                    expect(lens).to_be_visible()
                    assert same_scene(lens.screenshot(),before), 'visibility recovery changed rotated lens'
                    expect(panel.locator('.material-time-chart')).to_have_count(1)
                    if cycle < 2:
                        page.evaluate("window.controlledHidden=true;document.dispatchEvent(new Event('visibilitychange'))")
                        expect(panel.locator('[data-material-timeline] canvas')).to_have_count(0)
                checks.append('CONTROLLED DOM: hidden releases canvases and WebGL context; three authorized recoveries retain view without duplicate charts')
                panel.locator('[data-material-scene=country]').click()
                globe=panel.locator('[data-material-globe] canvas')
                expect(globe).to_be_visible();globe.scroll_into_view_if_needed();b=globe.bounding_box()
                page.mouse.move(b['x']+b['width']*.4,b['y']+b['height']*.4)
                page.mouse.down();page.mouse.move(b['x']+b['width']*.5,b['y']+b['height']*.6,steps=10);page.mouse.up()
                page.wait_for_timeout(100);before_globe=globe.screenshot()
                globe.evaluate("e=>{window.globeLost=0;e.addEventListener('webglcontextlost',()=>window.globeLost++)}")
                page.evaluate("window.controlledHidden=true;document.dispatchEvent(new Event('visibilitychange'))")
                expect(globe).to_have_count(0)
                page.wait_for_function('window.globeLost===1')
                page.evaluate("window.controlledHidden=false;document.dispatchEvent(new Event('visibilitychange'))")
                expect(globe).to_be_visible()
                assert same_scene(globe.screenshot(),before_globe), 'globe visibility recovery loses camera'
                panel.locator('[data-material-scene=time]').click()
                expect(lens).to_be_visible()
                checks.append('CONTROLLED DOM globe: real contextlost and removed canvas; authorized remount preserves rotated globe')

            if args.case in ('labels', 'all'):
                for width, height in [(1366,900), (390,844), (320,780)]:
                    page.set_viewport_size({'width':width,'height':height})
                    labels = panel.locator('.material-time-lens-label')
                    assert labels.count() >= 3, 'lens needs readable screen-size year/type labels'
                    assert labels.evaluate_all('es=>es.every(e=>parseFloat(getComputedStyle(e).fontSize)>=14)')
                    lens.scroll_into_view_if_needed()
                    page.screenshot(path=str(out/f'time-{width}-viewport.png'))
                checks.append('Lens year and type labels retain >=14 CSS pixels at 1366/390/320')

            if args.case in ('security', 'all'):
                page.set_viewport_size({'width':1366,'height':900})
                for status in (403, 404):
                    page.route('**/api/material-discovery?**', lambda route, request, status=status: route.fulfill(status=status, json={'error':'合成失权'}), times=1)
                    focus_refresh()
                    expect(panel.get_by_role('alert')).to_contain_text('无法读取')
                    expect(panel.locator('canvas')).to_have_count(0)
                    expect(panel.locator('[data-material-record]')).to_have_count(0)
                    panel.locator('[data-material-retry]').click()
                    expect(lens).to_be_visible()
                # A different real cookie-session actor cannot populate the old actor's view.
                def browser_login(username):
                    csrf = page.request.get(base+'api/session').json()['csrf']
                    assert page.request.post(base+'api/login', data={'username':username, 'password':'LocalDemo2026!'}, headers={'X-CSRF-Token':csrf}).ok
                browser_login('researcher')
                panel.locator('[data-material-retry]').click()
                expect(panel.get_by_role('alert')).to_contain_text('账号已切换')
                expect(panel.locator('canvas')).to_have_count(0)
                browser_login('colleague')
                panel.locator('[data-material-retry]').click()
                expect(lens).to_be_visible()
                checks.append('403/404 clear prior data/graphs, recovery reauthorizes; real cookie actor switch clears old actor representation')

            if args.case in ('network', 'all'):
                page.set_viewport_size({'width':1366,'height':900})
                page.goto(base+'#library?feed=all&q='+ids[0])
                page.locator('.library-row').first.get_by_role('button').first.click()
                explorer = page.locator('.library-reader [data-record-explore]')
                explorer.locator('summary').click()
                expect(explorer.locator('[data-network-viewport] canvas').first).to_be_visible()
                explorer.locator('[data-explore-mode=space]').click()
                graph = explorer.locator('[data-network-viewport] canvas')
                expect(graph).to_have_count(1)
                graph.scroll_into_view_if_needed()
                b = graph.bounding_box()
                page.mouse.move(b['x']+b['width']*.4,b['y']+b['height']*.45)
                page.mouse.down();page.mouse.move(b['x']+b['width']*.55,b['y']+b['height']*.6,steps=10);page.mouse.up()
                page.wait_for_timeout(150)
                before = graph.screenshot()
                page.evaluate("""()=>{window.controlledHidden=false;
                    Object.defineProperty(document,'hidden',{configurable:true,get:()=>window.controlledHidden});
                    window.networkLost=0;document.querySelector('[data-network-viewport] canvas').addEventListener('webglcontextlost',()=>window.networkLost++);
                    window.controlledHidden=true;document.dispatchEvent(new Event('visibilitychange'));}""")
                expect(graph).to_have_count(0)
                page.wait_for_function('window.networkLost===1')
                held = []
                page.route('**/api/records/'+ids[0],lambda route:held.append(route),times=1)
                page.evaluate("window.controlledHidden=false;document.dispatchEvent(new Event('visibilitychange'))")
                page.wait_for_timeout(150)
                assert held
                expect(graph).to_have_count(0)
                held[0].fulfill(response=held[0].fetch())
                expect(graph).to_have_count(1)
                assert same_scene(graph.screenshot(),before), 'authorized network remount loses rotated camera'
                checks.append('CONTROLLED DOM network: WebGL released, no remount before authenticated record reread, rotated view restored')
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        (out/'results.json').write_text(json.dumps({'checks':checks,'page_errors':errors,'base':base,
            'visibility_evidence':'controlled DOM component test; native OS visibility not claimed',
            'server_thread_closed':not thread.is_alive()}, ensure_ascii=False, indent=2), encoding='utf-8')
        data = (out/'data').resolve()
        assert data.parent == out and data.name == 'data'
        shutil.rmtree(data)


if __name__ == '__main__':
    main()
