"""#149: synthetic HTTP + real Chromium/WebGL, no workers or paid calls."""
import argparse
import json
import math
import sys
import threading
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from platform_app.web import create_app

class Quiet(WSGIRequestHandler):
    def log_request(self, *args, **kwargs): pass

def projected(page, lon=24, lat=57, camera=None, radius=2.508):
    box = page.locator('[data-material-globe] canvas').bounding_box()
    camera = camera or [8.6*math.cos(math.radians(45))*math.sin(math.radians(22)),8.6*math.sin(math.radians(45)),8.6*math.cos(math.radians(45))*math.cos(math.radians(22))]
    length = math.sqrt(sum(v*v for v in camera)); forward=[v/length for v in camera]
    right=[forward[2],0,-forward[0]]; rl=math.sqrt(sum(v*v for v in right));right=[v/rl for v in right]
    up=[forward[1]*right[2]-forward[2]*right[1],forward[2]*right[0]-forward[0]*right[2],forward[0]*right[1]-forward[1]*right[0]]
    lon,lat=map(math.radians,(lon,lat)); point=[radius*math.cos(lat)*math.sin(lon),radius*math.sin(lat),radius*math.cos(lat)*math.cos(lon)]
    dot=lambda a,b:sum(x*y for x,y in zip(a,b))
    scale=box['height']/2/math.tan(math.radians(20))/(length-dot(point,forward))
    return box['x']+box['width']/2+dot(point,right)*scale,box['y']+box['height']/2-dot(point,up)*scale

# Observe the real browser/GPU boundary without shipping test hooks. The probe
# measures object-space vertex radii and the actual model-view scale used to draw
# curved tops/walls. It does not replace Three, geometry, controls or rendering.
GPU_PROBE = r"""(() => {
  const probe=window.globeProbe={draws:0,raf:0,pending:0,maxPending:0,capture:false,meshes:[],samples:[]};
  probe.violations=[];document.addEventListener('securitypolicyviolation',e=>probe.violations.push({directive:e.violatedDirective,blocked:e.blockedURI}));
  const raf=window.requestAnimationFrame.bind(window),cancel=window.cancelAnimationFrame.bind(window),pending=new Set();
  window.requestAnimationFrame=fn=>{const id=raf(t=>{pending.delete(id);probe.raf++;fn(t)});pending.add(id);probe.maxPending=Math.max(probe.maxPending,pending.size);return id};
  window.cancelAnimationFrame=id=>{pending.delete(id);cancel(id)};
  for(const name of ['WebGLRenderingContext','WebGL2RenderingContext']){
    const proto=window[name]?.prototype;if(!proto)continue;
    const buffers=new WeakMap(),locations=new WeakMap(),arrays=new WeakMap(),defaults=new Map(),programs=new WeakMap();let bound=null,program=null,vao=null;
    const attributes=()=>{if(!vao)return defaults;if(!arrays.has(vao))arrays.set(vao,new Map());return arrays.get(vao)};
    const wrap=(name,run)=>{const original=proto[name];if(original)proto[name]=function(...args){const result=original.apply(this,args);run.call(this,args,result);return result}};
    wrap('bindBuffer',function([target,buffer]){if(target===this.ARRAY_BUFFER)bound=buffer});
    wrap('bufferData',function([target,data]){
      if(target!==this.ARRAY_BUFFER||!bound||!(data instanceof Float32Array)||data.length%3)return;
      let min=Infinity,max=0;for(let i=0;i<data.length;i+=3){const r=Math.hypot(data[i],data[i+1],data[i+2]);min=Math.min(min,r);max=Math.max(max,r)}
      buffers.set(bound,{min,max,vertices:data.length/3});
    });
    wrap('bindVertexArray',function([value]){vao=value});
    wrap('getAttribLocation',function([p,name],index){let info=programs.get(p)||{};if(name==='position')info.position=index;programs.set(p,info)});
    wrap('getUniformLocation',function([p,name],location){if(location)locations.set(location,{p,name})});
    wrap('useProgram',function([p]){program=p});
    wrap('vertexAttribPointer',function([index,size]){attributes().set(index,{buffer:bound,size})});
    wrap('uniformMatrix4fv',function([loc,transpose,m]){const found=locations.get(loc);if(found?.name==='modelViewMatrix'){const info=programs.get(found.p)||{};info.scale=Math.hypot(m[0],m[1],m[2]);programs.set(found.p,info)}});
    for(const name of ['drawElements','drawArrays','drawElementsInstanced','drawArraysInstanced'])wrap(name,function(){
      if(!this.canvas.matches('[data-material-globe] canvas'))return;
      probe.draws++;
      if(probe.capture){const info=programs.get(program),attribute=attributes().get(info?.position),b=buffers.get(attribute?.buffer);
        if(b&&attribute.size===3&&b.min>2.45&&b.max<2.65)probe.meshes.push({...b,scale:info.scale,minWorld:b.min*info.scale,maxWorld:b.max*info.scale});}
    });
  }
})();"""

