'use strict';

function relationshipPath(type,id){return type==='employment'?`/api/people/${encodeURIComponent(id)}/employments`:`/api/records/${encodeURIComponent(id)}/affiliations`;}
function relationshipLabel(type){return type==='employment'?'任职经历':'文章署名单位';}
function employmentDates(item){return item.start_date&&item.end_date?`${item.start_date} — ${item.end_date}`:item.start_date?`${item.start_date} 起（结束时间未知）`:item.end_date?`截至 ${item.end_date}（开始时间未知）`:'任职时间未知';}
function relationshipValue(item,type){
  if(!item)return '<p class="muted">此前尚未建立这项关系。</p>';
  const subject=type==='employment'?`${esc(item.role)} · ${esc(employmentDates(item))}`:`署名：${esc(item.byline?.raw_name||item.byline_name||'原署名')} ${item.byline?.removed_at?'（署名已移除）':''}`;
  return `<p><strong>${esc(item.institution?.name||item.institution_name||'机构')}</strong>${item.removed_at?' · 已移除':''}</p><p>${subject}</p><p class="prose small">出处：${esc(item.evidence)}</p>`;
}
function relationshipList(items,type){return items.length?items.map(item=>`<article class="affiliation-card">${relationshipValue(item,type)}</article>`).join(''):'<p class="muted">尚未登记有依据的关系。</p>';}

async function employmentSection(id,source=false){
  const data=await api(source?`/api/sources/${encodeURIComponent(id)}/employments`:relationshipPath('employment',id));
  return `<section class="detail-section person-section employment-section"><div class="between wrap"><h2>${source?'任职人物':'任职经历'}</h2><div class="row wrap">${source?`<button class="button tiny" data-action="employment-person-picker" data-id="${esc(id)}">登记任职人物</button>`:linkButton('维护任职经历','edit-employments',id,'button tiny')}${!source?linkButton('任职历史','employment-history',id):''}</div></div><p class="small muted">依据人物与机构履历登记，已知时间按原有精度保留。</p>${data.items.map(item=>`<article class="affiliation-card">${source?`<a class="detail-link" href="#people?id=${encodeURIComponent(item.person.id)}">${esc(item.person.name)}</a>`:sourceName(item.institution.id)}<p><strong>${esc(item.role)}</strong> · ${esc(employmentDates(item))}</p><p class="prose small">出处：${esc(item.evidence)}</p>${source?`<div class="row wrap"><button class="link-button" data-action="edit-employments" data-id="${esc(item.person.id)}" data-source="${esc(id)}">维护此人任职</button><button class="link-button" data-action="employment-history" data-id="${esc(item.person.id)}" data-source="${esc(id)}">任职历史</button></div>`:''}</article>`).join('')||'<p class="muted">尚未登记任职经历，不能据此推断当前任职情况。</p>'}</section>`;
}
async function articleAffiliationSection(record){
  if(isResearchContent(record.kind))return '';
  const data=await api(relationshipPath('affiliation',record.id));
  return `<section class="detail-section article-affiliation-section"><div class="between wrap"><h3>文章署名单位</h3><div class="row wrap">${linkButton('维护文章单位','edit-affiliations',record.id)}${linkButton('单位历史','affiliation-history',record.id)}</div></div><p class="small muted">本篇作品具体署名中的单位，独立于人物任职与作品发布机构。</p>${data.items.filter(item=>!item.byline.removed_at).map(item=>`<article class="affiliation-card"><p><strong>${esc(item.byline.raw_name)}</strong> · 第 ${item.byline.position} 项署名</p><div class="row wrap">${bylineIdentity(item.byline)}</div><p>${sourceName(item.institution.id)}</p><p class="prose small">出处：${esc(item.evidence)}</p></article>`).join('')||'<p class="muted">尚未登记文章署名单位。</p>'}${data.items.some(item=>item.byline.removed_at)?'<p class="small muted">已移除署名的单位记录仍保留，可在维护列表与历史中整理。</p>':''}</section>`;
}
async function institutionAffiliationsSection(id){
  const data=await api(`/api/sources/${encodeURIComponent(id)}/affiliations`);
  return `<section class="detail-section institution-affiliations"><h2>文章中的署名单位</h2><p class="small muted">${data.total} 项可阅读的具体署名单位记录</p>${data.items.map(item=>`<article class="affiliation-card"><h3>${linkButton(esc(item.record.title),'detail',item.record.id,'title-button')}</h3><p>第 ${item.byline.position} 项署名：${esc(item.byline.raw_name)}</p><div class="row wrap">${bylineIdentity(item.byline)}</div><p class="prose small">出处：${esc(item.evidence)}</p><div class="row wrap"><button class="link-button" data-action="edit-affiliations" data-id="${esc(item.record.id)}" data-source="${esc(id)}">维护这篇文章的单位</button><button class="link-button" data-action="affiliation-history" data-id="${esc(item.record.id)}" data-source="${esc(id)}">单位历史</button></div></article>`).join('')||'<p class="muted">尚无可阅读的署名单位记录。</p>'}</section>`;
}
async function institutionPublishedSection(id,page=1){
  const data=await api(`/api/sources/${encodeURIComponent(id)}/published-works?page=${page}`);
  return `<section class="detail-section institution-published" data-published-source="${esc(id)}"><h2>发布作品</h2><p class="small muted">${data.total} 份可阅读的原始资料登记此机构为发布方</p>${data.items.map(record=>`<article class="affiliation-card"><h3>${linkButton(esc(record.title),'detail',record.id,'title-button')}</h3><p class="small muted">${esc([record.published_on,record.authors].filter(Boolean).join(' · '))}</p></article>`).join('')||'<p class="muted">尚无可阅读的发布作品。</p>'}${data.total>data.size?`<div class="pagination">${page>1?linkButton('上一页','source-published-page',String(page-1)):''}<span>第 ${page} / ${Math.ceil(data.total/data.size)} 页</span>${page*data.size<data.total?linkButton('下一页','source-published-page',String(page+1)):''}</div>`:''}</section>`;
}

