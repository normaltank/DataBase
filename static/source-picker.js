'use strict';

// Stable select values remain the form/draft contract. The bounded candidate
// view adds search and ordinary checkboxes without changing relationship roles.
const sourceGroups={institution:'机构',journal:'期刊',publication:'其他出版物'};
let sourceSelectCounter=0;
function sourceById(id){return state.sources.find(s=>s.id===id||(s.previous_ids||[]).includes(id));}
function sourceSelectionIds(values){return [...new Set((Array.isArray(values)?values:String(values||'').split(/[|;,]/).map(v=>v.trim()).filter(Boolean)).map(v=>sourceById(v)?.id||v))];}
function restoreSourceSelection(select,values){
  const selected=sourceSelectionIds(values);
  if(select.multiple)for(const option of select.options)option.selected=selected.includes(option.value);
  else select.value=selected[0]||'';
}
function sourceScopeMatches(source,group='',country='',international=''){
  return (!group||source.group===group)&&(!country||(country==='__pending__'?!source.filter_countries.length:source.filter_countries.includes(country)))&&(!international||source.kind==='journal'&&source.international_status===international);
}
function sourceChoiceText(source){return source.name+' · '+sourceLabel(source)+' · '+(source.filter_countries?.join(' / ')||'国别待确认');}
function searchableSourceField(name,label,values=[],options={}){
  const id='source-select-'+(++sourceSelectCounter),selected=sourceSelectionIds(values);
  const allowed=state.sources.filter(s=>(!options.groups||options.groups.includes(s.group))&&s.id!==options.exclude);
  const groups=Object.fromEntries(Object.entries({...sourceGroups,maintenance:'资料发现网站'}).filter(([group])=>options.groups?options.groups.includes(group):allowed.some(s=>s.group===group)));
  const select=`<select id="${id}" ${name?`name="${name}"`:''} ${options.multiple?'multiple':''} ${options.rel?'data-rel="target_id"':''} data-source-values hidden aria-hidden="true" tabindex="-1">${options.multiple?'':'<option value=""></option>'}${allowed.map(s=>`<option value="${esc(s.id)}" ${selected.includes(s.id)?'selected':''}>${esc(s.name)}</option>`).join('')}</select>`;
  const root=document.createElement('div');root.className='field source-select';root.dataset.sourceSelect='';root.dataset.fixedGroup=options.groups?.length===1?options.groups[0]:'';
  root.innerHTML=`<span class="field-label">${esc(label)}</span>${select}<div data-source-selected aria-label="${esc(label)}已选择"></div><details data-source-disclosure><summary>选择或调整${esc(label)}</summary><div class="source-select-search"><label for="${id}-search">搜索${esc(label)}</label><input id="${id}-search" type="search" data-source-search ${options.rel?'aria-required="true"':''} placeholder="显示名称、原名或别名" autocomplete="off"><div class="source-select-filters">${options.groups?.length===1?'':`<label>候选类型<select data-source-group>${selectOptions(groups,'','全部类型')}</select></label>`}<label>候选国别<select data-source-country>${selectOptions({...Object.fromEntries([...new Set(allowed.flatMap(s=>s.filter_countries||[]))].sort().map(c=>[c,c])),__pending__:'待确认'},'','全部国别')}</select></label></div><div data-source-candidates class="source-candidates"></div><div class="source-candidate-pages"><button type="button" class="button tiny" data-source-page="-1">上一组</button><button type="button" class="button tiny" data-source-page="1">下一组</button></div><p class="form-help" data-source-count role="status"></p></div></details><p class="error-text" data-source-error role="alert"></p>`;
  for(const value of selected)if(!allowed.some(s=>s.id===value)){const option=new Option(value,value,true,true);root.querySelector('select').add(option);}
  if(options.scope){root.dataset.fixedGroup=options.scope.group||'';root.dataset.scopeCountry=options.scope.country||'';root.dataset.international=options.scope.international||'';root.querySelector('.source-select-filters').remove();}
  renderSourceSelect(root);return root.outerHTML;
}
function renderSourceSelect(root){
  const select=root.querySelector('[data-source-values]'),selected=new Set([...select.selectedOptions].map(o=>o.value).filter(Boolean));
  const allowed=new Set([...select.options].map(o=>o.value)),group=root.dataset.fixedGroup||root.querySelector('[data-source-group]')?.value||'',country=root.dataset.scopeCountry||root.querySelector('[data-source-country]')?.value||'',international=root.dataset.international||'';
  const words=(root.querySelector('[data-source-search]').value||'').toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  const candidates=state.sources.filter(s=>allowed.has(s.id)&&sourceScopeMatches(s,group,country,international)&&words.every(w=>(s.name+' '+s.original_name+' '+s.aliases).toLocaleLowerCase().includes(w)));
  const page=Math.max(0,Math.min(Number(root.dataset.candidatePage)||0,Math.max(0,Math.ceil(candidates.length/8)-1)));root.dataset.candidatePage=page;
  root.querySelector('[data-source-selected]').innerHTML=[...selected].map(id=>{const s=state.sources.find(s=>s.id===id);return `<button type="button" class="source-selected-value" data-source-remove="${esc(id)}" aria-label="移除${esc(s?.name||id)}">${esc(s?sourceChoiceText(s):id)} <span aria-hidden="true">×</span></button>`;}).join('')||'<span class="small muted">尚未选择</span>';
  root.querySelector('[data-source-candidates]').innerHTML=candidates.slice(page*8,page*8+8).map(s=>`<label class="source-candidate"><input type="${select.multiple?'checkbox':'radio'}" data-source-option="${esc(s.id)}" ${selected.has(s.id)?'checked':''}><span>${esc(sourceChoiceText(s))}${s.original_name&&s.original_name!==s.name?`<small>${esc(s.original_name)}</small>`:''}</span></label>`).join('')||'<p class="small muted">没有匹配来源，请调整名称或候选条件。</p>';
  root.querySelector('[data-source-count]').textContent=`找到 ${candidates.length} 个候选 · 第 ${page+1} / ${Math.max(1,Math.ceil(candidates.length/8))} 组 · 已选 ${selected.size} 个`;
  root.querySelector('[data-source-page="-1"]').disabled=page===0;root.querySelector('[data-source-page="1"]').disabled=(page+1)*8>=candidates.length;
  root.querySelector('.source-candidate-pages').hidden=candidates.length<=8;
  if(selected.size)root.querySelector('[data-source-error]').textContent='';
}
function refreshSourcePickers(root){root.querySelectorAll('[data-source-select]').forEach(renderSourceSelect);}
function sourceSelectChanged(root,id,checked){
  const select=root.querySelector('[data-source-values]');
  for(const option of select.options)if(!select.multiple||option.value===id)option.selected=option.value===id&&checked;
  if(!select.multiple&&!checked)select.value='';
  renderSourceSelect(root);select.dispatchEvent(new Event('change',{bubbles:true}));
}
document.addEventListener('input',event=>{if(event.target.matches('[data-source-search]')){const root=event.target.closest('[data-source-select]');root.dataset.candidatePage=0;renderSourceSelect(root);}});
document.addEventListener('change',event=>{
  const root=event.target.closest('[data-source-select]');if(!root)return;
  if(event.target.matches('[data-source-group],[data-source-country]')){root.dataset.candidatePage=0;renderSourceSelect(root);}
  if(event.target.matches('[data-source-option]')){const id=event.target.dataset.sourceOption,checked=event.target.checked;sourceSelectChanged(root,id,checked);root.querySelector(`[data-source-option="${CSS.escape(id)}"]`)?.focus();}
});
document.addEventListener('click',event=>{
  const paging=event.target.closest('[data-source-page]');if(paging){const root=paging.closest('[data-source-select]');root.dataset.candidatePage=Number(root.dataset.candidatePage||0)+Number(paging.dataset.sourcePage);renderSourceSelect(root);return;}
  const remove=event.target.closest('[data-source-remove]');if(!remove)return;
  const root=remove.closest('[data-source-select]');sourceSelectChanged(root,remove.dataset.sourceRemove,false);root.querySelector('summary').focus();
});
document.addEventListener('submit',event=>{
  const missing=[...event.target.querySelectorAll('[data-source-values][data-rel="target_id"]')].find(select=>!select.value);if(!missing)return;
  event.preventDefault();event.stopImmediatePropagation();const root=missing.closest('[data-source-select]');root.querySelector('[data-source-disclosure]').open=true;root.querySelector('[data-source-error]').textContent='请选择已登记的关联机构。';root.querySelector('[data-source-search]').focus();
},true);
document.addEventListener('keydown',event=>{
  if(event.key==='ArrowDown'&&event.target.matches('[data-source-search]')){event.preventDefault();event.target.closest('[data-source-select]').querySelector('[data-source-option]')?.focus();}
});

