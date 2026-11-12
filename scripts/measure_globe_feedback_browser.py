"""#149 local before/after lab sample; synthetic HTTP, real Chromium, no INP claim."""
import argparse
import json
import subprocess
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from check_globe_feedback_browser import ROOT, Quiet
from platform_app.web import create_app

PERF_PROBE=r"""(() => {
 const p=window.globeProbe;p.frames=[];p.longtasks=[];p.events=[];
 try{new PerformanceObserver(list=>p.longtasks.push(...list.getEntries().map(e=>({start:e.startTime,duration:e.duration})))).observe({type:'longtask',buffered:true})}catch{}
 try{new PerformanceObserver(list=>p.events.push(...list.getEntries().filter(e=>e.interactionId).map(e=>({name:e.name,start:e.startTime,duration:e.duration,processingDelay:e.processingStart-e.startTime,handler:e.processingEnd-e.processingStart,target:e.target?.textContent?.slice(0,50)})))).observe({type:'event',durationThreshold:16,buffered:true})}catch{}
 for(const name of ['WebGLRenderingContext','WebGL2RenderingContext']){
  const proto=window[name]?.prototype;if(!proto)continue;
  const clear=proto.clear;proto.clear=function(...args){if(this.canvas.matches('[data-material-globe] canvas'))p.frames.push({time:performance.now(),before:p.draws,last:performance.now()});return clear.apply(this,args)};
  for(const method of ['drawElements','drawArrays','drawElementsInstanced','drawArraysInstanced']){const original=proto[method];if(original)proto[method]=function(...args){const answer=original.apply(this,args);if(this.canvas.matches('[data-material-globe] canvas')&&p.frames.length){p.draws++;p.frames.at(-1).last=performance.now();}return answer}}
 }
})();"""

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--evidence',type=Path,required=True);args=parser.parse_args();out=args.evidence.resolve();out.mkdir(parents=True,exist_ok=False)
 app=create_app(out/'synthetic-data',testing=True,embedded_worker=False);client=app.test_client()
 def post(path,data):
  r=client.post(path,json=data,headers={'X-CSRF-Token':client.get('/api/session').json['csrf']});assert r.status_code in (200,201),r.json;return r.json
 post('/api/login',{'username':'admin','password':'LocalDemo2026!'})
 for country,count in [('Latvia',9),('Germany',6),('France',3)]:
  for i in range(count):post('/api/records',{'title':f'合成性能 {country} {i}','kind':'report','countries':country})
 server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
 result={'worker':False,'paid_calls':0,'viewport':[1440,960],'limits':'Single Windows/Chromium laboratory sample. GPU submission timing and scripted pointer cadence are not physical display latency, field INP or a universal frame-rate guarantee. Both runs use the same observer overhead.','runs':{}}
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True)
   for label in ['baseline','updated']:
    page=browser.new_page(viewport={'width':1440,'height':960},reduced_motion='no-preference');page.add_init_script('window.globeProbe={draws:0}');page.add_init_script(PERF_PROBE)
    baseline_requests=[]
    if label=='baseline':
     old=subprocess.check_output(['git','show','36deb96eec3a8a22d3a1e1cba88289d41389c731:static/vendor/visual/globe.js'],cwd=ROOT).decode('utf-8')
     def baseline(route):
      baseline_requests.append(route.request.url);route.fulfill(content_type='text/javascript',body=old)
     page.route('**/static/vendor/visual/globe.js*',baseline)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(base+'/#library?feed=all&q=合成性能');page.get_by_role('button',name='研究员',exact=True).click();canvas=page.locator('[data-material-globe] canvas')
    try:expect(canvas).to_be_visible(timeout=15000)
    except Exception:
     page.screenshot(path=str(out/(label+'-failed.png')));(out/(label+'-failed.txt')).write_text(json.dumps({'errors':errors,'url':page.url,'body':page.locator('body').inner_text()},ensure_ascii=False,indent=2),encoding='utf-8');raise
    canvas.scroll_into_view_if_needed();page.wait_for_timeout(500)
    assert label!='baseline' or baseline_requests,'Baseline bundle route was never used'
    visibility=page.evaluate("async()=>{const s=await(await fetch('/api/session')).json(),d=await(await fetch('/api/material-discovery?feed=all&q=合成性能')).json();return {user:s.user?.username,total:d.country_context?.total??d.total}}")
    assert visibility['user']=='researcher' and visibility['total']==18,visibility
    renderer=canvas.evaluate("e=>{const gl=e.getContext('webgl2'),ext=gl.getExtension('WEBGL_debug_renderer_info');return {version:gl.getParameter(gl.VERSION),renderer:gl.getParameter(ext?ext.UNMASKED_RENDERER_WEBGL:gl.RENDERER)}}")
    box=canvas.bounding_box();x,y=box['x']+box['width']/2,box['y']+box['height']/2
    cdp=page.context.new_cdp_session(page);cdp.send('Profiler.enable');cdp.send('Profiler.start')
    page.evaluate('window.globeProbe.frames=[];window.globeProbe.longtasks=[];window.globeProbe.events=[];window.globeProbe.start=performance.now()')
    page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+150,y+25,steps=24);page.mouse.move(x+35,y-20,steps=24);page.mouse.up();page.wait_for_timeout(500)
    measured=page.evaluate('''()=>{const p=window.globeProbe;return {frames:p.frames.map((f,i)=>({time:f.time-p.start,draws:(p.frames[i+1]?.before??p.draws)-f.before,submission_ms:f.last-f.time})),longtasks:p.longtasks.filter(t=>t.start>=p.start),events:p.events}}''')
    page.locator('.material-country-list [data-material-country=LV]').click();page.wait_for_timeout(350)
    profile=cdp.send('Profiler.stop')['profile'];(out/(label+'.cpuprofile')).write_text(json.dumps(profile),encoding='utf-8')
    measured['click_events']=page.evaluate("window.globeProbe.events.filter(e=>e.name==='click'&&e.target?.includes('拉脱维亚'))")
    measured['visibility']=visibility;measured['renderer']=renderer;measured['baseline_bundle_requests']=baseline_requests
    page.screenshot(path=str(out/(label+'.png')));measured['errors']=errors
    result['runs'][label]=measured;page.close()
   result['browser']=browser.version;browser.close()
 finally:
  server.shutdown();server.server_close();thread.join(5);(out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
