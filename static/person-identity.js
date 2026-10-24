'use strict';

const personIdentityFields={name:'显示姓名',original_name:'原名',chinese_name:'中文名',introduction:'人物介绍',avatar:'头像'};
const personIdentityRoles={keep:'保留编号的档案',duplicate:'合并到前者的档案'};

function identityPersonCard(person,label='') {
  return `<section class="identity-person">${label?`<p class="eyebrow">${esc(label)}</p>`:''}<h3>${esc(person.name)}</h3><p class="small muted identity-id">${esc(person.id)} · 版本 ${person.version}</p>${personAvatar(person,true)}${personNames(person).length?`<p class="person-names">${esc(personNames(person).join(' · '))}</p>`:''}<div class="rich-prose">${readRich(person.introduction_html||'<p>介绍待补充</p>')}</div><p class="prose"><strong>参考出处</strong><br>${esc(person.sources||'未填写')}</p>${person.avatar_source?`<p class="small prose">头像来源：${esc(person.avatar_source)}</p>`:''}</section>`;
}

function identityRelations(relations) {
  return `<section class="identity-relations"><h3>涉及的资料与关系</h3><p class="form-help">这里列出你当前可阅读的资料与研究关联。正文、作者授权和报告采用的引用依据继续保留。</p>
    <details><summary>作品 · ${relations.works.length} 份</summary>${relations.works.map(work=>`<article><h4>${linkButton(esc(work.title),'detail',work.id,'link-button')}</h4>${work.bylines.map(row=>`<p>${row.position}. ${esc(row.raw_name)} · ${esc(row.target?.name||'身份待确认')}${row.removed_at?' · 已移除':''}<br><span class="small">${esc(row.evidence||'确认依据待补充')}</span></p>`).join('')}</article>`).join('')||'<p>暂无可阅读的相关作品。</p>'}</details>
    <details><summary>任职经历 · ${relations.employments.length} 条</summary>${relations.employments.map(row=>`<p>${esc(row.person?.name||row.person_id)} · ${esc(row.institution?.name||row.institution_id)} · ${esc(row.role)}${row.removed_at?' · 已移除':''}<br><span class="small">${esc(row.start_date||'起始未知')} — ${esc(row.end_date||'结束未知')} · ${esc(row.evidence)}</span></p>`).join('')||'<p>暂无任职关系。</p>'}</details>
    <details><summary>研究笔记 · ${relations.notes.length} 份</summary>${relations.notes.map(note=>`<p>${linkButton(esc(note.title),'detail',note.id,'link-button')}<br><span class="small">${note.subjects.map(row=>esc(row.subject_name)+(row.status==='removed'?'（已移除）':'')).join(' · ')}</span></p>`).join('')||'<p>暂无可阅读的相关笔记。</p>'}</details>
    <details><summary>文章署名单位 · ${relations.affiliations.length} 条</summary>${relations.affiliations.map(row=>`<p>${esc(row.record.title)} · ${esc(row.byline.raw_name)} · ${esc(row.institution?.name||row.institution_id)}${row.removed_at?' · 已移除':''}<br><span class="small">${esc(row.evidence)}</span></p>`).join('')||'<p>暂无可阅读的文章署名单位。</p>'}</details></section>`;
}

async function searchPersonMerge(keep,query='') {
  const result=await api('/api/people?page_size=100&q='+encodeURIComponent(query));
  modal('选择要比较的人物',`<form data-form="person-merge-search" data-keep="${esc(keep)}"><div class="field"><label for="identity-query">查找重复人物</label><div class="row"><input id="identity-query" name="q" value="${esc(query)}" placeholder="姓名、原名或别名"><button class="button" type="submit">搜索</button></div></div><p class="form-error" role="alert"></p></form><div class="identity-candidates">${result.items.filter(person=>person.id!==keep).map(person=>`<article><h3>${esc(person.name)}</h3><p>${esc(personNames(person).join(' · '))}</p><p>${esc(person.introduction_text.slice(0,180)||'介绍待补充')}</p><button class="button" data-action="person-compare" data-keep="${esc(keep)}" data-duplicate="${esc(person.id)}">比较此人物</button></article>`).join('')||'<p class="muted">没有可比较的人物。可换一种姓名写法查找。</p>'}${result.total>result.items.length?'<p>请用搜索缩小结果。</p>':''}</div>`);
}

