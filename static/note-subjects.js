'use strict';

const noteSubjectLabels={person:'人物',institution:'机构',journal:'期刊'};
function noteSubjectKey(subject){return subject.subject_type+':'+subject.subject_id;}
function noteSubjectLink(subject){
  const label=esc(subject.subject_name||subject.subject_id);
  return subject.subject_type==='person'?`<a class="link-button" data-action="note-subject-person" data-id="${esc(subject.subject_id)}" href="#people?id=${encodeURIComponent(subject.subject_id)}">${label}</a>`:linkButton(label,'source-detail',subject.subject_id,'link-button');
}
function noteSubjectDetail(record){
  if(record.kind!=='research_note')return '';
  const subjects=record.research_subjects||[];
  return `<section class="detail-section note-subject-detail"><div class="between wrap"><h3>笔记研究对象</h3>${record.can_edit?linkButton('调整研究对象','edit-record',record.id):''}</div>${subjects.length?subjects.map(subject=>`<div class="note-subject-entry"><div class="row wrap">${noteSubjectLink(subject)}<span class="small muted">${noteSubjectLabels[subject.subject_type]}</span>${subject.status==='needs_review'?'<span class="badge pending">研究对象待复核</span>':''}</div>${subject.identity_change?`<p class="notice">此人物身份${subject.identity_change.action==='person_merge'?'已合并':'已拆回'}，笔记正文与原有研究对象来历保留。<br>依据：${esc(subject.identity_change.evidence)} ${linkButton('查看身份说明','person-identity-history',subject.subject_id,'link-button')}</p>`:''}${subject.status==='needs_review'?`<p class="small muted">原对象：${esc(subject.original_subject_name||subject.original_subject_id)}。此关联暂不计入人物已确认笔记。</p>${record.can_edit?`<button class="button tiny" data-action="note-subject-review" data-id="${esc(record.id)}" data-relation="${esc(subject.id)}">复核研究对象</button>`:'<p class="small muted">由笔记作者或当前授权同事确认。</p>'}`:''}</div>`).join(''):'<p class="muted">尚未明确选择研究对象。</p>'}${record.can_edit?linkButton('研究对象调整历史','note-subject-history',record.id):''}</section>`;
}
async function noteSubjectProfile(type,id){
  const path=(type==='person'?'/api/people/':'/api/sources/')+encodeURIComponent(id)+'/research-notes';
  const notes=await api(path);
  return `<section class="detail-section note-subject-profile"><div class="between wrap"><h2>研究笔记</h2><div class="row wrap"><button class="button primary tiny" data-action="new-subject-note" data-type="${type}" data-id="${esc(id)}">写研究笔记</button><button class="button tiny" data-action="existing-subject-note" data-type="${type}" data-id="${esc(id)}">关联已有笔记</button></div></div><p class="small muted">明确以此对象开展研究的笔记 · ${notes.total} 份</p>${notes.items.map(note=>`<article class="note-subject-card">${linkButton(esc(note.title),'detail',note.id,'detail-link')}<p class="small muted">${esc(note.author_name||'负责作者待确认')} · 版本 ${note.version}</p>${note.abstract?`<p>${esc(note.abstract)}</p>`:''}</article>`).join('')||'<p class="muted">暂无可阅读的关联笔记。</p>'}</section>`;
}
async function prepareNoteSubjectForm(form,record){
  const people=[];let page=1,total=1;
  while(people.length<total){const result=await api('/api/people?page_size=100&page='+page++);people.push(...result.items);total=result.total;if(!result.items.length)break;}
  if(!form.isConnected)return;
  const choices=[...people.map(p=>({subject_type:'person',subject_id:p.id,name:p.name,hint:[personNames(p).join(' · '),personHint(p,70)].filter(Boolean).join(' · ')})),
    ...state.sources.filter(s=>isInstitution(s)||s.kind==='journal').map(s=>({subject_type:isInstitution(s)?'institution':'journal',subject_id:s.id,name:s.name,hint:s.original_name||''}))];
  form._subjectChoices=choices;
  const checked=new Set((record.research_subjects||[]).map(noteSubjectKey));
  const section=document.createElement('section');section.className='wide note-subject-picker';section.dataset.noteSubjectPicker='';
  section.innerHTML=`<h3>笔记研究对象（可多选）</h3><p class="form-help">明确选择这份笔记研究的人物、机构和期刊。</p><div class="field"><label for="note-subject-search">筛选研究对象</label><input id="note-subject-search" type="search" data-note-subject-search placeholder="查找人物、机构或期刊"></div><div class="note-subject-choices">${choices.map(subject=>`<label class="check-label" data-note-subject-choice="${esc((subject.name+' '+subject.hint).toLowerCase())}"><input type="checkbox" name="research_subject_choices" value="${esc(noteSubjectKey(subject))}" ${checked.has(noteSubjectKey(subject))?'checked':''}><span>${esc(subject.name)} <small>${noteSubjectLabels[subject.subject_type]}</small>${subject.hint?`<small class="note-subject-hint">${esc(subject.hint)}</small>`:''}</span></label>`).join('')||'<p class="muted">请先建立人物、机构或期刊档案。</p>'}</div>`;
  form.querySelector('[data-rich-field="body_html"]').before(section);
  updateNoteSubjectMode(form);
}
function updateNoteSubjectMode(form){const section=form.querySelector('[data-note-subject-picker]');if(section)section.hidden=form.elements.kind.value!=='research_note';}
function noteSubjectValues(form){
  const keys=new FormData(form).getAll('research_subject_choices'),current=form._editing.original.research_subjects||[];
  return keys.flatMap(key=>{const existing=current.filter(subject=>noteSubjectKey(subject)===key);if(existing.length)return existing.map(subject=>({id:subject.id,version:subject.version,subject_type:subject.subject_type,subject_id:subject.subject_id}));const selected=form._subjectChoices.find(subject=>noteSubjectKey(subject)===key);return selected?[{subject_type:selected.subject_type,subject_id:selected.subject_id}]:[];});
}
function noteSubjectConflict(form,latest){
  if(latest.kind!=='research_note'||!form._subjectChoices)return '';
  const names=keys=>keys.map(key=>form._subjectChoices.find(subject=>noteSubjectKey(subject)===key)?.name||key).join('；')||'未选择';
  return `<div class="comparison-grid note-subject-comparison"><section><h4>你的研究对象选择</h4><p>${esc(names(new FormData(form).getAll('research_subject_choices')))}</p></section><section><h4>最新研究对象</h4><p>${esc(names((latest.research_subjects||[]).map(noteSubjectKey)))}</p></section></div>`;
}

