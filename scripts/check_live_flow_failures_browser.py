"""#141 module/worker recovery at the real HTTP+Chrome boundary; synthetic only."""
import argparse
import json
import logging
from pathlib import Path
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from platform_app import store
from tests.test_maintenance_agent import MaintenanceAgentTests
from live_flow_browser_policy import install,verify,verify_workers


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    output=args.evidence.resolve();output.mkdir(parents=True,exist_ok=False)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    fixture=MaintenanceAgentTests();fixture.setUp()
    jid=fixture.queue('failure-contract')
    db=store.connect(fixture.data_dir/'platform.sqlite3')
    with db:
        for position,name in [(1,'read'),(2,'finish')]:
            db.execute('INSERT INTO maintenance_steps VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (f'flow-step-{position}',jid,position,f'call-{position}',name,'{}','completed','{}','{}',store.now(),store.now()))
    db.close()
    empty_jid=fixture.queue('no-step-contract')
    server=make_server('127.0.0.1',0,fixture.app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    checks=[];violations=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            context=browser.new_context(viewport={'width':1366,'height':900})
            try:
                empty=context.new_page();install(empty);empty.goto(base+'/#maintenance-agent')
                empty.get_by_role('button',name='资料管理员',exact=True).click()
                empty.locator(f'[data-maintenance-select="{empty_jid}"]').click()
                expect(empty.locator('[data-trace-detail]')).to_contain_text('尚无执行步骤')
                expect(empty.locator('[data-flow-status]')).to_contain_text('尚无图节点')
                expect(empty.locator('[data-flow-slot]')).to_be_hidden()
                verify_workers(empty)
                db=store.connect(fixture.data_dir/'platform.sqlite3')
                with db:
                    db.execute("UPDATE maintenance_jobs SET status='running' WHERE id=?",(empty_jid,))
                    db.execute('INSERT INTO maintenance_steps VALUES(?,?,1,?,?,?,?,?,?,?,?)',('first-real-step',empty_jid,'first-call','read','{}','completed','{}','{}',store.now(),store.now()))
                db.close()
                empty.get_by_role('button',name='刷新状态',exact=True).click()
                expect(empty.locator('.react-flow__node')).to_have_count(1)
                expect(empty.locator('[data-flow-status]')).to_contain_text('流程图可点选')
                expect(empty.locator('[data-flow-slot]')).to_be_visible()
                assert empty.locator('[data-flow-command]').evaluate_all('buttons=>buttons.every(button=>!button.disabled)')
                verify_workers(empty);empty.close();checks.append('zero-step empty graph; actual first step restores graph, controls and true Worker')
                for failure in ['module','worker']:
                    page=context.new_page();install(page)
                    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                    blocked='**/static/vendor/visual/'+('flow.js' if failure=='module' else 'elk-worker.min.js')
                    page.route(blocked,lambda route:route.abort())
                    page.goto(base+'/#maintenance-agent')
                    if page.get_by_role('button',name='资料管理员',exact=True).count():page.get_by_role('button',name='资料管理员',exact=True).click()
                    page.locator(f'[data-maintenance-select="{jid}"]').click()
                    status=page.locator('[data-flow-status]')
                    expect(status).to_contain_text('未能加载' if failure=='module' else '排列失败',timeout=16000)
                    verify_workers(page)
                    expect(page.locator('[data-trace-step]')).to_have_count(2)
                    page.locator('[data-trace-step]').last.click()
                    expect(page.locator('[data-trace-detail]')).to_contain_text('此步记录处理结束')
                    page.unroute(blocked)
                    page.get_by_role('button',name='重试流程图',exact=True).click()
                    expect(page.locator('.react-flow__node')).to_have_count(2)
                    expect(status).to_contain_text('流程图可点选')
                    verify_workers(page)
                    graph_node=page.locator('.react-flow__node').first
                    graph_node.focus();page.keyboard.press('Enter')
                    expect(page.locator('[data-trace-step][aria-pressed=true]')).to_contain_text('读取当前内容')
                    page.screenshot(path=str(output/f'{failure}-recovered.png'),full_page=True)
                    violations.extend(verify(page));checks.append(f'{failure} failure retains equivalent text, retry loads actual module/Worker, named graph keyboard reads')
                    # Worker script loading failures can emit a native worker
                    # error, which is the intentionally exercised failure.
                    if failure=='module':assert not errors,errors
                    page.close()
            finally:context.close();browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5);fixture.doCleanups()
        (output/'result.json').write_text(json.dumps({'checks':checks,'policy_violations':violations,'server_closed':not thread.is_alive()},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':checks,'evidence':str(output)},ensure_ascii=False))


if __name__=='__main__':main()
