'use strict';
const archiveFieldNames={name:'显示名称',original_name:'原文名称',aliases:'其他名称',introduction:'来源介绍',institution_types:'机构类型',location:'所在地',country:'机构国家',research_scope:'研究覆盖范围',issn:'ISSN',website:'官方网站',catalogue_url:'资料入口',host:'主办机构',publisher:'出版机构',relationships:'机构关系',international_status:'国际办刊定位'};
const archiveStates={queued:'等待后台',running:'正在取得与整理',paused:'暂停待恢复',failed:'取得或处理失败',invalidated:'已失效',cancelled:'已取消',ready:'待核对建议',empty:'无新增有据建议',unmatched:'机构待匹配',pending:'待选择',adopted:'已采用',rejected:'已拒绝'};
function archiveValue(value,field){
  if(Array.isArray(value))return value.map(v=>typeof v==='string'?(institutionTypes[v]||v):JSON.stringify(v)).join(' / ')||'未登记';
  if(value&&typeof value==='object')return (value.type?(relationLabels[value.type]||value.type)+'：':'')+(value.target_name||JSON.stringify(value));
  if(['host','publisher'].includes(field)&&value)return value.split(' | ').map(id=>state.sources.find(s=>s.id===id)?.name||id).join(' / ');
  if(field==='international_status')return internationalLabels[value]||value||'未登记';
  return String(value||'未登记');
}
let archiveView=null,archiveTimer;
function archiveSnapshot(){
  const root=document.querySelector('[data-archive-review]');
  return {selected:new Set([...(root?.querySelectorAll('input[name=candidate]:checked')||[])].map(x=>x.value)),
    opened:new Set([...(root?.querySelectorAll('details[open]')||[])].map(x=>x.dataset.candidate||x.dataset.archiveHistory)),
    scroll:document.querySelector('#modal-root .drawer-body')?.scrollTop||0};
}
function archiveReviewHtml(data,saved){
  const pending=data.candidates.filter(c=>['pending','unmatched'].includes(c.status));
  const title=esc(data.name||state.sources.find(s=>s.id===data.target_id)?.name||'来源档案');
  return `<section data-archive-review data-id="${esc(data.target_id)}" data-version="${data.version}"><div class="between wrap"><h3>${title}</h3><button class="button tiny" data-archive-action="refresh">刷新</button></div><div class="archive-jobs">${data.jobs.slice(0,3).map(j=>`<div><strong>${esc(archiveStates[j.status]||j.status)}</strong>${j.reason?`<p role="status">${esc(j.reason)}</p>`:''}${['queued','running','paused'].includes(j.status)?`<button class="button tiny" data-archive-action="cancel" data-id="${esc(j.id)}">取消任务</button>`:''}</div>`).join('')||'<p>尚未排队。</p>'}</div><form data-form="archive-decide"><div class="archive-candidates">${pending.map(c=>archiveCandidate(c,saved)).join('')||'<p class="notice">当前没有待选择的有据建议。</p>'}</div><div class="form-error" role="alert"></div><div class="archive-actions"><button type="submit" class="button primary" name="decision" value="adopt" ${pending.length?'':'disabled'}>采用所选</button><button type="submit" class="button" name="decision" value="reject" ${pending.length?'':'disabled'}>拒绝所选</button></div></form><div class="row wrap section-gap"><button class="button" data-archive-action="queue">${data.jobs.length?'重新取得建议':'取得AI补全建议'}</button><a class="button" href="/api/sources/${encodeURIComponent(data.target_id)}/suggestions/export" download>导出建议与依据</a></div>${data.candidates.some(c=>!['pending','unmatched'].includes(c.status))?`<details class="section-gap" data-archive-history="history" ${saved.opened.has('history')?'open':''}><summary>已处理建议与采用来历</summary>${data.candidates.filter(c=>!['pending','unmatched'].includes(c.status)).map(c=>archiveCandidate(c,saved)).join('')}</details>`:''}<details class="section-gap" data-archive-history="events" ${saved.opened.has('events')?'open':''}><summary>处理历史</summary>${data.events.map(e=>`<p>${esc(archiveStates[e.action]||e.action)} · ${esc(e.actor_id)} · ${dateTime(e.created_at)}</p>`).join('')||'<p>尚无处理历史。</p>'}</details></section>`;
}
function archiveCandidate(c,saved){
  const selectable=['pending','unmatched'].includes(c.status);
  return `<article class="archive-candidate" data-candidate-row="${esc(c.id)}"><div class="between wrap"><label class="archive-choice">${selectable?`<input type="checkbox" name="candidate" value="${esc(c.id)}" ${saved.selected.has(c.id)?'checked':''}>`:''}<strong>${esc(archiveFieldNames[c.field]||c.field)}</strong></label>${c.status!=='pending'?'<span class="badge neutral">'+esc(archiveStates[c.status])+'</span>':''}</div><div class="archive-comparison"><div><span>原值</span><p>${esc(archiveValue(c.before,c.field))}</p></div><div><span>建议值</span><p>${esc(archiveValue(c.value,c.field))}</p></div></div>${c.status==='unmatched'?'<p class="notice">关联机构尚未唯一登记；保留依据，可先登记或核查机构后重新取得。</p>':''}${c.stale&&selectable?'<p class="notice">档案已有修订；建议保留，请对照当前档案后重新取得。</p>':''}<details data-candidate="${esc(c.id)}" ${saved.opened.has(c.id)?'open':''}><summary>查看实际依据</summary><blockquote>${esc(c.evidence.quote)}</blockquote><div class="archive-evidence-meta">${externalLink(c.evidence.url,'官方网站原页')}<span>取得 ${dateTime(c.evidence.fetched_at)}</span></div><details><summary>本次材料与版本</summary><pre>${esc(c.evidence.text)}</pre><p class="small">SHA-256 ${esc(c.evidence.sha256)}</p><p class="small">输入 ${esc(c.input_hash)} · 基准版本 ${c.base_version} · 模型 ${esc(c.machine.response_model||c.machine.requested_model||'待记录')}</p></details></details>${c.decided_by?`<p class="small">${esc(archiveStates[c.status])}：${esc(c.decided_by)} · ${dateTime(c.decided_at)}</p>`:''}</article>`;
}
async function openArchiveSuggestions(sid){
  clearTimeout(archiveTimer);
  const account=state.me.id,data=await api('/api/sources/'+encodeURIComponent(sid)+'/suggestions');
  if(state.me?.id!==account)return;
  archiveView={sid,account};
  modal('AI补全与依据',archiveReviewHtml(data,{selected:new Set(),opened:new Set(),scroll:0}));
  scheduleArchiveRefresh(data);
}
function scheduleArchiveRefresh(data){
  clearTimeout(archiveTimer);
  if(data.jobs.some(j=>['queued','running'].includes(j.status)))archiveTimer=setTimeout(()=>refreshArchiveSuggestions().catch(()=>{}),2500);
}
async function refreshArchiveSuggestions(){
  const root=document.querySelector('[data-archive-review]'),view=archiveView;
  if(!root||!view||view.account!==state.me?.id)return;
  const saved=archiveSnapshot(),data=await api('/api/sources/'+encodeURIComponent(view.sid)+'/suggestions');
  if(!root.isConnected||view!==archiveView||view.account!==state.me?.id)return;
  // Keep current choices and expanded evidence while a durable worker progresses.
  root.outerHTML=archiveReviewHtml(data,saved);
  document.querySelector('#modal-root .drawer-body').scrollTop=saved.scroll;
  scheduleArchiveRefresh(data);
}
document.addEventListener('click',async event=>{
  const open=event.target.closest('[data-archive-source]');
  if(open){try{await openArchiveSuggestions(open.dataset.archiveSource);}catch(error){toast(error.message);}return;}
  const batch=event.target.closest('[data-archive-batch]');
  if(batch){
    try{const query=new URLSearchParams(state.params);query.delete('id');const data=await api('/api/sources?'+query);
      const rows=data.items.filter(s=>isInstitution(s)||isPublication(s));
      modal('批量取得档案建议',`<form data-form="archive-batch"><div class="archive-batch-list">${rows.map(s=>`<label><input type="checkbox" name="source" value="${esc(s.id)}">${esc(s.name)}</label>`).join('')||'<p>当前查找没有适用档案。</p>'}</div><div class="form-error" role="alert"></div><div class="form-actions"><button class="button" type="button" data-action="close">关闭</button><button class="button primary" type="submit">为所选来源排队</button></div></form>`);
    }catch(error){toast(error.message);}return;
  }
  const button=event.target.closest('[data-archive-action]');if(!button)return;
  const root=button.closest('[data-archive-review]');if(!root)return;
  button.disabled=true;
  try{
    if(button.dataset.archiveAction==='queue')await api('/api/archive-jobs',{method:'POST',body:{source_ids:[root.dataset.id],request_id:crypto.randomUUID()}});
    if(button.dataset.archiveAction==='cancel')await api('/api/archive-jobs/'+encodeURIComponent(button.dataset.id)+'/cancel',{method:'POST',body:{}});
    await refreshArchiveSuggestions();
  }catch(error){root.querySelector('.form-error').textContent=error.message;button.disabled=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target;if(!['archive-decide','archive-batch'].includes(form.dataset.form))return;
  event.preventDefault();const button=event.submitter;button.disabled=true;
  try{
    if(form.dataset.form==='archive-batch'){
      const ids=new FormData(form).getAll('source');
      if(!ids.length||ids.length>20)throw new Error('请选择1—20个来源。');
      await api('/api/archive-jobs',{method:'POST',body:{source_ids:ids,request_id:crypto.randomUUID()}});
      toast('已排队 '+ids.length+' 个来源');closeModal();return;
    }
    const root=form.closest('[data-archive-review]'),ids=new FormData(form).getAll('candidate');
    if(!ids.length)throw new Error('请勾选建议。');
    await api('/api/sources/'+encodeURIComponent(root.dataset.id)+'/suggestions/decide',{method:'POST',body:{version:Number(root.dataset.version),[button.value]:ids}});
    await loadLookups();await refreshArchiveSuggestions();toast(button.value==='adopt'?'已采用所选建议，仍待核对':'已拒绝所选建议');
  }catch(error){form.querySelector('.form-error').textContent=error.message;button.disabled=false;}
});
