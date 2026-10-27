'use strict';

// Batch actions consume only the library's explicit, account-scoped selection.
const libraryBulk={busy:false,message:'',epoch:0,selection:''};
function libraryBulkRender() {
  const mount=document.querySelector('[data-library-batch-actions]');if(!mount)return;
  mount.hidden=!window.librarySelection.count();
  if(!mount.firstElementChild)mount.innerHTML='<button class="button tiny" type="button" data-action="bulk-favorite">收藏选中</button><button class="button tiny" type="button" data-action="bulk-collection">加入专题</button><button class="button tiny" type="button" data-action="bulk-export">导出选中 CSV</button><button class="button tiny" type="button" data-action="bulk-export-ris">导出选中 RIS</button><p class="small" data-library-batch-status role="status" aria-live="polite"></p>';
  mount.querySelectorAll('button').forEach(button=>{button.disabled=libraryBulk.busy||!window.librarySelection.count();});
  mount.querySelector('[data-library-batch-status]').textContent=libraryBulk.message;
}
function libraryBulkJob() {
  const epoch=++libraryBulk.epoch,account=state.me?.id,csrf=state.csrf,load=state.loadId,hash=location.hash;
  const ids=window.librarySelection.ids();
  return {ids,current:()=>epoch===libraryBulk.epoch&&account===state.me?.id&&csrf===state.csrf&&load===state.loadId&&hash===location.hash&&!!document.querySelector('.library-workspace')};
}
function libraryBulkMessage(message) {libraryBulk.message=message;libraryBulkRender();}
function libraryBulkBusy(busy) {libraryBulk.busy=busy;libraryBulkRender();}
function libraryBulkResult(result,target) {
  return '已处理 '+result.selected+' 条：'+(target==='收藏'?'新增收藏 ':'加入专题新增 ')+result.added+' 条，原已'+(target==='收藏'?'收藏 ':'存在 ')+result.existing+' 条。';
}
async function libraryBulkFavorite() {
  const job=libraryBulkJob();if(!job.ids.length)return;
  libraryBulkBusy(true);libraryBulkMessage('正在收藏选中的 '+job.ids.length+' 条资料…');
  try{
    const result=await api('/api/library/bulk/favorites',{method:'POST',body:{ids:job.ids}});
    if(!job.current())return;
    syncFavoriteState(job.ids,true);
    libraryBulkMessage(libraryBulkResult(result,'收藏'));
  }catch(error){if(job.current())libraryBulkMessage('批量收藏未完成，已保留选择。'+error.message);}
  finally{if(job.current())libraryBulkBusy(false);}
}
async function libraryBulkCollections(chosen='') {
  const job=libraryBulkJob();if(!job.ids.length)return;
  libraryBulkBusy(true);libraryBulkMessage('正在读取可维护的专题…');
  try{
    const result=await api('/api/collections');if(!job.current())return;
    const items=result.items.filter(item=>item.visibility==='shared'||item.owner_id===state.me.id);
    modal('将选中资料加入专题','<form data-form="bulk-collection"><p>已选 '+job.ids.length+' 条资料。已有条目保留一份。</p>'+(items.length?'<div class="field"><label for="bulk-collection-target">目标专题</label><select id="bulk-collection-target" name="collection" required><option value="">请选择专题</option>'+items.map(item=>'<option value="'+esc(item.id)+'" data-version="'+item.version+'" '+(item.id===chosen?'selected':'')+'>'+esc(item.name)+'</option>').join('')+'</select></div>':'<p>暂无可维护专题，请先在专题资料夹中创建。</p>')+'<div class="form-error" role="alert"></div><div class="form-actions"><button class="button" type="button" data-action="bulk-refresh-collections">重新读取专题</button><button class="button primary" type="submit" '+(!items.length?'disabled':'')+'>确认加入</button></div></form>',true);
    document.querySelector('[data-form="bulk-collection"]')._selection=job.ids;
    libraryBulkMessage('');
  }catch(error){if(job.current())libraryBulkMessage('专题读取失败，已保留选择。'+error.message);}
  finally{if(job.current())libraryBulkBusy(false);}
}
async function libraryBulkAddCollection(form) {
  const option=form.elements.collection?.selectedOptions[0];if(!option?.value)return;
  const job=libraryBulkJob(),ids=form._selection;
  const button=form.querySelector('[type="submit"]');button.disabled=true;libraryBulkBusy(true);
  libraryBulkMessage('正在将选中的 '+ids.length+' 条资料加入专题…');
  form.querySelector('.form-error').textContent='正在加入专题…';
  try{
    const result=await api('/api/library/bulk/collections/'+encodeURIComponent(option.value),{method:'POST',body:{ids,version:Number(option.dataset.version)}});
    if(!job.current())return;
    if(form.isConnected)closeModal();libraryBulkMessage(libraryBulkResult(result,'专题'));
  }catch(error){if(job.current()){
    const message=(error.status?'本次未加入任何资料，已保留选择。':'未能确认加入结果，已保留选择。')+error.message+(error.status===409?' 请重新读取专题后重试。':'');
    libraryBulkMessage(message);if(form.isConnected)form.querySelector('.form-error').textContent=message;
  }}
  finally{if(job.current()){libraryBulkBusy(false);if(form.isConnected)button.disabled=false;}}
}
async function libraryBulkExport(format='csv') {
  const job=libraryBulkJob();if(!job.ids.length)return;
  const label=format.toUpperCase();
  libraryBulkBusy(true);libraryBulkMessage('正在生成选中 '+label+'…');
  try{
    const response=await fetch('/api/library/bulk/export'+(format==='ris'?'-ris':''),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({ids:job.ids})});
    if(!job.current())return;
    if(!response.ok){const result=await response.json();if(response.status===401){state.me=null;showLogin();return;}throw new Error(result.error||'导出失败，请重试。');}
    const blob=await response.blob();if(!job.current())return;
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='research-selected-records.'+format;link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
    libraryBulkMessage('已生成选中的 '+job.ids.length+' 条题录，正在下载 '+label+'。');
  }catch(error){if(job.current())libraryBulkMessage('选中导出未完成，已保留选择。'+error.message);}
  finally{if(job.current())libraryBulkBusy(false);}
}
document.addEventListener('library:rendered',()=>{libraryBulk.epoch++;libraryBulk.busy=false;libraryBulk.message='';libraryBulkRender();});
document.addEventListener('library:selection-change',event=>{
  const selection=JSON.stringify(event.detail.ids);
  if(selection!==libraryBulk.selection){libraryBulk.selection=selection;libraryBulk.message='';}
  if(!state.me||!event.detail.count){libraryBulk.epoch++;libraryBulk.busy=false;}
  libraryBulkRender();
});
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-action]');if(!button)return;
  const action=button.dataset.action;
  if(!['bulk-favorite','bulk-collection','bulk-export','bulk-export-ris','bulk-refresh-collections'].includes(action))return;
  event.preventDefault();
  if(libraryBulk.busy)return;
  if(action==='bulk-favorite')libraryBulkFavorite();
  else if(action==='bulk-collection')libraryBulkCollections();
  else if(action==='bulk-export')libraryBulkExport();
  else if(action==='bulk-export-ris')libraryBulkExport('ris');
  else libraryBulkCollections(document.querySelector('#bulk-collection-target')?.value||'');
});
document.addEventListener('submit',event=>{if(event.target.dataset.form==='bulk-collection'){event.preventDefault();if(!libraryBulk.busy)libraryBulkAddCollection(event.target);}});
