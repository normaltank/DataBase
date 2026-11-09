'use strict';
let maintenanceAgentState=null;
const maintenanceStatuses={queued:'等待处理',running:'正在整理',paused:'已暂停',completed:'已完成',failed:'未完成',cancelled:'已取消'};
const maintenanceTools={find:'查找已有档案',read:'读取当前内容',search:'搜索公开资料',fetch:'读取公开网页',save_profile:'保存档案',save_record:'整理文章',set_bylines:'关联作者',set_affiliations:'整理署名单位',set_employments:'整理任职',finish:'检查结果'};
const maintenanceRunStates={running:'运行中',waiting:'等待后台',paused:'已暂停',needs_configuration:'缺少配置'};
function maintenanceOverviewHtml(data){
  const info=data.overview,counts=info.counts;
  const queue=['queued','running','paused','failed'].map(key=>`<li>${maintenanceStatuses[key]} ${counts[key]||0}</li>`).join('');
  return `<div class="maintenance-status" role="status"><strong>${esc(maintenanceRunStates[info.status]||info.status)}</strong><p>${esc(info.reason)}</p><ul class="maintenance-counts">${queue}</ul>${state.me.role==='admin'?'<a href="#maintenance-ai">配置、暂停与费用</a>':''}</div><section class="section-gap"><h3>近期修改</h3>${info.recent_changes.length?`<ul class="maintenance-changes">${info.recent_changes.map(item=>`<li><div>${maintenanceObjectLink(item.target_type,item.target_id,item.title)}<p class="small muted">${item.actions.map(action=>esc(maintenanceTools[action]||action)).join(' · ')}</p></div><span class="muted">${dateTime(item.at)}</span></li>`).join('')}</ul>`:'<p class="muted">尚无正式修改。</p>'}</section>`;
}
function maintenanceSearchLinks(results){
  return Array.isArray(results)&&results.length?`<ul>${results.filter(item=>item&&item.url).map(item=>`<li>${externalLink(item.url,item.title||item.url)}</li>`).join('')}</ul>`:'';
}
function maintenanceObjectLink(kind,id,label){
  if(kind==='record')return linkButton(esc(label||id),'detail',id,'link-button');
  const url=kind==='person'?'#people?id=':'#sources?id=';
  return `<a href="${url}${encodeURIComponent(id)}">${esc(label||id)}</a>`;
}
function maintenanceJobHtml(job){
  return `<details class="maintenance-job" data-job="${esc(job.id)}"><summary><strong>${esc(maintenanceStatuses[job.status]||job.status)}</strong> · ${esc(job.title||job.target_id)} · ${dateTime(job.created_at)}</summary><p>${maintenanceObjectLink(job.target_type,job.target_id,'打开资料与档案')}</p>${job.reason?`<p role="status">${esc(job.reason)}</p>`:''}${['paused','failed'].includes(job.status)?`<button class="button" data-maintenance-resume="${esc(job.id)}">继续处理</button>`:''}<ol class="maintenance-steps">${job.steps.map(step=>`<li><strong>${esc(maintenanceTools[step.name]||step.name)}</strong> · ${step.status==='pending'?'等待执行':step.result.error?'需要调整':'已执行'}${step.result.error?`<p>${esc(step.result.error)}</p>`:''}${step.result.changed_target?`<p>${maintenanceObjectLink(...step.result.changed_target,step.result.object.name||step.result.object.title)} · 版本 ${step.result.object.version}</p><details><summary>查看改动</summary><pre>${esc(JSON.stringify(step.result.changes,null,2))}</pre></details>`:''}${step.name==='search'?maintenanceSearchLinks(step.result.results):''}${step.arguments.query?`<p>${esc(step.arguments.query)}</p>`:''}${step.arguments.url?`<p>${externalLink(step.arguments.url,'查看页面')}</p>`:''}${step.arguments.quote?`<blockquote>${esc(step.arguments.quote)}</blockquote>`:''}</li>`).join('')}</ol>${job.evidence.length?`<details><summary>实际取得的材料（${job.evidence.length}）</summary>${job.evidence.map(e=>`<article><h3>${e.method==='deepseek-fetch-markdown'?externalLink(e.url,'网页内容'):'搜索结果'}</h3><p>${dateTime(e.fetched_at)}</p>${e.method==='deepseek-search-json'?maintenanceSearchLinks(job.steps.find(step=>step.result.evidence_id===e.id)?.result.results):''}<p class="prose">${esc(e.text)}</p></article>`).join('')}</details>`:''}</details>`;
}
function maintenanceJobsPaint(view){
  if(view!==maintenanceAgentState||state.me?.id!==view.actor||state.page!=='maintenance-agent')return;
  const root=document.querySelector('[data-maintenance-jobs]');if(!root)return;
  const open=new Set([...root.querySelectorAll('details[data-job][open]')].map(x=>x.dataset.job));
  const heartbeat=document.querySelector('[data-maintenance-heartbeat]');if(heartbeat)heartbeat.textContent=view.heartbeat?'后台最近运行：'+dateTime(view.heartbeat):'等待后台运行';
  const overview=document.querySelector('[data-maintenance-overview]');if(overview)overview.innerHTML=maintenanceOverviewHtml(view);
  root.innerHTML=view.jobs.map(maintenanceJobHtml).join('')||'<p class="muted">后台将在启用后逐批整理公开资料与档案。</p>';
  root.querySelectorAll('[data-job]').forEach(x=>{if(open.has(x.dataset.job))x.open=true;});
}
async function maintenanceAgentView(){
  const actor=state.me.id,view={actor,jobs:[],requestId:crypto.randomUUID(),recordId:'',busy:false};maintenanceAgentState=view;
  const data=await api('/api/maintenance/jobs');if(view!==maintenanceAgentState||state.me?.id!==actor)return '';
  view.jobs=data.items;view.heartbeat=data.heartbeat;view.overview=data.overview;
  setTimeout(()=>maintenancePoll(view),5000);
  return `<section class="system-card maintenance-agent" aria-labelledby="maintenance-agent-heading"><div class="between wrap"><h2 id="maintenance-agent-heading">维护状态</h2><button class="button" data-maintenance-refresh>刷新状态</button></div><div data-maintenance-overview>${maintenanceOverviewHtml(view)}</div><details class="maintenance-single"><summary>指定一篇文章</summary><form data-form="maintenance-find"><label for="maintenance-query">查找文章</label><div class="row wrap"><input id="maintenance-query" name="q" type="search" maxlength="200" placeholder="题名、作者或 DOI"><button class="button" type="submit">查找</button></div></form><form data-form="maintenance-submit"><label for="maintenance-record">选择文章</label><select id="maintenance-record" name="record_id" required><option value="">先查找文章</option></select><button class="button primary" type="submit">开始整理</button><p data-maintenance-message role="status"></p><div class="form-error" role="alert"></div></form></details><p class="form-error" data-maintenance-error role="alert"></p><section class="section-gap"><h3>近期任务</h3><p class="small muted" data-maintenance-heartbeat>${data.heartbeat?'后台最近运行：'+dateTime(data.heartbeat):'等待后台运行'}</p><div data-maintenance-jobs>${data.items.map(maintenanceJobHtml).join('')||'<p class="muted">后台将在启用后逐批整理公开资料与档案。</p>'}</div></section></section>`;
}
async function maintenancePoll(view){
  if(view!==maintenanceAgentState||state.me?.id!==view.actor||state.page!=='maintenance-agent')return;
  try{if(!view.busy)await maintenanceReload(view);}catch(failure){const error=document.querySelector('[data-maintenance-error]');if(error&&view===maintenanceAgentState)error.textContent='状态暂未更新，可点击刷新状态。';}
  if(view===maintenanceAgentState&&state.me?.id===view.actor&&state.page==='maintenance-agent')setTimeout(()=>maintenancePoll(view),5000);
}
async function maintenanceReload(view){
  const result=await api('/api/maintenance/jobs');
  if(view!==maintenanceAgentState||state.me?.id!==view.actor||state.page!=='maintenance-agent')return;
  view.jobs=result.items;view.heartbeat=result.heartbeat;view.overview=result.overview;maintenanceJobsPaint(view);
  const error=document.querySelector('[data-maintenance-error]');if(error)error.textContent='';
}
document.addEventListener('submit',async event=>{
  const form=event.target.closest('[data-form="maintenance-find"],[data-form="maintenance-submit"]');if(!form)return;
  event.preventDefault();const view=maintenanceAgentState;if(!view||view.busy)return;
  const current=()=>view===maintenanceAgentState&&state.me?.id===view.actor&&state.page==='maintenance-agent';
  const error=document.querySelector('[data-form="maintenance-submit"] .form-error');error.textContent='';
  const button=form.querySelector('[type=submit]');view.busy=true;button.disabled=true;
  try{
    if(form.dataset.form==='maintenance-find'){
      const result=await api('/api/records?purpose=original&size=50&q='+encodeURIComponent(form.elements.q.value));if(!current())return;
      const select=document.querySelector('#maintenance-record');
      const items=result.items.filter(x=>!isResearchContent(x.kind)&&x.visibility==='shared');
      select.innerHTML='<option value="">'+(items.length?'选择要整理的文章':'未找到公共外部文章')+'</option>'+items.map(x=>`<option value="${esc(x.id)}">${esc(x.title)}${x.authors?' · '+esc(x.authors):''}</option>`).join('');
      select.focus();
    }else{
      const id=form.elements.record_id.value;if(id!==view.recordId){view.recordId=id;view.requestId=crypto.randomUUID();}
      const result=await api('/api/maintenance/jobs',{method:'POST',body:{target_type:'record',target_id:id,request_id:view.requestId}});if(!current())return;
      form.querySelector('[data-maintenance-message]').textContent='已安排，后台将继续整理。';
      const job=await api('/api/maintenance/jobs/'+encodeURIComponent(result.id));if(!current())return;
      view.jobs=[job,...view.jobs.filter(x=>x.id!==job.id)];maintenanceJobsPaint(view);
      document.querySelector(`[data-job="${CSS.escape(job.id)}"]`).open=true;
    }
  }catch(failure){if(current())error.textContent=failure.message+'；输入已保留，可重试。';}
  finally{view.busy=false;if(current())button.disabled=false;}
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-maintenance-refresh],[data-maintenance-resume]');if(!button)return;
  const view=maintenanceAgentState;if(!view||view.busy)return;
  const current=()=>view===maintenanceAgentState&&state.me?.id===view.actor&&state.page==='maintenance-agent';
  view.busy=true;button.disabled=true;
  try{
    if(button.dataset.maintenanceResume)await api('/api/maintenance/jobs/'+encodeURIComponent(button.dataset.maintenanceResume)+'/resume',{method:'POST',body:{}});
    if(!current())return;
    await maintenanceReload(view);
  }catch(failure){if(current())document.querySelector('[data-maintenance-error]').textContent=failure.message;}
  finally{view.busy=false;if(current())button.disabled=false;}
});
