'use strict';

// Library workspace: list/card presentation and explicitly selected stable IDs.
const libraryWorkspace={view:'list',items:[],page:1,total:0,size:12,readerId:null,readerRecord:null,readerEpoch:0,returnFocus:null,returnY:0,account:null,context:null,selected:new Set()};
const librarySelectionLimit=100;
const libraryReaderMedia=matchMedia('(max-width:1199px)');
window.librarySelection=Object.freeze({ids:()=>[...libraryWorkspace.selected],count:()=>libraryWorkspace.selected.size,clear:message=>libraryClearSelection(message),limit:librarySelectionLimit});
document.addEventListener('records:favorite-change',event=>{
  const ids=new Set(event.detail.ids),saved=event.detail.saved;
  for(const record of libraryWorkspace.items)if(ids.has(record.id))record.favorite=saved;
  if(libraryWorkspace.readerRecord&&ids.has(libraryWorkspace.readerRecord.id))libraryWorkspace.readerRecord.favorite=saved;
});
function librarySelectionChanged() {
  const selected=libraryWorkspace.selected;
  document.querySelectorAll('[data-library-select]').forEach(input=>{input.checked=selected.has(input.dataset.librarySelect);});
  document.querySelectorAll('[data-library-selection-count]').forEach(element=>{element.textContent='已选 '+selected.size+' 条';});
  document.querySelectorAll('[data-action="library-clear-selection"]').forEach(button=>{button.disabled=!selected.size;});
  document.querySelector('.library-workspace')?.classList.toggle('has-selection',!!selected.size);
  document.querySelectorAll('[data-library-selection-scope],[data-action="library-clear-selection"]').forEach(element=>{element.hidden=!selected.size;});
  document.dispatchEvent(new CustomEvent('library:selection-change',{detail:{ids:[...selected],count:selected.size,limit:librarySelectionLimit}}));
}
function libraryClearSelection(message='') {
  const count=libraryWorkspace.selected.size,restore=document.activeElement?.dataset.action==='library-clear-selection';libraryWorkspace.selected.clear();librarySelectionChanged();
  if(restore)document.querySelector('[data-action="library-select-page"]')?.focus({preventScroll:true});
  if(count&&message)toast(message);
}
function libraryRouteContext() {
  const active=['library','compilations','favorites','review'].includes(state.page),query=recordQuery();
  query.delete('page');query.delete('size');query.sort();
  const context=active?state.page+'?'+query:null;
  if(libraryWorkspace.account!==state.me?.id){libraryResetAccount();libraryWorkspace.account=state.me?.id;}
  else if(libraryWorkspace.context!==context)libraryClearSelection(active?'查找条件已改变，已清空选择。':'已离开资料库，已清空选择。');
  libraryWorkspace.context=context;libraryCloseReader(false);
}
function libraryResetAccount() {
  libraryCloseReader(false);libraryClearSelection();
  Object.assign(libraryWorkspace,{account:null,context:null,items:[],view:'list',returnFocus:null});
  state.detail=null;
}
function libraryCheckbox(record) {
  return '<label class="library-select"><input type="checkbox" data-library-select="'+esc(record.id)+'" aria-label="选择资料：'+esc(record.title)+'" '+(libraryWorkspace.selected.has(record.id)?'checked':'')+'><span class="sr-only">选择</span></label>';
}

