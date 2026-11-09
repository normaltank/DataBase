'use strict';
let maintenanceAgentState=null;
const maintenanceStatuses={queued:'等待处理',running:'正在整理',paused:'已暂停',completed:'已完成',failed:'未完成',cancelled:'已取消'};
const maintenanceTools={find:'查找已有档案',read:'读取当前内容',search:'搜索公开资料',fetch:'读取公开网页',save_profile:'保存档案',save_record:'整理文章',set_bylines:'关联作者',set_affiliations:'整理署名单位',set_employments:'整理任职',finish:'检查结果'};
function maintenanceObjectLink(kind,id,label){
  if(kind==='record')return linkButton(esc(label||id),'detail',id,'link-button');
  const url=kind==='person'?'#people?id=':'#sources?id=';
  return `<a href="${url}${encodeURIComponent(id)}">${esc(label||id)}</a>`;
}
function maintenanceJobHtml(job){
  return `<details class="maintenance-job" data-job="${esc(job.id)}"><summary><strong>${esc(maintenanceStatuses[job.status]||job.status)}</strong> · ${esc(job.title||job.target_id)} · ${dateTime(job.created_at)}</summary><p>${maintenanceObjectLink(job.target_type,job.target_id,'打开资料与档案')}</p>${job.reason?`<p role="status">${esc(job.reason)}</p>`:''}${['paused','failed'].includes(job.status)?`<button class="button" data-maintenance-resume="${esc(job.id)}">继续处理</button>`:''}<ol class="maintenance-steps">${job.steps.map(step=>`<li><strong>${esc(maintenanceTools[step.name]||step.name)}</strong> · ${step.status==='pending'?'等待执行':step.result.error?'需要调整':'已执行'}${step.result.error?`<p>${esc(step.result.error)}</p>`:''}${step.result.changed_target?`<p>${maintenanceObjectLink(...step.result.changed_target,step.result.object.name||step.result.object.title)} · 版本 ${step.result.object.version}</p><details><summary>查看改动</summary><pre>${esc(JSON.stringify(step.result.changes,null,2))}</pre></details>`:''}${step.arguments.query?`<p>${esc(step.arguments.query)}</p>`:''}${step.arguments.url?`<p>${externalLink(step.arguments.url,'查看页面')}</p>`:''}${step.arguments.quote?`<blockquote>${esc(step.arguments.quote)}</blockquote>`:''}</li>`).join('')}</ol>${job.evidence.length?`<details><summary>实际取得的材料（${job.evidence.length}）</summary>${job.evidence.map(e=>`<article><h3>${externalLink(e.url,e.method==='deepseek-fetch-markdown'?'网页内容':'搜索结果')}</h3><p>${dateTime(e.fetched_at)}</p><p class="prose">${esc(e.text)}</p></article>`).join('')}</details>`:''}</details>`;
}
function maintenanceJobsPaint(view){
  if(view!==maintenanceAgentState||state.me?.id!==view.actor||state.page!=='maintenance-agent')return;
  const root=document.querySelector('[data-maintenance-jobs]');if(!root)return;
  const open=new Set([...root.querySelectorAll('details[data-job][open]')].map(x=>x.dataset.job));
  const heartbeat=document.querySelector('[data-maintenance-heartbeat]');if(heartbeat)heartbeat.textContent=view.heartbeat?'后台最近运行：'+dateTime(view.heartbeat):'等待后台运行';
  root.innerHTML=view.jobs.map(maintenanceJobHtml).join('')||'<p class="muted">尚无维护任务。选择一篇文章开始整理。</p>';
  root.querySelectorAll('[data-job]').forEach(x=>{if(open.has(x.dataset.job))x.open=true;});
}
async function maintenanceAgentView(){
  const actor=state.me.id,view={actor,jobs:[],requestId:crypto.randomUUID(),recordId:'',busy:false};maintenanceAgentState=view;
  const data=await api('/api/maintenance/jobs');if(view!==maintenanceAgentState||state.me?.id!==actor)return '';
  view.jobs=data.items;view.heartbeat=data.heartbeat;
  return `<section class="system-card maintenance-agent" aria-labelledby="maintenance-agent-heading"><div class="between wrap"><h2 id="maintenance-agent-heading">整理一篇文章</h2><button class="button" data-maintenance-refresh>刷新状态</button></div><form data-form="maintenance-find"><label for="maintenance-query">查找文章</label><div class="row wrap"><input id="maintenance-query" name="q" type="search" maxlength="200" placeholder="题名、作者或 DOI"><button class="button" type="submit">查找</button></div></form><form data-form="maintenance-submit"><label for="maintenance-record">选择文章</label><select id="maintenance-record" name="record_id" required><option value="">先查找文章</option></select><button class="button primary" type="submit">开始整理</button><p data-maintenance-message role="status"></p><div class="form-error" role="alert"></div></form><section class="section-gap"><h2>最近任务</h2><p class="small muted" data-maintenance-heartbeat>${data.heartbeat?'后台最近运行：'+dateTime(data.heartbeat):'等待后台运行'}</p><div data-maintenance-jobs>${data.items.map(maintenanceJobHtml).join('')||'<p class="muted">尚无维护任务。选择一篇文章开始整理。</p>'}</div></section></section>`;
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
    const result=await api('/api/maintenance/jobs');if(!current())return;
    view.jobs=result.items;view.heartbeat=result.heartbeat;maintenanceJobsPaint(view);
  }catch(failure){if(current())document.querySelector('[data-form="maintenance-submit"] .form-error').textContent=failure.message;}
  finally{view.busy=false;if(current())button.disabled=false;}
});
