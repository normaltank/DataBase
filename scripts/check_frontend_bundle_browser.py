"""#80: synthetic HTTP on an untrusted origin and actual Chrome UI/zoom.

Uses only a new temporary data directory and a dynamically allocated local port.
--check uuid or --check typography is also a focused red/green reproduction.
"""
import argparse
import base64
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from platform_app.web import create_app
from scripts.check_topic_finals_browser import serve
from scripts.check_collaboration_library_browser import login
from scripts.check_reader_maintenance_browser import account, call, check_source, check_admin, check_interfaces
from scripts.check_ui_clarity_browser import reading, topic, journal, capture


def uuid_upload(page, base, evidence):
    page.goto(base+'/#collaboration?business=journal')
    page.get_by_role('button', name='新建期刊工作', exact=True).click()
    page.get_by_label('已知刊名 *', exact=True).fill('HTTP 合成期刊交接')
    page.get_by_label('原刊卷期或覆盖范围 *', exact=True).fill('2026年第1期')
    page.get_by_role('button', name='保存期刊工作', exact=True).click()
    try:
        expect(page.get_by_label('期刊编译文件 *', exact=True)).to_be_visible(timeout=2500)
    except Exception:
        page.screenshot(path=str(evidence/'uuid-failure.png'))
        (evidence/'uuid-failure.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
        raise
    request_key = page.locator('[data-form=journal-upload]').get_attribute('data-request')
    import re
    assert re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', request_key)
    page.get_by_label('期刊编译文件 *', exact=True).set_input_files(
        {'name':'http-synthetic.txt','mimeType':'text/plain','buffer':b'HTTP synthetic original'})
    page.get_by_role('button', name='保存文件新版本', exact=True).click()
    expect(page.get_by_role('link', name='下载期刊原件 v1', exact=True)).to_be_visible()
    capture(page, evidence, 'http-uuid-upload')
    return {'uuid_v4':True,'http_upload':True}


def typography(page, base, evidence):
    page.goto(base+'/#library?feed=all')
    expect(page.locator('.reading-origin').first).to_be_visible()
    sizes=page.locator('.reading-origin').evaluate_all('(xs)=>xs.map(x=>parseFloat(getComputedStyle(x).fontSize))')
    page.screenshot(path=str(evidence/'reading-typography.png'))
    assert min(sizes)>=14, sizes
    return sizes


def shortcuts(page, base, evidence, suffix='focused', editable=True):
    page.goto(base+'/#library?feed=all&q=资料')
    titles=page.locator('.record-title button')
    expect(titles).to_have_count(2)
    first,second=titles.all_text_contents()
    titles.first.click()
    reader=page.locator('.library-reader')
    heading=reader.locator('.detail-title')
    expect(heading).to_have_text(first)
    page.keyboard.press('Alt+ArrowUp')
    expect(heading).to_have_text(first)
    assert page.locator('.reading-column-labels').is_hidden()
    capture(page,evidence,'reading-keyboard-'+suffix)
    page.keyboard.press('Alt+ArrowDown')
    expect(heading).to_have_text(second)
    page.keyboard.press('Alt+ArrowDown')
    expect(heading).to_have_text(second)
    page.keyboard.press('Alt+ArrowUp')
    expect(heading).to_have_text(first)
    page.keyboard.press('Alt+ArrowDown')
    expect(heading).to_have_text(second)
    # Filter inputs remain usable beside the reader at desktop width.
    if editable:
        page.get_by_label('资料关键词',exact=True).focus()
        page.keyboard.press('Alt+ArrowUp')
        try:
            expect(heading).to_have_text(second,timeout=1500)
        except Exception:
            page.screenshot(path=str(evidence/'shortcut-input-failure.png'))
            raise
    reader.get_by_role('button',name='加入资料夹',exact=True).click()
    expect(page.get_by_role('dialog',name='加入资料夹',exact=True)).to_be_visible()
    page.keyboard.press('Alt+ArrowUp')
    expect(heading).to_have_text(second)
    page.keyboard.press('Escape')
    reader.get_by_role('button',name='返回列表',exact=True).focus()
    page.keyboard.press('Alt+Shift+ArrowUp')
    expect(heading).to_have_text(second)
    page.keyboard.press('Alt+Control+ArrowUp')
    expect(heading).to_have_text(second)
    page.keyboard.press('Alt+ArrowUp')
    expect(heading).to_have_text(first)
    page.keyboard.press('Escape')
    expect(titles.first).to_be_focused()
    page.keyboard.press('Alt+ArrowDown')
    expect(reader).to_be_hidden()
    page.goto(base+'/#collaboration')
    expect(page.get_by_role('heading',name='编译协作',exact=True)).to_be_visible()
    page.keyboard.press('Alt+ArrowDown')
    expect(page.locator('.library-reader')).to_have_count(0)
    capture(page,evidence,'shortcuts-page-exit-'+suffix)
    return {'prev_next_and_boundaries':True,'input_ignored':editable,'modal_ignored':True,
        'extra_modifiers_ignored':True,'close_restores_focus':True,'page_exit_ignored':True}


def measure(page, evidence, name):
    """Audit rendered text styles and opaque ancestor backgrounds, not token pairs.

    This does not evaluate image/gradient backdrops or native popup menus.
    """
    capture(page,evidence,name)
    result=page.evaluate(r'''() => {
      const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number);
      const blend=(top,bottom)=>{const a=top[3]??1;return top.slice(0,3).map((v,i)=>v*a+bottom[i]*(1-a))};
      const luminance=c=>c.map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4}).reduce((a,x,i)=>a+x*[.2126,.7152,.0722][i],0);
      const samples=[],unsupported=[];
      for(const el of document.querySelectorAll('#content *,#modal-root *')){
        if(!el.checkVisibility()||el.closest('svg')||!Array.from(el.childNodes).some(n=>n.nodeType===3&&n.textContent.trim()))continue;
        const style=getComputedStyle(el), ancestors=[]; let node=el;
        while(node){ancestors.unshift(node);node=node.parentElement;}
        let bg=[255,255,255], supported=true;
        for(const ancestor of ancestors){const s=getComputedStyle(ancestor);if(s.backgroundImage!=='none'||s.opacity!=='1')supported=false;bg=blend(rgb(s.backgroundColor),bg);}
        if(!supported){unsupported.push(el.textContent.trim().slice(0,60));continue;}
        const color=blend(rgb(style.color),bg), l1=luminance(color),l2=luminance(bg);
        samples.push({text:el.textContent.trim().slice(0,70),px:parseFloat(style.fontSize),contrast:(Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05),fg:style.color,bg});
      }
      return {css_width:innerWidth,css_height:innerHeight,dpr:devicePixelRatio,
        scroll_width:document.documentElement.scrollWidth,client_width:document.documentElement.clientWidth,
        samples,unsupported};
    }''')
    (evidence/(name+'-metrics.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    assert result['scroll_width']<=result['client_width']+1, result
    assert result['samples'], name
    result['minimum_font_px']=min(x['px'] for x in result['samples'])
    result['minimum_text_contrast']=min(x['contrast'] for x in result['samples'])
    assert result['minimum_font_px']>=14, (name,[x for x in result['samples'] if x['px']<14])
    assert result['minimum_text_contrast']>=4.5, (name,[x for x in result['samples'] if x['contrast']<4.5])
    return result


def matrix(page,context,base,evidence,worker,downloads):
    # Qualification setup still crosses the public authenticated HTTP interface.
    admin=context.request
    account(admin,base,'admin')
    qualification=next(q for q in admin.get(base+'/api/collaboration/qualifications').json()['items'] if q['id']=='researcher')
    call(admin,base,'/api/collaboration/qualifications/researcher',{'version':qualification['version'],'enabled':True},method='PUT')
    call(admin,base,'/api/sources',{'name':'合成LIIA配置入口','kind':'think_tank','website':'https://www.liia.lv/en/'},expected=201)
    account(context,base,'researcher')
    call(context,base,'/api/records',{'title':'旧研究笔记合成回归','kind':'research_note',
        'body_html':'<p>合成旧笔记，仅验证现有入口。</p>','visibility':'shared','sharing_confirmed':True},expected=201)
    page.reload()  # Refresh the browser's CSRF value after API-side account switches.
    # The previous focused test intentionally leaves no reader open.
    results=[]
    for width,zoom in ((1366,1),(390,1),(320,1),(1366,2)):
        page.set_viewport_size({'width':width,'height':900})
        worker.evaluate('async ({url,zoom})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,zoom)}',{'url':base,'zoom':zoom})
        actual=worker.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));return chrome.tabs.getZoom(t.id)}',base)
        assert actual==zoom
        # Fresh login also drops cross-page personal continuity from the previous run.
        page.get_by_role('button',name='退出登录',exact=True).click()
        expect(page.get_by_label('账号',exact=True)).to_be_visible()
        login(page,base,'researcher')
        suffix=f'{width}-{zoom}'
        page.goto(base+'/#collaboration?q=合成不存在的工作')
        expect(page.get_by_role('heading',name='当前范围暂无工作',exact=True)).to_be_visible()
        samples={'work-empty':measure(page,evidence,'work-empty-'+suffix)}
        page.get_by_role('button',name='查看全部可读工作',exact=True).click()
        expect(page.get_by_role('button',name='全部可读',exact=True)).to_have_attribute('aria-pressed','true')
        result={'width':width,'actual_zoom':actual,'reading':reading(page,base,evidence,suffix)}
        page.goto(base+'/#library?feed=all')
        expect(page.locator('.library-row')).not_to_have_count(0)
        samples['list']=measure(page,evidence,'list-'+suffix)
        page.locator('.record-title button').first.click()
        expect(page.locator('.library-reader .detail-title')).to_be_visible()
        samples['reader']=measure(page,evidence,'reader-'+suffix)
        page.keyboard.press('Escape')
        page.get_by_text('整理与导出',exact=True).click()
        page.get_by_role('button',name='卡片视图',exact=True).click()
        assert page.locator('.reading-column-labels').is_hidden()
        page.get_by_role('button',name='紧凑列表',exact=True).click()
        result['topic']=topic(page,base,evidence,suffix)
        samples['topic']=measure(page,evidence,'topic-'+suffix)
        result['journal']=journal(page,base,evidence,suffix)
        samples['products']=measure(page,evidence,'products-measured-'+suffix)
        check_interfaces(page,base,downloads)
        sid,jid,_=check_source(page,base,suffix,evidence)
        samples['source']=measure(page,evidence,'source-profile-'+suffix)
        check_admin(page,base,'合成推荐智库 '+suffix,evidence,suffix)
        account(context,base,'admin');page.reload()
        for route,heading in [('maintenance-sources','来源维护'),('maintenance-ingestion','公开来源自动采集'),('maintenance-ai','AI 费用')]:
            page.goto(base+'/#'+route)
            expect(page.get_by_role('heading',name=heading,exact=True)).to_be_visible()
            samples[route]=measure(page,evidence,route+'-'+suffix)
        result.update(source={'institution':sid,'journal':jid,'failure_and_duplicate_preserved_input':True},metrics=samples)
        if zoom==2:
            physical=context.new_cdp_session(page).send('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
            (evidence/'200-percent-physical.png').write_bytes(base64.b64decode(physical['data']))
        page.goto(base+'/#collaboration')
        results.append(result)
        print(json.dumps({'completed':suffix}),flush=True)
    assert context.request.get(base+'/api/admin/ai').json()['attempts']==[]
    return results


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check', choices=['uuid','typography','shortcuts','all'], default='all')
    args=parser.parse_args()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    expect.set_options(timeout=10000)
    evidence=Path(tempfile.mkdtemp(prefix='database-frontend-bundle-80-'))
    (Path(tempfile.gettempdir())/'database-frontend-bundle-80-latest.txt').write_text(str(evidence), encoding='utf-8')
    print(json.dumps({'evidence':str(evidence),'check':args.check}), flush=True)
    app=create_app(evidence/'data', testing=True)
    # Only this isolated test accepts the synthetic DNS name; production hosts stay unchanged.
    app.config['TRUSTED_HOSTS']=['127.0.0.1','localhost','frontend-preview.test']
    server, thread, local=serve(app)
    base=local.replace('127.0.0.1','frontend-preview.test')
    results={}
    try:
        with sync_playwright() as p:
            executable=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or 'C:/Program Files/Google/Chrome/Application/chrome.exe'
            extension=evidence/'zoom-extension'; extension.mkdir()
            (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Synthetic browser zoom verifier','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
            (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
            profile=evidence/'profile'
            context=p.chromium.launch_persistent_context(str(profile), executable_path=executable,
                headless=False, ignore_default_args=['--disable-extensions'], args=['--headless=new',
                '--enable-unsafe-extension-debugging','--remote-debugging-port=0','--no-proxy-server',
                '--host-resolver-rules=MAP frontend-preview.test 127.0.0.1'],
                viewport={'width':1366,'height':900}, accept_downloads=True)
            port=(profile/'DevToolsActivePort').read_text().splitlines()[0]
            browser=p.chromium.connect_over_cdp('http://127.0.0.1:'+port)
            cdp=browser.new_browser_cdp_session()
            cdp.send('Extensions.loadUnpacked', {'path':str(extension)})
            worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            downloads=evidence/'downloads'; downloads.mkdir()
            cdp.send('Browser.setDownloadBehavior', {'behavior':'allow','downloadPath':str(downloads),'eventsEnabled':True})
            page=context.pages[0]
            page.set_default_timeout(8000)
            errors=[]; page.on('pageerror', lambda error:errors.append(str(error)))
            try:
                login(page, base, 'researcher')
            except Exception:
                page.screenshot(path=str(evidence/'login-failure.png'))
                print(json.dumps({'url':page.url,'body':page.locator('body').inner_text(),'errors':errors},ensure_ascii=False),flush=True)
                raise
            secure=page.evaluate('({secure:isSecureContext,random:typeof crypto.randomUUID,values:typeof crypto.getRandomValues})')
            assert secure['secure'] is False and secure['values']=='function', secure
            results['origin']=secure
            if args.check in ('uuid','all'):
                results['uuid']=uuid_upload(page,base,evidence)
            if args.check in ('typography','shortcuts','all'):
                # APIRequestContext has no browser host-resolver rules. Use loopback for the
                # remaining HTTP fixtures and UI checks, with a separate authenticated cookie.
                base=local
                login(page,base,'researcher')
                call(context,base,'/api/records',{'title':'可读资料合成：跨国来源与研究依据','kind':'report',
                    'chinese_title':'可读资料合成：跨国来源与研究依据' if args.check=='typography' else '',
                    'body_html':'<p>完全合成内容，仅验证界面。</p>','visibility':'shared','sharing_confirmed':True},expected=201)
                if args.check in ('shortcuts','all'):
                    call(context,base,'/api/records',{'title':'另一篇合成资料','kind':'report',
                        'body_html':'<p>第二篇完全合成内容。</p>','visibility':'restricted'},expected=201)
                    results['shortcuts']=shortcuts(page,base,evidence)
                if args.check in ('typography','all'):
                    results['origin_font_px']=typography(page,base,evidence)
                if args.check=='all':
                    results['matrix']=matrix(page,context,base,evidence,worker,downloads)
            assert not errors, errors
            revision=subprocess.run(['git','rev-parse','HEAD'],check=True,capture_output=True,text=True).stdout.strip()
            (evidence/'results.json').write_text(json.dumps({'source_commit':revision,'base':base,
                'browser':cdp.send('Browser.getVersion'),'results':results,'pageerrors':errors},ensure_ascii=False,indent=2), encoding='utf-8')
            context.close()
            print(json.dumps({'evidence':str(evidence),'checks':list(results),'matrix_scenarios':len(results.get('matrix',[]))},ensure_ascii=False),flush=True)
    finally:
        server.shutdown(); thread.join(timeout=5)


if __name__=='__main__':
    main()
