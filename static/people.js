'use strict';

function personAvatar(person, small=false) {
  return person.avatar
    ? `<img class="person-avatar ${small?'small':''}" src="${esc(person.avatar.url)}" alt="${esc(person.name)}的头像">`
    : `<div class="person-avatar person-placeholder ${small?'small':''}" role="img" aria-label="暂无头像">${icon('person')}<span>暂无头像</span></div>`;
}

function personNames(person) {
  return [...new Set([person.original_name,person.chinese_name,...(person.aliases||'').split('\n')].map(x=>x.trim()).filter(x=>x&&x!==person.name))];
}

async function peoplePage() {
  if(state.params.get('id')){const id=state.params.get('id');return personPage(await api('/api/people/'+encodeURIComponent(id)),await bylineWorksSection('person',id));}
  const result=await api('/api/people?'+state.params),query=state.params.get('q')||'';
  return `<section class="people-page"><div class="page-heading between wrap"><div><h1>作者目录</h1><p>共同积累人物介绍与可查证的出处。</p></div>${linkButton(icon('plus')+' 建立人物档案','new-person','','button primary')}</div>
    <form data-form="people-search" class="toolbar"><div class="search-input">${icon('search')}<input name="q" type="search" aria-label="搜索作者" placeholder="原名、中文名或别名" value="${esc(query)}"></div><button class="button primary" type="submit">搜索</button>${query?linkButton('清除搜索','people-clear'):''}</form>
    <div class="results-head"><p>${query?'“'+esc(query)+'” · ':''}共 ${result.total} 位人物</p></div><div class="people-grid">${result.items.map(p=>`<article class="panel person-card">${personAvatar(p,true)}<div><h2><a href="#people?${esc(parameters({id:p.id}))}">${esc(p.name)}</a></h2>${personNames(p).length?`<p class="person-names">${esc(personNames(p).join(' · '))}</p>`:''}<p>${esc(p.introduction_text.slice(0,160)||'介绍待补充')}</p><p class="small muted">版本 ${p.version} · ${dateTime(p.updated_at)}</p></div></article>`).join('')||empty(query?'未找到人物':'还没有人物档案',query?'可以换一种姓名写法，或核实后建立新档案。':'可以先建立档案，再逐步积累资料。','person')}</div>
    ${result.total>result.page_size?`<div class="pagination">${result.page>1?linkButton('上一页','page',String(result.page-1)):''}<span>第 ${result.page} / ${Math.ceil(result.total/result.page_size)} 页</span>${result.page*result.page_size<result.total?linkButton('下一页','page',String(result.page+1)):''}</div>`:''}</section>`;
}

async function personPage(person,works='') {
  state.detail={type:'person',data:person};
  const names=personNames(person);
  return `<article class="person-page"><a class="back-link" href="#people?${esc(parameters({id:''}))}">← 返回作者目录</a>
    ${state.params.get('work')?linkButton('返回资料','byline-back',state.params.get('work')):''}
    <header class="person-heading"><div>${personAvatar(person)}${person.avatar&&person.avatar_source?`<p class="person-avatar-source">头像来源：${esc(person.avatar_source)}</p>`:''}</div><div><p class="eyebrow">人物 Wiki</p><h1>${esc(person.name)}</h1>${names.length?`<p class="person-names">${esc(names.join(' · '))}</p>`:''}<p class="muted">版本 ${person.version}${person.last_modifier?' · '+esc(person.last_modifier.name)+' · '+dateTime(person.last_modifier.created_at):''}</p><div class="detail-actions">${person.can_edit?linkButton(icon('edit')+' 编辑档案','edit-person',person.id,'button primary'):''}${linkButton(icon('clock')+' 修改历史','person-history',person.id)}</div></div></header>
    <section class="panel person-section"><h2>人物介绍</h2>${person.introduction_html?`<div class="rich-prose">${readRich(person.introduction_html)}</div>`:'<p class="muted">介绍待补充，可由中心成员共同维护。</p>'}${person.sources?`<section class="person-sources"><h3>参考出处</h3><p class="prose">${esc(person.sources)}</p></section>`:''}</section>
    ${works}
    ${await noteSubjectProfile('person',person.id)}
    <details class="person-identity"><summary>档案信息</summary><dl><dt>稳定编号</dt><dd>${esc(person.id)}</dd><dt>最近维护依据 / 说明</dt><dd>${esc(person.change_note)}</dd></dl></details></article>`;
}

