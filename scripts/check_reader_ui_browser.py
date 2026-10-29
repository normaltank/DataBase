"""#83 public browser checks, using only disposable synthetic data and ports."""
import argparse
import base64
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import subprocess
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from platform_app.web import create_app
from scripts.check_topic_finals_browser import serve
from scripts.check_collaboration_library_browser import login
from scripts.check_reader_maintenance_browser import call, account
from scripts.check_frontend_bundle_browser import measure as base_measure, matrix as legacy_matrix


def measure(page,evidence,name):
    result=base_measure(page,evidence,name)
    # Font size remains measurable even where backdrop contrast is unsupported.
    sizes=page.locator('#content *,#modal-root *').evaluate_all('''xs=>xs.filter(x=>x.checkVisibility()&&!x.closest('svg')&&[...x.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())).map(x=>parseFloat(getComputedStyle(x).fontSize))''')
    result['minimum_all_visible_font_px']=min(sizes)
    assert min(sizes)>=14,(name,min(sizes))
    return result


def open_first(page, base):
    page.goto(base+'/#library?feed=all')
    page.locator('.record-title button').first.click()
    expect(page.locator('.library-reader .ux-reading-article')).to_be_visible()
    return page.locator('.library-reader')


def preferences(page, base):
    reader=open_first(page,base)
    larger=reader.get_by_role('button',name='放大阅读字号',exact=True)
    smaller=reader.get_by_role('button',name='缩小阅读字号',exact=True)
    prose=reader.locator('.ux-main-body .rich-prose')
    expect(larger).to_be_visible()
    assert prose.evaluate('(x)=>getComputedStyle(x).fontSize')=='17px'
    larger.click()
    expect(prose).to_have_css('font-size','19px')
    larger.click()
    expect(prose).to_have_css('font-size','21px')
    expect(larger).to_be_disabled()
    reader.get_by_role('button',name='切换学术衬线体',exact=True).click()
    assert 'Georgia' in prose.evaluate('(x)=>getComputedStyle(x).fontFamily')
    page.reload();reader=open_first(page,base)
    assert reader.locator('.ux-main-body .rich-prose').evaluate('(x)=>getComputedStyle(x).fontSize')=='21px'
    for _ in range(2):reader.get_by_role('button',name='缩小阅读字号',exact=True).click()
    expect(reader.get_by_role('button',name='缩小阅读字号',exact=True)).to_be_disabled()
    for malformed in ['null','[]','{"scale":"invalid","serif":"false"}','{broken']:
        page.evaluate('(raw)=>localStorage.setItem("zhihui_reader_prefs",raw)',malformed)
        page.reload();reader=open_first(page,base)
        expect(reader.locator('.ux-main-body .rich-prose')).to_have_css('font-size','17px')
        expect(reader.get_by_role('button',name='切换学术衬线体',exact=True)).to_have_attribute('aria-pressed','false')
    return {'sizes':[17,19,21],'reload':True,'serif':True,'malformed_storage':True}


def storage(page, base):
    sid=call(page.context,base,'/api/sources',{'name':'禁用存储合成来源','kind':'think_tank','website':'https://example.org/synthetic'},expected=201)['id']
    page.add_init_script("""const originalGet=Storage.prototype.getItem,originalSet=Storage.prototype.setItem;
      Storage.prototype.getItem=function(key){if(this===sessionStorage||key==='zhihui_reader_prefs')throw new DOMException('blocked','SecurityError');return originalGet.call(this,key)};
      Storage.prototype.setItem=function(key,value){if(this===sessionStorage||key==='zhihui_reader_prefs')throw new DOMException('blocked','SecurityError');return originalSet.call(this,key,value)};""")
    page.reload()
    reader=open_first(page,base)
    reader.get_by_role('button',name='放大阅读字号',exact=True).click()
    expect(reader.locator('.ux-main-body .rich-prose')).to_have_css('font-size','19px')
    page.keyboard.press('Escape')
    page.goto(base+'/#sources')
    expect(page.get_by_role('heading',name='来源目录',exact=True)).to_be_visible()
    page.goto(base+'/#sources?id='+sid)
    expect(page.get_by_role('heading',name='禁用存储合成来源',exact=True)).to_be_visible()
    page.get_by_role('link',name='← 返回来源目录',exact=True).click()
    expect(page.get_by_role('heading',name='来源目录',exact=True)).to_be_visible()
    return {'disabled_storage_reading_and_change':True,'source_return':True}


