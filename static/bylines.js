'use strict';

function bylineIdentity(item) {
  const target=item.target;
  if(!target)return '<span class="muted">身份待确认</span>';
  return `<button type="button" class="link-button" data-action="byline-target" data-type="${esc(target.type)}" data-id="${esc(target.id)}" data-record="${esc(item.record_id)}">${esc(target.name)}</button><span class="small muted">${target.type==='person'?'个人作者':'机构作者'}</span>`;
}

function bylineList(items) {
  return items.length?`<ol class="byline-list">${items.map(item=>`<li><div class="row wrap"><strong>${esc(item.raw_name)}</strong><span class="badge ${item.status==='confirmed'?'verified':'pending'}">${item.status==='confirmed'?'已确认署名':'署名待确认'}</span></div><div class="row wrap">${bylineIdentity(item)}</div>${item.evidence?`<p class="small prose">依据：${esc(item.evidence)}</p>`:''}</li>`).join('')}</ol>`:'<p class="muted">尚未整理署名，原始文字仍保留。</p>';
}

async function bylineSection(record) {
  if(isResearchContent(record.kind))return '';
  const data=await api(`/api/records/${encodeURIComponent(record.id)}/bylines`);
  const originals=[...new Set(data.items.map(item=>item.original_authors).filter(text=>text&&text!==data.raw_authors))];
  return `<section class="detail-section byline-section"><div class="between wrap"><h3>作品署名</h3><div class="row wrap">${linkButton('整理署名','edit-bylines',record.id)}${linkButton('署名历史','byline-history',record.id)}</div></div><details><summary>原始整段署名</summary><p class="prose">${esc(data.raw_authors||'原始资料未登记署名')}</p>${originals.map(text=>`<p class="prose small">首次整理保留的原始署名：${esc(text)}</p>`).join('')}</details>${bylineList(data.items)}</section>`;
}

function bylineWorksMarkup(data,type,id,query='') {
  return `<section class="person-section detail-section byline-works" data-byline-works data-type="${esc(type)}" data-id="${esc(id)}"><h2>${type==='institution'?'机构署名作品':'已确认作品'}</h2><form data-form="byline-work-search" class="byline-search field"><input type="search" name="q" aria-label="搜索已确认作品" placeholder="在已确认作品中搜索" value="${esc(query)}"><button class="button" type="submit">搜索</button></form><p class="small muted">${data.total} 份已确认作品${query?' · '+esc(query):''}</p>${data.items.map(record=>`<article class="byline-work"><h3>${linkButton(esc(record.title),'detail',record.id,'title-button')}</h3><p class="small muted">${esc([record.published_on,record.authors].filter(Boolean).join(' · '))}</p>${record.bylines.map(item=>`<p class="small">署名：${esc(item.raw_name)}${item.evidence?' · 依据：'+esc(item.evidence):''}</p>`).join('')}</article>`).join('')||`<p class="muted">${query?'没有符合条件的已确认作品。':'暂未关联已确认作品。这只表示当前档案的收录情况。'}</p>`}${data.total>data.size?`<div class="pagination">${data.page>1?linkButton('上一页','byline-work-page',String(data.page-1)):''}<span>第 ${data.page} / ${Math.ceil(data.total/data.size)} 页</span>${data.page*data.size<data.total?linkButton('下一页','byline-work-page',String(data.page+1)):''}</div>`:''}</section>`;
}

async function bylineWorksSection(type,id,query='',page=1) {
  const root=type==='person'?'people':'sources';
  const data=await api(`/api/${root}/${encodeURIComponent(id)}/works?`+new URLSearchParams({q:query,page}));
  return bylineWorksMarkup(data,type,id,query);
}