async function personForm(id='',draftKey='') {
  const person=id?await api('/api/people/'+encodeURIComponent(id)):{kind:'person'};
  state.editing={type:'person',id,version:person.version,original:person};
  state.links=[];
  modal(id?'编辑人物档案':'建立人物档案',`<form data-form="person" class="workflow-form person-form"><p class="notice">人物档案由有效成员共同维护，每次保存保留修改人和依据。</p><div class="form-grid">
    ${inputField('name','显示姓名 *',person.name,'中文名或常用原名',true)}${inputField('original_name','原名',person.original_name)}${inputField('chinese_name','中文名',person.chinese_name)}${textField('aliases','其他姓名写法',person.aliases,'每行一种写法')}
    <section class="wide person-avatar-editor"><h3>头像</h3><div data-person-current-avatar>${personAvatar(person,true)}</div><div class="field"><label for="person-file">${person.avatar?'替换头像':'上传头像'}</label><input id="person-file" type="file" name="file" accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"><p class="form-help">JPEG、PNG 或 WebP，单张不超过 5 MiB。</p><div data-file-status></div></div>${inputField('avatar_source','头像来源',person.avatar_source,'来源链接或说明',true)}${person.avatar?'<label class="check-label"><input type="checkbox" name="remove_avatar" value="yes">移除当前头像（历史保留）</label>':''}</section>
    ${richEditor('introduction_html','人物介绍',person.introduction_html)}${textField('sources','参考出处',person.sources,'链接、文献名称及可定位的章节 / 页码')}${textField('change_note','本次维护依据 / 说明 *','','说明此次登记或修订所据材料')}
    </div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">关闭并保留草稿</button><button class="button primary" type="submit">保存人物档案</button></div></form>`);
  const form=document.querySelector('[data-form=person]');
  form.elements.name.required=true;form.elements.change_note.required=true;
  await enableEditorDraft(form,state.editing,'',draftKey);
}

async function submitPersonForm(form) {
  if(form.dataset.saving==='true')return;
  if(form._conflictPending)throw new Error('请先对照最新版本，再继续保存。');
  if(form._draftOffer)throw new Error('请先处理已有草稿。');
  syncRichForm(form);saveEditorDraft(form,true);
  const data=Object.fromEntries(new FormData(form));delete data.file;
  data.version=form._editing.version;data.remove_avatar=form.elements.remove_avatar?.checked||false;
  const file=form._draftFile||form.elements.file.files[0];
  if(file&&data.remove_avatar)throw new Error('请选择替换头像或移除当前头像其中一项。');
  const payload=new FormData();payload.set('data',JSON.stringify(data));if(file)payload.set('file',file,file.name);
  form.dataset.saving='true';
  try {
    const id=form._editing.id,result=await api('/api/people'+(id?'/'+encodeURIComponent(id):''),{method:id?'PUT':'POST',body:payload});
    await clearEditorDraft(form);form.dataset.saving='false';closeModal();toast('人物档案已保存');go('people',{id:result.id});
  } finally {form.dataset.saving='false';}
}

async function personConflict(form) {
  form._conflictPending=true;form._dirty=true;saveEditorDraft(form,true);
  const latest=await api('/api/people/'+encodeURIComponent(form._editing.id));
  if(!form.isConnected||form.dataset.draftUser!==state.me?.id)return;
  const draft=collectDraft(form).values,labels={name:'显示姓名',original_name:'原名',chinese_name:'中文名',aliases:'其他姓名写法',sources:'参考出处',avatar_source:'头像来源',change_note:'维护依据 / 说明'};
  form.querySelector('[data-conflict-panel]')?.remove();
  const panel=document.createElement('section');panel.className='conflict-panel';panel.dataset.conflictPanel='';panel._latest=latest;
  panel.innerHTML=`<h3>已有新版本，你的输入和待上传头像仍保留</h3><p>你基于版本 ${form._editing.version} 编辑，当前为版本 ${latest.version}。对照后可继续整理。</p><div class="comparison-grid"><section><h4>你的介绍草稿</h4><div class="rich-prose">${readRich(draft.introduction_html)}</div><p>头像操作：${form._draftFile?'上传 '+esc(form._draftFile.name):form.elements.remove_avatar?.checked?'移除当前头像':'保留服务器当前头像'}</p></section><section><h4>最新介绍</h4><div class="rich-prose">${readRich(latest.introduction_html)}</div>${personAvatar(latest,true)}</section></div><div class="table-scroll"><table class="comparison-table"><thead><tr><th>项目</th><th>你的输入</th><th>最新内容</th></tr></thead><tbody>${Object.entries(labels).filter(([key])=>draft[key]!==latest[key]).map(([key,label])=>`<tr><th>${label}</th><td>${esc(draft[key])}</td><td>${esc(latest[key])}</td></tr>`).join('')}</tbody></table></div><button type="button" class="button primary" data-action="person-accept-latest">已对照，以新版本继续编辑</button>`;
  form.querySelector('.form-actions').before(panel);panel.scrollIntoView({block:'nearest'});
}