def shortcuts(page, base):
    page.goto(base+'/#library?feed=all')
    search=page.get_by_label('资料关键词',exact=True)
    page.get_by_role('heading',name='资料',exact=True).click()
    page.keyboard.press('/')
    expect(search).to_be_focused()
    search.fill('unchanged')
    page.keyboard.press('Control+k')
    page.keyboard.type('x')
    expect(search).to_have_value('unchangedx')
    search.fill('')
    page.get_by_role('heading',name='资料',exact=True).click()
    page.keyboard.press('Control+k')
    expect(search).to_be_focused()
    page.keyboard.press('Tab')
    focus=page.locator(':focus')
    before=focus.evaluate('(x)=>x.outerHTML')
    page.keyboard.press('Control+Shift+k')
    assert page.locator(':focus').evaluate('(x)=>x.outerHTML')==before
    reader=open_first(page,base)
    heading=reader.locator('.detail-title');first=heading.inner_text()
    page.keyboard.press('j')
    expect(heading).not_to_have_text(first)
    second=heading.inner_text()
    page.keyboard.press('k')
    expect(heading).to_have_text(first)
    page.keyboard.press('Shift+j')
    expect(heading).to_have_text(first)
    page.keyboard.press('Control+Escape')
    expect(heading).to_have_text(first)
    reader.get_by_role('button',name='返回列表',exact=True).dispatch_event('keydown',{'key':'j','isComposing':True,'bubbles':True})
    expect(heading).to_have_text(first)
    search.focus();page.keyboard.press('j')
    expect(search).to_have_value('j');expect(heading).to_have_text(first)
    page.keyboard.press('Escape');expect(heading).to_have_text(first)
    search.fill('')
    reader.get_by_role('button',name='加入资料夹',exact=True).click()
    page.keyboard.press('j');page.keyboard.press('Control+k')
    expect(page.get_by_role('dialog',name='加入资料夹',exact=True)).to_be_visible()
    expect(heading).to_have_text(first)
    page.keyboard.press('Escape')
    reader.get_by_role('button',name='返回列表',exact=True).focus()
    page.keyboard.press('j');expect(heading).to_have_text(second)
    page.keyboard.press('Escape')
    expect(page.locator('.record-title button').first).to_be_focused()
    reader=open_first(page,base)
    reader.locator('.ux-maintenance > summary').click()
    reader.get_by_role('button',name='编辑内容',exact=True).click()
    if not page.locator('[data-record-body]').evaluate('(x)=>x.open'):
        page.locator('[data-record-body] > summary').click()
    editor=page.get_by_role('textbox',name='正文',exact=True)
    editor.fill('编辑输入')
    page.keyboard.press('/');page.keyboard.press('j');page.keyboard.press('k');page.keyboard.press('Control+k')
    expect(editor).to_have_text('编辑输入/jk')
    expect(page.get_by_role('dialog')).to_be_visible()
    page.keyboard.press('Escape')
    page.keyboard.press('Escape')
    page.goto(base+'/#personal');page.keyboard.press('j')
    expect(page.locator('.library-reader')).to_have_count(0)
    return {'search':True,'j_k':True,'input_modal_ime_modifiers_page_exit':True,'return_focus':True}