let bylineRowNumber=0,bylineSearchTimer;
function bylineRow(item={}) {
  const key='byline-row-'+(++bylineRowNumber),target=item.target;
  return `<fieldset class="byline-editor-row" data-byline-row data-id="${esc(item.id||'')}"><legend>署名片段</legend><div class="form-grid"><div class="field wide"><label for="${key}-raw">原始署名片段 *</label><textarea id="${key}-raw" data-byline="raw_name" required>${esc(item.raw_name)}</textarea></div><div class="field"><label for="${key}-status">确认状态</label><select id="${key}-status" data-byline="status"><option value="pending" ${item.status!=='confirmed'?'selected':''}>待确认</option><option value="confirmed" ${item.status==='confirmed'?'selected':''}>已确认（需要依据）</option></select></div><div class="field"><label for="${key}-type">作者身份类型</label><select id="${key}-type" data-byline="target_type">${selectOptions({person:'个人',institution:'机构'},item.target_type||'','未指定身份')}</select></div><div class="field"><label for="${key}-search">搜索身份档案</label><input id="${key}-search" type="search" data-byline-search placeholder="先选个人或机构，再输入姓名 / 名称"><span class="form-help" data-byline-search-status></span></div><div class="field"><label for="${key}-target">选择身份档案</label><select id="${key}-target" data-byline="target_id"><option value="">保留待确认</option>${target?`<option value="${esc(target.id)}" selected>${esc(target.name)}</option>`:''}</select></div><div class="field wide"><label for="${key}-evidence">署名确认依据</label><textarea id="${key}-evidence" data-byline="evidence" placeholder="作者主页、机构介绍或作品署名等可定位信息">${esc(item.evidence)}</textarea></div></div><div class="row wrap"><button type="button" class="button tiny" data-action="byline-up">上移</button><button type="button" class="button tiny" data-action="byline-down">下移</button><button type="button" class="button tiny" data-action="byline-remove">移除这项署名</button></div></fieldset>`;
}

function collectBylines(form) {
  return [...form.querySelectorAll('[data-byline-row]')].map(row=>{
    const value=Object.fromEntries([...row.querySelectorAll('[data-byline]')].map(el=>[el.dataset.byline,el.value]));
    if(!value.target_id)value.target_type='';
    return {...value,reconfirm:row.dataset.identityAdjusted==='true',target_name:row.querySelector('[data-byline=target_id]').selectedOptions[0]?.textContent||'',...(row.dataset.id?{id:row.dataset.id}:{})};
  });
}

function syncBylineForm(form) {
  form.elements.bylines_json.value=JSON.stringify(collectBylines(form));
  [...form.querySelectorAll('[data-byline-row]')].forEach((row,index,rows)=>{
    row.querySelector('legend').textContent='署名 '+(index+1);
    row.querySelector('[data-action=byline-up]').disabled=index===0;
    row.querySelector('[data-action=byline-down]').disabled=index===rows.length-1;
    const confirmed=row.querySelector('[data-byline=status]').value==='confirmed';
    row.querySelector('[data-byline=target_id]').required=confirmed;
    row.querySelector('[data-byline=evidence]').required=confirmed;
  });
}

async function bylineForm(id,draftKey='') {
  const [record,data]=await Promise.all([api('/api/records/'+encodeURIComponent(id)),api(`/api/records/${encodeURIComponent(id)}/bylines`)]);
  state.editing={type:'byline',id,version:data.version,draftSpecific:{record_version:data.record_version},original:{...record,kind:'byline'}};state.links=[];
  modal('整理作品署名',`<form data-form="byline" class="workflow-form"><input type="hidden" name="title" value="${esc(record.title)}"><input type="hidden" name="bylines_json" value=""><h3>${esc(record.title)}</h3><p class="notice">署名由成员共同维护，每次确认需有可核查依据。原始资料正文继续按原有授权编辑。</p><details open><summary>原始整段署名</summary><p class="prose">${esc(data.raw_authors||'原始资料未登记署名')}</p></details><div data-byline-rows>${data.items.map(bylineRow).join('')}</div><button type="button" class="button" data-action="byline-add">添加署名片段</button><div class="field section-gap"><label for="byline-change-note">本次维护依据 / 纠正说明 *</label><textarea id="byline-change-note" name="change_note" required></textarea></div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="byline-cancel" data-id="${esc(id)}">返回资料并保留草稿</button><button class="button primary" type="submit">保存署名</button></div></form>`);
  const form=document.querySelector('[data-form=byline]');
  syncBylineForm(form);await enableEditorDraft(form,state.editing,'',draftKey);
}

