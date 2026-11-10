"""#144 cross-account native File recovery through ordinary UI and real HTTP."""
import argparse
from email import message_from_bytes
import json
import logging
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from platform_app.web import create_app
from tests.test_topic_handoffs import HandoffTests
from live_flow_browser_policy import install as strict_policy, verify as verify_policy


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence', required=True)
    args=parser.parse_args()
    evidence=Path(args.evidence).resolve();evidence.mkdir(parents=True,exist_ok=False)
    checks={};captures=[];errors=[];attempts=[]
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    def capture(page,name):
        expect(page.locator('#toast')).to_have_css('opacity','0',timeout=7000)
        page.screenshot(path=str(evidence/name))
        captures.append({'path':name, 'viewport':page.viewport_size,
                         'position':page.evaluate('({x:scrollX,y:scrollY,readerY:document.querySelector(".library-reader")?.scrollTop||0})'),
                         'focus':page.locator(':focus').evaluate_all('els=>els.map(e=>e.getAttribute("aria-label")||e.textContent)')})
    with tempfile.TemporaryDirectory(prefix='repair144-recovery-') as temporary, patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('External provider forbidden')):
        fixture=HandoffTests();fixture.app=create_app(Path(temporary)/'data',testing=True,embedded_worker=False)
        fixture.clients={name:fixture.login(name) for name in ('researcher','colleague','admin')}
        tid=fixture.topic(theme='合成 · 跨账号保稿恢复')
        material=fixture.upload(tid,who='colleague').json['material_ref']
        server=make_server('127.0.0.1',0,fixture.app,threaded=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(headless=True)
                try:
                    context=browser.new_context(viewport={'width':1280,'height':720},reduced_motion='reduce')
                    strict_policy(context)
                    context.on('page',lambda p:p.on('pageerror',lambda error:errors.append(str(error))))
                    page=context.new_page()
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(base+f'/#collaboration?id={tid}&tab=selection')
                    page.get_by_role('button',name='研究员',exact=True).click()
                    card=page.locator(f'[data-material-ref="{material}"]')
                    form=card.locator('[data-form=handoff-review]')
                    version=form.get_attribute('data-version')
                    form.locator('summary').click()
                    form.locator('[name=note]').fill('账号 A 留在原版本的意见')
                    form.locator('[name=file]').set_input_files({'name':'account-a.txt','mimeType':'text/plain','buffer':b'KEEP ACCOUNT A ORIGINAL FILE'})
                    def unknown(route):
                        request=route.request
                        message=message_from_bytes(('Content-Type: '+request.headers['content-type']+'\r\n\r\n').encode()+request.post_data_buffer)
                        attempts.append([(part.get_param('name',header='content-disposition'),part.get_filename(),part.get_payload(decode=True)) for part in message.walk() if part.get_content_disposition()=='form-data'])
                        if len(attempts)==1:route.abort('failed')
                        else:route.continue_()
                    page.route('**/handoff-reviews',unknown)
                    form.get_by_role('button',name='退回',exact=True).click()
                    expect(form.locator('.form-error')).to_contain_text('重试')
                    page.route('**/api/client-revision',lambda route:route.fulfill(json={'revision':'synthetic-next'}))
                    page.evaluate("document.dispatchEvent(new Event('client:check'))")
                    update=page.get_by_role('button',name='更新页面',exact=True)
                    expect(update).to_be_visible();capture(page,'update-notice-1280x720.png')
                    update.click();expect(form.locator('[name=note]')).to_have_value('账号 A 留在原版本的意见')
                    capture(page,'update-unknown-error-1280x720.png')
                    page.get_by_role('button',name='退出登录',exact=True).click()
                    page.get_by_role('button',name='资料管理员',exact=True).click()
                    expect(page.locator('.workbench-account-link[data-id=personal]')).to_contain_text('管理')
                    expect(page.locator('input[type=file]')).to_have_count(0)
                    update.click()
                    recovery=page.get_by_role('link',name='新页继续（保留本页）',exact=True)
                    expect(recovery).to_be_visible()
                    expect(page.get_by_role('complementary',name='页面更新')).to_contain_text('其他账号的草稿')
                    assert recovery.get_attribute('target')=='_blank'
                    assert recovery.get_attribute('rel')=='noopener'
                    capture(page,'cross-account-recovery-1280x720.png')
                    page.set_viewport_size({'width':515,'height':791});recovery.focus()
                    capture(page,'cross-account-recovery-515x791.png')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                    page.set_viewport_size({'width':320,'height':844})
                    capture(page,'cross-account-recovery-320x844.png')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                    page.set_viewport_size({'width':515,'height':791})
                    with context.expect_page() as popup:
                        recovery.click()
                    fresh=popup.value
                    fresh.on('pageerror',lambda error:errors.append(str(error)))
                    try:
                        expect(fresh.locator('.workbench-account-link[data-id=personal]')).to_contain_text('管理')
                    except AssertionError:
                        print(json.dumps({'fresh_url':fresh.url,'body':fresh.locator('body').inner_text(),'errors':errors},ensure_ascii=False),flush=True)
                        raise
                    assert fresh.request.get(base+'/api/session').json()['user']['username']=='admin'
                    expect(fresh.locator('input[type=file]')).to_have_count(0)
                    fresh.goto(base+'/#library?feed=all')
                    expect(fresh.locator('.library-workspace')).to_be_visible()
                    expect(fresh.get_by_role('status').filter(has_text='正在读取当前查询的分布')).to_have_count(0)
                    assert not fresh.evaluate('clientHasDraft()')
                    checks['fresh_page_policy']=verify_policy(fresh)
                    capture(fresh,'updated-account-b-1280x720.png')
                    checks['b_continues_updated_site_without_a_draft']=True
                    # A's original DOM and unknown multipart stay in the old page.
                    page.get_by_role('button',name='退出登录',exact=True).click()
                    page.get_by_role('button',name='研究员',exact=True).click()
                    expect(form).to_have_attribute('data-version',version)
                    expect(form.locator('[name=note]')).to_have_value('账号 A 留在原版本的意见')
                    assert form.locator('[name=file]').evaluate('e=>e.files[0].name')=='account-a.txt'
                    expect(form.locator('.form-error')).to_contain_text('重试')
                    restored_notice=page.get_by_role('complementary',name='页面更新')
                    expect(restored_notice).not_to_contain_text('其他账号的草稿')
                    expect(restored_notice.locator('[data-client-continue]')).to_have_count(0)
                    expect(update).to_be_visible()
                    update.click()
                    expect(page.locator('#toast')).to_contain_text('未提交')
                    expect(form.locator('[name=note]')).to_have_value('账号 A 留在原版本的意见')
                    assert form.locator('[name=file]').evaluate('e=>e.files[0].name')=='account-a.txt'
                    checks['restored_a_update_notice_matches_current_identity']=True
                    form.scroll_into_view_if_needed()
                    capture(page,'account-a-restored-original-draft.png')
                    form.get_by_role('button',name='退回',exact=True).click()
                    expect(card.locator(':scope>.between>.badge')).to_have_text('当前版 1 · 退回')
                    assert len(attempts)==2 and attempts[0]==attempts[1]
                    checks['a_normal_login_restores_same_version_file_note_unknown_request']=True
                    assert not page.evaluate('clientHasDraft()')
                    route_before=page.url
                    with page.expect_navigation(wait_until='load'):
                        page.get_by_role('button',name='更新页面',exact=True).click()
                    expect(page.locator('.workbench-account-link[data-id=personal]')).to_contain_text('研究员')
                    assert page.url==route_before
                    expect(page.get_by_role('complementary',name='页面更新')).to_have_count(0)
                    capture(page,'updated-clean-same-route.png')
                    checks['clean_explicit_update_preserves_route_query']=True
                    checks['policy']=verify_policy(page)
                    assert not errors,errors
                finally:browser.close()
        finally:
            server.shutdown();server.server_close();thread.join(5)
            (evidence/'result.json').write_text(json.dumps({'checks':checks,'captures':captures,'errors':errors,'paid_calls':0,'embedded_worker':False,'base':base,'server_thread_stopped':not thread.is_alive()},ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
