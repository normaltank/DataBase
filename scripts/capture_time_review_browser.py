"""Recapture #134's original single-year time scene in an isolated synthetic app.

The original review images/metadata are never overwritten. The output names are
kept for comparison by the original reviewer. Native200 uses Chrome tab zoom.
"""
import argparse
import base64
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import quote

from PIL import Image
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_maintenance_agent import MaintenanceAgentTests


class Quiet(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.evidence_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sha = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(['git','rev-parse','HEAD^{tree}'], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(['git','status','--porcelain'], cwd=ROOT, text=True).strip()
    metadata = {'source_sha':sha,'source_tree':tree,'source_dirty':dirty,
                'fixture':'Same MaintenanceAgentTests synthetic maintenance/record fixture and public field updates as original final-visual capture.py; same LV/2021/one-record query',
                'captures':[],'errors':[]}
    os.environ['DATABASE_TEST_TMP'] = str(out)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    f = MaintenanceAgentTests()
    f.setUp()
    server = None
    thread = None
    try:
        jid = f.queue('final-visual-134')
        assert f.call('/api/admin/maintenance/run', user='admin').status_code == 200
        rid = f.rid
        current = f.detail(rid)
        assert f.call('/api/records/'+rid, {'version':current['version'],
            'title':'合成整合旅程 · 研究原文','countries':'Latvia','published_on':'2021',
            'abstract':'完全合成的视觉验收材料；用于查看作者、期刊及维护证据，不是真实研究结论。'}, method='PUT').status_code == 200
        f.record(title='合成整合旅程 · 其他资料',countries='Japan',published_on='2020',abstract='完全合成视觉验收资料。')
        server = make_server('127.0.0.1',0,f.app,threaded=True,request_handler=Quiet)
        assert server.server_port not in {6430,3435,3436}
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        metadata.update(record_id=rid, job_id=jid, role='researcher', base=base)
        extension = out/'zoom-extension'
        extension.mkdir()
        (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Isolated time review zoom','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
        (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(out/'profile'),headless=False,
                ignore_default_args=['--disable-extensions'], args=['--headless=new',
                    f'--disable-extensions-except={extension}',f'--load-extension={extension}'],
                viewport={'width':1366,'height':900})
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page = context.pages[0]
            page.on('pageerror',lambda error:metadata['errors'].append(str(error)))
            page.goto(base)
            page.get_by_role('button',name='研究员',exact=True).click()
            for variant,width,height,factor in [('desktop',1366,900,1),('mobile',390,844,1),('narrow320',320,780,1),('native200',1366,900,2)]:
                def zoom(value):
                    actual = worker.evaluate('''async ([base,value])=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,value);return chrome.tabs.getZoom(tab.id)}''',[base,value])
                    assert actual == value
                zoom(1)
                page.set_viewport_size({'width':width,'height':height})
                zoom(factor)
                page.goto(base+'/#library?feed=all&q='+quote('合成整合旅程'))
                panel = page.locator('.material-discovery')
                expect(panel.locator('[data-material-scene=country]')).to_be_visible()
                panel.locator('[data-material-scene=country]').click()
                expect(panel.locator('[data-material-country=LV]').last).to_be_visible()
                panel.locator('button[data-material-country=LV]').click()
                expect(panel.locator('.material-scope')).to_contain_text('1 条')
                if panel.locator('[data-material-scene=time]').get_attribute('aria-pressed') != 'true':
                    panel.locator('[data-material-scene=time]').click()
                expect(panel.locator('.material-time-chart canvas')).to_be_visible()
                panel.locator('[data-material-from]').fill('2021')
                panel.locator('[data-material-to]').fill('2021')
                panel.locator('[data-material-apply]').click()
                expect(panel.locator('.material-window-scope')).to_contain_text('完整匹配 1 条')
                if panel.locator('[data-material-lens]').get_attribute('aria-pressed') != 'true':
                    panel.locator('[data-material-lens]').click()
                expect(panel.locator('.material-time-lens canvas')).to_be_visible()
                panel.locator('[data-material-camera-reset]').click()
                chart = panel.locator('.material-time-chart')
                chart.evaluate("e=>e.scrollIntoView({block:'start',behavior:'instant'})")
                b = chart.bounding_box()
                if b and b['y'] < 90:
                    page.mouse.move(min(b['x']+20,width-10),max(100,min(height-20,b['y']+120)))
                    page.mouse.wheel(0,-100)
                page.wait_for_timeout(450)
                labels = panel.locator('.material-time-lens-label').evaluate_all('es=>es.map(e=>({text:e.textContent,fontSize:getComputedStyle(e).fontSize,box:e.getBoundingClientRect().toJSON()}))')
                assert {label['text'] for label in labels} >= {'2021','2021年末','期刊文章'}
                assert all(float(label['fontSize'].removesuffix('px')) >= 14 for label in labels)
                layout = page.evaluate('({innerWidth,innerHeight,scrollWidth:document.documentElement.scrollWidth,devicePixelRatio,scrollY})')
                assert layout['scrollWidth'] <= layout['innerWidth']+2
                path = out/f'02-time-{variant}-viewport.png'
                if factor == 2:
                    cdp = context.new_cdp_session(page)
                    shot = cdp.send('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False,'fromSurface':True})
                    path.write_bytes(base64.b64decode(shot['data']))
                    cdp.detach()
                else:
                    page.screenshot(path=str(path),full_page=False)
                metadata['captures'].append({'path':str(path),'scene':'02-time','variant':variant,
                    'capture_type':'viewport','png_dimensions':Image.open(path).size,'physical_viewport':page.viewport_size,
                    'native_zoom':factor,'layout':layout,'labels':labels,'route':page.url,'role':'researcher',
                    'record_id':rid,'source_sha':sha,'source_tree':tree,'captured_utc':datetime.now(timezone.utc).isoformat()})
                if factor==2:panel.locator('.material-time-lens').screenshot(path=str(out/'02-time-native200-lens.png'))
                print(path,flush=True)
            assert not metadata['errors'],metadata['errors']
            context.close()
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if thread:
            thread.join(timeout=5)
        f.doCleanups()
        metadata['server_thread_closed'] = not thread or not thread.is_alive()
        (out/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
