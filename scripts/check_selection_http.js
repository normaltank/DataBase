'use strict';
// Driven by check_selection_http.py: DOM events → real authenticated Flask HTTP.
const {JSDOM}=require('jsdom'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),readline=require('node:readline');
const dom=new JSDOM('<div id="modal-root"><div class="drawer-body"></div></div>',{runScripts:'outside-only',url:'http://synthetic.local'}),w=dom.window;
let sequence=0,pending=new Map(),loseNext=false,requests=[];
readline.createInterface({input:process.stdin}).on('line',line=>{const response=JSON.parse(line),resolve=pending.get(response.id);pending.delete(response.id);resolve(response);});
function http(url,options={}){return new Promise(resolve=>{const id=++sequence;pending.set(id,resolve);process.stdout.write(JSON.stringify({id,url,method:options.method||'GET',body:options.body,headers:options.headers})+'\n');});}
Object.assign(w,{esc:v=>String(v??'').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;'),dateTime:v=>v||'',externalLink:()=>'',toast(){},go(){},route:async()=>{},loadLookups:async()=>{},closeModal(){w.document.querySelector('.drawer-body').innerHTML='';},modal(title,html){w.document.querySelector('.drawer-body').innerHTML=html;},isInstitution:s=>s.kind==='institution',isPublication:s=>s.kind==='journal'});
w.eval(`var state={me:{id:'admin'},sources:[],params:new URLSearchParams({status:'all',q:'SELECTION108'}),page:'maintenance-sources'};`);
w.api=async(url,options={})=>{if(options.body instanceof w.FormData)options={...options,body:JSON.parse(options.body.get('data'))};if(options.method==='POST')requests.push({url,...options.body});const result=await http(url,options);if(result.status>=400)throw Object.assign(new Error(result.body.error),{status:result.status});if(loseNext&&options.method==='POST'){loseNext=false;throw new Error('synthetic response lost after persistent HTTP success');}return result.body;};
for(const file of ['collaboration.js','topic-review.js','archive-suggestions.js','person-profile-suggestions.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../static',file),'utf8'),dom.getInternalVMContext());
const tick=()=>new Promise(r=>setTimeout(r,5));
async function until(fn){for(let i=0;i<1000;i++){if(fn())return;await tick();}throw new Error('DOM operation did not finish');}
function change(input){input.checked=true;input.dispatchEvent(new w.Event('change',{bubbles:true}));}
function submit(form,decision){form.dispatchEvent(new w.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:form.querySelector(decision?`[type=submit][value=${decision}]`:'[type=submit]')}));}
async function queueAndRetry(form){loseNext=true;const before=requests.length;submit(form);submit(form);submit(form);await until(()=>form.dataset.saving==='false');assert.equal(requests.length,before+1);assert.match(form.querySelector('.form-error').textContent,/response lost/);const first=requests.at(-1);submit(form);await until(()=>!form.isConnected);assert.equal(requests.at(-1).request_id,first.request_id);return first;}
(async()=>{
  await w.archiveBatchForm();const sf=w.document.querySelector('[data-form=archive-batch]');assert.equal(sf.querySelectorAll('[name=source]').length,21);assert.equal(sf.querySelector('[data-batch-select=all]').disabled,true);
  const ids=[...sf.querySelectorAll('[name=source]')].slice(0,2).map(x=>{change(x);return x.value;});await queueAndRetry(sf);
  for(const id of ids){const state=await w.api('/api/sources/'+id+'/suggestions');assert.equal(state.jobs.length,1);assert.equal(state.jobs[0].status,'queued');}
  await w.authorBatchForm();const af=w.document.querySelector('[data-form=author-batch]'),first=af.querySelector('[name=author_record]');change(first);const rid=first.value;
  const search=w.document.querySelector('[data-form=author-search]');search.querySelector('input').value='SELECTION108 second';submit(search);await until(()=>af.textContent.includes('second'));assert.match(af.textContent,/当前未显示 1/);await queueAndRetry(af);
  assert.equal((await w.api('/api/records/'+rid+'/suggestions')).jobs.length,1);
  await w.collaborationTopicForm();const tf=w.document.querySelector('[data-form=collaboration-topic]');tf.elements.theme.value='SELECTION108 theme';change(tf.querySelector('[value=colleague]'));submit(tf);await until(()=>!tf.isConnected);
  const topics=await w.api('/api/collaboration/topics'),topic=topics.items.find(t=>t.theme==='SELECTION108 theme'),detail=await w.api('/api/collaboration/topics/'+topic.id);
  assert.deepEqual(detail.participants.map(p=>p.id).sort(),['admin','colleague']);
  await w.api('/api/members/colleague',{method:'PUT',body:{active:false}});
  const forged=await http('/api/collaboration/topics/'+topic.id+'/meetings',{method:'POST',body:{topic_version:detail.version,version:0,request_id:w.crypto.randomUUID(),assignments:[{title:'Invalid disabled assignee',author_id:'colleague'}]}});assert.equal(forged.status,400);
  assert.equal((await w.api('/api/collaboration/topics/'+topic.id+'/workflow')).assignments.length,0);
  await w.topicReviewMeeting(topic.id);const mf=w.document.querySelector('[data-form=topic-review-meeting]');mf.querySelector('[data-action=topic-review-add]').click();const row=mf.querySelector('[data-assignment-row]'),select=row.querySelector('[name=author_id]');assert.equal(select.value,'');assert.equal(select.querySelector('[value=colleague]').disabled,true);assert.match(row.textContent,/账号已停用/);row.querySelector('[name=title]').value='Valid selected assignee';select.value='admin';submit(mf);await until(()=>!mf.isConnected);
  const saved=(await w.api('/api/collaboration/topics/'+topic.id+'/workflow')).assignments;assert.equal(saved.length,1);assert.equal(saved[0].author_id,'admin');
  const pid=process.env.SELECTION108_PERSON_ID,person=await w.api('/api/people/'+pid),profilePath='/api/people/'+pid+'/profile-suggestions',before=await w.api(profilePath),alias=before.candidates.find(c=>c.field==='aliases'),intro=before.candidates.find(c=>c.field==='introduction');
  w.inputField=(name,label,value)=>`<label>${label}<input name="${name}" value="${value}"></label>`;w.modal('',await w.personProfileSection(person));
  let pf=w.document.querySelector('[data-person-profile-form=decide]');assert.equal(pf.querySelector('[type=submit]').disabled,true);change(pf.querySelector('[value="'+alias.id+'"]'));submit(pf,'reject');await until(()=>!pf.isConnected);pf=w.document.querySelector('[data-person-profile-form=decide]');assert.equal(pf.querySelector('[name=candidate]').value,intro.id);change(pf.querySelector('[name=candidate]'));submit(pf,'adopt');await until(()=>pf.dataset.saving==='false');
  const after=await w.api(profilePath);assert.equal(after.candidates.find(c=>c.id===alias.id).status,'rejected');assert.equal(after.candidates.find(c=>c.id===intro.id).status,'adopted');assert.equal((await w.api('/api/people/'+pid)).introduction_text,intro.value);const ai=await w.api('/api/admin/ai');assert.equal(ai.attempts.length,0);assert.equal(ai.charged_units,0);
  await w.collaborationTopicForm();const maximum=w.document.querySelector('[data-form=collaboration-topic]'),query=maximum.querySelector('[data-collaboration-member-search]'),all=maximum.querySelector('[data-action=collaboration-members-all]');
  query.value='LIMIT ';query.dispatchEvent(new w.Event('input',{bubbles:true}));
  assert.match(maximum.querySelector('[data-collaboration-member-count]').textContent,/当前查找 201 人/);assert.equal(all.disabled,true);
  const tooMany=[...maximum.querySelectorAll('[name=participant_ids]')].filter(x=>x.value.startsWith('limit-member-')).map(x=>x.value);
  const countBefore=(await w.api('/api/collaboration/topics')).items.length;
  const forgedMembers=await http('/api/collaboration/topics',{method:'POST',body:{theme:'LIMIT forged 201',participant_ids:tooMany}});assert.equal(forgedMembers.status,400);
  assert.equal((await w.api('/api/collaboration/topics')).items.length,countBefore);
  query.value='LIMIT INCLUDED';query.dispatchEvent(new w.Event('input',{bubbles:true}));all.click();
  const selectedIds=[...new w.FormData(maximum).getAll('participant_ids')];assert.equal(selectedIds.length,200);
  assert.equal(maximum.querySelector('[value=limit-member-200]').disabled,true);
  maximum.elements.theme.value='LIMIT 200 other researchers';submit(maximum);await until(()=>!maximum.isConnected);
  const savedMaximum=(await w.api('/api/collaboration/topics')).items.find(t=>t.theme==='LIMIT 200 other researchers'),maximumDetail=await w.api('/api/collaboration/topics/'+savedMaximum.id);
  assert.deepEqual(maximumDetail.participants.map(p=>p.id).sort(),['admin',...selectedIds].sort());
  // Maintenance must also retain all 200 others and allow the same legal payload.
  await w.collaborationTopicForm(savedMaximum.id);const editMaximum=w.document.querySelector('[data-form=collaboration-topic]');
  assert.equal(new w.FormData(editMaximum).getAll('participant_ids').length,200);submit(editMaximum);await until(()=>!editMaximum.isConnected);
  assert.equal((await w.api('/api/collaboration/topics/'+savedMaximum.id)).participants.length,201);
  // Actual core api() + ingestion DOM events against the same Flask session.
  // Hold the first completed write's response, then log into another admin.
  const batchDom=new JSDOM('<div id="app"></div>',{runScripts:'outside-only',url:'http://synthetic.local'}),b=batchDom.window;
  b.matchMedia=()=>({matches:false,addEventListener(){}});
  const add=b.addEventListener.bind(b);b.addEventListener=(type,handler,...rest)=>{if(type!=='DOMContentLoaded')add(type,handler,...rest);};
  b.sourceHref=id=>'#'+id;
  for(const file of ['app.js','ingestion.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../static',file),'utf8'),batchDom.getInternalVMContext());
  let hold,release,writeCalls=[];
  b.fetch=async(url,options={})=>{
    const body=typeof options.body==='string'?JSON.parse(options.body):options.body;
    const response=await http(url,{...options,body});
    if(options.method&&options.method!=='GET'){
      writeCalls.push({url,headers:options.headers});
      if(hold){hold();await new Promise(resolve=>release=resolve);}
    }
    return {ok:response.status<400,status:response.status,json:async()=>response.body};
  };
  async function batchLogin(username){
    if(username!=='admin'){const out=await http('/api/logout',{method:'POST'});assert.equal(out.status,200);}
    const login=await http('/api/login',{method:'POST',body:{username,password:'LocalDemo2026!'}});assert.equal(login.status,200);
    const session=(await http('/api/session')).body;b.eval('state.me='+JSON.stringify(session.user)+';state.csrf='+JSON.stringify(session.csrf));
  }
  for(const action of ['save','poll']){
    await batchLogin('admin');
    // Enable sources through HTTP before running the controlled batch.
    for(const source of (await http('/api/ingestion')).body.items)assert.equal((await http('/api/sources/'+source.source_id+'/ingestion',{method:'PUT',body:{enabled:true,frequency_hours:24}})).status,200);
    b.document.querySelector('#app').innerHTML=await b.ingestionSystemCard();
    const ids=[...b.document.querySelectorAll('[data-ingestion-select]')].map(x=>x.dataset.ingestionSelect);assert.equal(ids.length,2);
    for(const [i,form] of [...b.document.querySelectorAll('[data-form=ingestion-config]')].entries()){
      form.elements.frequency_hours.value=String(action==='save'?11+i:24);form.elements.frequency_hours.dispatchEvent(new b.Event('input',{bubbles:true}));
    }
    b.document.querySelector('[data-action=ingestion-all]').click();writeCalls=[];
    let firstArrived;const arrived=new Promise(resolve=>firstArrived=resolve);hold=()=>{hold=null;firstArrived();};
    b.document.querySelector('[data-action=ingestion-'+action+']').click();await arrived;
    const before=b.document.querySelector('[data-ingestion-summary]').textContent;
    await batchLogin('batch-other');release();
    await until(()=>!b.document.querySelector('[data-action=ingestion-'+action+']').disabled||b.eval('ingestionView.batch===false'));
    assert.equal(writeCalls.length,1,'the next source must never write through the new account/CSRF');
    assert.equal(b.document.querySelector('[data-ingestion-summary]').textContent,before,'old response cannot paint the new account');
    const second=(await http('/api/sources/'+ids[1]+'/ingestion')).body;
    if(action==='save')assert.equal(second.frequency_hours,24);else assert.equal(second.runs.length,0);
    // Re-enter the original account without replacing the view: unexecuted busy
    // flags must be released, so its retained second draft can still be saved.
    await batchLogin('admin');const secondForm=b.document.querySelector('[data-form=ingestion-config][data-id="'+ids[1]+'"]');
    secondForm.dispatchEvent(new b.Event('submit',{bubbles:true,cancelable:true}));await until(()=>writeCalls.length===2);await until(()=>!secondForm.querySelector('[type=submit]').disabled);
  }
  batchDom.window.close();
  process.stdout.write(JSON.stringify({done:true,requests:requests.length,source_jobs:2,record_jobs:1,topic_participants:detail.participants.map(p=>p.id),forged_assignee:forged.status,saved_assignee:saved[0].author_id,person_decisions:['rejected','adopted'],participant_limit:{other:200,total:maximumDetail.participants.length,forged_201:forgedMembers.status},ingestion_account_switch:['save','poll'],provider_calls:ai.attempts.length})+'\n');w.close();process.exit(0);
})().catch(error=>{process.stderr.write(error.stack+'\n');w.close();process.exit(1);});