def files(page,base):
    page.goto(base+'/#collaboration?business=journal')
    page.get_by_role('button',name='新建期刊工作',exact=True).click()
    page.get_by_label('已知刊名 *',exact=True).fill('文件反馈合成期刊')
    page.get_by_label('原刊卷期或覆盖范围 *',exact=True).fill('2026合成一期')
    page.get_by_role('button',name='保存期刊工作',exact=True).click()
    field=page.get_by_label('期刊编译文件 *',exact=True)
    field.set_input_files({'name':'第一次.txt','mimeType':'text/plain','buffer':b'x'*1024})
    feedback=page.locator('.file-picked-meta')
    expect(feedback).to_have_text('已选择：第一次.txt（1.0 KB）')
    field.set_input_files({'name':'改选.txt','mimeType':'text/plain','buffer':b'abc'})
    expect(feedback).to_have_text('已选择：改选.txt（3 字节）')
    field.set_input_files([])
    expect(feedback).to_have_count(0)
    # Native multiple-file control fixture exercises the common DOM handler;
    # current upload forms still accept exactly one file.
    page.evaluate('''() => {const input=document.createElement('input');input.type='file';input.multiple=true;input.setAttribute('aria-label','合成多文件控件');document.querySelector('#content').append(input)}''')
    multiple=page.get_by_label('合成多文件控件',exact=True)
    multiple.set_input_files([{'name':'a.txt','mimeType':'text/plain','buffer':b'a'},{'name':'b.txt','mimeType':'text/plain','buffer':b'bb'}])
    expect(page.locator('.file-picked-meta')).to_have_text('已选择：a.txt（1 字节）、b.txt（2 字节）')
    multiple.set_input_files([]);expect(feedback).to_have_count(0)
    return {'select_replace_clear':True,'native_multiple_control':True}


def statistics(page,base):
    rid=call(page.context,base,'/api/records',{'title':'篇幅边界合成','kind':'report',
        'body_html':'<p>'+'研'*1000+'</p><p>hello world &amp; !</p>',
        'abstract':'额外摘要不计入正文', 'original_catalogue':'隐藏维护说明'*100,
        'visibility':'shared','sharing_confirmed':True},expected=201)['id']
    page.goto(base+'/#library?feed=all&q=篇幅边界合成')
    page.locator('.record-title button').click()
    expect(page.locator('.ux-reading-stats')).to_have_text('正文 · 1,002 字词 · 约 3 分钟')
    rid=call(page.context,base,'/api/records',{'title':'仅摘要篇幅','kind':'report',
        'abstract':'研究'*20+' hello & !','visibility':'shared','sharing_confirmed':True},expected=201)['id']
    page.goto(base+'/#library?feed=all&q=仅摘要篇幅')
    page.locator('.record-title button').click()
    expect(page.locator('.ux-reading-stats')).to_have_text('摘要 · 41 字词 · 约 1 分钟')
    expect(page.locator('.ux-main-body')).to_have_count(0)
    return {'body_words':1002,'abstract_words':41,'metadata_excluded':True}


