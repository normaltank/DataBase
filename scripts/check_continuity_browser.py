"""Synthetic HTTP/browser acceptance for #30 and #31 on port 8854.

Creates its own temporary library. No existing data is read or imported.
Screenshots and results remain under CONTINUITY_EVIDENCE or system Temp.
"""
import json, os, socket, subprocess, time, traceback
from urllib.parse import urlencode
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('CONTINUITY_EVIDENCE',str(Path(os.environ['TEMP'])/'database-continuity-browser'))); OUT.mkdir(exist_ok=True); URL='http://127.0.0.1:8854'
results={}; server=None

def snap(p,name):
    p.screenshot(path=str(OUT/(name+'.png')),full_page=False)
    (OUT/(name+'.txt')).write_text(p.locator('body').inner_text(),encoding='utf-8')

def run():
 global server
 with socket.socket() as s:
  assert s.connect_ex(('127.0.0.1',8854))!=0,'8854 occupied'
 log=(OUT/'server.log').open('w',encoding='utf-8')
 server=subprocess.Popen([r'C:\Python312\python.exe',str(ROOT/'app.py'),'--no-import','--port','8854','--data-dir',str(OUT/('data-'+str(time.time_ns())))],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
 with sync_playwright() as pw:
  api=pw.request.new_context(base_url=URL)
  for n in range(100):
   try:
    if api.get('/health',timeout=500).ok: break
   except: time.sleep(.1)
  def call(path,data=None,method='POST'):
   csrf=api.get('/api/session').json()['csrf']
   r=api.fetch(path,method=method,data=data or {},headers={'X-CSRF-Token':csrf})
   assert r.ok,(path,r.status,r.text())
   return r.json()
  call('/api/login',{'username':'researcher','password':'LocalDemo2026!'})
  src=call('/api/sources',{'name':'合成来源Probe','kind':'institution'})['id']
  person=call('/api/people',{'name':'合成人物Probe','change_note':'合成测试'})['id']
  records=[]
  for n in range(40):
   rid=call('/api/records',{'kind':'report','title':f'Probe资料 {n:02d}','authors':'合成人物Probe','source_id':src,'published_on':'2026-01-01','body_html':'<p>合成正文</p>'*8})['id']; records.append(rid)
  by=api.get('/api/records/'+records[12]+'/bylines').json()
  call('/api/records/'+records[12]+'/bylines',{'version':by['version'],'record_version':by['record_version'],'items':[{'raw_name':'合成人物Probe','target_type':'person','target_id':person,'status':'confirmed','evidence':'https://example.org/synthetic'}],'change_note':'合成确认'},'PUT')
  for n in range(16): call('/api/records',{'kind':'research_note','title':f'Omit研究 {n:02d}','author_id':'researcher','published_on':'2026-10-01','body_html':'<p>合成</p>'})
  eligible=call('/api/records',{'kind':'report','title':'Omit原文可选','published_on':'2020-01-01','body_html':'<p>合成</p>'})['id']
  topic=call('/api/collections',{'name':'合成工作位置专题','visibility':'shared','research_question':'仅验证导航'})['id']
  call('/api/collections/'+topic+'/items',{'record_id':records[12]})
  results['fixture']={'records':57,'probe_matches':40,'omit_research':16,'omit_eligible':1,'sources':1,'people':1,'topics':1,'source':src,'person':person,'topic':topic,'target':records[12],'eligible':eligible}
  browser=pw.chromium.launch(executable_path=r'C:\Users\27451\AppData\Local\ms-playwright\chromium-1187\chrome-win\chrome.exe')
  ctx=browser.new_context(viewport={'width':1440,'height':1000},storage_state=api.storage_state()); p=ctx.new_page(); p.set_default_timeout(5000)
  def route(hash):
   p.goto(URL+'/#'+hash); p.wait_for_function("() => document.querySelector('#content') && !document.querySelector('#content .boot')"); p.wait_for_timeout(300)
  errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
  for width in (1366,390):
   p.set_viewport_size({'width':width,'height':900 if width>500 else 844})
   route('library?q=Probe&sort=title&page=2')
   p.get_by_role('button',name='卡片视图',exact=True).click()
   p.locator('[data-library-record="'+records[12]+'"] [data-action=detail]').first.click()
   p.locator('.library-reader .ux-identities > summary').click()
   p.locator('.library-reader [data-action=byline-target][data-type=person]').first.click()
   expect(p.locator('.person-page')).to_have_count(1)
   p.go_back()
   expect(p.locator('.library-reader:visible')).to_have_count(1)
   expect(p.locator('.library-workspace')).to_have_attribute('data-view','cards')
   p.locator('.library-reader .ux-identities > summary').click()
   p.locator('.library-reader [data-action=byline-target][data-type=person]').first.click()
   p.reload();p.get_by_role('button',name='返回资料',exact=True).click()
   expect(p.locator('.library-reader:visible')).to_have_count(1)
   assert 'page=2' in p.url
   p.locator('[data-action=library-reader-next]').click()
   expect(p.locator('.library-reader .detail-title')).to_contain_text('Probe资料 13')
   p.locator('[data-action=library-reader-prev]').click()
   expect(p.locator('.library-reader .detail-title')).to_contain_text('Probe资料 12')
   p.locator('.library-reader .ux-metadata summary').click()
   p.locator('.library-reader [data-action=source-detail]').first.click()
   expect(p.locator('#content .source-profile')).to_have_count(1)
   p.get_by_role('button',name='返回资料',exact=True).click()
   expect(p.locator('.library-reader:visible')).to_have_count(1)
   expect(p.locator('.library-workspace')).to_have_attribute('data-view','cards')
   p.reload();expect(p.locator('.library-reader:visible')).to_have_count(1);expect(p.locator('.library-workspace')).to_have_attribute('data-view','cards')
   snap(p,f'position-{width}')
   p.locator('[data-action=library-reader-close]').click()
   route('collections');p.locator('[data-action="open-collection"][data-id="'+topic+'"]').click()
   p.locator('#topic-record-search').fill('Probe');p.get_by_role('button',name='查找并添加',exact=True).click()
   expect(p.locator('[data-topic-results]')).to_contain_text('共 39 条')
   p.locator('[data-action=topic-page][data-page="2"]').click()
   expect(p.locator('[data-topic-results]')).to_contain_text('31–39')
   p.locator('.topic-record [data-action=detail]').first.click()
   expect(p.locator('.workspace-topic')).to_have_count(0)
   expect(p.locator('#modal-root .detail-title')).to_contain_text('Probe资料 12')
   p.go_back()
   expect(p.locator('.workspace-topic')).to_have_count(1)
   expect(p.locator('#topic-record-search')).to_have_value('Probe')
   expect(p.locator('[data-topic-results]')).to_contain_text('31–39')
   p.locator('.topic-record [data-action=detail]').first.click()
   expect(p.locator('.workspace-topic')).to_have_count(0)
   p.locator('[data-action=close]').first.click()
   expect(p.locator('.workspace-topic')).to_have_count(1)
   expect(p.locator('#topic-record-search')).to_have_value('Probe')
   expect(p.locator('[data-topic-results]')).to_contain_text('31–39')
   snap(p,f'topic-return-{width}')
   assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
  route('library?q=Probe&sort=title&page=2')
  p.locator('[data-library-record="'+records[12]+'"] [data-action=detail]').first.click()
  p.locator('.library-reader .ux-maintenance summary').click()
  p.locator('.library-reader [data-action=edit-record]').click()
  p.locator('#f-abstract').fill('Synthetic revision while reading')
  p.get_by_role('button',name='保存修订',exact=True).click()
  expect(p.locator('[data-form=record]')).to_have_count(0)
  p.locator('[data-action=close]').first.click()
  expect(p.locator('.library-reader:visible')).to_have_count(1)
  expect(p.locator('.library-reader')).to_contain_text('Synthetic revision while reading')
  route('library');p.get_by_role('button',name='提交资料',exact=False).first.click();p.locator('#f-kind').select_option('compilation');p.wait_for_timeout(900)
  delayed=[]
  def delay_candidates(request):
   if 'q=Slow' in request.request.url:delayed.append(request)
   else:request.continue_()
  p.route('**/api/record-candidates?*',delay_candidates)
  p.locator('#link-search').fill('Slow');p.wait_for_timeout(500)
  assert delayed
  p.locator('#link-search').fill('Probe')
  expect(p.locator('#link-results')).to_contain_text('共 40 条')
  delayed.pop().continue_();p.wait_for_timeout(250)
  expect(p.locator('#link-results')).to_contain_text('共 40 条')
  p.locator('[data-action=link-page][data-page="2"]').click()
  expect(p.locator('#link-results')).to_contain_text('16–30')
  p.locator('[data-action=link-page][data-page="3"]').click()
  expect(p.locator('#link-results')).to_contain_text('31–40')
  extra=p.locator('[data-action=select-link]').first.get_attribute('data-id')
  p.locator('[data-action=select-link]').first.click()
  expect(p.locator('#link-results')).to_contain_text('共 39 条')
  p.locator('#link-search').fill('Omit')
  expect(p.locator('#link-results')).to_contain_text('Omit原文可选')
  p.locator('[data-action=select-link][data-id="'+eligible+'"]').click()
  expect(p.locator('#selected-links')).to_contain_text('Omit原文可选')
  expect(p.locator('#link-results')).to_contain_text('共 0 条')
  expect(p.locator('#selected-links .selected-link')).to_have_count(2)
  p.locator('#f-title').fill('Browser saved references')
  p.locator('[data-rich-input]').fill('Synthetic saved content')
  snap(p,'original-selected')
  pending=[]
  def delay_save(request):
   if request.request.method=='POST':pending.append(request)
   else:request.continue_()
  p.route('**/api/records',delay_save)
  p.get_by_role('button',name='保存内容',exact=True).click()
  p.wait_for_timeout(300);assert pending
  p.go_back();expect(p.locator('[data-form=record]')).to_have_count(1)
  expect(p.locator('#f-title')).to_have_value('Browser saved references')
  pending.pop().continue_()
  expect(p.locator('[data-form=record]')).to_have_count(0)
  saved=api.get('/api/records?q=Browser%20saved%20references').json()['items'][0]
  detail=api.get('/api/records/'+saved['id']).json()
  assert {r['id'] for r in detail['linked_records']}=={extra,eligible}
  results['saved_references']=[extra,eligible]
  p.unroute('**/api/record-candidates?*',delay_candidates)
  p.unroute('**/api/records',delay_save)
  route('collections');p.locator('[data-action="open-collection"][data-id="'+topic+'"]').click()
  p.locator('#topic-record-search').fill('Probe');p.get_by_role('button',name='查找并添加',exact=True).click()
  expect(p.locator('[data-topic-results]')).to_contain_text('共 39 条')
  p.locator('[data-action=topic-page][data-page="2"]').click()
  expect(p.locator('[data-topic-results]')).to_contain_text('31–39')
  for n in range(9):
   p.locator('[data-action=topic-add]').first.click()
   expect(p.locator('[data-topic-results]')).to_contain_text('共 '+str(38-n)+' 条')
  expect(p.locator('[data-topic-results]')).to_contain_text('1–30')
  assert len(api.get('/api/collections/'+topic).json()['items'])==10
  results['saved_topic_items']=10
  # Keep an older response pending while changing the query and reopening the topic.
  topic_pending=[]
  def topic_network(request):
   if 'q=Slow' in request.request.url:topic_pending.append(request)
   elif 'q=Failure' in request.request.url:request.fulfill(status=503,json={'error':'Synthetic candidate service unavailable'})
   else:request.continue_()
  p.route('**/api/record-candidates?*',topic_network)
  p.locator('#topic-record-search').fill('Slow');p.get_by_role('button',name='查找并添加',exact=True).click();p.wait_for_timeout(150)
  assert topic_pending
  p.locator('#topic-record-search').fill('Probe');p.get_by_role('button',name='查找并添加',exact=True).click()
  expect(p.locator('[data-topic-results]')).to_contain_text('共 30 条')
  topic_pending.pop().continue_();p.wait_for_timeout(200)
  expect(p.locator('[data-topic-results]')).to_contain_text('共 30 条')
  p.locator('#topic-record-search').fill('Slow');p.get_by_role('button',name='查找并添加',exact=True).click();p.wait_for_timeout(150)
  p.locator('[data-action=close]').first.click()
  p.locator('[data-action="open-collection"][data-id="'+topic+'"]').click()
  p.locator('#topic-record-search').fill('NoSuchMatch');p.get_by_role('button',name='查找并添加',exact=True).click()
  expect(p.locator('[data-topic-results]')).to_contain_text('共 0 条')
  topic_pending.pop().continue_();p.wait_for_timeout(200)
  expect(p.locator('[data-topic-results]')).to_contain_text('共 0 条')
  p.locator('#topic-record-search').fill('Failure');p.get_by_role('button',name='查找并添加',exact=True).click()
  expect(p.locator('[data-topic-results] [role=alert]')).to_contain_text('Synthetic candidate service unavailable')
  p.unroute('**/api/record-candidates?*',topic_network)
  results['slow_changed_query_close_reopen_error']=True
  # A fresh link has no remembered path and falls back to a scoped library query.
  direct=ctx.new_page();direct.goto(URL+'/#sources?'+urlencode({'id':src,'work':records[12]}))
  direct.get_by_role('button',name='返回资料',exact=True).click()
  expect(direct.locator('.library-reader:visible')).to_have_count(1)
  assert '#library?q='+records[12] in direct.url
  direct.close()
  # A browser-driven route change preserves the dirty editor as a recoverable draft.
  route('library');p.get_by_role('button',name='提交资料',exact=False).first.click()
  p.locator('#f-title').fill('Protected synthetic draft')
  p.evaluate("location.hash='#sources'")
  expect(p.locator('[data-form=record]')).to_have_count(0)
  route('drafts');expect(p.locator('.workspace-drafts')).to_contain_text('Protected synthetic draft')
  p.locator('.draft-card').filter(has_text='Protected synthetic draft').get_by_role('button',name='继续编辑').click()
  p.get_by_role('button',name='恢复草稿',exact=True).click()
  expect(p.locator('#f-title')).to_have_value('Protected synthetic draft')
  p.get_by_role('button',name='关闭并保留草稿',exact=True).click()
  # Revocation while on a profile must recheck the material on browser back.
  colleague=pw.request.new_context(base_url=URL)
  csrf=colleague.get('/api/session').json()['csrf']
  assert colleague.post('/api/login',data={'username':'colleague','password':'LocalDemo2026!'},headers={'X-CSRF-Token':csrf}).ok
  cc=browser.new_context(viewport={'width':390,'height':844},storage_state=colleague.storage_state());cp=cc.new_page()
  cp.goto(URL+'/#library?q='+records[12])
  cp.locator('[data-library-record="'+records[12]+'"] [data-action=detail]').first.click()
  cp.locator('.library-reader .ux-metadata summary').click();cp.locator('.library-reader [data-action=source-detail]').first.click()
  expect(cp.locator('#content .source-profile')).to_have_count(1)
  latest=api.get('/api/records/'+records[12]).json()
  call('/api/records/'+records[12],{'version':latest['version'],'visibility':'restricted'},'PUT')
  cp.go_back();expect(cp.locator('.library-reader:visible')).to_have_count(0)
  expect(cp.locator('.library-workspace')).to_contain_text('暂时没有符合条件的资料')
  assert 'Probe资料 12' not in cp.locator('body').inner_text()
  snap(cp,'permission-fallback-390');cc.close();colleague.dispose()
  results['direct_refresh_back_draft_permission']=True
  results['page_errors']=errors
  assert not errors,errors
  results['passed']=True
  browser.close();api.dispose()
try:run()
except Exception:
 results['error']=traceback.format_exc();raise
finally:
 if server:
  server.terminate();server.wait(timeout=5)
 (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 print(OUT)
