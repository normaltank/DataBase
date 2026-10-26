const citationStances={unclassified:'未分类',supports:'支撑',contradicts:'反例',qualifies:'限定',background:'背景'};
const citationReasons={note_updated:'笔记已修订',original_updated:'原文已修订',original_merged:'原文已合并转向',identity_changed:'署名、文章单位或笔记研究对象关系有变化'};
function citationReview(c){return '<p><strong>引用用途：'+esc(citationStances[c.stance]||'未分类')+'</strong></p>'+(c.claim_note?'<p class="prose">所涉判断与说明：'+esc(c.claim_note)+'</p>':'')+((c.staleness_reasons||[]).length?'<p class="notice">有变更待评估：'+c.staleness_reasons.map(r=>esc(citationReasons[r]||r)).join('；')+'</p>':'')+(c.identity_changes||[]).map(d=>'<p class="form-help">'+esc(({bylines:'原文署名',article_affiliations:'文章署名单位',subjects:'笔记研究对象'})[d.scope]||d.scope)+'：'+(d.change==='endpoints_or_status'?'当前端点或确认状态已改变':'关系历史已有修订（当前端点及状态相同）')+'</p>').join('')+(c.identity_baseline_status==='unknown'?'<p class="form-help">历史未记录完整身份基线，无法自动比较。</p>':'');}
function groupedCitations(citations,render){return Object.entries(citationStances).map(([role,label])=>{const items=citations.filter(c=>(c.stance||'unclassified')===role);return items.length?'<section class="citation-group"><h4>'+esc(label)+'</h4>'+items.map(render).join('')+'</section>':'';}).join('');}
function citationScopeNotice(citations){const roles=new Set(citations.map(c=>c.stance||'unclassified'));return roles.has('unclassified')?'当前可见引用中有未分类用途，反例与限定的登记情况未知。':roles.size===1&&roles.has('supports')?'当前可见的已登记引用中未登记反例或限定；这不表示现实中不存在相反材料。':'';}
'use strict';

