'use strict';
// Public page scripts and DOM actions with controlled HTTP responses; no server or real data.
const {JSDOM}=require('jsdom');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {loadPageScripts,jsonResponse}=require('./dom_page_contract');
const root=path.join(__dirname,'..');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function waitFor(check){for(let i=0;i<50;i++){if(check())return;await tick();}assert.ok(check(),'page did not reach expected state');}
async function page(query,failure,savedConditions=null){
  const dom=new JSDOM('<div id="app"></div><div id="modal-root"></div><div id="toast"></div>',{runScripts:'outside-only',url:'http://synthetic.local/#library?'+new URLSearchParams(query)}),w=dom.window;
  w.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}});w.scrollTo=()=>{};
  const requests=[];let failing=true;
  w.fetch=async(url,options={})=>{
    requests.push({url:String(url),method:options.method||'GET'});
    let status=200,body;
    if(url==='/api/session')body={user:{id:'synthetic-reader',name:'合成研究员',role:'researcher'},csrf:'synthetic'};
    else if(url==='/health')body={schema:26};
    else if(url==='/api/country-names')body={};
    else if(['/api/sources','/api/users','/api/collections'].includes(url))body={items:[]};
    else if(url==='/api/saved-searches/scoped')body={id:'scoped',name:'合成范围',version:1,conditions:savedConditions||{feed:'all',q:'拉脱维亚',source:'persisted-source'}};
    else if(String(url).startsWith('/api/records?')){
      if(failing){if(failure==='network')throw new TypeError('Failed to fetch');status=failure.status;body={error:failure.error};}
      else body={items:[],total:0,page:1,size:20,facets:{},facet_options:{}};
    }else throw new Error('Unexpected request: '+url);
    return jsonResponse(body,status);
  };
  loadPageScripts(dom);
  await waitFor(()=>w.document.querySelector('#content .notice.error'));
  return {w,requests,recover(){failing=false;},close(){w.close();}};
}
(async()=>{
  for(const scope of [{},{source:'live-source'},{collection:'live-collection'},{saved_search:'scoped'}]){
    for(const failure of [{status:503,error:'合成服务暂不可用'},'network']){
      const query={feed:'all',q:'拉脱维亚',...scope},p=await page(query,failure);
      try{
        const {document}=p.w;
        assert.equal(document.querySelector('[data-action="saved-adjust"]'),null,'transient failure must not offer scope removal');
        assert.match(document.querySelector('h1').textContent,/暂时无法读取资料/);
        const before=p.requests.filter(r=>r.url.startsWith('/api/records?')).at(-1).url;
        const retry=document.querySelector('[data-action="saved-retry"]');assert.ok(retry,'transient failure needs an effective retry');
        p.recover();retry.click();await waitFor(()=>document.querySelector('.library-workspace'));
        const after=p.requests.filter(r=>r.url.startsWith('/api/records?')).at(-1).url;
        assert.equal(after,before,'retry must keep the full query');
        assert.equal(document.querySelector('[name=q]').value,query.q);
        assert.equal(p.requests.some(r=>r.method!=='GET'),false,'retry does not mutate saved searches');
      }finally{p.close();}
    }
  }
  console.log('PASS ordinary/source/collection/saved search: 503 and network failures retry the same conditions through DOM events');
  for(const saved of [false,true])for(const [scope,message,input] of [[{source:'gone-source'},'来源不存在。','remove_source'],[{collection:'gone-collection'},'专题不存在或没有访问权限。','remove_collection']]){
    const conditions={feed:'all',q:'保留关键词',...scope};
    const p=await page(saved?{saved_search:'scoped'}:conditions,{status:404,error:message},conditions);
    try{
      const d=p.w.document;assert.match(d.querySelector('h1').textContent,/检索范围暂不可用/);
      d.querySelector('[data-action="saved-adjust"]').click();await waitFor(()=>d.querySelector('[data-saved-form="adjust"]'));
      const form=d.querySelector('[data-saved-form="adjust"]'),check=form.querySelector('[name="'+input+'"]');assert.ok(check);
      check.checked=true;p.recover();form.dispatchEvent(new p.w.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:form.querySelector('[type=submit]')}));
      await waitFor(()=>d.querySelector('.library-workspace'));
      const last=new URL(p.requests.filter(r=>r.url.startsWith('/api/records?')).at(-1).url,'http://synthetic.local');
      assert.equal(last.searchParams.get('q'),'保留关键词');assert.equal(last.searchParams.has(Object.keys(scope)[0]),false);
    }finally{p.close();}
  }
  console.log('PASS ordinary and saved source/collection 404 contracts retain explicit scope adjustment and unrelated conditions');
})().catch(error=>{console.error(error);process.exitCode=1;});
