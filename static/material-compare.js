'use strict';

// Compare only explicitly selected stable IDs. Bodies live in this view, never history.
const materialCompare={mode:null,ids:[],entries:new Map(),epoch:0,account:null,hash:null,load:null,root:null,focus:null,y:0,listY:0};
function materialCompareCurrent(epoch){
  return epoch===materialCompare.epoch&&materialCompare.account===state.me?.id&&materialCompare.hash===location.hash&&materialCompare.load===state.loadId&&materialCompare.root?.isConnected;
}
function materialCompareReset(restore=false){
  const previous=materialCompare.root;
  materialCompare.epoch++;materialCompare.mode=null;materialCompare.ids=[];materialCompare.entries.clear();
  previous?.classList.remove('material-comparing','material-comparison-reading');
  previous?.querySelector('.material-compare')?.remove();
  previous?.querySelectorAll('[data-material-return]')?.forEach(button=>button.remove());
  if(restore&&previous?.isConnected){
    const focus=materialCompare.focus?.isConnected?materialCompare.focus:previous.querySelector('[data-material-compare="open"]');
    focus?.focus({preventScroll:true});
    const list=previous.querySelector('.record-list');if(list)list.scrollTop=materialCompare.listY;
    window.scrollTo(0,materialCompare.y);
  }
  materialCompare.root=null;materialCompare.account=null;
}
function materialCompareStatus(){
  const count=window.librarySelection?.count()||0;
  document.querySelectorAll('[data-material-compare="open"]').forEach(button=>{button.disabled=count<2||count>3;});
  document.querySelectorAll('[data-material-selection-status]').forEach(node=>{
    node.textContent=count>3?'已选 '+count+' 篇，请减少至 2–3 篇再比较。':count<2?'勾选 2–3 篇资料后比较，可跨页选择。':'已选 '+count+' 篇，可并排比较。';
  });
  if(materialCompare.mode&&(materialCompare.account!==state.me?.id||materialCompare.hash!==location.hash||!materialCompare.root?.isConnected))materialCompareReset();
}
function materialCompareMount(){
  const root=document.querySelector('.library-workspace');if(!root)return;
  if(materialCompare.mode&&root!==materialCompare.root)materialCompareReset();
  const tools=root.querySelector('[data-library-tools]');
  if(tools&&!tools.querySelector('[data-material-compare="select"]'))tools.insertAdjacentHTML('beforeend','<button type="button" class="button tiny" data-material-compare="select">选择资料比较</button>');
  const selection=root.querySelector('.library-selection');
  if(selection&&!selection.querySelector('[data-material-compare="open"]'))selection.insertAdjacentHTML('beforeend','<button type="button" class="button tiny" data-material-compare="open" aria-describedby="material-selection-status">比较已选资料</button><span id="material-selection-status" class="small" data-material-selection-status role="status"></span>');
  materialCompareStatus();
}
function materialCompareText(value,empty){return esc(String(value||'').trim()||empty);}
function materialCompareChinese(record,field){
  const abstract=field==='abstract',human=abstract?record.chinese_abstract:record.chinese_title;
  const value=human||(record.translation_origin==='machine'?(abstract?(record.abstract_is_chinese?record.display_abstract:''):record.display_title):'');
  if(value)return '<span class="reading-origin">'+(human?'人工中文':abstract?'机器译文':'机器译题')+'</span><p>'+esc(value)+'</p>';
  if(record.translation_origin==='original'&&record.has_chinese)return '<span class="reading-origin">原始中文</span><p>'+materialCompareText(abstract?record.abstract:record.title,abstract?'暂无中文摘要':'暂无中文题名')+'</p>';
  return '<p>暂无'+(abstract?'中文摘要':'中文题名')+'</p>';
}
function materialCompareAccess(record){
  const access=record.reading_access||{},items=[];
  if(record.body_html||record.body_text)items.push('有保存正文');
  if(access.platform_files?.length)items.push('有原文件');
  if(access.original_url||access.official_files?.length)items.push('有原文线索');
  if(record.has_chinese)items.push(record.translation_origin==='machine'?'有机器中文':'有可读中文');
  if(!items.length)items.push('仅题录');
  return '<p>'+items.map(esc).join(' · ')+'</p>';
}
function materialCompareOriginalLink(record){
  // Accept web destinations only, including records created before URL validation.
  const candidates=[record.reading_access?.original_url,...(record.reading_access?.official_files||[]).map(link=>link.url)];
  const url=candidates.find(value=>/^https?:\/\//i.test(String(value||'')));
  return url?'<a class="button tiny" href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">打开原文</a>':'<span>暂无原文链接</span>';
}
function materialCompareCell(id,field,index){
  const entry=materialCompare.entries.get(id),record=entry?.record;
  if(!record){
    if(field!=='title')return '<span class="muted">'+(entry?.error?'未能读取':'读取中…')+'</span>';
    if(!entry?.error)return '<p role="status">正在读取第 '+(index+1)+' 篇…</p>';
    return '<p role="alert">第 '+(index+1)+' 篇：'+(entry.unavailable?'资料已删除或无权访问。':'读取失败，请重试。')+'</p><div class="row wrap"><button type="button" class="button tiny" data-material-retry="'+esc(id)+'">重试读取</button><button type="button" class="button tiny" data-material-remove="'+esc(id)+'">移除此项</button></div>';
  }
  switch(field){
    case 'title':return '<strong>'+materialCompareText(record.original_title||record.title,'题名未登记')+'</strong><div class="material-compare-actions"><button type="button" class="button tiny" data-material-read="'+esc(id)+'">阅读这篇</button>'+materialCompareOriginalLink(record)+'<button type="button" class="button tiny" data-material-remove="'+esc(id)+'" aria-label="移除第 '+(index+1)+' 篇">移除此项</button></div>';
    case 'chinese-title':return materialCompareChinese(record,'title');
    case 'abstract':return '<p>'+materialCompareText(record.abstract,'暂无原始摘要')+'</p>';
    case 'chinese-abstract':return materialCompareChinese(record,'abstract');
    case 'authors':return '<p>'+materialCompareText(record.authors,'原始署名未登记')+'</p>';
    case 'source':return '<p>'+materialCompareText(recordSourceLabels(record).join('；'),'来源未登记')+'</p>';
    case 'published':return '<p>'+materialCompareText(record.published_on,'发表时间未知')+'</p>';
    case 'collected':return '<p>'+materialCompareText(record.created_at?.slice(0,10),'首次收录时间未知')+'</p>';
    case 'access':return materialCompareAccess(record);
  }
}
function materialCompareRender(focus=false){
  if(!materialCompare.root?.isConnected)return;
  let panel=materialCompare.root.querySelector('.material-compare');
  if(!panel){panel=document.createElement('section');panel.className='material-compare';panel.setAttribute('role','region');panel.setAttribute('aria-label','资料比较');materialCompare.root.append(panel);}
  const active=panel.contains(document.activeElement)?document.activeElement:null;
  const action=active&&[...active.attributes].find(attribute=>attribute.name.startsWith('data-material-'));
  const restore=action?'['+action.name+'="'+CSS.escape(action.value)+'"]':active?.tagName==='H2'?'h2':null;
  panel.dataset.count=String(materialCompare.ids.length);
  const fields=[['title','原始题名与阅读'],['chinese-title','中文题名'],['abstract','原始摘要'],['chinese-abstract','中文摘要'],['authors','原始署名'],['source','来源'],['published','发表时间'],['collected','首次收录'],['access','内容可用性']];
  panel.innerHTML='<header class="material-compare-head"><h2 tabindex="-1">资料比较 · '+materialCompare.ids.length+' 篇</h2><button type="button" class="button tiny" data-material-compare="close">关闭比较</button></header>'
    +(materialCompare.ids.length<2?'<p role="status">请返回列表再选择资料，比较需要 2–3 篇。</p>':'')
    +'<div class="material-compare-fields">'+fields.map(([field,label])=>'<section class="material-compare-field" aria-label="'+label+'"><h3>'+label+'</h3><div class="material-compare-values">'+materialCompare.ids.map((id,index)=>'<div class="material-compare-value" data-material-item="'+esc(id)+'"><span class="material-compare-number">第 '+(index+1)+' 篇</span>'+materialCompareCell(id,field,index)+'</div>').join('')+'</div></section>').join('')+'</div>';
  panel.hidden=materialCompare.mode!=='compare';
  if(focus||restore)(restore?panel.querySelector(restore)||panel.querySelector('h2'):panel.querySelector('h2')).focus({preventScroll:true});
}
async function materialCompareRead(ids=materialCompare.ids){
  const epoch=++materialCompare.epoch;
  for(const id of ids)materialCompare.entries.set(id,{});
  materialCompareRender();
  await Promise.all(ids.map(async id=>{
    try{
      const record=await api('/api/records/'+encodeURIComponent(id));
      if(!materialCompareCurrent(epoch))return;
      materialCompare.entries.set(id,{record});
    }catch(error){
      if(!materialCompareCurrent(epoch))return;
      materialCompare.entries.set(id,{error:true,unavailable:[403,404].includes(error.status)});
    }
    if(materialCompareCurrent(epoch))materialCompareRender();
  }));
}
function materialCompareOpen(button){
  const ids=window.librarySelection.ids();if(ids.length<2||ids.length>3){materialCompareStatus();return;}
  materialCompareReset();
  Object.assign(materialCompare,{mode:'compare',ids,account:state.me?.id,hash:location.hash,load:state.loadId,root:button.closest('.library-workspace'),focus:button,y:window.scrollY,listY:document.querySelector('.record-list')?.scrollTop||0});
  libraryCloseReader(false);materialCompare.root.classList.add('material-comparing');
  materialCompareRender(true);window.scrollTo(0,0);materialCompareRead();
}
async function materialCompareReturn(){
  if(!materialCompare.mode)return;
  libraryCloseReader(false);materialCompare.mode='compare';
  materialCompare.root.classList.remove('material-comparison-reading');materialCompare.root.classList.add('material-comparing');
  materialCompareRender(true);await materialCompareRead();
}
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-material-compare],[data-material-retry],[data-material-remove],[data-material-read],[data-material-return]');
  if(!button)return;
  if(button.dataset.materialCompare==='select'){
    const root=button.closest('.library-workspace');if(!root.classList.contains('library-organizing'))root.querySelector('[data-action="reading-organize"]')?.click();
    root.querySelector('.reading-tools').open=false;root.querySelector('[data-library-select]')?.focus();
  }else if(button.dataset.materialCompare==='open')materialCompareOpen(button);
  else if(button.dataset.materialCompare==='close')materialCompareReset(true);
  else if(button.hasAttribute('data-material-return'))materialCompareReturn();
  else if(button.dataset.materialRetry)materialCompareRead();
  else if(button.dataset.materialRemove){
    const id=button.dataset.materialRemove;materialCompare.ids=materialCompare.ids.filter(value=>value!==id);materialCompare.entries.delete(id);
    window.librarySelection.remove(id);materialCompareRender(true);
  }else if(button.dataset.materialRead){
    materialCompare.epoch++;materialCompare.mode='reader';
    materialCompare.root.classList.remove('material-comparing');materialCompare.root.classList.add('material-comparison-reading');
    materialCompare.root.querySelector('.material-compare').hidden=true;
    libraryOpenReader(button.dataset.materialRead,button).then(()=>{
      if(materialCompare.mode==='reader'&&!libraryWorkspace.readerId)materialCompareReturn();
    });
  }
});
// Catch the existing reader's close action before it restores a hidden comparison control.
document.addEventListener('click',event=>{
  if(materialCompare.mode==='reader'&&event.target.closest('[data-action="library-reader-close"]')){event.preventDefault();event.stopImmediatePropagation();materialCompareReturn();}
},true);
document.addEventListener('keydown',event=>{
  if(event.key!=='Escape'||!materialCompare.mode||event.defaultPrevented||event.isComposing||keyboardEditing(event))return;
  event.preventDefault();event.stopImmediatePropagation();
  if(materialCompare.mode==='reader')materialCompareReturn();else materialCompareReset(true);
},true);
document.addEventListener('library:reader-rendered',event=>{
  if(materialCompare.mode!=='reader'||materialCompare.root!==event.detail.root.closest('.library-workspace'))return;
  event.detail.root.parentElement.querySelector('.library-reader-head').insertAdjacentHTML('afterbegin','<button type="button" class="button tiny" data-material-return>返回比较</button>');
});
document.addEventListener('library:rendered',materialCompareMount);
document.addEventListener('library:selection-change',materialCompareStatus);
window.addEventListener('hashchange',()=>materialCompareReset());
window.addEventListener('popstate',()=>materialCompareReset());
window.addEventListener('focus',()=>{if(materialCompare.mode==='compare')materialCompareRead();});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&materialCompare.mode==='compare')materialCompareRead();});
new MutationObserver(()=>{
  if(materialCompare.mode&&(!materialCompare.root?.isConnected||materialCompare.account!==state.me?.id))materialCompareReset();
}).observe(document.querySelector('#app'),{childList:true,subtree:true});