def collaboration(page,base):
    account(page.context,base,'admin')
    q=next(x for x in page.context.request.get(base+'/api/collaboration/qualifications').json()['items'] if x['id']=='researcher')
    call(page.context,base,'/api/collaboration/qualifications/researcher',{'version':q['version'],'enabled':True},method='PUT')
    account(page.context,base,'researcher')
    tid=call(page.context,base,'/api/collaboration/topics',{'theme':'交稿人数合成','participant_ids':['colleague']},expected=201)['id']
    account(page.context,base,'colleague')
    page.reload()
    page.goto(base+'/#collaboration?id='+tid)
    page.get_by_label('选题报告文件 *',exact=True).set_input_files({'name':'他人先交.txt','mimeType':'text/plain','buffer':b'first other participant'})
    page.get_by_role('button',name='提交为版本 1',exact=True).click()
    expect(page.get_by_role('link',name='下载原件 v1',exact=True)).to_be_visible()
    account(page.context,base,'researcher')
    page.reload()
    page.goto(base+'/#collaboration?id='+tid)
    expect(page.get_by_role('button',name='提交我的选题报告',exact=True)).to_be_visible()
    expect(page.get_by_label('选题报告文件 *',exact=True)).to_be_visible()
    progress=page.get_by_role('progressbar',name='有效参与成员的选题报告交稿人数',exact=True)
    expect(progress).to_have_attribute('aria-valuenow','1')
    expect(progress).to_have_attribute('aria-valuemax','2')
    expect(page.get_by_text('有效参与成员 2 人 · 已交选题报告 1 人',exact=True)).to_be_visible()
    # Synthetic HTTP projection variants cover defensive presentation without
    # claiming these shapes were emitted by a normal server transaction.
    original=page.request.get(base+'/api/collaboration/topics/'+tid).json()
    colleague=next(p for p in original['participants'] if p['id']=='colleague')
    researcher=next(p for p in original['participants'] if p['id']=='researcher')
    endpoint=base+'/api/collaboration/topics/'+tid
    for participants,total,submitted in [([colleague,colleague,{**researcher,'active':False}],1,1),([{**colleague,'active':False},researcher],1,0),([],0,0)]:
        page.route(endpoint,lambda route,request,participants=participants:route.fulfill(json={**original,'participants':participants}))
        page.reload()
        if total:
            expect(progress).to_have_attribute('aria-valuemax',str(total))
            expect(progress).to_have_attribute('aria-valuenow',str(submitted))
        else:
            expect(progress).to_have_count(0)
            expect(page.get_by_text('暂无有效参与成员，暂不计算交稿进度。',exact=True)).to_be_visible()
        page.unroute(endpoint)
    return {'other_submitted_first_own_entry_visible':True,'submitted_people':1,'active_participants':2,'http_projection_duplicate_disabled_empty':True}


def progress(page,base):
    reader=open_first(page,base)
    bar=page.get_by_role('progressbar',name='本篇阅读位置',exact=True)
    expect(bar).to_have_attribute('aria-valuenow','0')
    top=reader.locator('.library-reader-head').bounding_box()['y']
    reader.evaluate('(x)=>{x.scrollTop=x.scrollHeight}')
    expect(bar).to_have_attribute('aria-valuenow','100')
    assert abs(reader.locator('.library-reader-head').bounding_box()['y']-top)<=1
    page.keyboard.press('j')
    expect(bar).to_have_attribute('aria-valuenow','0')
    return {'scroll_end':100,'next_resets':0,'header_sticky':True}


def copying(page,base):
    reader=open_first(page,base)
    next_title=page.locator('.record-title button').nth(1).inner_text()
    # Clipboard is an external browser boundary; no app functions are replaced.
    page.evaluate("() => Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.copiedText=text}}})")
    copy=reader.get_by_role('button',name='复制出处',exact=True)
    copy.click()
    expect(reader.get_by_role('button',name='已复制',exact=True)).to_be_visible()
    assert page.evaluate('() => window.copiedText').strip()
    page.evaluate("() => Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new DOMException('denied','NotAllowedError')}}})")
    reader.get_by_role('button',name='已复制',exact=True).click()
    expect(page.get_by_label('选择下方文字后复制',exact=True)).to_be_visible()
    assert reader.get_by_role('button',name='已复制',exact=True).count()==0
    page.evaluate("() => Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:()=>new Promise(resolve=>window.completeCopy=resolve)}})")
    copy.click()
    page.wait_for_function('() => typeof window.completeCopy==="function"')
    reader.get_by_role('button',name='返回列表',exact=True).focus()
    page.keyboard.press('j')
    expect(reader.locator('.detail-title')).to_have_text(next_title)
    page.evaluate('() => window.completeCopy()')
    expect(reader.get_by_role('button',name='已复制',exact=True)).to_have_count(0)
    expect(reader.locator('[data-copy-region]')).to_be_empty()
    return {'success_text':True,'failure_manual_copy':True,'late_copy_after_navigation_ignored':True}


