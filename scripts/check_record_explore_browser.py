"""#124 public HTTP and real-browser acceptance; owns only a fresh library on 8895.

Run: python scripts/check_record_explore_browser.py
Evidence and synthetic data stay in system Temp. Never imports research material.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
URL = 'http://127.0.0.1:8895'


def run():
    evidence = Path(tempfile.mkdtemp(prefix='database-record-explore-'))
    print('Evidence:', evidence, flush=True)
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', 8895)) != 0, '8895 occupied'
    log = (evidence / 'server.log').open('w', encoding='utf-8')
    server = subprocess.Popen([sys.executable, str(ROOT / 'app.py'), '--no-import',
        '--port', '8895', '--data-dir', str(evidence / 'data')], cwd=ROOT,
        stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        with sync_playwright() as pw:
            api = pw.request.new_context(base_url=URL)
            for _ in range(100):
                try:
                    if api.get('/health', timeout=500).ok:
                        break
                except Exception:
                    time.sleep(.1)
            def call(path, data, method='POST', client=api):
                token = client.get('/api/session').json()['csrf']
                response = client.fetch(path, method=method, data=data,
                    headers={'X-CSRF-Token': token})
                assert response.ok, (path, response.status, response.text())
                return response.json()
            call('/api/login', {'username': 'researcher', 'password': 'LocalDemo2026!'})
            publisher = call('/api/sources', {'name':'合成发布机构', 'kind':'institution'})['id']
            journal = call('/api/sources', {'name':'合成刊载期刊', 'kind':'journal'})['id']
            unit = call('/api/sources', {'name':'合成文章署名单位', 'kind':'institution'})['id']
            person = call('/api/people', {'name':'合成同名作者', 'change_note':'合成测试'})['id']
            rid = call('/api/records', {'title':'Explore 研究原文', 'kind':'report',
                'authors':'合成同名作者; 同名未确认', 'source_id':publisher, 'serial_id':journal,
                'abstract':'原始摘要用于验证阅读入口。', 'body_html':'<p>合成正文，用于测试阅读位置。</p>'*30})['id']
            by = api.get(f'/api/records/{rid}/bylines').json()
            call(f'/api/records/{rid}/bylines', {'version':by['version'],
                'record_version':by['record_version'], 'change_note':'合成人工确认', 'items':[
                {'raw_name':'合成同名作者', 'target_type':'person', 'target_id':person,
                    'status':'confirmed', 'evidence':'https://example.org/identity'},
                {'raw_name':'合成同名作者（同名未确认）', 'target_type':'person','target_id':person,'status':'pending'}]}, 'PUT')
            af = api.get(f'/api/records/{rid}/affiliations').json()
            call(f'/api/records/{rid}/affiliations', {'version':af['version'],
                'record_version':af['record_version'], 'byline_version':af['byline_version'],
                'change_note':'合成文章单位', 'items':[{'byline_id':af['bylines'][0]['id'],
                    'institution_id':unit, 'evidence':'https://example.org/article'}]}, 'PUT')
            outcome = call('/api/records', {'title':'可见中心成果', 'kind':'compilation',
                'author_id':'researcher', 'linked_ids':[rid], 'body_html':'<p>合成编译</p>'})['id']
            other = pw.request.new_context(base_url=URL)
            call('/api/login', {'username':'colleague', 'password':'LocalDemo2026!'}, client=other)
            hidden = call('/api/records', {'title':'不可泄露的隐藏成果', 'kind':'compilation',
                'author_id':'colleague', 'visibility':'restricted', 'linked_ids':[rid],
                'body_html':'<p>隐藏</p>'}, client=other)['id']
            revocable = call('/api/records', {'title':'稍后撤权的成果', 'kind':'compilation',
                'author_id':'colleague', 'linked_ids':[rid], 'body_html':'<p>合成成果</p>'}, client=other)['id']
            empty = call('/api/records', {'title':'Empty 无关系', 'kind':'report'})['id']
            for n in range(25):
                call('/api/records', {'title':f'Explore {n:02d}', 'kind':'report'})
            assert {r['id'] for r in api.get(f'/api/records/{rid}').json()['cited_by']} == {outcome, revocable}
            assert api.get(f'/api/records/{hidden}').status in (403,404)
            browser = pw.chromium.launch()
            context = browser.new_context(base_url=URL,storage_state=api.storage_state(), viewport={'width':1366,'height':900})
            page = context.new_page()
            page.set_default_timeout(6000)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def open_reader(record=rid, query='Explore'):
                page.goto(URL+'/#library?q='+query+'&sort=title'+('&page=2' if record==rid else ''))
                page.locator(f'[data-library-record="{record}"] [data-action="detail"]').first.click()
                expect(page.locator('.library-reader [data-reading-title]')).to_be_visible()
            open_reader()
            # Tracer bullet: discover confirmed authors and real source roles before prose.
            explorer = page.locator('.library-reader [data-record-explore]')
            expect(explorer.locator('summary')).to_have_text('关联探索')
            assert explorer.evaluate('(e)=>!!(e.compareDocumentPosition(document.querySelector("#ux-body")) & Node.DOCUMENT_POSITION_FOLLOWING)')
            explorer.locator('summary').focus()
            page.keyboard.press('Enter')
            expect(explorer).to_contain_text('已确认作者')
            expect(explorer).to_contain_text('合成同名作者')
            expect(explorer).to_contain_text('发布机构')
            expect(explorer).to_contain_text('刊载期刊')
            expect(explorer).to_contain_text('文章署名单位')
            expect(explorer).to_contain_text('同名未确认')
            expect(explorer.locator('[data-explore-target]')).to_have_count(6)
            assert '不可泄露' not in explorer.inner_text()
            # Real destinations and both explicit return and browser back retain context.
            explorer.locator(f'[data-explore-target][data-id="{person}"]').click()
            expect(page.locator('.person-page')).to_be_visible()
            page.get_by_role('button', name='返回资料', exact=True).click()
            expect(explorer).to_be_visible()
            expect(explorer).to_have_attribute('open', '')
            assert 'q=Explore' in page.url and 'sort=title' in page.url
            explorer.locator(f'[data-explore-target][data-id="{publisher}"]').click()
            expect(page.locator('.source-profile')).to_be_visible()
            page.go_back()
            expect(explorer).to_be_visible()
            explorer.locator(f'[data-explore-target][data-id="{outcome}"]').click()
            expect(page.locator('.library-reader [data-reading-title]')).to_have_text('可见中心成果')
            outcome_explorer=page.locator('.library-reader [data-record-explore]')
            outcome_explorer.locator('summary').click()
            expect(outcome_explorer).to_contain_text('本篇引用的原始资料')
            expect(outcome_explorer.locator(f'[data-explore-target][data-id="{rid}"]')).to_have_text('Explore 研究原文')
            page.get_by_role('button',name='返回前一篇：Explore 研究原文',exact=True).click()
            expect(page.locator('.library-reader [data-reading-title]')).to_have_text('Explore 研究原文')
            expect(explorer).to_have_attribute('open', '')
            assert 'q=Explore' in page.url
            assert 'page=2' in page.url
            # Permission changes affect the visible relationship projection immediately.
            version = other.get(f'/api/records/{revocable}').json()['version']
            call(f'/api/records/{revocable}', {'version':version,'visibility':'restricted'}, 'PUT', client=other)
            explorer.get_by_role('button',name='刷新关联',exact=True).click()
            expect(explorer.locator('[data-explore-target]')).to_have_count(5)
            expect(explorer).not_to_contain_text('稍后撤权')
            # A public HTTP failure is local to exploration and provides a retry.
            page.route(f'**/api/records/{rid}/bylines',lambda route:route.fulfill(status=503,json={'error':'Synthetic unavailable'}))
            explorer.get_by_role('button',name='刷新关联',exact=True).click()
            expect(explorer.get_by_role('alert')).to_contain_text('关联读取失败')
            expect(page.locator('#ux-body')).to_contain_text('合成正文')
            page.unroute(f'**/api/records/{rid}/bylines')
            explorer.get_by_role('button',name='重试读取关联',exact=True).click()
            expect(explorer.locator('[data-explore-target]')).to_have_count(5)
            # Resize and 200% browser zoom keep semantic links and keyboard controls usable.
            for name,width,scale in [('desktop',1366,1),('mobile',390,1),('small',320,1),('zoom-200',1366,2)]:
                page.set_viewport_size({'width':int(width/scale),'height':int(900/scale)})
                cdp=context.new_cdp_session(page)
                cdp.send('Emulation.setDeviceMetricsOverride',{'width':int(width/scale),'height':int(900/scale),'deviceScaleFactor':scale,'mobile':False})
                explorer.locator('summary').focus()
                page.keyboard.press('Tab')
                assert page.locator(':focus').get_attribute('data-explore-target') == ''
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), name
                page.evaluate('window.scrollTo(0,0)')
                page.screenshot(path=str(evidence/(name+'.png')),full_page=False)
                explorer.locator('[data-explore-target]').last.scroll_into_view_if_needed()
                page.screenshot(path=str(evidence/(name+'-relations.png')),full_page=False)
                cdp.detach()
            # Late responses cannot replace a newly opened article.
            page.set_viewport_size({'width':1366,'height':900})
            pending=[]
            page.route(f'**/api/records/{rid}/bylines',lambda route:pending.append(route))
            explorer.get_by_role('button',name='刷新关联',exact=True).click()
            page.wait_for_timeout(150)
            assert pending
            open_reader(empty,'Empty')
            new_explorer=page.locator('.library-reader [data-record-explore]')
            new_explorer.locator('summary').click()
            expect(new_explorer).to_contain_text('尚未登记可查看的关联')
            pending.pop().continue_()
            expect(new_explorer).not_to_contain_text('合成同名作者')
            page.unroute(f'**/api/records/{rid}/bylines')
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(evidence/'empty.png'),full_page=False)
            # Change the actual browser session while a relationship response waits.
            open_reader()
            explorer.locator('summary').click()
            expect(explorer.locator('[data-explore-target]')).to_have_count(5)
            page.route(f'**/api/records/{rid}/bylines',lambda route:pending.append(route))
            explorer.get_by_role('button',name='刷新关联',exact=True).click()
            page.wait_for_timeout(150)
            assert pending
            call('/api/login', {'username':'colleague','password':'LocalDemo2026!'},client=context.request)
            pending.pop().continue_()
            expect(explorer.get_by_role('alert')).to_contain_text('关联读取失败')
            expect(explorer.locator('[data-explore-target]')).to_have_count(0)
            page.unroute(f'**/api/records/{rid}/bylines')
            page.reload()
            expect(page.locator('.topbar')).to_contain_text('研究员 · 周')
            (evidence / 'result.json').write_text(json.dumps({'confirmed_identity_and_roles':True,
                'query_page_and_reader_return':True,'restricted_target_omission_and_revocation':True,
                'failure_retry_empty_late_response_account_switch':True,
                'viewports':['1366','390','320','200% equivalent 683 CSS pixels'],'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
            assert not errors, errors
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
        log.close()


if __name__ == '__main__':
    run()