function restoreBylineDraft(form,draft) {
  form._bylineBodyConflict=draft.specific.record_version!==form._editing.draftSpecific.record_version;
  form._editing.draftSpecific={...draft.specific};
  const items=JSON.parse(form.elements.bylines_json.value||'[]');
  form.querySelector('[data-byline-rows]').innerHTML=items.map(item=>bylineRow({...item,target:item.target_id?{id:item.target_id,name:item.target_name||item.target_id}:null})).join('');
  [...form.querySelectorAll('[data-byline-row]')].forEach((row,index)=>row.dataset.identityAdjusted=String(!!items[index].reconfirm));
  syncBylineForm(form);
}

async function bylineConflict(form) {
  form._conflictPending=true;form._dirty=true;saveEditorDraft(form,true);
  const latest=await api(`/api/records/${encodeURIComponent(form._editing.id)}/bylines`);
  if(!form.isConnected||form.dataset.draftUser!==state.me?.id)return;
  form.querySelector('[data-conflict-panel]')?.remove();
  const panel=document.createElement('section');panel.className='conflict-panel';panel.dataset.conflictPanel='';panel._latest=latest;
  panel.innerHTML=`<h3>署名或原始资料已有新版本，你的输入仍保留</h3><p>你基于署名版本 ${form._editing.version} 整理，当前为版本 ${latest.version}。请对照最新题录与署名；已被移除的条目需要移出草稿，或在署名历史中明确恢复。</p><p class="prose">当前原始整段署名：${esc(latest.raw_authors||'未登记')}</p>${bylineList(latest.items)}<div class="row wrap"><button type="button" class="button primary" data-action="byline-accept-latest">已对照，保留我的整理继续编辑</button><button type="button" class="button" data-action="byline-use-server">采用最新署名列表</button></div>`;
  form.querySelector('.form-actions').before(panel);panel.scrollIntoView({block:'nearest'});
}

async function submitBylineForm(form) {
  if(form.dataset.saving==='true')return;
  if(form._conflictPending)throw new Error('请先对照最新署名，再继续保存。');
  if(form._draftOffer)throw new Error('请先处理已有草稿。');
  syncBylineForm(form);form._dirty=true;saveEditorDraft(form,true);form.dataset.saving='true';
  try {
    await api(`/api/records/${encodeURIComponent(form._editing.id)}/bylines`,{method:'PUT',body:{version:form._editing.version,record_version:form._editing.draftSpecific.record_version,items:collectBylines(form),change_note:form.elements.change_note.value}});
    const id=form._editing.id;await clearEditorDraft(form);form.dataset.saving='false';closeModal();if(typeof uxRefreshBackground==='function')await uxRefreshBackground();await openRecord(id);toast('署名已保存');
  } finally {form.dataset.saving='false';}
}

function bylineHistoryValue(item) {
  if(!item)return '<p class="muted">此前尚未建立这项署名</p>';
  return `<p><strong>${esc(item.raw_name)}</strong> · ${item.removed_at?'已移除':item.status==='confirmed'?'已确认':'待确认'} · 顺序 ${item.position}</p><p>${esc(item.target?.name||'未指定身份')} ${item.target?'（'+esc(item.target.type==='person'?'个人':'机构')+'）':''}</p><p class="prose small">依据：${esc(item.evidence||'未填写')}</p>`;
}