async function reviewNoteSubject(noteId,relationId,selected=''){
  const record=await api('/api/records/'+encodeURIComponent(noteId));
  const subject=record.research_subjects.find(row=>row.id===relationId);
  if(!record.can_edit||!subject||subject.status!=='needs_review')throw new Error('研究对象状态或编辑授权已改变，请重新打开笔记。');
  const people=[];let page=1,total=1;
  while(people.length<total){const result=await api('/api/people?page_size=100&page='+page++);people.push(...result.items);total=result.total;if(!result.items.length)break;}
  const choices=[...people.map(person=>({key:'person:'+person.id,name:person.name+(personHint(person,70)?' · '+personHint(person,70):''),type:'人物'})),...state.sources.filter(source=>isInstitution(source)||source.kind==='journal').map(source=>({key:(isInstitution(source)?'institution:':'journal:')+source.id,name:source.name,type:isInstitution(source)?'机构':'期刊'}))];
  const original=subject.original_subject_type+':'+subject.original_subject_id,value=selected||original;
  modal('复核笔记研究对象',`<form data-form="note-subject-review"><h3>${esc(record.title)}</h3><p class="notice">身份更正依据：${esc(subject.identity_change?.evidence||'请查看人物身份整理历史')}</p><p>原对象：${esc(subject.original_subject_name||subject.original_subject_id)}</p><p class="form-help">明确确认原对象、改选或移除这条关联。笔记正文、作者授权和报告采用的引用保持。</p><label class="field"><span>处理这条研究对象关联</span><select name="selection" required>${choices.map(choice=>`<option value="${esc(choice.key)}" ${choice.key===value?'selected':''}>${esc(choice.name)} · ${choice.type}${choice.key===original?'（原对象）':''}</option>`).join('')}<option value="remove" ${value==='remove'?'selected':''}>移除此关联，保留笔记</option></select></label><p class="form-error" role="alert"></p><div data-review-conflict></div><div class="form-actions"><button type="button" class="button" data-action="close">关闭</button><button type="submit" class="button primary">确认研究对象处理</button></div></form>`);
  const form=document.querySelector('[data-form=note-subject-review]');form._review={record,subject};
}