async function mergeChoices(type,q='') {
  const d=await api(type==='source'?'/api/sources?q='+encodeURIComponent(q):'/api/records?size=100&q='+encodeURIComponent(q));
  return d.items.map(r=>({id:r.id,name:r.name||r.title}));
}
async function duplicatesView(type='record') {
  const [result,choices]=await Promise.all([api('/api/duplicates?type='+type),mergeChoices(type)]);
  const options=Object.fromEntries(choices.map(r=>[r.id,r.name+' · '+r.id]));
  modal(type==='source'?'整理重复来源':'整理重复资料','<p class="muted">先比较内容与关联，再人工确认保留哪条记录。</p><form data-form="merge-choice" data-type="'+type+'" class="section-gap"><div class="field"><label for="merge-query">查找需要比较的记录</label><div class="row"><input id="merge-query" name="q" placeholder="题名、名称或编号"><button class="button" type="button" data-action="merge-search">查找</button></div></div><div class="form-grid section-gap">'+selectField('keep_id','保留的主记录',options)+selectField('duplicate_id','待合并记录',options)+'</div><div class="form-error" role="alert"></div><button type="submit" class="button primary section-gap">比较与查看影响</button></form><section class="detail-section"><h3>疑似重复</h3>'+(result.limited?'<p class="notice">候选较多，以下是本次扫描结果，可用上方查找补充比较。</p>':'')+(result.items.map(pair=>'<article class="duplicate-card"><h4>'+esc(pair.keep.name)+'</h4><p>'+esc(pair.duplicate.name)+'</p><p class="muted">'+esc(pair.reason)+'</p><button class="button tiny" data-action="compare-duplicate" data-type="'+type+'" data-keep="'+esc(pair.keep.id)+'" data-duplicate="'+esc(pair.duplicate.id)+'">比较这两条</button></article>').join('')||'<p class="muted">暂未发现疑似重复，可手动选择两条记录。</p>')+'</section>');
}
function readableField(value){if(typeof value==='string'){try{const decoded=JSON.parse(value);if(Array.isArray(decoded))return decoded.map(v=>typeof v==='object'?Object.values(v).join(' · '):v).join('；');}catch{}return value;}return Array.isArray(value)?value.join('；'):String(value??'');}
function mergeSide(r) {
  const labels={id:'稳定编号',kind:'类型',original_name:'原名',original_title:'原题名',authors:'署名',aliases:'其他名称',coverage:'覆盖范围',country:'国家',host_id:'主办方',publisher_id:'出版方',website:'官网',doi:'DOI',issn:'ISSN',published_on:'日期',visibility:'可见范围',owner_id:'提交者编号',author_id:'负责作者编号',author_confirmed:'作者已确认',editors:'获授权成员',attachment_ids:'附件编号',relationships:'机构关系',abstract:'摘要',notes:'备注',research_question:'研究问题',stage_judgment:'阶段判断',quote:'原文摘录',translation:'译文',interpretation:'研究说明',locator:'位置',evidence_version:'原文版本'};
  return '<h3>'+esc(r.name||r.title)+'</h3><p class="muted">版本 '+r.version+'</p><dl class="comparison-fields">'+Object.entries(labels).filter(([k])=>r[k]!==undefined&&r[k]!==''&&r[k]!==null).map(([k,l])=>detailPair(l,esc(k==='kind'?(kinds[r[k]]||sourceKinds[r[k]]||r[k]):readableField(r[k])))).join('')+'</dl><h4>正文 / 介绍</h4><div class="rich-prose">'+readRich(r.body_html||r.introduction_html||r.comparison_html)+'</div>';
}
async function mergePreview(type,keepId,duplicateId) {
  const result=await api('/api/merge/preview',{method:'POST',body:{type,keep_id:keepId,duplicate_id:duplicateId}});
  modal('合并前比较','<p class="notice">'+esc(result.explanation)+'</p><div class="comparison-grid merge-comparison"><section><div class="badge blue">保留主记录</div>'+mergeSide(result.keep)+'</section><section><div class="badge pending">归档并转接的记录</div>'+mergeSide(result.duplicate)+'</section></div><button type="button" class="button" data-action="swap-merge">交换保留方向</button><section class="detail-section"><h3>将转接的关联</h3><dl class="detail-grid">'+Object.entries(result.impact).map(([key,value])=>detailPair(esc(key),esc(value))).join('')+'</dl></section><form data-form="merge-confirm"><div class="form-error" role="alert"></div>'+(result.allowed?'<label class="check-label"><input type="checkbox" name="confirmed" required>已核对上述两条及影响，确认保留左侧主记录并归档另一条。</label><div class="form-actions"><button type="button" class="button" data-action="close">取消</button><button type="submit" class="button primary">确认合并</button></div>':'<p class="notice error">'+esc(result.blocked_reason)+'</p>')+'</form>');
  document.querySelector('[data-form=merge-confirm]')._preview=result;
}
function archivedLinks(kind,r){return (r.previous_ids||[]).length?'<section class="detail-section"><h3>合并前编号与内容</h3>'+(r.previous_ids||[]).map(id=>'<button class="detail-link" data-action="view-archived" data-type="'+kind+'" data-id="'+esc(id)+'">'+esc(id)+' · 查看合并前内容</button>').join('')+'</section>':'';}
async function archivedView(kind,id){const d=await api('/api/merged/'+kind+'/'+encodeURIComponent(id));modal('合并前内容（只读）','<p class="notice">旧编号 '+esc(id)+' 现指向 '+esc(d.current_id)+'。</p>'+mergeSide(d.archived)+'<div class="detail-actions">'+linkButton('返回当前记录',kind==='source'?'source-detail':'detail',d.current_id)+'</div>');}

