"""Synthetic translation UI smoke: dynamic port, isolated data, mocked provider HTTP."""
import sys,json,tempfile,threading,os,time
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from platform_app.web import create_app
from werkzeug.serving import make_server,WSGIRequestHandler
from playwright.sync_api import sync_playwright,expect
root=Path(os.environ.get('DATABASE_TRANSLATION_EVIDENCE') or tempfile.mkdtemp(prefix='translation-evidence-'))
root.mkdir(parents=True, exist_ok=True)
data_temp=tempfile.TemporaryDirectory(prefix='translation-browser-')
app=create_app(Path(data_temp.name)/'data',testing=True)
c=app.test_client()
def post(path,data):return c.post(path,json=data,headers={'X-CSRF-Token':c.get('/api/session').json['csrf']})
post('/api/login',{'username':'researcher','password':'LocalDemo2026!'})
rid=post('/api/records',{'title':'Synthetic translation example','abstract':'Synthetic abstract only.','kind':'journal_article'}).json['id']
class Quiet(WSGIRequestHandler):
 def log(self,*args,**kwargs):pass
server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
server_thread=threading.Thread(target=server.serve_forever,daemon=True)
server_thread.start()
provider_delay = {'seconds': 0}
def provider(*args,**kwargs):
 time.sleep(provider_delay['seconds'])
 response=MagicMock();response.__enter__.return_value=response;response.geturl.return_value='https://api.deepseek.com/chat/completions'
 response.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'title':'合成机器译题','abstract':'合成机器摘要'})}}]}).encode()
 return response
results={}
try:
 with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'synthetic-browser-key','DEEPSEEK_BASE_URL':'https://api.deepseek.com','DEEPSEEK_MODEL':'deepseek-flash'}),patch('urllib.request.OpenerDirector.open',side_effect=provider),sync_playwright() as p:
  browser=p.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None,args=['--no-sandbox'])
  for width in [1366,390]:
   ctx=browser.new_context(viewport={'width':width,'height':900});page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto('http://127.0.0.1:'+str(server.server_port));page.get_by_role('button',name='研究员',exact=True).click()
   page.locator('[data-action=detail][data-id="'+rid+'"]').first.click()
   panel=page.locator('[data-translations]');expect(panel).to_be_visible(timeout=5000)
   if panel.locator('details').first.get_attribute('open') is None:panel.locator('summary').first.click()
   panel.get_by_role('button',name='新建翻译任务',exact=True).click()
   panel.get_by_role('button',name='执行本篇翻译',exact=True).first.click()
   expect(panel).to_contain_text('合成机器译题',timeout=10000)
   adoption=panel.locator('[data-translation-adoption]').first
   adoption.locator('summary').click()
   adoption.locator('[name=chinese_title]').fill('人工复核译题 '+str(width))
   adoption.get_by_role('button',name='采用此版本',exact=True).click()
   expect(panel).to_contain_text('人工复核译题 '+str(width))
   page.screenshot(path=str(root/f'translation-{width}.png'),full_page=True)
   panel.get_by_role('button',name='新建翻译任务',exact=True).click()
   panel.get_by_role('button',name='执行本篇翻译',exact=True).first.click()
   adoption=panel.locator('[data-translation-adoption]').first
   expect(adoption).to_be_visible()
   adoption.locator('summary').click()
   adoption.locator('[name=chinese_title]').fill('冲突时保留的人工输入')
   page.evaluate("async rid => {const r=await api('/api/records/'+rid); await api('/api/records/'+rid,{method:'PUT',body:{version:r.version,title:'Revised synthetic '+r.version}});}",rid)
   adoption.get_by_role('button',name='采用此版本',exact=True).click()
   expect(panel.locator('[data-translation-status]')).to_contain_text('更新')
   expect(adoption.locator('[name=chinese_title]')).to_have_value('冲突时保留的人工输入')
   page.screenshot(path=str(root/f'conflict-{width}.png'),full_page=True)
   page.locator('[data-action=close]').first.click()
   page.locator('[data-action=detail][data-id="'+rid+'"]').first.click()
   panel=page.locator('[data-translations]')
   expect(panel).to_contain_text('原文已变化，待复核')
   panel.get_by_role('button',name='新建翻译任务',exact=True).click()
   provider_delay['seconds']=.4
   with page.expect_response(lambda response: '/api/translations/' in response.url and response.url.endswith('/run')):
    panel.get_by_role('button',name='执行本篇翻译',exact=True).first.click()
    page.locator('[data-action=close]').first.click()
   expect(panel).not_to_be_attached()
   provider_delay['seconds']=0
   results[str(width)]={'page_errors':errors,'horizontal_overflow':page.evaluate('document.documentElement.scrollWidth>innerWidth'),'conflict_preserves_input':True,'late_response_keeps_reader_closed':True}
   assert not errors and not results[str(width)]['horizontal_overflow'],results
   ctx.close()
  browser.close()
finally:
 server.shutdown()
 server_thread.join()
 server.server_close()
 data_temp.cleanup()
(root/'browser-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2), encoding="utf-8")
print(json.dumps(results,ensure_ascii=False))