let affiliationRowCounter=0;
function affiliationEditorRow(type,item={},data={}){
  const key='affiliation-row-'+(++affiliationRowCounter),institutions=state.sources.filter(isInstitution);
  const choices=[...data.bylines||[]];
  if(item.byline_id&&!choices.some(row=>row.id===item.byline_id))choices.push(item.byline||{id:item.byline_id,raw_name:item.byline_name||'原署名',removed_at:true});
  const options=institutions.map(s=>`<option value="${esc(s.id)}" ${s.id===item.institution_id?'selected':''}>${esc(s.name)}${s.original_name&&s.original_name!==s.name?' · '+esc(s.original_name):''}</option>`).join('');
  const retained=item.institution_id&&!institutions.some(s=>s.id===item.institution_id)?`<option value="${esc(item.institution_id)}" selected>${esc(item.institution?.name||item.institution_name||'原机构（请核查）')}</option>`:'';
  return `<fieldset class="affiliation-editor-row" data-affiliation-row data-id="${esc(item.id||'')}" data-reconfirm="${!!item.reconfirm}"><legend>${type==='employment'?'任职':'署名单位'}</legend><div class="form-grid">${type==='affiliation'?`<div class="field wide"><label for="${key}-byline">本篇作品的具体署名 *</label><select id="${key}-byline" data-affiliation="byline_id" required><option value="">请选择署名</option>${choices.map(row=>`<option value="${esc(row.id)}" ${row.id===item.byline_id?'selected':''}>${esc(row.raw_name)}${row.target?' · '+esc(row.target.name):''}${row.position?' · 第 '+row.position+' 项':''}${row.removed_at?'（已移除）':''}</option>`).join('')}</select></div>`:''}<div class="field"><label for="${key}-search">筛选机构</label><input id="${key}-search" type="search" data-affiliation-filter placeholder="机构名称或原名"></div><div class="field"><label for="${key}-institution">已有机构 *</label><select id="${key}-institution" data-affiliation="institution_id" required><option value="">请选择机构</option>${retained}${options}</select></div>${type==='employment'?`<div class="field wide"><label for="${key}-role">任职角色 *</label><input id="${key}-role" data-affiliation="role" required value="${esc(item.role)}" placeholder="如研究员、顾问"></div><div class="field"><label for="${key}-start">起始时间</label><input id="${key}-start" data-affiliation="start_date" value="${esc(item.start_date)}" placeholder="YYYY、YYYY-MM 或 YYYY-MM-DD"></div><div class="field"><label for="${key}-end">结束时间</label><input id="${key}-end" data-affiliation="end_date" value="${esc(item.end_date)}" placeholder="未知时留空"></div>`:''}<div class="field wide"><label for="${key}-evidence">可核查出处 *</label><textarea id="${key}-evidence" data-affiliation="evidence" required placeholder="具体主页、文章首页、链接及可定位信息">${esc(item.evidence)}</textarea></div></div><button type="button" class="button tiny" data-action="affiliation-remove-row">移除这一项（历史保留）</button></fieldset>`;
}
function collectAffiliations(form){
  return [...form.querySelectorAll('[data-affiliation-row]')].map(row=>({...Object.fromEntries([...row.querySelectorAll('[data-affiliation]')].map(input=>[input.dataset.affiliation,input.value])),...(row.dataset.id?{id:row.dataset.id}:{}),reconfirm:row.dataset.reconfirm==='true',institution_name:row.querySelector('[data-affiliation=institution_id]').selectedOptions[0]?.textContent||'',byline_name:row.querySelector('[data-affiliation=byline_id]')?.selectedOptions[0]?.textContent||''}));
}
function syncAffiliationForm(form){form.elements.relations_json.value=JSON.stringify(collectAffiliations(form));}
async function relationshipForm(type,id,source='',draftKey=''){
  const data=await api(relationshipPath(type,id)),owner=type==='employment'?data.person:await api('/api/records/'+encodeURIComponent(id)),title=owner.name||owner.title;
  state.editing={type,id,version:data.version,original:{kind:type,title},draftSpecific:{record_version:data.record_version,byline_version:data.byline_version,return_source:source}};state.links=[];
  modal(`${title} · ${relationshipLabel(type)}`,`<form data-form="relations" data-type="${type}" class="workflow-form"><input type="hidden" name="title" value="${esc(title)}"><input type="hidden" name="relations_json"><p class="notice">${type==='employment'?'登记有依据的角色与时间，可同时保存多家机构和多个时期。未知起止时间留空，不补作现任判断。':'单位属于本篇作品的具体署名。请先在“整理署名”登记作者片段；修改这里的单位不建立任职关系。'}</p><div data-affiliation-rows>${data.items.map(item=>affiliationEditorRow(type,item,data)).join('')}</div><button type="button" class="button" data-action="affiliation-add-row">${type==='employment'?'添加一段任职':'添加一个文章单位'}</button><div class="field section-gap"><label for="relationship-change-note">本次维护依据 / 纠正说明 *</label><textarea id="relationship-change-note" name="change_note" required></textarea></div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="affiliation-cancel">返回并保留草稿</button><button type="submit" class="button primary">保存${relationshipLabel(type)}</button></div></form>`);
  const form=document.querySelector('[data-form=relations]');form._relationsData=data;
  syncAffiliationForm(form);await enableEditorDraft(form,state.editing,'',draftKey);
}
function restoreRelationshipDraft(form,draft){
  form._relationshipContextConflict=draft.specific.record_version!==form._editing.draftSpecific.record_version||draft.specific.byline_version!==form._editing.draftSpecific.byline_version;
  form._editing.draftSpecific={...draft.specific};
  const items=JSON.parse(form.elements.relations_json.value||'[]');
  form.querySelector('[data-affiliation-rows]').innerHTML=items.map(item=>affiliationEditorRow(form.dataset.type,item,form._relationsData)).join('');syncAffiliationForm(form);
}
async function relationshipReturn(type,id,source=''){
  if(source)await openSource(source);else if(type==='employment'){if(state.page==='people'&&state.params.get('id')===id)await route();else go('people',{id});}else await openRecord(id);
}
async function submitRelationshipForm(form){
  if(form._conflictPending)throw new Error('请先对照最新关系，再继续保存。');
  if(form._draftOffer)throw new Error('请先处理已有草稿。');
  syncAffiliationForm(form);form._dirty=true;saveEditorDraft(form,true);
  const edit=form._editing;
  await api(relationshipPath(form.dataset.type,edit.id),{method:'PUT',body:{version:edit.version,...edit.draftSpecific,items:collectAffiliations(form),change_note:form.elements.change_note.value}});
  await clearEditorDraft(form);closeModal();await relationshipReturn(form.dataset.type,edit.id,edit.draftSpecific.return_source);toast(relationshipLabel(form.dataset.type)+'已保存');
}
async function relationshipConflict(form){
  form._conflictPending=true;form._dirty=true;saveEditorDraft(form,true);
  const latest=await api(relationshipPath(form.dataset.type,form._editing.id));
  if(!form.isConnected||form.dataset.draftUser!==state.me?.id)return;
  form.querySelector('[data-conflict-panel]')?.remove();
  const panel=document.createElement('section');panel.className='conflict-panel';panel.dataset.conflictPanel='';panel._latest=latest;
  panel.innerHTML=`<h3>已有新版本，你的输入仍保留</h3><p>当前关系版本 ${latest.version}。请对照最新列表，已被移除的条目需要移出草稿，或在关系历史中明确恢复。</p><h4>最新已保存关系</h4>${relationshipList(latest.items,form.dataset.type)}<div class="row wrap"><button type="button" class="button primary" data-action="affiliation-accept-latest">已对照，保留我的输入继续编辑</button><button type="button" class="button" data-action="affiliation-use-server">采用最新关系列表</button></div>`;
  form.querySelector('.form-actions').before(panel);panel.scrollIntoView({block:'nearest'});
}
async function relationshipHistory(type,id,source=''){
  const [current,history]=await Promise.all([api(relationshipPath(type,id)),api(relationshipPath(type,id)+'/history')]),labels={manual:'人工维护',source_merge:'来源合并转接',record_merge:'资料合并转接'};
  modal(relationshipLabel(type)+' · 修改历史',`<p class="notice">恢复只调整所选这一项关系，并形成新版本。其他并存关系继续保留。</p><div class="person-history">${history.items.map(event=>`<details class="person-history-item"><summary><strong>${esc(event.after.institution.name)}</strong> · ${esc(labels[event.change_kind]||event.change_kind)}<span>${esc(event.actor_name)} · ${dateTime(event.created_at)}</span></summary><div class="person-history-content"><p class="prose">维护依据：${esc(event.change_note)}</p><div class="comparison-grid"><section><h4>修改前</h4>${relationshipValue(event.before,type)}</section><section><h4>修改后 · 关系版本 ${event.after.version}</h4>${relationshipValue(event.after,type)}</section></div><details><summary>关系来历</summary><p>关系编号 ${esc(event.after.id)}<br>原机构 ${esc(state.sources.find(s=>s.id===event.after.original_institution_id)?.name||event.after.original_institution_id)}<br>人工调整 ${event.after.manual_revision} 次</p></details><form data-form="relation-restore" data-type="${type}" data-id="${esc(id)}" data-event="${event.id}" data-source="${esc(source)}"><div class="field"><label>恢复这一项至修改后状态的依据<textarea name="change_note" required></textarea></label></div><div class="form-error" role="alert"></div><div data-restore-conflict></div><button type="submit" class="button">恢复这一项关系</button></form></div></details>`).join('')||'<p class="muted">尚无关系维护历史。</p>'}</div>`);
  document.querySelectorAll('[data-form=relation-restore]').forEach(form=>form._current=current);
}
async function restoreRelationshipForm(form){
  if(form._conflictPending)throw new Error('请先对照最新关系，再确认恢复。');
  const current=form._current,type=form.dataset.type,id=form.dataset.id;
  try{
    await api(relationshipPath(type,id)+`/history/${form.dataset.event}/restore`,{method:'POST',body:{version:current.version,record_version:current.record_version,byline_version:current.byline_version,change_note:form.elements.change_note.value}});
    closeModal();await relationshipReturn(type,id,form.dataset.source);toast('已恢复这一项关系');
  }catch(error){
    if(error.status===409){const latest=await api(relationshipPath(type,id));form._conflictPending=true;form._restoreLatest=latest;form.querySelector('[data-restore-conflict]').innerHTML=`<div class="notice"><p>已有新版本，恢复说明已保留。请核查当前关系：</p>${relationshipList(latest.items,type)}<button type="button" class="button" data-action="affiliation-review-restore">已对照，继续恢复所选关系</button></div>`;}
    throw error;
  }
}
async function employmentPersonPicker(source,query=''){
  const data=await api('/api/people?page_size=100&q='+encodeURIComponent(query));
  modal('选择任职人物',`<form data-form="employment-person-search" data-source="${esc(source)}"><div class="field"><label for="employment-person-query">查找人物</label><div class="row"><input id="employment-person-query" name="q" type="search" value="${esc(query)}" placeholder="姓名、原名或别名"><button type="submit" class="button">搜索</button></div></div></form>${data.items.map(person=>`<article class="affiliation-card"><h3>${esc(person.name)}</h3><p class="small muted">${esc(personNames(person).join(' · '))}</p><p>${esc(personHint(person,150)||'介绍待补充')}</p><button class="button" data-action="employment-choose-person" data-id="${esc(person.id)}" data-source="${esc(source)}">选择此人并登记任职</button></article>`).join('')||'<p class="muted">未找到人物，可先从作者目录建立档案。</p>'}${data.total>data.items.length?'<p class="muted">请用搜索缩小结果。</p>':''}`);
}

