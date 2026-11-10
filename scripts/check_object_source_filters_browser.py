"""Filtered source title/menu parity, native links and actual short windows."""
import argparse
import json
import logging
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit, parse_qs

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from platform_app.web import create_app
from tests.test_topic_handoffs import HandoffTests
from live_flow_browser_policy import install as strict_policy, verify as verify_policy


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',required=True);args=parser.parse_args()
    evidence=Path(args.evidence).resolve();evidence.mkdir(parents=True,exist_ok=False)
    checks=[];captures=[];errors=[]
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    with tempfile.TemporaryDirectory(prefix='repair144-filters-') as temporary,patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('External provider forbidden')):
        f=HandoffTests();f.app=create_app(Path(temporary)/'data',testing=True,embedded_worker=False)
        f.clients={n:f.login(n) for n in ('researcher','admin')}
        for index in range(4):
            response=f.call('/api/sources',{'name':f'合成 & Baltic 区域政策研究所 {index+1}','kind':'institution','country':'Latvia','institution_types':['research_institute']})
            assert response.status_code==201,response.json
        server=make_server('127.0.0.1',0,f.app,threaded=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True)
                try:
                    p=browser.new_page(viewport={'width':1280,'height':720},reduced_motion='reduce');strict_policy(p)
                    p.on('pageerror',lambda error:errors.append(str(error)))
                    p.goto(base+'/#sources?q=合成');p.get_by_role('button',name='研究员',exact=True).click()
                    for page,params in [('sources',{'q':'合成 & Baltic','group':'institution','institution_type':'research_institute','country':'Latvia','page':'2'}),('maintenance-sources',{'q':'合成 & Baltic','kind':'institution','status':'all','page':'2'})]:
                        if page=='maintenance-sources':
                            p.get_by_role('button',name='退出登录',exact=True).click();p.get_by_role('button',name='资料管理员',exact=True).click()
                        route='#'+page+'?'+urlencode(params)
                        p.goto(base+'/'+route)
                        row=p.locator('.workbench-source-row').first;expect(row).to_be_visible()
                        href=row.locator('h2 a').get_attribute('href')
                        row.get_by_role('button',name='更多来源操作').click()
                        menu=p.get_by_role('menu',name='对象操作');action=menu.get_by_role('menuitem',name='打开档案',exact=True)
                        assert action.get_attribute('href')==href
                        action.click();expect(p.locator('.source-profile')).to_be_visible()
                        destination=parse_qs(urlsplit(p.url).fragment.partition('?')[2])
                        for key,value in params.items():assert destination[key]==[value],destination
                        assert destination['id']==[row_id:=parse_qs(href.partition('?')[2])['id'][0]]
                        p.locator('[data-action=source-directory-back]').click();expect(row).to_be_visible()
                        returned=parse_qs(urlsplit(p.url).fragment.partition('?')[2])
                        assert returned=={key:[value] for key,value in params.items()},returned
                        checks.append({'page':page,'filters':params,'id':row_id,'same_destination':True,'returned_filters':True})
                    # Dense normal research directory at the user's real heights.
                    p.goto(base+'/#sources?q=合成')
                    for width,height in [(1280,720),(515,791)]:
                        p.set_viewport_size({'width':width,'height':height})
                        rows=p.locator('.workbench-source-row');expect(rows).to_have_count(4)
                        row=rows.nth(2);row.scroll_into_view_if_needed()
                        row.get_by_role('button',name='更多来源操作').click()
                        menu=p.get_by_role('menu',name='对象操作');expect(menu).to_be_visible()
                        box=menu.bounding_box();assert box['x']>=0 and box['x']+box['width']<=width+1 and box['y']>=0 and box['y']+box['height']<=height+1
                        name=f'sources-short-edge-{width}x{height}.png';p.screenshot(path=str(evidence/name))
                        captures.append({'path':name,'viewport':p.viewport_size,'position':p.evaluate('({x:scrollX,y:scrollY})'),'state':'open menu, focused first action; third of four synthetic sources'})
                        p.keyboard.press('Escape')
                        expect(row.get_by_role('button',name='更多来源操作')).to_be_focused()
                    policy=verify_policy(p);assert not errors,errors
                finally:browser.close()
        finally:
            server.shutdown();server.server_close();thread.join(5)
            (evidence/'result.json').write_text(json.dumps({'checks':checks,'captures':captures,'errors':errors,'paid_calls':0,'base':base,'embedded_worker':False,'server_thread_stopped':not thread.is_alive()},ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
