'use strict';
const {JSDOM}=require('jsdom'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),readline=require('node:readline');
const dom=new JSDOM('<main id="content"></main><div id="modal-root"><div class="drawer-body"></div></div>',{runScripts:'outside-only',url:'http://synthetic.local/'}),w=dom.window;
let sequence=0,pending=new Map(),writes=[],loseNext=false,tid,holdNext=false,held;
readline.createInterface({input:process.stdin}).on('line',line=>{const r=JSON.parse(line);pending.get(r.id)(r);pending.delete(r.id);});
function http(url,options={}){return new Promise(resolve=>{const id=++sequence;pending.set(id,resolve);process.stdout.write(JSON.stringify({id,url,...options})+'\n');});}
Object.assign(w,{esc:v=>String(v??'').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;'),dateTime:v=>v||'',toast(){},journalWorkPage(){},workMaterialTools(){return '';},workReturnButton(){return '';},linkButton:(label,action,id='',cls='button')=>`<button class="${cls}" data-action="${action}" data-id="${id}">${label}</button>`,modal(title,html){w.document.querySelector('.drawer-body').innerHTML='<h2>'+title+'</h2>'+html;},closeModal(){w.document.querySelector('.drawer-body').innerHTML='';}});
w.readableFileSize=bytes=>bytes+' B';
w.eval(`var state={me:{id:'researcher'},loadId:1,params:new URLSearchParams(),page:'collaboration',collections:[]};var modalGeneration=0;`);
w.api=async(url,options={})=>{
  const body=options.body;
  let payload=body,file;
  if(body instanceof w.FormData){payload=JSON.parse(body.get('data'));const f=body.get('file');if(f?.size)file={name:f.name,base64:Buffer.from(await new Promise((resolve,reject)=>{const r=new w.FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsArrayBuffer(f);})).toString('base64')};}
  if(options.method==='POST')writes.push({url,body:payload});
  if(holdNext){holdNext=false;await new Promise(resolve=>held=resolve);}
  const result=await http(url,{method:options.method||'GET',body:payload,file});
  if(result.status>=400)throw Object.assign(new Error(result.body.error),{status:result.status});
  if(loseNext&&options.method==='POST'){loseNext=false;throw new Error('synthetic unknown result');}
  return result.body;
};
for(const file of ['collaboration.js','topic-review.js','topic-finals.js','topic-closure.js','workbench.js','topic-handoffs.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../static',file),'utf8'),dom.getInternalVMContext());
const tick=()=>new Promise(r=>setTimeout(r,5));async function until(fn){for(let i=0;i<1500;i++){if(fn())return;await tick();}throw new Error('DOM operation timed out: '+w.document.body.textContent.slice(-500));}
w.route=async()=>{w.document.querySelector('#content').innerHTML=await w.workbenchTopic(tid);};
w.go=async(page,params)=>{w.eval('state').params=new w.URLSearchParams(params);await w.route();};
function submit(form,value){form.dispatchEvent(new w.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:form.querySelector(value?`[value="${value}"]`:'[type=submit]')}));}
function file(form,name='flow.txt',text='synthetic DOM original'){const f=new w.File([text],name,{type:'text/plain'});Object.defineProperty(form.elements.file,'files',{value:[f],configurable:true});const Native=w.FormData;if(!w._filePatched){w.FormData=class extends Native{constructor(form){super(form);if(form?.elements.file?.files[0])this.set('file',form.elements.file.files[0]);}};w._filePatched=true;}return f;}
async function login(who){await http('/api/login',{method:'POST',body:{username:who,password:'LocalDemo2026!'}});w.eval('state').me.id=who;}
async function upload(stage='selection',material){w.eval('state').params.set('tab',stage);await w.route();let form=material?w.document.querySelector(`[data-material="${material}"]`):w.document.querySelector('[data-form=handoff-upload][data-material=""]');file(form);submit(form);await until(()=>!form.isConnected);return (await w.api(`/api/collaboration/topics/${tid}/handoffs`)).materials.filter(m=>m.stage===stage&&m.owner_id===w.eval('state').me.id).at(-1);}
async function review(value,unknown=false){await login('researcher');await w.route();const form=w.document.querySelector('[data-form=handoff-review]');assert(form,'lead can review selection');if(unknown)loseNext=true;submit(form,value);if(unknown){await until(()=>form.dataset.saving==='false');assert.match(form.querySelector('.form-error').textContent,/unknown result/);const attempt=writes.at(-1);submit(form,value);await until(()=>!form.isConnected);assert.deepEqual(writes.at(-1),attempt);}else await until(()=>!form.isConnected);}
(async()=>{
 await login('admin');await w.api('/api/collaboration/qualifications/researcher',{method:'PUT',body:{version:0,enabled:true}});await login('researcher');tid=(await w.api('/api/collaboration/topics',{method:'POST',body:{theme:'DOM synthetic handoffs',participant_ids:['colleague']}})).id;
 await w.route();assert.equal(w.document.querySelectorAll('[data-action=topic-review-meeting]').length,0);assert(w.document.querySelector('[data-action=topic-review-enter]'));
 await login('colleague');await w.route();const f=w.document.querySelector('[data-form=handoff-upload]');file(f);loseNext=true;const before=writes.length;submit(f);submit(f);submit(f);await until(()=>f.dataset.saving==='false');assert.equal(writes.length,before+1);assert.match(f.querySelector('.form-error').textContent,/unknown result/);const first=writes.at(-1);submit(f);await until(()=>!f.isConnected);assert.deepEqual(writes.at(-1),first);
 let b=await w.api(`/api/collaboration/topics/${tid}/handoffs`);assert.equal(b.materials.length,1);let ref=b.materials[0].ref;
 await review('returned',true);await login('colleague');await upload('selection',ref);await review('approved');
 b=await w.api(`/api/collaboration/topics/${tid}/handoffs`);assert.equal(b.materials[0].status,'approved');assert.equal(b.materials[0].versions.length,2);
 w.document.querySelector('[data-action=topic-review-enter]').click();await until(()=>w.document.querySelector('[data-form=topic-stage-enter]'));const stage=w.document.querySelector('[data-form=topic-stage-enter]');submit(stage);await until(()=>!stage.isConnected);assert.equal((await w.api(`/api/collaboration/topics/${tid}/handoffs`)).stage,'compilation');
 await login('colleague');ref=(await upload('compilation')).ref;await review('returned');await login('colleague');await upload('compilation',ref);await review('approved');
 // Owner+lead can submit and review their own independent material.
 await upload('compilation');await review('approved');
 // An open form captured under another account cannot write as the new one.
 await login('colleague');await w.route();const retained=w.document.querySelector('[data-form=handoff-upload][data-material=""]');file(retained);await login('admin');const count=writes.length;submit(retained);await tick();assert.equal(writes.length,count);assert.match(retained.querySelector('.form-error').textContent,/账号已切换/);
 await login('researcher');await w.route();w.document.querySelector('[data-action=topic-closure-end]').click();await until(()=>w.document.querySelector('[data-form=topic-closure]'));const end=w.document.querySelector('[data-form=topic-closure]');submit(end);await until(()=>/已结束/.test(w.document.querySelector('.workbench-detail-meta').textContent));assert.match(w.document.querySelector('.workbench-detail-meta').textContent,/已结束 · 负责人/);assert.equal(w.document.querySelectorAll('[data-form=handoff-upload]').length,0);
 w.document.querySelector('[data-action=topic-closure-reopen]').click();await until(()=>w.document.querySelector('[data-form=topic-closure]'));const reopen=w.document.querySelector('[data-form=topic-closure]');submit(reopen);await until(()=>!reopen.isConnected);assert.equal((await w.api(`/api/collaboration/topics/${tid}/handoffs`)).stage,'compilation');
 // A qualifying old final uses the unchanged legacy HTTP chain, then the new
 // workbench's secondary entry must still permit first/new optional summaries.
 tid=(await w.api('/api/collaboration/topics',{method:'POST',body:{theme:'DOM synthetic old final and optional summary',participant_ids:['colleague']}})).id;
 const base=`/api/collaboration/topics/${tid}`;
 await w.api(base+'/meetings',{method:'POST',body:{request_id:'legacy-meeting',version:0,topic_version:1,assignments:[{title:'Synthetic old final',author_id:'colleague'}]}});
 let topic=await w.api(base);await w.api(base+'/enter-compilation',{method:'POST',body:{request_id:'legacy-enter',topic_version:topic.version,stage_version:topic.stage_version}});
 let workflow=await w.api(base+'/workflow'),assignment=workflow.assignments[0];
 await login('colleague');const draft=new w.FormData();draft.set('data',JSON.stringify({request_id:'legacy-draft',topic_version:1,meeting_version:1,version:0}));draft.set('file',new w.File(['synthetic old final original'],'old-final.txt'));
 const saved=await w.api(base+'/assignments/'+assignment.id+'/submissions',{method:'POST',body:draft});
 const existing=(await w.api('/api/records',{method:'POST',body:{kind:'compilation',title:'Synthetic existing summary result',body_html:'<p>Preserve author text</p>',visibility:'shared',sharing_confirmed:true}})).id;
 const beforeRecord=await w.api('/api/records/'+existing);
 await login('researcher');const final=await w.api(base+'/assignments/'+assignment.id+'/finals',{method:'POST',body:{request_id:'legacy-final',topic_version:1,meeting_version:1,version:1,submission_id:saved.id,status:'pending',visibility:'restricted'}});
 for(const version of [1,2]){
   await w.route();const history=w.document.querySelector('[data-action=handoff-legacy]');assert.equal(history.closest('details').open,false);history.click();
   await until(()=>w.document.querySelector('[data-action=topic-finals-summary]'));w.document.querySelector('[data-action=topic-finals-summary]').click();
   await until(()=>w.document.querySelector('[data-form=topic-finals-summary]'));const summary=w.document.querySelector('[data-form=topic-finals-summary]');
   assert.equal(summary.querySelector('[type=submit]').textContent,'保存整期汇总 v'+version);
   const adoption=summary.querySelector(`[name=final_ids][value="${final.id}"]`);adoption.checked=true;adoption.dispatchEvent(new w.Event('change',{bubbles:true}));file(summary,'summary-'+version+'.txt','synthetic optional summary '+version);
   if(version===2){
     summary.elements.author_id.value='colleague';summary.elements.record_query.value='Synthetic existing summary result';summary.querySelector('[data-action=topic-finals-search]').click();
     await until(()=>summary.elements.record_id.querySelector(`[value="${existing}"]`));summary.elements.record_id.value=existing;
   }
   submit(summary);await until(()=>!summary.isConnected);
   workflow=await w.api(base+'/workflow');assert.equal(workflow.summaries.length,version);assert.equal(workflow.summaries[0].version,version);assert.equal(workflow.summaries[0].adoptions[0].id,final.id);
   if(version===2)assert.equal(workflow.summaries[0].record.id,existing);
 }
 const afterRecord=await w.api('/api/records/'+existing);for(const key of ['body_html','visibility','author_id','version','editors'])assert.deepEqual(afterRecord[key],beforeRecord[key],'summary association preserves existing result '+key);
 // The same historical content remains readable after closing, with no summary write entry.
 await w.route();w.document.querySelector('[data-action=topic-closure-end]').click();await until(()=>w.document.querySelector('[data-form=topic-closure]'));const legacyEnd=w.document.querySelector('[data-form=topic-closure]');submit(legacyEnd);await until(()=>!legacyEnd.isConnected);
 w.document.querySelector('[data-action=handoff-legacy]').click();await until(()=>w.document.querySelector('[data-summary-card]'));assert.equal(w.document.querySelector('[data-action=topic-finals-summary]'),null);assert.equal((await w.api(base)).can_submit_summary,false);
 process.stdout.write(JSON.stringify({done:true,unknown_result_retry:true,account_switch_blocked:true,two_stages:true,solo_lead:true,closed_lead_label:true,optional_legacy_summary_versions:2,existing_result_association:true,closed_summary_read_only:true,writes:writes.length})+'\n');w.close();process.exit(0);
})().catch(error=>{process.stderr.write(error.stack+'\n');w.close();process.exit(1);});