document.addEventListener('input',event=>{
  const form=event.target.closest('[data-form=relations]');if(!form)return;
  if(event.target.matches('[data-affiliation-filter]')){const query=event.target.value.trim().toLowerCase(),select=event.target.closest('[data-affiliation-row]').querySelector('[data-affiliation=institution_id]');[...select.options].forEach(option=>option.hidden=!!option.value&&option.value!==select.value&&!option.textContent.toLowerCase().includes(query));}
  syncAffiliationForm(form);
},true);
document.addEventListener('change',event=>{const form=event.target.closest('[data-form=relations]');if(!form)return;if(event.target.matches('[data-affiliation=institution_id],[data-affiliation=byline_id]'))event.target.closest('[data-affiliation-row]').dataset.reconfirm='true';syncAffiliationForm(form);},true);
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action]');if(!button)return;
  const action=button.dataset.action,form=button.closest('[data-form=relations]');
  try{
    if(action==='edit-employments')await relationshipForm('employment',button.dataset.id,button.dataset.source);
    else if(action==='edit-affiliations')await relationshipForm('affiliation',button.dataset.id,button.dataset.source);
    else if(action==='employment-history'||action==='affiliation-history')await relationshipHistory(action==='employment-history'?'employment':'affiliation',button.dataset.id,button.dataset.source);
    else if(action==='employment-person-picker')await employmentPersonPicker(button.dataset.id);
    else if(action==='source-published-page'){const section=button.closest('[data-published-source]');section.outerHTML=await institutionPublishedSection(section.dataset.publishedSource,Number(button.dataset.id));}
    else if(action==='employment-choose-person'){
      await relationshipForm('employment',button.dataset.id,button.dataset.source);const current=document.querySelector('[data-form=relations]');
      current.querySelector('[data-affiliation-rows]').insertAdjacentHTML('beforeend',affiliationEditorRow('employment',{institution_id:button.dataset.source},current._relationsData));syncAffiliationForm(current);current._dirty=true;saveEditorDraft(current,true);
    }else if(action==='affiliation-add-row'){form.querySelector('[data-affiliation-rows]').insertAdjacentHTML('beforeend',affiliationEditorRow(form.dataset.type,{},form._relationsData));syncAffiliationForm(form);form._dirty=true;saveEditorDraft(form,true);form.querySelector('[data-affiliation-row]:last-child input,[data-affiliation-row]:last-child select')?.focus();}
    else if(action==='affiliation-remove-row'){button.closest('[data-affiliation-row]').remove();syncAffiliationForm(form);form._dirty=true;saveEditorDraft(form,true);}
    else if(action==='affiliation-cancel'){const edit=form._editing;if(closeModal()!==false)await relationshipReturn(form.dataset.type,edit.id,edit.draftSpecific.return_source);}
    else if(action==='affiliation-accept-latest'||action==='affiliation-use-server'){
      const panel=button.closest('[data-conflict-panel]'),current=panel.closest('form'),latest=panel._latest,items=action==='affiliation-use-server'?latest.items:collectAffiliations(current);
      current._relationsData=latest;current._editing.version=latest.version;current._editing.draftSpecific={...current._editing.draftSpecific,record_version:latest.record_version,byline_version:latest.byline_version};
      current.querySelector('[data-affiliation-rows]').innerHTML=items.map(item=>affiliationEditorRow(current.dataset.type,item,latest)).join('');current._conflictPending=false;panel.remove();current.querySelector('.form-error').textContent='';syncAffiliationForm(current);saveEditorDraft(current,true);
    }else if(action==='affiliation-review-restore'){const current=button.closest('form');current._current=current._restoreLatest;current._conflictPending=false;current.querySelector('[data-restore-conflict]').innerHTML='';current.querySelector('.form-error').textContent='已采用最新版本，请再次确认恢复。';}
  }catch(error){toast(error.message);}
});
document.addEventListener('submit',async event=>{const form=event.target;if(form.dataset.form!=='employment-person-search')return;event.preventDefault();try{await employmentPersonPicker(form.dataset.source,form.elements.q.value);}catch(error){toast(error.message);}});
