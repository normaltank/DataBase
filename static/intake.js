'use strict';

const intakeLabels={title:'题名',authors:'原始署名',published_on:'发表日期',publication_title:'刊物名称',doi:'DOI',url:'原文链接',abstract:'摘要',language:'语言'};
function intakeEvidenceHtml(evidence){
  if(!evidence?.length)return '';
  return '<details class="intake-evidence"><summary>辅助录入取得依据</summary><p class="form-help">以下为取得时的题录，当前字段可能经过人工修改。仅取得题录，不代表已保存全文、附件或完成核对。</p>'+evidence.map(e=>'<section><p>输入：'+esc(e.input)+'<br>取得时间：'+esc(e.retrieved_at)+'</p>'+(e.sources||[]).map(s=>'<p>'+esc(s.provider)+' · '+externalLink(s.url,'取得来源')+'</p>').join('')+'<details><summary>原始题录与外部标识</summary><pre>'+esc(JSON.stringify(e,null,2))+'</pre></details></section>').join('')+'</details>';
}
function prepareIntakeForm(form){
  if(form._editing.id||isResearchContent(form.elements.kind.value))return;
  const section=document.createElement('section');section.className='intake-editor wide';section.dataset.intakeEditor='';
  section.innerHTML='<h3>粘贴 DOI 或文章链接</h3><p class="form-help">取得后先预览，再选择应用。缺失或失败时可继续手填。</p><label for="intake-input">DOI / 公开文章网址</label><div class="intake-input-row"><input id="intake-input" name="intake_input" placeholder="10.… 或 https://…" autocomplete="off"><button type="button" class="button" data-intake-fetch>取得题录</button></div><div data-intake-status role="status" aria-live="polite"></div><div data-intake-preview></div><input type="hidden" name="intake_token"><input type="hidden" name="intake_preview"><input type="hidden" name="intake_byline_json"><input type="hidden" name="intake_preview_state">';
  form.querySelector('.form-grid').prepend(section);
  section.addEventListener('click',async event=>{
    if(event.target.closest('[data-intake-fetch]'))await requestIntake(form);
    if(event.target.closest('[data-intake-apply]'))applyIntake(form);
    if(event.target.closest('[data-intake-use-link]')){
      if(!form.elements.url.value.trim()){
        try{const u=new URL(form.elements.intake_input.value);if(['http:','https:'].includes(u.protocol)&&!u.username&&!u.password)form.elements.url.value=u.href;}catch{}
      }
      form._dirty=true;saveEditorDraft(form,true);
    }
  });
  section.addEventListener('input',event=>{
    if(event.target.name==='intake_input'){
      form._intakeGeneration=(form._intakeGeneration||0)+1;
      if(form._intakePending)form.querySelector('[data-intake-status]').textContent='输入已更改，旧请求不会应用；请重新取得题录。';
    }
    const authors=intakeBylines(form,false),sources=Object.fromEntries([...form.querySelectorAll('[data-intake-source]')].map(el=>[el.dataset.intakeSource,el.value])),replace=[...form.querySelectorAll('[data-intake-replace]:checked')].map(el=>el.dataset.intakeReplace);
    form.elements.intake_preview_state.value=JSON.stringify({authors,sources,replace});
    if(form._intakePreview?.token===form.elements.intake_token.value)form.elements.intake_byline_json.value=JSON.stringify(authors);
    form._dirty=true;saveEditorDraft(form,true);
  });
}
function restoreIntakeForm(form){
  if(!form.querySelector('[data-intake-editor]'))return;
  form._intakeGeneration=(form._intakeGeneration||0)+1;
  try{form._intakePreview=JSON.parse(form.elements.intake_preview.value||'null');}catch{form._intakePreview=null;}
  renderIntakePreview(form);
  if(form.elements.intake_token.value)form.querySelector('[data-intake-status]').textContent='已恢复取得依据与关联选择；可继续核对、修改和保存。';
}
async function requestIntake(form){
  if(form._draftOffer){form.querySelector('[data-intake-status]').textContent='请先恢复或舍弃已有草稿。';return;}
  const value=form.elements.intake_input.value.trim(),account=state.me?.id,generation=(form._intakeGeneration||0)+1;
  form._intakeGeneration=generation;form._intakePending=true;const status=form.querySelector('[data-intake-status]');status.textContent='正在取得题录，可继续手填；结果先进入预览。';
  const active=()=>form.isConnected&&state.me?.id===account&&form._intakeGeneration===generation&&form.elements.intake_input.value.trim()===value;
  try{
    const result=await api('/api/intake/preview',{method:'POST',body:{input:value}});
    if(!active())return;
    form._intakePreview=result;form.elements.intake_preview.value=JSON.stringify(result);form.elements.intake_preview_state.value='';renderIntakePreview(form);
    status.textContent='题录已取得，请核对后应用。';form._dirty=true;saveEditorDraft(form,true);
  }catch(error){if(active()){status.textContent=error.message+' 已有输入保留，可继续手填。';status.insertAdjacentHTML('beforeend',' <button type="button" class="button tiny" data-intake-use-link>将输入链接填到空白原文链接</button>');}}
  finally{if(form._intakeGeneration===generation)form._intakePending=false;}
}
function renderIntakePreview(form){
  const p=form._intakePreview,holder=form.querySelector('[data-intake-preview]');if(!p||!holder)return;
  let selection={};try{selection=JSON.parse(form.elements.intake_preview_state.value||'{}');}catch{}
  let saved=selection.authors||[];
  holder.innerHTML='<section class="intake-preview"><h4>取得预览</h4><p class="form-help">只填入空白字段；勾选某字段才替换已有内容。姓名匹配只是线索，身份关联需要明确确认。</p>'
    +(p.warnings||[]).map(w=>'<p class="notice">'+esc(w)+'</p>').join('')
    +(p.duplicates?.length?'<div class="notice"><strong>已收录候选</strong>'+p.duplicates.map(d=>'<button type="button" class="detail-link" data-action="detail" data-id="'+esc(d.id)+'">'+esc(d.title)+' · '+esc(d.basis)+'</button>').join('')+'<p>请先查看，保存时仍会检查重复。</p></div>':'')
    +'<div class="intake-fields">'+Object.entries(p.fields).filter(([key,value])=>value&&intakeLabels[key]).map(([key,value])=>'<div class="intake-field"><strong>'+esc(intakeLabels[key])+'</strong><p>'+esc(value)+'</p><span class="form-help">依据：'+esc(p.provenance[key]||'文章网址')+'</span><label class="check-label"><input type="checkbox" data-intake-replace="'+esc(key)+'" '+(selection.replace?.includes(key)?'checked':'')+'>替换此字段已有值</label></div>').join('')+'</div>'
    +'<fieldset class="intake-authors"><legend>原始署名与身份核对</legend>'+p.authors.map((author,index)=>{
      const row=saved[index],choices=p.candidates?.authors?.[index]?.items||[];
      return '<section data-intake-author="'+index+'"><label>原始署名<input data-intake-name value="'+esc(row?.raw_name||author.raw_name)+'"></label>'
        +'<p class="form-help">外部标识：'+esc(JSON.stringify(author.identifiers||{}))+(author.affiliations?.length?' · 文章署名单位线索：'+esc(author.affiliations.join('; ')):'')+'</p>'
        +'<label>已有作者／机构候选<select data-intake-target><option value="">保留待确认署名，之后补档</option>'+choices.map(c=>'<option value="'+esc(c.type+':'+c.id)+'" '+(row?.target_type+':'+row?.target_id===c.type+':'+c.id?'selected':'')+'>'+esc(c.name+' · '+c.basis)+'</option>').join('')+'</select></label>'
        +(p.candidates?.authors?.[index]?.truncated?'<p class="form-help">仅显示前 30 个同名候选（共 '+p.candidates.authors[index].total+' 个）；可先保留署名，保存后在作品署名维护中搜索完整档案。</p>':'')+'<label class="check-label"><input type="checkbox" data-intake-confirm '+(row?.status==='confirmed'?'checked':'')+'>我已核对所选身份，确认此署名属于该档案</label><label>身份确认依据<input data-intake-evidence value="'+esc(row?.evidence||'')+'" placeholder="文章署名页／作者主页与核对说明"></label></section>';
    }).join('')+'</fieldset>'
    +'<fieldset><legend>已有来源候选</legend>'+['source_id','serial_id'].map(field=>'<label>'+(field==='source_id'?'文章发布机构':'所属期刊／连续出版物')+'<select data-intake-source="'+field+'"><option value="">不自动关联，保留文字出处</option>'+(p.candidates?.sources||[]).filter(c=>c.field===field).map(c=>'<option value="'+esc(c.id)+'" '+(selection.sources?.[field]===c.id?'selected':'')+'>'+esc(c.name+' · '+c.basis)+'</option>').join('')+'</select></label>').join('')+(p.candidates?.sources_truncated?'<p class="form-help">仅显示前 50 个来源候选，可在表单来源选择器中搜索全部来源。</p>':'')+'<p class="form-help">明确选择后应用。发布商、主办方、署名单位和任职关系分别维护；不会推断国别或任职。</p></fieldset>'
    +intakeEvidenceHtml([p])+'<button type="button" class="button primary" data-intake-apply>应用预览及已核对选择</button><p class="form-help">仅取得题录，不下载全文或附件，不会自动标记已核对。</p></section>';
}
function intakeBylines(form,validate=true){
  return [...form.querySelectorAll('[data-intake-author]')].map(row=>{
    const selected=row.querySelector('[data-intake-target]').value,confirmed=row.querySelector('[data-intake-confirm]').checked;
    if(validate&&confirmed&&!selected)throw new Error('确认署名前请先选择对应身份。');
    const split=selected.indexOf(':'),evidence=row.querySelector('[data-intake-evidence]').value.trim();
    if(validate&&confirmed&&!evidence)throw new Error('确认署名需要填写可核查的依据。');
    return {raw_name:row.querySelector('[data-intake-name]').value,status:confirmed?'confirmed':'pending',target_type:selected?selected.slice(0,split):'',target_id:selected?selected.slice(split+1):'',evidence};
  });
}
function applyIntake(form){
  try{
    const p=form._intakePreview;if(!p)return;
    const items=intakeBylines(form);
    for(const [key,value] of Object.entries(p.fields)){
      const input=form.elements.namedItem(key);if(!input||!intakeLabels[key])continue;
      if(!input.value.trim()||form.querySelector('[data-intake-replace="'+key+'"]')?.checked){
        if(input.tagName==='SELECT'&&![...input.options].some(o=>o.value===value)){const option=new Option(value,value);input.add(option);}
        input.value=value;
      }
    }
    for(const select of form.querySelectorAll('[data-intake-source]'))if(select.value)restoreSourceSelection(form.elements.namedItem(select.dataset.intakeSource),select.value);
    refreshSourcePickers(form);
    form.elements.intake_token.value=p.token;form.elements.intake_byline_json.value=JSON.stringify(items);
    form.querySelector('[data-intake-status]').textContent='已应用到表单；已有字段仅按你的选择替换。可继续修改后保存。';
    form._dirty=true;saveEditorDraft(form,true);
  }catch(error){form.querySelector('[data-intake-status]').textContent=error.message;}
}
function intakeSaveValues(form,values){
  delete values.intake_input;delete values.intake_preview;delete values.intake_byline_json;delete values.intake_preview_state;
  if(!form.elements.intake_token?.value){delete values.intake_token;return;}
  if(isResearchContent(values.kind))throw new Error('辅助题录用于外部资料；请改回外部资料类型后保存。');
  if(form._intakePreview?.token===form.elements.intake_token.value)values.intake_bylines=intakeBylines(form);
  else values.intake_bylines=JSON.parse(form.elements.intake_byline_json.value||'[]');
}
