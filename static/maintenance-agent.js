'use strict';
let maintenanceAgentState=null;
const maintenanceStatuses={queued:'等待处理',running:'正在整理',paused:'已暂停',completed:'已完成',failed:'未完成',cancelled:'已取消'};
const maintenanceTools={find:'查找已有档案',read:'读取当前内容',read_field:'读取档案片段',read_evidence:'查阅已存材料',read_feedback:'查看问题说明',search:'搜索公开资料',fetch:'读取公开网页',save_profile:'保存档案',save_record:'整理文章',set_bylines:'关联作者',set_affiliations:'整理署名单位',set_employments:'整理任职',finish:'检查结果'};
const maintenanceRunStates={running:'运行中',waiting:'等待后台',paused:'已暂停',needs_configuration:'缺少配置'};
function maintenanceSearchLinks(results){
  return Array.isArray(results)&&results.length?`<ul>${results.filter(item=>item&&item.url).map(item=>`<li>${externalLink(item.url,item.title||item.url)}</li>`).join('')}</ul>`:'';
}
function maintenanceObjectLink(kind,id,label){
  if(kind==='record')return linkButton(esc(label||id),'detail',id,'link-button');
  const url=kind==='person'?'#people?id=':'#sources?id=';
  return `<a href="${url}${encodeURIComponent(id)}">${esc(label||id)}</a>`;
}
function maintenanceViewActive(view){return !!view&&view===maintenanceAgentState&&state.me?.id===view.actor&&state.page==='maintenance-agent'&&state.loadId===view.pageTurn;}
function maintenanceStop(view){
  if(!view)return;clearTimeout(view.timer);view.controller?.abort();view.detailController?.abort();view.detail=null;view.jobs=[];
  if(maintenanceAgentState===view)maintenanceAgentState=null;
}
function maintenanceJobRow(job,view){
  return `<button type="button" class="maintenance-job-row" data-key="job-${esc(job.id)}" data-maintenance-select="${esc(job.id)}" aria-pressed="${job.id===view.selected}"><strong>${esc(job.title||job.target_id)}</strong><span>${esc(maintenanceStatuses[job.status]||job.status)} · ${job.step_count} 步</span><span class="muted">${dateTime(job.created_at)}</span>${job.reason?`<span>${esc(job.reason)}</span>`:''}${job.last_step?`<span class="muted">末步：${esc(maintenanceTools[job.last_step.name]||job.last_step.name)} · ${job.last_step.status==='pending'?'等待执行':'已记录'}</span>`:''}</button>`;
}
function maintenanceJobsPaint(view){
  if(!maintenanceViewActive(view)||!view.root?.isConnected)return;
  const root=view.root;
  const info=view.overview;
  maintenancePatch(root.querySelector('[data-maintenance-running]'),`<strong>${esc(maintenanceRunStates[info.status]||info.status)}</strong><span>${esc(info.reason)}</span>${state.me.role==='admin'?'<a href="#maintenance-ai">配置、暂停与费用</a>':''}`);
  const jobs=view.jobs.filter(job=>!view.filter||job.status===view.filter);
  maintenancePatch(root.querySelector('[data-maintenance-jobs]'),jobs.map(job=>maintenanceJobRow(job,view)).join('')||'<p class="muted">当前近期窗口中没有符合此状态的任务。</p>');
  root.querySelector('[data-maintenance-window]').textContent=`有权近期窗口：已加载 ${view.window.loaded} / 上限 ${view.window.limit} 项；${view.window.has_more?'还有更早的有权任务':'已覆盖当前有权任务'}。筛选仅作用于此窗口。`;
  root.querySelector('[data-maintenance-range]').textContent=view.window.loaded?`${dateTime(view.window.oldest_at)} — ${dateTime(view.window.newest_at)}`:'尚无有权任务';
  root.querySelector('[data-maintenance-heartbeat]').textContent=view.heartbeat?'后台最近运行：'+dateTime(view.heartbeat):'等待后台运行';
  const selected=view.jobs.find(job=>job.id===view.selected);
  root.querySelector('[data-maintenance-selection-note]').textContent=view.selected&&!selected?'所选任务暂不在近期窗口中；详情每次刷新仍重新检查权限。':'';
  maintenancePatch(root.querySelector('[data-maintenance-recent]'),info.recent_changes.length?`<ul class="maintenance-changes">${info.recent_changes.map(item=>`<li data-key="recent-${esc(item.target_type)}-${esc(item.target_id)}"><div>${maintenanceObjectLink(item.target_type,item.target_id,item.title)}<p class="muted">${item.actions.map(action=>esc(maintenanceTools[action]||action)).join(' · ')}</p></div><span>${dateTime(item.at)}</span></li>`).join('')}</ul>`:'<p class="muted">当前有权近期窗口尚无正式修改。</p>');
}
function maintenanceDetailPaint(view,job){
  if(!maintenanceViewActive(view)||!view.root?.isConnected||view.selected!==job.id)return;
  const target=view.root.querySelector('[data-maintenance-detail]');
  if(target.dataset.loadedJob!==job.id){target.innerHTML=`<div class="maintenance-current-object">${maintenanceObjectLink(job.target_type,job.target_id,'打开当前资料与档案')}<span class="muted">处理轨迹保留当时记录</span><button class="button" type="button" data-maintenance-resume="${esc(job.id)}" hidden>继续处理</button></div><div class="maintenance-trace" data-maintenance-trace data-trace-job="${esc(job.id)}"></div>`;target.dataset.loadedJob=job.id;}
  target.querySelector('[data-maintenance-resume]').hidden=!['paused','failed'].includes(job.status);
  maintenanceTraceUpdate(target.querySelector('[data-maintenance-trace]'),job);
  view.detail=job;
}
async function maintenanceAgentView(){
  maintenanceStop(maintenanceAgentState);
  const view={actor:state.me.id,pageTurn:state.loadId,jobs:[],selected:'',selectionTurn:0,filter:'',requestId:crypto.randomUUID(),recordId:'',busy:false,lastSuccess:''};maintenanceAgentState=view;
  const data=await api('/api/maintenance/jobs?view=summary');if(!maintenanceViewActive(view))return '';
  Object.assign(view,data);view.selected=data.items[0]?.id||'';view.jobs=data.items;view.lastSuccess=new Date().toISOString();
  return `<section class="system-card maintenance-agent" data-maintenance-view="${view.pageTurn}" aria-labelledby="maintenance-agent-heading"><div class="between wrap"><h2 id="maintenance-agent-heading">维护状态</h2><button class="button" data-maintenance-refresh>刷新状态</button></div><div class="maintenance-running" data-maintenance-running></div><p class="maintenance-read-status" data-maintenance-updated role="status">正在读取任务详情…</p><p class="form-error" data-maintenance-error role="alert"></p><section class="maintenance-workspace"><div class="maintenance-job-list"><h3>近期任务</h3><label for="maintenance-state-filter">当前窗口状态</label><select id="maintenance-state-filter" data-maintenance-filter><option value="">全部状态</option>${Object.entries(maintenanceStatuses).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select><p class="muted" data-maintenance-window></p><p class="muted" data-maintenance-range></p><div data-maintenance-jobs></div></div><div class="maintenance-selected"><p class="muted" data-maintenance-selection-note></p><div data-maintenance-detail><p class="muted">${view.selected?'正在读取所选任务…':'选择任务后查看真实步骤、材料和修改前后。'}</p></div></div></section><details class="maintenance-secondary"><summary>近期修改与后台时间</summary><p class="muted">以下修改来自当前有权近期任务窗口。</p><p class="muted" data-maintenance-heartbeat></p><div data-maintenance-recent></div></details><details class="maintenance-single"><summary>指定一篇文章</summary><form data-form="maintenance-find"><label for="maintenance-query">查找文章</label><div class="row wrap"><input id="maintenance-query" name="q" type="search" maxlength="200" placeholder="题名、作者或 DOI"><button class="button" type="submit">查找</button></div></form><form data-form="maintenance-submit"><label for="maintenance-record">选择文章</label><select id="maintenance-record" name="record_id" required><option value="">先查找文章</option></select><button class="button primary" type="submit">开始整理</button><p data-maintenance-message role="status"></p><div class="form-error" role="alert"></div></form></details></section>`;
}
async function maintenanceReload(view,{summary=true}={}){
  if(!maintenanceViewActive(view))return;
  if(view.inFlight)return view.inFlight;
  view.inFlight=(async()=>{
    const error=view.root?.querySelector('[data-maintenance-error]');
    try{
      if(summary){
        view.controller=new AbortController();
        const result=await api('/api/maintenance/jobs?view=summary',{signal:view.controller.signal});
        if(!maintenanceViewActive(view))return;
        Object.assign(view,{jobs:result.items,window:result.window,heartbeat:result.heartbeat,overview:result.overview});maintenanceJobsPaint(view);
      }
      while(maintenanceViewActive(view)&&view.selected){
        const selected=view.selected,turn=view.selectionTurn;
        try{
          view.detailController=new AbortController();
          const job=await api('/api/maintenance/jobs/'+encodeURIComponent(selected),{signal:view.detailController.signal});
          if(!maintenanceViewActive(view))return;
          if(selected!==view.selected||turn!==view.selectionTurn)continue;
          maintenanceDetailPaint(view,job);break;
        }catch(failure){
          if(!maintenanceViewActive(view))return;
          if(selected!==view.selected||turn!==view.selectionTurn)continue;
          if([401,403,404].includes(failure.status)){view.detail=null;const detail=view.root.querySelector('[data-maintenance-detail]');delete detail.dataset.loadedJob;detail.replaceChildren();detail.textContent='此任务或所据材料已不可访问，已清除详情。';}
          throw failure;
        }
      }
      if(!maintenanceViewActive(view))return;
      view.lastSuccess=new Date().toISOString();if(error)error.textContent='';
      view.root.querySelector('[data-maintenance-updated]').textContent='最近成功更新：'+dateTime(view.lastSuccess);
    }catch(failure){
      if(!maintenanceViewActive(view)||failure.name==='AbortError')return;
      if([401,403].includes(failure.status)){view.detail=null;view.jobs=[];view.root.querySelector('[data-maintenance-detail]').replaceChildren();view.root.querySelector('[data-maintenance-jobs]').replaceChildren();}
      if(error)error.textContent=failure.message+'；状态未更新，可刷新状态重试。';
      view.root.querySelector('[data-maintenance-updated]').textContent='未更新；最后成功更新：'+dateTime(view.lastSuccess);
    }
  })();
  try{return await view.inFlight;}finally{view.inFlight=null;}
}
function maintenancePollSchedule(view){clearTimeout(view.timer);if(maintenanceViewActive(view))view.timer=setTimeout(async()=>{await maintenanceReload(view);maintenancePollSchedule(view);},5000);}
const maintenanceViewObserver=new MutationObserver(()=>{
  const view=maintenanceAgentState;if(!view)return;
  if(!maintenanceViewActive(view)||(view.root&&!view.root.isConnected)){maintenanceStop(view);return;}
  if(!view.root){view.root=document.querySelector('[data-maintenance-view="'+view.pageTurn+'"]');if(view.root){maintenanceJobsPaint(view);maintenanceReload(view,{summary:false}).finally(()=>maintenancePollSchedule(view));}}
});
maintenanceViewObserver.observe(document.documentElement,{childList:true,subtree:true});
document.addEventListener('change',event=>{
  if(!event.target.matches('[data-maintenance-filter]'))return;
  const view=maintenanceAgentState;if(!maintenanceViewActive(view))return;view.filter=event.target.value;maintenanceJobsPaint(view);
});
document.addEventListener('submit',async event=>{
  const form=event.target.closest('[data-form="maintenance-find"],[data-form="maintenance-submit"]');if(!form)return;
  event.preventDefault();const view=maintenanceAgentState;if(!view||view.busy)return;
  const current=()=>maintenanceViewActive(view),error=view.root.querySelector('[data-form="maintenance-submit"] .form-error');error.textContent='';
  const button=form.querySelector('[type=submit]');view.busy=true;button.disabled=true;
  try{
    if(form.dataset.form==='maintenance-find'){
      const result=await api('/api/records?purpose=original&size=50&q='+encodeURIComponent(form.elements.q.value));if(!current())return;
      const select=view.root.querySelector('#maintenance-record'),items=result.items.filter(x=>!isResearchContent(x.kind)&&x.visibility==='shared');
      select.innerHTML='<option value="">'+(items.length?'选择要整理的文章':'未找到公共外部文章')+'</option>'+items.map(x=>`<option value="${esc(x.id)}">${esc(x.title)}${x.authors?' · '+esc(x.authors):''}</option>`).join('');select.focus();
    }else{
      const id=form.elements.record_id.value;if(id!==view.recordId){view.recordId=id;view.requestId=crypto.randomUUID();}
      const result=await api('/api/maintenance/jobs',{method:'POST',body:{target_type:'record',target_id:id,request_id:view.requestId}});if(!current())return;
      form.querySelector('[data-maintenance-message]').textContent='已安排，后台将继续整理。';
      view.selected=result.id;view.selectionTurn++;view.detailController?.abort();await maintenanceReload(view);
    }
  }catch(failure){if(current())error.textContent=failure.message+'；输入已保留，可重试。';}
  finally{view.busy=false;if(current())button.disabled=false;}
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-maintenance-select],[data-maintenance-refresh],[data-maintenance-resume]');if(!button)return;
  const view=maintenanceAgentState;if(!view||!maintenanceViewActive(view))return;
  if(button.dataset.maintenanceSelect){
    if(view.selected===button.dataset.maintenanceSelect)return;
    view.selected=button.dataset.maintenanceSelect;view.selectionTurn++;view.detail=null;view.detailController?.abort();
    const detail=view.root.querySelector('[data-maintenance-detail]');delete detail.dataset.loadedJob;detail.textContent='正在读取所选任务…';maintenanceJobsPaint(view);
    await maintenanceReload(view,{summary:false});return;
  }
  if(view.busy)return;button.disabled=true;
  try{
    if(button.dataset.maintenanceResume)await api('/api/maintenance/jobs/'+encodeURIComponent(button.dataset.maintenanceResume)+'/resume',{method:'POST',body:{}});
    if(maintenanceViewActive(view))await maintenanceReload(view);
  }catch(failure){if(maintenanceViewActive(view))view.root.querySelector('[data-maintenance-error]').textContent=failure.message;}
  finally{if(button.isConnected)button.disabled=false;}
});