function identityFormEnd(action,draft,allowed=true) {
  if(!allowed)return '';
  return `${textField('evidence',action==='merge'?'确认同一人的依据 *':'拆回依据 / 说明 *',draft.evidence||'','注明可定位的主页、作品署名或反证')}
    <label class="check-label identity-confirm"><input type="checkbox" name="confirmed" required><span>${action==='merge'?'已核实属于同一人，并已核对本次保留信息与影响。':'已核对原合并与当前状态，确认恢复两个身份。'}</span></label><p class="form-error" role="alert"></p><div data-identity-conflict></div><div class="form-actions"><button type="button" class="button" data-action="close">关闭</button><button class="button primary" type="submit">${action==='merge'?'确认合并人物':'确认拆回人物'}</button></div>`;
}

async function comparePeople(keep,duplicate,draft={}) {
  const preview=await api('/api/people/merge-preview',{method:'POST',body:{keep_id:keep,duplicate_id:duplicate}});
  modal('比较并合并人物',`<form data-form="person-identity" data-operation="merge"><p class="notice">保留“${esc(preview.keep.name)}”的稳定编号，另一编号继续指向此人。请选择当前显示的信息；其他内容和两份档案的来历保留在历史中。</p><button type="button" class="button" data-action="person-swap-comparison" data-keep="${esc(duplicate)}" data-duplicate="${esc(keep)}">交换保留编号</button><div class="identity-comparison">${identityPersonCard(preview.keep,'保留编号的档案')}${identityPersonCard(preview.duplicate,'合并到前者的档案')}</div>
    <section class="identity-choices"><h3>选择合并后当前显示的信息</h3><p class="form-help">${preview.conflicts.length?'存在差异：'+preview.conflicts.map(key=>personIdentityFields[key]).join('、'):'两份档案的当前信息一致。'} 姓名写法和参考出处汇集保留。</p>${Object.entries(personIdentityFields).map(([key,label])=>`<fieldset><legend>${label} *</legend>${[['keep',preview.keep],['duplicate',preview.duplicate]].map(([side,person])=>`<label><input type="radio" name="${key}" value="${side}" required ${draft.choices?.[key]===side?'checked':''}><span><strong>${personIdentityRoles[side]}</strong><br>${esc(person.name)}${key==='avatar'?person.avatar?'的头像':' · 暂无头像':key==='introduction'?'的介绍':' · '+esc(person[key]||'未填写')}</span></label>`).join('')}</fieldset>`).join('')}</section>${identityRelations(preview.relationships)}${identityFormEnd('merge',draft)}</form>`);
  const form=document.querySelector('[data-form=person-identity]');
  form._identity={preview,keep,duplicate};form._requestKey=crypto.randomUUID();
  form.elements.evidence.required=true;
}

async function personIdentityHistory(pid) {
  const result=await api('/api/people/'+encodeURIComponent(pid)+'/identity-history');
  modal('人物身份整理历史',`<p class="notice">身份合并与拆回分别记录；修改介绍的历史恢复不会拆回身份。</p>${result.items.map(event=>`<article class="identity-event"><h3>${event.event_type==='merge'?'人物合并':'人物拆回'}${event.status==='split'?' · 已拆回':''}</h3><p class="small muted">${esc(event.actor_name)} · ${dateTime(event.created_at)}</p><p class="prose">${esc(event.evidence)}</p><details><summary>查看原档案、依据和关系</summary><div class="identity-comparison">${event.people_before.map(person=>identityPersonCard(person)).join('')}</div>${identityRelations(event.relationships)}<p class="small identity-id">事件 ${esc(event.id)}</p></details>${event.event_type==='merge'&&event.status==='active'?`<button class="button" data-action="person-preview-split" data-id="${esc(event.id)}">预览拆回</button>`:''}</article>`).join('')||'<p class="muted">尚无身份合并或拆回记录。</p>'}`);
}

