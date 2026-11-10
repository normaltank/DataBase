"""Reported desk composition matrix: long synthetic originals, native zoom, no real data."""
import argparse,base64,json,os,subprocess,threading,uuid
from pathlib import Path
import sys
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from check_compilation_desk_browser import fixture,Quiet

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--evidence',type=Path,required=True);args=ap.parse_args();out=args.evidence.resolve();out.mkdir(parents=True,exist_ok=False)
    test,topics=fixture(out);tid=topics[1];m=next(m for m in test.board(tid)['materials'] if m['owner_id']=='colleague');ref=m['ref']
    assert test.decide(tid,m['versions'][0]['ref'],decision='approved',note='第二版已核对，保留此版审阅。').status_code==201
    original='合成 · 拉脱维亚研究编译稿\n\n'+('\n\n'.join(f'第{i}段：本段是明确标识的合成编译材料。它用于核对长稿开头是否能尽早阅读，以及版本切换、真实原件和审阅责任能否保持清楚。原始材料、处理方法与研究者解释分别保存。' for i in range(1,17)))
    r=test.call(f'/api/collaboration/topics/{tid}/handoffs',dict(stage='selection',token=test.board(tid,'colleague')['token'],request_id=uuid.uuid4().hex,material_ref=ref,title='合成 · 拉脱维亚研究编译稿',note='第3版合成长稿；不表示真实研究结论。'),'colleague',file=('合成长编译稿-v3.txt',original.encode()));assert r.status_code==201,r.json
    extension=out/'zoom-extension';extension.mkdir();(extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Isolated matrix zoom','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}));(extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
    server=make_server('127.0.0.1',0,test.app,threaded=True,request_handler=Quiet);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}';metrics=[];errors=[];head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch_persistent_context(str(out/'profile'),executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE',p.chromium.executable_path),headless=False,ignore_default_args=['--disable-extensions'],args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}'],viewport={'width':1440,'height':1000},device_scale_factor=1,reduced_motion='reduce')
            page=browser.pages[0];page.on('pageerror',lambda e:errors.append(str(e)));page.goto(base);page.get_by_role('button',name='研究员',exact=True).click()
            zoom=browser.service_workers[0] if browser.service_workers else browser.wait_for_event('serviceworker')
            def set_zoom(factor):
                zoom.evaluate('async ({url,factor})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,factor)}',{'url':base,'factor':factor})
                return zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));return chrome.tabs.getZoom(t.id)}',base)
            def capture(name,factor,probe=None):
                page.wait_for_timeout(180);path=out/(name+'.png')
                if factor==2:
                    cdp=browser.new_cdp_session(page);path.write_bytes(base64.b64decode(cdp.send('Page.captureScreenshot',{'format':'png','fromSurface':True,'captureBeyondViewport':False})['data']));cdp.detach()
                else:page.screenshot(path=str(path))
                size=Image.open(path).size;data=page.evaluate('({innerWidth,innerHeight,outerWidth,outerHeight,deviceScale:devicePixelRatio,documentWidth:document.documentElement.scrollWidth,scrollY,cssZoom:getComputedStyle(document.documentElement).zoom})');data.update(file=path.name,imageWidth=size[0],imageHeight=size[1],actualZoom=zoom.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));return chrome.tabs.getZoom(t.id)}',base),sourceHEAD=head)
                assert data['actualZoom']==factor and data['documentWidth']<=data['innerWidth']+2,data
                assert data['cssZoom'] in ('1','normal'),data
                if factor==1:assert size==(data['innerWidth'],data['innerHeight']),data
                if probe and probe.count():data['contentBounds']=probe.first.bounding_box()
                metrics.append(data)
            for width,height,factor in [(320,780,1),(390,844,1),(1280,900,1),(1440,1000,1),(1440,1000,2)]:
                page.set_viewport_size({'width':width,'height':height});assert set_zoom(factor)==factor;suffix=f'{width}-zoom{factor}'
                page.goto(base+f'/#collaboration?id={tid}&tab=selection');material=page.locator(f'[data-material-ref="{ref}"]');expect(page.locator('.desk-material-index')).to_be_visible()
                if page.locator('[data-desk-material-picker]').is_visible():page.locator('[data-desk-material-picker]').select_option(ref)
                else:page.locator(f'[data-desk-material="{ref}"]').click()
                expect(material.locator('[data-desk-preview]')).to_contain_text('第16段')
                expect(material.locator('.handoff-current-actions>h3')).to_contain_text('写入当前版 3')
                page.evaluate('scrollTo(0,0)');capture('long-desk-'+suffix,factor,material.locator('[data-desk-preview]'))
                if factor==2:
                    jump=material.get_by_role('button',name='阅读原件',exact=True);assert jump.bounding_box()['y']<page.evaluate('innerHeight')
                    jump.click();expect(material.locator('[data-desk-preview]')).to_be_focused();capture('long-desk-read-'+suffix,factor,material.locator('[data-desk-preview]'))
                material.locator('.handoff-track-details>summary').click();material.locator('.handoff-track-details').scroll_into_view_if_needed();capture('timeline-'+suffix,factor,material.locator('.handoff-lineage-tracks'))
                material.locator('.handoff-graph>summary').click();expect(material.locator('.react-flow__node')).to_have_count(5);expect(material.locator('[data-flow-status]')).to_have_text('');material.get_by_role('button',name='显示全图',exact=True).click();material.locator('.actual-flow').scroll_into_view_if_needed();page.wait_for_timeout(250);capture('graph-'+suffix,factor,material.locator('[data-flow-slot]'))
                groups=material.locator('.actual-flow').evaluate('e=>e._actualFlow.snapshot.groups')
                geometry=material.locator('.react-flow__node').evaluate_all('els=>Object.fromEntries(els.map(e=>[e.dataset.id,e.getBoundingClientRect().toJSON()]))')
                submissions=[]
                for group in groups:
                    submit=geometry[group['nodes'][0]];submissions.append(submit)
                    for rid in group['nodes'][1:]:
                        review=geometry[rid];assert abs(review['x']-submit['x'])<1 and review['y']>submit['y'],(group,geometry)
                narrow=material.locator('[data-flow-slot]').evaluate('e=>e.clientWidth<700')
                if narrow:
                    assert max(x['x'] for x in submissions)-min(x['x'] for x in submissions)<1
                    assert all(b['y']>a['y'] for a,b in zip(submissions,submissions[1:]))
                else:
                    assert max(x['y'] for x in submissions)-min(x['y'] for x in submissions)<1
                    assert all(b['x']>a['x'] for a,b in zip(submissions,submissions[1:]))
                assert material.locator('.react-flow__viewport').evaluate('e=>new DOMMatrix(getComputedStyle(e).transform).a')==1
                metrics[-1].update(versionGroups=groups,eventGeometry=geometry,versionAxis='vertical' if narrow else 'horizontal',defaultGraphScale=1)
                metrics[-1]['nodeFontSizes']=material.locator('.react-flow__node').evaluate_all('els=>els.map(e=>getComputedStyle(e).fontSize)')
                assert all(float(v.replace('px',''))>=14 for v in metrics[-1]['nodeFontSizes'])
                metrics[-1].update(nodeCount=material.locator('.react-flow__node').count(),flowStatus=material.locator('[data-flow-status]').inner_text(),allNodesInSlot=material.locator('[data-flow-slot]').evaluate('(s)=>{const b=s.getBoundingClientRect();return [...s.querySelectorAll(".react-flow__node")].every(n=>{const r=n.getBoundingClientRect();return r.left>=b.left-2&&r.right<=b.right+2&&r.top>=b.top-2&&r.bottom<=b.bottom+2})}'))
                page.goto(base+'/#library?feed=all');expect(page.locator('.library-row')).to_have_count(6)
                panel=page.locator('.material-discovery')
                if panel.get_attribute('open') is None:panel.locator('>summary').click()
                expect(panel.locator('[data-material-globe] canvas')).to_be_visible();page.evaluate('scrollTo(0,0)');capture('discovery-'+suffix,factor,panel.locator('[data-material-globe]'))
                canvas=panel.locator('[data-material-globe] canvas').element_handle()
                page.get_by_role('button',name='查看候选资料',exact=True).click();expect(page.locator('.library-results-area')).to_be_focused();capture('candidates-'+suffix,factor,page.locator('.library-row').first)
                page.get_by_role('button',name='返回图形探索',exact=True).click();assert canvas.evaluate('e=>e.isConnected')
                page.get_by_role('button',name='查看候选资料',exact=True).click()
                page.locator('.library-row .title-button').first.click();expect(page.locator('.library-reader .ux-main-body .rich-prose p').first).to_be_visible();page.evaluate('scrollTo(0,0)');capture('reader-'+suffix,factor,page.locator('.library-reader .ux-main-body .rich-prose p').first)
                assert page.get_by_role('button',name='返回探索与结果',exact=True).count()==1
                page.get_by_role('button',name='返回探索与结果',exact=True).click();assert '#library?feed=all' in page.url
                page.goto(base+'/#sources');page.locator('.workbench-source-row h2 a').last.click();expect(page.locator('.source-introduction .rich-prose')).to_be_visible();page.evaluate('scrollTo(0,0)');capture('source-'+suffix,factor,page.locator('.source-introduction .rich-prose'))
                page.goto(base+'/#people');page.locator('.workbench-person-row h2 a').first.click();expect(page.locator('#person-introduction')).to_be_visible();page.evaluate('scrollTo(0,0)');capture('person-'+suffix,factor,page.locator('.person-section .rich-prose'))
            assert not errors,errors
            browser.close()
    finally:server.shutdown();server.server_close()
    (out/'metrics.json').write_text(json.dumps({'sourceHEAD':head,'base':base,'worker':False,'paid_calls':0,'longOriginalParagraphs':16,'errors':errors,'screenshots':metrics},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'head':head,'screenshots':len(metrics),'evidence':str(out)},ensure_ascii=False))
if __name__=='__main__':main()
