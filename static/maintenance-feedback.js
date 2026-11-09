'use strict';
// Detail feedback shares the maintenance Agent and its durable results.
const maintenanceFeedbackDrafts=new Map();
const maintenanceActionRequests=new Map();
const feedbackStates={queued:'等待处理',running:'正在查证',paused:'已暂停',completed:'已完成',failed:'处理失败',cancelled:'已取消'};
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
function feedbackHistoryHtml(jobs){
  if(!jobs.length)return '<p class="muted">暂无处理记录</p>';
  return jobs.map(job=>`<details class="feedback-job" data-key="feedback-job-${esc(job.id)}"><summary>${esc(feedbackStates[job.status]||job.status)} · ${dateTime(job.created_at)}</summary>${maintenanceTraceHtml(job)}</details>`).join('');
}
function feedbackStatus(job){return job?(job.status==='completed'&&job.reason?job.reason:feedbackStates[job.status]||job.status):'';}
async function maintenanceFeedbackHtml(kind,obj){
  if(!state.me||state.schema<29)return '';
  if(kind==='record'&&(isResearchContent(obj.kind)||obj.visibility!=='shared'||obj.evidence_record_id))return '';
  if(kind==='source'&&!isInstitution(obj)&&!isPublication(obj))return '';
  const actor=state.me.id,pageTurn=state.loadId,key=feedbackKey(kind,obj.id),draft=maintenanceFeedbackDrafts.get(key)||{text:'',request:''};
  let jobs=[],failure='';
  try{jobs=(await api('/api/maintenance/targets/'+kind+'/'+encodeURIComponent(obj.id))).items;}catch(error){failure=error.message;}
  if(state.me?.id!==actor||state.loadId!==pageTurn)return '';
  return `<details class="maintenance-feedback" data-feedback-kind="${kind}" data-feedback-id="${esc(obj.id)}" data-feedback-actor="${esc(state.me.id)}"><summary>指出问题 <span data-feedback-brief>${esc(jobs[0]?feedbackStates[jobs[0].status]:'')}</span></summary><form data-maintenance-feedback><label class="field">问题说明<textarea name="feedback" rows="2" maxlength="4000" required placeholder="例如：这篇文章关联到了同名的另一位作者">${esc(draft.text)}</textarea></label><div class="row wrap"><button class="button primary" type="submit">提交问题</button><button class="button" type="button" data-feedback-refresh>刷新结果</button></div><p role="status" data-feedback-status>${esc(feedbackStatus(jobs[0]))}</p><p class="form-error" role="alert">${esc(failure)}</p></form><details class="feedback-history"><summary>处理记录与出处</summary><div data-feedback-history>${feedbackHistoryHtml(jobs)}</div></details></details>`;
}
async function refreshMaintenanceFeedback(panel){
  if(panel._feedbackFlight)return panel._feedbackFlight;
  panel._feedbackFlight=readMaintenanceFeedback(panel);
  try{return await panel._feedbackFlight;}finally{panel._feedbackFlight=null;}
}
async function readMaintenanceFeedback(panel){
  const actor=panel.dataset.feedbackActor,turn=(panel._feedbackTurn||0)+1;panel._feedbackTurn=turn;
  let result;
  try{result=await api('/api/maintenance/targets/'+panel.dataset.feedbackKind+'/'+encodeURIComponent(panel.dataset.feedbackId));}
  catch(failure){
    if(panel.isConnected&&state.me?.id===actor&&panel._feedbackTurn===turn){
      if([401,403,404].includes(failure.status)){panel.querySelector('[data-feedback-history]').replaceChildren();panel.querySelector('[data-feedback-status]').textContent='对象或所据材料已不可访问，已清除处理详情。';}
      panel.querySelector('.form-error').textContent=failure.message+'；处理记录未更新，可刷新结果。'+(panel._feedbackSuccess?' 最后成功更新：'+dateTime(panel._feedbackSuccess):'');
    }
    throw failure;
  }
  if(!panel.isConnected||state.me?.id!==actor||panel._feedbackTurn!==turn)return;
  panel.querySelector('[data-feedback-brief]').textContent=result.items[0]?feedbackStates[result.items[0].status]:'';
  panel.querySelector('[data-feedback-status]').textContent=feedbackStatus(result.items[0]);
  maintenancePatch(panel.querySelector('[data-feedback-history]'),feedbackHistoryHtml(result.items));
  panel._feedbackSuccess=new Date().toISOString();panel.querySelector('.form-error').textContent='';
}
let maintenanceFeedbackActor='';
const maintenanceFeedbackPanels=new Set();
function maintenanceFeedbackSchedule(panel){
  clearTimeout(panel._feedbackTimer);
  if(!panel.isConnected||state.me?.id!==panel.dataset.feedbackActor)return;
  panel._feedbackTimer=setTimeout(async()=>{
    if(panel.isConnected&&panel.open&&state.me?.id===panel.dataset.feedbackActor)try{await refreshMaintenanceFeedback(panel);}catch(failure){/* The panel retains its own readable failure state. */}
    maintenanceFeedbackSchedule(panel);
  },5000);
}
const maintenanceFeedbackObserver=new MutationObserver(()=>{
  const actor=state.me?.id||'';
  if(actor!==maintenanceFeedbackActor){maintenanceFeedbackDrafts.clear();maintenanceActionRequests.clear();maintenanceFeedbackActor=actor;}
  for(const panel of maintenanceFeedbackPanels)if(!panel.isConnected||panel.dataset.feedbackActor!==actor){clearTimeout(panel._feedbackTimer);panel._feedbackTurn=(panel._feedbackTurn||0)+1;maintenanceFeedbackPanels.delete(panel);}
  document.querySelectorAll('.maintenance-feedback').forEach(panel=>{if(!maintenanceFeedbackPanels.has(panel)){maintenanceFeedbackPanels.add(panel);maintenanceFeedbackSchedule(panel);}});
});
maintenanceFeedbackObserver.observe(document.documentElement,{childList:true,subtree:true});
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
