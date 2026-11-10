"""Two reported desk regressions: concrete original scope and local-only host entry."""
import argparse,json,sys,tempfile,threading,subprocess
from pathlib import Path
from werkzeug.serving import make_server,WSGIRequestHandler
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from platform_app.web import create_app
class Quiet(WSGIRequestHandler):
    def log_request(self,*a,**k):pass

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--evidence',type=Path);args=ap.parse_args()
    out=args.evidence or Path(tempfile.mkdtemp(prefix='desk-access-synthetic-'));out.mkdir(parents=True,exist_ok=True)
    checks=[]
    app=create_app(out/'synthetic-data',testing=True,embedded_worker=False,portable_trial=True)
    # The actual session endpoint decides admission; the LAN browser uses that
    # response without changing the application's host-eligibility logic.
    lan=app.test_client();lan_session=lan.get('/api/session',environ_overrides={'REMOTE_ADDR':'192.0.2.10'}).json
    assert not lan_session['host_available']
    denied=lan.post('/api/trial/host',json={},headers={'X-CSRF-Token':lan_session['csrf']},environ_overrides={'REMOTE_ADDR':'192.0.2.10'})
    assert denied.status_code==403
    server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            dom=browser.new_page();dom.set_content('<article class="handoff-material"><div class="handoff-version" id="current"><strong>CURRENT.txt</strong><button data-version="current">查看内容</button><details class="desk-file-meta"></details></div><details open><summary>接续的旧材料</summary><div class="handoff-version" id="source"><strong>SOURCE.txt</strong><button data-version="source">查看内容</button><details class="desk-file-meta"></details></div></details></article>')
            source=(ROOT/'static/desk.js').read_text(encoding='utf-8').split('async function deskPreview',1)[0]
            dom.add_script_tag(content='function esc(s){return s.replaceAll("<","&lt;")}\n'+source)
            dom.evaluate('deskRenderPreview(document.querySelector("#current button"),{status:"ready",name:"CURRENT.txt",segments:[{text:"CURRENT BODY"}]})')
            dom.evaluate('deskRenderPreview(document.querySelector("#source button"),{status:"ready",name:"SOURCE.txt",segments:[{text:"SOURCE BODY"}]})')
            expect(dom.locator('#current [data-desk-preview]')).to_have_text('CURRENT BODY')
            expect(dom.locator('#source [data-desk-preview]')).to_have_text('SOURCE BODY')
            checks.append('Standards P2: actual deskRenderPreview keeps current/source concrete .handoff-version text separate')
            page=browser.new_page();page.goto(base+'/#library?feed=all&q=synthetic-return')
            expect(page.locator('.desk-header')).to_be_visible()
            session=page.request.get(base+'/api/session').json();assert session['host_available'] and session['user']['temporary'];actor=session['user']['id'];original=page.url.split('#',1)[1]
            expect(page.locator('.desk-header')).to_be_visible();page.locator('[popovertarget=desk-personal]').click()
            expect(page.locator('#desk-personal [data-action=trial-host]')).to_be_visible()
            page.screenshot(path=str(out/'local-host-entry.png'))
            page.locator('#desk-personal [data-action=trial-host]').click();expect(page.locator('body')).to_have_attribute('data-page','system')
            page.locator('[popovertarget=desk-personal]').click();page.get_by_role('button',name='返回研究身份',exact=True).click()
            expect(page.locator('body')).to_have_attribute('data-page','library');assert page.url.split('#',1)[1]==original
            assert page.request.get(base+'/api/session').json()['user']['id']==actor
            checks.append('Spec P2: local temporary researcher personal menu enters host maintenance and returns same actor/query without logout')
            remote_context=browser.new_context();remote_context.add_cookies([{'name':'session','value':lan.get_cookie('session').value,'url':base}]);remote=remote_context.new_page();remote.route('**/api/session',lambda route:route.fulfill(json=lan_session));remote.goto(base+'/#collaboration');expect(remote.locator('.desk-header')).to_be_visible();remote.locator('[popovertarget=desk-personal]').click();expect(remote.locator('[data-action=trial-host]')).to_have_count(0);remote.screenshot(path=str(out/'lan-no-host-entry.png'))
            checks.append('LAN session host_available=false has no host entry; actual LAN POST /api/trial/host remains403')
            browser.close()
    finally:server.shutdown();server.server_close()
    (out/'result.json').write_text(json.dumps({'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'checks':checks,'worker':False,'base':base},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(checks,ensure_ascii=False))
if __name__=='__main__':main()