async function previewPersonSplit(eventId,draft={}) {
  const preview=await api('/api/people/identity-events/'+encodeURIComponent(eventId)+'/split-preview',{method:'POST',body:{}});
  modal('拆回人物合并',`<form data-form="person-identity" data-operation="split"><p class="notice">原合并依据：${esc(preview.merge.evidence)}</p>${preview.allowed?'<p class="notice">恢复两个原身份。后续独立编辑、明确纠正及解除保持；仅按本次合并的来历恢复原转接。</p>':`<p class="notice identity-blocked" role="alert">${esc(preview.reason)}</p>`}${preview.split_order.length?`<section class="identity-split-order"><h3>先拆回后续合并</h3><ol>${preview.split_order.map(event=>`<li><p>${esc(event.duplicate_name)} → ${esc(event.keep_name)}<br><span class="small">${esc(event.evidence)}</span></p><button type="button" class="button" data-action="person-preview-split" data-id="${esc(event.event_id)}">预览这次后续合并</button></li>`).join('')}</ol><p class="form-help">按顺序完成后，从身份整理历史重新预览本次。</p></section>`:''}${identitySplitChanges(preview,draft)}<details class="identity-originals"><summary>查看合并前档案与文章单位</summary><div class="identity-comparison">${preview.merge.people_before.map(person=>identityPersonCard(person,person.id===preview.merge.keep_id?'保留编号的原档案':person.id===preview.merge.duplicate_id?'并入的原档案':'关联的原身份')).join('')}</div>${identityRelations(preview.relationships)}</details>${identityFormEnd('split',draft,preview.allowed)}</form>`);
  const form=document.querySelector('[data-form=person-identity]');form._identity={preview,eventId};form._requestKey=crypto.randomUUID();
  if(form.elements.evidence)form.elements.evidence.required=true;
}

function identitySplitChanges(preview,draft) {
  const labels={transferred:'原有转接',added:'后续新增',corrected:'独立更正',removed:'已解除',unchanged:'原有确定关系'};
  const people=preview.merge.people_before,keep=people.find(p=>p.id===preview.merge.keep_id),duplicate=people.find(p=>p.id===preview.merge.duplicate_id);
  const rows=Object.entries(preview.changes).flatMap(([type,items])=>items.map(row=>({...row,type})));
  const fieldLabels={...personIdentityFields,introduction_html:'介绍',introduction_text:'介绍',avatar_id:'头像',avatar_source:'头像来源',aliases:'姓名写法',sources:'参考出处'};
  const edited=preview.profile_changes.filter(p=>p.fields.length).map(p=>`<p>${esc(people.find(person=>person.id===p.person_id)?.name||'原档案')}：${esc([...new Set(p.fields.map(key=>fieldLabels[key]||key))].join('、'))}</p>`).join('');
  return `<section class="identity-split-changes"><h3>拆回后的归属</h3><p class="form-help">仅列出你当前可阅读的关系。新增作品可以待确认；新增任职须明确分配。笔记研究对象由作者或当前授权同事确认。</p>${edited?`<div class="notice"><strong>保留后续独立修改</strong>${edited}</div>`:''}${Object.entries(labels).map(([classification,label])=>{
    const group=rows.filter(row=>row.classification===classification);if(!group.length)return '';
    return `<details ${classification==='added'?'open':''}><summary>${label} · ${group.length} 条</summary>${group.map(row=>{
      const note=preview.relationships.notes.find(item=>item.subjects.some(s=>s.id===row.id));
      const work=preview.relationships.works.find(item=>item.bylines.some(s=>s.id===row.id));
      const title=row.type==='employments'?`${row.institution?.name||''} · ${row.role}`:row.type==='bylines'?`${work?.title||''} · ${row.raw_name}`:note?.title||'';
      const current=row.type==='employments'?row.person?.name:row.type==='bylines'?row.target?.name:row.subject_name;
      const restored=people.find(person=>person.id===row.restore_id)?.name;
      const hint=classification==='transferred'?'按原来历恢复归属，后续字段保留。':classification==='corrected'?'保留已明确纠正的当前归属。':classification==='removed'?'保持解除，保留历史。':'保留现有关系。';
      const value=draft.allocations?.[row.type]?.[row.id]||'';
      return `<article><h4>${esc(title)}</h4>${current?`<p class="small">当前：${esc(current)}${restored?' → 恢复为 '+esc(restored):''}</p>`:''}${classification==='added'?(row.can_assign&&preview.allowed?`<label class="field"><span>${row.type==='employments'?'任职归属 *':'新增关系归属'}</span><select data-split-allocation data-relation-type="${row.type}" data-relation-id="${esc(row.id)}" aria-label="${esc(title)}的归属" ${row.type==='employments'?'required':''}>${row.type==='employments'?`<option value="">请选择人物</option>`:`<option value="pending" ${!value||value==='pending'?'selected':''}>${row.type==='subjects'?'保留待作者复核':'保留待确认'}</option>`}<option value="keep" ${value==='keep'?'selected':''}>${esc(keep.name)}（保留原编号）</option><option value="duplicate" ${value==='duplicate'?'selected':''}>${esc(duplicate.name)}（恢复原编号）</option></select></label>`:`<p class="small">${row.type==='subjects'?'由笔记作者或当前授权同事稍后复核。':'拆回时明确选择归属。'}</p>`):`<p class="small">${hint}</p>`}</article>`;
    }).join('')}</details>`;
  }).join('')||'<p>没有需要转接或分配的可阅读关系。</p>'}</section>`;
}

