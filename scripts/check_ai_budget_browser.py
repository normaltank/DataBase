"""Real admin browser controls plus independent synthetic provider; temporary data only."""
import json,os,ssl,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server,WSGIRequestHandler
from platform_app.web import create_app
from tests.test_ai_budget import Provider,PRICE

class Quiet(WSGIRequestHandler):
 def log(self,*args,**kwargs):pass

out=Path(tempfile.mkdtemp(prefix='ai63-browser-'))
app=create_app(out/'data',testing=True)
web=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
provider=ThreadingHTTPServer(('127.0.0.1',0),Provider)
Provider.requests=[];Provider.mode='missing';Provider.before_reply=None
for server in [web,provider]:threading.Thread(target=server.serve_forever,daemon=True).start()
results={}
try:
 with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'synthetic-browser-key','DEEPSEEK_BASE_URL':f'https://127.0.0.1:{provider.server_port}','DEEPSEEK_MODEL':'deepseek-flash','DEEPSEEK_PRICING_JSON':json.dumps(PRICE)}),patch.object(ssl.SSLContext,'wrap_socket',lambda context,sock,*a,**k:sock),sync_playwright() as p:
  browser=p.chromium.launch(executable_path=os.environ.get('DATABASE_BROWSER_EXECUTABLE') or None,args=['--no-sandbox'])
  for width in [1366,390]:
   context=browser.new_context(viewport={'width':width,'height':900});page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(type(e).__name__))
   page.goto(f'http://127.0.0.1:{web.server_port}');page.get_by_role('button',name='资料管理员',exact=True).click()
   page.evaluate("go('system')")
   card=page.locator('.ai-budget-card');expect(card).to_be_visible()
   card.get_by_label('月额度',exact=True).fill('0.050000');card.get_by_label('币种',exact=True).fill('USD');card.get_by_role('button',name='保存月额度',exact=True).click()
   expect(card).to_contain_text('0.05 USD')
   card.get_by_role('button',name='暂停 AI',exact=True).click();expect(card.get_by_role('button',name='恢复 AI',exact=True)).to_be_visible()
   card.get_by_role('button',name='恢复 AI',exact=True).click();expect(card.get_by_role('button',name='暂停 AI',exact=True)).to_be_visible()
   rid=page.evaluate("async width => (await api('/api/records',{method:'POST',body:{title:'Synthetic budget browser original '+width,kind:'journal_article'}})).id",width)
   page.evaluate("async rid=>{const job=await api('/api/records/'+rid+'/translations',{method:'POST',body:{version:1,request_id:'browser-'+rid}});return api('/api/translations/'+job.id+'/run',{method:'POST',body:{}})}",rid)
   card.get_by_role('button',name='刷新费用',exact=True).click();expect(card).to_contain_text('费用未知')
   card.get_by_text('精确金额与调用依据',exact=True).click()
   unresolved=card.locator('.ai-attempt').filter(has=page.locator('[data-form=ai-resolve]')).first
   unresolved.get_by_text('核对并记录这次费用',exact=True).click()
   form=unresolved.locator('form');form.locator('[name=charged]').fill('0.000025');form.locator('[name=basis]').fill('Synthetic invoice independently confirms 25 micro USD')
   form.get_by_role('button',name='记录核实费用',exact=True).click()
   expect(card.locator('[data-form=ai-resolve]')).to_have_count(0)
   page.screenshot(path=str(out/f'admin-{width}.png'),full_page=True)
   overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth')
   assert not overflow and not errors,(width,overflow,errors)
   page.evaluate("document.documentElement.style.zoom='200%'");page.screenshot(path=str(out/f'admin-{width}-200.png'),full_page=True)
   assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
   page.evaluate("document.documentElement.style.zoom=''")
   page.evaluate("async()=>{await api('/api/logout',{method:'POST',body:{}});location.reload()}")
   page.get_by_role('button',name='研究员',exact=True).click();expect(page.locator('.login-shell')).to_have_count(0);page.evaluate("go('system')")
   expect(page.locator('.ai-budget-card')).to_have_count(0)
   status=page.evaluate("async()=> (await fetch('/api/admin/ai')).status")
   assert status==403
   page.evaluate("go('library')");expect(page.locator('#content')).to_contain_text('Synthetic budget browser original')
   page.screenshot(path=str(out/f'reader-{width}.png'),full_page=True)
   results[str(width)]={'admin_saved_cap':True,'pause_resume':True,'unknown_reconciled':True,'reader_original_visible':True,'reader_admin_forbidden':True,'overflow':overflow,'page_errors':errors}
   context.close()
  browser.close()
 assert len(Provider.requests)==2,len(Provider.requests)
 (out/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 print(out)
finally:
 web.shutdown();web.server_close();provider.shutdown();provider.server_close()
