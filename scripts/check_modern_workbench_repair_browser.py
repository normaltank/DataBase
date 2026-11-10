"""#142 repair regressions through HTTP fixtures and normal browser controls."""
import argparse
import json
import logging
import re
from pathlib import Path
import shutil
import subprocess
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from platform_app.web import create_app
from tests.test_topic_handoffs import HandoffTests
from tests.test_maintenance_agent import MaintenanceAgentTests
from live_flow_browser_policy import install as strict_policy, verify as verify_policy

SIZES=[(1366,900),(390,844),(320,780),(556,884)]
CAPTURES=[]

def capture(page, out, name):
    expect(page.locator('#toast')).to_have_css('opacity','0',timeout=7000)
    path=out/(name+'.png');page.screenshot(path=str(path))
    CAPTURES.append(dict(file=path.name,viewport=page.viewport_size,position=page.evaluate('({scrollY,readerY:document.querySelector(".library-reader")?.scrollTop||0,panelY:document.querySelector(".record-explore-content")?.scrollTop||0})')))


def network_boxes(page):
    return page.locator('[data-network-viewport]').evaluate('''slot=>{const b=slot.getBoundingClientRect();return [...slot.querySelectorAll('.record-network-label')].filter(e=>!e.hidden).map(e=>{const r=e.getBoundingClientRect();return {text:e.textContent,x:r.x-b.x,y:r.y-b.y,width:r.width,height:r.height,right:r.right-b.x,bottom:r.bottom-b.y,inside:r.left>=b.left-1&&r.right<=b.right+1&&r.top>=b.top-1&&r.bottom<=b.bottom+1};});}''')


def reader_checks(page, base, out, case, result):
    page.goto(base+'/#library?feed=all&q=Repair%20probe')
    page.get_by_role('button',name='研究员',exact=True).click()
    expect(page.locator('.library-row')).to_have_count(4)
    for width,height in (SIZES[1:] if case=='discovery' else SIZES):
        page.set_viewport_size(dict(width=width,height=height));page.goto(base+'/#library?feed=all&q=Repair%20probe');page.reload()
        expect(page.locator('.library-row')).to_have_count(4)
        row=page.locator('.record-title button').first
        if case=='discovery':
            result[str(width)]={'first_title_y':row.bounding_box()['y']}
            capture(page,out,f'discovery-{width}')
            assert row.bounding_box()['y']<430, result[str(width)]
            page.locator('.reading-more>summary').click()
            page.get_by_label('时间类型',exact=True).select_option('updated')
            page.get_by_role('button',name='应用筛选',exact=True).click()
            expect(page).to_have_url(re.compile('date_field=updated'))
            if not page.locator('.reading-more').evaluate('e=>e.open'):page.locator('.reading-more>summary').click()
            page.get_by_label('排序方式',exact=True).select_option('title')
            expect(page).to_have_url(re.compile('sort=title'))
            expect(page.locator('.library-row')).to_have_count(4)
            if not page.locator('.reading-more').evaluate('e=>e.open'):page.locator('.reading-more>summary').click()
            page.get_by_role('button',name='重置筛选',exact=True).click()
            expect(page.locator('.library-row')).to_have_count(4)
            page.locator('[name=q]').fill('Repair probe');page.get_by_role('button',name='查找',exact=True).click()
            expect(page.locator('.reading-filter-chip')).to_be_visible()
            page.locator('.reading-filter-chip').first.click()
            expect(page.locator('.reading-filter-chip')).to_have_count(0)
            continue
        row.click();expect(page.locator('.library-reader [data-reading-title]')).to_be_visible()
        if case=='language':
            page.locator('[data-material-add]').click();page.locator('[data-action=library-reader-next]').click();page.locator('[data-material-add]').click()
            for language in ['original','chinese']:
                button=page.locator(f'[data-action=reading-language][data-language={language}]');button.click();expect(button).to_have_attribute('aria-pressed','true')
                page.locator('.library-reader .ux-reader-tools>summary').click()
                page.locator('.library-reader').evaluate('e=>e.scrollTop=80')
                before=page.locator('.library-reader').evaluate('e=>e.scrollTop')
                title=page.locator('[data-reading-title]').inner_text()
                page.locator('[data-reading-compare] [data-material-compare=open]').click();expect(page.locator('.material-compare')).to_be_visible()
                page.locator('[data-material-compare=close]').click()
                expect(button).to_have_attribute('aria-pressed','true')
                expect(page.locator('[data-reading-title]')).to_have_text(title)
                assert page.locator('.ux-reader-tools').evaluate('e=>e.open')
                assert abs(page.locator('.library-reader').evaluate('e=>e.scrollTop')-before)<2
                capture(page,out,f'compare-return-{language}-{width}')
                page.locator('.library-reader .ux-reader-tools>summary').click()
            result[str(width)]='original/chinese, details and scroll restored'
            # New page selection is intentionally explicit; reload clears prior in-memory selection.
        else:
            relation=page.locator('[data-record-explore]');relation.locator(':scope > summary').click()
            expect(page.locator('.record-network-label')).to_have_count(2)
            result[str(width)]={}
            for mode in ['plane','space']:
                relation.locator(f'[data-explore-mode={mode}]').click();expect(page.locator('.record-network-label')).to_have_count(2)
                page.wait_for_timeout(200)
                initial=network_boxes(page);assert all(item['inside'] for item in initial),initial
                relation.locator('[data-explore-reset]').click();page.wait_for_timeout(200)
                boxes=network_boxes(page);result[str(width)][mode]={'initial':initial,'reset':boxes}
                relation.locator('[data-explore-locate]').click()
                capture(page,out,f'reader-relations-{mode}-{width}')
                assert all(item['inside'] for item in boxes),boxes
                viewport=relation.locator('[data-network-viewport]');viewport.scroll_into_view_if_needed();box=viewport.bounding_box()
                page.mouse.move(box['x']+25,box['y']+25);page.mouse.down();page.mouse.move(box['x']+55,box['y']+45,steps=6);page.mouse.up();page.wait_for_timeout(100)
                moved=network_boxes(page)
                if not relation.locator('.record-network-text').evaluate('e=>e.open'):relation.get_by_text('关系文字列表',exact=True).click()
                relation.locator('[data-explore-select]').first.click();relation.locator('[data-explore-refresh]').click();expect(relation.locator('.record-explore-content')).not_to_have_attribute('aria-busy','true')
                after=network_boxes(page)
                assert all(abs(a['x']-b['x'])<1 and abs(a['y']-b['y'])<1 for a,b in zip(moved,after)),(moved,after)
                expect(relation.locator('[data-network-selection]')).to_contain_text('完全合成 · 研究机构')
            relation.get_by_role('button',name='关闭关联',exact=True).click()
    result['policy_violations']=verify_policy(page)


