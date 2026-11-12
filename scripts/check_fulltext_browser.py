"""#65 actual reader, public HTTP, isolated synthetic data and mocked suppliers.

No real research directory, credentials, external acquisition or paid calls.
"""
import argparse
import hashlib
import json
import os
import sys
import threading
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server,WSGIRequestHandler
from tests.test_fulltext import FulltextTests
from platform_app.fulltext import run_pending
from platform_app.maintenance import restore_backup
from platform_app.web import create_app


class Quiet(WSGIRequestHandler):
    def log(self,*args,**kwargs):pass


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',required=True,type=Path)
    args=parser.parse_args();out=args.evidence.resolve();out.mkdir(parents=True,exist_ok=True)
    fixture=FulltextTests();fixture.setUp()
    app=fixture.app;rid=fixture.record(title='合成 · 按需原件与全文阅读',language='English')
    fixture.body(rid)
    no_body=fixture.record(title='合成 · 只有公开链接',url='https://example.org/metadata.pdf')
    fixture.call('/api/admin/ai/config',{'cap':'1','currency':'USD'},user='admin')
    server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port);errors=[];result={'real_paid_calls':0,'checks':[]}
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,**({'executable_path':os.environ['DATABASE_BROWSER_EXECUTABLE']} if os.environ.get('DATABASE_BROWSER_EXECUTABLE') else {}))
            page=browser.new_page(viewport={'width':1366,'height':900},reduced_motion='reduce')
            page.set_default_timeout(15000)
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(base+'/#library?feed=all&q=合成');page.get_by_role('button',name='研究员',exact=True).click()
            page.locator('[data-action=detail][data-id="'+no_body+'"]').first.click()
            section=page.locator('[data-fulltext-record]');expect(section).to_contain_text('尚未取得可用作品正文')
            expect(section.locator('[data-action=fulltext-request]')).to_have_count(0)
            page.get_by_role('button',name='返回探索与结果',exact=True).click()
            page.locator('[data-action=detail][data-id="'+rid+'"]').first.click()
            pdf=fixture.text_pdf()
            with fixture.public(pdf):section.get_by_role('button',name='保存公开原文件',exact=True).click();expect(section.get_by_role('link',name='下载已保存原文件')).to_be_visible()
            with page.expect_download() as downloading:section.get_by_role('link',name='下载已保存原文件').click()
            downloaded=downloading.value;downloaded.save_as(out/'saved-original.pdf')
            content=(out/'saved-original.pdf').read_bytes()
            assert content==pdf
            detail=page.request.get(base+'/api/records/'+rid).json()
            assert detail['saved_originals'][0]['sha256']==hashlib.sha256(content).hexdigest()
            assert detail['saved_originals'][0]['requested_url']=='https://example.org/original.pdf'
            result['checks'].append('actual reader save/download matches independent PDF bytes and provenance')
            print('Saved PDF and verified provenance',flush=True)
            section.get_by_role('button',name='翻译此 PDF 已提取文字').click();expect(section).to_contain_text('0 / 2 段')
            expect(section).to_contain_text('此 PDF 共 2 页，其中 2 页取得可提取文字')
            print('Requested persistent fulltext task',flush=True)
            # Run one durable paragraph, then restart processing with a fresh
            # connection. Only the second segment fails; first is preserved.
            with fixture.provider(failing={1}):run_pending(app.config['DATA_DIR'],limit=2)
            print('Processed partial fulltext task',flush=True)
            page.locator('body').click(position={'x':10,'y':120});expect(section).to_contain_text('1 / 2 段',timeout=12000)
            expect(section).to_contain_text('AI响应失败')
            section.get_by_role('button',name='原译对照',exact=True).click()
            expect(section).to_contain_text('Actual PDF page 1.');expect(section).to_contain_text('第一段完整译文。')
            expect(section).to_contain_text('PDF 第 2 页（文件页码）')
            section.locator('details:has([data-fulltext-edit]) > summary').first.click()
            form=section.locator('[data-fulltext-edit]').first;form.locator('textarea').fill('浏览器人工校订，保留输入。')
            page.wait_for_timeout(5500);expect(form.locator('textarea')).to_have_value('浏览器人工校订，保留输入。')
            print('Preserved open correction draft',flush=True)
            # A second member correction makes this form stale, without changing
            # the old form's draft. Actual HTTP conflict must preserve it.
            jid=page.request.get(base+'/api/records/'+rid).json()['fulltext']['versions'][0]['id']
            fixture.call('/api/fulltext/'+jid+'/edit',{'paragraph':0,'revision':0,'text':'同事先保存的校订。'},user='colleague')
            form.get_by_role('button',name='保存校订').click();expect(form.locator('[data-edit-status]')).to_contain_text('当前输入仍保留')
            expect(form.locator('textarea')).to_have_value('浏览器人工校订，保留输入。')
            page.screenshot(path=str(out/'conflict-desktop.png'),full_page=True)
            # Leave/reopen obtains the new revision; save through the real form.
            page.get_by_role('button',name='返回探索与结果',exact=True).click()
            page.locator('[data-action=detail][data-id="'+rid+'"]').first.click()
            section.locator('details:has([data-fulltext-edit]) > summary').first.click()
            form=section.locator('[data-fulltext-edit]').first;form.locator('textarea').fill('浏览器采用的人工校订。');form.get_by_role('button',name='保存校订').click()
            expect(section).to_contain_text('浏览器采用的人工校订。')
            section.get_by_role('button',name='继续未完成段落').click()
            with fixture.provider() as provider:
                fixture.worker('2090-11-12T00:10:00+00:00');assert provider.sent.call_count==1
            page.locator('body').click(position={'x':10,'y':120});expect(section).to_contain_text('2 / 2 段',timeout=12000)
            expect(section).to_contain_text('浏览器采用的人工校订。')
            section.get_by_role('button',name='原文',exact=True).click();expect(section.locator('.fulltext-paragraph > p.prose').first).to_contain_text('Actual PDF page 1.')
            section.get_by_role('button',name='中文',exact=True).click();expect(section.locator('.fulltext-paragraph > p.prose').first).to_have_text('浏览器采用的人工校订。')
            result['checks'].append('partial progress, actual retry, language switch, polling draft preservation and human conflict')
            for width in [1366,390,320]:
                page.set_viewport_size({'width':width,'height':900})
                section.scroll_into_view_if_needed()
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),width
                page.screenshot(path=str(out/f'reading-{width}.png'),full_page=True)
            result['checks'].append('1366/390/320 reader with no page overflow')
            # An in-flight read must not reopen a reader that was left meanwhile.
            held=[]
            page.route('**/api/records/'+rid,lambda route:held.append(route))
            section.get_by_role('button',name='原文',exact=True).click()
            page.get_by_role('button',name='返回探索与结果',exact=True).click()
            assert held
            for route in held:route.fulfill(response=route.fetch())
            page.unroute('**/api/records/'+rid)
            expect(page.locator('[data-fulltext-record]')).to_have_count(0)
            result['checks'].append('late state response cannot reopen a closed reader')
            browser.close()
            extension=out/'zoom-extension';extension.mkdir()
            (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Synthetic fulltext zoom','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
            (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
            zoom=p.chromium.launch_persistent_context(str(out/'zoom-profile'),headless=False,ignore_default_args=['--disable-extensions'],args=['--headless=new',f'--disable-extensions-except={extension}',f'--load-extension={extension}'],viewport={'width':1366,'height':900})
            worker=zoom.service_workers[0] if zoom.service_workers else zoom.wait_for_event('serviceworker')
            zp=zoom.pages[0];zp.goto(base+'/#library?feed=all&q=合成');zp.get_by_role('button',name='研究员',exact=True).click()
            zp.locator('[data-action=detail][data-id="'+rid+'"]').first.click()
            worker.evaluate('''async()=>{const tabs=await chrome.tabs.query({});const tab=tabs.find(t=>t.url.startsWith('http://127.0.0.1:'));await chrome.tabs.setZoom(tab.id,2)}''')
            expect(zp.locator('[data-fulltext-record]')).to_contain_text('此 PDF 共 2 页')
            assert zp.evaluate('document.documentElement.scrollWidth<=innerWidth')
            zp.locator('[data-fulltext-record]').scroll_into_view_if_needed();zp.screenshot(path=str(out/'zoom-200.png'))
            result['zoom_inner_width']=zp.evaluate('innerWidth');zoom.close()
            result['checks'].append('native Chromium 200% PDF reader zoom without overflow')
        expected=fixture.detail(rid)
        with fixture.call('/api/backup',user='admin') as response:(out/'complete.zip').write_bytes(response.data)
        restored=restore_backup(out/'complete.zip',out/'new-directory')
        recovered=create_app(restored,testing=True).test_client();csrf=recovered.get('/api/session').json['csrf']
        recovered.post('/api/login',json={'username':'researcher','password':'LocalDemo2026!'},headers={'X-CSRF-Token':csrf})
        assert recovered.get('/api/records/'+rid).json['fulltext']==expected['fulltext']
        result['checks'].append('browser-produced file, originals, translations and human version restored to a new directory')
        result['page_errors']=errors;assert not errors,errors
    finally:
        server.shutdown();thread.join();server.server_close();fixture.doCleanups()
        (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