async function submitNoteSubjectReview(form){
  if(form._needsComparison)throw new Error('请先重新核对最新笔记与授权。');
  const {record,subject}=form._review,selection=form.elements.selection.value;
  const desired=record.research_subjects.flatMap(row=>{
    if(row.id!==subject.id)return [row];if(selection==='remove')return [];
    const split=selection.indexOf(':');return [{...row,subject_type:selection.slice(0,split),subject_id:selection.slice(split+1),confirm:true}];
  });
  try{
    await api('/api/records/'+encodeURIComponent(record.id)+'/research-subjects',{method:'PUT',body:{version:record.version,research_subjects:desired}});
    closeModal();if(typeof uxRefreshBackground==='function')await uxRefreshBackground();await workflowOpenRecord(record.id);toast('研究对象已明确处理');
  }catch(error){if(error.status===409){form._needsComparison=true;form.querySelector('[data-review-conflict]').innerHTML='<p class="notice">你的选择仍保留，请重新核对最新版本。</p><button type="button" class="button" data-action="note-subject-review-recompare">重新核对，保留选择</button>';}throw error;}
}
async function existingSubjectNotes(type,id,query=''){
  const result=await api('/api/records?kind=research_note&editable=1&size=100&q='+encodeURIComponent(query));
  modal('选择可编辑的研究笔记',`<form data-form="subject-note-search" data-type="${type}" data-id="${esc(id)}"><div class="field"><label for="subject-note-query">查找笔记</label><div class="row"><input id="subject-note-query" name="q" value="${esc(query)}" placeholder="笔记题名或正文"><button class="button" type="submit">搜索</button></div></div></form><div class="note-subject-list">${result.items.map(note=>`<article class="note-subject-card"><h3>${esc(note.title)}</h3><button class="button" data-action="link-subject-note" data-id="${esc(note.id)}" data-type="${type}" data-subject-id="${esc(id)}">选择并编辑研究对象</button></article>`).join('')||'<p class="muted">没有可编辑的笔记。可先写一份新笔记。</p>'}${result.total>result.items.length?'<p class="muted">请用搜索缩小结果。</p>':''}</div>`);
}
document.addEventListener('input',event=>{if(!event.target.matches('[data-note-subject-search]'))return;const q=event.target.value.trim().toLowerCase();event.target.closest('[data-note-subject-picker]').querySelectorAll('[data-note-subject-choice]').forEach(choice=>choice.hidden=!choice.dataset.noteSubjectChoice.includes(q));});
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action]');if(!button)return;
  try{
    const type=button.dataset.type,id=button.dataset.id;
    if(button.dataset.action==='note-subject-person'){
      event.preventDefault();if(state.page==='people'&&state.params.get('id')===id)await route();else go('people',{id});
    }else if(button.dataset.action==='new-subject-note')await workflowRecordForm('','research_note','subject:'+type+':'+id,'','',{research_subjects:[{subject_type:type,subject_id:id}]});
    else if(button.dataset.action==='existing-subject-note')await existingSubjectNotes(type,id);
    else if(button.dataset.action==='link-subject-note'){
      await workflowRecordForm(id);const form=document.querySelector('[data-form=record]');if(!form)return;
      const key=type+':'+button.dataset.subjectId,choice=[...form.querySelectorAll('[name=research_subject_choices]')].find(input=>input.value===key);
      if(!choice)throw new Error('研究对象已改变，请重新打开档案。');choice.checked=true;form._dirty=true;saveEditorDraft(form,true);
    }else if(button.dataset.action==='note-subject-review')await reviewNoteSubject(id,button.dataset.relation);
    else if(button.dataset.action==='note-subject-review-recompare'){
      const form=button.closest('form');await reviewNoteSubject(form._review.record.id,form._review.subject.id,form.elements.selection.value);
    }else if(button.dataset.action==='note-subject-history'){
      const result=await api('/api/records/'+encodeURIComponent(id)+'/research-subjects/history');
      const labels={created:'选择研究对象',manual:'人工调整',removed:'移除关联',source_merge:'来源合并转接',record_merge:'笔记合并转接',person_merge:'人物合并转接',person_split:'人物拆回转接',person_split_review:'人物拆回后研究对象待复核／分配'};
      modal('研究对象调整历史',result.items.map(item=>`<article class="note-subject-card"><h3>${esc(labels[item.action]||item.action)} · ${esc(item.snapshot.subject_name||item.snapshot.subject_id)}</h3><p>${esc(item.actor_name)} · ${dateTime(item.created_at)}</p><p>${noteSubjectLabels[item.snapshot.subject_type]} · ${esc(item.snapshot.subject_name||item.snapshot.subject_id)} · 关系版本 ${item.snapshot.version}</p><p class="small muted">原对象：${noteSubjectLabels[item.snapshot.original_subject_type]} · ${esc(item.snapshot.original_subject_name||item.snapshot.original_subject_id)}</p><details><summary>追溯编号</summary><p>当前对象 ${esc(item.snapshot.subject_id)}<br>原对象 ${esc(item.snapshot.original_subject_id)}<br>原笔记 ${esc(item.snapshot.original_note_id)}</p></details></article>`).join('')||'<p class="muted">尚无调整记录。</p>');
    }
  }catch(error){toast(error.message);}
});
document.addEventListener('submit',async event=>{const form=event.target;if(!['subject-note-search','note-subject-review'].includes(form.dataset.form))return;event.preventDefault();try{if(form.dataset.form==='note-subject-review')await submitNoteSubjectReview(form);else await existingSubjectNotes(form.dataset.type,form.dataset.id,form.elements.q.value);}catch(error){const errorBox=form.querySelector('.form-error');if(errorBox)errorBox.textContent=error.message;else toast(error.message);}});
