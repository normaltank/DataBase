/* Actual page event/read seams. Browser layout is checked separately. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {test}=require('node:test');

function page(){
  const pending=[],listeners={};
  const jobs={innerHTML:'',querySelectorAll:()=>[]};
  const context=vm.createContext({state:{me:{id:'one'},schema:29,page:'maintenance-agent'},
    document:{addEventListener:(name,fn)=>{(listeners[name]??=[]).push(fn);},querySelector:s=>s==='[data-maintenance-jobs]'?jobs:null,querySelectorAll:()=>[]},
    api:(url,options)=>new Promise((resolve,reject)=>pending.push({url,options,resolve,reject})),
    esc:String,dateTime:String,linkButton:()=>'<a>Article</a>',CSS:{escape:String},crypto:{randomUUID:(()=>{let n=0;return()=>`request-${++n}`;})()}});
  for(const file of ['maintenance-agent.js','maintenance-feedback.js'])vm.runInContext(fs.readFileSync('static/'+file,'utf8'),context);
  return {context,pending,listeners,jobs,run:code=>vm.runInContext(code,context)};
}
const result=status=>({items:[{id:'job',status,title:'Article',target_id:'a',target_type:'record',created_at:'now',steps:[],evidence:[]}],overview:{counts:{},recent_changes:[]}});

test('newer status read wins over an older poll response',async()=>{
  const p=page();p.run("maintenanceAgentState={actor:'one',jobs:[]};globalThis.first=maintenanceReload(maintenanceAgentState);globalThis.second=maintenanceReload(maintenanceAgentState)");
  p.pending[1].resolve(result('completed'));await p.context.second;
  p.pending[0].resolve(result('running'));await p.context.first;
  assert.match(p.jobs.innerHTML,/已完成/);assert.doesNotMatch(p.jobs.innerHTML,/正在整理/);
});

test('target status read ignores an older response and a changed account',async()=>{
  const p=page(),nodes={};
  const panel={dataset:{feedbackActor:'one',feedbackKind:'person',feedbackId:'p'},isConnected:true,
    querySelector:s=>nodes[s]??=( {textContent:'',innerHTML:''} )};
  p.context.panel=panel;
  p.run('globalThis.first=refreshMaintenanceFeedback(panel);globalThis.second=refreshMaintenanceFeedback(panel)');
  p.pending[1].resolve(result('completed'));await p.context.second;
  p.pending[0].resolve(result('running'));await p.context.first;
  assert.equal(nodes['[data-feedback-status]'].textContent,'已完成');
  const late=p.run('refreshMaintenanceFeedback(panel)');p.context.state.me.id='two';
  p.pending[2].resolve(result('running'));await late;
  assert.equal(nodes['[data-feedback-status]'].textContent,'已完成');
});

test('one-click maintenance retries the same request without requiring feedback',async()=>{
  const p=page(),nodes={};
  const root={dataset:{actor:'one',kind:'source',id:'s'},isConnected:true,querySelector:s=>nodes[s]??={textContent:'',disabled:false}};
  const button={closest:()=>root};
  const event={target:{closest:s=>s==='[data-maintenance-start]'?button:null}};
  const click=()=>Promise.all(p.listeners.click.map(fn=>fn(event)));
  const first=click();
  assert.equal(p.pending.length,1);assert.equal(p.pending[0].url,'/api/maintenance/jobs');
  assert.deepEqual(JSON.parse(JSON.stringify(p.pending[0].options.body)),{target_type:'source',target_id:'s',request_id:'request-1'});
  await click();assert.equal(p.pending.length,1);
  p.pending[0].reject(new Error('Synthetic lost response'));await first;
  assert.match(nodes['.form-error'].textContent,/Synthetic/);
  const retry=click();assert.equal(p.pending[1].options.body.request_id,'request-1');
  p.pending[1].resolve({id:'job'});await retry;
  assert.match(nodes['[data-maintenance-action-status]'].textContent,/等待处理/);
  const late=click();p.context.state.me.id='two';p.pending[2].reject(new Error('Old account failure'));await late;
  assert.doesNotMatch(nodes['.form-error'].textContent,/Old account/);
});