def maintenance_checks(playwright,out,result):
    fixture=MaintenanceAgentTests();fixture.setUp();server=None
    try:
        jid=fixture.queue('modern-repair-browser');assert fixture.call('/api/admin/maintenance/run',user='admin').status_code==200
        server=make_server('127.0.0.1',0,fixture.app,threaded=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        browser=playwright.chromium.launch(headless=True)
        try:
            page=browser.new_page(reduced_motion='reduce');strict_policy(page)
            page.goto(f'http://127.0.0.1:{server.server_port}/#maintenance-agent');page.get_by_role('button',name='资料管理员',exact=True).click()
            page.locator(f'[data-maintenance-select="{jid}"]').click();expect(page.locator('[data-trace-step]')).to_have_count(14)
            for width,height in SIZES:
                page.set_viewport_size(dict(width=width,height=height));page.evaluate('scrollTo(0,0)')
                capture(page,out,f'maintenance-entry-{width}')
                action=page.get_by_role('button',name='查看修改与依据',exact=True)
                if width<700:
                    result[str(width)]={'action_y':action.bounding_box()['y']}
                    assert action.bounding_box()['y']+44<=height,result[str(width)]
                page.get_by_role('button',name='有改动',exact=True).click()
                page.locator('[data-trace-step]').filter(has_text='关联作者').click()
                if width<700:action.click()
                expect(page.locator('[data-trace-detail]')).to_contain_text('Alex Vale')
                capture(page,out,f'maintenance-changes-{width}')
                page.get_by_role('button',name='全部',exact=True).click()
            result['policy_violations']=verify_policy(page)
        finally:browser.close()
    finally:
        if server:server.shutdown();server.server_close();thread.join(5)
        fixture.doCleanups()


def fallback_checks(page,base,tid,ref,out,result):
    page.route('**/static/vendor/visual/flow.js*',lambda route:route.abort('failed'))
    page.goto(base+f'/#collaboration?id={tid}&tab=selection');page.get_by_role('button',name='研究员',exact=True).click()
    material=page.locator(f'[data-material-ref="{ref}"]')
    expect(material.locator('[data-flow-status]')).to_contain_text('未能加载')
    slot=material.locator('[data-flow-slot]');assert not slot.is_visible(),slot.bounding_box()
    expect(material.get_by_role('button',name='查看版本 1',exact=True)).to_be_visible()
    for width,height in SIZES:
        page.set_viewport_size(dict(width=width,height=height));material.locator(':scope > .between > h2').scroll_into_view_if_needed()
        capture(page,out,f'no-module-handoff-{width}')
    material.locator('[data-form=handoff-review]').get_by_role('button',name='通过此版',exact=True).click()
    expect(material.locator(':scope > .between > .badge')).to_have_text('当前版 1 · 通过')
    result['native_approval']='passed'
    page.unroute('**/static/vendor/visual/flow.js*')
    material.locator('[data-flow-command=retry]').click();expect(material.locator('.react-flow__node')).not_to_have_count(0)
    result['module_retry']='passed'
    page.route('**/elk-worker.min.js',lambda route:route.abort('failed'));page.reload()
    if not material.locator('.handoff-graph').evaluate('e=>e.open'):material.locator('.handoff-graph>summary').click()
    expect(material.locator('[data-flow-status]')).to_contain_text('排列失败',timeout=15000)
    expect(material.locator('[data-flow-slot]')).not_to_be_visible()
    expect(material.get_by_role('button',name='查看版本 1',exact=True)).to_be_visible()
    capture(page,out,'no-layout-handoff-556')
    page.unroute('**/elk-worker.min.js');material.locator('[data-flow-command=retry]').click()
    expect(material.locator('.react-flow__node')).not_to_have_count(0)
    result['layout_failure_and_retry']='passed';result['policy_violations']=verify_policy(page)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',required=True);parser.add_argument('--case',choices=['language','network','discovery','maintenance','fallback'],required=True);args=parser.parse_args()
    out=Path(args.evidence).resolve();out.mkdir(parents=True,exist_ok=False);data=out/'synthetic-data'
    result={'case':args.case,'paid_calls':0,'embedded_worker':False,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_diff':subprocess.check_output(['git','diff','--stat'],text=True).strip()}
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server=None
    try:
        with sync_playwright() as p:
            if args.case=='maintenance':maintenance_checks(p,out,result);return
            f=HandoffTests();f.app=create_app(data,testing=True,embedded_worker=False);f.clients={n:f.login(n) for n in ('researcher','colleague','admin')}
            source=f.call('/api/sources',{'name':'完全合成 · 研究机构','kind':'institution'}).json['id']
            for i in range(4):
                r=f.call('/api/records',{'title':f'Repair probe {i} · 区域政策与研究证据的多行题名需要完整可读','chinese_title':f'Repair probe 合成资料{i} · 区域政策与研究证据的多行题名需要完整可读','kind':'report','source_id':source,'abstract':'Original abstract','chinese_abstract':'中文摘要','body_html':'<p>完全合成的验证正文。</p>'*40});assert r.status_code==201,r.json
            tid=f.topic(theme='完全合成 · 返修验证');ref=f.upload(tid,who='researcher',title='完全合成 · 降级材料').json['material_ref']
            server=make_server('127.0.0.1',0,f.app,threaded=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            browser=p.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport=dict(width=1366,height=900),reduced_motion='reduce');strict_policy(page)
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                base=f'http://127.0.0.1:{server.server_port}'
                if args.case=='fallback':fallback_checks(page,base,tid,ref,out,result)
                else:reader_checks(page,base,out,args.case,result)
                assert not errors,errors;result['errors']=errors
            finally:browser.close()
    finally:
        if server:server.shutdown();server.server_close();thread.join(5);result['server_closed']=not thread.is_alive()
        assert data.parent==out and data.name=='synthetic-data'
        if data.exists():shutil.rmtree(data)
        result['synthetic_removed']=not data.exists();result['captures']=CAPTURES
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
