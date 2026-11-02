"""Actual installed Chromium/HTTP source-suggestion workflow; synthetic server only."""
import argparse
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from scripts.check_collaboration_library_browser import login
from scripts.check_reader_maintenance_browser import call, account


def flow(page, context, base, evidence, suffix):
    sid = call(context, base, '/api/sources', {'name': 'SYNTHETIC93 ' + suffix, 'kind': 'institution',
              'website': 'https://synthetic93.example/' + suffix}, expected=201)['id']
    page.goto(base + '/#sources?id=' + sid)
    page.get_by_role('button', name='AI补全', exact=True).click()
    page.get_by_role('button', name='取得AI补全建议', exact=True).click()
    page.screenshot(path=str(evidence / ('queued-' + suffix + '.png')))
    root = page.locator('[data-archive-review]')
    expect(root.locator('input[name=candidate]')).to_have_count(2, timeout=20000)
    rows = root.locator('.archive-candidates > .archive-candidate')
    location = rows.filter(has_text='所在地')
    country = rows.filter(has_text='机构国家')
    location.get_by_text('查看实际依据', exact=True).click()
    expect(location.locator('blockquote')).to_have_text('Our office is in Riga, Latvia.')
    location.locator('input').check()
    page.screenshot(path=str(evidence / ('evidence-' + suffix + '.png')))
    root.get_by_role('button', name='采用所选', exact=True).click()
    expect(root.locator('.archive-candidates input')).to_have_count(1)
    assert context.request.get(base + '/api/sources/' + sid).json()['location'] == 'Riga'
    root.locator('.archive-candidates input').check()
    root.get_by_role('button', name='拒绝所选', exact=True).click()
    expect(root.locator('.archive-candidates input')).to_have_count(0)
    root.get_by_text('已处理建议与采用来历', exact=True).click()
    expect(root.locator('[data-archive-history=history]')).to_contain_text('已采用')
    expect(root.locator('[data-archive-history=history]')).to_contain_text('已拒绝')
    page.screenshot(path=str(evidence / ('decisions-' + suffix + '.png')))
    root.get_by_role('button', name='重新取得建议', exact=True).click()
    expect(root.locator('.archive-candidates input')).to_have_count(1, timeout=20000)
    root.locator('.archive-candidates input').check()
    source = context.request.get(base + '/api/sources/' + sid).json()
    call(context, base, '/api/sources/' + sid, {'version': source['version'], 'research_scope': 'Human correction'}, method='PUT')
    root.get_by_role('button', name='采用所选', exact=True).click()
    expect(root.locator('.form-error')).to_contain_text('已被修订')
    expect(root.locator('.archive-candidates input')).to_be_checked()
    assert context.request.get(base + '/api/sources/' + sid).json()['country'] == ''
    page.screenshot(path=str(evidence / ('conflict-' + suffix + '.png')))
    measure = page.evaluate('''() => ({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,
      scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth,
      modalWidth:document.querySelector('[role=dialog]').getBoundingClientRect().width})''')
    assert measure['scrollWidth'] <= measure['clientWidth'] + 1, measure
    return {'source_id': sid, 'measure': measure, 'queue_evidence_adopt_reject_conflict': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8914')
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    expect.set_options(timeout=7000)
    with sync_playwright() as p:
        executable = os.environ.get('DATABASE_BROWSER_EXECUTABLE') or 'C:/Program Files/Google/Chrome/Application/chrome.exe'
        profile = args.evidence / 'profile'
        extension = args.evidence / 'extension'
        extension.mkdir(exist_ok=True)
        (extension / 'manifest.json').write_text(json.dumps({'manifest_version': 3, 'name': 'Archive verification zoom',
            'version': '1.0', 'permissions': ['tabs'], 'background': {'service_worker': 'worker.js'}}))
        (extension / 'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
        context = p.chromium.launch_persistent_context(str(profile), executable_path=executable, headless=False,
            ignore_default_args=['--disable-extensions'], args=['--headless=new', '--enable-unsafe-extension-debugging',
            '--remote-debugging-port=0', '--no-proxy-server'], viewport={'width': 1440, 'height': 900}, accept_downloads=True)
        port = (profile / 'DevToolsActivePort').read_text().splitlines()[0]
        browser = p.chromium.connect_over_cdp('http://127.0.0.1:' + port)
        browser.new_browser_cdp_session().send('Extensions.loadUnpacked', {'path': str(extension)})
        worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
        page = context.pages[0] if context.pages else context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            login(page, args.base, 'researcher')
            results = []
            for width, zoom in [(1440, 1), (1366, 1), (390, 1), (320, 1), (1366, 2)]:
                page.set_viewport_size({'width': width, 'height': 900})
                actual = worker.evaluate('''async ({url,zoom})=>{const tab=(await chrome.tabs.query({})).find(t=>t.url===url);
                    await chrome.tabs.setZoom(tab.id,zoom);return await chrome.tabs.getZoom(tab.id)}''', {'url': page.url, 'zoom': zoom})
                assert actual == zoom
                suffix = str(width) + '-' + str(zoom)
                results.append(flow(page, context, args.base, args.evidence, suffix))
                if zoom == 2:
                    physical = context.new_cdp_session(page).send('Page.captureScreenshot', {'format':'png', 'captureBeyondViewport': False})
                    (args.evidence / '200-percent-physical.png').write_bytes(base64.b64decode(physical['data']))
                print(json.dumps({'passed': suffix}), flush=True)
            assert errors == [], errors
            (args.evidence / 'results.json').write_text(json.dumps({'results': results, 'pageerrors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            page.screenshot(path=str(args.evidence / 'failure.png'))
            (args.evidence / 'failure.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
            raise
        finally:
            context.close()
            browser.close()


if __name__ == '__main__':
    main()
