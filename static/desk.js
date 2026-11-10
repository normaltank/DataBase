'use strict';
// A material is selected without replacing its native upload/review forms.
const deskSelections=new Map();
let deskMotion=null;
function deskRenderPreview(button,result){
  const host=button.closest('.handoff-version');if(!host)return;
  let preview=host.querySelector('[data-desk-preview]');
  if(!preview){preview=document.createElement('section');preview.dataset.deskPreview='';preview.className='desk-original';const meta=host.querySelector('.desk-file-meta');if(meta)meta.before(preview);else host.append(preview);}
  preview.dataset.version=button.dataset.version;
  preview.setAttribute('aria-label',result.name||'原件预览');
  preview.innerHTML=(result.status==='ready'?'<div class="desk-original-text">'+result.segments.map(s=>'<p>'+esc(s.text)+'</p>').join('')+'</div>':'<p>此文件暂不能预览，请下载原件查看。</p>');
}
async function deskPreview(item){
  if(!item)return;
  const button=item.querySelector('[data-handoff-reading] [data-action="handoff-view"]');if(!button)return;
  const version=button.dataset.version,account=state.me?.id;
  if(item.dataset.previewLoading===version||button.closest('.handoff-version').querySelector('[data-desk-preview]')?.dataset.version===version)return;
  item.dataset.previewLoading=version;
  try{const tid=item.closest('[data-collaboration-topic]').dataset.collaborationTopic;const result=await api('/api/collaboration/topics/'+encodeURIComponent(tid)+'/handoff-preview?version_ref='+encodeURIComponent(version));if(account===state.me?.id&&item.isConnected&&item.querySelector('[data-handoff-version]')?.value===version)deskRenderPreview(button,result);}
  catch(error){if(item.isConnected&&account===state.me?.id){const status=item.querySelector('[data-lineage-status]');if(status)status.textContent='原件预览未读取：'+error.message+'。可用“查看内容”重试。';}}
  finally{delete item.dataset.previewLoading;}
}
function deskSelect(root,ref,focus=false){
  const items=[...root.querySelectorAll(':scope > .handoff-material')],chosen=items.find(item=>item.dataset.materialRef===ref)||items[0];if(!chosen)return;
  const key=state.me.id+'|'+workbenchState.selected+'|'+state.params.get('tab');deskSelections.set(key,chosen.dataset.materialRef);
  items.forEach(item=>{item.hidden=item!==chosen;if(!item.dataset.deskTools){item.dataset.deskTools='true';const toolbar=item.querySelector('.handoff-lineage-toolbar'),current=toolbar?.querySelector('[data-action=handoff-current]'),picker=item.querySelector('.handoff-version-picker');if(current&&picker)picker.append(current);const actions=item.querySelector('.handoff-current-actions');if(actions)picker?.after(actions);if(toolbar){const details=document.createElement('details');details.className='desk-refresh';details.innerHTML='<summary>更新材料状态</summary>';toolbar.before(details);details.append(toolbar);}}});
  const picker=root.querySelector('[data-desk-material-picker]');if(picker)picker.value=chosen.dataset.materialRef;
  chosen.querySelectorAll('[data-action=handoff-current]').forEach(button=>button.hidden=chosen.querySelector('[data-handoff-version]')?.selectedIndex===0);
  root.querySelectorAll('[data-desk-material]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.deskMaterial===chosen.dataset.materialRef)));
  if(focus){const h=chosen.querySelector('h2');h.tabIndex=-1;h.focus({preventScroll:true});window.deskTransition?.(chosen);}
  deskPreview(chosen);
}
function deskDisclosure(selector,label){
  document.querySelectorAll(selector).forEach(content=>{if(content.dataset.deskDisclosure)return;content.dataset.deskDisclosure='true';if(content.matches('.source-filters')){const submit=content.querySelector('[type=submit]');if(submit)content.closest('form').querySelector('.toolbar').append(submit);}const details=document.createElement('details');details.className='desk-progressive';details.innerHTML='<summary>'+label+'</summary>';content.before(details);details.append(content);if([...state.params.keys()].some(key=>['q','country','employment_country','subject_country','year','journal_id','from','to'].includes(key)))details.open=true;});
}
function deskPrepare(){
  document.querySelectorAll('.library-reader .ux-reading-toolbar').forEach(toolbar=>{const tools=toolbar.querySelector('.ux-reader-tools>.ux-reading-actions'),compare=toolbar.querySelector(':scope>[data-reading-compare]');if(tools&&compare)tools.append(compare);});
  deskDisclosure('.source-search .source-filters','按国别、类型与收录范围筛选');
  deskDisclosure('.people-search .people-country-filters','按任职与作品研究对象国查找');
  deskDisclosure('.journal-result-search','查找刊物与期次');
  deskDisclosure('.reading-library form[data-reading-filters]','查找与筛选资料');
  document.querySelectorAll('.desk-workspace .handoff-materials').forEach(root=>{
    const items=[...root.querySelectorAll(':scope > .handoff-material')];if(!items.length)return;
    const signature=items.map(item=>item.dataset.materialRef+'|'+item.querySelector('h2').textContent+'|'+item.querySelector('.badge').textContent).join(';');
    if(root._deskSignature===signature)return;root._deskSignature=signature;const upload=root.querySelector(':scope > .handoff-upload')||root.querySelector('.desk-material-index > .handoff-upload');upload?.remove();root.querySelector('.desk-material-index')?.remove();
    const nav=document.createElement('nav');nav.className='desk-material-index';nav.setAttribute('aria-label','本期材料');
    nav.innerHTML='<h2>本期材料</h2>'+items.map(item=>{const title=item.querySelector('h2').textContent,owner=item.querySelector('.handoff-owner').textContent,status=item.querySelector('.badge').textContent;return '<button data-desk-material="'+esc(item.dataset.materialRef)+'" aria-pressed="false"><strong>'+esc(title)+'</strong><span>'+esc(owner)+'</span><span>'+esc(status)+'</span></button>';}).join('');
    nav.insertAdjacentHTML('beforeend','<label class="desk-material-picker">本期材料<select data-desk-material-picker>'+items.map(item=>'<option value="'+esc(item.dataset.materialRef)+'">'+esc(item.querySelector('h2').textContent)+' · '+esc(item.querySelector('.badge').textContent)+'</option>').join('')+'</select></label>');if(upload)nav.querySelector('h2').after(upload);root.prepend(nav);const key=state.me.id+'|'+workbenchState.selected+'|'+state.params.get('tab');deskSelect(root,deskSelections.get(key));
  });
}
new MutationObserver(deskPrepare).observe(document.documentElement,{childList:true,subtree:true});
document.addEventListener('click',event=>{const button=event.target.closest('[data-desk-material]');if(button)deskSelect(button.closest('.handoff-materials'),button.dataset.deskMaterial,true);if(event.target.closest('[data-action="handoff-select"],[data-action="handoff-current"]'))queueMicrotask(()=>{const item=event.target.closest('.handoff-material');item?.querySelectorAll('[data-action=handoff-current]').forEach(button=>button.hidden=item.querySelector('[data-handoff-version]')?.selectedIndex===0);deskPreview(item);});});
document.addEventListener('change',event=>{if(event.target.matches('[data-handoff-version]'))queueMicrotask(()=>{const item=event.target.closest('.handoff-material');item?.querySelectorAll('[data-action=handoff-current]').forEach(button=>button.hidden=item.querySelector('[data-handoff-version]')?.selectedIndex===0);deskPreview(item);});});
// Load the same-origin, locked bundle only for the authored object→workface transition.
import(clientAsset('/static/vendor/visual/desk-motion.js')).then(module=>{deskMotion=module;window.deskCancelTransition=module.cancel;window.deskTransition=target=>module.transition(target);}).catch(()=>{});
window.addEventListener('hashchange',()=>deskMotion?.cancel());

document.addEventListener('change',event=>{if(event.target.matches('[data-desk-material-picker]'))deskSelect(event.target.closest('.handoff-materials'),event.target.value,true);});

document.addEventListener('visibilitychange',()=>{if(document.hidden)deskMotion?.cancel();});
matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change',()=>deskMotion?.cancel());