async function allVisibleNotes() {
  const rows=[];let page=1,total=1;while(rows.length<total){const d=await api('/api/records?kind=research_note&size=100&page='+page++);rows.push(...d.items);total=d.total;if(!d.items.length)break;}return rows;
}
async function enhanceEvidenceForm(form,r,evidenceId='') {
  const notes=await allVisibleNotes();if(!form.isConnected)return;
  const existing=(r.evidence_citations||[]).map(c=>c.excerpt_id);
  const noteSection=document.createElement('section');noteSection.className='wide evidence-editor';noteSection.dataset.evidenceEditor='';
  noteSection.innerHTML='<h3>摘录出处（可选）</h3><div class="field"><label for="evidence-search">查找原始资料</label><div class="row"><input id="evidence-search" placeholder="题名、作者或编号"><button class="button" type="button" data-action="evidence-original-search">查找</button></div></div><div data-evidence-results></div><input type="hidden" name="evidence_record_id" value="'+esc(r.evidence_record_id||evidenceId)+'"><div data-evidence-origin class="notice section-gap" hidden></div>'
    +textField('quote','原文摘录',r.quote)+textField('translation','我的译文',r.translation)+textField('interpretation','研究说明 / 解释',r.interpretation)+inputField('locator','页码 / 段落 / 其他定位',r.locator,'例如：第 12 页，第 2 段',true)+inputField('evidence_url','原文位置链接',r.evidence_url,'https://…',true,'url')+selectField('evidence_attachment_id','所据附件',{},r.evidence_attachment_id,'未选择附件',true)
    +(r.id?'<label class="check-label"><input type="checkbox" name="refresh_evidence">将所据原文更新到当前版本（会形成新修订）</label>':'');
  const citations=document.createElement('section');citations.className='wide evidence-picker';citations.dataset.evidencePicker='';
  citations.innerHTML='<h3>引用研究笔记 / 摘录</h3><p class="form-help">每份笔记在本报告登记一个主要用途；说明可写具体判断与适用范围。用途由成员选择，不代表系统评价材料。</p><div class="source-picker"><input type="search" data-source-picker-search aria-label="筛选研究证据" placeholder="筛选笔记或摘录"><div class="source-pick-list">'+notes.filter(n=>n.id!==r.id).map(n=>{
    const saved=(r.evidence_citations||[]).find(c=>c.excerpt_id===n.id);
    return '<div data-source-choice="'+esc((n.title+' '+n.authors).toLowerCase())+'"><label class="check-label"><input type="checkbox" name="evidence_ids" value="'+esc(n.id)+'" '+(saved?'checked':'')+'><span>'+esc(n.title)+' · 当前 v'+n.version+'</span></label><div data-citation-context '+(saved?'':'hidden')+'>'+selectField('citation_stance_'+n.id,'引用用途',citationStances,saved?.stance||'background')+textField('citation_claim_'+n.id,'所涉判断与说明',saved?.claim_note||'')+'</div></div>';
  }).join('')+'</div></div><p class="form-help">保留引用时版本；笔记以后修改不会悄悄替换本报告的依据。原文、身份或笔记变化仅提示待评估。</p>'+(r.id&&existing.length?'<label class="check-label"><input type="checkbox" name="refresh_citations">明确更新所选笔记为当前版本（笔记仍固定旧原文时，原文提示继续保留）</label>':'');
  form.querySelector('[data-rich-field=body_html]').before(noteSection,citations);
  if(r.evidence_record_id||evidenceId)await setEvidenceOriginal(form,r.evidence_record_id||evidenceId,r.evidence_attachment_id,r.evidence_version);
  if(Number.isInteger(r.evidence_occurrence)){
    const occurrence=document.createElement('input');occurrence.type='hidden';occurrence.name='evidence_occurrence';occurrence.value=String(r.evidence_occurrence);noteSection.append(occurrence);
    for(const name of ['quote','locator','evidence_attachment_id'])form.elements[name].addEventListener('input',()=>occurrence.remove());
  }
  updateEvidenceMode(form);
}
function updateEvidenceMode(form){const kind=form.elements.kind.value;const note=form.querySelector('[data-evidence-editor]'),citations=form.querySelector('[data-evidence-picker]');if(note){note.hidden=kind!=='research_note';citations.hidden=!['compilation','research_report'].includes(kind);}}
async function setEvidenceOriginal(form,id,attachment='',version=null) {
  const r=await api('/api/records/'+encodeURIComponent(id));if(!form.isConnected)return;
  form.elements.evidence_record_id.value=r.id;
  form.querySelector('[data-evidence-origin]').hidden=false;
  form.querySelector('[data-evidence-origin]').innerHTML='<strong>'+esc(r.title)+'</strong><p>所据版本 '+(version||r.version)+' · '+esc(r.authors)+'</p>';
  const options=Object.fromEntries((r.attachments||[]).map(a=>[a.id,a.name]));if(attachment&&!options[attachment])options[attachment]='历史引用附件';
  form.elements.evidence_attachment_id.innerHTML=selectOptions(options,attachment,'未选择附件');
  form.querySelector('[data-evidence-results]').innerHTML='';
}
async function prepareEvidenceDraft(form,values){if(values.evidence_record_id&&form.querySelector('[data-evidence-editor]')){try{await setEvidenceOriginal(form,values.evidence_record_id,values.evidence_attachment_id,form._editing.original.evidence_version);}catch(error){form.querySelector('.form-error').textContent=error.message+' 草稿输入继续保留。';}}}
function evidenceSnapshotData(note) {
  let snapshot=note.evidence_snapshot??note.evidence_snapshot_json;
  if(typeof snapshot==='string'){try{snapshot=JSON.parse(snapshot);}catch{return {};}}
  return snapshot&&typeof snapshot==='object'&&!Array.isArray(snapshot)?snapshot:{};
}
function attachmentAnchorDetail(snapshot) {
  const anchor=snapshot.attachment_anchor;
  if(!anchor)return '<p class="form-help">历史未记录附件锚点，无法自动检查当时的文件与位置。</p>';
  const status=anchor.quote_match||{},labels={matched:'已在指定位置的提取文字中匹配',not_matched:'未在指定位置的提取文字中匹配',unchecked:'无法检查指定位置的提取文字'};
  const reasons={at_location:'规范化空白后匹配',quote_not_at_location:'该位置未找到相同原句（跨段等情况可手工核对）',location_not_found:'索引未记录该位置（跨段等情况可手工核对）',unindexed:'尚无有效索引',empty:'无可提取文字',unsupported:'格式不支持',limit:'超过提取限制',failed:'提取失败',missing:'文件缺失',file_mismatch:'文件字节与登记摘要不一致'};
  return '<section class="section-gap attachment-anchor"><h4>引用附件锚点</h4><p>'+esc(labels[status.status]||'无法检查指定位置的提取文字')+' · '+esc(reasons[status.reason]||status.reason||'未记录原因')+'</p><p class="form-help">提取文字匹配与文件摘要只供核对，不证明材料真实、身份或研究结论。</p><dl class="detail-grid">'+[['附件',anchor.name],['附件编号',anchor.id],['字节数',anchor.bytes],['SHA-256',anchor.sha256],['固定位置',anchor.locator],['前文',anchor.context_prefix||'未取得'],['后文',anchor.context_suffix||'未取得']].map(([label,value])=>detailPair(label,esc(value))).join('')+'</dl></section>';
}
function originalSnapshotDetail(note) {
  const snapshot=evidenceSnapshotData(note),missing='<span class="muted">该快照未记录</span>';
  const value=text=>text!==null&&text!==undefined&&String(text).trim()?esc(text):missing;
  // Fall back only to the reference saved with this note, never to current source metadata.
  const fields=[['所据题名',snapshot.title],['原文作者',snapshot.authors],['原文日期',snapshot.published_on],['稳定编号',snapshot.id||note.evidence_record_id],['引用时版本',snapshot.version??note.evidence_version]];
  if(snapshot.original_title&&snapshot.original_title!==snapshot.title)fields.push(['原题名',snapshot.original_title]);
  if(snapshot.doi)fields.push(['DOI',snapshot.doi]);
  const url=safeUrl(snapshot.url),body=typeof snapshot.body_html==='string'?snapshot.body_html.trim():'';
  return '<details class="section-gap" data-evidence-snapshot><summary>引用时的原始资料快照</summary><p class="form-help section-gap">以下为引用时保存的信息。</p><dl class="detail-grid">'+fields.map(([label,text])=>detailPair(label,value(text))).join('')+detailPair('原文链接',url?externalLink(snapshot.url,snapshot.url,'link-button'):'<span class="muted">该快照无可用原文链接</span>')+'</dl>'
    +(body?'<h4>正文（引用时）</h4><div class="rich-prose">'+readRich(body)+'</div>':'<p class="prose">此快照未保存原文正文。</p>')
    +(snapshot.abstract?'<h4 class="section-gap">摘要（引用时）</h4><p class="prose">'+esc(snapshot.abstract)+'</p>':'')+'</details>';
}
function evidenceDetail(r) {
  let html='';
  if(!isResearchContent(r.kind))html+='<section class="detail-section"><div class="between wrap"><h3>研究摘录</h3>'+linkButton(icon('plus')+' 保存一段摘录','new-excerpt',r.id,'button primary')+'</div>'+((r.excerpts||[]).map(n=>linkButton(esc(n.title),'detail',n.id,'detail-link')).join('')||'<p class="muted section-gap">尚无可见摘录。</p>')+'</section>';
  if(r.evidence_record_id){const snap=evidenceSnapshotData(r);html+='<section class="detail-section"><h3>摘录与出处</h3><dl class="detail-grid">'+detailPair('原始资料',linkButton(esc(snap.title||r.evidence_record_id),'detail',r.evidence_record_id,'link-button'))+detailPair('引用时版本',esc(r.evidence_version))+detailPair('位置',esc(r.locator))+'</dl><h4>原文摘录</h4><blockquote class="quote-text">'+esc(r.quote)+'</blockquote>'+(r.translation?'<h4>我的译文</h4><p class="prose section-gap">'+esc(r.translation)+'</p>':'')+(r.interpretation?'<h4 class="section-gap">研究说明 / 解释</h4><p class="prose section-gap">'+esc(r.interpretation)+'</p>':'')+'<div class="detail-actions">'+(r.evidence_url?externalLink(r.evidence_url,'前往原文位置'):'')+(r.evidence_file_url?'<a class="button tiny" href="'+esc(r.evidence_file_url)+'">下载所据附件</a>':'')+'</div>'+attachmentAnchorDetail(snap)+originalSnapshotDetail(r)+'</section>';}
  if((r.evidence_citations||[]).length)html+='<section class="detail-section"><h3>报告引用的证据</h3><p class="form-help">'+esc(citationScopeNotice(r.evidence_citations))+'</p>'+groupedCitations(r.evidence_citations,c=>{const s=c.snapshot||{};return '<article class="citation-card"><h4>'+esc(s.title)+'</h4>'+citationReview(c)+'<p class="muted">引用笔记 v'+c.excerpt_version+' · 当前 v'+c.current_version+'</p><p>原文位置：'+esc(s.locator||'笔记内详述')+'</p>'+(s.quote?'<blockquote class="quote-text">'+esc(s.quote)+'</blockquote>':'')+(s.translation?'<p class="prose"><strong>译文：</strong>'+esc(s.translation)+'</p>':'')+(s.interpretation?'<p class="prose"><strong>研究说明：</strong>'+esc(s.interpretation)+'</p>':'')+(s.body_html?'<div class="rich-prose">'+readRich(s.body_html)+'</div>':'')+(s.evidence_record_id?attachmentAnchorDetail(evidenceSnapshotData(s))+originalSnapshotDetail(s):'')+'<div class="detail-actions">'+linkButton('查看当前笔记','detail',c.excerpt_id)+(s.evidence_record_id?linkButton('查看当前原始资料','detail',c.current_original_id||s.evidence_record_id):'')+'</div></article>';})+'</section>';
  return html+archivedLinks('record',r);
}
async function workflowHistory(kind,id) {
  const [history,current]=await Promise.all([api('/api/history/'+kind+'/'+encodeURIComponent(id)),api('/api/'+(kind==='record'?'records':'sources')+'/'+encodeURIComponent(id))]);state.detail={type:kind,data:current};
  modal('修改历史','<p class="muted">恢复形成新版本，当前作者身份与授权保持不变。</p><div class="section-gap">'+history.items.map((r,i)=>'<article class="history-row"><div><strong>版本 '+r.version+' · '+esc(r.action)+'</strong><p>'+esc(r.actor_name)+' · '+dateTime(r.created_at)+'</p>'+(r.target_id&&r.target_id!==current.id?'<p>合并前编号：'+esc(r.target_id)+'</p>':'')+'</div><div class="row wrap"><button class="button tiny" data-action="history-snapshot" data-id="'+r.id+'">查看内容</button>'+(i===0?'<span class="badge verified">最新修订</span>':r.restorable!==false&&(kind==='record'?current.can_edit:true)?'<button class="button tiny" data-action="restore" data-id="'+r.id+'">恢复此版本</button>':'')+'</div></article>').join('')+'</div><section data-history-snapshot class="detail-section" hidden></section>');
}
document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-action]');if(!b)return;
  try{
    if(b.dataset.action==='duplicates')await duplicatesView(b.dataset.id||'record');
    else if(b.dataset.action==='merge-search'){const f=b.closest('form'),items=await mergeChoices(f.dataset.type,f.elements.q.value);for(const name of ['keep_id','duplicate_id']){const select=f.elements[name],old=select.value;select.innerHTML=selectOptions(Object.fromEntries(items.map(r=>[r.id,r.name+' · '+r.id])),old);}}
    else if(b.dataset.action==='compare-duplicate')await mergePreview(b.dataset.type,b.dataset.keep,b.dataset.duplicate);
    else if(b.dataset.action==='swap-merge'){const p=document.querySelector('[data-form=merge-confirm]')._preview;await mergePreview(p.type,p.duplicate.id,p.keep.id);}
    else if(b.dataset.action==='view-archived')await archivedView(b.dataset.type,b.dataset.id);
    else if(b.dataset.action==='new-excerpt')await workflowRecordForm('','research_note','excerpt-'+b.dataset.id,'',b.dataset.id);
    else if(b.dataset.action==='evidence-original-search'){const f=b.closest('form'),q=f.querySelector('#evidence-search').value,items=(await api('/api/records?size=30&q='+encodeURIComponent(q))).items.filter(r=>!isResearchContent(r.kind));f.querySelector('[data-evidence-results]').innerHTML=items.map(r=>'<button type="button" class="detail-link" data-action="choose-evidence-original" data-id="'+esc(r.id)+'">'+esc(r.title)+'</button>').join('')||'<p class="muted">没有匹配的原始资料。</p>';}
    else if(b.dataset.action==='choose-evidence-original'){const form=b.closest('form');await setEvidenceOriginal(form,b.dataset.id);form._dirty=true;saveEditorDraft(form,true);}
    else if(b.dataset.action==='history-snapshot'){const d=await api('/api/history/'+b.dataset.id),target=document.querySelector('[data-history-snapshot]');target.hidden=false;target.innerHTML='<h3>'+esc(d.action)+' · '+esc(d.target_id)+'</h3>'+mergeSide(d.snapshot);target.scrollIntoView({block:'start'});}
  }catch(error){const form=b.closest('form');if(form?.querySelector('.form-error'))form.querySelector('.form-error').textContent=error.message;else toast(error.message);}
});
document.addEventListener('submit',async event=>{
  const form=event.target;if(!['merge-choice','merge-confirm'].includes(form.dataset.form))return;event.preventDefault();const button=form.querySelector('[type=submit]'),error=form.querySelector('.form-error');if(button)button.disabled=true;
  try{if(form.dataset.form==='merge-choice'){if(!form.elements.keep_id.value||!form.elements.duplicate_id.value)throw new Error('请选择两条记录。');await mergePreview(form.dataset.type,form.elements.keep_id.value,form.elements.duplicate_id.value);}
    else{const p=form._preview;if(!form.elements.confirmed.checked)throw new Error('请先核对并确认合并。');const result=await api('/api/merge',{method:'POST',body:{type:p.type,keep_id:p.keep.id,duplicate_id:p.duplicate.id,keep_version:p.keep.version,duplicate_version:p.duplicate.version,confirmed:true}});await loadLookups();await route();if(p.type==='source')await openSource(result.id);else await openRecord(result.id);toast('合并完成，旧编号与历史已保留');}
  }catch(e){error.textContent=e.message+(e.status===409?' 请关闭后重新比较。':'');}finally{if(button)button.disabled=false;}
});

document.addEventListener('change',event=>{const input=event.target;if(input.name==='evidence_ids'){const context=input.closest('[data-source-choice]')?.querySelector('[data-citation-context]');if(context)context.hidden=!input.checked;}});