def camera(page):
    return page.locator('.material-discovery').evaluate('(e)=>e._globe.getViewState().position')

def settled(page, duration=350):
    page.wait_for_timeout(duration)

def retry_selected_country(page, out, result):
    """A recoverable HTTP failure must retain the selected country's feedback."""
    panel=page.locator('.material-discovery');status=panel.locator('[data-material-globe-status]')
    canvas=panel.locator('[data-material-globe] canvas')
    page.mouse.move(0,0)
    panel.locator('.material-country-list [data-material-country=LV]').click()
    expect(panel.locator('.material-scope')).to_contain_text('9 条')
    expect(panel).not_to_have_attribute('aria-busy','true')
    expect(status).to_contain_text('已选：拉脱维亚')
    canvas.focus();page.keyboard.press('ArrowLeft');settled(page)
    original_canvas=canvas.element_handle();original_camera=camera(page);selected_url=page.url
    assert 'country=LV' in selected_url
    page.route('**/api/material-discovery?**',lambda route:route.fulfill(status=503,json={'error':'合成分布读取失败'}),times=1)
    with page.expect_response(lambda r:'/api/material-discovery?' in r.url and r.status==503):
        panel.locator('[data-material-retry]').click()
    expect(status).to_contain_text('读取失败，保留上次分布与输入')
    expect(panel).not_to_have_attribute('aria-busy','true')
    page.screenshot(path=str(out/'retry-failed-read.png'))
    with page.expect_response(lambda r:'/api/material-discovery?' in r.url and r.status==200):
        panel.locator('[data-material-retry]').click()
    expect(panel).not_to_have_attribute('aria-busy','true')
    result['retry_recovery']={'url':page.url,'status':status.inner_text(),
        'selected':panel.locator('.material-country-list [aria-pressed=true]').evaluate_all('(items)=>items.map(e=>e.dataset.materialCountry)'),
        'same_canvas':original_canvas.evaluate('(e)=>e===document.querySelector("[data-material-globe] canvas")'),
        'camera_before':original_camera,'camera_after':camera(page),'http_statuses':[503,200]}
    page.screenshot(path=str(out/'retry-recovered.png'))
    assert page.url==selected_url
    expect(panel.locator('.material-country-list [aria-pressed=true]')).to_have_count(1)
    expect(panel.locator('.material-country-list [data-material-country=LV]')).to_have_attribute('aria-pressed','true')
    assert result['retry_recovery']['same_canvas'] and camera(page)==original_camera
    expect(status).to_contain_text('已选：拉脱维亚')
    expect(status).not_to_contain_text('读取失败')
    result['checks'].append('Selected LV survives HTTP 503 then successful retry: status, button and URL agree; same canvas and rotated camera')
    panel.locator('[data-material-clear=country]').click()
    expect(panel).not_to_have_attribute('aria-busy','true')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--case',choices=['return','raised','retry','all'],default='all')
    args=parser.parse_args();out=args.evidence.resolve();out.mkdir(parents=True,exist_ok=False)
    app=create_app(out/'synthetic-data',testing=True,embedded_worker=False);client=app.test_client()
    def post(path, data):
        response=client.post(path,json=data,headers={'X-CSRF-Token':client.get('/api/session').json['csrf']})
        assert response.status_code in (200,201), response.json
        return response.json
    post('/api/login',{'username':'admin','password':'LocalDemo2026!'})
    source=post('/api/sources',{'name':'合成浮雕来源','kind':'institution','country':'Latvia'})['id']
    for country, count in [('Latvia',9),('Germany',6),('France',3),('United States',2),('Russia',1),('Japan',1)]:
        for i in range(count):post('/api/records',{'title':f'合成浮雕 {country} {i}','kind':'report','source_id':source,'countries':country,'published_on':'2022','body_html':'<p>完全合成的地球验收资料。</p>'})
    server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    result={'base':f'http://127.0.0.1:{server.server_port}','worker':False,'paid_calls':0,'checks':[]};errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1440,'height':960},reduced_motion='no-preference')
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.add_init_script(GPU_PROBE)
            page.goto(result['base']+'/#library?feed=all&q=合成浮雕');page.get_by_role('button',name='研究员',exact=True).click()
            canvas=page.locator('[data-material-globe] canvas');expect(canvas).to_be_visible();canvas.scroll_into_view_if_needed()
            page.screenshot(path=str(out/'desktop-initial.png'))
            if args.case in ('retry','all'):
                retry_selected_country(page,out,result)
                if args.case=='retry':
                    result['csp_violations']=page.evaluate('window.globeProbe.violations')
                    assert not result['csp_violations'] and not errors,(result['csp_violations'],errors)
                    browser.close();return
                page.locator('[data-material-view=europe]').click();settled(page)
            x,y=projected(page);before=page.url
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+60,y,steps=8);page.mouse.move(x,y,steps=8);page.mouse.up()
            page.wait_for_timeout(350)
            result['return_drag']={'before':before,'after':page.url}
            assert page.url==before,'A drag that returns to its start selected a country'
            result['checks'].append('Dragging past the threshold and back does not select a country')
            if args.case=='return':browser.close();return
            panel=page.locator('.material-discovery');status=panel.locator('[data-material-globe-status]')
            # The visible raised top and the base sphere project differently.
            # Use an independently fixed LV interior/near-north-edge coordinate
            # from the supplied map, including an oblique view. A multi-select
            # tap must remove LV instead of adding its neighbor Estonia.
            for name,lon,lat,oblique in [('center',25.5,56.8,False),('coast-edge',24,57,False),('north-edge',24.75,57.87,False),('oblique-edge',24.75,57.87,True)]:
                panel.locator('[data-material-view=europe]').click()
                panel.locator('.material-country-list [data-material-country=LV]').click()
                panel.locator('[data-material-country-multi]').check();canvas.scroll_into_view_if_needed()
                if oblique:canvas.focus();page.keyboard.press('ArrowLeft');page.keyboard.press('ArrowLeft')
                settled(page);x,y=projected(page,lon,lat,camera(page),radius=2.575)
                canvas.screenshot(path=str(out/('raised-pick-'+name+'.png')))
                page.mouse.click(x,y)
                expect(panel.locator('.material-country-list [data-material-country=LV]')).to_have_attribute('aria-pressed','false')
                assert 'country=' not in page.url,('Raised top selected a neighbor',name,page.url)
                panel.locator('[data-material-country-multi]').uncheck()
            panel.locator('[data-material-view=europe]').click()
            panel.locator('.material-country-list [data-material-country=US]').click()
            panel.locator('[data-material-country-multi]').check();canvas.scroll_into_view_if_needed();settled(page)
            x,y=projected(page,-120,37,camera(page),radius=2.575);page.mouse.click(x,y)
            expect(panel.locator('.material-country-list [data-material-country=US]')).to_have_attribute('aria-pressed','true')
            panel.locator('[data-material-clear=country]').click();panel.locator('[data-material-country-multi]').uncheck()
            result['checks'].append('Raised LV top center/north edge/oblique edge hit the visible country and toggle it off without selecting a neighbor')
            result['checks'].append('A raised country on the far side stays occluded when clicking its projected coordinates')
            if args.case=='raised':browser.close();return
            panel.locator('[data-material-view=europe]').click();settled(page)
            canvas.scroll_into_view_if_needed();original_canvas=canvas.element_handle();start_camera=camera(page)
            # Hover without selecting; zero-data countries remain discoverable.
            x,y=projected(page,19,52);page.mouse.move(x,y)
            expect(status).to_contain_text('预览：波兰');expect(status).to_contain_text('暂无资料')
            assert 'country=' not in page.url
            page.screenshot(path=str(out/'desktop-hover-no-data.png'))
            # Hold both relevant public HTTP reads. Selection and geometry must
            # be visibly updated before either request has returned.
            held=[]
            def hold(route):held.append(route)
            page.route('**/api/material-discovery?**country=LV*',hold)
            page.route('**/api/records?**country=LV*',hold)
            page.mouse.move(0,0)
            page.evaluate('window.globeProbe.capture=true;window.globeProbe.meshes=[]')
            before_click=page.evaluate('performance.now()')
            panel.locator('.material-country-list [data-material-country=LV]').focus();page.keyboard.press('Enter')
            expect(status).to_contain_text('已选：拉脱维亚')
            for _ in range(40):
                if page.evaluate('window.globeProbe.meshes.some(m=>m.minWorld>2.56&&m.maxWorld<2.59)'):break
                page.wait_for_timeout(50)
            result['mesh_probe']=page.evaluate('({meshes:window.globeProbe.meshes,draws:window.globeProbe.draws})')
            assert page.evaluate('window.globeProbe.meshes.some(m=>m.minWorld>2.56&&m.maxWorld<2.59)'),result['mesh_probe']
            result['lab_feedback_ms']=page.evaluate('performance.now()')-before_click
            assert held,'Slow-response condition was not exercised'
            meshes=page.evaluate('window.globeProbe.meshes');page.evaluate('window.globeProbe.capture=false')
            tops=[m for m in meshes if m['minWorld']>2.56 and m['maxWorld']<2.59]
            sides=[m for m in meshes if 2.50<m['minWorld']<2.52 and 2.56<m['maxWorld']<2.59]
            assert tops and sides, meshes
            result['geometry']={'selected_top':tops[0],'side_wall':sides[0],'height':tops[0]['maxWorld']-2.508,'lift_ratio':(tops[0]['maxWorld']-2.508)/2.508}
            assert camera(page)==start_camera and original_canvas.evaluate('(e)=>e.isConnected')
            page.screenshot(path=str(out/'desktop-selected-latvia.png'));canvas.screenshot(path=str(out/'globe-selected-latvia.png'))
            # A newer selection must win over both late responses.
            panel.locator('.material-country-list [data-material-country=DE]').click()
            expect(panel.locator('.material-scope')).to_contain_text('6 条')
            for route in held:route.fulfill(response=route.fetch())
            page.unroute('**/api/material-discovery?**country=LV*',hold);page.unroute('**/api/records?**country=LV*',hold)
            expect(status).to_contain_text('已选：德国');expect(panel.locator('.material-country-list [data-material-country=DE]')).to_have_attribute('aria-pressed','true')
            assert camera(page)==start_camera and original_canvas.evaluate('(e)=>e.isConnected')
            result['checks'].append('Immediate real raised top + side walls while HTTP waits; newer DE survives late LV; same camera/canvas')
            # Public query supports multiple selected countries, preserving that
            # shape without adding a new query or permission protocol.
            panel.locator('[data-material-clear=country]').click()
            panel.locator('[data-material-country-multi]').check()
            panel.locator('.material-country-list [data-material-country=LV]').click()
            panel.locator('.material-country-list [data-material-country=DE]').click()
            expect(status).to_contain_text('拉脱维亚、德国');expect(panel.locator('.material-country-list [aria-pressed=true]')).to_have_count(2)
            panel.locator('[data-material-clear=country]').click();panel.locator('[data-material-country-multi]').uncheck();expect(status).to_contain_text('拖动旋转')
            settled(page);page.evaluate('window.globeProbe.meshes=[];window.globeProbe.capture=true');panel.locator('[data-material-globe-zoom="1"]').click();settled(page)
            assert not page.evaluate('window.globeProbe.meshes.some(m=>m.minWorld>2.56&&m.maxWorld<2.59)'), 'Old selected top remained raised'
            page.evaluate('window.globeProbe.capture=false')
            result['checks'].append('Multi-country query raises both; clearing removes relief')
            # Default and close views, then an oblique view. No automatic flight.
            panel.locator('[data-material-view=europe]').click();panel.locator('.material-country-list [data-material-country=LV]').click()
            for _ in range(3):panel.locator('[data-material-globe-zoom="1"]').click()
            canvas.focus();page.keyboard.press('ArrowLeft');page.keyboard.press('ArrowLeft');settled(page)
            canvas.screenshot(path=str(out/'globe-selected-oblique.png'))
            panel.locator('.material-country-list [data-material-country=FR]').click();settled(page)
            canvas.screenshot(path=str(out/'globe-france-islands.png'))
            panel.locator('.material-country-list [data-material-country=RU]').click();panel.locator('[data-material-view=world]').click();settled(page)
            canvas.screenshot(path=str(out/'globe-russia-world.png'))
            # Wheel, keyboard and button zoom all obey bounds.
            canvas.focus();page.keyboard.press('Home')
            for _ in range(20):page.keyboard.press('+')
            near=math.sqrt(sum(v*v for v in camera(page)));assert 3.39<=near<=3.41,near
            for _ in range(40):page.keyboard.press('-')
            far=math.sqrt(sum(v*v for v in camera(page)));assert 14.99<=far<=15.01,far
            canvas.hover();page.mouse.wheel(0,-100000);settled(page);wheel_near=math.sqrt(sum(v*v for v in camera(page)));assert wheel_near>=3.39,wheel_near
            page.mouse.wheel(0,100000);settled(page);wheel_far=math.sqrt(sum(v*v for v in camera(page)));assert wheel_far<=15.01,wheel_far
            result['zoom_bounds']={'keyboard_near':near,'keyboard_far':far,'wheel_near':wheel_near,'wheel_far':wheel_far}
            panel.locator('[data-material-view=europe]').click();panel.locator('[data-material-clear=country]').click();settled(page)
            # Direct trajectory while held, then short inertia and interruption.
            canvas.scroll_into_view_if_needed();box=canvas.bounding_box();x,y=box['x']+box['width']/2,box['y']+box['height']/2
            page.mouse.move(x,y);page.mouse.down();a=camera(page)
            page.mouse.move(x+35,y,steps=3);b=camera(page);page.mouse.move(x+70,y,steps=3);c=camera(page)
            assert a!=b and b!=c,'Drag camera did not follow held input'
            settled(page,80);assert camera(page)==c,'Held pointer continued drifting without input'
            page.mouse.up();settled(page,100);assert camera(page)==c,'A stationary held release started inertia'
            page.evaluate('''()=>{window.globeProbe.releaseInputs=[];for(const name of ['pointermove','pointerup'])document.addEventListener(name,e=>{if(e.target.tagName==='CANVAS')window.globeProbe.releaseInputs.push({name:e.type,input:e.timeStamp,handled:performance.now()})},true)}''')
            page.evaluate('''()=>{document.addEventListener('pointerup',function capture(e){
              if(e.target.tagName!=='CANVAS')return;
              document.removeEventListener('pointerup',capture,true);
              const start=performance.now(),panel=document.querySelector('.material-discovery');
              const trail=window.globeProbe.trail=[{ms:0,camera:panel._globe.getViewState().position}];
              function sample(){trail.push({ms:performance.now()-start,camera:panel._globe.getViewState().position});if(performance.now()-start<400)requestAnimationFrame(sample)}
              requestAnimationFrame(sample);
            },true)}''')
            # Script a known quick native release. Awaiting Playwright mouse
            # commands can itself exceed the 70ms release window on software
            # rendering; explicit CDP event timestamps separate input cadence
            # from that driver delay without changing the product threshold.
            mouse_cdp=page.context.new_cdp_session(page);stamp=time.time()
            mouse_cdp.send('Input.dispatchMouseEvent',{'type':'mousePressed','x':x+70,'y':y,'button':'left','buttons':1,'clickCount':1,'timestamp':stamp})
            for i,dx in enumerate([80,90,100],1):mouse_cdp.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x+dx,'y':y,'buttons':1,'timestamp':stamp+i*.016})
            mouse_cdp.send('Input.dispatchMouseEvent',{'type':'mouseReleased','x':x+100,'y':y,'button':'left','buttons':0,'clickCount':1,'timestamp':stamp+.064});settled(page,500)
            inputs=page.evaluate('window.globeProbe.releaseInputs');trail=page.evaluate('window.globeProbe.trail')
            gap=inputs[-1]['input']-inputs[-2]['input'];assert 15<=gap<=17,('Quick-release fixture cadence was not delivered',inputs)
            result['inertia']={'samples':trail,'inputs':inputs,'release_input_gap_ms':gap,'capture':'in-page rAF after trusted Chromium CDP pointerup; scripted 16ms input timestamps, not physical-device latency'}
            assert len({tuple(sample['camera']) for sample in trail})>1,'Release inertia did not run'
            assert trail[-1]['camera']==trail[-2]['camera'],'Release inertia did not converge'
            last_change=max(b['ms'] for a,b in zip(trail,trail[1:]) if a['camera']!=b['camera'])
            result['inertia']['last_change_ms']=last_change
            assert last_change<=315,'Release inertia exceeded the agreed laboratory stopping window'
            before=page.url
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(x-65,y,steps=4);page.mouse.up();settled(page,20)
            page.mouse.down();interrupted=camera(page);settled(page,150);assert camera(page)==interrupted,'New input did not stop inertia';page.mouse.up()
            # Secondary mouse buttons, lost capture, cancellation and dragging
            # outside never submit selection or leave an active gesture.
            panel.locator('[data-material-view=europe]').click();canvas.scroll_into_view_if_needed();x,y=projected(page)
            page.mouse.click(x,y,button='right');page.mouse.click(x,y,button='middle');assert page.url==before
            page.mouse.move(x,y);page.mouse.down();canvas.evaluate('(e)=>e.releasePointerCapture(1)');settled(page,30);page.mouse.up();assert page.url==before
            canvas.focus();page.keyboard.press('Home')
            # Cancel and drag-out never submit selection and never stick.
            page.mouse.down();canvas.dispatch_event('pointercancel',{'pointerId':1,'pointerType':'mouse'});page.mouse.up();assert page.url==before
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(box['x']-20,y,steps=5);page.mouse.up();settled(page);assert page.url==before
            still=camera(page);page.mouse.move(x,y);settled(page,100);assert camera(page)==still
            result['checks'].append('Held drag follows immediately; <=315ms release convergence; new input stops; cancel and outside release do not select or stick')
            # Reduced motion both on a running instance and on first load.
            page.emulate_media(reduced_motion='reduce');panel.locator('[data-material-view=europe]').click()
            canvas.focus();page.keyboard.press('ArrowRight');key_camera=camera(page);settled(page,100);assert camera(page)==key_camera
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+70,y,steps=4);page.mouse.up();reduced=camera(page);settled(page,300);assert camera(page)==reduced
            panel.locator('.material-country-list [data-material-country=LV]').click();expect(status).to_contain_text('已选：拉脱维亚');settled(page)
            settled(page);idle=page.evaluate('window.globeProbe.draws');settled(page,3000);assert page.evaluate('window.globeProbe.draws')==idle,'Idle globe kept drawing'
            canvas.focus();page.keyboard.press('+');settled(page);assert page.evaluate('window.globeProbe.draws')>idle
            idle=page.evaluate('window.globeProbe.draws');settled(page,3000);assert page.evaluate('window.globeProbe.draws')==idle
            result['idle']={'duration_ms':3000,'new_gpu_draws':0,'raf_max_pending':page.evaluate('window.globeProbe.maxPending')}
            result['checks'].append('Live reduced-motion removes tails and keeps selected relief; idle GPU draws zero for 3s, resumes and stops again')
            # Real Chromium touch events on a 390px viewport, not mouse emulation.
            mobile=browser.new_page(viewport={'width':390,'height':844},has_touch=True,is_mobile=True,reduced_motion='reduce')
            mobile.on('pageerror',lambda e:errors.append(str(e)));mobile.add_init_script(GPU_PROBE)
            mobile.goto(result['base']+'/#library?feed=all&q=合成浮雕');mobile.get_by_role('button',name='研究员',exact=True).click()
            mobile.locator('.material-discovery>summary').click();mc=mobile.locator('[data-material-globe] canvas');expect(mc).to_be_visible();mc.scroll_into_view_if_needed()
            mobile.locator('.material-country-list [data-material-country=LV]').focus();mobile.keyboard.press('Enter');expect(mobile.locator('[data-material-globe-status]')).to_contain_text('已选：拉脱维亚')
            mc.scroll_into_view_if_needed();settled(mobile);mobile.screenshot(path=str(out/'390-selected.png'));mc.screenshot(path=str(out/'390-globe-selected.png'))
            mp=mobile.locator('.material-discovery');mp.locator('[data-material-clear=country]').click();mc.scroll_into_view_if_needed();settled(mobile)
            box=mc.bounding_box();x,y=projected(mobile);cdp=mobile.context.new_cdp_session(mobile)
            touch=lambda kind,points:cdp.send('Input.dispatchTouchEvent',{'type':kind,'touchPoints':[{'x':px,'y':py,'id':pid} for px,py,pid in points]})
            before=mobile.url;touch('touchStart',[(x,y,1)]);touch('touchMove',[(x+45,y,1)]);touch('touchMove',[(x,y,1)]);touch('touchEnd',[]);settled(mobile);assert mobile.url==before
            mp.locator('[data-material-view=europe]').click();mc.scroll_into_view_if_needed();x,y=projected(mobile)
            touch('touchStart',[(x,y,1)]);touch('touchStart',[(x,y,1),(x+25,y+20,2)]);touch('touchMove',[(x-15,y,1),(x+45,y+20,2)]);touch('touchEnd',[]);settled(mobile);assert mobile.url==before
            touch('touchStart',[(x,y,1)]);touch('touchCancel',[]);settled(mobile);assert mobile.url==before
            mp.locator('[data-material-view=europe]').click();mc.scroll_into_view_if_needed();x,y=projected(mobile);touch('touchStart',[(x,y,1)]);touch('touchEnd',[])
            expect(mobile.locator('[data-material-globe-status]')).to_contain_text('已选：拉脱维亚')
            assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            result['checks'].append('390px: keyboard selection, genuine Chromium CDP touch tap/drag-return/two-finger pinch/cancel; no overflow')
            result['touch_limitation']='Chromium simulated touch, not a physical touch screen'
            result['csp_violations']=page.evaluate('window.globeProbe.violations')+mobile.evaluate('window.globeProbe.violations')
            assert not result['csp_violations'],result['csp_violations']
            # Disposal: no canvas left and no queued work after scene removal.
            page.goto(result['base']+'/#sources');expect(canvas).to_have_count(0);settled(page)
            idle=page.evaluate('window.globeProbe.draws');settled(page,350);assert page.evaluate('window.globeProbe.draws')==idle
            result['checks'].append('Route disposal removes canvas and stops GPU work')
            mobile.close();browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(5);result['errors']=errors;(out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    assert not errors, errors
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
