"""Isolated #64 HTTP/Chrome workflow, synthetic network/provider, actual browser zoom."""
import argparse
import json
import logging
import re
import sys
import subprocess
import threading
from contextlib import suppress
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
from tests.test_author_suggestions import AuthorSuggestionsTests
from tests.test_archive_suggestions import Provider
from scripts.check_topic_finals_browser import serve
from scripts.check_collaboration_browser import login
from scripts.check_reader_maintenance_browser import call
from platform_app import archive_suggestions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--check', choices=['all','exceptions'], default='all')
    args = parser.parse_args()
    root = args.evidence_dir.resolve()
    if root.exists():
        parser.error('Use a fresh evidence directory.')
    root.mkdir(parents=True)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    fixture = AuthorSuggestionsTests()
    fixture.setUp()
    fixture.synthetic()
    Provider.transform = lambda output, value: {'suggestions': value['author_facts']}
    generation = [0]
    def fetch(url):
        value = {'message': {'title': ['Synthetic version '+str(generation[0])], 'DOI': url.split('/works/')[-1].replace('%2F', '/').replace('%2f', '/'),
            'author': [{'given': name, 'family': 'Example', 'ORCID': 'https://orcid.org/' + oid} for name, oid in [
                ('Ada', '0000-0002-1825-0097'), ('Bob', '0000-0001-5109-3700'), ('Carol', '0000-0002-9079-593X')]]}}
        raw = json.dumps(value).encode()
        return {'url': url, 'content_type': 'application/json', 'bytes': raw, 'text': raw.decode()}
    fixture.fetcher = fetch
    server, thread, base = serve(fixture.app)
    stop = threading.Event()
    def work():
        while not stop.wait(.2):
            archive_suggestions.run_pending(Path(fixture.temp.name) / 'data')
    worker_thread = threading.Thread(target=work, daemon=True)
    worker_thread.start()
    context = browser = None
    try:
        p = sync_playwright().start()
        if p:
            executable = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
            extension = root / 'extension'
            extension.mkdir()
            (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Author acceptance zoom','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
            (extension/'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});')
            profile = root/'profile'
            context = p.chromium.launch_persistent_context(str(profile), executable_path=executable, headless=False,
                ignore_default_args=['--disable-extensions'], args=['--headless=new','--enable-unsafe-extension-debugging','--remote-debugging-port=0','--no-proxy-server'],
                viewport={'width':1440,'height':900},accept_downloads=True)
            port = (profile/'DevToolsActivePort').read_text().splitlines()[0]
            browser = p.chromium.connect_over_cdp('http://127.0.0.1:'+port)
            cdp = browser.new_browser_cdp_session()
            cdp.send('Extensions.loadUnpacked',{'path':str(extension)})
            downloads = root/'downloads';downloads.mkdir()
            cdp.send('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(downloads),'eventsEnabled':True})
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            page = context.pages[0]
            errors=[];results=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            login(page,base,'researcher')
            actual = 1
            for width, zoom in ([] if args.check=='exceptions' else [(1440,1),(1366,1),(390,1),(320,1),(1366,2)]):
                page.set_viewport_size({'width':width,'height':900})
                actual = worker.evaluate("async ({base,zoom})=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(t.id,zoom);return chrome.tabs.getZoom(t.id)}",{'base':base,'zoom':zoom})
                assert actual == zoom
                suffix=f'{width}-{zoom}'
                pid=call(context,base,'/api/people',{'name':'Ada Example','change_note':'Synthetic existing author'},expected=201)['id']
                rid=call(context,base,'/api/records',{'kind':'report','title':'SYNTHETIC64 '+suffix,'authors':'Ada Example; Bob Example; Carol Example','doi':'10.5555/'+suffix,'body_html':'<p>Synthetic public article.</p>'},expected=201)['id']
                page.goto(base+'/#library?feed=all&q=SYNTHETIC64%20'+suffix)
                page.locator('.record-title button').first.click()
                page.locator('.ux-identities > summary').click()
                page.get_by_role('button',name='作者关联建议',exact=True).click()
                page.get_by_role('button',name='取得作者建议',exact=True).click()
                review=page.locator('[data-archive-review]')
                expect(review.locator('input[name=candidate]')).to_have_count(3,timeout=20000)
                assert context.request.get(base+'/api/records/'+rid+'/bylines').json()['items']==[]
                rows=review.locator('.archive-candidates > .archive-candidate')
                first,second,third=rows.nth(0),rows.nth(1),rows.nth(2)
                first.get_by_text('查看实际依据',exact=True).focus();page.keyboard.press('Enter')
                expect(first.locator('.author-native-facts')).to_contain_text('Ada Example')
                expect(first.locator('.author-native-facts')).to_contain_text('0000-0002-1825-0097')
                expect(first.get_by_text('输入 ',exact=False)).not_to_be_visible()
                first.locator('[data-author-choice]').select_option(pid)
                if second.locator('[data-author-choice]').count():
                    second.locator('[data-author-choice]').select_option('new')
                first.locator('input[name=candidate]').focus();page.keyboard.press('Space')
                second.locator('input[name=candidate]').focus();page.keyboard.press('Space')
                choices_before=review.locator('input[name=candidate]:checked').count()
                review.get_by_role('button',name='刷新',exact=True).click()
                expect(review.locator('input[name=candidate]:checked')).to_have_count(choices_before)
                page.screenshot(path=str(root/('evidence-'+suffix+'.png')))
                review.get_by_role('button',name='采用所选',exact=True).click()
                expect(review.locator('.archive-candidates input[name=candidate]')).to_have_count(1)
                bylines=context.request.get(base+'/api/records/'+rid+'/bylines').json()['items']
                assert [b['raw_name'] for b in bylines]==['Ada Example','Bob Example','Carol Example']
                assert bylines[0]['target_id']==pid
                assert bylines[1]['status']=='confirmed' and bylines[2]['status']=='pending'
                review.locator('.archive-candidates input[name=candidate]').focus();page.keyboard.press('Space')
                review.get_by_role('button',name='拒绝所选',exact=True).focus();page.keyboard.press('Enter')
                expect(review.locator('.archive-candidates input[name=candidate]')).to_have_count(0)
                review.get_by_text('已处理建议与采用来历',exact=True).click()
                expect(review.locator('[data-archive-history=history]')).to_contain_text('已采用')
                expect(review.locator('[data-archive-history=history]')).to_contain_text('已拒绝')
                with page.expect_download() as download:
                    review.get_by_role('link',name='导出建议与依据',exact=True).click()
                saved=downloads/download.value.suggested_filename
                assert download.value.failure() is None and saved.stat().st_size>0
                import zipfile
                with zipfile.ZipFile(saved) as bundle:
                    payload=json.loads(bundle.read('suggestions.json'))
                    assert payload['targets'][0]['target_id']==rid
                    assert {c['status'] for c in payload['targets'][0]['candidates']}=={'adopted','rejected'}
                    assert any(n.startswith('evidence/') and bundle.read(n) for n in bundle.namelist())
                generation[0]+=1
                review.get_by_role('button',name='重新取得建议',exact=True).click()
                expect(review.locator('.archive-candidates input[name=candidate]')).to_have_count(1,timeout=20000)
                review.locator('.archive-candidates input[name=candidate]').focus();page.keyboard.press('Space')
                record=context.request.get(base+'/api/records/'+rid).json()
                call(context,base,'/api/records/'+rid,{'version':record['version'],'title':record['title']+' human correction'},method='PUT')
                review.get_by_role('button',name='采用所选',exact=True).click()
                expect(review.locator('.form-error')).to_contain_text('已修订')
                expect(review.locator('.archive-candidates input[name=candidate]')).to_be_checked()
                page.screenshot(path=str(root/('conflict-'+suffix+'.png')))
                measure=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
                assert measure['scroll']<=measure['width'],measure
                results.append({'width':width,'actual_zoom':actual,'record_id':rid,'keyboard_evidence_select_adopt_reject':True,'existing_and_new_person':True,'download_verified':True,'conflict_selection_preserved':True,'measure':measure})
                print(json.dumps({'passed':suffix}),flush=True)
            institution=call(context,base,'/api/sources',{'kind':'institution','name':'Example Institute'},expected=201)['id']
            article='<h1>Article</h1><script type="application/ld+json">'+json.dumps({'@type':'Article','headline':'Article','publisher':{'name':'Publisher Only'},'author':{'@type':'Person','name':'Ada Example','url':'https://profile.example/role-ada','affiliation':{'name':'Example Institute'}}})+'</script>'
            def role_fetch(url):
                html='<h1>Ada Example</h1><p>Ada Example is Researcher at Example Institute.</p>' if url.endswith('/role-ada') else article
                return {'url':url,'content_type':'text/html','bytes':html.encode(),'text':html}
            fixture.fetcher=role_fetch
            for width in [1366,390]:
                page.set_viewport_size({'width':width,'height':1100})
                worker.evaluate("async base=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(t.id,1)}",base)
                role_record=call(context,base,'/api/records',{'kind':'report','title':'SYNTHETIC64 roles '+str(width),'authors':'Ada Example','url':'https://article.example/role-'+str(width)},expected=201)['id']
                page.goto(base+'/#library?feed=all&q=SYNTHETIC64%20roles%20'+str(width))
                page.locator('.record-title button').first.click()
                page.locator('.ux-identities > summary').click()
                page.get_by_role('button',name='作者关联建议',exact=True).click()
                page.get_by_role('button',name='取得作者建议',exact=True).click()
                review=page.locator('[data-archive-review]')
                expect(review.locator('input[name=candidate]')).to_have_count(1,timeout=20000)
                review.locator('[data-author-choice]').select_option('new')
                review.get_by_text('查看实际依据',exact=True).click()
                expect(page.locator('#toast')).not_to_have_class(re.compile(r'\bshow\b'))
                page.screenshot(path=str(root/('roles-'+str(width)+'.png')))
                for name in ['candidate','article_units','employments']:
                    review.locator('input[name='+name+']').focus();page.keyboard.press('Space')
                review.get_by_role('button',name='采用所选',exact=True).click()
                expect(review.locator('.archive-candidates input[name=candidate]')).to_have_count(0)
                formal=context.request.get(base+'/api/records/'+role_record+'/bylines').json()['items'][0]
                units=context.request.get(base+'/api/records/'+role_record+'/affiliations').json()['items']
                jobs=context.request.get(base+'/api/people/'+formal['target_id']+'/employments').json()['items']
                assert len(units)==1 and units[0]['institution_id']==institution
                assert len(jobs)==1 and jobs[0]['role']=='Researcher' and jobs[0]['start_date']==jobs[0]['end_date']==''
                results.append({'width':width,'separate_optional_units_and_employment_adopted':True})
            fixture.fetcher=fetch
            page.set_viewport_size({'width':1366,'height':900})
            actual=worker.evaluate("async base=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(t.id,2);return chrome.tabs.getZoom(t.id)}",base)
            assert actual==2
            call(context,base,'/api/login',{'username':'admin','password':'LocalDemo2026!'})
            page.goto(base+'/#maintenance-ai');page.reload()
            batch=[]
            for i in range(2):
                batch.append(call(context,base,'/api/records',{'kind':'report','title':'SYNTHETIC64 batch '+str(i),'authors':'Ada Example; Bob Example; Carol Example','doi':'10.5555/batch'+str(i)},expected=201)['id'])
            page.get_by_role('button',name='批量整理作者建议',exact=True).click()
            page.get_by_role('searchbox',name='资料关键词',exact=True).fill('SYNTHETIC64 batch')
            page.get_by_role('button',name='查找资料',exact=True).click()
            expect(page.locator('input[name=author_record]')).to_have_count(2)
            for check in page.locator('input[name=author_record]').all():
                check.focus();page.keyboard.press('Space')
            expect(page.locator('input[name=author_record]:checked')).to_have_count(2)
            page.get_by_role('button',name='为所选资料排队',exact=True).click()
            expect(page.get_by_role('button',name=re.compile('^核对作者建议：'))).to_have_count(2)
            page.get_by_role('button',name=re.compile('^核对作者建议：')).first.click()
            expect(page.locator('.archive-candidates input[name=candidate]')).to_have_count(3,timeout=20000)
            page.screenshot(path=str(root/'batch-200-percent.png'))
            results.append({'explicit_two_record_batch':True,'actual_zoom':actual,'record_ids':batch})
            call(context,base,'/api/admin/ai/pause',{'paused':True})
            paused=call(context,base,'/api/records',{'kind':'report','title':'SYNTHETIC64 paused','authors':'Ada Example','doi':'10.5555/paused'},expected=201)['id']
            job=call(context,base,'/api/archive-jobs',{'record_ids':[paused],'request_id':'paused-browser'},expected=201)['items'][0]['id']
            page.wait_for_function("async rid=>(await (await fetch('/api/records/'+rid+'/suggestions')).json()).jobs[0].status==='paused'",arg=paused)
            page.goto(base+'/#maintenance-ai');page.reload()
            task=page.locator('[data-ai-tasks] > details').filter(has_text='SYNTHETIC64 paused')
            task.locator(':scope > summary').click()
            expect(task.get_by_role('button',name='核对作者建议',exact=True)).to_be_visible()
            task.get_by_label('处理及批准依据',exact=True).fill('Synthetic approval while pause stays enabled')
            with page.expect_response(lambda r:'/api/admin/archive-jobs/'+job+'/retry' in r.url) as response:
                task.get_by_role('button',name='批准受控重试',exact=True).click()
            assert response.value.status==200
            results.append({'paused_record_exception_target_and_retry':True})
            assert not errors,errors
            (root/'results.json').write_text(json.dumps({'git_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parents[1],text=True).strip(),'schema':fixture.app.test_client().get('/health').json['schema'],'browser':executable,'results':results,'pageerrors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
    except Exception:
        with suppress(Exception):
            page.screenshot(path=str(root/'failure.png'))
            (root/'failure.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
        raise
    finally:
        with suppress(Exception):
            if context: context.close()
            if browser: browser.close()
        with suppress(Exception):
            p.stop()
        stop.set();worker_thread.join(timeout=10)
        server.shutdown();thread.join(timeout=5);server.server_close()
        fixture.doCleanups()


if __name__ == '__main__':
    main()