function identityDraft(form) {
  const allocations={};form.querySelectorAll('[data-split-allocation]').forEach(select=>{(allocations[select.dataset.relationType]||={})[select.dataset.relationId]=select.value;});
  return {evidence:form.elements.evidence?.value||'',allocations,choices:Object.fromEntries(Object.keys(personIdentityFields).map(key=>[key,form.elements[key]?.value||'']))};
}

async function submitPersonIdentity(form) {
  if(form.dataset.saving==='true')return;
  if(form._needsComparison)throw new Error('请先重新比较当前影响，再确认提交。');
  const draft=identityDraft(form),operation=form.dataset.operation;
  const body={preview_id:form._identity.preview.preview_id,idempotency_key:form._requestKey,evidence:draft.evidence,confirmed:form.elements.confirmed.checked};
  if(operation==='merge')body.choices=draft.choices;
  else body.allocations=draft.allocations;
  form.dataset.saving='true';
  try {
    const result=await api('/api/people/'+operation,{method:'POST',body});
    closeModal();toast(operation==='merge'?'人物已合并，旧编号与历史继续保留':'人物已拆回，历史继续保留');go('people',{id:result.keep_id});
  } catch(error) {
    if(error.status===409){
      form._needsComparison=true;
      form.querySelector('[data-identity-conflict]').innerHTML='<p class="notice">你的选择和依据仍保留。重新比较后，请再次核实当前影响并确认。</p><button type="button" class="button" data-action="person-recompare">重新比较，保留输入</button>';
    }
    throw error;
  } finally {form.dataset.saving='false';}
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action]');if(!button)return;
  try {
    const action=button.dataset.action;
    if(action==='person-merge-picker')await searchPersonMerge(button.dataset.id);
    else if(action==='person-compare'||action==='person-swap-comparison')await comparePeople(button.dataset.keep,button.dataset.duplicate);
    else if(action==='person-identity-history')await personIdentityHistory(button.dataset.id);
    else if(action==='person-preview-split')await previewPersonSplit(button.dataset.id);
    else if(action==='person-recompare'){
      const form=button.closest('form'),draft=identityDraft(form),context=form._identity;
      if(form.dataset.operation==='merge')await comparePeople(context.keep,context.duplicate,draft);else await previewPersonSplit(context.eventId,draft);
    }
  } catch(error){toast(error.message);}
});
