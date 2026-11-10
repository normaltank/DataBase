'use strict';

// A reader-local, one-hop view. Only public API projections establish edges.
(() => {
  function destination(type,id,name,role,direction='in',note='',evidence='',provenance='',relationId='') {
    return {type,id,name,role,direction,note,evidence,provenance,key:type+':'+id,relationId:relationId||role+':'+type+':'+id};
  }
  function targetLink(edge,recordId) {
    const page=edge.type==='person'?'people':edge.type==='source'?'sources':'library';
    const params=new URLSearchParams(edge.type==='record'?{q:edge.id}:{id:edge.id,work:recordId});
    return '<a href="#'+page+'?'+params+'" data-explore-target data-type="'+esc(edge.type)+'" data-id="'+esc(edge.id)+'">'+esc(edge.name)+'</a>';
  }
  function disclosure(label,value){return '<div class="record-network-evidence"><button class="button tiny" type="button" data-explore-disclosure aria-expanded="false">'+label+'</button><p class="record-explore-note" hidden>'+esc(value)+'</p></div>';}
  function basis(value){return value?disclosure('查看关联依据',value):'';}
  function projection(record,bylines,affiliations,sources) {
    const edges=[],pending=[];
    for(const item of bylines.items||[]) {
      if(item.status==='confirmed'&&item.target)edges.push(destination(item.target.type==='person'?'person':'source',item.target.id,item.target.name,item.machine?(item.target.type==='person'?'AI 关联作者':'AI 关联机构作者'):(item.target.type==='person'?'已确认作者':'已确认机构作者'),'in','原始署名：'+item.raw_name,item.evidence,item.machine?'AI 正式关联 · '+(item.human_checked?'人工已核对':'尚未人工核对'):'人工确认关联','byline:'+item.id));
      else pending.push(item.raw_name);
    }
    if(!bylines.items?.length&&bylines.raw_authors)pending.push(bylines.raw_authors);
    for(const [field,role] of [['source_id','发布机构'],['serial_id','刊载期刊']]) {
      const source=sources.find(item=>item.id===record[field]);
      if(source)edges.push(destination('source',source.id,source.name,role,'in','','本篇登记的'+(field==='source_id'?'发布来源':'刊载期刊')+'字段'));
    }
    for(const item of affiliations.items||[])if(!item.byline?.removed_at&&item.institution)edges.push(destination('source',item.institution.id,item.institution.name,'文章署名单位','in','本篇署名：'+(item.byline?.raw_name||'原署名'),item.evidence,'','affiliation:'+item.id));
    for(const item of record.linked_records||[])edges.push(destination('record',item.id,item.display_title||item.title,'关联原始资料','out','','本篇明确登记的原始资料关联'));
    for(const item of record.cited_by||[])edges.push(destination('record',item.id,item.display_title||item.title,item.kind==='research_note'?'引用本篇的研究笔记':'引用本篇的中心成果','in','','该研究内容明确登记引用本篇'));
    const center='record:'+record.id,nodes=new Map([[center,{key:center,type:'record',id:record.id,name:record.display_title||record.title}]]);
    for(const edge of edges)nodes.set(edge.key,{key:edge.key,type:edge.type,id:edge.id,name:edge.name});
    return {record,edges,pending,center,nodes:[...nodes.values()],graphEdges:edges.map(e=>({key:e.relationId,role:e.role,from:e.direction==='out'?center:e.key,to:e.direction==='out'?e.key:center}))};
  }
  function render(model,mode) {
    const {record,edges,pending}=model;
    const rows=edges.map(edge=>'<li class="record-explore-edge '+(edge.direction==='out'?'record-explore-out':'')+'"><span class="record-explore-relation">'+esc(edge.direction==='out'?'本篇引用的原始资料':edge.role)+'<svg class="record-explore-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12H4m6-5-6 5 6 5"/></svg></span><div class="record-explore-target">'+targetLink(edge,record.id)+'<button type="button" class="button tiny" data-explore-select="'+esc(edge.key)+'">选择'+esc(edge.name)+'</button>'+(edge.note?'<span class="record-explore-note">'+esc(edge.note)+'</span>':'')+(edge.provenance?'<span class="record-explore-note">'+esc(edge.provenance)+'</span>':'')+basis(edge.evidence)+'</div></li>').join('');
    return '<div class="between"><h3>关联探索</h3><button type="button" class="button" data-explore-close>关闭关联</button></div>'
      +(edges.length?'<div class="record-network-controls" role="group" aria-label="关系图视图"><button class="button" type="button" data-explore-mode="plane" aria-pressed="'+(mode==='plane')+'">平面关系</button><button class="button" type="button" data-explore-mode="space" aria-pressed="'+(mode==='space')+'">空间关系</button><button class="button" type="button" data-explore-reset>重置视角</button><button class="button" type="button" data-explore-locate>查看所选关系</button><button class="button" type="button" data-explore-retry hidden>重试图形</button></div><p class="record-explore-note" data-network-status role="status"></p><div class="record-network-selection" data-network-selection tabindex="-1" aria-live="polite"></div><div class="record-network-viewport" data-network-viewport></div>':'')
      +(rows?'<details class="record-network-text"><summary>关系文字列表</summary><ul class="record-explore-edges" aria-label="本篇的一跳关系">'+rows+'</ul></details>':'<p class="record-explore-empty">尚未登记可查看的关联。</p>')
      +(pending.length?'<div class="record-explore-pending"><strong>原始署名 · 身份未确认</strong><p>'+pending.map(esc).join('；')+'</p></div>':'')
      +'<button type="button" class="button tiny" data-explore-refresh>刷新关联</button>';
  }
  function mount({record,root}) {
    const article=root?.querySelector('.ux-reading-article');
    if(!article||article.querySelector('[data-record-explore]'))return;
    const account=state.me?.id,hash=location.hash,loadId=state.loadId;
    const details=document.createElement('details');
    details.className='record-explore';details.dataset.recordExplore=record.id;
    details.innerHTML='<summary>关联探索</summary><div class="record-explore-content" aria-live="polite"></div>';
    article.querySelector('.ux-reading-toolbar').append(details);
    const content=details.querySelector('.record-explore-content');
    const saved=history.state?.position?.recordExplore;
    let epoch=0,visual=null,visualEpoch=0,model=null,mode=saved?.id===record.id?saved.mode:'plane',selected=saved?.id===record.id?saved.selected:null,viewState=saved?.id===record.id?saved.viewState:null;
    details._explorePosition=()=>({id:record.id,mode,selected,viewState:visual?.getViewState()||viewState});
    const dispose=()=>{visualEpoch++;if(visual)viewState=visual.getViewState();visual?.dispose();visual=null;};
    const current=token=>token===epoch&&details.isConnected&&account===state.me?.id&&hash===location.hash&&loadId===state.loadId;
    function snapshot(){return {center:model.center,nodes:model.nodes,edges:model.graphEdges,selected:selected||model.center};}
    function select(key){
      if(!model||!model.nodes.some(n=>n.key===key))return;selected=key;
      const slot=content.querySelector('[data-network-selection]');if(!slot)return;
      const node=model.nodes.find(n=>n.key===key),relations=model.edges.filter(e=>e.key===key);
      slot.innerHTML='<strong>'+esc(node.name)+'</strong><span class="record-explore-note">'+esc(node.type==='person'?'人物':node.type==='source'?'来源档案':'资料／成果')+'</span>'+(relations.length?relations.map(e=>'<p>'+esc(e.direction==='out'?'本篇 → '+e.name:e.name+' → 本篇')+' · '+esc(e.role)+(e.provenance?' · '+esc(e.provenance):'')+'</p>'+basis(e.evidence)).join('')+targetLink(node,record.id):'<p class="record-explore-note">当前阅读的中心篇目。</p>')+disclosure('详细标识',node.id);
      content.querySelectorAll('[data-explore-select]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.exploreSelect===key)));
      visual?.update(snapshot());
    }
    async function mountGraph(){
      dispose();const token=visualEpoch,slot=content.querySelector('[data-network-viewport]');
      if(!slot||!model?.edges.length)return;
      const valid=()=>token===visualEpoch&&current(epoch)&&details.open&&!document.hidden;
      const status=message=>{if(current(epoch)&&details.open){const target=content.querySelector('[data-network-status]');if(target)target.textContent=message;const failed=/未能|不可用|失败/.test(message);const retry=content.querySelector('[data-explore-retry]');if(retry)retry.hidden=!failed;if(failed){const text=content.querySelector('.record-network-text');if(text)text.open=true;}}};
      status('正在加载关系图…');
      try{const instance=await window.visualLoader.mount('network',slot,{snapshot:snapshot(),mode,viewState,onSelect:select,onStatus:status},{isCurrent:valid});if(valid()){visual=instance;status('');}else instance?.dispose();}
      catch(error){if(valid())status('图形未能加载，可继续使用下方文字关系，或重试图形。');}
    }
    async function load() {
      const token=++epoch;
      const focusAtStart=document.activeElement,restoreFocus=content.contains(focusAtStart);
      content.setAttribute('aria-busy','true');
      content.querySelector('[data-explore-error]')?.remove();
      if(!model)content.innerHTML='<p class="record-explore-empty" role="status">正在读取关联…</p>';
      try {
        const session=await api('/api/session');
        if(!current(token))return;
        if(session.user?.id!==account)throw Object.assign(new Error('账号已切换'),{status:401});
        const fresh=await api('/api/records/'+encodeURIComponent(record.id));
        if(!current(token)||!details.open)return;
        const [bylines,affiliations]=isResearchContent(fresh.kind)?[{items:[]},{items:[]}]:await Promise.all([
          api('/api/records/'+encodeURIComponent(record.id)+'/bylines'),
          api('/api/records/'+encodeURIComponent(record.id)+'/affiliations')]);
        if(!current(token)||!details.open)return;
        const sources=await Promise.all([...new Set([fresh.source_id,fresh.serial_id].filter(Boolean))].map(id=>api('/api/sources/'+encodeURIComponent(id))));
        if(!current(token)||!details.open)return;
        const latestSession=await api('/api/session');
        if(!current(token))return;
        if(latestSession.user?.id!==account)throw Object.assign(new Error('账号已切换'),{status:401});
        const next=projection(fresh,bylines,affiliations,sources);
        const signature=value=>JSON.stringify([value.edges,value.pending,value.record.display_title||value.record.title]);
        if(model&&signature(model)===signature(next)){model=next;if(!visual)mountGraph();return;}
        const previousSlot=visual&&content.querySelector('[data-network-viewport]');
        model=next;
        if(!model.nodes.some(n=>n.key===selected))selected=model.center;
        content.innerHTML=render(model,mode);
        const nextSlot=content.querySelector('[data-network-viewport]');
        if(previousSlot&&nextSlot){nextSlot.replaceWith(previousSlot);select(selected);visual.resize();}
        else{dispose();select(selected);mountGraph();}
      } catch(error) {
        if(current(token)&&details.open){
          if([401,403,404].includes(error.status)){dispose();viewState=null;model=null;content.replaceChildren();}
          else if(!model)content.replaceChildren();
          content.insertAdjacentHTML('afterbegin','<div data-explore-error><p class="record-explore-empty" role="alert">关联读取失败，'+(model?'当前内容尚未更新。':'请重试。')+'</p><button type="button" class="button tiny" data-explore-refresh>重试读取关联</button></div>');
        }
      } finally {
        if(current(token)){content.removeAttribute('aria-busy');if(restoreFocus&&!focusAtStart.isConnected&&document.activeElement===document.body){const attr=['data-explore-mode','data-explore-select','data-explore-refresh','data-explore-target'].find(key=>focusAtStart.hasAttribute(key));const target=attr?content.querySelector('['+attr+'="'+CSS.escape(focusAtStart.getAttribute(attr))+'"]'):null;(target||content.querySelector('[data-explore-refresh]'))?.focus({preventScroll:true});}}
      }
    }
    details.addEventListener('toggle',()=>{if(details.open)load();else{epoch++;dispose();model=null;content.replaceChildren();}});
    details.addEventListener('click',event=>{
      if(event.target.closest('[data-explore-close]')){details.open=false;details.querySelector('summary').focus({preventScroll:true});return;}
      if(event.target.closest('[data-explore-refresh]'))load();
      const choose=event.target.closest('[data-explore-select]');if(choose)select(choose.dataset.exploreSelect);
      const disclosureButton=event.target.closest('[data-explore-disclosure]');if(disclosureButton){const open=disclosureButton.getAttribute('aria-expanded')!=='true';disclosureButton.setAttribute('aria-expanded',String(open));disclosureButton.nextElementSibling.hidden=!open;}
      const switcher=event.target.closest('[data-explore-mode]');
      if(switcher){mode=switcher.dataset.exploreMode;content.querySelectorAll('[data-explore-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b===switcher)));if(visual){try{visual.setMode(mode);}catch(error){/* text and retry stay available */}}else mountGraph();}
      if(event.target.closest('[data-explore-reset]'))visual?.reset();
      if(event.target.closest('[data-explore-locate]')){const slot=content.querySelector('[data-network-selection]');slot?.scrollIntoView({block:'start'});slot?.focus({preventScroll:true});}
      if(event.target.closest('[data-explore-retry]'))mountGraph();
      const link=event.target.closest('[data-explore-target]');
      if(!link||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||event.button!==0)return;
      event.preventDefault();
      const type=link.dataset.type,id=link.dataset.id;
      if(type!=='record') {go(type==='person'?'people':'sources',{id,work:record.id});return;}
      continuityRemember();
      const position=continuityPosition();
      if(!position){openRecord(id).catch(error=>toast(error.message));return;}
      const nextHash='#library?'+new URLSearchParams({q:id});
      history.pushState({position:{account,hash:nextHash,reader:id,view:'list'},recordExploreReturn:{position,title:record.display_title||record.title}},'',nextHash);
      route().catch(error=>toast(error.message));
    });
    const back=history.state?.recordExploreReturn;
    if(back?.position?.account===account) {
      const button=document.createElement('button');button.type='button';button.className='button record-explore-back';
      button.textContent='返回前一篇：'+back.title;
      button.addEventListener('click',()=>{
        history.pushState({position:back.position},'',back.position.hash);
        route().catch(error=>toast(error.message));
      });
      article.prepend(button);
    }
    // Revalidate visible relations after returning from another window.
    const refresh=()=>{if(!document.hidden&&details.isConnected&&details.open)load();};
    const visibility=()=>{if(document.hidden){epoch++;dispose();}else refresh();};
    document.addEventListener('visibilitychange',visibility);
    window.addEventListener('focus',refresh);
    const routeChanged=()=>{if(!current(epoch)){dispose();viewState=null;model=null;content.replaceChildren();}};
    window.addEventListener('hashchange',routeChanged);
    const observer=new MutationObserver(()=>{if(!details.isConnected){epoch++;dispose();model=null;window.removeEventListener('focus',refresh);document.removeEventListener('visibilitychange',visibility);window.removeEventListener('hashchange',routeChanged);observer.disconnect();}});
    observer.observe(document.body,{childList:true,subtree:true});
  }
  document.addEventListener('library:reader-rendered',event=>mount(event.detail));
})();
