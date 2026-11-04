/* Public page event seam; no browser/layout claims. Run: node tests/ingestion_ui.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');

function page(storage = new Map()) {
  const listeners = {}, saved = new Map(), forms = new Map();
  const fields = ['enabled', 'frequency_hours', 'inclusion_rule', 'backfill_days'];
  for (const id of ['a', 'b']) {
    saved.set(id, {source_id:id, name:`Source ${id}`, enabled:true, frequency_hours:24,
      inclusion_rule:'research_only', backfill_days:30, runs:[], scope:'Synthetic only'});
    const form = {dataset:{id}, elements:{}, button:{disabled:false}, error:{textContent:''},
      closest:selector=>selector.includes('ingestion-config') ? form : null,
      querySelector:selector=>selector.includes('submit') ? form.button : form.error,
      reportValidity:()=>true};
    for (const key of fields) form.elements[key] = {value:String(saved.get(id)[key]), checked:saved.get(id)[key]};
    forms.set(id, form);
  }
  const noopNode = {textContent:'', innerHTML:'', disabled:false, className:'', setAttribute(){}, querySelector(){return noopNode}, querySelectorAll(){return []}};
  const nodes = new Map();
  const root = {isConnected:true, querySelector:selector=>{
    if(!nodes.has(selector))nodes.set(selector,{...noopNode});return nodes.get(selector);
  }, querySelectorAll:()=>[]};
  const calls = [];
  let apiHook;
  const context = vm.createContext({console, Map, Set, Number, String, Array, Object, JSON, Date,
    encodeURIComponent, crypto:require('node:crypto').webcrypto,
    sessionStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},
    state:{me:{id:'admin', role:'admin'}}, esc:x=>String(x??''), dateTime:x=>String(x??''),
    sourceHref:x=>'#'+x, linkButton:()=>'', detailPair:()=>'', toast(){},
    document:{addEventListener:(type,handler)=>{(listeners[type]??=[]).push(handler)},
      querySelector:selector=>selector.includes('ingestion-config') ? forms.get(selector.match(/data-id="([^"]+)"/)?.[1]) : root,
      querySelectorAll:()=>[]},
    api:async (path, options)=>{
      calls.push({path,options,actor:context.state.me?.id});
      if (apiHook) {const response=await apiHook(path, options);if(response)return response;}
      if (!options) return {items:[...saved.values()].map(s=>({...s})), unavailable:[]};
      const id = path.split('/')[3];
      if (options.method==='PUT') Object.assign(saved.get(id), options.body);
      return {...saved.get(id)};
    },
    route:async ()=>{for (const [id,form] of forms) for (const key of fields) {
      form.elements[key].value=String(saved.get(id)[key]);form.elements[key].checked=saved.get(id)[key];
    }}
  });
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../static/ingestion.js'),'utf8'),context);
  const fire = async (type,target)=>{for(const handler of listeners[type]||[]) await handler({target,preventDefault(){}})};
  const edit = async (id,key,value)=>{
    const form=forms.get(id), input=form.elements[key]; input.value=String(value);input.checked=value;input.name=key;
    input.closest=selector=>selector.includes('ingestion-config')?form:null;
    await fire('input',input);await fire('change',input);
  };
  const click=action=>{
    const button={dataset:{action:'ingestion-'+action},disabled:false};button.closest=()=>button;
    return fire('click',button);
  };
  const select=async(id,checked)=>fire('change',{dataset:{ingestionSelect:id},checked,closest:()=>null});
  return {context, forms, saved, calls, fire, edit, click, select, nodes, hook:fn=>apiHook=fn};
}

test('saving one source preserves another source draft through the actual submit handler', async()=>{
  const p=page();await p.context.ingestionSystemCard();
  await p.edit('a','frequency_hours',11);await p.edit('b','frequency_hours',13);
  await p.fire('submit',p.forms.get('a'));
  assert.equal(p.saved.get('a').frequency_hours,11);
  assert.equal(p.forms.get('b').elements.frequency_hours.value,'13');
  assert.equal(p.saved.get('b').frequency_hours,24);
});

test('all and clear have an explicit source count; enable/disable save only selected drafts',async()=>{
  const p=page();await p.context.ingestionSystemCard();await p.click('all');
  assert.equal(p.nodes.get('[data-ingestion-count]').textContent,'已选 2 个来源');
  await p.click('clear');assert.equal(p.nodes.get('[data-ingestion-count]').textContent,'已选 0 个来源');
  assert.equal(p.nodes.get('[data-action="ingestion-save"]').disabled,true);
  await p.select('a',true);await p.edit('a','frequency_hours',17);await p.edit('b','frequency_hours',19);
  await p.click('disable');assert.equal(p.saved.get('a').enabled,false);assert.equal(p.saved.get('a').frequency_hours,17);
  assert.equal(p.saved.get('b').enabled,true);assert.equal(p.saved.get('b').frequency_hours,24);
  assert.equal(p.forms.get('b').elements.frequency_hours.value,'19');
  await p.click('enable');assert.equal(p.saved.get('a').enabled,true);
});

test('partial save failure preserves selection, failed draft, and other results for retry',async()=>{
  const p=page();await p.context.ingestionSystemCard();await p.click('all');
  await p.edit('a','backfill_days',60);await p.edit('b','backfill_days',90);
  p.hook((path,options)=>{if(options&&path.includes('/b/'))throw new Error('Synthetic 500');});
  await p.click('save');assert.equal(p.saved.get('a').backfill_days,60);assert.equal(p.saved.get('b').backfill_days,30);
  assert.equal(p.forms.get('b').elements.backfill_days.value,'90');
  assert.equal(p.nodes.get('[data-ingestion-count]').textContent,'已选 2 个来源');
  assert.match(p.nodes.get('[data-ingestion-result="b"]').textContent,/保存失败.*Synthetic 500/);
  p.hook(null);await p.fire('submit',p.forms.get('b'));assert.equal(p.saved.get('b').backfill_days,90);
});

test('save response keeps newer edits and duplicate submit does not send twice',async()=>{
  const p=page();await p.context.ingestionSystemCard();await p.edit('a','frequency_hours',11);
  let release;const gate=new Promise(resolve=>release=resolve);
  p.hook((path,options)=>options?gate:undefined);
  const first=p.fire('submit',p.forms.get('a'));await p.fire('submit',p.forms.get('a'));
  await p.edit('a','frequency_hours',23);release();await first;
  assert.equal(p.calls.filter(call=>call.options?.method==='PUT').length,1);
  assert.equal(p.saved.get('a').frequency_hours,11);
  assert.equal(p.forms.get('a').elements.frequency_hours.value,'23');
  assert.match(p.nodes.get('[data-ingestion-draft="a"]').textContent,/未保存/);
});

test('refresh waiting for HTTP keeps edits and selections made after refresh began',async()=>{
  const p=page();await p.context.ingestionSystemCard();let release;
  const gate=new Promise(resolve=>release=resolve);p.hook((path,options)=>!options?gate:undefined);
  const pending=p.click('refresh');await p.edit('b','frequency_hours',29);await p.select('b',true);
  release();await pending;assert.equal(p.forms.get('b').elements.frequency_hours.value,'29');
  assert.equal(p.nodes.get('[data-ingestion-count]').textContent,'已选 1 个来源');
});

test('poll skips drafts, blocks repeated clicks, and unknown result retry keeps request identity',async()=>{
  const p=page();await p.context.ingestionSystemCard();await p.click('all');await p.edit('b','frequency_hours',31);
  let release;const gate=new Promise(resolve=>release=resolve);
  p.hook((path,options)=>options?.method==='POST'?gate:undefined);
  const pending=p.click('poll');await p.click('poll');release();await pending;
  let posts=p.calls.filter(call=>call.options?.method==='POST');assert.equal(posts.length,1);assert.match(posts[0].path,/\/a\/ingestion\/run$/);
  p.hook((path,options)=>{if(options?.method==='POST')throw new Error('Response lost');});await p.click('poll');
  p.hook(null);await p.click('poll');posts=p.calls.filter(call=>call.options?.method==='POST');
  assert.equal(posts[1].options.body.request_id,posts[2].options.body.request_id);
  assert.notEqual(posts[0].options.body.request_id,posts[1].options.body.request_id);
});

test('an older refresh response cannot undo a save completed while refresh waited',async()=>{
  const p=page();await p.context.ingestionSystemCard();
  const stale={items:[...p.saved.values()].map(source=>({...source})),unavailable:[]};
  let release;const gate=new Promise(resolve=>release=resolve);
  p.hook(async(path,options)=>{if(!options){await gate;return stale;}});
  const pending=p.click('refresh');await p.edit('a','frequency_hours',37);
  await p.fire('submit',p.forms.get('a'));release();await pending;
  assert.equal(p.saved.get('a').frequency_hours,37);
  assert.equal(p.forms.get('a').elements.frequency_hours.value,'37');
  assert.equal(p.nodes.get('[data-ingestion-draft="a"]').textContent,'设置已保存');
});

test('clearing a numeric input remains empty so a user can type a replacement',async()=>{
  const p=page();await p.context.ingestionSystemCard();await p.edit('a','frequency_hours','');
  assert.equal(p.forms.get('a').elements.frequency_hours.value,'');
  await p.edit('a','frequency_hours',41);await p.fire('submit',p.forms.get('a'));
  assert.equal(p.saved.get('a').frequency_hours,41);
});

test('an unknown poll result keeps its identity across a browser page reload',async()=>{
  const storage=new Map(),first=page(storage);await first.context.ingestionSystemCard();await first.select('a',true);
  first.hook((path,options)=>{if(options?.method==='POST')throw new Error('Response lost');});await first.click('poll');
  const second=page(storage);await second.context.ingestionSystemCard();await second.select('a',true);await second.click('poll');
  assert.equal(first.calls.find(call=>call.options?.method==='POST').options.body.request_id,
    second.calls.find(call=>call.options?.method==='POST').options.body.request_id);
});

for(const action of ['save','poll'])for(const outcome of ['response','error'])for(const reopen of [false,true])test(`${action} stops remaining writes after account switches during ${outcome}, reopened=${reopen}`,async()=>{
  const p=page();await p.context.ingestionSystemCard();await p.click('all');
  await p.edit('a','frequency_hours',11);if(action==='poll')await p.fire('submit',p.forms.get('a'));
  p.calls.length=0;
  let release;const gate=new Promise(resolve=>release=resolve);
  p.hook(async(path,options)=>{if(options){await gate;if(outcome==='error')throw new Error('账号已切换');}});
  const pending=p.click(action);p.context.state.me={id:'other-admin',role:'admin'};
  if(reopen)await p.context.ingestionSystemCard();
  const before=p.nodes.get('[data-ingestion-summary]').textContent;
  release();await pending;
  assert.deepEqual(p.calls.filter(c=>c.options).map(c=>[c.path,c.actor]),[[`/api/sources/a/ingestion${action==='poll'?'/run':''}`,'admin']]);
  assert.equal(p.nodes.get('[data-ingestion-summary]').textContent,before,'old batch must not repaint another account');
  // Returning to the original view must not strand unexecuted sources busy.
  p.context.state.me={id:'admin',role:'admin'};if(reopen)await p.context.ingestionSystemCard();p.hook(null);
  await p.fire('submit',p.forms.get('b'));
  assert.equal(p.calls.filter(c=>c.options&&c.path.includes('/b/')).length,1);
});

test('returning to the same account with a replacement view does not resume an old batch',async()=>{
  const p=page();await p.context.ingestionSystemCard();await p.click('all');
  let release;const gate=new Promise(resolve=>release=resolve);p.hook((path,options)=>options?gate:undefined);
  const pending=p.click('save');
  p.context.state.me={id:'other-admin',role:'admin'};await p.context.ingestionSystemCard();
  p.context.state.me={id:'admin',role:'admin'};await p.context.ingestionSystemCard();
  release();await pending;
  assert.equal(p.calls.filter(c=>c.options).length,1,'view replacement must stop the second write even when the account id matches again');
  p.hook(null);await p.fire('submit',p.forms.get('b'));
  assert.equal(p.calls.filter(c=>c.options).length,2,'the new view can submit its own intent');
});
