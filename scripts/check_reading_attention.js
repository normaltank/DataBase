'use strict';
// Actual page scripts, DOM events and controlled HTTP. No listener or provider.
const {JSDOM}=require('jsdom');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),tick=()=>new Promise(resolve=>setImmediate(resolve));
async function waitFor(check){for(let i=0;i<80;i++){if(check())return;await tick();}assert.ok(check(),'page did not reach expected state');}
const record={id:'r1',title:'港湾文化活动',display_title:'港湾文化活动',original_title:'Harbour culture',kind:'journal_article',status:'pending',visibility:'shared',version:1,authors:'Synthetic Author',published_on:'2026-10-01',language:'en',body_html:'<p>保存的文章正文，应当先于维护信息。</p>',abstract:'Original abstract',display_abstract:'Original abstract',translation_origin:'machine',has_chinese:true,abstract_is_chinese:false,can_edit:true,attachments:[{id:'f1',name:'article.pdf',bytes:100}],reading_access:{platform_files:[{id:'f1',name:'article.pdf',url:'/api/attachments/f1'}],official_files:[],has_body:true},related_source_ids:[],linked_records:[],cited_by:[],translations:[]};
const source={id:'s1',name:'合成公共研究所',kind:'institution',status:'pending',version:1,scope_status:'core',institution_types:[],country_labels:['拉脱维亚'],research_scope:'社区',introduction_html:'<p>研究所介绍。</p>',relationships:[],related_from:[],related:[],previous_ids:[]};
const person={id:'p1',requested_id:'p1',name:'合成人物',original_name:'Synthetic Person',chinese_name:'',version:1,can_edit:true,introduction_html:'<p>人物介绍正文。</p>',previous_ids:[]};
const candidate=(id,status)=>({id,status,field:'introduction',before:'旧介绍',value:'新介绍',evidence:{url:'https://example.invalid/person',quote:'公开介绍证据'},machine:{},base_version:1});
async function page(route,profile={},overrides={}){
  const material={...record,...overrides};
  const dom=new JSDOM('<div id="app"></div><div id="modal-root"></div><div id="toast"></div>',{runScripts:'outside-only',url:'http://synthetic.local/#'+route}),w=dom.window,requests=[],errors=[];
  w.addEventListener('error',event=>errors.push(event.error?.message||event.message));
  w.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}});w.scrollTo=(x,y)=>{Object.defineProperty(w,'scrollY',{value:y,configurable:true});};
  w.HTMLElement.prototype.scrollIntoView=function(){};w.ResizeObserver=class{observe(){}disconnect(){}};
  w.CSS={escape:s=>String(s)};
  let profileFailure=false,profileData={target_id:'p1',version:1,jobs:[],materials:[],events:[],candidates:[],...profile};
  w.fetch=async(raw,options={})=>{
    const url=new URL(raw,'http://synthetic.local'),p=url.pathname;requests.push({url:String(raw),method:options.method||'GET'});
    let body;
    if(p==='/api/session')body={user:{id:'reader',name:'合成研究员',role:'researcher'},csrf:'synthetic'};
    else if(p==='/health')body={schema:26};
    else if(p==='/api/country-names')body={};
    else if(p==='/api/sources/s1')body=source;
    else if(p==='/api/people/p1')body=person;
    else if(p==='/api/sources')body={items:[source]};
    else if(p==='/api/records/r1')body=material;
    else if(p==='/api/records/r1/bylines')body={items:[],raw_authors:record.authors};
    else if(p==='/api/people/p1/profile-suggestions'){
      if(profileFailure)return {ok:false,status:503,json:async()=>({error:'合成补全读取失败，请重试'})};
      body=profileData;
    }
    else if(p.endsWith('/profile-suggestions/decide')){const decision=JSON.parse(options.body);profileData={...profileData,version:2,candidates:profileData.candidates.map(c=>({...c,status:decision.reject?.includes(c.id)?'rejected':c.status}))};body={};}
    else if(p==='/api/records')body={items:!url.searchParams.has('source_section')||url.searchParams.get('source_section')==='published'?[material]:[],total:!url.searchParams.has('source_section')||url.searchParams.get('source_section')==='published'?1:0,page:1,size:20,facets:{},facet_options:{}};
    else if(p.endsWith('/works'))body={items:[{...record,bylines:[]}],total:1,page:1,size:20};
    else if(p.startsWith('/api/'))body={items:[],total:0,page:1,size:20,version:1,person,subjects:[],bylines:[]};
    else throw new Error('Unexpected request '+raw);
    return {ok:true,status:200,json:async()=>body};
  };
  const html=fs.readFileSync(path.join(root,'templates/index.html'),'utf8');
  for(const [,file] of html.matchAll(/<script src="\/static\/([^"]+)"/g))vm.runInContext(fs.readFileSync(path.join(root,'static',file),'utf8'),dom.getInternalVMContext(),{filename:file});
  try{await waitFor(()=>w.document.querySelector(route==='sources'?'#content [data-action="source-preview"]':'#content [data-action="detail"]'));}catch(error){console.error(route,w.document.querySelector('#content')?.textContent);w.close();throw error;}
  return {w,requests,failProfile:value=>{profileFailure=value;},close(){w.close();assert.deepEqual(errors,[],'actual scripts run without browser errors');}};
}
function assertReading(document){
  const article=document.querySelector('.ux-reading-article'),body=article.querySelector('#ux-body'),identities=article.querySelector('.ux-identities');
  assert.ok(body,'saved body is readable');assert.ok(identities,'identity tools remain available');
  assert.ok(body.compareDocumentPosition(identities)&4,'body must precede identity maintenance');
  assert.equal(identities.open,false,'identity maintenance starts closed');
  assert.ok(article.querySelector('[data-action="favorite"]'),'favorite remains available');
  assert.ok(article.querySelector('[data-action="ux-copy"]'),'copy remains available');
  assert.ok(article.querySelector('[data-action="edit-record"]'),'authorized editing remains available');
}
(async()=>{
  for(const route of ['sources?id=s1&content_published=2','people?id=p1','library?feed=all&q=Harbour']){
    const p=await page(route);try{
      const d=p.w.document,origin=d.querySelector('#content [data-action="detail"]');origin.focus();p.w.scrollTo(0,320);const hash=p.w.location.hash;
      if(route.startsWith('sources')){
        const content=d.querySelector('#source-content'),relations=d.querySelector('#source-relations');
        assert.ok(content.compareDocumentPosition(relations)&4,'source materials precede relationships');
        assert.equal(relations.closest('details').open,false,'source relationship details start closed');
      }
      origin.click();await waitFor(()=>d.querySelector('.ux-reading-article'));assertReading(d);
      const close=d.querySelector('[data-action="library-reader-close"]')||d.querySelector('#modal-root [data-action="close"]');close.click();await tick();
      assert.equal(p.w.location.hash,hash,'return preserves route and query');assert.equal(d.activeElement,origin,'return restores the exact work link');assert.equal(p.w.scrollY,320,'return preserves scroll');
    }finally{p.close();}
  }
  console.log('PASS source/person/search → body-first reader → original route, position and focus');
  const preview=await page('sources');try{
    const d=preview.w.document,directory=d.querySelector('[data-action="source-preview"]');directory.focus();directory.click();await waitFor(()=>d.querySelector('.source-preview'));
    const original=d.querySelector('.source-preview'),work=original.querySelector('[data-action="detail"]'),scroll=original.closest('.drawer-body');scroll.scrollTop=180;work.focus();work.click();
    await waitFor(()=>d.querySelector('.ux-reading-article'));assertReading(d);
    d.activeElement.dispatchEvent(new preview.w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));await tick();
    assert.equal(d.querySelector('.source-preview'),original,'reader returns to the exact source preview');assert.equal(d.activeElement,work);assert.equal(scroll.scrollTop,180);
    d.querySelector('#modal-root [data-action="close"]').click();assert.equal(d.activeElement,directory,'closing preview returns to its directory action');
  }finally{preview.close();}
  console.log('PASS quick source preview → reader → original preview and directory focus');
  for(const candidates of [[],[candidate('done','adopted'),candidate('no','rejected')],[candidate('pending','pending'),candidate('done','adopted')]]){
    const p=await page('people?id=p1',{candidates});try{
      const d=p.w.document,workspace=d.querySelector('[data-person-profile]'),works=d.querySelector('#person-works');
      assert.equal(workspace.tagName,'DETAILS','profile completion is an explicit workspace');
      assert.equal(workspace.open,false,'normal profile reading starts with completion closed');
      assert.ok(works.compareDocumentPosition(workspace)&4,'works precede maintenance');
      assert.equal(d.querySelectorAll('[data-person-profile-form="decide"] input[name="candidate"]').length,candidates.filter(c=>c.status==='pending').length);
      if(!candidates.some(c=>c.status==='pending'))assert.equal(workspace.querySelector('[data-person-profile-form="decide"] button'),null,'zero pending has no disabled decisions');
      if(candidates.some(c=>c.status!=='pending'))assert.equal(workspace.querySelector('[data-profile-open="decided"]').open,false,'completed suggestions stay in closed history');
      d.querySelector('[data-person-profile-open]').click();assert.equal(workspace.open,true,'explicit action opens completion');
      assert.equal(d.activeElement,workspace.querySelector('[name="name"]'),'explicit action focuses the name field');
      const refresh=workspace.querySelector('[data-person-profile-action="refresh"]');p.failProfile(true);refresh.click();
      await waitFor(()=>workspace.querySelector('[data-profile-action-status]').textContent);
      assert.equal(refresh.disabled,false,'failed refresh can be retried');p.failProfile(false);refresh.click();
      await waitFor(()=>!workspace.querySelector('[data-profile-action-status]').textContent);
      if(candidates.some(c=>c.status==='pending')){
        workspace.querySelector('[data-suggestion-select="all"]').click();const form=workspace.querySelector('[data-person-profile-form="decide"]'),reject=form.querySelector('[value="reject"]');reject.focus();
        form.dispatchEvent(new p.w.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:reject}));
        await waitFor(()=>!workspace.querySelector('[name="candidate"]'));
        assert.equal(workspace.querySelector('[data-person-profile-form="decide"] button'),null,'last decision removes useless controls');
        assert.equal(d.activeElement,workspace.querySelector('[data-person-profile-action="refresh"]'),'completed decision keeps keyboard focus in the workspace');
      }
    }finally{p.close();}
  }
  console.log('PASS person empty/pending/completed suggestion states and explicit keyboard destination');
  const p=await page('sources?id=s1',{}, {body_html:'',abstract:'',display_abstract:'',preview_excerpt:{abstract_mode:'missing',notice:'synthetic processing note'},reading_access:{platform_files:[],official_files:[],has_body:false}});
  try{
    const d=p.w.document;d.querySelector('[data-action="detail"]').click();await waitFor(()=>d.querySelector('.ux-reading-article'));
    const visible=d.querySelector('[data-reading-abstract="chinese"]');assert.equal(visible.textContent,'暂无摘要');assert.equal(visible.querySelector('.prose'),null,'missing abstract is not fabricated');
    const original=d.querySelector('[data-action="reading-language"][data-language="original"]');original.click();assert.equal(d.querySelector('[data-reading-title]').textContent,'Harbour culture');
    assert.equal(d.querySelector('[data-reading-abstract="original"]').hidden,false,'original version remains available');
    assert.equal(d.querySelector('[data-reading-machine-title]').hidden,true,'original view does not carry a machine-title label');
    assert.equal(d.querySelector('[data-action="ux-read-body"]'),null,'bibliography does not claim saved full text');
  }finally{p.close();}
  console.log('PASS metadata-only record stays honest and original-title language control works');
})().catch(error=>{console.error(error);process.exitCode=1;});
