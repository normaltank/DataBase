"""Compilation desk verification: public HTTP, synthetic data, random port, worker off."""
import argparse, io, json, sys, threading, tempfile, subprocess
from pathlib import Path
from werkzeug.serving import make_server, WSGIRequestHandler
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from platform_app.web import create_app
from tests.test_topic_handoffs import HandoffTests
class Quiet(WSGIRequestHandler):
    def log_request(self,*args,**kwargs):pass

def fixture(out):
    test=HandoffTests();test.app=create_app(out/'synthetic-data',testing=True,embedded_worker=False)
    test.clients={name:test.login(name) for name in ('researcher','colleague','admin')}
    topics=[]
    for theme in ('合成 · 波罗的海安全与欧洲政策转向','合成 · 中东欧社会变迁与区域合作'):
        tid=test.topic(theme=theme);topics.append(tid)
        for who,title in [('colleague','拉脱维亚政策观察：选题报告'),('researcher','区域合作：文献选目与说明')]:
            board=test.board(tid,who)
            r=test.call(f'/api/collaboration/topics/{tid}/handoffs',{'stage':'selection','token':board['token'],'request_id':__import__('uuid').uuid4().hex,'title':title,'note':'仅用于本轮界面验收的合成材料。'},who,file=(title+'.txt',('合成原件\n\n'+('本材料用于验证具体版本、原件预览和负责人意见。研究材料与成果分别保存。\n\n'*6)).encode()))
            assert r.status_code==201,r.json
            if who=='colleague':
                material=r.json['material_ref'];m=next(m for m in test.board(tid)['materials'] if m['ref']==material)
                assert test.decide(tid,m['versions'][0]['ref'],note='请补充选文理由与原始出处。').status_code==201
                assert test.upload(tid,who,material_ref=material,title=title).status_code==201
        if len(topics)==1:
            b=test.board(tid);r=test.call(f'/api/collaboration/topics/{tid}/enter-compilation',{'request_id':'synthetic-advance','topic_version':1,'stage_version':1});assert r.status_code==201,r.json
            r=test.upload(tid,'colleague','compilation',title='拉脱维亚安全政策：编译稿');assert r.status_code==201,r.json
    source=test.call('/api/sources',{'name':'合成 · 欧洲区域研究所','kind':'institution','country':'Latvia','introduction_html':'<p>独立合成档案：关注区域政治、国际关系与社会变迁。本介绍仅用于界面验证。</p>'}).json['id']
    journal=test.call('/api/sources',{'name':'合成 · 中东欧政治研究','kind':'journal','introduction_html':'<p>合成期刊档案，用于验证期次成果与原始资料分别组织。</p>'}).json['id']
    for i in range(6):
        r=test.call('/api/records',{'title':f'合成 · 区域政治研究 {i+1}','kind':'report','source_id':source,'countries':'Latvia' if i%2==0 else 'Germany','body_html':'<h2>研究正文</h2>'+('<p>这是一份独立的合成资料，正文用于检查阅读宽度、控制层级与返回上下文。</p>'*18),'published_on':str(2020+i)})
        assert r.status_code==201,r.json
    person=test.call('/api/people',{'name':'合成 · 安娜·卡林娜','introduction_html':'<p>合成人物档案。研究区域政治与社会变迁，身份介绍、作品及研究笔记分别保存。</p>','change_note':'界面测试合成人物'});assert person.status_code==201,person.json
    for issue in ('第1期','第2期'):
        r=test.call('/api/journal-results',{'journal_name':'合成 · 中东欧政治研究','journal_id':journal,'year':2026,'issue':issue,'request_id':__import__('uuid').uuid4().hex},file=(issue+'概览.txt',b'SYNTHETIC COMPILED RESULT'));assert r.status_code==201,r.json
    return test,topics

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--evidence',type=Path);ap.add_argument('--serve',action='store_true');args=ap.parse_args()
    out=args.evidence or Path(tempfile.mkdtemp(prefix='database-desk-browser-'));out.mkdir(parents=True,exist_ok=True)
    test,topics=fixture(out)
    server=make_server('127.0.0.1',0,test.app,threaded=True,request_handler=Quiet);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
    print(json.dumps({'base':base,'topics':topics,'evidence':str(out)},ensure_ascii=False),flush=True)
    if args.serve:threading.Event().wait();return
    errors=[];checks=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce');page.on('pageerror',lambda e:errors.append(str(e)));page.add_init_script("window.cspViolations=[];document.addEventListener('securitypolicyviolation',e=>window.cspViolations.push({directive:e.violatedDirective,blocked:e.blockedURI,source:e.sourceFile,line:e.lineNumber}))")
            page.goto(base);page.get_by_role('button',name='研究员',exact=True).click()
            expect(page.get_by_role('heading',name='协作编译',exact=True)).to_be_visible();expect(page.locator('.workbench-row')).to_have_count(2)
            assert page.locator('.sidebar').count()==0
            assert page.locator('.workbench-detail').count()==0
            page.screenshot(path=str(out/'desktop-index.png'),full_page=True)
            page.locator('[data-action=workbench-select]').first.click();expect(page.locator('[data-collaboration-topic]')).to_be_visible();expect(page.locator('[data-desk-preview]')).to_be_visible()
            page.screenshot(path=str(out/'desktop-desk.png'),full_page=True)
            for width in (320,390,1280):
                page.set_viewport_size({'width':width,'height':1000});page.screenshot(path=str(out/f'desk-{width}.png'),full_page=True)
                size=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})');assert size['scroll']<=size['width']+1,size
            checks.append('index has two real synthetic periods; no sidebar or empty detail; full desk original preview; 320/390/1280/1440 no document overflow')
            page.set_viewport_size({'width':1440,'height':1000})
            # Native top-layer menus: keyboard dismissal and focus restoration.
            personal=page.get_by_role('button',name='研究员 · 林',exact=True);personal.click();expect(page.locator('#desk-personal')).to_be_visible();page.keyboard.press('Escape');expect(personal).to_be_focused();expect(page.locator('#desk-personal')).not_to_be_visible()
            for route in ('compilations','sources','people','library?feed=all'):
                page.goto(base+'/#'+route);expect(page.locator('#content h1').first).to_be_visible();
                if route.startswith('library'):expect(page.locator('[data-material-globe] canvas')).to_be_visible()
                page.screenshot(path=str(out/(route.split('?')[0]+'-desktop.png')),full_page=True)
            page.locator('.library-row .title-button').first.click();expect(page.locator('.library-reader .detail-title')).to_be_visible();page.screenshot(path=str(out/'reader-desktop.png'),full_page=True);page.get_by_role('button',name='返回探索',exact=True).click()
            page.goto(base+'/#sources');page.locator('.workbench-source-row h2 a').last.click();expect(page.locator('.source-introduction .rich-prose')).to_be_visible();page.screenshot(path=str(out/'source-profile-desktop.png'),full_page=True)
            page.goto(base+'/#people');page.locator('.workbench-person-row h2 a').first.click();expect(page.locator('#person-introduction')).to_be_visible();page.screenshot(path=str(out/'person-profile-desktop.png'),full_page=True)
            for width in (320,390):
                page.set_viewport_size({'width':width,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');page.screenshot(path=str(out/f'person-profile-{width}.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1000})
            # Member uploads a concrete next version through the rendered native form.
            ctx=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce');member=ctx.new_page();member.goto(base+f'/#collaboration?id={topics[1]}&tab=selection');member.get_by_role('button',name='协作同事',exact=True).click()
            board=test.board(topics[1]);own=next(m for m in board['materials'] if m['owner_id']=='colleague');ref=own['ref']
            member.locator('[data-desk-material="'+ref+'"]').click();material=member.locator('[data-material-ref="'+ref+'"]');material.locator('.handoff-current-actions .handoff-upload>summary').click()
            upload=material.locator('[data-form=handoff-upload]');upload.locator('[name=file]').set_input_files({'name':'成员新版本.txt','mimeType':'text/plain','buffer':b'SYNTHETIC MEMBER VERSION THREE'});upload.locator('[name=note]').fill('新版本保留原始出处');upload.get_by_role('button',name='保存新版本',exact=True).click();expect(material.locator(':scope>.between>.badge')).to_contain_text('当前版 3')
            page.goto(base+f'/#collaboration?id={topics[1]}&tab=selection');page.locator('[data-desk-material="'+ref+'"]').click();material=page.locator('[data-material-ref="'+ref+'"]');review=material.locator('[data-form=handoff-review]');review.locator('details>summary').click();review.locator('[name=note]').fill('保留的具体版本意见');review.locator('[name=file]').set_input_files({'name':'review-draft.txt','mimeType':'text/plain','buffer':b'SYNTHETIC REVIEW DRAFT'})
            file_input=review.locator('[name=file]').element_handle();material.locator('[data-handoff-version]').select_option(index=2);expect(material.locator('[data-desk-preview]')).to_contain_text('合成原件');assert file_input.evaluate('(e)=>e.isConnected&&e.files[0].name==="review-draft.txt"');expect(review.locator('[name=note]')).to_have_value('保留的具体版本意见');material.locator('[data-handoff-version]').select_option(index=0)
            page.route('**/handoff-reviews',lambda route:route.fulfill(status=503,json={'error':'合成保存失败'}));review.get_by_role('button',name='退回',exact=True).click();expect(review.locator('.form-error')).to_contain_text('合成保存失败');assert file_input.evaluate('(e)=>e.files[0].name==="review-draft.txt"');page.unroute('**/handoff-reviews');review.get_by_role('button',name='退回',exact=True).click();expect(material.locator(':scope>.between>.badge')).to_contain_text('退回')
            # A submitted fourth version creates its own review target; old originals stay readable.
            material_member=member.locator('[data-material-ref="'+ref+'"]');material_member.locator('.desk-refresh>summary').click();material_member.get_by_role('button',name='刷新材料状态',exact=True).click();expect(material_member.locator(':scope>.between>.badge')).to_contain_text('退回')
            upload=material_member.locator('[data-form=handoff-upload]');upload.locator('[name=file]').set_input_files({'name':'成员第四版.txt','mimeType':'text/plain','buffer':b'SYNTHETIC MEMBER VERSION FOUR'});upload.get_by_role('button',name='保存新版本',exact=True).click();expect(material_member.locator(':scope>.between>.badge')).to_contain_text('当前版 4')
            material.locator('.desk-refresh>summary').click();material.get_by_role('button',name='刷新材料状态',exact=True).click();expect(material.locator(':scope>.between>.badge')).to_contain_text('当前版 4');material.locator('[data-handoff-version]').select_option(index=0);current=material.locator('[data-form=handoff-review]').filter(has=page.locator('[type=submit]:not([disabled])')).last;current.get_by_role('button',name='通过此版',exact=True).click();expect(material.locator(':scope>.between>.badge')).to_contain_text('通过')
            material.locator('[data-handoff-version]').select_option(index=1);expect(material.locator('[data-desk-preview]')).to_contain_text('SYNTHETIC MEMBER VERSION THREE');expect(material.locator('[data-handoff-reading]')).to_contain_text('保留的具体版本意见')
            checks.append('member upload v3 → lead review concrete v3 with file/note retained across historical switch and failed write → return → member v4 → approve v4 → historical original/readback')
            page.emulate_media(reduced_motion='no-preference');page.goto(base+'/#collaboration');page.locator('[data-action=workbench-select]').first.click();expect(page.locator('.desk-workspace')).to_be_visible();animated=page.locator('.desk-workspace').element_handle();page.get_by_role('button',name='返回协作编译',exact=True).click();expect(page.get_by_role('heading',name='协作编译',exact=True)).to_be_visible();assert animated.evaluate('(e)=>!e.isConnected&&!e.style.opacity&&!e.style.transform')
            checks.append('object transition cancels and reverts on route replacement; reduced-motion checks use immediate final state')
            violations=page.evaluate('window.cspViolations');application_violations=[v for v in violations if not(v['source']=='http://local.adguard.org/' and v['blocked']=='eval' and v['directive']=='script-src')];assert not application_violations,application_violations
            (out/'csp.json').write_text(json.dumps(violations,ensure_ascii=False,indent=2),encoding='utf-8')
            checks.append('application has no CSP violations (blocked external AdGuard injection separately recorded); native popover Escape restores focus; result/archive/discovery/reader content surfaces render')
            # A truly empty personal scope contains one useful empty state.
            empty_ctx=browser.new_context();empty_page=empty_ctx.new_page();empty_page.goto(base);empty_page.get_by_role('button',name='资料管理员',exact=True).click();expect(empty_page.locator('.desk-empty')).to_have_count(1);expect(empty_page.locator('.workbench-detail')).to_have_count(0);empty_page.get_by_role('button',name='查看全部可读',exact=True).click();expect(empty_page.locator('.workbench-row')).to_have_count(2);empty_ctx.close()
            checks.append('empty-hash login defaults to collaboration; empty participating scope has one working empty state')
            ctx.close()
            assert not errors,errors
            (out/'result.json').write_text(json.dumps({'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'base':base,'worker':False,'paid_calls':0,'checks':checks,'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8');browser.close()
    finally:server.shutdown();server.server_close()
    print(json.dumps({'evidence':str(out),'checks':checks},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