function libraryRow(record) {
  return '<article class="library-row" data-library-record="'+esc(record.id)+'">'+libraryCheckbox(record)+'<div class="library-row-main"><h2 class="record-title">'+linkButton(esc(record.title),'detail',record.id,'title-button')+'</h2><div class="record-meta">'+[recordAuthorLabel(record),record.published_on,...recordSourceLabels(record)].filter(Boolean).map(value=>'<span>'+esc(value)+'</span>').join('')+'</div>'
    +(record.search_snippet?'<p class="search-snippet">'+esc(record.search_snippet)+'</p>':'')+'<div data-library-attachment-matches="'+esc(record.id)+'">'+(typeof attachmentMatchSection==='function'?attachmentMatchSection(record):'')+'</div></div><div class="library-row-status">'+typeBadge(record.kind)+badge(record.status)+(record.visibility==='restricted'?'<span class="badge neutral">限授权成员</span>':'')+'<div class="ux-reading-actions">'+uxReadingActions(record,true)+'</div></div></article>';
}
function libraryResultsHTML() {
  if(!libraryWorkspace.items.length)return empty('暂时没有符合条件的资料','试试减少筛选条件，或提交一份新的资料。');
  return libraryWorkspace.items.map(record=>libraryWorkspace.view==='list'?libraryRow(record):'<div class="library-card-item" data-library-record="'+esc(record.id)+'">'+libraryCheckbox(record)+recordCard(record)+'</div>').join('');
}
async function libraryWorkspacePage() {
  const account=state.me?.id,loadId=state.loadId;
  const data=await api('/api/records?'+recordQuery());
  if(account!==state.me?.id||loadId!==state.loadId)throw new Error('资料查找已更新。');
  Object.assign(libraryWorkspace,{items:data.items,page:data.page,total:data.total,size:data.size});
  const root=document.createElement('div');root.innerHTML=await uxLibraryPage(data);
  const library=root.firstElementChild;
  library.classList.add('library-workspace');library.dataset.view=libraryWorkspace.view;
  const views=document.createElement('div');views.className='library-views';views.setAttribute('aria-label','资料显示方式');
  views.innerHTML=['list','cards'].map(view=>'<button class="button tiny" type="button" data-action="library-view" data-view="'+view+'" aria-pressed="'+(libraryWorkspace.view===view)+'">'+(view==='list'?'紧凑列表':'卡片视图')+'</button>').join('');
  library.querySelector('.results-head').append(views);
  const resultControls=document.createElement('div');resultControls.className='library-result-controls';
  const sort=library.querySelector('#sort-select');sort.before(resultControls);resultControls.append(sort,views);
  const selection=document.createElement('section');selection.className='library-selection';selection.setAttribute('aria-label','选择资料');
  selection.innerHTML='<strong data-library-selection-count>已选 '+libraryWorkspace.selected.size+' 条</strong><button class="button tiny" type="button" data-action="library-select-page" '+(!data.items.length?'disabled':'')+'>选择当前页</button><button class="button tiny" type="button" data-action="library-clear-selection" '+(!libraryWorkspace.selected.size?'disabled':'')+'>清空选择</button><span class="small muted" data-library-selection-scope>仅勾选的资料 · 最多 '+librarySelectionLimit+' 条</span><div data-library-batch-actions></div>';
  library.querySelector('.record-list').before(selection);
  library.querySelector('.record-list').innerHTML=libraryResultsHTML();
  const workspace=document.createElement('div');workspace.className='library-results-workspace';
  const list=library.querySelector('.record-list');list.before(workspace);workspace.append(list);
  workspace.insertAdjacentHTML('beforeend','<section class="library-reader" aria-label="连续阅读" hidden></section>');
  return root.innerHTML;
}
function libraryCloseReader(restore=true) {
  if(state.detail?.type==='record'&&state.detail.data.id===libraryWorkspace.readerId)state.detail=null;
  libraryWorkspace.readerEpoch++;libraryWorkspace.readerId=null;libraryWorkspace.readerRecord=null;
  const panel=document.querySelector('.library-reader');if(panel){panel.hidden=true;panel.replaceChildren();panel.closest('.library-workspace').classList.remove('library-reading');}
  document.querySelector('.library-workspace .record-list')?.removeAttribute('inert');
  document.querySelectorAll('.library-current').forEach(row=>row.classList.remove('library-current'));
  document.body.classList.remove('library-narrow-reading');
  libraryReaderBackground(false);
  if(restore){let focus=libraryWorkspace.returnFocus;if(!focus?.isConnected)focus=[...document.querySelectorAll('.record-list [data-action]')].find(button=>button.dataset.id===libraryWorkspace.returnFocus?.dataset.id&&button.dataset.action===libraryWorkspace.returnFocus?.dataset.action);focus?.focus({preventScroll:true});window.scrollTo(0,libraryWorkspace.returnY);}
}
function libraryAfterRender() {
  if(!document.querySelector('.library-workspace'))return;
  librarySelectionChanged();
  document.dispatchEvent(new CustomEvent('library:rendered',{detail:{root:document.querySelector('.library-workspace'),items:libraryWorkspace.items}}));
}
let libraryPermissionCheck=false;
function libraryReaderBackground(blocked){
  const sidebar=document.querySelector('.sidebar');
  sidebar?.toggleAttribute('inert',blocked||navigationMedia.matches);
  if(blocked)sidebar?.setAttribute('aria-hidden','true');else sidebar?.removeAttribute('aria-hidden');
  document.querySelector('.topbar')?.toggleAttribute('inert',blocked);
  const root=document.querySelector('.library-workspace');
  if(root)for(const child of root.children)if(!child.classList.contains('library-results-workspace'))child.inert=blocked;
}
async function libraryCheckPermissions() {
  if(libraryPermissionCheck||!state.me||!document.querySelector('.library-workspace')||document.querySelector('#modal-root .overlay'))return;
  libraryPermissionCheck=true;
  const account=state.me.id,hash=location.hash,readerId=libraryWorkspace.readerId;
  try{
    const session=await api('/api/session');
    if(session.user?.id!==account){libraryResetAccount();state.me=session.user;state.csrf=session.csrf;closeModal();if(state.me)await loadLookups();await route();return;}
    const ids=[...new Set([...libraryWorkspace.selected,...(readerId?[readerId]:[])])];
    let removed=false,readerAllowed=true;
    for(const id of ids){
      try{await api('/api/records/'+encodeURIComponent(id));}
      catch(error){if(error.status!==404&&error.status!==403)throw error;removed=libraryWorkspace.selected.delete(id)||removed;if(id===readerId)readerAllowed=false;}
      if(account!==state.me?.id||hash!==location.hash)return;
    }
    const data=await api('/api/records?'+recordQuery());
    if(account!==state.me?.id||hash!==location.hash)return;
    const changed=data.items.length!==libraryWorkspace.items.length||data.items.some((record,index)=>record.id!==libraryWorkspace.items[index]?.id||record.version!==libraryWorkspace.items[index]?.version);
    if(changed||!readerAllowed){
      await route();
      if(readerId&&readerAllowed&&libraryWorkspace.items.some(record=>record.id===readerId)){
        const origin=[...document.querySelectorAll('.record-title [data-action="detail"]')].find(button=>button.dataset.id===readerId);
        await libraryOpenReader(readerId,origin);
      }
    }
    if(removed){librarySelectionChanged();toast('资料访问范围已更新，已清空选择中的失效条目。');}
  }catch(error){if(account===state.me?.id&&hash===location.hash){libraryCloseReader(false);libraryClearSelection();toast(error.message);}}
  finally{libraryPermissionCheck=false;}
}
window.addEventListener('focus',()=>{libraryCheckPermissions().catch(error=>toast(error.message));});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)libraryCheckPermissions().catch(error=>toast(error.message));});
function libraryReaderSemantics() {
  const panel=document.querySelector('.library-reader');if(!panel||panel.hidden)return;
  const narrow=libraryReaderMedia.matches;
  panel.setAttribute('role',narrow?'dialog':'region');
  if(narrow)panel.setAttribute('aria-modal','true');else panel.removeAttribute('aria-modal');
  document.querySelector('.library-workspace .record-list').inert=narrow;
  document.body.classList.toggle('library-narrow-reading',narrow);
  libraryReaderBackground(narrow);
  if(narrow&&!panel.contains(document.activeElement))panel.querySelector('[data-action="library-reader-close"]')?.focus({preventScroll:true});
}
async function libraryOpenReader(id,origin=null,section='') {
  const panel=document.querySelector('.library-reader');if(!panel)return;
  const epoch=++libraryWorkspace.readerEpoch,account=state.me?.id,hash=location.hash;
  const firstOpen=!libraryWorkspace.readerId;
  if(firstOpen){libraryWorkspace.returnFocus=origin||document.activeElement;libraryWorkspace.returnY=window.scrollY;}
  libraryWorkspace.readerId=id;panel.hidden=false;
  panel.closest('.library-workspace').classList.add('library-reading');
  panel.innerHTML='<header class="library-reader-head"><button class="button tiny" type="button" data-action="library-reader-close">返回列表</button></header><p class="library-loading" role="status">正在读取资料…</p>';libraryReaderSemantics();
  panel.querySelector('[data-action="library-reader-close"]').focus({preventScroll:true});
  try{
    const record=await api('/api/records/'+encodeURIComponent(id));
    if(epoch!==libraryWorkspace.readerEpoch||account!==state.me?.id||hash!==location.hash||!panel.isConnected)return;
    const index=libraryWorkspace.items.findIndex(record=>record.id===id);
    panel.innerHTML='<header class="library-reader-head"><button class="button tiny" type="button" data-action="library-reader-close">返回列表</button><div class="row"><button class="button tiny" type="button" data-action="library-reader-prev" '+(index<=0?'disabled':'')+'>上一条</button><button class="button tiny" type="button" data-action="library-reader-next" '+(index<0||index>=libraryWorkspace.items.length-1?'disabled':'')+'>下一条</button></div><p>本页第 '+(index+1)+' / '+libraryWorkspace.items.length+' 条</p></header><div class="drawer-body library-reader-body"></div>';
    const body=panel.querySelector('.library-reader-body');await uxReadRecord(record,body);
    if(epoch!==libraryWorkspace.readerEpoch||account!==state.me?.id||!panel.isConnected){body.replaceChildren();return;}
    panel.scrollTop=0;body.scrollTop=0;
    if(firstOpen&&!libraryReaderMedia.matches){const workspace=panel.closest('.library-results-workspace');window.scrollTo(0,Math.max(0,window.scrollY+workspace.getBoundingClientRect().top-16));}
    libraryWorkspace.readerRecord=record;
    const focus=section?body.querySelector(section):body.querySelector('.detail-title');
    if(focus){focus.tabIndex=-1;focus.focus({preventScroll:true});if(section)focus.scrollIntoView({block:'start'});}
    for(const row of document.querySelectorAll('[data-library-record]'))row.classList.toggle('library-current',row.dataset.libraryRecord===id);
  }catch(error){if(epoch===libraryWorkspace.readerEpoch){libraryCloseReader();toast(error.message);}}
}
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-action]');if(!button)return;
  const action=button.dataset.action;
  if(button.closest('.library-reader')&&libraryWorkspace.readerRecord&&!document.querySelector('#modal-root .overlay'))state.detail={type:'record',data:libraryWorkspace.readerRecord};
  if(['detail','ux-read-body','ux-files'].includes(action)&&button.closest('.library-workspace .record-list')){
    event.preventDefault();event.stopImmediatePropagation();
    libraryOpenReader(button.dataset.id,button,action==='ux-read-body'?'#ux-body':action==='ux-files'?'#ux-files':'').catch(error=>toast(error.message));
  }else if(action==='library-reader-close'){libraryCloseReader();}
  else if(action==='library-reader-prev'||action==='library-reader-next'){
    const index=libraryWorkspace.items.findIndex(record=>record.id===libraryWorkspace.readerId),next=libraryWorkspace.items[index+(action.endsWith('prev')?-1:1)];
    if(next)libraryOpenReader(next.id).catch(error=>toast(error.message));
  }
},true);
document.addEventListener('keydown',event=>{
  const panel=document.querySelector('.library-reader:not([hidden])');if(!panel||document.querySelector('#modal-root .overlay'))return;
  if(event.key==='Escape'){event.preventDefault();libraryCloseReader();}
  else if(event.key==='Tab'&&panel.getAttribute('aria-modal')==='true'){
    const targets=dialogFocusTargets(panel),first=targets[0],last=targets[targets.length-1];
    if(event.shiftKey&&(document.activeElement===first||!targets.includes(document.activeElement))){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }
});
libraryReaderMedia.addEventListener('change',libraryReaderSemantics);
document.addEventListener('click',event=>{
  const selection=event.target.closest('[data-action="library-select-page"],[data-action="library-clear-selection"]');
  if(selection){
    if(selection.dataset.action==='library-clear-selection')libraryClearSelection('已清空选择。');
    else{for(const record of libraryWorkspace.items){if(libraryWorkspace.selected.size>=librarySelectionLimit)break;libraryWorkspace.selected.add(record.id);}librarySelectionChanged();if(!libraryWorkspace.items.every(record=>libraryWorkspace.selected.has(record.id)))toast('最多选择 '+librarySelectionLimit+' 条，请先减少选择。');}
    return;
  }
  const button=event.target.closest('[data-action="library-view"]');if(!button)return;
  libraryWorkspace.view=button.dataset.view;
  const root=button.closest('.library-workspace');root.dataset.view=libraryWorkspace.view;
  root.querySelector('.record-list').innerHTML=libraryResultsHTML();
  root.querySelectorAll('[data-action="library-view"]').forEach(item=>item.setAttribute('aria-pressed',item.dataset.view===libraryWorkspace.view));
});
document.addEventListener('change',event=>{
  const input=event.target.closest('[data-library-select]');if(!input)return;
  if(input.checked){if(libraryWorkspace.selected.size>=librarySelectionLimit){input.checked=false;toast('最多选择 '+librarySelectionLimit+' 条，请先减少选择。');return;}libraryWorkspace.selected.add(input.dataset.librarySelect);}
  else libraryWorkspace.selected.delete(input.dataset.librarySelect);
  librarySelectionChanged();
});
