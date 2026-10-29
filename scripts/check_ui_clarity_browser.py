"""#77: actionable empty states and concise research paths, on synthetic data only.

Public HTTP seeds and real Chrome clicks; no production data, collection or AI.
--red records the old empty state and then fails on its missing next action.
"""
import argparse
import base64
import json
import logging
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from platform_app.web import create_app
from scripts.check_topic_finals_browser import serve
from scripts.check_collaboration_library_browser import login
from scripts.check_collaboration_browser import no_overflow
from scripts.check_reader_maintenance_browser import account, call, nav, check_source, check_interfaces, check_admin


def empty_work(page, base):
    page.goto(base+'/#collaboration')
    expect(page.get_by_role('heading', name='当前范围暂无工作', exact=True)).to_be_visible()


def capture(page, evidence, name):
    no_overflow(page)
    page.evaluate("scrollTo({top:0,left:0,behavior:'instant'})")
    page.wait_for_function('() => scrollY===0')
    expect(page.locator('#toast')).not_to_have_class('show')
    page.screenshot(path=str(evidence/(name+'.png')),full_page=False,scale='css')


def observed(page,evidence,check,*args):
    try:
        return check(page,*args)
    except Exception:
        page.screenshot(path=str(evidence/'failure.png'),full_page=False)
        (evidence/'failure.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
        raise


def reading(page, base, evidence, suffix):
    page.goto(base+'/#library?feed=all&q=合成不存在的检索')
    expect(page.get_by_role('heading',name='暂时没有符合条件的资料',exact=True)).to_be_visible()
    capture(page,evidence,'reading-empty-'+suffix)
    page.locator('.empty-actions').get_by_role('button',name='重置筛选',exact=True).focus()
    page.keyboard.press('Enter')
    expect(page.locator('.library-row')).not_to_have_count(0)
    page.get_by_label('资料关键词',exact=True).fill('可读资料合成')
    page.get_by_role('button',name='查找',exact=True).click()
    expect(page.locator('.library-row')).to_have_count(1)
    saved=page.url
    title=page.get_by_role('button',name='可读资料合成：跨国来源与研究依据',exact=True)
    title.click()
    reader=page.locator('.library-reader')
    expect(reader.get_by_text('待核对',exact=True)).to_be_visible()
    expect(reader.get_by_text('中心共享',exact=True)).to_be_visible()
    expect(reader.get_by_text('版本 1',exact=True)).to_be_visible()
    expect(reader.get_by_text('原始信息 · 中文待处理',exact=True)).to_be_visible()
    expect(reader.get_by_role('button',name='加入资料夹',exact=True)).to_be_visible()
    favorite=reader.get_by_role('button',name='收藏资料',exact=True)
    if not favorite.count():
        reader.get_by_role('button',name='取消收藏',exact=True).click()
    reader.get_by_role('button',name='收藏资料',exact=True).focus()
    page.keyboard.press('Enter')
    expect(reader.get_by_role('button',name='取消收藏',exact=True)).to_be_visible()
    capture(page,evidence,'reading-toolbar-'+suffix)
    reader.get_by_role('button',name='加入资料夹',exact=True).click()
    expect(page.get_by_role('dialog',name='加入资料夹',exact=True)).to_be_visible()
    page.keyboard.press('Escape')
    page.get_by_role('button',name='返回列表',exact=True).click()
    expect(title).to_be_focused()
    assert page.url==saved
    return {'filter_and_return':True,'toolbar_favorite_and_collection':True,'permission_version_origin_visible':True}


def topic(page,base,evidence,suffix):
    page.goto(base+'/#collaboration')
    page.get_by_role('button',name='开启一期主题',exact=True).click()
    title='合成主题交接 '+suffix
    page.get_by_label('本期主题 *',exact=True).fill(title)
    page.get_by_role('dialog').get_by_role('checkbox',name='研究员 · 周',exact=True).check()
    page.get_by_role('button',name='保存本期信息',exact=True).click()
    expect(page.get_by_role('heading',name=title,exact=True)).to_be_visible()
    expect(page.get_by_text('选题报告交接',exact=True)).to_be_visible()
    capture(page,evidence,'topic-first-upload-'+suffix)
    page.get_by_label('选题报告文件 *',exact=True).set_input_files({'name':'选题报告_'+('跨国来源'*18)+'.txt','mimeType':'text/plain','buffer':b'synthetic candidate report'})
    page.get_by_role('button',name='提交为版本 1',exact=True).click()
    expect(page.get_by_role('link',name='下载原件 v1',exact=True)).to_be_visible()
    page.get_by_role('button',name='记录会议决定',exact=True).click()
    page.get_by_label('简短会议决定（可选）',exact=True).fill('采用合成文章，保留实际出处。')
    page.get_by_role('button',name='添加采用文章',exact=True).click()
    row=page.get_by_role('dialog').locator('[data-assignment-row]')
    row.get_by_label('题名或报告项目',exact=False).fill('合成采用文章 '+('研究依据与长题名'*10))
    row.get_by_label('编译研究员',exact=False).select_option('researcher')
    page.get_by_role('button',name='保存会议决定 v1',exact=True).click()
    expect(page.get_by_role('heading',name='编译稿与返修',exact=True)).to_be_visible()
    # Candidate revision remains reachable after the meeting.
    page.get_by_role('button',name='提交我的选题报告',exact=True).click()
    expect(page.get_by_label('选题报告文件 *',exact=True)).to_be_visible()
    page.get_by_role('button',name='我的编译分工',exact=True).click()
    card=page.locator('[data-assignment-card]')
    card.get_by_label('编译稿文件 *',exact=True).set_input_files({'name':'编译稿_'+('完整原件长文件名'*15)+'.txt','mimeType':'text/plain','buffer':b'synthetic manuscript v1'})
    card.get_by_role('button',name='提交编译稿 v1',exact=True).click()
    expect(card.get_by_text('待审',exact=True)).to_be_visible()
    card.get_by_text('退回修改 · 针对版本 1',exact=True).click()
    card.get_by_label('退回意见',exact=True).fill('请补原文页码。')
    card.get_by_role('button',name='退回版本 1',exact=True).click()
    expect(card.get_by_text('返修',exact=True)).to_be_visible()
    expect(card.get_by_text('请补原文页码。',exact=True)).to_be_visible()
    capture(page,evidence,'topic-returned-'+suffix)
    page.get_by_role('button',name='我的编译分工',exact=True).click()
    card.get_by_label('编译稿文件 *',exact=True).set_input_files({'name':'返修稿.txt','mimeType':'text/plain','buffer':b'synthetic manuscript v2'})
    card.get_by_role('button',name='提交编译稿 v2',exact=True).click()
    card.get_by_role('button',name='确认当前稿件定稿',exact=True).focus()
    page.keyboard.press('Enter')
    dialog=page.get_by_role('dialog')
    expect(dialog.get_by_label('新成果的可见范围',exact=True)).to_be_visible()
    expect(dialog.get_by_label('新成果的可见范围',exact=True)).to_have_value('restricted')
    expect(dialog.get_by_role('heading',name='合成采用文章 '+('研究依据与长题名'*10)+' · 稿件 v2',exact=True)).to_be_visible()
    no_overflow(page)
    dialog.get_by_role('button',name='确认稿件 v2 为定稿',exact=True).click()
    expect(card.get_by_text('已定稿',exact=True)).to_be_visible()
    page.get_by_role('button',name='← 返回主题工作',exact=True).click()
    page.locator('[data-work-id]').filter(has_text=title).get_by_role('button',name='进入主题工作',exact=True).click()
    # The latest created work is first; exact title resolves without assuming row order.
    if not page.get_by_role('heading',name=title,exact=True).count():
        page.goto(base+'/#collaboration')
        page.get_by_role('button',name=title,exact=True).click()
    return {'candidate_upload':True,'candidate_revision_after_meeting':True,'return_and_resubmit':True,'exact_v2_final':True}


def journal(page,base,evidence,suffix):
    page.goto(base+'/#collaboration?business=journal')
    page.get_by_role('button',name='新建期刊工作',exact=True).click()
    name='合成期刊留档 '+suffix
    page.get_by_label('已知刊名 *',exact=True).fill(name)
    page.get_by_label('原刊卷期或覆盖范围 *',exact=True).fill('2026年第1—3期')
    page.get_by_role('button',name='保存期刊工作',exact=True).click()
    page.get_by_label('期刊编译文件 *',exact=True).set_input_files({'name':'期刊成品_'+('长文件名'*25)+'.txt','mimeType':'text/plain','buffer':b'synthetic journal product'})
    page.get_by_label('材料类型',exact=True).select_option('product')
    page.get_by_role('button',name='保存文件新版本',exact=True).click()
    expect(page.get_by_text('当前成品',exact=True)).to_have_count(0)
    expect(page.get_by_role('button',name='作为当前成品 v1',exact=True)).to_be_visible()
    expect(page.locator('#toast')).to_contain_text('尚未设为当前成品')
    page.get_by_role('button',name='作为当前成品 v1',exact=True).click()
    expect(page.get_by_text('当前成品',exact=True)).to_be_visible()
    capture(page,evidence,'journal-product-'+suffix)
    with page.expect_download() as download:
        page.get_by_role('link',name='下载期刊原件 v1',exact=True).click()
    assert download.value.failure() is None
    assert (evidence/'downloads'/download.value.suggested_filename).read_bytes()==b'synthetic journal product'
    nav(page,'中心成果')
    page.get_by_role('button',name='期刊编译',exact=True).click()
    product=page.locator('[data-work-id]').filter(has_text=name)
    with page.expect_download() as download:
        product.get_by_role('link',name='下载成果原件 v1',exact=True).click()
    assert download.value.failure() is None
    assert (evidence/'downloads'/download.value.suggested_filename).read_bytes()==b'synthetic journal product'
    capture(page,evidence,'products-'+suffix)
    return {'separate_journal_work':True,'explicit_product_adoption':True,'product_download_bytes':True}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--red', action='store_true')
    args=parser.parse_args()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    expect.set_options(timeout=12000)
    evidence=Path(tempfile.mkdtemp(prefix='database-ui-clarity-77-'))
    (Path(tempfile.gettempdir())/'database-ui-clarity-77-latest.txt').write_text(str(evidence),encoding='utf-8')
    print(json.dumps({'evidence':str(evidence)}),flush=True)
    app=create_app(evidence/'data',testing=True)
    server,thread,base=serve(app)
    try:
        with sync_playwright() as p:
            executable=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or 'C:/Program Files/Google/Chrome/Application/chrome.exe'
            extension=evidence/'zoom-extension';extension.mkdir()
            (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Synthetic browser zoom verifier','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
            (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
            profile=evidence/'profile'
            context=p.chromium.launch_persistent_context(str(profile),executable_path=executable,headless=False,ignore_default_args=['--disable-extensions'],args=['--headless=new','--enable-unsafe-extension-debugging','--remote-debugging-port=0'],viewport={'width':1366,'height':900},accept_downloads=True)
            # Branded Chrome no longer loads unpacked extensions from --load-extension.
            # Load the local verifier through the browser CDP session, in this Temp profile.
            port=(profile/'DevToolsActivePort').read_text().splitlines()[0]
            browser=p.chromium.connect_over_cdp('http://127.0.0.1:'+port)
            cdp=browser.new_browser_cdp_session()
            cdp.send('Extensions.loadUnpacked',{'path':str(extension)})
            worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            downloads=evidence/'downloads';downloads.mkdir()
            cdp.send('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(downloads),'eventsEnabled':True})
            page=context.pages[0]
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            login(page,base,'researcher')
            empty_work(page,base)
            capture(page,evidence,('before' if args.red else 'after')+'-empty-work')
            if args.red:
                expect(page.get_by_role('button',name='查看全部可读工作',exact=True)).to_be_visible(timeout=1500)
            else:
                page.get_by_role('button',name='查看全部可读工作',exact=True).focus()
                page.keyboard.press('Enter')
                expect(page.get_by_role('button',name='全部可读',exact=True)).to_have_attribute('aria-pressed','true')
                admin=p.request.new_context(base_url=base);account(admin,base,'admin')
                qualifications=admin.get(base+'/api/collaboration/qualifications').json()['items']
                qualification=next(q for q in qualifications if q['id']=='researcher')
                call(admin,base,'/api/collaboration/qualifications/researcher',{'version':qualification['version'],'enabled':True},method='PUT')
                for title,kind in [('可读资料合成：跨国来源与研究依据','report'),('旧研究笔记合成回归','research_note')]:
                    call(context,base,'/api/records',{'title':title,'kind':kind,'body_html':'<p>合成内容，仅用于界面验收。</p>','visibility':'shared','sharing_confirmed':True},expected=201)
                results=[]
                for width,zoom in ((1366,1),(390,1),(1366,2)):
                    page.set_viewport_size({'width':width,'height':900})
                    worker.evaluate('async ({url,zoom})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));await chrome.tabs.setZoom(t.id,zoom)}',{'url':base,'zoom':zoom})
                    actual=worker.evaluate('async url=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(url));return chrome.tabs.getZoom(t.id)}',base)
                    assert actual==zoom
                    if results:
                        page.get_by_role('button',name='退出登录',exact=True).click();login(page,base,'researcher')
                    suffix=f'{width}-{zoom}'
                    page.goto(base+'/#collaboration?q=合成不存在的工作')
                    expect(page.get_by_role('heading',name='当前范围暂无工作',exact=True)).to_be_visible()
                    capture(page,evidence,'work-empty-'+suffix)
                    page.get_by_role('button',name='查看期刊编译',exact=True).click()
                    expect(page.get_by_role('heading',name='期刊编译',exact=True)).to_be_visible()
                    result={'width':width,'actual_zoom':actual,'reading':observed(page,evidence,reading,base,evidence,suffix),'topic':observed(page,evidence,topic,base,evidence,suffix),'journal':observed(page,evidence,journal,base,evidence,suffix)}
                    check_interfaces(page,base,downloads)
                    sid,jid,metrics=check_source(page,base,suffix,evidence)
                    check_admin(page,base,'合成推荐智库 '+suffix,evidence,suffix)
                    result.update(source={'institution':sid,'journal':jid,'failure_and_duplicate_preserved_input':True},metrics=metrics)
                    if zoom==2:
                        page.screenshot(path=str(evidence/'zoom-viewport.png'),full_page=False,scale='css')
                        physical=context.new_cdp_session(page).send('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
                        (evidence/'zoom-physical.png').write_bytes(base64.b64decode(physical['data']))
                    results.append(result)
                    print(json.dumps({'completed':suffix}),flush=True)
                assert not errors,errors
                assert admin.get(base+'/api/admin/ai').json()['attempts']==[]
                screenshots={path.name:struct.unpack('>II',path.read_bytes()[16:24]) for path in evidence.glob('*.png')}
                revision=subprocess.run(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parents[1],check=True,capture_output=True,text=True).stdout.strip()
                (evidence/'results.json').write_text(json.dumps({'source_commit':revision,'base':base,'browser':cdp.send('Browser.getVersion'),'executable':executable,'zoom_method':'chrome.tabs.setZoom verified by chrome.tabs.getZoom','results':results,'screenshot_pixels':screenshots,'pageerrors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({'evidence':str(evidence),'scenarios':len(results),'pageerrors':errors}),flush=True)
            context.close()
    finally:
        server.shutdown();thread.join(timeout=5)


if __name__=='__main__':
    main()