async function personHistory(id) {
  const [person,history]=await Promise.all([api('/api/people/'+encodeURIComponent(id)),api('/api/people/'+encodeURIComponent(id)+'/history')]);
  modal(person.name+' · 修改历史',`<p class="notice">恢复会形成新版本，保留全部修订及头像。</p><div class="person-history">${history.items.map(item=>`<details class="person-history-item"><summary><strong>版本 ${item.version}</strong> · ${esc(item.action)}<span>${esc(item.actor_name)} · ${dateTime(item.created_at)}</span></summary><div class="person-history-content"><h3>${esc(item.snapshot.name)}</h3>${personNames(item.snapshot).length?`<p>${esc(personNames(item.snapshot).join(' · '))}</p>`:''}${personAvatar(item.snapshot,true)}${item.snapshot.avatar_source?`<p>头像来源：${esc(item.snapshot.avatar_source)}</p>`:''}<div class="rich-prose">${readRich(item.snapshot.introduction_html)}</div><p class="prose"><strong>参考出处：</strong>${esc(item.snapshot.sources||'未填写')}</p><p><strong>维护依据：</strong>${esc(item.snapshot.change_note)}</p>${item.can_restore&&item.version!==person.version?`<form data-form="person-restore" data-person="${esc(id)}" data-revision="${item.id}" data-version="${person.version}"><div class="field"><label>恢复依据 / 说明<textarea name="change_note" required></textarea></label></div><p class="form-error" role="alert"></p><div data-restore-conflict></div><button class="button" type="submit">恢复为当前内容</button></form>`:'<p class="muted">当前版本</p>'}</div></details>`).join('')}</div>`);
}

async function restorePersonForm(form) {
  if(form.dataset.conflict==='true')throw new Error('请先对照当前版本，再确认恢复。');
  try {
    await api(`/api/people/${encodeURIComponent(form.dataset.person)}/restore/${form.dataset.revision}`,{method:'POST',body:{version:Number(form.dataset.version),change_note:form.elements.change_note.value}});
    closeModal();toast('已恢复为新版本');go('people',{id:form.dataset.person});
  } catch(error) {
    if(error.status===409){
      const latest=await api('/api/people/'+encodeURIComponent(form.dataset.person));
      form.dataset.conflict='true';form._restoreLatest=latest;
      form.querySelector('[data-restore-conflict]').innerHTML=`<div class="notice"><p>当前已变为版本 ${latest.version}，恢复说明已保留。请核对最新内容：</p><h3>${esc(latest.name)}</h3>${personAvatar(latest,true)}<div class="rich-prose">${readRich(latest.introduction_html)}</div><p class="prose">${esc(latest.sources)}</p><button type="button" class="button" data-action="person-review-restore">已对照，继续恢复所选历史</button></div>`;
    }
    throw error;
  }
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action]');if(!button)return;
  try {
    if(button.dataset.action==='new-person')await personForm();
    else if(button.dataset.action==='edit-person')await personForm(button.dataset.id);
    else if(button.dataset.action==='person-history')await personHistory(button.dataset.id);
    else if(button.dataset.action==='people-clear')go('people');
    else if(button.dataset.action==='person-accept-latest'){
      const panel=button.closest('[data-conflict-panel]'),form=panel.closest('form'),latest=panel._latest;
      form._editing.version=latest.version;form._editing.original=latest;form._conflictPending=false;
      form.querySelector('[data-person-current-avatar]').innerHTML=personAvatar(latest,true);panel.remove();
      form.querySelector('.form-error').textContent='';saveEditorDraft(form,true);toast('输入仍保留，请检查后保存。');
    } else if(button.dataset.action==='person-review-restore'){
      const form=button.closest('form');form.dataset.version=form._restoreLatest.version;form.dataset.conflict='false';
      form.querySelector('[data-restore-conflict]').innerHTML='';form.querySelector('.form-error').textContent='已采用最新版本，请确认后提交恢复。';
    }
  } catch(error){toast(error.message);}
});
