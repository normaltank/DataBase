"""Repeatable real Chromium acceptance; starts only synthetic data on its own port."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def verify_selection(page, api, base):
    for i in range(40):
        assert api('/api/records',{'title':'Probe %02d'%i,'kind':'report'})['status']==201
    saved=api('/api/saved-searches',{'name':'Probe selection','conditions':{'q':'Probe','sort':'title'}})['body']
    page.goto(base+'/#library?saved_search='+saved['id'])
    page.get_by_text('检索：Probe selection',exact=True).wait_for()
    page.locator('[data-library-select]').first.check()
    page.get_by_text('已选 1 条',exact=True).wait_for()
    page.get_by_role('button',name='下一页',exact=True).click()
    page.get_by_text('第 2 / 4 页',exact=True).wait_for()
    page.get_by_text('已选 1 条',exact=True).wait_for(timeout=3000)
    page.go_back()
    page.get_by_text('第 1 / 4 页',exact=True).wait_for()
    assert page.locator('[data-library-select]').first.is_checked()
    page.go_forward()
    page.get_by_text('第 2 / 4 页',exact=True).wait_for()
    page.get_by_text('已选 1 条',exact=True).wait_for()
    # Updating the same persisted search changes its effective scope and clears selection.
    current=api('/api/saved-searches/'+saved['id'],None,'GET')['body']
    assert api('/api/saved-searches/'+saved['id'],{'version':current['version'],'conditions':{'q':'Probe 00','sort':'title'}},'PUT')['status']==200
    page.get_by_role('button',name='上一页',exact=True).click()
    page.get_by_text('已选 0 条',exact=True).wait_for()
    page.get_by_role('button',name='Probe 00',exact=True).wait_for()
    assert page.locator('[data-library-select]').count()==1
    page.locator('[data-library-select]').first.check()
    page.get_by_label('资料关键词',exact=True).fill('Probe 01')
    page.locator('[data-form=library-search]').get_by_role('button',name='搜索',exact=True).click()
    page.get_by_text('已选 0 条',exact=True).wait_for()
    page.get_by_role('button',name='Probe 01',exact=True).wait_for()
    assert page.locator('[data-library-select]').count()==1
    return ['saved search id-only first open retains selection across pages and history',
            'persisted condition/version update and explicit filter changes clear selection']


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence-dir',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8853)
    parser.add_argument('--selection-only',action='store_true')
    args=parser.parse_args()
    try:
        occupied=socket.create_connection(('127.0.0.1',args.port),timeout=.25)
    except OSError:
        pass
    else:
        occupied.close()
        parser.error('Requested test port is occupied; refusing to use an existing service.')
    args.evidence_dir.mkdir(parents=True,exist_ok=True)
    base=f'http://127.0.0.1:{args.port}'
    log=(args.evidence_dir/'server.log').open('w',encoding='utf-8')
    service=subprocess.Popen([os.environ.get('DATABASE_SERVER_PYTHON',sys.executable),str(ROOT/'app.py'),'--port',str(args.port),'--data-dir',str(args.evidence_dir/'data'),'--no-import'],cwd=ROOT,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    results=[]
    try:
        for _ in range(100):
            try:
                if service.poll() is not None:raise RuntimeError('Synthetic service exited during startup.')
                urllib.request.urlopen(base+'/health',timeout=1).close();break
            except OSError: time.sleep(.1)
        else:
            raise RuntimeError('Synthetic service did not become ready.')
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,**({'executable_path':os.environ['DATABASE_BROWSER_EXECUTABLE']} if os.environ.get('DATABASE_BROWSER_EXECUTABLE') else {}))
            context=browser.new_context(viewport={'width':1366,'height':900})
            page=context.new_page()
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base)
            page.get_by_label('账号',exact=True).fill('researcher')
            page.get_by_label('密码',exact=True).fill('LocalDemo2026!')
            page.get_by_role('button',name='进入工作台').click()
            page.get_by_role('heading',name='查找研究资料',exact=True).wait_for()
            def api(path,body=None,method='POST'):
                return page.evaluate('''async ({path,body,method})=>{const session=await(await fetch('/api/session')).json();const response=await fetch(path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf},body:body===null?undefined:JSON.stringify(body)});return {status:response.status,body:await response.json()};}''',dict(path=path,body=body,method=method))
            if args.selection_only:
                results.extend(verify_selection(page,api,base))
                assert not errors,errors
                browser.close()
                print(json.dumps(results,ensure_ascii=False))
                return
            api('/api/records',{'title':'Latvia original','kind':'report'})
            api('/api/records',{'title':'Unrelated original','kind':'report'})
            page.goto(base+'/#favorites?q=Latvia&page=3')
            page.get_by_role('button',name='保存检索',exact=True).click()
            page.get_by_label('检索名称',exact=True).fill('Latvia favorites')
            page.locator('[data-saved-form=name]').get_by_role('button',name='保存检索',exact=True).click()
            page.get_by_text('检索：Latvia favorites',exact=True).wait_for()
            saved=api('/api/saved-searches',None,'GET')['body']['items'][0]
            assert saved['conditions']=={'q':'Latvia','favorite':'1'},saved
            assert 'page=' not in page.url
            results.append('favorite implicit condition and first-page open')
            page.reload()
            page.get_by_text('检索：Latvia favorites',exact=True).wait_for()
            results.append('refresh persisted conditions')
            page.get_by_role('button',name='我的检索',exact=True).click()
            page.get_by_label('按名称查找检索').fill('Latvia')
            page.get_by_role('button',name='查找',exact=True).click()
            page.get_by_role('button',name='改名／更新').click()
            page.get_by_label('检索名称',exact=True).fill('Renamed favorites')
            page.get_by_role('button',name='保存名称',exact=True).click()
            page.get_by_text('检索：Renamed favorites',exact=True).wait_for()
            results.append('search management and rename')
            page.screenshot(path=str(args.evidence_dir/'desktop.png'),full_page=True)
            # Duplicate/conflict failures keep the name input.
            page.get_by_role('button',name='保存检索',exact=True).click()
            page.get_by_label('检索名称',exact=True).fill('Renamed favorites')
            page.locator('[data-saved-form=name]').get_by_role('button',name='保存检索',exact=True).click()
            page.locator('[data-saved-form=name] .form-error').filter(has_text='名称已存在').wait_for()
            assert page.get_by_label('检索名称',exact=True).input_value()=='Renamed favorites'
            page.get_by_role('button',name='关闭',exact=True).click()
            results.append('duplicate failure retains name')
            page.set_viewport_size({'width':390,'height':844})
            page.get_by_role('button',name='我的检索',exact=True).click()
            page.get_by_role('button',name='改名／更新').click()
            page.get_by_label('检索名称',exact=True).fill('Retained conflict name')
            current=api('/api/saved-searches/'+saved['id'],None,'GET')['body']
            assert api('/api/saved-searches/'+saved['id'],{'name':'Another window','version':current['version']},'PUT')['status']==200
            page.get_by_role('button',name='保存名称',exact=True).click()
            page.locator('[data-saved-form=name] .form-error').filter(has_text='其他窗口').wait_for()
            assert page.get_by_label('检索名称',exact=True).input_value()=='Retained conflict name'
            page.screenshot(path=str(args.evidence_dir/'narrow-conflict.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            results.append('narrow keyboard-accessible conflict retains input')
            page.get_by_role('button',name='返回我的检索',exact=True).click()
            page.get_by_role('button',name='删除',exact=True).click()
            page.get_by_text('确认删除个人检索“Another window”？',exact=True).wait_for()
            page.get_by_role('button',name='确认删除',exact=True).click()
            page.get_by_text('没有匹配的个人检索。',exact=True).wait_for()
            results.append('explicit named delete confirmation')
            # Change live filters, explicitly update the saved query, then save a second copy.
            page.set_viewport_size({'width':1366,'height':900})
            page.get_by_role('button',name='关闭',exact=True).click()
            page.goto(base+'/#library?q=Latvia')
            page.get_by_role('button',name='保存检索',exact=True).click()
            page.get_by_label('检索名称',exact=True).fill('Update candidate')
            page.locator('[data-saved-form=name]').get_by_role('button',name='保存检索',exact=True).click()
            page.get_by_text('检索：Update candidate',exact=True).wait_for()
            page.get_by_label('资料关键词',exact=True).fill('Unrelated')
            page.locator('[data-form=library-search]').get_by_role('button',name='搜索',exact=True).click()
            page.wait_for_url('**/*q=Unrelated*')
            page.get_by_role('button',name='我的检索',exact=True).click()
            page.get_by_role('button',name='改名／更新',exact=True).click()
            page.get_by_role('button',name='用当前条件更新',exact=True).click()
            page.get_by_text('检索：Update candidate',exact=True).wait_for()
            assert api('/api/saved-searches',None,'GET')['body']['items'][0]['conditions']=={'q':'Unrelated'}
            page.get_by_role('button',name='我的检索',exact=True).click()
            page.get_by_role('button',name='另存当前条件',exact=True).click()
            page.get_by_label('检索名称',exact=True).fill('Second query')
            page.locator('[data-saved-form=name]').get_by_role('button',name='保存检索',exact=True).click()
            page.get_by_text('检索：Second query',exact=True).wait_for()
            results.append('explicit update current conditions and save as independent search')
            saved_items=api('/api/saved-searches',None,'GET')['body']['items']
            slow_id=next(item['id'] for item in saved_items if item['name']=='Update candidate')
            fast_id=next(item['id'] for item in saved_items if item['name']=='Second query')
            # Hold an earlier network response until a later route has rendered.
            held=[]
            page.route('**/api/saved-searches/'+slow_id,lambda route:held.append(route))
            page.evaluate('(id)=>location.hash="#library?saved_search="+id',slow_id)
            page.wait_for_timeout(200)
            page.evaluate('(id)=>location.hash="#library?saved_search="+id',fast_id)
            page.get_by_text('检索：Second query',exact=True).wait_for()
            for request in held:request.continue_()
            page.wait_for_timeout(300)
            assert page.get_by_text('检索：Second query',exact=True).is_visible()
            page.unroute('**/api/saved-searches/'+slow_id)
            results.append('late earlier saved-search response cannot replace newer route')
            # Real editor navigation must preserve the existing personal draft.
            page.get_by_role('button',name='提交资料',exact=True).first.click()
            page.locator('form[data-draft-key]').wait_for()
            page.locator('input[name=title]').fill('Unsaved saved-search draft')
            page.evaluate('(id)=>location.hash="#library?saved_search="+id',fast_id)
            page.get_by_text('检索：Second query',exact=True).wait_for()
            page.goto(base+'/#drafts')
            page.get_by_text('Unsaved saved-search draft',exact=True).wait_for()
            results.append('editor draft retained during saved-search route switch')
            # Compilation/review entry points retain their effective implicit conditions.
            for route,name,expected in [('compilations','Compiled query',{'kind':'compilation'}),('review','Pending query',{'status':'pending'})]:
                page.goto(base+'/#'+route)
                page.get_by_role('button',name='保存检索',exact=True).click()
                page.get_by_label('检索名称',exact=True).fill(name)
                page.get_by_label('检索名称',exact=True).press('Enter')
                page.get_by_text('检索：'+name,exact=True).wait_for()
                found=api('/api/saved-searches',None,'GET')['body']['items']
                assert next(item for item in found if item['name']==name)['conditions']==expected
            results.append('compilation and review implicit conditions; keyboard save')
            # A previously shared collection becoming private must keep the scope and offer explicit adjustment.
            api('/api/login',{'username':'colleague','password':'LocalDemo2026!'})
            collection=api('/api/collections',{'name':'Revoked scope','visibility':'shared'})['body']['id']
            api('/api/login',{'username':'researcher','password':'LocalDemo2026!'})
            scoped=api('/api/saved-searches',{'name':'Scope to adjust','conditions':{'q':'Latvia','collection':collection}})['body']
            api('/api/login',{'username':'colleague','password':'LocalDemo2026!'})
            current=api('/api/collections/'+collection,None,'GET')['body']
            assert api('/api/collections/'+collection,{**current,'visibility':'private'},'PUT')['status']==200
            api('/api/login',{'username':'researcher','password':'LocalDemo2026!'})
            page.reload()
            page.goto(base+'/#library?saved_search='+scoped['id'])
            page.get_by_role('heading',name='检索范围暂不可用',exact=True).wait_for()
            assert not page.locator('.record-list').count()
            page.get_by_role('button',name='调整条件',exact=True).click()
            page.get_by_label('移除专题限制',exact=True).check()
            page.get_by_role('button',name='应用调整后的条件',exact=True).click()
            page.get_by_role('button',name='Latvia original',exact=True).wait_for()
            assert api('/api/saved-searches/'+scoped['id'],None,'GET')['body']['conditions']['collection']==collection
            results.append('revoked scope blocks results; explicit adjustment retains persisted original')
            # Account switch while a personal query response is held.
            page.goto(base+'/#library')
            page.get_by_role('button',name='我的检索',exact=True).wait_for()
            held=[]
            page.route('**/api/saved-searches/'+slow_id,lambda route:held.append(route))
            page.evaluate('(id)=>location.hash="#library?saved_search="+id',slow_id)
            page.wait_for_timeout(200)
            other=page.context.new_page()
            other.goto(base)
            other.evaluate("""async()=>{let s=await(await fetch('/api/session')).json();await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':s.csrf},body:JSON.stringify({username:'colleague',password:'LocalDemo2026!'})});new BroadcastChannel('zhihui-account').postMessage({user:'colleague'});} """)
            page.wait_for_timeout(300)
            for request in held:request.continue_()
            page.unroute('**/api/saved-searches/'+slow_id)
            page.goto(base+'/#library')
            page.get_by_role('button',name='我的检索',exact=True).click()
            page.get_by_text('没有匹配的个人检索。',exact=True).wait_for()
            results.append('account switch and stale personal response isolated')
            page.screenshot(path=str(args.evidence_dir/'final-account.png'),full_page=True)
            assert not errors,errors
            browser.close()
    finally:
        service.terminate();service.wait(timeout=10);log.close()
        (args.evidence_dir/'results.json').write_text(json.dumps({'checks':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False))

if __name__=='__main__':main()