async function bylineHistory(id) {
  const [current,history]=await Promise.all([api(`/api/records/${encodeURIComponent(id)}/bylines`),api(`/api/records/${encodeURIComponent(id)}/bylines/history`)]);
  const labels={manual:'人工维护',manual_confirmation:'明确确认署名身份',record_merge:'资料合并转接',source_merge:'来源合并转接',order_adjustment:'署名顺序整理',person_merge:'人物合并转接',person_split:'人物拆回转接',person_split_review:'人物拆回后署名待确认'};
  modal('作品署名历史',`<p class="notice">署名历史独立保留。恢复正文历史会保留当前公共署名；在这里可以明确恢复某一项署名。</p><div class="person-history">${history.items.map(item=>`<details class="person-history-item"><summary><strong>${esc(item.after.raw_name)}</strong> · ${esc(labels[item.change_kind]||item.change_kind)}<span>${esc(item.actor_name)} · ${dateTime(item.created_at)}</span></summary><div class="person-history-content"><p class="prose">维护说明：${esc(item.change_note)}</p><div class="comparison-grid"><section><h4>修改前</h4>${bylineHistoryValue(item.before)}</section><section><h4>修改后 · 关系版本 ${item.after.version}</h4>${bylineHistoryValue(item.after)}</section></div><details><summary>保留的原始整段署名</summary><p class="prose">${esc(item.after.original_authors)}</p></details><form data-form="byline-restore" data-record="${esc(id)}" data-revision="${item.id}" data-version="${current.version}"><div class="field"><label>恢复这一项至修改后状态的依据<textarea name="change_note" required></textarea></label></div><div class="form-error" role="alert"></div><div data-restore-conflict></div><button class="button" type="submit">恢复这一项署名</button></form></div></details>`).join('')||'<p class="muted">尚无署名维护历史。</p>'}</div>${linkButton('返回资料','byline-back',id)}`);
}

async function restoreBylineForm(form) {
  if(form.dataset.conflict==='true')throw new Error('请先对照最新署名，再确认恢复。');
  try {
    await api(`/api/records/${encodeURIComponent(form.dataset.record)}/bylines/history/${form.dataset.revision}/restore`,{method:'POST',body:{version:Number(form.dataset.version),change_note:form.elements.change_note.value}});
    if(typeof uxRefreshBackground==='function')await uxRefreshBackground();await openRecord(form.dataset.record);toast('已恢复这一项署名，历史继续保留');
  } catch(error) {
    if(error.status===409){const latest=await api(`/api/records/${encodeURIComponent(form.dataset.record)}/bylines`);form.dataset.conflict='true';form._restoreLatest=latest;form.querySelector('[data-restore-conflict]').innerHTML=`<div class="notice"><p>当前署名已变为版本 ${latest.version}，恢复说明已保留。</p>${bylineList(latest.items)}<button type="button" class="button" data-action="byline-review-restore">已对照，继续恢复所选署名</button></div>`;}
    throw error;
  }
}

async function searchBylineIdentity(input) {
  const row=input.closest('[data-byline-row]'),kind=row.querySelector('[data-byline=target_type]').value,query=input.value.trim(),status=row.querySelector('[data-byline-search-status]');
  if(!kind){status.textContent='请先选择个人或机构。';return;}
  const result=await api(kind==='person'?'/api/people?page_size=100&q='+encodeURIComponent(query):'/api/sources?q='+encodeURIComponent(query));
  if(!row.isConnected||input.value.trim()!==query||row.querySelector('[data-byline=target_type]').value!==kind)return;
  const items=result.items.filter(item=>kind==='person'||isInstitution(item)),select=row.querySelector('[data-byline=target_id]'),chosen=select.selectedOptions[0];
  const retained=chosen?.value&&!items.some(item=>item.id===chosen.value)?chosen.outerHTML:'';
  select.innerHTML='<option value="">保留待确认</option>'+retained+items.map(item=>`<option value="${esc(item.id)}" ${item.id===chosen?.value?'selected':''}>${esc(item.name)}${item.original_name&&item.original_name!==item.name?' · '+esc(item.original_name):''}${personHint(item,65)?' · '+esc(personHint(item,65)):''} · ${esc(item.id.slice(-8))}</option>`).join('');
  status.textContent=items.length?'找到 '+items.length+' 项，请核实后选择。'+(result.total>items.length?'可以补充姓名缩小范围。':''):'没有找到档案；可先保留待确认，再核实建档。';
}

