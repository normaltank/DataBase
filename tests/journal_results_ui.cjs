/* Actual page-event handlers; browser/layout verification lives in the browser check. */
const assert=require('node:assert/strict');
const {test}=require('node:test');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

function page(){
  const listeners={},calls=[],navigations=[],messages=[];
  const original={name:'synthetic.docx',bytes:'UNCHANGED ORIGINAL'};
  const fields=new Map([['files',original],['file_note','Uncommitted member note']]);
  const error={textContent:''},conflict={innerHTML:''},button={disabled:false,textContent:"Save"};
  const form={dataset:{jrForm:'files',id:'result-one',series:'series-one',version:'2',request:'stable-request-001'},isConnected:true,
    matches:()=>true,hasAttribute:()=>false,querySelector:selector=>selector==='[type=submit]'?button:selector==='.form-error'?error:conflict};
  class FormData {
    constructor(){this.fields=new Map(fields);}
    get(key){return this.fields.get(key);}
    set(key,value){this.fields.set(key,value);}
    [Symbol.iterator](){return this.fields[Symbol.iterator]();}
  }
  let hook=async()=>({id:'result-one'});
  const context=vm.createContext({URLSearchParams,Map,Set,String,Number,Object,Array,JSON,FormData,
    crypto:require('node:crypto').webcrypto,encodeURIComponent,
    state:{me:{id:'member-one'},loadId:1,params:new URLSearchParams(),page:'journal-results'},
    esc:x=>String(x),dateTime:x=>x,readableFileSize:x=>String(x),
    location:{hash:'#journal-results'},scrollY:0,
    document:{addEventListener:(type,handler)=>(listeners[type]??=[]).push(handler),querySelector:()=>null,querySelectorAll:()=>[]},
    api:async(url,options)=>{calls.push({url,options});return hook(url,options);},
    go:(...args)=>navigations.push(args),toast:message=>messages.push(message),route:async()=>{}
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/journal-results.js'),'utf8'),context);
  return {context,calls,navigations,messages,fields,original,form,error,conflict,button,hook:fn=>hook=fn,
    click:async attribute=>{const b={dataset:{},disabled:false,isConnected:true,hasAttribute:key=>key===attribute,closest:selector=>selector==='form'?form:b};for(const handler of listeners.click)await handler({target:b});},
    submit:async()=>{for(const handler of listeners.submit)await handler({target:form,preventDefault(){}});}};
}

test('a pending save sends one request even when submit fires twice',async()=>{
  const p=page();let release;const gate=new Promise(resolve=>release=resolve);
  p.hook(()=>gate);const pending=p.submit(),duplicate=p.submit();
  const count=p.calls.length;release({id:'result-one'});await Promise.all([pending,duplicate]);assert.equal(count,1);
  assert.equal(p.navigations.length,1);
});

test('a lost response keeps selected bytes, text and request identity for retry',async()=>{
  const p=page();p.hook(()=>{throw new Error('Synthetic connection failure');});await p.submit();
  assert.equal(p.fields.get('files'),p.original);assert.equal(p.fields.get('file_note'),'Uncommitted member note');
  assert.match(p.error.textContent,/connection failure/);assert.equal(p.navigations.length,0);
  p.hook(async()=>({id:'result-one'}));await p.submit();
  const payload=p.calls.map(c=>JSON.parse(c.options.body.get('data')));
  assert.equal(payload[0].request_id,'stable-request-001');assert.equal(payload[1].request_id,'stable-request-001');
  assert.equal(payload[1].series_id,'series-one');assert.equal(p.calls[1].options.body.get('files'),p.original);
});

test('a stale save shows a recovery action and blocks overwrite while retaining draft',async()=>{
  const p=page();p.hook(()=>{const e=new Error('Synthetic stale version');e.status=409;throw e;});await p.submit();
  assert.match(p.conflict.innerHTML,/读取最新状态/);assert.equal(p.form.dataset.conflict,'true');
  assert.equal(p.fields.get('files'),p.original);await p.submit();assert.equal(p.calls.length,1);
});

test('a save response after account switch cannot navigate or announce success',async()=>{
  const p=page();let release;const gate=new Promise(resolve=>release=resolve);p.hook(()=>gate);
  const pending=p.submit();p.context.state.me={id:'another-member'};release({id:'result-one'});await pending;
  assert.equal(p.navigations.length,0);assert.equal(p.messages.length,0);
});


test('lost creation response and changed draft recover the committed result without another create',async()=>{
  const p=page();Object.assign(p.form.dataset,{jrForm:'create',id:'',series:''});
  for(const [key,value] of Object.entries({journal_name:'Synthetic',year:2026,issue:'1',note:'Original'}))p.fields.set(key,value);
  p.hook(()=>{throw new Error('Response lost after commit');});await p.submit();
  assert.equal(p.button.disabled,true);assert.match(p.error.textContent,/这期可能已保存/);
  p.fields.set('note','Changed after response lost');
  await p.submit();assert.equal(p.calls.length,1);
  assert.match(p.conflict.innerHTML,/data-jr-recover/);
  const result={id:'committed-one',journal_name:'Synthetic',year:2026,issue:'1',version:1,note:'Original',files:[{versions:[{name:'synthetic.docx',version:1}]}]};
  p.hook(async()=>({action:'create',result}));await p.click('data-jr-recover');
  assert.equal(p.navigations.length,0);assert.equal(p.button.disabled,false);
  assert.equal(p.calls.filter(c=>c.options?.method==='PUT').length,0); // Reading does not save changes.
  assert.equal(p.form.dataset.id,'committed-one');assert.equal(p.form.dataset.jrForm,'metadata');
  assert.equal(p.fields.get('files'),p.original);assert.equal(p.fields.get('file_note'),'Uncommitted member note');
  assert.equal(p.fields.get('note'),'Changed after response lost');
  assert.equal(p.button.textContent,'将当前期次信息保存到这期');
  p.hook(async()=>({id:'committed-one'}));await p.submit();
  const last=p.calls.at(-1);assert.equal(last.url,'/api/journal-results/committed-one');
  assert.equal(last.options.method,'PUT');assert.equal(last.options.body.note,'Changed after response lost');
  assert.equal(last.options.body.version,1);assert.notEqual(last.options.body.request_id,'stable-request-001');
  assert.equal(p.calls.filter(c=>c.options?.method==='POST').length,1);
});


test('a create conflict replaces backend language and stops repeated creation until lookup',async()=>{
  const p=page();Object.assign(p.form.dataset,{jrForm:'create',id:'',series:''});
  p.hook(()=>{const e=new Error('同一保存请求的内容已改变');e.status=409;throw e;});await p.submit();
  assert.equal(p.error.textContent,'这期可能已保存，请先查看结果。');assert.equal(p.button.disabled,true);
  await p.submit();assert.equal(p.calls.length,1);assert.match(p.conflict.innerHTML,/查看保存结果/);
});

test('an absent receipt permits retrying the original save without changing its identity',async()=>{
  const p=page();Object.assign(p.form.dataset,{jrForm:'create',id:'',series:''});
  p.hook(()=>{throw new Error('Lost response');});await p.submit();
  p.hook(()=>{const e=new Error('尚未找到这次保存的成果，可重试保存。');e.status=404;throw e;});await p.click('data-jr-recover');
  assert.equal(p.button.disabled,false);assert.equal(p.button.textContent,'重试保存一期成果');
  assert.equal(p.form.dataset.request,'stable-request-001');
  p.hook(async()=>({id:'created-one'}));await p.submit();
  assert.equal(p.calls.at(-1).options.method,'POST');
  assert.equal(JSON.parse(p.calls.at(-1).options.body.get('data')).request_id,'stable-request-001');
});
