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
  return `<section class="detail-section note-subject-detail"><div class="between wrap"><h3>笔记研究对象</h3>${record.can_edit?linkButton('调整研究对象','edit-record',record.id):''}</div>${subjects.length?subjects.map(subject=>`<div><div class="row wrap">${noteSubjectLink(subject)}<span class="small muted">${noteSubjectLabels[subject.subject_type]}</span>${subject.status==='needs_review'?'<span class="badge pending">研究对象待复核</span>':''}</div>${subject.identity_change?`<p class="notice">此人物身份${subject.identity_change.action==='person_merge'?'已合并':'已拆回'}，笔记正文与原有研究对象来历保留。${linkButton('查看身份说明','person-identity-history',subject.subject_id,'link-button')}</p>`:''}</div>`).join(''):'<p class="muted">尚未明确选择研究对象。</p>'}${record.can_edit?linkButton('研究对象调整历史','note-subject-history',record.id):''}</section>`;
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
  const choices=[...people.map(p=>({subject_type:'person',subject_id:p.id,name:p.name,hint:personNames(p).join(' · ')||p.introduction_text.slice(0,70)})),
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
    }else if(button.dataset.action==='note-subject-history'){
      const result=await api('/api/records/'+encodeURIComponent(id)+'/research-subjects/history');
      const labels={created:'选择研究对象',manual:'人工调整',removed:'移除关联',source_merge:'来源合并转接',record_merge:'笔记合并转接',person_merge:'人物合并转接',person_split:'人物拆回转接'};
      modal('研究对象调整历史',result.items.map(item=>`<article class="note-subject-card"><h3>${esc(labels[item.action]||item.action)} · ${esc(item.snapshot.subject_name||item.snapshot.subject_id)}</h3><p>${esc(item.actor_name)} · ${dateTime(item.created_at)}</p><p>${noteSubjectLabels[item.snapshot.subject_type]} · ${esc(item.snapshot.subject_name||item.snapshot.subject_id)} · 关系版本 ${item.snapshot.version}</p><p class="small muted">原对象：${noteSubjectLabels[item.snapshot.original_subject_type]} · ${esc(item.snapshot.original_subject_name||item.snapshot.original_subject_id)}</p><details><summary>追溯编号</summary><p>当前对象 ${esc(item.snapshot.subject_id)}<br>原对象 ${esc(item.snapshot.original_subject_id)}<br>原笔记 ${esc(item.snapshot.original_note_id)}</p></details></article>`).join('')||'<p class="muted">尚无调整记录。</p>');
    }
  }catch(error){toast(error.message);}
});
document.addEventListener('submit',async event=>{const form=event.target;if(form.dataset.form!=='subject-note-search')return;event.preventDefault();try{await existingSubjectNotes(form.dataset.type,form.dataset.id,form.elements.q.value);}catch(error){toast(error.message);}});