def matrix(page,context,base,evidence,worker,downloads):
    results=[]
    call(context,base,'/api/sources',{'name':'合成期刊主办国别提示','kind':'journal','website':'https://example.org/journal'},expected=201)
    person=call(context,base,'/api/people',{'name':'合成人物与长题名'+'跨语言研究'*8,'original_name':'Synthetic Researcher','change_note':'合成界面依据','introduction_html':'<p>合成人物介绍，保留出处。</p>'},expected=201)['id']
    for width,zoom in [(1366,1),(390,1),(320,1),(1366,2)]:
        page.set_viewport_size({'width':width,'height':900})
        actual=worker.evaluate('''async ({url,zoom})=>{const tabs=await chrome.tabs.query({});const tab=tabs.find(t=>t.url===url);await chrome.tabs.setZoom(tab.id,zoom);return await chrome.tabs.getZoom(tab.id)}''',{'url':page.url,'zoom':zoom})
        assert actual==zoom
        suffix=f'{width}-{zoom}'
        page.goto(base+'/#library?feed=all')
        page.reload()  # Each density sample starts with no transient selection.
        expect(page.locator('.library-row')).to_have_count(14)
        rows=page.locator('.library-row').evaluate_all('(xs)=>xs.map(x=>{const b=x.getBoundingClientRect();return {top:b.top,bottom:b.bottom}})')
        size=page.evaluate('() => ({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})')
        density={'first_row_top':rows[0]['top'],'fully_visible_rows':sum(x['top']>=0 and x['bottom']<=size['height'] for x in rows),'rows':len(rows),**size}
        data={'width':width,'actual_zoom':actual,'density':density,'list':measure(page,evidence,'dense-list-'+suffix)}
        reader=open_first(page,base)
        data['reader_default']=measure(page,evidence,'reader-default-'+suffix)
        for _ in range(2):reader.get_by_role('button',name='放大阅读字号',exact=True).click()
        expect(reader.locator('.ux-main-body .rich-prose')).to_have_css('font-size','21px')
        data['reader_large']=measure(page,evidence,'reader-large-'+suffix)
        table=reader.locator('.reading-table')
        table.scroll_into_view_if_needed()
        data['table']=table.evaluate('(x)=>{x.scrollLeft=x.scrollWidth;return {width:x.clientWidth,scrollWidth:x.scrollWidth,scrollLeft:x.scrollLeft}}')
        assert data['table']['scrollLeft']>0,data['table']
        # Screenshot the actual long table after local horizontal scrolling.
        page.screenshot(path=str(evidence/('long-table-'+suffix+'.png')))
        assert page.evaluate('() => document.documentElement.scrollWidth<=document.documentElement.clientWidth+1')
        page.keyboard.press('Escape')
        page.evaluate("() => localStorage.removeItem('zhihui_reader_prefs')")
        page.get_by_text('整理与导出',exact=True).click()
        page.get_by_role('button',name='批量整理',exact=True).click()
        page.locator('[data-library-select]').first.check()
        data['selection']=measure(page,evidence,'selection-'+suffix)
        page.screenshot(path=str(evidence/('selection-'+suffix+'.png')))
        page.goto(base+'/#sources?group=journal')
        page.get_by_text('筛选条件',exact=True).click()
        expect(page.get_by_text('期刊按主办国别筛选，出版方国家另记；国际定位独立登记。',exact=True)).to_be_visible()
        data['source_filters']=measure(page,evidence,'source-filters-'+suffix)
        page.goto(base+'/#people?id='+person)
        expect(page.get_by_role('navigation',name='人物章节',exact=True)).to_be_visible()
        data['person']=measure(page,evidence,'person-'+suffix)
        page.get_by_role('navigation',name='人物章节',exact=True).get_by_role('button',name='任职经历',exact=True).click()
        expect(page.locator('#person-employment')).to_be_focused()
        if zoom==2:
            physical=context.new_cdp_session(page).send('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
            (evidence/'200-percent-physical.png').write_bytes(base64.b64decode(physical['data']))
        results.append(data)
        print(json.dumps({'density':density,'scenario':suffix}),flush=True)
    # Reuse existing topic/journal handoffs and source permissions on this new code.
    page.set_viewport_size({'width':1366,'height':900})
    worker.evaluate('''async url=>{const tab=(await chrome.tabs.query({})).find(t=>t.url===url);await chrome.tabs.setZoom(tab.id,1)}''',page.url)
    call(context,base,'/api/records',{'title':'可读资料合成：跨国来源与研究依据','kind':'report','body_html':'<p>合成阅读回归。</p>','visibility':'shared','sharing_confirmed':True},expected=201)
    return {'reader_matrix':results,'handoff_matrix':legacy_matrix(page,context,base,evidence,worker,downloads)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check',choices=['preferences','storage','shortcuts','files','statistics','collaboration','progress','copying','matrix'],default='preferences')
    args=parser.parse_args()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    expect.set_options(timeout=4000)
    evidence=Path(tempfile.mkdtemp(prefix='database-reader-ui-83-'))
    (Path(tempfile.gettempdir())/'database-reader-ui-83-latest.txt').write_text(str(evidence))
    print(json.dumps({'evidence':str(evidence),'check':args.check}),flush=True)
    revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    source_paths=sorted(list(Path('static').glob('*'))+list(Path('templates').glob('*'))+[Path(__file__)])
    source_hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths if path.is_file()}
    app=create_app(evidence/'data',testing=True)
    server,thread,base=serve(app)
    try:
        with sync_playwright() as p:
            executable=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or 'C:/Program Files/Google/Chrome/Application/chrome.exe'
            if args.check=='matrix':
                profile=evidence/'profile';extension=evidence/'extension';extension.mkdir()
                (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Isolated zoom verification','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
                (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
                context=p.chromium.launch_persistent_context(str(profile),executable_path=executable,headless=False,ignore_default_args=['--disable-extensions'],args=['--headless=new','--enable-unsafe-extension-debugging','--remote-debugging-port=0','--no-proxy-server'],viewport={'width':1366,'height':900},accept_downloads=True)
                port=(profile/'DevToolsActivePort').read_text().splitlines()[0]
                browser=p.chromium.connect_over_cdp('http://127.0.0.1:'+port)
                cdp=browser.new_browser_cdp_session();cdp.send('Extensions.loadUnpacked',{'path':str(extension)})
                worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                downloads=evidence/'downloads';downloads.mkdir()
                cdp.send('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(downloads),'eventsEnabled':True})
            else:
                browser=p.chromium.launch(executable_path=executable,headless=True)
                context=browser.new_context(viewport={'width':1366,'height':900})
            page=context.pages[0] if context.pages else context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            login(page,base,'researcher')
            for n in range(14):
                call(context,base,'/api/records',{'title':f'合成阅读资料 {n:02d}', 'kind':'report',
                    'body_html':'<p>'+('真实可读合成正文。'*100)+'</p><table><tbody><tr>'+''.join('<td>长表格合成列 '+str(x)+'</td>' for x in range(12))+'</tr></tbody></table>',
                    'visibility':'shared','sharing_confirmed':True},expected=201)
            try:
                result=matrix(page,context,base,evidence,worker,downloads) if args.check=='matrix' else globals()[args.check](page,base)
                assert not errors,errors
                assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest for path,digest in source_hashes.items()),'Sources changed during browser checks'
                (evidence/'results.json').write_text(json.dumps({'source_commit':revision,'source_files_sha256':source_hashes,'results':result,'pageerrors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({'passed':args.check,'evidence':str(evidence)},ensure_ascii=False),flush=True)
            except Exception:
                page.screenshot(path=str(evidence/'failure.png'))
                (evidence/'failure.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
                raise
            finally:context.close();browser.close()
    finally:server.shutdown();thread.join(timeout=5)


if __name__=='__main__':main()
