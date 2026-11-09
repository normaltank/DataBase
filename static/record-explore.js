'use strict';

// A reader-local, one-hop view. Only public API projections establish edges.
(() => {
  function destination(type,id,name,role,direction='in',note='') {
    return {type,id,name,role,direction,note};
  }
  function targetLink(edge,recordId) {
    const page=edge.type==='person'?'people':edge.type==='source'?'sources':'library';
    const params=new URLSearchParams(edge.type==='record'?{q:edge.id}:{id:edge.id,work:recordId});
    return '<a href="#'+page+'?'+params+'" data-explore-target data-type="'+esc(edge.type)+'" data-id="'+esc(edge.id)+'">'+esc(edge.name)+'</a>';
  }
  function render(record,bylines,affiliations) {
    const edges=[],pending=[];
    for(const item of bylines.items||[]) {
      if(item.status==='confirmed'&&item.target)edges.push(destination(item.target.type==='person'?'person':'source',item.target.id,item.target.name,item.machine?(item.target.type==='person'?'AI 关联作者':'AI 关联机构作者'):(item.target.type==='person'?'已确认作者':'已确认机构作者'),'in',item.raw_name));
      else pending.push(item.raw_name);
    }
    if(!bylines.items?.length&&bylines.raw_authors)pending.push(bylines.raw_authors);
    for(const [field,role] of [['source_id','发布机构'],['serial_id','刊载期刊']]) {
      const source=state.sources.find(item=>item.id===record[field]);
      if(source)edges.push(destination('source',source.id,source.name,role));
    }
    for(const item of affiliations.items||[])if(!item.byline?.removed_at&&item.institution)edges.push(destination('source',item.institution.id,item.institution.name,'文章署名单位','in','本篇署名：'+(item.byline?.raw_name||'原署名')));
    for(const item of record.linked_records||[])edges.push(destination('record',item.id,item.display_title||item.title,'关联原始资料','out'));
    for(const item of record.cited_by||[])edges.push(destination('record',item.id,item.display_title||item.title,item.kind==='research_note'?'引用本篇的研究笔记':'引用本篇的中心成果','in'));
    const rows=edges.map(edge=>'<li class="record-explore-edge '+(edge.direction==='out'?'record-explore-out':'')+'"><span class="record-explore-relation">'+esc(edge.direction==='out'?'本篇引用的原始资料':edge.role)+'<svg class="record-explore-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12H4m6-5-6 5 6 5"/></svg></span><div class="record-explore-target">'+targetLink(edge,record.id)+(edge.note?'<span class="record-explore-note">'+esc(edge.note)+'</span>':'')+'</div></li>').join('');
    return '<div class="record-explore-center"><span>'+esc(isResearchContent(record.kind)?'本篇研究内容':'本篇资料')+'</span><strong>'+esc(record.display_title||record.title)+'</strong></div>'
      +(rows?'<ul class="record-explore-edges" aria-label="本篇的一跳关系">'+rows+'</ul>':'<p class="record-explore-empty">尚未登记可查看的关联。</p>')
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
    article.querySelector('.ux-reading-toolbar').after(details);
    const content=details.querySelector('.record-explore-content');
    let epoch=0;
    const current=token=>token===epoch&&details.isConnected&&account===state.me?.id&&hash===location.hash&&loadId===state.loadId;
    async function load() {
      const token=++epoch;
      const restoreFocus=content.contains(document.activeElement);
      content.setAttribute('aria-busy','true');
      content.innerHTML='<p class="record-explore-empty" role="status">正在读取关联…</p>';
      try {
        const session=await api('/api/session');
        if(!current(token)||session.user?.id!==account)throw new Error('账号已切换');
        const fresh=await api('/api/records/'+encodeURIComponent(record.id));
        if(!current(token)||!details.open)return;
        const [bylines,affiliations]=isResearchContent(fresh.kind)?[{items:[]},{items:[]}]:await Promise.all([
          api('/api/records/'+encodeURIComponent(record.id)+'/bylines'),
          api('/api/records/'+encodeURIComponent(record.id)+'/affiliations')]);
        if(!current(token)||!details.open)return;
        const latestSession=await api('/api/session');
        if(!current(token)||latestSession.user?.id!==account)throw new Error('账号已切换');
        content.innerHTML=render(fresh,bylines,affiliations);
      } catch(error) {
        if(current(token)&&details.open)content.innerHTML='<p class="record-explore-empty" role="alert">关联读取失败，请重试。</p><button type="button" class="button tiny" data-explore-refresh>重试读取关联</button>';
      } finally {
        if(current(token)){content.removeAttribute('aria-busy');if(restoreFocus)content.querySelector('[data-explore-refresh]')?.focus({preventScroll:true});}
      }
    }
    details.addEventListener('toggle',()=>{if(details.open)load();else{epoch++;content.replaceChildren();}});
    details.addEventListener('click',event=>{
      if(event.target.closest('[data-explore-refresh]'))load();
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
    const refresh=()=>{if(details.isConnected&&details.open)load();};
    window.addEventListener('focus',refresh);
    const observer=new MutationObserver(()=>{if(!details.isConnected){epoch++;window.removeEventListener('focus',refresh);observer.disconnect();}});
    observer.observe(document.body,{childList:true,subtree:true});
  }
  document.addEventListener('library:reader-rendered',event=>mount(event.detail));
})();
