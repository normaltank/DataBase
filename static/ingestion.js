'use strict';
const ingestionLabels={queued:'等待后台运行',running:'后台运行中',failed:'取得失败',partial:'部分失败',succeeded:'本轮已完成',saved:'已保存',excluded:'规则排除',blocked:'受限重复待检查',acquiring:'正在取得',feed:'取得官方目录',entries:'保存单篇',done:'完成'};
const ingestionFields=['enabled','frequency_hours','inclusion_rule','backfill_days'];
let ingestionView=null;
function ingestionRequestTokens(actor){
  try{return new Map(JSON.parse(sessionStorage.getItem('ingestion-requests:'+actor)||'[]').filter(pair=>Array.isArray(pair)&&pair.length===2&&pair.every(value=>typeof value==='string')));}catch{return new Map();}
}
function ingestionKeepRequests(view){try{sessionStorage.setItem('ingestion-requests:'+view.actor,JSON.stringify([...view.tokens]));}catch{/* Requests remain stable in this page when browser storage is unavailable. */}}
function ingestionValues(source){return {enabled:!!source.enabled,frequency_hours:Number(source.frequency_hours),inclusion_rule:source.inclusion_rule,backfill_days:Number(source.backfill_days||30)};}
function ingestionDirty(item){return ingestionFields.some(key=>item.draft[key]!==item.saved[key]);}
function ingestionRunnable(item){return item.saved.enabled&&!ingestionDirty(item)&&!item.busy;}
function ingestionAccept(data,revisions,drafts){
  const actor=state.me?.id;
  if(!ingestionView||ingestionView.actor!==actor)ingestionView={actor,items:new Map(),selected:new Set(),tokens:ingestionRequestTokens(actor),unavailable:[],refreshing:false,batch:false,summary:''};
  const view=ingestionView, present=new Set();
  for(const source of data.items){
    const id=source.source_id, saved=ingestionValues(source), old=view.items.get(id);present.add(id);
    if(old&&revisions&&(old.busy||old.revision!==revisions.get(id)))continue;
    const draft=old?{...old.draft}:{...saved};
    if(old&&(!drafts||drafts.get(id)===old.draft))for(const key of ingestionFields)if(draft[key]===old.saved[key])draft[key]=saved[key];
    if(old)Object.assign(old,{source,saved,draft});else view.items.set(id,{source,saved,draft});
  }
  for(const id of view.items.keys())if(!present.has(id)){view.items.delete(id);view.selected.delete(id);}
  view.unavailable=data.unavailable||[];view.heartbeat=data.worker_heartbeat;return view;
}
function ingestionRunsHtml(s){return `<dl class="detail-grid section-gap">${detailPair('状态',s.enabled?'已启用':'未启用')}${detailPair('最近尝试',s.last_attempt?dateTime(s.last_attempt):'尚未尝试')}${detailPair('最近成功取得官方目录',s.last_success?dateTime(s.last_success):'尚未成功')}${detailPair('下次巡检',s.enabled?dateTime(s.next_run):'已停用')}</dl>${s.last_error?'<p class="notice error">'+esc(s.last_error)+'</p>':''}<p class="small">覆盖：${esc(s.scope)}。近期可为零；零条只表示当前响应无可纳入条目。</p>${s.runs.map(r=>`<details class="ingestion-run" ${['failed','partial','running','queued'].includes(r.status)?'open':''}><summary>${esc(ingestionLabels[r.status]||r.status)} · ${esc(ingestionLabels[r.stage]||r.stage)} · 尝试 ${r.attempts} 次 · ${dateTime(r.created_at)}</summary>${r.error?'<p class="notice error">'+esc(r.error)+'</p>':''}${['partial','failed'].includes(r.status)?`<button class="button" data-action="ingestion-retry" data-id="${esc(r.id)}">重跑失败条目</button>`:''}<p>目录返回 ${r.coverage.returned??'未知'} 条；窗口 ${esc(r.coverage.window?.start||'未取得')} 至 ${esc(r.coverage.window?.end||'未取得')}；最早日期 ${esc(r.coverage.earliest||'未知')}</p><p>${esc((r.coverage.warnings||[]).join(' '))}</p>${r.entries.map(e=>`<article class="ingestion-entry"><strong>${esc(e.title)}</strong><p>${esc(ingestionLabels[e.stage]||e.stage)} · 尝试 ${e.attempts} 次 · ${esc(e.reason)}${e.error?' · '+esc(e.error):''}</p>${e.record_id?linkButton('阅读已保存资料','detail',e.record_id,'button tiny'):''}<details><summary>目录原始字段</summary><pre>${esc(JSON.stringify(e.raw,null,2))}</pre></details></article>`).join('')}<details><summary>覆盖、排除与继续取得位置</summary><pre>${esc(JSON.stringify(r.coverage,null,2))}</pre></details></details>`).join('')||'<p>尚无采集任务。保存启用后等待后台，或安排立即巡检。</p>'}`;}
function ingestionSourceHtml(item){
  const s=item.source,d=item.draft,id=esc(s.source_id),selected=ingestionView.selected.has(s.source_id);
  return `<section class="ingestion-source" data-ingestion-source="${id}"><div class="between wrap"><h3>${esc(s.name)} · ${esc(s.adapter_name)}</h3><label class="ingestion-select"><input type="checkbox" data-ingestion-select="${id}" ${selected?'checked':''}> 选择此来源用于批量操作</label></div><form data-form="ingestion-config" data-id="${id}"><div class="ingestion-controls"><label><input type="checkbox" name="enabled" ${d.enabled?'checked':''}> 启用持续采集</label><label>巡检间隔（小时）<input type="number" min="1" max="720" name="frequency_hours" value="${d.frequency_hours}" required></label><label>纳入规则<select name="inclusion_rule"><option value="research_only" ${d.inclusion_rule==='research_only'?'selected':''}>研究栏目，排除明确事务通知</option><option value="all_opinions" ${d.inclusion_rule==='all_opinions'?'selected':''}>全部当前条目</option></select></label><label>日期回溯窗口（天）<input type="number" min="30" max="3650" name="backfill_days" value="${d.backfill_days}" required></label><button class="button primary" type="submit" ${item.busy?'disabled':''}>保存此来源设置</button></div><p class="small muted" data-ingestion-draft="${id}">${ingestionDirty(item)?'有未保存的修改':'设置已保存'}</p><div class="form-error" role="alert"></div></form><div class="row wrap section-gap"><button class="button" data-action="ingestion-run" data-id="${id}" ${ingestionRunnable(item)?'':'disabled'}>安排此来源立即巡检</button><a class="button" href="${sourceHref(s.source_id)}">查看来源档案</a></div><p class="small" data-ingestion-result="${id}" role="status">${esc(item.result||'')}</p><div data-ingestion-status="${id}">${ingestionRunsHtml(s)}</div></section>`;
}
function ingestionUnavailableHtml(view){return `${view.unavailable.length?`<details class="section-gap"><summary>未接入固定采集的来源（${view.unavailable.length}）</summary><p class="small muted">这些来源不在全选或批量操作范围内。</p><ul>${view.unavailable.map(s=>`<li>${esc(s.name)}：${esc(s.reason)}</li>`).join('')}</ul></details>`:''}`;}
function ingestionCardHtml(view){
  const available=[...view.items.values()],selected=[...view.selected],runnable=selected.filter(id=>ingestionRunnable(view.items.get(id))).length;
  return `<section class="system-card ingestion-card" aria-labelledby="ingestion-heading"><div class="between wrap"><h2 id="ingestion-heading">公开来源自动采集</h2><button class="button" data-action="ingestion-refresh" ${view.refreshing?'disabled':''}>刷新状态（保留草稿）</button></div><p>启用后由独立后台持续运行。默认每日、首轮最近30天；可明确扩大当前响应的日期回溯窗口。新建文章自动排一次作者候选，仍须人工采用；中文或AI暂停不妨碍公开采集。</p><p class="small muted" data-ingestion-heartbeat>后台最近心跳：${view.heartbeat?dateTime(view.heartbeat):'未检测到，请按运行说明启动采集后台'}</p><div class="ingestion-batch" aria-label="采集来源批量操作"><p class="small">选择范围：下方全部 ${available.length} 个已接入固定采集的来源。勾选“选择此来源”不会改变启用状态。</p><div class="row wrap"><button class="button" data-action="ingestion-all" ${available.length?'':'disabled'}>全选可操作来源</button><button class="button" data-action="ingestion-clear" ${selected.length?'':'disabled'}>清空选择</button><span data-ingestion-count role="status">已选 ${selected.length} 个来源</span></div><p class="small" data-ingestion-selected>${selected.length?'已选：'+esc(selected.map(id=>view.items.get(id).source.name).join('、')):'尚未选择来源'}</p><div class="row wrap"><button class="button" data-action="ingestion-enable" ${selected.length&&!view.batch?'':'disabled'}>启用并保存所选</button><button class="button" data-action="ingestion-disable" ${selected.length&&!view.batch?'':'disabled'}>停用并保存所选</button><button class="button primary" data-action="ingestion-save" ${selected.length&&!view.batch?'':'disabled'}>保存所选设置</button><button class="button" data-action="ingestion-poll" ${runnable&&!view.batch?'':'disabled'}>巡检所选可用来源（${runnable}）</button></div><p class="small muted" data-ingestion-help>启用／停用会一并保存所选来源当前设置。巡检仅安排已保存、已启用且无未保存修改的来源；每项结果在对应来源下显示。</p><p class="small" data-ingestion-summary role="status">${esc(view.summary)}</p></div><div data-ingestion-unavailable>${ingestionUnavailableHtml(view)}</div><div data-ingestion-sources data-ingestion-source-ids="${esc(available.map(item=>item.source.source_id).join(','))}">${available.map(ingestionSourceHtml).join('')||'<p>尚未登记支持固定采集的来源；请核对既有来源官网后另行接入。</p>'}</div></section>`;
}
async function ingestionSystemCard(){
  if(state.me?.role!=='admin')return '';
  return ingestionCardHtml(ingestionAccept(await api('/api/ingestion')));
}
function ingestionForm(id){return document.querySelector('[data-form="ingestion-config"][data-id="'+id+'"]');}
function ingestionPaint(view=ingestionView){
  if(!view||view!==ingestionView||state.me?.id!==view.actor)return;
  const root=document.querySelector('.ingestion-card');if(!root)return;
  const unavailable=root.querySelector('[data-ingestion-unavailable]');
  if(unavailable&&unavailable.ingestionItems!==view.unavailable){const opened=unavailable.querySelector('details')?.open;unavailable.innerHTML=ingestionUnavailableHtml(view);if(opened&&unavailable.querySelector('details'))unavailable.querySelector('details').open=true;unavailable.ingestionItems=view.unavailable;}
  const sources=root.querySelector('[data-ingestion-sources]'),sourceIds=[...view.items.keys()].join(',');
  if(sources?.dataset&&sources.dataset.ingestionSourceIds!==sourceIds){sources.innerHTML=[...view.items.values()].map(ingestionSourceHtml).join('')||'<p>尚无支持固定采集的来源。</p>';sources.dataset.ingestionSourceIds=sourceIds;}
  const selected=[...view.selected].filter(id=>view.items.has(id)),runnable=selected.filter(id=>ingestionRunnable(view.items.get(id))).length;
  const text=(selector,value)=>{const node=root.querySelector(selector);if(node)node.textContent=value;};
  const disabled=(action,value)=>{const node=root.querySelector('[data-action="ingestion-'+action+'"]');if(node)node.disabled=value;};
  text('[data-ingestion-count]','已选 '+selected.length+' 个来源');
  text('[data-ingestion-selected]',selected.length?'已选：'+selected.map(id=>view.items.get(id).source.name).join('、'):'尚未选择来源');
  text('[data-ingestion-summary]',view.summary);
  text('[data-action="ingestion-poll"]','巡检所选可用来源（'+runnable+'）');
  disabled('clear',!selected.length);disabled('all',![...view.items.values()].some(item=>!item.busy));
  for(const action of ['enable','disable','save'])disabled(action,!selected.some(id=>!view.items.get(id).busy)||view.batch);
  disabled('poll',!runnable||view.batch);disabled('refresh',view.refreshing);
  text('[data-ingestion-heartbeat]','后台最近心跳：'+(view.heartbeat?dateTime(view.heartbeat):'未检测到，请按运行说明启动采集后台'));
  for(const [id,item] of view.items){
    const form=ingestionForm(id);
    if(form){
      for(const key of ingestionFields){const input=form.elements[key];if(key==='enabled')input.checked=item.draft[key];else if(String(input.value)!==String(item.draft[key]))input.value=item.draft[key];}
      form.querySelector('[type=submit]').disabled=!!item.busy;
      form.querySelector('.form-error').textContent=item.error||'';
    }
    text('[data-ingestion-draft="'+id+'"]',ingestionDirty(item)?'有未保存的修改':'设置已保存');
    text('[data-ingestion-result="'+id+'"]',item.result||'');
    const pick=root.querySelector('[data-ingestion-select="'+id+'"]');if(pick){pick.checked=view.selected.has(id);pick.disabled=!!item.busy;}
    const run=root.querySelector('[data-action="ingestion-run"][data-id="'+id+'"]');if(run)run.disabled=!ingestionRunnable(item);
    const status=root.querySelector('[data-ingestion-status="'+id+'"]');
    if(status&&status.ingestionSource!==item.source){status.innerHTML=ingestionRunsHtml(item.source);status.ingestionSource=item.source;}
    for(const retry of root.querySelectorAll('[data-ingestion-source="'+id+'"] [data-action="ingestion-retry"]'))retry.disabled=!!item.busy||!item.saved.enabled;
  }
}
function ingestionReadForm(form){
  if(!ingestionView)return;
  const item=ingestionView.items.get(form.dataset.id);if(!item)return;
  const number=key=>form.elements[key].value===''?'':Number(form.elements[key].value);
  item.draft={enabled:form.elements.enabled.checked,frequency_hours:number('frequency_hours'),inclusion_rule:form.elements.inclusion_rule.value,backfill_days:number('backfill_days')};
}
async function ingestionExecute(ids,action,runId){
  const view=ingestionView;if(!view||state.me?.id!==view.actor)return;
  const jobs=ids.filter(id=>view.items.has(id)&&!view.items.get(id).busy).map(id=>{
    const item=view.items.get(id),form=ingestionForm(id);if(form)ingestionReadForm(form);
    return {id,item,form,body:{...item.draft}};
  }).filter(job=>action!=='run'||ingestionRunnable(job.item));
  if(!jobs.length)return;
  if(action==='enable'||action==='disable')for(const job of jobs){job.body.enabled=action==='enable';job.item.draft.enabled=job.body.enabled;}
  for(const job of jobs){job.item.busy=true;job.item.revision=(job.item.revision||0)+1;}
  view.summary='正在处理 '+jobs.length+' 个来源…';ingestionPaint(view);
  let succeeded=0,failed=0;
  for(const job of jobs){
    const {id,item,form,body}=job,save=['save','enable','disable'].includes(action),key=action+':'+(runId||id);
    item.error='';item.result=save?'正在保存设置…':'正在安排后台任务…';ingestionPaint(view);
    try{
      if(save&&form&&!form.reportValidity())throw new Error('请修正此来源的参数后重新保存。');
      if(!save&&!view.tokens.has(key)){view.tokens.set(key,crypto.randomUUID());ingestionKeepRequests(view);}
      const result=await api(action==='retry'?'/api/ingestion/runs/'+encodeURIComponent(runId)+'/retry':'/api/sources/'+encodeURIComponent(id)+'/ingestion'+(save?'':'/run'),{method:save?'PUT':'POST',body:save?body:{request_id:view.tokens.get(key)}});
      const previous=item.saved;item.source={...item.source,...result};item.saved=ingestionValues(result);
      // Responses update the saved baseline, while newer per-field edits stay drafts.
      for(const field of ingestionFields)if(item.draft[field]===(save?body[field]:previous[field]))item.draft[field]=item.saved[field];
      view.tokens.delete(key);ingestionKeepRequests(view);
      item.result=save?'设置已保存'+(ingestionDirty(item)?'；仍有新修改待保存':''):(result.runs.some(run=>['queued','running'].includes(run.status))?'任务已安排，等待后台执行':'此请求已处理，未重复安排任务；查看下方巡检结果');succeeded++;
    }catch(error){item.error=error.message;item.result=(save?'保存失败':'安排失败')+'：'+error.message+'；输入和选择已保留，可重试。';failed++;}
    finally{item.busy=false;ingestionPaint(view);}
  }
  view.summary='本次 '+jobs.length+' 个来源：成功 '+succeeded+'，失败 '+failed+'。'+(failed?'失败项保留输入，请在对应来源重试。':'');ingestionPaint(view);
}
async function ingestionRefresh(){
  const view=ingestionView;if(!view||view.refreshing)return;
  const revisions=new Map([...view.items].map(([id,item])=>[id,item.revision]));
  const drafts=new Map([...view.items].map(([id,item])=>[id,item.draft]));
  view.refreshing=true;ingestionPaint(view);
  try{
    const data=await api('/api/ingestion');if(view!==ingestionView||state.me?.id!==view.actor)return;
    // Merge against the current draft, including edits made while the request waited.
    ingestionAccept(data,revisions,drafts);view.summary='状态已刷新，未保存的修改和选择已保留。';
  }catch(error){view.summary='刷新失败：'+error.message+'；当前输入和选择已保留。';}
  finally{view.refreshing=false;ingestionPaint(view);}
}
function automaticAcquisitionHtml(acquired){
  if(!acquired)return '';
  return `<section class="detail-section acquisition-reading"><h3>自动取得与原文快照</h3><p>系统取得，尚未人工核对。中文待处理；原始摘要缺项保持缺项。</p>${acquired.snapshots.map((s,i)=>`<details ${i===acquired.snapshots.length-1?'open':''}><summary>${s.work_body_available?'作品HTML正文快照':'网页说明／原摘要快照'} · ${dateTime(s.retrieved_at)}${s.content_kind==='no_body'?' · 无可辨认正文':''}</summary><p>${s.work_body_available?'已取得文章HTML正文，仍须核对原站及适用范围。':s.content_kind==='no_body'?'未辨认网页正文；未取得所指作品全文。':'仅网页说明或原摘要；PDF链接不表示已下载或保全全文。'}</p><div class="reading-content">${s.page_html}</div><div class="row wrap">${externalLink(s.url,'查看原站')}${(s.pdf_links||[]).map(url=>externalLink(url,'官方PDF链接（未下载）')).join('')}</div><details class="acquisition-basis"><summary>取得依据</summary><p>${esc(s.reason)}</p><p class="small muted">页面原署名：${esc(s.sidebar_credit||'未取得')}；与正文中的作者、发言者或制作角色分别理解。</p><p class="small">SHA256：<span class="snapshot-hash">${esc(s.sha256)}</span> · ${s.bytes.toLocaleString()} 字节 · ${esc(s.adapter)}</p><a class="button tiny" href="${esc(s.download_url)}" download>下载原始页面字节</a>${s.metadata?`<details><summary>文章题录、原日期与逐作者标识</summary><pre>${esc(JSON.stringify({fields:s.metadata.fields,authors:s.metadata.authors,date_fields:s.metadata.raw?.date_fields,displayed_date:s.metadata.raw?.displayed_date,provenance:s.metadata.provenance,warnings:s.metadata.warnings},null,2))}</pre></details>`:""}</details></details>`).join('')||'<p>尚无成功取得的网页快照；可以先读题录和原文链接，维护者可重跑取得。</p>'}<details><summary>取得尝试记录</summary><pre>${esc(JSON.stringify(acquired.attempts,null,2))}</pre></details></section>`;
}
function automaticProcessingHtml(record){
  const summary=record.machine_summary,classification=record.machine_classification,tasks=record.automatic_tasks||[];
  if(!tasks.length)return '';
  const certainty={supported:'有据机器分类',uncertain:'不确定，未用于筛选'};
  return '<section class="detail-section automatic-processing"><h3>中文整理与内容依据</h3>'
    +(summary?'<section class="machine-overview"><h3>机器概述 · 非原始摘要</h3><p class="prose">'+esc(summary.summary)+'</p><details><summary>原文版本与引文定位</summary><p>快照 '+esc(record.machine_summary_basis.snapshot_id)+' · '+esc(record.machine_summary_basis.body_basis)+'</p>'+summary.citations.map(c=>'<blockquote>'+esc(c.quote)+'</blockquote><p class="small">正文字符 '+c.start+'—'+c.end+'（终点不含）</p>').join('')+'</details></section>':'')
    +(classification?'<details><summary>研究对象、主题与类型的机器依据</summary><p>当前研究对象：'+esc(record.subject_countries||'未知')+'；主题：'+esc(record.subject_topics||'待分类')+'。人工登记优先；来源所在地单独理解。</p>'+[...classification.countries,...classification.topics,...(classification.type?[classification.type]:[])].map(c=>'<p><strong>'+esc(c.value)+'</strong> · '+esc(certainty[c.certainty])+'</p><blockquote>'+esc(c.quote)+'</blockquote><p class="small">依据字段：'+esc(c.field)+'</p>').join('')+'</details>':'')
    +(tasks.some(t=>!t.stale&&['queued','running','paused','failed'].includes(t.status))?'<p class="small muted">部分中文整理待处理；原始资料仍可阅读，维护者可查看处理状态。</p>':'')
    +'<details><summary>自动处理版本与来历</summary>'+tasks.map(t=>'<p>'+esc({translation:'题名及原摘要翻译',classification:'内容分类',summary:'正文机器概述'}[t.task]||t.task)+' · '+esc({queued:'等待后台',running:'后台处理中',paused:'暂停待恢复',failed:'需维护者处理',succeeded:'已完成'}[t.status]||t.status)+(t.stale?' · 已有更新输入':'')+' · '+esc(t.rule_version)+'</p><p class="small">'+esc(t.reason)+'</p><p class="small">输入 '+esc(t.input_hash)+' · 所据资料版本 '+t.source_version+'</p>').join('')+'</details></section>';
}
for(const type of ['input','change'])document.addEventListener(type,event=>{
  const input=event.target,form=input.closest('[data-form="ingestion-config"]');
  if(form){ingestionReadForm(form);ingestionPaint();return;}
  if(type==='change'&&input.dataset?.ingestionSelect&&ingestionView){
    const id=input.dataset.ingestionSelect;if(!ingestionView.items.has(id)||ingestionView.items.get(id).busy)return;
    if(input.checked)ingestionView.selected.add(id);else ingestionView.selected.delete(id);ingestionPaint();
  }
});
document.addEventListener('submit',async event=>{
  const form=event.target.closest('[data-form="ingestion-config"]');if(!form)return;
  event.preventDefault();await ingestionExecute([form.dataset.id],'save');
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action^="ingestion-"]');if(!button||button.disabled||!ingestionView)return;
  const action=button.dataset.action,view=ingestionView;
  if(action==='ingestion-all'){for(const [id,item] of view.items)if(!item.busy)view.selected.add(id);ingestionPaint();return;}
  if(action==='ingestion-clear'){view.selected.clear();ingestionPaint();return;}
  if(action==='ingestion-refresh'){await ingestionRefresh();return;}
  if(action==='ingestion-run'){await ingestionExecute([button.dataset.id],'run');return;}
  if(action==='ingestion-retry'){
    const id=button.closest('[data-ingestion-source]').dataset.ingestionSource;
    await ingestionExecute([id],'retry',button.dataset.id);return;
  }
  const bulk={ 'ingestion-enable':'enable','ingestion-disable':'disable','ingestion-save':'save','ingestion-poll':'run'}[action];
  if(!bulk||view.batch)return;
  view.batch=true;try{await ingestionExecute([...view.selected],bulk);}finally{view.batch=false;ingestionPaint(view);}
});
