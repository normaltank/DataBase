"""Integrated workbench stages/closure at real browser seams; fresh synthetic data only."""
import argparse
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from platform_app.web import create_app
from scripts.check_collaboration_browser import no_overflow
from scripts.check_collaboration_recovery import login as account
from scripts.check_topic_finals_browser import call, serve
from scripts.verify_work_materials import verify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--case', choices=['all', 'phone'], default='all')
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=False)
    out = args.evidence
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app = create_app(out / 'data', testing=True)
    lead, author, admin = [account(app, who) for who in ('researcher', 'colleague', 'admin')]
    assert admin.put('/api/collaboration/qualifications/researcher', json={'version': 0, 'enabled': True}, headers={'X-CSRF-Token': admin.get('/api/session').json['csrf']}).status_code == 200
    observer = call(admin, '/api/members', {'username': 'observer', 'name': '无文章分工成员', 'password': 'LocalDemo2026!', 'role': 'researcher'})['id']
    extension = out / 'zoom-extension'
    extension.mkdir()
    (extension / 'manifest.json').write_text(json.dumps({'manifest_version': 3, 'name': 'Workbench actual zoom', 'version': '1.0', 'permissions': ['tabs'], 'background': {'service_worker': 'worker.js'}}))
    (extension / 'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
    server, thread, base = serve(app)
    result = {'cases': [], 'page_errors': []}
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(out / 'profile'), headless=False, ignore_default_args=['--disable-extensions'], args=['--headless=new', f'--disable-extensions-except={extension}', f'--load-extension={extension}'], viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page = context.pages[0]
            page.on('pageerror', lambda e: result['page_errors'].append(str(e)))
            expect.set_options(timeout=15000)
            def visit(who, tid, tab=''):
                page.goto(base)
                page.locator('[data-form=login], [data-action=logout]').first.wait_for(state='attached')
                if page.locator('[data-action=logout]').count():
                    page.locator('[data-action=logout]').click()
                    expect(page.get_by_label('账号', exact=True)).to_be_visible()
                page.get_by_label('账号', exact=True).fill(who)
                page.get_by_label('密码', exact=True).fill('LocalDemo2026!')
                page.get_by_role('button', name='查看资料', exact=True).click()
                expect(page.locator('[data-action=logout]')).to_be_visible()
                page.goto(base + f'/#collaboration?id={tid}' + ('&tab=' + tab if tab else ''))
                expect(page.locator('[data-collaboration-topic]')).to_be_visible()
            def file(locator, name, raw):
                locator.set_input_files({'name': name, 'mimeType': 'text/plain', 'buffer': raw})
            def snap(name):
                page.evaluate('window.scrollTo({top:0,left:0,behavior:"instant"})')
                page.wait_for_function('scrollY === 0')
                layout = no_overflow(page)
                if layout['width'] <= 700:
                    for action in page.locator('[data-action=topic-review-enter], [data-action=topic-closure-end], [data-action=topic-closure-reopen], .workbench-primary-actions .workbench-actions>summary').all():
                        if action.is_visible():
                            assert action.bounding_box()['height'] >= 44
                page.screenshot(path=str(out / (name + '.png')), full_page=True)
                return layout
            cases = ((390, 1),) if args.case == 'phone' else ((1440, 1), (1366, 1), (390, 1), (320, 1), (1366, 2))
            for width, zoom in cases:
                label = f'{width}-{zoom}'
                page.set_viewport_size({'width': width, 'height': 1000})
                tid = call(lead, '/api/collaboration/topics', {'theme': '并列交接阶段验收 ' + label, 'participant_ids': ['colleague', observer]})['id']
                root = '/api/collaboration/topics/' + tid
                visit('colleague', tid)
                worker.evaluate("async ({base,zoom})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(t.id,zoom)}", {'base': base, 'zoom': zoom})
                actual = worker.evaluate("async base=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));return chrome.tabs.getZoom(t.id)}", base)
                assert actual == zoom
                expect(page.locator('.workbench-detail-context')).to_contain_text('第一阶段：选题')
                file(page.get_by_label('选题报告文件 *', exact=True), '选题报告.txt', b'synthetic candidate original')
                page.get_by_role('button', name='提交为版本 1', exact=True).click()
                expect(page.get_by_role('link', name='下载原件 v1', exact=True)).to_be_visible()
                visit('researcher', tid)
                page.get_by_role('button', name='记录会议决定', exact=True).click()
                page.get_by_label('简短会议决定（可选）', exact=True).fill('讨论存档，尚未确认进入编译')
                page.get_by_role('button', name='保存会议决定 v1', exact=True).click()
                expect(page.locator('.workbench-detail-context')).to_contain_text('第一阶段：选题')
                assert not page.locator('[data-topic-manuscripts]').count()
                page.get_by_role('button', name='修改会议决定', exact=True).click()
                for index in range(2):
                    page.get_by_role('button', name='添加采用文章', exact=True).click()
                    row = page.locator('[data-assignment-row]').nth(index)
                    row.get_by_label('题名或报告项目 *', exact=True).fill('文章 ' + str(index + 1) + '：' + '跨国资料与可核查出处' * 7)
                    row.get_by_label('编译研究员 *', exact=True).select_option('colleague')
                    row.get_by_label('出处或站外链接（可选）', exact=True).fill('https://example.invalid/' + str(index))
                page.get_by_role('button', name='保存会议决定 v2', exact=True).click()
                expect(page.locator('.workbench-detail-context')).to_contain_text('第一阶段：选题')
                assert not page.get_by_role('button', name='稿件与审稿', exact=True).count()
                snap(label + '-selection-with-assignments')
                page.get_by_role('button', name='确认分工，进入编译阶段', exact=True).click()
                expect(page.get_by_role('dialog')).to_contain_text('研究员 · 周')
                page.get_by_role('button', name='确认以上分工，进入编译', exact=True).click()
                expect(page.locator('.workbench-detail-context')).to_contain_text('第二阶段：编译')
                aids = [a['id'] for a in lead.get(root + '/workflow').json['assignments']]
                visit('colleague', tid)
                expect(page.locator('.workbench-manuscripts tbody tr')).to_have_count(2)
                file(page.get_by_label('编译稿文件 *', exact=True), '编译稿v1.txt', b'draft v1')
                page.get_by_role('button', name='提交编译稿 v1', exact=True).click()
                expect(page.locator('[data-assignment-card]')).to_contain_text('待审')
                page.locator('[data-action=workbench-assignment]').nth(1).click()
                expect(page.locator('[data-assignment-card]')).to_have_attribute('data-assignment-card', aids[1])
                file(page.get_by_label('编译稿文件 *', exact=True), '另一篇.txt', b'other draft v1')
                page.get_by_role('button', name='提交编译稿 v1', exact=True).click()
                visit('researcher', tid)
                page.get_by_text('退回修改 · 针对版本 1', exact=True).click()
                page.get_by_label('退回意见', exact=True).fill('请补页码')
                page.get_by_role('button', name='退回版本 1', exact=True).click()
                expect(page.locator('[data-assignment-card]')).to_contain_text('返修')
                visit('colleague', tid)
                page.get_by_text('提交我的编译稿 · 新版本 2', exact=True).click()
                file(page.get_by_label('编译稿文件 *', exact=True), '编译稿v2.txt', b'draft exact v2')
                page.get_by_role('button', name='提交编译稿 v2', exact=True).click()
                visit('researcher', tid)
                page.get_by_role('button', name='确认当前稿件定稿', exact=True).click()
                page.get_by_role('button', name='确认稿件 v2 为定稿', exact=True).click()
                page.get_by_role('button', name='成果', exact=True).click()
                expect(page.locator('[data-topic-single-finals]')).to_contain_text('定稿 v2')
                page.get_by_role('button', name='提交整期汇总', exact=True).click()
                file(page.get_by_label('整期汇总文件 *', exact=True), '汇总.txt', b'summary adopts exact v2')
                page.get_by_role('dialog').locator('[name=final_ids]').check()
                page.get_by_role('button', name='保存整期汇总 v1', exact=True).click()
                expect(page.get_by_role('heading', name='整期汇总 v1', exact=True)).to_be_visible()
                snap(label + '-finals-and-summary')
                page.get_by_role('button', name='结束本期', exact=True).click()
                expect(page.get_by_role('dialog')).to_contain_text('待审')
                page.get_by_role('button', name='确认结束本期', exact=True).click()
                expect(page.locator('[data-topic-closed]')).to_be_visible()
                assert not page.locator('input[type=file]').count()
                assert not page.locator('[data-action=collaboration-edit],[data-action=topic-review-meeting],[data-action=topic-finals-summary],[data-action=topic-finals-confirm]').count()
                snap(label + '-closed-readonly')
                visit('colleague', tid, 'products')
                expect(page.locator('[data-topic-closed]')).to_be_visible()
                assert not page.get_by_role('button', name='重新开启本期', exact=True).count()
                with page.expect_download() as event:
                    page.get_by_role('link', name='下载定稿 v2', exact=True).click()
                assert Path(event.value.path()).read_bytes() == b'draft exact v2'
                page.get_by_text('下载本期材料包', exact=True).click()
                with page.expect_download() as event:
                    page.get_by_role('link', name='全部已提交材料', exact=True).click()
                package = out / (label + '-closed.zip')
                event.value.save_as(str(package)); verify(package)
                visit('admin', tid)
                assert not page.locator('[data-action=topic-closure-reopen],[data-action=topic-closure-end]').count()
                visit('researcher', tid)
                page.get_by_role('button', name='重新开启本期', exact=True).click()
                page.get_by_role('button', name='确认重新开启', exact=True).click()
                expect(page.locator('[data-topic-closed]')).to_have_count(0)
                expect(page.locator('.workbench-detail-context')).to_contain_text('第二阶段：编译')
                visit('observer', tid)
                expect(page.get_by_text('当前尚无文章分工，请联系负责人。', exact=True)).to_be_visible()
                assert not page.get_by_role('button', name='我的编译分工', exact=True).count()
                page.get_by_text('补充前期材料', exact=True).click()
                page.get_by_role('button', name='补充选题材料', exact=True).click()
                file(page.get_by_label('选题报告文件 *', exact=True), '补选题.txt', b'observer supplement')
                page.get_by_role('button', name='提交为版本 1', exact=True).click()
                expect(page.get_by_role('link', name='下载原件 v1', exact=True)).to_have_count(2)
                layout = snap(label + '-reopened-supplement')
                assert lead.get(root + '/workflow').json['summaries'][0]['adoptions'][0]['version'] == 2
                assert lead.get(root).json['stage_events'][0]['meeting_version'] == 2
                if width == 1440:
                    # End an open manuscript from another session; bytes and note survive.
                    visit('colleague', tid)
                    page.locator('[data-action=workbench-assignment]').first.click()
                    page.get_by_text('提交我的编译稿 · 新版本 3', exact=True).click()
                    control = page.get_by_label('编译稿文件 *', exact=True)
                    file(control, '重开后继续.txt', b'preserved draft v3')
                    page.get_by_label('交稿说明（可选）', exact=True).fill('保留旧表单说明')
                    preview = lead.get(root + '/closure-preview').json
                    call(lead, root + '/end', {'request_id': 'stale-form-close', 'lifecycle_version': preview['lifecycle_version'], 'basis_token': preview['basis_token'], 'confirm': True})
                    page.get_by_role('button', name='提交编译稿 v3', exact=True).click()
                    expect(page.locator('[data-topic-review-conflict]')).to_contain_text('本期已结束')
                    expect(page.get_by_label('交稿说明（可选）', exact=True)).to_have_value('保留旧表单说明')
                    assert control.evaluate('e=>e.files[0].name') == '重开后继续.txt'
                    call(lead, root + '/reopen', {'request_id': 'stale-form-reopen', 'lifecycle_version': lead.get(root).json['lifecycle_version']})
                    page.get_by_role('button', name='已核对，保留输入继续交接', exact=True).click()
                    page.get_by_role('button', name='提交编译稿 v3', exact=True).click()
                    expect(page.locator('[data-assignment-card]')).to_contain_text('待审')
                    assert lead.get(root + '/workflow').json['summaries'][0]['adoptions'][0]['version'] == 2
                    snap(label + '-old-form-preserved-reopened')
                    # Closing selection also locks candidate/meeting controls and reopens selection.
                    selection = call(lead, '/api/collaboration/topics', {'theme': '选题期结束重开', 'participant_ids': ['colleague']})['id']
                    visit('researcher', selection)
                    page.get_by_role('button', name='结束本期', exact=True).click()
                    page.get_by_role('button', name='确认结束本期', exact=True).click()
                    expect(page.locator('[data-topic-closed]')).to_be_visible()
                    assert not page.locator('input[type=file], [data-action=topic-review-meeting]').count()
                    page.get_by_role('button', name='重新开启本期', exact=True).click()
                    page.get_by_role('button', name='确认重新开启', exact=True).click()
                    expect(page.locator('.workbench-detail-context')).to_contain_text('第一阶段：选题')
                    expect(page.get_by_label('选题报告文件 *', exact=True)).to_be_visible()
                result['cases'].append({'width': width, 'zoom': actual, 'layout': layout, 'topic': tid, 'candidate_meeting_explicit_stage_two_assignments_return_revise_final_summary_close_readonly_reopen_supplement': True})
            assert not result['page_errors'], result['page_errors']
            context.close()
    finally:
        server.shutdown(); thread.join(timeout=5); server.server_close()
        (out / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'evidence': str(out), **result}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