document.addEventListener('input',event=>{
  const form=event.target.closest('[data-form=byline]');if(!form)return;
  syncBylineForm(form);
  if(event.target.matches('[data-byline-search]')){clearTimeout(bylineSearchTimer);const input=event.target;bylineSearchTimer=setTimeout(()=>searchBylineIdentity(input).catch(error=>{if(input.isConnected)input.closest('[data-byline-row]').querySelector('[data-byline-search-status]').textContent=error.message;}),250);}
},true);
document.addEventListener('change',event=>{
  const form=event.target.closest('[data-form=byline]');if(!form)return;
  if(event.target.matches('[data-byline=target_type],[data-byline=target_id]')||(event.target.matches('[data-byline=status]')&&event.target.value==='confirmed'))event.target.closest('[data-byline-row]').dataset.identityAdjusted='true';
  if(event.target.matches('[data-byline=target_type]')){const row=event.target.closest('[data-byline-row]');row.querySelector('[data-byline=target_id]').innerHTML='<option value="">保留待确认</option>';row.querySelector('[data-byline-search]').value='';row.querySelector('[data-byline-search-status]').textContent='';}
  syncBylineForm(form);
},true);
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action]');if(!button)return;
  const action=button.dataset.action,form=button.closest('[data-form=byline]');
  try {
    if(action==='edit-bylines')await bylineForm(button.dataset.id);
    else if(action==='byline-history')await bylineHistory(button.dataset.id);
    else if(action==='byline-cancel'){if(closeModal()!==false)await openRecord(button.dataset.id);}
    else if(action==='byline-back'){if(typeof continuityReturn!=='function'||!await continuityReturn(button.dataset.id))await openRecord(button.dataset.id);}
    else if(action==='byline-target'){
      if(closeModal(false)===false)return;
      if(button.dataset.type==='person')go('people',{id:button.dataset.id,work:button.dataset.record});
      else{state.bylineSourceReturn={id:button.dataset.id,record:button.dataset.record};await openSource(button.dataset.id);}
    } else if(action==='byline-add'){form.querySelector('[data-byline-rows]').insertAdjacentHTML('beforeend',bylineRow());syncBylineForm(form);form._dirty=true;saveEditorDraft(form,true);form.querySelector('[data-byline-row]:last-child textarea').focus();}
    else if(['byline-up','byline-down','byline-remove'].includes(action)){
      const row=button.closest('[data-byline-row]');
      if(action==='byline-remove')row.remove();else if(action==='byline-up'&&row.previousElementSibling)row.previousElementSibling.before(row);else if(action==='byline-down'&&row.nextElementSibling)row.nextElementSibling.after(row);
      syncBylineForm(form);form._dirty=true;saveEditorDraft(form,true);
    } else if(action==='byline-accept-latest'||action==='byline-use-server'){
      const panel=button.closest('[data-conflict-panel]'),current=panel.closest('form'),latest=panel._latest;
      if(action==='byline-use-server')current.querySelector('[data-byline-rows]').innerHTML=latest.items.map(bylineRow).join('');
      current._editing.version=latest.version;current._editing.draftSpecific={record_version:latest.record_version};current._conflictPending=false;panel.remove();current.querySelector('.form-error').textContent='';syncBylineForm(current);saveEditorDraft(current,true);
    } else if(action==='byline-review-restore'){const current=button.closest('form');current.dataset.version=current._restoreLatest.version;current.dataset.conflict='false';current.querySelector('[data-restore-conflict]').innerHTML='';current.querySelector('.form-error').textContent='已采用最新版本，请再次确认恢复。';}
    else if(action==='byline-work-page'){const section=button.closest('[data-byline-works]');section.outerHTML=await bylineWorksSection(section.dataset.type,section.dataset.id,section.querySelector('[name=q]').value,Number(button.dataset.id));}
  } catch(error){toast(error.message);}
});
document.addEventListener('submit',async event=>{
  const form=event.target.closest('[data-form=byline-work-search]');if(!form)return;event.preventDefault();
  const section=form.closest('[data-byline-works]');
  try{section.outerHTML=await bylineWorksSection(section.dataset.type,section.dataset.id,form.elements.q.value);}catch(error){toast(error.message);}
});
