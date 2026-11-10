"""#144 graph/person/maintenance entry acceptance with a deterministic provider."""
import argparse
import json
import logging
from pathlib import Path
import sys
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from platform_app.web import create_app
from tests.test_maintenance_agent import MaintenanceAgentTests
from live_flow_browser_policy import install as strict_policy, verify as verify_policy


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',required=True);args=parser.parse_args()
    evidence=Path(args.evidence).resolve();evidence.mkdir(parents=True,exist_ok=False)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    fixture=MaintenanceAgentTests()
    with patch('tests.test_maintenance_agent.create_app',lambda data,testing: create_app(data,testing=testing,embedded_worker=False)):
        fixture.setUp()  # This fixture installs a provider transport that rejects unexpected requests.
    checks={};errors=[];captures=[];positions=[]
    def capture(page,name):
        page.screenshot(path=str(evidence/name))
        positions.append({'path':name,'viewport':page.viewport_size,'position':page.evaluate('({x:scrollX,y:scrollY,readerY:document.querySelector(".library-reader")?.scrollTop||0})'),'focus':page.locator(':focus').evaluate_all('els=>els.map(e=>e.getAttribute("aria-label")||e.textContent)')})
    server=None
    try:
        jid=fixture.queue('object-menu-graph-144')
        assert fixture.call('/api/admin/maintenance/run',user='admin').status_code==200
        record=fixture.detail(fixture.rid)
        assert fixture.call('/api/records/'+fixture.rid,{'version':record['version'],'chinese_title':'合成 Baltic 合作资料','chinese_abstract':'合成中文摘要','body_html':'<p>长篇合成研究正文，验证阅读位置。</p>'*70},method='PUT').status_code==200
        fixture.record(title='Baltic pagination predecessor',body_html='<p>合成分页。</p>')
        server=make_server('127.0.0.1',0,fixture.app,threaded=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={'width':1366,'height':900},reduced_motion='reduce')
                strict_policy(page);page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/#people?q=Alex');page.get_by_role('button',name='研究员',exact=True).click()
                person=page.locator('.workbench-person-row').first
                expect(person).to_be_visible()
                menu=page.get_by_role('menu',name='对象操作')
                for width in [1366,1280,515,390,320]:
                    page.set_viewport_size({'width':width,'height':900 if width>700 else 844});page.evaluate('scrollTo(0,0)')
                    person.get_by_role('button',name='更多人物操作').click();expect(menu).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                    capture(page,f'people-{width}.png');captures.append(f'people-{width}.png')
                    page.keyboard.press('Escape')
                checks['people_all_widths']=True
                page.set_viewport_size({'width':1366,'height':900});page.goto(base+'/#library?feed=all&q=Baltic&page=2&size=1')
                page.locator('.record-title button').first.click()
                page.locator('.library-reader [data-language=original]').first.click()
                explorer=page.locator('.library-reader [data-record-explore]')
                explorer.locator(':scope>summary').click()
                expect(explorer.locator('[data-network-viewport] canvas').first).to_be_visible()
                explorer.locator('[data-network-viewport]').scroll_into_view_if_needed()
                # Read the real node label's projected position, then right-click
                # its actual canvas node. No synthetic dispatch or hidden graph API.
                label=explorer.locator('.record-network-label').filter(has_text='Alex Vale').first
                expect(label).to_be_visible()
                point=label.evaluate('e=>({x:e.parentElement.getBoundingClientRect().left+parseFloat(e.style.left),y:e.parentElement.getBoundingClientRect().top+parseFloat(e.style.top)})')
                assert 0 <= point['y'] <= page.viewport_size['height'],point
                page.mouse.click(point['x'],point['y'],button='right')
                expect(menu.get_by_role('menuitem',name='打开人物档案',exact=True)).to_be_visible()
                page.keyboard.press('Escape')
                slot=explorer.locator('[data-network-selection]')
                slot.get_by_role('button',name='更多关联对象操作').focus();page.keyboard.press('Shift+F10')
                expect(menu.get_by_role('menuitem',name='打开人物档案',exact=True)).to_be_focused()
                page.keyboard.press('Escape')
                explorer.get_by_role('button',name='查看所选关系',exact=True).click()
                capture(page,'network-menu-entry.png');captures.append('network-menu-entry.png')
                checks['actual_network_node_and_keyboard']=True
                # Each profile action keeps the reader's full return context.
                for kind, label in [('person','打开人物档案'), ('source','打开档案')]:
                    if not explorer.locator('.record-network-text').evaluate('e=>e.open'):
                        explorer.locator('.record-network-text>summary').click()
                    target=explorer.locator(f'.record-explore-edges [data-explore-target][data-type="{kind}"]').first
                    edge=target.locator('..')
                    edge.locator('[data-explore-select]').click()
                    expected_href=slot.locator('[data-explore-target]').get_attribute('href')
                    slot.get_by_role('button',name='更多关联对象操作').click()
                    action=menu.get_by_role('menuitem',name=label,exact=True)
                    assert action.get_attribute('href')==expected_href
                    with page.context.expect_page() as native_tab:
                        action.click(modifiers=['Control'])
                    native=native_tab.value
                    expect(native.get_by_role('button',name='返回资料',exact=True)).to_be_visible()
                    assert 'work='+fixture.rid in native.url
                    native.close()
                    slot.get_by_role('button',name='更多关联对象操作').click()
                    scroll_before=page.evaluate('({y:scrollY,readerY:document.querySelector(".library-reader").scrollTop})')
                    action.click()
                    expect(page.get_by_role('button',name='返回资料',exact=True)).to_be_visible()
                    position=page.evaluate('history.state.returnPosition')
                    assert position['readerLanguage']=='original'
                    assert position['recordExplore']['selected'].startswith(kind+':')
                    assert position['y']==scroll_before['y'] and position['readerY']==scroll_before['readerY']
                    name=f'reader-{kind}-profile.png';capture(page,name);captures.append(name)
                    page.get_by_role('button',name='返回资料',exact=True).click()
                    expect(explorer).to_be_visible()
                    expect(slot).to_have_attribute('data-object-kind',kind)
                    assert 'q=Baltic&page=2&size=1' in page.url
                    expect(page.locator('.library-reader [data-reading-language]')).to_have_attribute('data-reading-language','original')
                    expect(page.locator('.library-reader')).to_have_js_property('scrollTop',position['readerY'])
                    name=f'reader-{kind}-restored.png';capture(page,name);captures.append(name)
                checks['reader_source_and_person_menu_return']=True
                page.goto(base+'/#maintenance-agent');expect(page.get_by_text('此入口供资料管理员使用',exact=True)).to_be_visible()
                expect(page.locator('[data-trace-step]')).to_have_count(0)
                page.get_by_role('button',name='退出登录',exact=True).click();page.get_by_role('button',name='资料管理员',exact=True).click()
                page.locator(f'[data-maintenance-select="{jid}"]').click()
                steps=page.locator('.trace-step-row');expect(steps).to_have_count(14)
                target=steps.filter(has_text='关联作者').first
                target.get_by_role('button',name='更多步骤操作').click();menu.get_by_role('menuitem',name='查看修改与依据',exact=True).click()
                expect(page.locator('[data-trace-detail]')).to_contain_text('Alex Vale')
                for width in [1366,1280,515,390,320]:
                    page.set_viewport_size({'width':width,'height':900 if width>700 else 844})
                    target.get_by_role('button',name='更多步骤操作').click();expect(menu).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                    capture(page,f'maintenance-menu-{width}.png');captures.append(f'maintenance-menu-{width}.png')
                    page.keyboard.press('Escape')
                checks['maintenance_steps_all_widths_and_role']=True
                checks['policy']=verify_policy(page)
                assert not errors,errors
            finally:browser.close()
    finally:
        if server:server.shutdown();server.server_close();thread.join(5)
        fixture.doCleanups()
        (evidence/'result.json').write_text(json.dumps({'checks':checks,'captures':captures,'capture_positions':positions,'errors':errors,'worker_enabled':False,'paid_calls':0,'base':base if server else None,'server_thread_stopped':not thread.is_alive() if server else None},ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
