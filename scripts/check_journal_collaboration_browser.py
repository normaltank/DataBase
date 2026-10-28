"""Real browser journal save/revise/product/return on fresh synthetic data only."""
import hashlib
import json
import logging
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server
from platform_app.web import create_app
from scripts.check_collaboration_browser import login, no_overflow, original


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    evidence = Path(tempfile.mkdtemp(prefix='database-journal-browser-'))
    extension = evidence / 'zoom-extension'
    extension.mkdir()
    (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Local journal zoom verifier','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}),encoding='utf-8')
    (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(() => {});',encoding='utf-8')
    app=create_app(evidence/'data',testing=True)
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    results,errors=[],[]
    try:
        with sync_playwright() as p:
            executable=os.environ.get('DATABASE_BROWSER_EXECUTABLE')
            context=p.chromium.launch_persistent_context(str(evidence/'browser-profile'),headless=False,
                **({'executable_path':executable} if executable else {}),ignore_default_args=['--disable-extensions'],
                args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}'],viewport={'width':1366,'height':900},accept_downloads=True)
            worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page=context.pages[0]
            page.on('pageerror',lambda error:errors.append(str(error)))
            for width,zoom in ((1366,1),(390,1),(1366,2)):
                page.set_viewport_size({'width':width,'height':900})
                worker.evaluate('async ({url,zoom})=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));if(t)await chrome.tabs.setZoom(t.id,zoom);}',{'url':base,'zoom':zoom})
                login(page,base,'researcher')
                # Set after navigation too, so the first blank tab is covered.
                worker.evaluate('async ({url,zoom})=>{const t=(await chrome.tabs.query({})).find(x=>x.url.startsWith(url));await chrome.tabs.setZoom(t.id,zoom);}',{'url':base,'zoom':zoom})
                page.get_by_role('button',name='期刊编译',exact=True).click()
                expect(page.get_by_role('heading',name='期刊编译',exact=True)).to_be_visible()
                page.get_by_role('button',name='新建期刊工作',exact=True).click()
                name=f'合成刊物 {width} / {int(zoom*100)}%'
                page.get_by_label('已知刊名',exact=False).fill(name)
                page.get_by_label('原刊卷期或覆盖范围',exact=False).fill('2025年第1—3期 · 跨期整体概览')
                page.get_by_label('出处线索',exact=False).fill('https://example.invalid/journal · 尚未建立独立期刊档案')
                page.get_by_role('button',name='保存期刊工作',exact=True).click()
                expect(page.get_by_role('heading',name=name,exact=True)).to_be_visible()
                work_url=page.url
                first,second=original('期刊原稿一'),original('期刊修订成品二')
                long_name='期刊概览_'+('原刊跨期材料与正文出处'*8)+'.docx'
                page.get_by_label('期刊编译文件',exact=False).set_input_files({'name':long_name,'mimeType':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','buffer':first})
                page.get_by_label('简短说明',exact=False).fill('保留原稿，不拆逐篇条目。')
                page.get_by_role('button',name='保存文件新版本',exact=True).click()
                expect(page.get_by_role('link',name='下载期刊原件 v1',exact=True)).to_be_visible()
                expect(page.get_by_label('期刊编译文件',exact=False)).to_be_hidden()
                page.get_by_role('button',name='提交文件',exact=True).click()
                page.get_by_label('期刊编译文件',exact=False).set_input_files({'name':'修订成品.docx','mimeType':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','buffer':second})
                page.get_by_label('材料类型',exact=True).select_option('product')
                page.get_by_label('简短说明',exact=False).fill('实际成品，另行记录采用。')
                # Concurrent metadata update through a second real page preserves selected bytes.
                peer=context.new_page()
                peer.goto(work_url)
                peer.get_by_role('button',name='补充期刊信息',exact=True).click()
                peer.get_by_label('出处线索',exact=False).fill('并行补充的刊物出处')
                peer.get_by_role('button',name='保存期刊工作',exact=True).click()
                expect(peer.get_by_role('heading',name=name,exact=True)).to_be_visible()
                page.get_by_role('button',name='保存文件新版本',exact=True).click()
                expect(page.get_by_role('heading',name='请核对期刊最新材料',exact=True)).to_be_visible()
                expect(page.get_by_label('简短说明',exact=False)).to_have_value('实际成品，另行记录采用。')
                assert page.locator('#journal-file').evaluate('el=>el.files[0].name')=='修订成品.docx'
                page.get_by_role('button',name='已核对，保留文件继续',exact=True).click()
                page.get_by_role('button',name='保存文件新版本',exact=True).click()
                expect(page.get_by_role('link',name='下载期刊原件 v2',exact=True)).to_be_visible()
                peer.close()
                page.get_by_role('button',name='作为当前成品 v2',exact=True).click()
                expect(page.get_by_text('当前成品',exact=True)).to_be_visible()
                page.get_by_text('查看此前 1 个文件版本',exact=True).click()
                with page.expect_download() as download:
                    page.get_by_role('link',name='下载期刊原件 v1',exact=True).click()
                assert Path(download.value.path()).read_bytes()==first
                with page.expect_download() as download:
                    page.get_by_role('link',name='下载期刊原件 v2',exact=True).click()
                assert Path(download.value.path()).read_bytes()==second
                actions=page.locator('.collaboration-file .stack .button').evaluate_all("els=>els.map(el=>({width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height}))")
                assert actions and all(a['width']>=140 and a['height']<=64 for a in actions),actions
                page.get_by_text('完整文件名',exact=True).click()
                expect(page.get_by_text(long_name,exact=True)).to_be_visible()
                no_overflow(page)
                page.get_by_text('完整文件名',exact=True).click()
                layout=no_overflow(page)
                if zoom==2:
                    assert layout['width']<800 and layout['dpr']>=2,layout
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(evidence/f'journal-{width}-{int(zoom*100)}.png'),full_page=zoom==1)
                page.get_by_role('button',name='查看正文与原文关联',exact=True).click()
                expect(page.get_by_role('dialog')).to_be_visible()
                page.get_by_role('button',name='关闭',exact=True).click()
                expect(page.get_by_role('heading',name=name,exact=True)).to_be_visible()
                page.get_by_role('button',name='← 返回期刊工作',exact=True).click()
                expect(page.get_by_role('heading',name='期刊编译',exact=True)).to_be_visible()
                page.get_by_role('button',name=name+' · 2025年第1—3期 · 跨期整体概览',exact=True).click()
                expect(page.get_by_text('当前成品',exact=True)).to_be_visible()
                # Real keyboard can reach the note after the file/select controls.
                page.get_by_role('button',name='提交文件',exact=True).click()
                page.get_by_label('期刊编译文件',exact=False).focus()
                page.keyboard.press('Tab')
                expect(page.get_by_label('材料类型',exact=True)).to_be_focused()
                page.keyboard.press('Tab')
                expect(page.get_by_label('简短说明',exact=False)).to_be_focused()
                no_overflow(page)
                page.get_by_role('button',name='退出登录',exact=True).click()
                results.append({'width':width,'zoom':zoom,'layout':layout,'old_sha256':hashlib.sha256(first).hexdigest(),'product_sha256':hashlib.sha256(second).hexdigest(),'conflict_preserved_file':True,'record_and_list_return':True,'actions':actions})
            assert not errors,errors
            context.close()
        (evidence/'results.json').write_text(json.dumps({'base':base,'results':results,'pageerrors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'evidence':str(evidence),'scenarios':len(results),'pageerrors':errors},ensure_ascii=False))
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__=='__main__':
    main()
