'use strict';
// Saved searches own personal settings; libraryPage remains the sole result renderer.
const savedSearchUI={account:null,active:null,epoch:0,managerEpoch:0,current:{},items:[],query:'',page:1};
const savedSearchKeys=new Set(['q','kind','source','source_section','source_group','source_country','source_international','language','country','status','from','to','collection','sort','favorite','editable','evidence_of']);
function savedSearchConditions(query=recordQuery()){
  return Object.fromEntries([...query].filter(([key,value])=>savedSearchKeys.has(key)&&value.trim()));
}
function savedSearchSummary(value){
  const names={q:'关键词',kind:'类型',source:'来源',source_section:'来源分区',source_group:'来源类型',source_country:'来源国别',source_international:'国际办刊',language:'语种',country:'研究对象',status:'核对状态',from:'日期起',to:'日期止',collection:'专题',sort:'排序',favorite:'我的收藏',editable:'可编辑',evidence_of:'原始资料'};
  const labels={favorite:{'1':'是'},editable:{'1':'是'},kind:kinds,language:languages,status:{pending:'待核对',verified:'已核对'},sort:{date:'发表时间',updated:'更新时间',title:'题名'},source_group:{institution:'机构',journal:'期刊',publication:'其他出版物'},source_international:{yes:'是',no:'否',unknown:'待确认'},source_section:{published:'发布／刊载',associated:'一般关联',translations:'目录译稿',outputs:'研究成果'}};
  return Object.entries(value).map(([key,item])=>names[key]+'：'+(labels[key]?.[item]||(key==='source'?(state.sources.find(s=>s.id===item)?.name||'已保存的来源（当前不可访问）'):key==='collection'?(state.collections.find(c=>c.id===item)?.name||'已保存的专题（当前不可访问）'):null)||item)).join(' · ')||'全部可访问资料 · 按发表时间排序';
}
function savedSearchToolbar(){
  const saved=savedSearchUI.active;
  return '<section class="saved-search-bar" aria-label="个人常用检索">'+(saved?'<div><strong>检索：'+esc(saved.name)+'</strong><p>'+esc(savedSearchSummary(savedSearchConditions()))+'</p></div>':'')+'<div class="row wrap">'+linkButton('保存检索','saved-create')+linkButton('我的检索','saved-manage')+'</div></section>';
}
async function savedSearchLibraryPage(render){
  const account=state.me?.id,epoch=++savedSearchUI.epoch,load=state.loadId;
  if(savedSearchUI.account!==account){savedSearchUI.account=account;savedSearchUI.active=null;savedSearchUI.managerEpoch++;}
  const sid=state.params.get('saved_search');
  if(sid){
    try{
      const saved=await api('/api/saved-searches/'+encodeURIComponent(sid));
      if(epoch!==savedSearchUI.epoch||account!==state.me?.id||load!==state.loadId)return '';
      savedSearchUI.active=saved;
      const page=state.params.get('page');state.params=new URLSearchParams(saved.conditions);state.params.set('saved_search',sid);if(page)state.params.set('page',page);
      if(typeof libraryRouteContext==='function')libraryRouteContext(saved.version);
    }catch(error){
      if(epoch!==savedSearchUI.epoch||account!==state.me?.id||load!==state.loadId)return '';
      savedSearchUI.active=null;
      if(typeof libraryRouteContext==='function')libraryRouteContext(0);
      return '<h1>个人常用检索</h1><div class="notice error">'+esc(error.message)+'</div>'+linkButton('我的检索','saved-manage');
    }
  }else savedSearchUI.active=null;
  try{const root=document.createElement('div');root.innerHTML=await render();const heading=root.querySelector('.page-heading');if(heading)heading.insertAdjacentHTML('afterend',savedSearchToolbar());else root.insertAdjacentHTML('afterbegin',savedSearchToolbar());return root.innerHTML;}
  catch(error){
    if(epoch!==savedSearchUI.epoch||account!==state.me?.id||load!==state.loadId)return '';
    return savedSearchToolbar()+'<h1>检索范围暂不可用</h1><div class="notice error">'+esc(error.message)+' 原条件已保留，请调整来源或专题后重新保存。</div>'+linkButton('调整条件','saved-adjust');
  }
}
function savedSearchDialog(title,body){
  const editor=currentEditorForm();if(editor&&!saveEditorDraft(editor)){toast('草稿尚未保存，请保持编辑器打开。');return false;}
  modal(title,body,true);return true;
}
function savedSearchNameForm(item=null,copy=false){
  const values=savedSearchUI.current;
  savedSearchDialog(item&&!copy?'管理检索':'保存检索','<form data-saved-form="name" data-id="'+esc(item&&!copy?item.id:'')+'" data-version="'+(item?.version||'')+'"><div class="field"><label for="saved-search-name">检索名称</label><input id="saved-search-name" name="name" required maxlength="120" value="'+esc(item?item.name+(copy?' 副本':''):'')+'" autofocus></div><p class="saved-condition-summary">'+esc(savedSearchSummary(item&&!copy?item.conditions:values))+'</p><div class="form-error" role="alert"></div><div class="saved-actions"><button class="button primary" type="submit">'+(item&&!copy?'保存名称':'保存检索')+'</button>'+(item&&!copy?'<button class="button" type="button" data-action="saved-update" data-id="'+esc(item.id)+'" data-version="'+item.version+'">用当前条件更新</button>':'')+linkButton('返回我的检索','saved-manage')+'</div></form>');
  document.querySelector('#saved-search-name')?.focus();
}
async function savedSearchManager(q='',page=1){
  const account=state.me?.id,epoch=++savedSearchUI.managerEpoch;
  if(!document.querySelector('[data-saved-manager]')){
    if(!savedSearchDialog('我的检索','<section data-saved-manager><form data-saved-form="find" class="row"><input name="q" maxlength="120" aria-label="按名称查找检索" placeholder="按名称查找检索"><button class="button" type="submit">查找</button></form><div data-saved-results aria-live="polite">正在读取…</div></section>'))return;
  }
  const root=document.querySelector('[data-saved-manager]');root.querySelector('input').value=q;
  const result=await api('/api/saved-searches?'+new URLSearchParams({q,page,size:12}));
  if(epoch!==savedSearchUI.managerEpoch||account!==state.me?.id||!root.isConnected)return;
  Object.assign(savedSearchUI,{items:result.items,query:q,page});
  root.querySelector('[data-saved-results]').innerHTML=result.items.map(item=>'<article class="saved-search-item"><h3>'+linkButton(esc(item.name),'saved-open',item.id,'title-button')+'</h3><p>'+esc(savedSearchSummary(item.conditions))+'</p><div class="saved-actions">'+linkButton('打开','saved-open',item.id)+linkButton('改名／更新','saved-edit',item.id)+linkButton('另存当前条件','saved-copy',item.id)+linkButton('删除','saved-delete',item.id)+'</div></article>').join('')||'<p class="notice">没有匹配的个人检索。</p>';
  root.querySelector('[data-saved-results]').insertAdjacentHTML('beforeend','<div class="saved-actions"><button class="button tiny" data-action="saved-manager-page" data-page="'+(page-1)+'" '+(page<=1?'disabled':'')+'>上一页</button><span>共 '+result.total+' 项 · 第 '+page+' 页</span><button class="button tiny" data-action="saved-manager-page" data-page="'+(page+1)+'" '+(page*result.size>=result.total?'disabled':'')+'>下一页</button></div>');
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action^="saved-"]');if(!button)return;
  const action=button.dataset.action,id=button.dataset.id,account=state.me?.id;
  try{
    if(action==='saved-create'){savedSearchUI.current=savedSearchConditions();savedSearchNameForm();}
    else if(action==='saved-manage'){if(!document.querySelector('[data-saved-form]'))savedSearchUI.current=savedSearchConditions();await savedSearchManager();}
    else if(action==='saved-manager-page')await savedSearchManager(savedSearchUI.query,Number(button.dataset.page));
    else if(action==='saved-open'){if(closeModal()===false)return;savedSearchUI.epoch++;go('library',{saved_search:id});}
    else if(action==='saved-adjust'){
      const value=savedSearchUI.active?.conditions||savedSearchConditions();
      savedSearchDialog('调整检索范围','<form data-saved-form="adjust"><p>原检索条件继续保留。请明确选择要移除的范围，再用资料库现有筛选调整。</p>'+(value.source?'<label class="saved-remove-scope"><input type="checkbox" name="remove_source">移除来源限制及其内容分区</label>':'')+(value.collection?'<label class="saved-remove-scope"><input type="checkbox" name="remove_collection">移除专题限制</label>':'')+'<p class="saved-condition-summary">'+esc(savedSearchSummary(value))+'</p><div class="form-error" role="alert"></div><button class="button primary" type="submit">应用调整后的条件</button></form>');
    }
    else if(action==='saved-edit'||action==='saved-copy')savedSearchNameForm(savedSearchUI.items.find(item=>item.id===id),action==='saved-copy');
    else if(action==='saved-delete'){
      const item=savedSearchUI.items.find(item=>item.id===id);
      savedSearchDialog('删除检索','<form data-saved-form="delete" data-id="'+esc(id)+'" data-version="'+item.version+'"><p>确认删除个人检索“'+esc(item.name)+'”？</p><p class="small muted">资料、收藏与专题继续保留。</p><div class="form-error" role="alert"></div><div class="saved-actions"><button class="button danger" type="submit">确认删除</button>'+linkButton('取消','saved-manage')+'</div></form>');
    }else if(action==='saved-update'){
      const form=button.closest('form');button.disabled=true;
      const updated=await api('/api/saved-searches/'+encodeURIComponent(id),{method:'PUT',body:{version:Number(button.dataset.version),name:document.querySelector('#saved-search-name').value,conditions:savedSearchUI.current}});
      if(account!==state.me?.id||!form?.isConnected)return;savedSearchUI.active=updated;closeModal();toast('已更新为当前条件');go('library',{saved_search:id});
    }
  }catch(error){const form=button.closest('form');if(form?.isConnected&&form.querySelector('.form-error'))form.querySelector('.form-error').textContent=error.message;else toast(error.message);}
  finally{if(button.isConnected)button.disabled=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target.closest('[data-saved-form]');if(!form)return;event.preventDefault();
  const account=state.me?.id,kind=form.dataset.savedForm,button=form.querySelector('[type=submit]');button.disabled=true;
  try{
    if(kind==='adjust'){const value={...(savedSearchUI.active?.conditions||savedSearchConditions())},data=new FormData(form);if(!data.has('remove_source')&&!data.has('remove_collection'))throw new Error('请选择要移除的范围。');if(data.has('remove_source')){delete value.source;delete value.source_section;}if(data.has('remove_collection'))delete value.collection;closeModal();go('library',value);return;}
    if(kind==='find'){await savedSearchManager(form.elements.q.value.trim());return;}
    const id=form.dataset.id;
    const payload=kind==='delete'?{version:Number(form.dataset.version)}:{name:form.elements.name.value,...(id?{version:Number(form.dataset.version)}:{conditions:savedSearchUI.current})};
    const result=await api('/api/saved-searches'+(id?'/'+encodeURIComponent(id):''),{method:kind==='delete'?'DELETE':id?'PUT':'POST',body:payload});
    if(account!==state.me?.id||!form.isConnected)return;
    if(kind==='delete'){if(savedSearchUI.active?.id===id)savedSearchUI.active=null;await savedSearchManager();toast('已删除检索');}
    else{savedSearchUI.active=result;closeModal();toast('检索已保存');go('library',{saved_search:result.id});}
  }catch(error){if(form.isConnected){let output=form.querySelector('.form-error');if(!output){output=document.createElement('p');output.className='form-error';form.append(output);}output.textContent=error.message;}}
  finally{if(button.isConnected)button.disabled=false;}
});
