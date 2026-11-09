'use strict';
// Detail feedback shares the maintenance Agent and its durable results.
const maintenanceFeedbackDrafts=new Map();
const maintenanceActionRequests=new Map();
const feedbackStates={queued:'等待处理',running:'正在查证',paused:'已暂停',completed:'已完成',failed:'处理失败',cancelled:'已由新反馈接续'};
function feedbackKey(kind,id){return state.me.id+':'+kind+':'+id;}
function maintenanceActionHtml(kind,obj){
  if(!state.me||state.schema<29)return '';
  if(kind==='record'&&(isResearchContent(obj.kind)||obj.visibility!=='shared'||obj.evidence_record_id))return '';
  const request=maintenanceActionRequests.get(feedbackKey(kind,obj.id));
  return `<span class="maintenance-action" data-maintenance-action data-kind="${kind}" data-id="${esc(obj.id)}" data-actor="${esc(state.me.id)}"><button type="button" class="button tiny" data-maintenance-start ${request?.busy?'disabled':''}>${kind==='record'?'AI整理关联':'AI补全'}</button><span role="status" data-maintenance-action-status>${esc(request?.status||'')}</span><span class="form-error" role="alert">${esc(request?.error||'')}</span></span>`;
}
function maintenanceActionActive(root,actor,kind,id){return root.isConnected&&state.me?.id===actor&&root.dataset.actor===actor&&root.dataset.kind===kind&&root.dataset.id===id;}
function maintenanceActionPaint(root,request){
  root.querySelector('[data-maintenance-start]').disabled=!!request.busy;
  root.querySelector('[data-maintenance-action-status]').textContent=request.status||'';
  root.querySelector('.form-error').textContent=request.error||'';
}
function feedbackValue(value){
  if(value==null||value==='')return '未填写';
  if(value&&typeof value==='object'&&Array.isArray(value.items))return value.items.map(item=>{
    const target=item.target||item.institution;
    const link=target?maintenanceObjectLink(target.type==='person'?'person':'source',target.id,target.name):'未关联';
    return [esc(item.raw_name||''),link,esc(item.role||''),esc([item.start_date,item.end_date].filter(Boolean).join('—'))].filter(Boolean).join(' · ');
  }).join('<br>')||'未关联';
  if(typeof value==='string'){
    const text=document.createElement('div');text.innerHTML=readRich(value);
    return esc(text.textContent||'未填写');
  }
  return esc(JSON.stringify(value));
}
function feedbackVisibleChange(field,change){
  if(field==='version')return false;
  if(['bylines','affiliations','employments'].includes(field)){
    const signature=value=>JSON.stringify((value?.items||[]).map(item=>[item.id,item.raw_name,item.target_id,item.institution_id,item.role,item.start_date,item.end_date]));
    return signature(change.before)!==signature(change.after);
  }
  return true;
}
function feedbackHistoryHtml(jobs){
  if(!jobs.length)return '<p class="muted">暂无处理记录</p>';
  const fields={keywords:'标签',introduction_html:'简介',bylines:'作者归属',affiliations:'署名单位',countries:'研究对象国',name:'姓名',original_name:'原名',chinese_name:'中文名',aliases:'其他名称',employments:'任职',abstract:'摘要',title:'题名',original_title:'原题名',orcid:'ORCID',doi:'DOI',issn:'ISSN',sources:'简介出处',country:'国家',location:'所在地',research_scope:'研究范围',website:'网站',serial_id:'所属刊物',source_id:'发布机构'};
  return jobs.map(job=>`<details class="feedback-job"><summary>${esc(feedbackStates[job.status]||job.status)} · ${dateTime(job.created_at)}</summary>${job.feedback?`<p>${esc(job.feedback)}</p>`:''}${job.reason?`<p>${esc(job.reason)}</p>`:''}${job.steps.filter(s=>s.result.changes).map(s=>`<dl>${Object.entries(s.result.changes).filter(([field,change])=>feedbackVisibleChange(field,change)).map(([field,change])=>`<dt>${esc(fields[field]||'档案信息')}</dt><dd><span>原值：${feedbackValue(change.before)}</span><span>新值：${feedbackValue(change.after)}</span></dd>`).join('')}</dl>`).join('')}${job.evidence.length?`<details><summary>查看出处</summary>${job.evidence.map(e=>`<p>${externalLink(e.url,e.url)} · ${dateTime(e.fetched_at)}</p>`).join('')}</details>`:''}</details>`).join('');
}
function feedbackStatus(job){return job?(job.status==='completed'&&job.reason?job.reason:feedbackStates[job.status]||job.status):'';}
async function maintenanceFeedbackHtml(kind,obj){
  if(!state.me||state.schema<29)return '';
  if(kind==='record'&&(isResearchContent(obj.kind)||obj.visibility!=='shared'||obj.evidence_record_id))return '';
  if(kind==='source'&&!isInstitution(obj)&&!isPublication(obj))return '';
  const actor=state.me.id,key=feedbackKey(kind,obj.id),draft=maintenanceFeedbackDrafts.get(key)||{text:'',request:''};
  let jobs=[],failure='';
  try{jobs=(await api('/api/maintenance/targets/'+kind+'/'+encodeURIComponent(obj.id))).items;}catch(error){failure=error.message;}
  if(state.me?.id!==actor)return '';
  return `<details class="maintenance-feedback" data-feedback-kind="${kind}" data-feedback-id="${esc(obj.id)}" data-feedback-actor="${esc(state.me.id)}"><summary>指出问题 <span data-feedback-brief>${esc(jobs[0]?feedbackStates[jobs[0].status]:'')}</span></summary><form data-maintenance-feedback><label class="field">问题说明<textarea name="feedback" rows="2" maxlength="4000" required placeholder="例如：这篇文章关联到了同名的另一位作者">${esc(draft.text)}</textarea></label><div class="row wrap"><button class="button primary" type="submit">提交问题</button><button class="button" type="button" data-feedback-refresh>刷新结果</button></div><p role="status" data-feedback-status>${esc(feedbackStatus(jobs[0]))}</p><p class="form-error" role="alert">${esc(failure)}</p></form><details class="feedback-history"><summary>处理记录与出处</summary><div data-feedback-history>${feedbackHistoryHtml(jobs)}</div></details></details>`;
}
async function refreshMaintenanceFeedback(panel){
  const actor=panel.dataset.feedbackActor,turn=(panel._feedbackTurn||0)+1;panel._feedbackTurn=turn;
  const result=await api('/api/maintenance/targets/'+panel.dataset.feedbackKind+'/'+encodeURIComponent(panel.dataset.feedbackId));
  if(!panel.isConnected||state.me?.id!==actor||panel._feedbackTurn!==turn)return;
  panel.querySelector('[data-feedback-brief]').textContent=result.items[0]?feedbackStates[result.items[0].status]:'';
  panel.querySelector('[data-feedback-status]').textContent=feedbackStatus(result.items[0]);
  panel.querySelector('[data-feedback-history]').innerHTML=feedbackHistoryHtml(result.items);
}
document.addEventListener('input',event=>{
  if(!event.target.matches('[data-maintenance-feedback] textarea'))return;
  const panel=event.target.closest('.maintenance-feedback');
  maintenanceFeedbackDrafts.set(feedbackKey(panel.dataset.feedbackKind,panel.dataset.feedbackId),{text:event.target.value,request:''});
});
document.addEventListener('submit',async event=>{
  const form=event.target.closest('[data-maintenance-feedback]');if(!form)return;
  event.preventDefault();if(form.dataset.busy)return;
  const panel=form.closest('.maintenance-feedback'),actor=panel.dataset.feedbackActor;
  if(state.me?.id!==actor)return;
  const key=feedbackKey(panel.dataset.feedbackKind,panel.dataset.feedbackId),input=form.elements.feedback,text=input.value.trim();
  if(!text){input.setCustomValidity('请写下需要改正的问题。');input.reportValidity();input.setCustomValidity('');return;}
  const draft=maintenanceFeedbackDrafts.get(key)||{text,request:''};
  if(!draft.request)draft.request=crypto.randomUUID();maintenanceFeedbackDrafts.set(key,draft);
  const button=form.querySelector('[type=submit]'),error=form.querySelector('.form-error');
  form.dataset.busy='1';button.disabled=true;input.readOnly=true;error.textContent='';
  form.querySelector('[data-feedback-status]').textContent='正在提交…';
  try{
    await api('/api/maintenance/jobs',{method:'POST',body:{target_type:panel.dataset.feedbackKind,target_id:panel.dataset.feedbackId,request_id:draft.request,feedback:text}});
    if(!panel.isConnected||state.me?.id!==actor)return;
    panel._feedbackTurn=(panel._feedbackTurn||0)+1;
    input.value='';maintenanceFeedbackDrafts.delete(key);
    form.querySelector('[data-feedback-status]').textContent='已提交，等待查证。';
    panel.querySelector('[data-feedback-brief]').textContent='等待处理';
    try{await refreshMaintenanceFeedback(panel);}catch(failure){if(panel.isConnected&&state.me?.id===actor)error.textContent='问题已提交，暂时无法读取结果；请刷新结果。';}
  }catch(failure){if(panel.isConnected&&state.me?.id===actor){error.textContent=failure.message;form.querySelector('[data-feedback-status]').textContent='提交失败，问题说明已保留。';}}
  finally{delete form.dataset.busy;if(form.isConnected){button.disabled=false;input.readOnly=false;}}
});
document.addEventListener('click',async event=>{
  const start=event.target.closest('[data-maintenance-start]');
  if(start){
    const root=start.closest('[data-maintenance-action]'),{actor,kind,id}=root.dataset;
    if(!maintenanceActionActive(root,actor,kind,id))return;
    const key=feedbackKey(kind,id),request=maintenanceActionRequests.get(key)||{id:crypto.randomUUID()};
    if(request.busy)return;
    request.busy=true;request.status='正在安排…';request.error='';maintenanceActionRequests.set(key,request);maintenanceActionPaint(root,request);
    try{
      await api('/api/maintenance/jobs',{method:'POST',body:{target_type:kind,target_id:id,request_id:request.id}});
      request.id=crypto.randomUUID();request.status='已安排，等待处理。';
      if(!maintenanceActionActive(root,actor,kind,id))return;
      const panel=[...document.querySelectorAll('.maintenance-feedback')].find(p=>p.dataset.feedbackActor===actor&&p.dataset.feedbackKind===kind&&p.dataset.feedbackId===id);
      if(panel){panel._feedbackTurn=(panel._feedbackTurn||0)+1;panel.querySelector('[data-feedback-brief]').textContent='等待处理';try{await refreshMaintenanceFeedback(panel);}catch(failure){if(maintenanceActionActive(root,actor,kind,id))request.error='已安排，暂时无法读取结果；可刷新结果。';}}
    }catch(failure){request.status='安排失败，可重试。';request.error=failure.message;}
    finally{request.busy=false;if(maintenanceActionActive(root,actor,kind,id))maintenanceActionPaint(root,request);else document.querySelectorAll('[data-maintenance-action]').forEach(current=>{if(maintenanceActionActive(current,actor,kind,id))maintenanceActionPaint(current,request);});}
    return;
  }
  const button=event.target.closest('[data-feedback-refresh]');if(!button)return;
  const panel=button.closest('.maintenance-feedback'),error=panel.querySelector('.form-error');button.disabled=true;error.textContent='';
  try{await refreshMaintenanceFeedback(panel);}catch(failure){if(panel.isConnected)error.textContent=failure.message;}
  finally{if(button.isConnected)button.disabled=false;}
});
