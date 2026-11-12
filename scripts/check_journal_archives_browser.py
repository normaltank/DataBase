"""Real journal archive journeys on isolated synthetic data at1366 and390.

No source acquisition, model calls, real research database or sample PDF input.
"""
import argparse
import io
import json
import logging
import os
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler
from tests.test_journal_archives import JournalArchiveTests


class Quiet(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')


def login(page, base, user):
    page.goto(base)
    page.get_by_label('账号', exact=True).fill(user)
    page.get_by_label('密码', exact=True).fill('LocalDemo2026!')
    page.get_by_role('button', name='查看资料', exact=True).click()
    expect(page.locator('[data-action="nav"][data-id="collaboration"]')).to_be_attached()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args()
    out = args.evidence.resolve()
    out.mkdir(parents=True, exist_ok=True)
    fixture = JournalArchiveTests()
    fixture.setUp()
    original_id = fixture.call('/api/records', {'title': 'Synthetic linked original', 'kind': 'journal_article',
                            'serial_id': fixture.journal, 'volume': '2', 'issue': '1', 'published_on': '2024',
                            'abstract': 'Synthetic original abstract for browser reading.',
                            'body_html': '<p>Original paragraph for the synthetic journal journey.</p>'}).json['id']
    original = fixture.get('/api/records/' + original_id)
    second = fixture.issue(label='Synthetic combined 2025 issue', year='2025', number='2—3', coverage='unverified')
    personal = fixture.compilation(kind='compilation', title='Synthetic personal author-controlled compilation')
    restricted = fixture.compilation(kind='compilation', title='Hidden synthetic personal compilation', visibility='restricted')
    image = io.BytesIO()
    Image.new('RGB', (200, 260), '#234e78').save(image, format='PNG')
    server = make_server('127.0.0.1', 0, fixture.app, threaded=True, request_handler=Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:' + str(server.server_port)
    errors, checks = [], []
    try:
        p = sync_playwright().start()
        if True:
            browser = p.chromium.launch(headless=True, **({'executable_path': os.environ['DATABASE_BROWSER_EXECUTABLE']} if os.environ.get('DATABASE_BROWSER_EXECUTABLE') else {}))
            for width in [1366, 390]:
                context = browser.new_context(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                colleague_context = browser.new_context(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                page, colleague = context.new_page(), colleague_context.new_page()
                for tab in [page, colleague]:
                    tab.set_default_timeout(15000)
                    tab.on('pageerror', lambda error: errors.append(str(error)))
                login(page, base, 'researcher')
                page.goto(base + '/#sources?group=journal')
                page.get_by_role('link', name='Synthetic archive journal', exact=True).click()
                expect(page.get_by_role('heading', name='Synthetic archive journal', exact=True)).to_be_visible()
                page.get_by_role('link', name='维护期刊信息与指标', exact=True).click()
                page.get_by_label('创刊时间（保留实际精度）', exact=True).fill('1980年代（合成）')
                page.get_by_label('纸本 ISSN', exact=True).fill('1111-1111')
                cover = page.locator('.ja-edit-section').filter(has=page.locator('[data-ja-cover]'))
                cover.locator('summary').click()
                cover.get_by_label('上传封面图片（JPEG／PNG／WebP）', exact=True).set_input_files({'name': 'synthetic.png', 'mimeType': 'image/png', 'buffer': image.getvalue()})
                cover.get_by_label('封面出处', exact=True).fill('Program-created synthetic blue cover; no real publication.')
                cover.get_by_label('这是示意图，不代表当前卷期', exact=True).check()
                page.get_by_role('button', name='添加影响因子记录', exact=True).click()
                metric = page.locator('[data-ja-metric]').last
                metric.get_by_label('数值（缺失留空，零值填0）', exact=True).fill('0')
                metric.get_by_label('指标年度（未知留空）', exact=True).fill('2024')
                metric.get_by_label('指标出处', exact=True).fill('Synthetic indicator statement; demonstration only.')
                no_overflow(page)
                page.get_by_role('button', name='保存期刊信息', exact=True).click()
                page.wait_for_timeout(800)
                if page.locator('.ja-metric-value').count() == 0:
                    page.screenshot(path=str(out / 'failure.png'), full_page=True)
                    (out / 'failure.html').write_text(page.content(), encoding='utf-8')
                    print(json.dumps({'errors': errors, 'form_error': page.locator('.form-error').all_text_contents()}, ensure_ascii=False))
                expect(page.locator('.ja-metric-value').last).to_contain_text('0')
                expect(page.get_by_alt_text('期刊封面', exact=True)).to_be_visible()
                page.screenshot(path=str(out / f'journal-{width}.png'), full_page=True)
                page.get_by_role('link', name='登记原刊卷期', exact=True).click()
                page.get_by_label('原刊卷期标识／已知范围', exact=True).fill(f'Synthetic browser issue {width}')
                page.get_by_label('原刊年份', exact=True).fill('2024')
                page.get_by_label('原刊卷号', exact=True).fill('2')
                page.get_by_label('原刊期号', exact=True).fill('1')
                page.get_by_label('目次覆盖', exact=True).select_option('complete')
                page.get_by_label('原目次出处（完整目次必填）', exact=True).fill('https://example.invalid/synthetic/complete-toc')
                page.get_by_role('button', name='添加栏目', exact=True).click()
                page.get_by_label('栏目原名', exact=True).fill('Research articles')
                page.get_by_role('button', name='添加目次条目', exact=True).click()
                entry = page.locator('[data-ja-entry-row]')
                entry.get_by_label('原文题名 *', exact=True).fill('Synthetic linked original')
                entry.get_by_label('原始署名', exact=True).fill('Unresolved synthetic byline')
                entry.locator('summary').click()
                entry.get_by_label('查找已有资料', exact=True).fill('Synthetic linked original')
                entry.get_by_role('button', name='查找已有资料', exact=True).click()
                entry.locator('[data-ja="choose-record"]').click()
                entry.get_by_label('本期归属依据', exact=True).fill('Synthetic original contents evidence')
                page.get_by_role('button', name='保存卷期与目次', exact=True).click()
                expect(page.get_by_role('heading', name=f'Synthetic browser issue {width}', exact=True)).to_be_visible()
                issue_url = page.url
                page.get_by_role('button', name='阅读已入库资料', exact=True).scroll_into_view_if_needed()
                y = page.evaluate('scrollY')
                page.get_by_role('button', name='阅读已入库资料', exact=True).click()
                expect(page.locator('.ux-reading-article')).to_be_visible()
                page.locator('#modal-root [data-action="close"]').first.click()
                expect(page.locator('.ux-reading-article')).to_have_count(0)
                assert abs(page.evaluate('scrollY') - y) < 4
                no_overflow(page)
                page.screenshot(path=str(out / f'contents-{width}.png'), full_page=True)
                page.get_by_role('link', name='维护卷期与目次', exact=True).click()
                page.get_by_label('原刊期号', exact=True).fill('9')
                page.get_by_role('button', name='保存卷期与目次', exact=True).click()
                expect(page.locator('.form-error')).to_contain_text('冲突')
                expect(page.get_by_label('原文题名 *', exact=True)).to_have_value('Synthetic linked original')
                page.get_by_role('button', name='继续核对当前输入', exact=True).click()
                page.get_by_label('题录差异核对说明', exact=True).fill('Synthetic checked discrepancy: keep original issue 1 and declared issue 9.')
                page.get_by_role('button', name='保存卷期与目次', exact=True).click()
                page.get_by_role('link', name='返回期刊档案', exact=True).click()
                page.get_by_role('link', name='新建目录译稿', exact=True).click()
                page.get_by_label('译稿题名 *', exact=True).fill(f'Synthetic cross-issue draft {width}')
                page.get_by_label('编译者署名 *', exact=True).fill('Synthetic compiler')
                page.get_by_label('年份／卷期／跨期覆盖范围 *', exact=True).fill('2024—2025 multiple issues')
                page.locator('[data-rich-input]').fill('Synthetic whole manuscript retained before structured compilation.')
                page.get_by_role('button', name='保存整体目录译稿', exact=True).click()
                expect(page.get_by_role('heading', name='选编内容与原文依据', exact=True)).to_be_visible()
                edit_url = page.url
                page.get_by_label(f'Synthetic browser issue {width}', exact=True).check()
                page.get_by_label('Synthetic combined 2025 issue', exact=True).check()
                page.get_by_role('button', name='添加选编内容', exact=True).click()
                selection = page.locator('[data-ja-selection]')
                issue_id = issue_url.split('ja_issue=')[1].split('&')[0]
                archive = fixture.get(fixture.base)
                issue = next(i for i in archive['issues'] if i['id'] == issue_id)
                entry_id = issue['sections'][0]['entries'][0]['id']
                selection.get_by_label('所选目次', exact=True).select_option(issue_id + ':' + entry_id)
                selection.get_by_label('内容类别', exact=True).select_option('abstract_translation')
                selection.get_by_label('编译／录入署名 *', exact=True).fill('Synthetic compiler')
                selection.locator('[data-rich-input]').fill('合成摘要译文，只作操作演示。')
                selection.get_by_label('所据入库资料编号', exact=True).fill(original_id)
                selection.get_by_label('所据资料版本', exact=True).fill(str(original['version']))
                selection.get_by_label('原文位置', exact=True).fill('Abstract, first paragraph')
                page.get_by_role('button', name='保存选编内容', exact=True).click()
                expect(page.locator('.ja-selected-content')).to_contain_text('合成摘要译文')
                page.get_by_role('link', name='编写选编内容与原文依据', exact=True).click()
                page.get_by_label('编译、审校等署名（不改变账号授权）', exact=True).fill('Researcher current input must survive conflict')
                login(colleague, base, 'colleague')
                colleague.goto(edit_url)
                colleague.get_by_label('编译、审校等署名（不改变账号授权）', exact=True).fill('Colleague saved revision')
                colleague.get_by_role('button', name='保存选编内容', exact=True).click()
                expect(colleague.locator('.ja-selected-content')).to_contain_text('合成摘要译文')
                page.get_by_role('button', name='保存选编内容', exact=True).click()
                expect(page.locator('.form-error')).to_contain_text('新版本')
                expect(page.get_by_label('编译、审校等署名（不改变账号授权）', exact=True)).to_have_value('Researcher current input must survive conflict')
                page.get_by_role('button', name='读取最新版本并对照，保留当前输入', exact=True).click()
                expect(page.locator('[data-ja-conflict]')).to_contain_text('Colleague saved revision')
                no_overflow(page)
                page.screenshot(path=str(out / f'conflict-{width}.png'), full_page=True)
                page.get_by_role('button', name='我已对照，继续编辑当前输入', exact=True).click()
                page.get_by_role('button', name='保存选编内容', exact=True).click()
                expect(page.locator('.ja-facts').first).to_contain_text('Researcher current input must survive conflict')
                page.get_by_role('link', name='选编与依据历史', exact=True).click()
                page.locator('.ja-history').first.locator('summary').first.click()
                no_overflow(page)
                page.screenshot(path=str(out / f'history-{width}.png'), full_page=True)
                colleague.goto(base + '/#sources?' + 'id=' + fixture.journal + '&ja_compilation=' + personal['id'] + '&ja_edit=compilation')
                expect(colleague.locator('.journal-archive')).to_contain_text('当前内容只供阅读')
                expect(colleague.locator('[data-ja-form]')).to_have_count(0)
                colleague.goto(base + '/#sources?' + 'id=' + fixture.journal + '&ja_compilation=' + restricted['id'])
                expect(colleague.get_by_role('heading', name=restricted['title'], exact=True)).to_have_count(0)
                expect(colleague.locator('[data-ja-form]')).to_have_count(0)
                checks.append({'width': width, 'article_return_position': True, 'conflict_inputs_preserved': True,
                               'cross_issue_compilation': True, 'unauthorized_personal_edit_hidden': True, 'restricted_content_hidden': True})
                context.close()
                colleague_context.close()
            browser.close()
        assert not errors, errors
        (out / 'result.json').write_text(json.dumps({'checks': checks, 'page_errors': errors, 'real_ai_calls': 0, 'port': server.server_port}, indent=2), encoding='utf-8')
        print(json.dumps({'checks': checks, 'page_errors': errors, 'real_ai_calls': 0}))
    except BaseException:
        if 'page' in locals() and not page.is_closed():
            page.screenshot(path=str(out / 'failure.png'), full_page=True)
            (out / 'failure.html').write_text(page.content(), encoding='utf-8')
            print(json.dumps({'errors': errors, 'form_error': page.locator('.form-error').all_text_contents(), 'url': page.url}, ensure_ascii=False))
        raise
    finally:
        if 'p' in locals():
            p.stop()
        server.shutdown()
        fixture.temp.cleanup()


if __name__ == '__main__':
    main()
