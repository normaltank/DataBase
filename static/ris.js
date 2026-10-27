'use strict';

// One member-owned draft contains the complete queue and each entry's edits.
function risDraftKey(account=state.me.id){return draftPrefix+encodeURIComponent(account)+':ris:queue';}
const risMemoryDrafts=new Map();
function risReleaseAccountEditor(){
  const form=currentEditorForm();if(!form?._risQueue)return;
  if(!saveEditorDraft(form,true)){risMemoryDrafts.set(form.dataset.draftKey,collectDraft(form));form._saved=true;}
  // Reconcile any late save through the signed status endpoint on restoration.
  delete form.dataset.saving;form.inert=false;
}
function risEvidenceHtml(items){
  if(!items?.length)return '';
  return '<details class="intake-evidence"><summary>RIS 交换依据</summary><p class="form-help">仅保留本条原文与标签、文件名、摘要和序号；其他条目及原文件整体未进入共享资料。文件摘要用于辨认输入，不证明题录真实。</p>'+items.map(e=>'<section><p>'+esc(e.file_name)+' · 第 '+e.entry_index+' 条 · '+esc(e.original_type)+'<br>导入预览时间：'+esc(e.imported_at)+'<br>SHA-256：<span class="ris-hash">'+esc(e.file_sha256)+'</span></p><details><summary>本条原始 RIS 与映射依据</summary><pre>'+esc(e.raw_entry)+'</pre><pre>'+esc(JSON.stringify(e,null,2))+'</pre></details></section>').join('')+'</details>';
}
function risCaptureEditor(form){
  const queue=form?._risQueue;if(!queue)return;
  if(form._risIndex!==undefined){
    const edit={};
    for(const el of form.elements){
      if(!el.name||el.type==='file'||el.name==='ris_queue_json')continue;
      if(['checkbox','radio'].includes(el.type)){if(!edit[el.name])edit[el.name]=[];if(el.checked)edit[el.name].push(el.value);}
      else if(el.multiple)edit[el.name]=[...el.selectedOptions].map(option=>option.value);
      else edit[el.name]=el.value;
    }
    queue.items[form._risIndex].edit=edit;
    queue.items[form._risIndex].file=form._draftFile?{name:form._draftFile.name,size:form._draftFile.size}:null;
    if(form._intakePreview)queue.items[form._risIndex].bylines=intakeBylines(form,false);
  }
  if(form.elements.ris_queue_json)form.elements.ris_queue_json.value=JSON.stringify(queue);
}
function risQueueHtml(queue){
  return '<section class="ris-queue" data-ris-queue><h3>'+esc(queue.filename)+' · '+queue.items.length+' 条题录</h3><p class="form-help">每条只有明确保存后才入库。切换条目和关闭时保留整队列草稿。</p><ol>'+queue.items.map((item,i)=>'<li><div><strong>第 '+item.index+' 条 · '+esc(item.type)+'</strong><span>'+esc(item.edit?.title||item.fields.title||'题名缺失')+'</span><small>'+esc(item.saved?'已保存 · '+item.saved:item.skipped?'已跳过':item.errors.length?'未支持或格式错误（第 '+item.line+' 行）':item.saveError?'保存失败，输入保留':'待处理')+'</small></div>'+(item.saved?'<button type="button" class="button tiny" data-ris-open="'+esc(item.saved)+'">查看资料</button>':'<button type="button" class="button tiny" data-ris-edit="'+i+'">'+(item.errors.length?'查看问题':'核对本条')+'</button>')+'<button type="button" class="button tiny" data-ris-skip="'+i+'" '+(item.saved?'disabled':'')+'>'+(item.skipped?'继续处理':'跳过')+'</button></li>').join('')+'</ol></section>';
}
function risUploadHtml(){return '<section class="ris-upload"><h3>选择题录文件</h3><p class="form-help">UTF-8 RIS（可带 BOM），最多 1 MiB、100 条。支持 JOUR、RPRT、WEB/ELEC、GEN。只导入题录，不访问链接、附件或本机路径。</p><label>RIS 文件<input type="file" data-ris-file accept=".ris,text/plain,application/x-research-info-systems"></label><button type="button" class="button" data-ris-preview>预览文件</button><p data-ris-status role="status" aria-live="polite"></p></section>';}
function risBind(form,queue,index,persist=true){
  form._risQueue=queue;form._risIndex=index;form._editing.type='ris';form.dataset.draftKey=risDraftKey();
  if(index!==undefined)form._risFileKey=risDraftKey()+':'+queue.sha256+':'+index;
  const hidden=document.createElement('input');hidden.type='hidden';hidden.name='ris_queue_json';form.append(hidden);
  form.querySelector('.draft-offer')?.remove();form._draftOffer=null;
  form._dirty=true;if(persist){risCaptureEditor(form);if(saveEditorDraft(form,true))risMemoryDrafts.delete(form.dataset.draftKey);}
}
async function risOpenDraft(key=risDraftKey()){
  let draft;try{draft=JSON.parse(localStorage.getItem(key)||'null');}catch{}
  draft=risMemoryDrafts.get(key)||draft;
  if(draft?.user_id!==state.me.id)return risShowQueue(null);
  let queue;try{queue=JSON.parse(draft.values.ris_queue_json||'null');}catch{}
  if(!queue)return risShowQueue(null);
  const actor=state.me.id;
  await risShowQueue(queue);
  const form=currentEditorForm(),generation=modalGeneration;
  const status=form.querySelector('[data-ris-status]');status.textContent='正在核对本账号已保存的条目…';
  form.inert=true;
  try{
    for(const item of queue.items){
      if(!item.token)continue;
      const result=await api('/api/ris/status',{method:'POST',body:{token:item.token}});
      if(actor!==state.me?.id||!form.isConnected||generation!==modalGeneration)return;
      if(result.saved){item.saved=result.id;delete item.saveError;}
    }
    risCaptureEditor(form);saveEditorDraft(form,true);
    form.querySelector('[data-ris-queue]').outerHTML=risQueueHtml(queue);
    status.textContent='已恢复整队列；已保存条目不会再次提交。';
  }catch(error){status.textContent='保存状态暂未核对：'+error.message+'。可重新打开后核对，所有输入仍保留。';form.querySelectorAll('[data-ris-edit]').forEach(b=>b.disabled=true);}
  finally{if(form.isConnected)form.inert=false;}
}
async function risShowQueue(queue){
  if(modal('RIS 题录导入','<form data-form="ris-upload">'+(queue?risQueueHtml(queue):'')+risUploadHtml()+'<div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">关闭并保留草稿</button></div></form>')===false)return;
  const form=document.querySelector('[data-form=ris-upload]');
  await enableEditorDraft(form,{type:'ris',id:'',original:{kind:'other'}},'ris-upload-'+crypto.randomUUID());
  form.querySelector('.draft-offer')?.remove();form._draftOffer=null;
  risBind(form,queue||{filename:'尚未选择文件',items:[]});
}
async function risEdit(form,index){
  risCaptureEditor(form);if(!saveEditorDraft(form,true))throw new Error('草稿未能保存，请保持当前编辑器打开。');
  const queue=form._risQueue,item=queue.items[index],actor=state.me.id;
  if(item.saved)return workflowOpenRecord(item.saved);
  if(item.errors.length){
    await risShowQueue(queue);
    const panel=document.createElement('section');panel.className='notice error';panel.innerHTML='<h3>第 '+item.index+' 条问题</h3>'+item.errors.map(e=>'<p>'+esc(e)+'</p>').join('')+'<pre>'+esc(item.evidence.raw_entry)+'</pre>';currentEditorForm().querySelector('[data-ris-queue]').after(panel);return;
  }
  await workflowRecordForm('',item.edit?.kind||item.fields.kind,'ris-item-'+crypto.randomUUID(),'','',{...item.fields});
  const editor=document.querySelector('[data-form=record]');if(!editor||actor!==state.me?.id)return;
  // The standard editor owns field, source, identity, draft and validation UI.
  const metadata={format:'RIS',input:queue.filename+' · 第 '+item.index+' 条',retrieved_at:item.evidence.imported_at,fields:item.fields,
    authors:item.authors,identifiers:{},provenance:Object.fromEntries(Object.keys(item.fields).map(k=>[k,'RIS'])),
    warnings:item.warnings,duplicates:item.duplicates,candidates:item.candidates,token:item.token,sources:[]};
  setIntakePreview(editor,metadata);fillIntakeBlanks(editor);
  editor.querySelector('[data-intake-editor] .intake-input-row').hidden=true;
  editor.querySelector('[data-intake-editor] label[for=intake-input]').hidden=true;
  editor.querySelector('[data-intake-editor] h3').textContent='本条身份与来源核对';
  editor.querySelector('[data-intake-detach]')?.remove();
  editor.querySelector('[data-intake-editor] .intake-evidence')?.remove();
  editor.elements.intake_token.value='';
  const token=document.createElement('input');token.type='hidden';token.name='ris_token';token.value=item.token;editor.append(token);
  const head=document.createElement('section');head.className='wide ris-editor-head';
  head.innerHTML=risQueueHtml(queue)+'<h3>核对第 '+item.index+' 条 · 原类型 '+esc(item.type)+'</h3>'
    +(item.warnings.length?'<div class="notice">'+item.warnings.map(w=>'<p>'+esc(w)+'</p>').join('')+'</div>':'')
    +(item.file_duplicates.length?'<p class="notice">文件内可能重复：第 '+item.file_duplicates.join('、')+' 条。保存时会再次检查 DOI 与网址。</p>':'')
    +(item.evidence.requires_date_review?'<label class="check-label"><input type="checkbox" name="ris_date_reviewed">我已核对原始日期并完成修正，或确认日期暂留空</label>':'')
    +'<button type="button" class="button tiny" data-ris-recheck>重新核对当前字段与保存结果</button><p data-ris-check-status role="status"></p>'+risEvidenceHtml([item.evidence]);
  editor.querySelector('.form-grid').prepend(head);
  // All kinds shown here are external material; the server repeats this check.
  [...editor.elements.kind.options].filter(o=>isResearchContent(o.value)).forEach(o=>o.remove());
  if(item.edit){
    for(const el of editor.elements){
      if(!el.name||el.type==='file'||el.name==='ris_token'||!Object.hasOwn(item.edit,el.name))continue;
      const value=item.edit[el.name];
      if(['checkbox','radio'].includes(el.type))el.checked=Array.isArray(value)&&value.includes(el.value);
      else if(el.matches('[data-source-values]'))restoreSourceSelection(el,value);
      else if(el.multiple)[...el.options].forEach(option=>option.selected=(Array.isArray(value)?value:[value]).includes(option.value));
      else {if(el.tagName==='SELECT'&&value&&![...el.options].some(o=>o.value===value))el.add(new Option(value,value));el.value=value;}
    }
    restoreIntakeForm(editor);editor.elements.intake_token.value='';
    editor.querySelectorAll('[data-rich-field]').forEach(field=>field.querySelector('[data-rich-input]').innerHTML=cleanRich(item.edit[field.dataset.richField]||''));
  }
  editor.querySelector('[data-intake-detach]')?.remove();
  editor.querySelector('[type=submit]').textContent='保存本条并接续';
  const fileDraft=item.file;
  editor._updateInformationMode?.();refreshSourcePickers(editor);risBind(editor,queue,index,false);
  if(fileDraft){
    editor.inert=true;
    try{const file=await draftFileOperation(editor._risFileKey,'get');if(!editor.isConnected||actor!==state.me?.id)return;editor._draftFile=file||null;showDraftFile(editor);if(!file)draftStatus(editor,'文字已恢复；附件草稿不可用，请重新选择附件。',true);}
    catch{draftStatus(editor,'附件草稿暂不可用，请重新选择附件。',true);}
    finally{if(editor.isConnected)editor.inert=false;}
  }
  saveEditorDraft(editor,true);
  editor.querySelector('.form-error').textContent=item.saveError||'';
}
function risSaveValues(form,values){
  if(!form._risQueue)return;
  delete values.ris_queue_json;delete values.intake_token;
  values.ris_token=form.elements.ris_token.value;
  values.ris_date_reviewed=!!form.elements.ris_date_reviewed?.checked;
  values.intake_bylines=intakeBylines(form);
  risCaptureEditor(form);
}
async function risRecordSaved(form,result){
  const queue=form._risQueue,item=queue.items[form._risIndex],actor=form.dataset.draftUser;
  item.saved=result.id;delete item.saveError;risCaptureEditor(form);saveEditorDraft(form,true);
  form._saved=true;delete form.dataset.saving;form.inert=false;
  if(actor!==state.me?.id||!form.isConnected)return;
  await loadLookups();
  const next=queue.items.findIndex(i=>!i.saved&&!i.skipped&&!i.errors.length);
  await risShowQueue(queue);
  if(next>=0)await risEdit(currentEditorForm(),next);
  toast('本条已保存：'+result.id+'；其余条目尚未保存。');
}
document.addEventListener('library:rendered',event=>{
  if(state.page!=='library')return;
  const button=document.createElement('button');button.type='button';button.className='button';button.dataset.risStart='';button.textContent='导入 RIS 文件';event.detail.root.querySelector('.page-heading').append(button);
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-ris-start],[data-ris-preview],[data-ris-edit],[data-ris-skip],[data-ris-open],[data-ris-recheck]');if(!button)return;
  const form=button.closest('form');
  try{
    if(button.hasAttribute('data-ris-start'))return await risOpenDraft();
    if(button.hasAttribute('data-ris-open'))return await workflowOpenRecord(button.dataset.risOpen);
    if(button.hasAttribute('data-ris-edit'))return await risEdit(form,Number(button.dataset.risEdit));
    if(button.hasAttribute('data-ris-skip')){risCaptureEditor(form);const item=form._risQueue.items[Number(button.dataset.risSkip)];item.skipped=!item.skipped;saveEditorDraft(form,true);return await risShowQueue(form._risQueue);}
    if(button.hasAttribute('data-ris-recheck')){
      const actor=state.me.id,item=form._risQueue.items[form._risIndex];
      const result=await api('/api/ris/status',{method:'POST',body:{token:item.token,fields:Object.fromEntries(new FormData(form))}});
      if(!form.isConnected||actor!==state.me?.id)return;
      if(result.saved){item.saved=result.id;saveEditorDraft(form,true);await risShowQueue(form._risQueue);}
      else form.querySelector('[data-ris-check-status]').innerHTML='本预览条目尚未保存。'+(result.duplicates||[]).map(d=>'<p>'+esc(d.basis)+'：'+linkButton(esc(d.title),'detail',d.id,'link-button')+'</p>').join('');
      return;
    }
    if(button.hasAttribute('data-ris-preview')){
      const file=form.querySelector('[data-ris-file]').files[0];if(!file)throw new Error('请先选择 RIS 文件。');if(file.size>1024*1024)throw new Error('RIS 文件不能超过 1 MiB。');
      if(form._risQueue.items.length&&!button.dataset.replaceConfirmed){
        const status=form.querySelector('[data-ris-status]');status.innerHTML='当前队列仍保留。<button type="button" class="button tiny" data-ris-preview data-replace-confirmed="true">确认替换队列并预览所选文件</button>';return;
      }
      const actor=state.me.id,generation=modalGeneration,version=form._risFileGeneration||0,body=new FormData();body.set('file',file,file.name);button.disabled=true;
      form.querySelector('[data-ris-status]').textContent='正在预览；不会写入正式资料…';
      try{const result=await api('/api/ris/preview',{method:'POST',body});if(!form.isConnected||actor!==state.me?.id||generation!==modalGeneration||version!==(form._risFileGeneration||0))return;await risShowQueue(result);}
      finally{if(button.isConnected)button.disabled=false;}
    }
  }catch(error){const target=form?.querySelector('.form-error');if(target)target.textContent=error.message;else toast(error.message);}
});
document.addEventListener('change',event=>{if(event.target.matches('[data-ris-file]')){const form=event.target.closest('form');form._risFileGeneration=(form._risFileGeneration||0)+1;form.querySelector('[data-ris-status]').textContent='文件选择已改变；当前队列仍保留，请明确预览。';}});