function librarySourceFilters(p){
  const countries=[...new Set(state.sources.filter(s=>s.group!=='maintenance').flatMap(s=>s.filter_countries||[]))].sort();
  return `<div class="field"><label for="filter-source-group">来源类型</label><select id="filter-source-group" name="source_group">${selectOptions(sourceGroups,p.get('source_group'),'全部来源类型')}</select></div><div class="field"><label for="filter-source-country">来源国别</label><select id="filter-source-country" name="source_country">${selectOptions({...Object.fromEntries(countries.map(c=>[c,c])),__pending__:'待确认'},p.get('source_country'),'全部来源国别')}</select></div><div class="field"><label for="filter-source-international">国际办刊定位</label><select id="filter-source-international" name="source_international" ${p.get('source_group')&&p.get('source_group')!=='journal'?'disabled':''}>${selectOptions(internationalLabels,p.get('source_international'),'全部国际定位')}</select><span class="form-help">仅适用于期刊</span></div>${searchableSourceField('source','具体来源（可选）',p.get('source'),{groups:['institution','journal','publication'],scope:{group:p.get('source_group'),country:p.get('source_country'),international:p.get('source_international')}})}<p class="form-help source-range-notice" data-source-range-notice role="status">来源国别与资料研究对象分别筛选；发布、刊载或一般关联的同一来源须满足所有来源条件。</p>`;
}
document.addEventListener('change',event=>{
  const form=event.target.closest('[data-form="filters"]');if(!form||!['source_group','source_country','source_international'].includes(event.target.name))return;
  const group=form.elements.source_group.value,international=form.elements.source_international;
  international.disabled=!!group&&group!=='journal';if(international.disabled)international.value='';
  const root=form.querySelector('[data-source-select]'),select=root.querySelector('[data-source-values]');
  root.dataset.fixedGroup=group;root.dataset.scopeCountry=form.elements.source_country.value;root.dataset.international=international.value;
  if(select.value){const selected=state.sources.find(s=>s.id===select.value);if(!selected||!sourceScopeMatches(selected,group,root.dataset.scopeCountry,international.value)){select.value='';form.querySelector('[data-source-range-notice]').textContent='已清除不符合新来源范围的具体来源，请应用筛选。';}}
  renderSourceSelect(root);
});
