'use strict';
const archiveFieldNames={name:'显示名称',original_name:'原文名称',aliases:'其他名称',introduction:'来源介绍',institution_types:'机构类型',location:'所在地',country:'机构国家',research_scope:'研究覆盖范围',issn:'ISSN',website:'官方网站',catalogue_url:'资料入口',host:'主办机构',publisher:'出版机构',relationships:'机构关系',international_status:'国际办刊定位'};
const archiveStates={queued:'等待后台',running:'正在取得与整理',paused:'暂停待恢复',failed:'取得或处理失败',invalidated:'已失效',cancelled:'已取消',ready:'待核对建议',empty:'无新增有据建议',unmatched:'机构待匹配',pending:'待选择',adopted:'已采用',rejected:'已拒绝'};
function archiveValue(value,field){
  if(field==='country'&&value)return [...new Set(String(value).split(/[|;；,，]/).map(x=>countryLabel(x.trim())).filter(Boolean))].join(' / ');
  if(Array.isArray(value))return value.map(v=>typeof v==='string'?(institutionTypes[v]||v):JSON.stringify(v)).join(' / ')||'未登记';
  if(value&&typeof value==='object')return (value.type?(relationLabels[value.type]||value.type)+'：':'')+(value.target_name||JSON.stringify(value));
  if(['host','publisher'].includes(field)&&value)return value.split(' | ').map(id=>state.sources.find(s=>s.id===id)?.name||id).join(' / ');
  if(field==='international_status')return internationalLabels[value]||value||'未登记';
  return String(value||'未登记');
}
let archiveView=null,archiveTimer,archiveRefreshTurn=0;
// These controls only describe candidate checkboxes; identity and optional
// employment/unit decisions remain separate, explicit choices.
function suggestionSelectionControls(total,selected,available=total){
  return `<div class="row wrap section-gap" data-suggestion-selection><span role="status" aria-live="polite" data-suggestion-count>待核对 ${total} 项 · 可全选 ${available} 项 · 已选 ${selected} 项</span><button type="button" class="button tiny" data-suggestion-select="all" ${available?'':'disabled'}>选择当前有据待核对项</button><button type="button" class="button tiny" data-suggestion-select="clear" ${selected?'':'disabled'}>清空选择</button></div><p class="form-help">按项核对后再采用或拒绝；待匹配、失效及附带的任职／单位不自动全选。</p>`;
}
function updateSuggestionSelection(form){
  const inputs=[...form.querySelectorAll('input[name=candidate]')],count=inputs.filter(x=>x.checked).length,busy=form.dataset.saving==='true';
  form.querySelector('[data-suggestion-count]').textContent=`待核对 ${inputs.length} 项 · 可全选 ${inputs.filter(x=>x.dataset.suggestionEligible!=='false').length} 项 · 已选 ${count} 项`;
  for(const b of form.querySelectorAll('button[type=submit]'))b.disabled=busy||!count;
  form.inert=busy;
  form.querySelector('[data-suggestion-select=clear]').disabled=busy||!count;
  form.querySelector('[data-suggestion-select=all]').disabled=busy||!inputs.some(x=>x.dataset.suggestionEligible!=='false'&&!x.checked);
}
document.addEventListener('change',event=>{if(event.target.matches('input[name=candidate]')){const form=event.target.closest('form');if(form?.querySelector('[data-suggestion-selection]'))updateSuggestionSelection(form);}});
document.addEventListener('click',event=>{
  const b=event.target.closest('[data-suggestion-select]');if(!b)return;const form=b.closest('form');if(form.dataset.saving==='true')return;
  for(const input of form.querySelectorAll('input[name=candidate]'))if(b.dataset.suggestionSelect==='clear'||input.dataset.suggestionEligible!=='false')input.checked=b.dataset.suggestionSelect==='all';
  if(b.dataset.suggestionSelect==='clear')for(const input of form.querySelectorAll('[name=article_units],[name=employments]'))input.checked=false;
  updateSuggestionSelection(form);
});
function archiveSnapshot(){
  const root=document.querySelector('[data-archive-review]');
  return {selected:new Set([...(root?.querySelectorAll('input[name=candidate]:checked')||[])].map(x=>x.value)),
    opened:new Set([...(root?.querySelectorAll('details[open]')||[])].map(x=>x.dataset.candidate||x.dataset.archiveHistory)),
    choices:Object.fromEntries([...(root?.querySelectorAll('[data-author-choice]')||[])].map(x=>[x.dataset.authorChoice,x.value])),
    units:new Set([...(root?.querySelectorAll('input[name=article_units]:checked')||[])].map(x=>x.value)),
    employments:new Set([...(root?.querySelectorAll('input[name=employments]:checked')||[])].map(x=>x.value)),
    error:root?.querySelector('.form-error')?.textContent||'',scroll:document.querySelector('#modal-root .drawer-body')?.scrollTop||0};
}
function archiveReviewHtml(data,saved){
  const author=data.target_type==='record';
  const pending=data.candidates.filter(c=>['pending','unmatched'].includes(c.status));
  const title=esc(data.name||state.sources.find(s=>s.id===data.target_id)?.name||'来源档案');
  return `<section data-archive-review data-id="${esc(data.target_id)}" data-version="${data.version}" data-type="${data.target_type||'source'}" data-byline-version="${data.byline_version||0}"><div class="between wrap"><h3>${title}</h3><button class="button tiny" data-archive-action="refresh">刷新</button></div><div class="archive-jobs">${data.jobs.slice(0,3).map(j=>`<div><strong>${esc(archiveStates[j.status]||j.status)}</strong>${j.reason&&!['ready','empty'].includes(j.status)?`<p role="status">${esc(j.reason)}</p>`:''}${['queued','running','paused'].includes(j.status)?`<button class="button tiny" data-archive-action="cancel" data-id="${esc(j.id)}">取消任务</button>`:''}</div>`).join('')||'<p>尚未排队。</p>'}</div>${author?`<p class="notice">${data.coverage.authors} 位署名 · ${data.coverage.supported} 位有身份材料 · ${data.coverage.remaining} 位仍待补证</p>${(data.coverage.limitations||[]).map(x=>`<p>${esc(x)}</p>`).join('')}`:''}<form data-form="archive-decide">${suggestionSelectionControls(pending.length,pending.filter(c=>saved.selected.has(c.id)).length,pending.filter(c=>c.status==='pending'&&!c.stale&&c.operation?.action!=='unmatched').length)}<div class="archive-candidates">${pending.map(c=>archiveCandidate(c,saved)).join('')||'<p class="notice">当前没有待选择的有据建议。</p>'}</div><div class="form-error" role="alert"></div><div class="archive-actions"><button type="submit" class="button primary" name="decision" value="adopt" ${pending.some(c=>saved.selected.has(c.id))?'':'disabled'}>采用所选</button><button type="submit" class="button" name="decision" value="reject" ${pending.some(c=>saved.selected.has(c.id))?'':'disabled'}>拒绝所选</button></div></form><div class="row wrap section-gap"><button class="button" data-archive-action="queue">${data.jobs.length?'重新取得建议':author?'取得作者建议':'取得AI补全建议'}</button><a class="button" href="${archiveTargetPath(data.target_type,data.target_id)}/export" download>导出建议与依据</a></div>${data.candidates.some(c=>!['pending','unmatched'].includes(c.status))?`<details class="section-gap" data-archive-history="history" ${saved.opened.has('history')?'open':''}><summary>已处理建议与采用来历</summary>${data.candidates.filter(c=>!['pending','unmatched'].includes(c.status)).map(c=>archiveCandidate(c,saved)).join('')}</details>`:''}<details class="section-gap" data-archive-history="events" ${saved.opened.has('events')?'open':''}><summary>处理历史</summary>${data.events.map(e=>`<p>${esc(archiveStates[e.action]||e.action)} · ${esc(e.actor_id)} · ${dateTime(e.created_at)}</p>`).join('')||'<p>尚无处理历史。</p>'}</details></section>`;
}
function archiveCandidate(c,saved){
  if(c.operation)return authorCandidate(c,saved);
  const selectable=['pending','unmatched'].includes(c.status);
  return `<article class="archive-candidate" data-candidate-row="${esc(c.id)}"><div class="between wrap"><label class="archive-choice">${selectable?`<input type="checkbox" name="candidate" data-suggestion-eligible="${c.status==='pending'&&!c.stale&&c.operation?.action!=='unmatched'}" value="${esc(c.id)}" ${saved.selected.has(c.id)?'checked':''}>`:''}<strong>${esc((archiveFieldNames[c.field]||c.field)+(c.evidence_only?'依据':''))}</strong></label>${c.status!=='pending'?'<span class="badge neutral">'+esc(archiveStates[c.status])+'</span>':''}</div><div class="archive-comparison"><div><span>原值</span><p>${esc(c.evidence_only?(c.before_evidence||'未登记'):archiveValue(c.before,c.field))}</p></div><div><span>建议值</span><p>${esc(c.evidence_only?c.evidence.quote:archiveValue(c.value,c.field))}</p></div></div>${c.status==='unmatched'?'<p class="notice">关联机构尚未唯一登记；保留依据，可先登记或核查机构后重新取得。</p>':''}${c.stale&&selectable?'<p class="notice">档案已有修订；建议保留，请对照当前档案后重新取得。</p>':''}<details data-candidate="${esc(c.id)}" ${saved.opened.has(c.id)?'open':''}><summary>查看实际依据</summary><blockquote>${esc(c.evidence.quote)}</blockquote><div class="archive-evidence-meta">${externalLink(c.evidence.url,'查看来源')}<span>取得 ${dateTime(c.evidence.fetched_at)}</span></div><details><summary>本次材料与版本</summary><pre>${esc(c.evidence.text)}</pre><p class="small">SHA-256 ${esc(c.evidence.sha256)}</p><p class="small">输入 ${esc(c.input_hash)} · 基准版本 ${c.base_version} · 模型 ${esc(c.machine.response_model||c.machine.requested_model||'待记录')}</p></details></details>${c.decided_by?`<p class="small">${esc(archiveStates[c.status])}：${esc(c.decided_by)} · ${dateTime(c.decided_at)}</p>`:''}</article>`;
}
function archiveTargetPath(type,id){return '/api/'+(type==='record'?'records':'sources')+'/'+encodeURIComponent(id)+'/suggestions';}
function suggestionQueueRequest(owner,body){
  const signature=JSON.stringify(Object.entries(body).map(([key,value])=>[key,Array.isArray(value)?[...value].sort():value]));
  if(owner._archiveRequest?.signature!==signature)owner._archiveRequest={signature,id:crypto.randomUUID()};
  return {...body,request_id:owner._archiveRequest.id};
}
function archiveBatchControls(scope){return `<div class="row wrap section-gap"><button type="button" class="button tiny" data-batch-select="all">全选${scope}</button><button type="button" class="button tiny" data-batch-select="clear">清空全部选择</button></div><div data-batch-summary role="status" aria-live="polite"></div>`;}
function updateArchiveBatch(form){
  const author=form.dataset.form==='author-batch',name=author?'author_record':'source',inputs=[...form.querySelectorAll(`input[name=${name}]`)];
  const ids=author?[...authorBatchSelection]:inputs.filter(x=>x.checked).map(x=>x.value),visible=inputs.filter(x=>!x.closest('label').hidden),visibleIds=new Set(visible.map(x=>x.value));
  const titles=author?authorBatchTitles:form._sourceTitles,hidden=ids.filter(id=>!visibleIds.has(id));
  const opened=!!form.querySelector('[data-batch-summary] details[open]');
  form.querySelector('[data-batch-summary]').innerHTML=`<p>已选 ${ids.length} / 20 项 · 当前未显示 ${hidden.length} 项 · 当前范围 ${visible.length} 项</p>${new Set([...ids,...visibleIds]).size>20?'<p class="form-help">当前范围与已选合计超过20项，不能全选。请逐项选择或清空后分批处理。</p>':''}${ids.length?`<details ${opened?'open':''}><summary>查看全部已选（含隐藏项）</summary>${ids.map(id=>`<p>${esc(titles?.get(id)||id)} <button type="button" class="button tiny" data-batch-remove="${esc(id)}">移除此项</button></p>`).join('')}</details>`:'<p class="form-help">请先选择1—20项再排队。</p>'}`;
  const busy=form.dataset.saving==='true';
  form.inert=busy;
  for(const input of inputs)input.disabled=!input.checked&&ids.length>=20;
  form.querySelector('[type=submit]').disabled=busy||!ids.length||ids.length>20;
  form.querySelector('[data-batch-select=all]').disabled=busy||!visible.length||new Set([...ids,...visibleIds]).size>20||visible.every(x=>x.checked);
  form.querySelector('[data-batch-select=clear]').disabled=busy||!ids.length;
}
async function archiveBatchForm(){
  const query=new URLSearchParams(state.params);query.delete('id');if(state.page==='maintenance-sources'&&!query.has('status'))query.set('status','pending');if(query.get('status')==='all')query.delete('status');
  const account=state.me.id,data=await api('/api/sources?'+query);if(account!==state.me?.id)return;
  const rows=data.items.filter(s=>isInstitution(s)||isPublication(s));
  modal('批量取得档案建议',`<form data-form="archive-batch"><p>本次查找共 ${rows.length} 个适用来源；每批最多20项。</p><label class="field">在本次结果中筛选<input type="search" data-source-batch-search></label>${archiveBatchControls('当前筛选结果')}<div class="archive-batch-list">${rows.map(s=>`<label data-batch-title="${esc(s.name.toLocaleLowerCase())}"><input type="checkbox" name="source" value="${esc(s.id)}">${esc(s.name)}</label>`).join('')||'<p>当前查找没有适用档案。请调整来源查找条件。</p>'}</div><div class="form-error" role="alert"></div><div class="form-actions"><button class="button" type="button" data-action="close">关闭</button><button class="button primary" type="submit" disabled>为所选来源排队</button></div></form>`);
  const form=document.querySelector('[data-form=archive-batch]');form._sourceTitles=new Map(rows.map(s=>[s.id,s.name]));form._account=account;updateArchiveBatch(form);
}
async function openArchiveSuggestions(sid,type='source'){
  clearTimeout(archiveTimer);
  const account=state.me.id,data=await api(archiveTargetPath(type,sid));
  if(state.me?.id!==account)return;
  archiveView={sid,type,account,data};
  modal(type==='record'?'作者关联建议':'AI补全与依据',archiveReviewHtml(data,{selected:new Set(),opened:new Set(),scroll:0}));
  updateSuggestionSelection(document.querySelector('[data-form=archive-decide]'));
  scheduleArchiveRefresh(data);
}
function scheduleArchiveRefresh(data){
  clearTimeout(archiveTimer);
  if(data.jobs.some(j=>['queued','running'].includes(j.status)))archiveTimer=setTimeout(()=>refreshArchiveSuggestions().catch(()=>{}),2500);
}
async function refreshArchiveSuggestions(){
  const root=document.querySelector('[data-archive-review]'),view=archiveView;
  if(!root||!view||view.account!==state.me?.id)return;
  if(root.querySelector('form')?.dataset.saving==='true'||view.queueSaving){scheduleArchiveRefresh(view.data);return;}
  const turn=++archiveRefreshTurn,data=await api(archiveTargetPath(view.type,view.sid));
  if(!root.isConnected||view!==archiveView||view.account!==state.me?.id||turn!==archiveRefreshTurn||root.querySelector('form')?.dataset.saving==='true'||view.queueSaving)return;
  const saved=archiveSnapshot(),active=document.activeElement,focus=root.contains(active)?{name:active.name,value:active.value,action:active.dataset.archiveAction,choice:active.dataset.authorChoice}:null;
  // Keep current choices and expanded evidence while a durable worker progresses.
  root.outerHTML=archiveReviewHtml(data,saved);
  document.querySelector('#modal-root .drawer-body').scrollTop=saved.scroll;
  const next=document.querySelector('[data-archive-review]');updateSuggestionSelection(next.querySelector('form'));
  next.querySelector('.form-error').textContent=saved.error;view.data=data;
  if(focus){const target=focus.name?[...next.querySelectorAll('[name]')].find(x=>x.name===focus.name&&x.value===focus.value):focus.choice?[...next.querySelectorAll('[data-author-choice]')].find(x=>x.dataset.authorChoice===focus.choice):[...next.querySelectorAll('[data-archive-action]')].find(x=>x.dataset.archiveAction===focus.action);target?.focus({preventScroll:true});}
  scheduleArchiveRefresh(data);
}
document.addEventListener('click',async event=>{
  const authorOpen=event.target.closest('[data-archive-record]');
  if(authorOpen){try{await openArchiveSuggestions(authorOpen.dataset.archiveRecord,'record');}catch(error){toast(error.message);}return;}
  const authorBatch=event.target.closest('[data-author-batch]');
  if(authorBatch){try{await authorBatchForm();}catch(error){toast(error.message);}return;}
  const authorPage=event.target.closest('[data-author-page]');
  if(authorPage){try{await authorBatchResults(Number(authorPage.dataset.authorPage));}catch(error){toast(error.message);}return;}
  const open=event.target.closest('[data-archive-source]');
  if(open){try{await openArchiveSuggestions(open.dataset.archiveSource);}catch(error){toast(error.message);}return;}
  const batch=event.target.closest('[data-archive-batch]');
  if(batch){
    try{await archiveBatchForm();}catch(error){toast(error.message);}return;
  }
  const button=event.target.closest('[data-archive-action]');if(!button)return;
  const root=button.closest('[data-archive-review]');if(!root)return;
  const view=archiveView;if(view?.queueSaving)return;button.disabled=true;
  try{
    if(button.dataset.archiveAction==='queue'){view.queueSaving=true;await api('/api/archive-jobs',{method:'POST',body:suggestionQueueRequest(view,{[root.dataset.type==='record'?'record_ids':'source_ids']:[root.dataset.id]})});view._archiveRequest=null;view.queueSaving=false;}
    if(button.dataset.archiveAction==='cancel')await api('/api/archive-jobs/'+encodeURIComponent(button.dataset.id)+'/cancel',{method:'POST',body:{}});
    await refreshArchiveSuggestions();
  }catch(error){if(root.isConnected){root.querySelector('.form-error').textContent=error.message;button.disabled=false;}}finally{if(view)view.queueSaving=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target;if(!['archive-decide','archive-batch'].includes(form.dataset.form))return;
  event.preventDefault();if(form.dataset.saving==='true')return;const button=event.submitter;if(!button)return;const account=state.me?.id;form.dataset.saving='true';button.disabled=true;form.querySelector('.form-error').textContent='';
  if(form.dataset.form==='archive-decide')updateSuggestionSelection(form);else updateArchiveBatch(form);
  try{
    if(form.dataset.form==='archive-batch'){
      const ids=new FormData(form).getAll('source');
      if(!ids.length||ids.length>20)throw new Error('请选择1—20个来源。');
      await api('/api/archive-jobs',{method:'POST',body:suggestionQueueRequest(form,{source_ids:ids})});
      if(!form.isConnected||form._account!==state.me?.id)return;
      toast('已排队 '+ids.length+' 个来源');closeModal();return;
    }
    const root=form.closest('[data-archive-review]'),ids=new FormData(form).getAll('candidate');
    if(!ids.length)throw new Error('请勾选建议。');
    const body={version:Number(root.dataset.version),byline_version:Number(root.dataset.bylineVersion),[button.value]:ids};
    if(root.dataset.type==='record'&&button.value==='adopt'){
      body.choices=Object.fromEntries([...form.querySelectorAll('[data-author-choice]')].filter(x=>ids.includes(x.dataset.authorChoice)).map(x=>[x.dataset.authorChoice,x.value]));
      body.article_units=new FormData(form).getAll('article_units').filter(id=>ids.includes(id));
      body.employments=new FormData(form).getAll('employments').filter(id=>ids.includes(id));
    }
    await api(archiveTargetPath(root.dataset.type,root.dataset.id)+'/decide',{method:'POST',body});
    if(!form.isConnected||account!==state.me?.id)return;
    await loadLookups();form.dataset.saving='false';await refreshArchiveSuggestions();toast(button.value==='adopt'?'已采用所选建议，仍待核对':'已拒绝所选建议');
  }catch(error){if(form.isConnected)form.querySelector('.form-error').textContent=error.message;}finally{form.dataset.saving='false';if(form.isConnected){if(form.dataset.form==='archive-batch')updateArchiveBatch(form);else updateSuggestionSelection(form);}}
});

function authorMaterial(e,quote='',technical=''){
  return `<blockquote>${esc(quote||e.text.slice(0,900))}</blockquote><div class="archive-evidence-meta">${externalLink(e.url,'查看来源')}<span>取得 ${dateTime(e.fetched_at)}</span></div><details><summary>完整实际材料与版本</summary><pre>${esc(e.text)}</pre><p class="small">SHA-256 ${esc(e.sha256)}</p>${technical}</details>`;
}
function authorCandidate(c,saved){
  const fact=c.value,op=c.operation,selectable=['pending','unmatched'].includes(c.status);
  const actions={create_person:'新建有据人物＋关联本篇',choose_identity:'选择身份＋关联本篇',link_existing:op.kind==='institution'?'已有机构署名＋关联本篇':'已有作者＋关联本篇',unmatched:'保留未确认署名'};
  const identity=c.identity?.name||fact.raw_name;
  const technical=`<p class="small">输入 ${esc(c.input_hash)} · 基准版本 ${c.base_version} · 模型 ${esc(c.machine.response_model||c.machine.requested_model||'待记录')}</p>`;
  const nativeFields=`<div class="author-native-facts"><strong>${fact.native.given||fact.native.family?'原题录作者字段':'文章结构化作者字段'}</strong><p>姓名：${esc(fact.raw_name)}</p>${fact.orcid?`<p>ORCID：${esc(fact.orcid)}</p>`:''}${c.article_doi?`<p>文章 DOI：${esc(c.article_doi)}</p>`:''}<p>作者位置：author[${fact.index}]</p></div>`;
  const choice=op.action==='choose_identity'&&selectable?`<label class="field">选择已有作者或新建有据人物<select data-author-choice="${esc(c.id)}" aria-label="${esc(fact.raw_name)}身份"><option value="">请选择身份</option>${op.matches.map(m=>`<option value="${esc(m.id)}" ${saved.choices?.[c.id]===m.id?'selected':''}>${esc(m.name)} · 已有作者</option>`).join('')}<option value="new" ${saved.choices?.[c.id]==='new'?'selected':''}>新建有据人物</option></select></label>`:'';
  const related=['article_units','employments'].map(key=>(op[key]||[]).length?`<div class="section-gap">${selectable?`<label class="archive-choice"><input type="checkbox" name="${key}" value="${esc(c.id)}" ${(key==='article_units'?saved.units:saved.employments)?.has(c.id)?'checked':''}>同时采用${key==='article_units'?'文章单位':'任职经历'}</label>`:`<strong>${key==='article_units'?'文章单位建议':'任职建议'}</strong>`}${op[key].map(r=>`<p>${esc(r.institution_name)}${r.role?' · '+esc(r.role):''}</p><blockquote>${esc(r.quote)}</blockquote>`).join('')}</div>`:'').join('');
  return `<article class="archive-candidate" data-candidate-row="${esc(c.id)}"><div class="between wrap"><label class="archive-choice">${selectable?`<input type="checkbox" name="candidate" data-suggestion-eligible="${c.status==='pending'&&!c.stale&&c.operation?.action!=='unmatched'}" value="${esc(c.id)}" ${saved.selected.has(c.id)?'checked':''}>`:''}<strong>署名 ${fact.index+1}：${esc(fact.raw_name)}</strong></label>${c.status==='pending'?'':`<span class="badge neutral">${esc(c.status==='unmatched'?'身份待核':archiveStates[c.status]||c.status)}</span>`}</div><div class="archive-comparison"><div><span>原始署名</span><p>${esc(fact.raw_name)}</p></div><div><span>建议身份与操作</span><p>${esc(identity)} · ${esc(actions[op.action])}</p>${fact.orcid?`<p>ORCID ${esc(fact.orcid)}</p>`:''}</div></div>${choice}${op.action==='unmatched'?'<p class="notice">身份依据不足或有冲突，保留候选与原始署名，可继续阅读或人工整理。</p>':''}${c.stale&&selectable?'<p class="notice">资料或署名已有修订；当前选择保留，请对照最新内容。</p>':''}${related}<details data-candidate="${esc(c.id)}" ${saved.opened.has(c.id)?'open':''}><summary>查看实际依据</summary>${nativeFields}<details><summary>原始字段片段</summary>${authorMaterial(c.evidence,c.evidence.quote,technical)}</details>${(c.additional_evidence||[]).map(e=>authorMaterial(e)).join('')}</details>${c.decided_by?`<p class="small">${esc(archiveStates[c.status])}：${esc(c.decided_by)} · ${dateTime(c.decided_at)}</p>`:''}</article>`;
}
let authorBatchSelection=new Set(),authorBatchEpoch=0,authorBatchTitles=new Map();
function rememberAuthorBatch(){for(const input of document.querySelectorAll('input[name=author_record]'))input.checked?authorBatchSelection.add(input.value):authorBatchSelection.delete(input.value);}
async function authorBatchResults(page=1){
  rememberAuthorBatch();
  const q=document.querySelector('[data-form=author-search] input').value,epoch=++authorBatchEpoch,root=document.querySelector('[data-author-results]'),account=state.me?.id;
  root.innerHTML='<p role="status">正在查找资料…</p>';
  updateArchiveBatch(root.closest('form'));
  const data=await api('/api/records?author_suggestions=1&size=20&page='+page+'&q='+encodeURIComponent(q));
  if(epoch!==authorBatchEpoch||!root.isConnected||account!==state.me?.id)return;
  const rows=data.items;
  for(const r of rows)authorBatchTitles.set(r.id,r.title);
  root.innerHTML=`<div class="archive-batch-list">${rows.map(r=>`<label><input type="checkbox" name="author_record" value="${esc(r.id)}" ${authorBatchSelection.has(r.id)?'checked':''}>${esc(r.title)}</label>`).join('')||'<p>当前页没有含公开网址或 DOI 的外部资料。</p>'}</div><div class="row wrap section-gap">${page>1?`<button class="button" type="button" data-author-page="${page-1}">上一页</button>`:''}<span>第 ${page} 页</span>${page*20<data.total?`<button class="button" type="button" data-author-page="${page+1}">下一页</button>`:''}</div>`;
  updateArchiveBatch(root.closest('form'));
}
async function authorBatchForm(){
  authorBatchSelection=new Set();authorBatchTitles=new Map();
  modal('批量作者关联建议',`<form data-form="author-search" class="row wrap"><label class="field">资料关键词<input type="search" name="q"></label><button class="button" type="submit">查找资料</button></form><form data-form="author-batch">${archiveBatchControls('当前页')}<div data-author-results></div><p>只为明确选中的1—20篇公开外部资料排队。</p><div class="form-error" role="alert"></div><button class="button primary" type="submit" disabled>为所选资料排队</button></form>`);
  document.querySelector('[data-form=author-batch]')._account=state.me.id;
  await authorBatchResults();
}
document.addEventListener('submit',async event=>{
  const form=event.target;if(!['author-search','author-batch'].includes(form.dataset.form))return;
  event.preventDefault();
  if(form.dataset.form==='author-batch'&&form.dataset.saving==='true')return;
  try{
    if(form.dataset.form==='author-search'){await authorBatchResults();return;}
    rememberAuthorBatch();const ids=[...authorBatchSelection];
    if(!ids.length||ids.length>20)throw new Error('请选择1—20篇公开外部资料。');
    form.dataset.saving='true';updateArchiveBatch(form);
    await api('/api/archive-jobs',{method:'POST',body:suggestionQueueRequest(form,{record_ids:ids})});
    if(!form.isConnected||form._account!==state.me?.id)return;
    modal('已排队作者建议',`<p>后台正在取得与整理，可打开逐篇核对。</p><div class="archive-batch-list">${ids.map(id=>`<button class="button" data-archive-record="${esc(id)}">核对作者建议：${esc(authorBatchTitles.get(id)||'所选资料')}</button>`).join('')}</div>`);
  }catch(error){if(form.isConnected){const target=document.querySelector('[data-form=author-batch] .form-error');if(target)target.textContent=error.message;else toast(error.message);}}finally{if(form.dataset.form==='author-batch'){form.dataset.saving='false';if(form.isConnected)updateArchiveBatch(form);}}
});

document.addEventListener('change',event=>{
  if(event.target.matches('input[name=author_record]')){event.target.checked?authorBatchSelection.add(event.target.value):authorBatchSelection.delete(event.target.value);updateArchiveBatch(event.target.closest('form'));}
  if(event.target.matches('[data-form=archive-batch] input[name=source]'))updateArchiveBatch(event.target.closest('form'));
});
document.addEventListener('input',event=>{if(!event.target.matches('[data-source-batch-search]'))return;const form=event.target.closest('form'),q=event.target.value.toLocaleLowerCase().trim();for(const label of form.querySelectorAll('[data-batch-title]'))label.hidden=!label.dataset.batchTitle.includes(q);updateArchiveBatch(form);});
document.addEventListener('click',event=>{
  const b=event.target.closest('[data-batch-select],[data-batch-remove]');if(!b)return;const form=b.closest('form');if(form.dataset.saving==='true')return;
  const author=form.dataset.form==='author-batch',name=author?'author_record':'source';
  if(author&&b.dataset.batchSelect==='clear')authorBatchSelection.clear();
  if(author&&b.dataset.batchRemove)authorBatchSelection.delete(b.dataset.batchRemove);
  for(const input of form.querySelectorAll(`input[name=${name}]`)){
    if(b.dataset.batchRemove){if(input.value===b.dataset.batchRemove)input.checked=false;}
    else if(b.dataset.batchSelect==='clear')input.checked=false;
    else if(!input.closest('label').hidden)input.checked=true;
    if(author)input.checked?authorBatchSelection.add(input.value):authorBatchSelection.delete(input.value);
  }
  updateArchiveBatch(form);
  if(b.dataset.batchRemove)form.querySelector('[data-batch-summary] summary')?.focus();
});
