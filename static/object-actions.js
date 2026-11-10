'use strict';

// Native and visual objects expose the same actions. This portal owns only
// focus and presentation; validated application handlers still own all writes.
window.objectActions=(()=>{
  const attached=new WeakMap();let active=null;
  const more=label=>'<button type="button" class="object-more" data-object-more aria-label="'+esc(label||'更多操作')+'" aria-haspopup="menu" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/></svg></button>';
  function close(restore=true){const old=active;if(!old)return;active=null;old.menu.remove();old.observer.disconnect();old.origin.querySelector('[data-object-more]')?.setAttribute('aria-expanded','false');if(restore&&old.focus?.isConnected)old.focus.focus({preventScroll:true});}
  const native=event=>event.target.closest('a,input,textarea,select,[contenteditable="true"]')||!!window.getSelection()?.toString();
  function invoke(origin,action,id,extra={}){const trigger=document.createElement('button');trigger.hidden=true;Object.assign(trigger.dataset,{action,id,...extra});origin.append(trigger);trigger.click();trigger.remove();}
  function resolve(origin){
    if(attached.has(origin))return attached.get(origin)();
    const kind=origin.dataset.objectKind,id=origin.dataset.objectId;
    if(kind==='record'){
      const record=libraryWorkspace.items.find(r=>r.id===id);if(!record||libraryWorkspace.account!==state.me?.id)return [];
      const selected=window.librarySelection.ids(),included=selected.includes(id),full=selected.length>=3;
      return [{id:'read',label:'阅读资料',run:()=>invoke(origin,'detail',id)},
        {id:'favorite',label:record.favorite?'取消收藏':'收藏资料',run:()=>invoke(origin,'favorite',id,{saved:String(!!record.favorite)})},
        {id:'folder',label:'加入资料夹',run:()=>invoke(origin,'add-to-collection',id)},
        {id:'compare-select',label:included?'移出比较选择':'选择用于比较',disabled:!included&&full,run:()=>{if(included)window.librarySelection.remove(id);else if(window.librarySelection.count()<3)window.librarySelection.add(id);libraryWorkspace.organizing=true;document.querySelector('.library-workspace')?.classList.add('library-organizing');}},
        ...(selected.length>=2&&selected.length<=3?[{id:'compare',label:'比较已选 '+selected.length+' 篇',run:()=>materialCompareOpen(origin.querySelector('[data-object-more]'))}]:[])];
    }
    if(kind==='source')return [{id:'profile',label:'打开档案',href:sourceUrl(id)},{id:'preview',label:'快速预览',run:()=>invoke(origin,'source-preview',id)},{id:'records',label:'查看来源资料',run:()=>invoke(origin,'source-records',id)}];
    if(kind==='person')return [{id:'profile',label:'打开人物档案',href:'#people?id='+encodeURIComponent(id)}];
    if(kind==='work')return [{id:'open',label:'打开工作',run:()=>invoke(origin,'workbench-select',id,{business:origin.dataset.objectBusiness})}];
    if(kind==='material'){
      const root=origin.closest('.handoff-lineage');if(!root||root.dataset.lineageAccount!==state.me?.id)return [];
      return handoffMenuActions(root,'version:'+id).map(action=>({...action,run:()=>handoffNodeAction(root,'version:'+id,action.id)}));
    }
    if(kind==='step'){
      const trace=origin.closest('[data-maintenance-trace]'),model=trace?._maintenanceTrace,step=model?.job.steps.find(s=>s.id===id);
      if(!step||state.me?.role!=='admin')return [];
      return [{id:'read',label:'查看修改与依据',run:()=>{origin.querySelector('[data-trace-step]').click();trace.querySelector('[data-trace-locate]').click();}},
        ...(maintenanceTraceEvidence(model.job,step).length?[{id:'evidence',label:'查看所用材料',run:()=>{const evidence=maintenanceTraceEvidence(model.job,step)[0];[...trace.querySelectorAll('[data-trace-evidence]')].find(b=>b.dataset.traceEvidence===evidence.id)?.click();trace.querySelector('[data-trace-locate]').click();}}]:[])];
    }
    return [];
  }
  function signature(origin){return JSON.stringify(resolve(origin).map(({id,label,disabled,href})=>({id,label,disabled:!!disabled,href})));}
  function valid(item){return active===item&&item.origin.isConnected&&item.account===state.me?.id&&item.load===state.loadId&&item.hash===location.hash&&item.signature===signature(item.origin);}
  function open(origin,event){
    const actions=resolve(origin);if(!actions.length||!state.me)return false;
    close(false);
    const menu=document.createElement('div');menu.className='object-menu';menu.role='menu';menu.setAttribute('aria-label','对象操作');
    const focus=event?.target?.closest('[data-object-more],button,[tabindex]')||origin.querySelector('button,a')||origin;
    const item={origin,menu,focus,account:state.me.id,load:state.loadId,hash:location.hash,width:innerWidth,height:innerHeight,signature:signature(origin)};active=item;
    actions.forEach(action=>{
      const button=document.createElement(action.href?'a':'button');if(action.href)button.href=action.href;else button.type='button';
      button.role='menuitem';button.tabIndex=-1;button.textContent=action.label;button.setAttribute('aria-disabled',String(!!action.disabled));
      button.addEventListener('click',async event=>{if(!valid(item)||action.disabled){event.preventDefault();if(!valid(item))close();return;}close();if(!action.href||(action.run&&event.button===0&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey)){event.preventDefault();try{await action.run();}catch(error){toast(error.message);}}});menu.append(button);
    });
    document.body.append(menu);origin.querySelector('[data-object-more]')?.setAttribute('aria-expanded','true');
    item.anchor=origin.querySelector('[data-object-more]')||focus;
    const rect=item.anchor.getBoundingClientRect(),pointer=event?.type==='contextmenu'||event?.button===2;item.rect=rect;
    const x=pointer?event.clientX:rect.left,y=pointer?event.clientY:rect.bottom+4;
    menu.style.left=Math.max(8,Math.min(x,innerWidth-menu.offsetWidth-8))+'px';menu.style.top=Math.max(8,Math.min(y,innerHeight-menu.offsetHeight-8))+'px';
    item.observer=new MutationObserver(()=>{if(!valid(item))close();});item.observer.observe(document.querySelector('#app'),{subtree:true,childList:true,attributes:true});
    menu.querySelector('[aria-disabled="false"]')?.focus({preventScroll:true});return true;
  }
  function originOf(target){return target.closest('[data-object-kind],[data-object-anchor]');}
  document.addEventListener('click',event=>{const button=event.target.closest('[data-object-more]');if(button){const origin=originOf(button);if(origin&&open(origin,event)){event.preventDefault();event.stopImmediatePropagation();}}else if(active&&!active.menu.contains(event.target))close(false);},true);
  document.addEventListener('contextmenu',event=>{if(native(event)){close(false);return;}const origin=originOf(event.target);if(origin&&open(origin,event)){event.preventDefault();event.stopImmediatePropagation();}},true);
  document.addEventListener('keydown',event=>{
    if(active){if(!valid(active)){close();return;}if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();close();return;}if(event.key==='Tab'){close();return;}
      if(active.menu.contains(event.target)&&['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();const items=[...active.menu.querySelectorAll('[aria-disabled="false"]')],index=items.indexOf(document.activeElement);items[event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowDown'?1:items.length-1))%items.length]?.focus();return;}
    }
    if(event.key==='ContextMenu'||event.shiftKey&&event.key==='F10'){if(native(event))return;const origin=originOf(event.target);if(origin&&open(origin,event)){event.preventDefault();event.stopImmediatePropagation();}}
  },true);
  window.addEventListener('hashchange',()=>close(false));window.addEventListener('resize',()=>{if(active&&(active.width!==innerWidth||active.height!==innerHeight))close();});
  // Pointer scrolling dismisses a menu; delayed layout/scroll restoration after
  // a touch-sized trigger is opened must not immediately close it again.
  for(const type of ['wheel','touchmove'])document.addEventListener(type,event=>{if(active&&!active.menu.contains(event.target))close();},{capture:true,passive:true});
  function attach(origin,provider){origin.dataset.objectAnchor='';attached.set(origin,provider);}
  return {more,attach,open,close,resolve};
})();
