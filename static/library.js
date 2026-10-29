'use strict';

// Library workspace: list/card presentation and explicitly selected stable IDs.
const libraryWorkspace={view:'list',items:[],page:1,total:0,size:20,readerId:null,readerRecord:null,readerEpoch:0,returnFocus:null,returnY:0,account:null,context:null,selected:new Set(),organizing:false,batch:null};
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
function libraryRouteContext(savedVersion=null) {
  // A saved ID is not an effective query until its persisted conditions resolve.
  if(state.params.has('saved_search')&&savedVersion===null)return;
  const active=['library','compilations','favorites','review'].includes(state.page),query=recordQuery();
  query.delete('page');query.delete('size');query.sort();
  const context=active?state.page+'?'+query+(savedVersion===null?'':'@'+savedVersion):null;
  if(libraryWorkspace.account!==state.me?.id){libraryResetAccount();libraryWorkspace.account=state.me?.id;}
  else if(libraryWorkspace.context!==context)libraryClearSelection(active?'查找条件已改变，已清空选择。':'已离开资料库，已清空选择。');
  libraryWorkspace.context=context;libraryCloseReader(false);
}
function libraryResetAccount() {
  libraryCloseReader(false);libraryClearSelection();
  Object.assign(libraryWorkspace,{account:null,context:null,items:[],view:'list',returnFocus:null,organizing:false,batch:null,readingConfirmation:null,finishContext:null});
  state.detail=null;
}
function libraryCheckbox(record) {
  return '<label class="library-select"><input type="checkbox" data-library-select="'+esc(record.id)+'" aria-label="选择资料：'+esc(record.title)+'" '+(libraryWorkspace.selected.has(record.id)?'checked':'')+'><span class="sr-only">选择</span></label>';
}

const readingAvailability={body:'有保存正文',file:'有原文件',link:'有原文线索',chinese:'有可读中文',translation_pending:'中文待处理',no_abstract:'无原摘要',bibliography:'仅题录'};
function readingFacet(data,key,label,labels={}){
  const selected=(state.params.get(key)||'').split('|').filter(Boolean),items=[...(data.facets?.[key]||[])];
  for(const value of selected)if(!items.some(item=>item.value===value))items.push({value,count:0});
  const name=value=>value==='__unknown__'?'未知／待分类':value==='__pending__'?'待确认':labels[value]||(key==='source'?sourceById(value)?.name:null)||value;
  return '<details class="reading-facet"><summary>'+label+(selected.length?' · '+selected.map(name).map(esc).join('、'):' · 全部')+'</summary><div class="reading-facet-options">'+(items.map(item=>'<label><input type="checkbox" name="'+key+'" value="'+esc(item.value)+'" '+(selected.includes(item.value)?'checked':'')+'><span>'+esc(name(item.value))+'</span><small>'+item.count+'</small></label>').join('')||'<p class="small muted">当前范围没有已登记的选项。</p>')+'</div></details>';
}
function readingResetParams(){
  const p=new URLSearchParams();
  for(const key of ['source_section','collection','feed','batch','batch_scope','status','editable','evidence_of','source_international'])if(state.params.has(key))p.set(key,state.params.get(key));
  if(state.params.has('source')&&state.params.get('source_filter')!=='1')p.set('source',state.params.get('source'));
  return p;
}
function readingLibraryHTML(data){
  const p=recordQuery(),batch=libraryWorkspace.batch,isNew=!!batch,c=state.collections.find(c=>c.id===p.get('collection'));
  const title=c?.name||({library:'资料',compilations:'独立成果与跨期译稿',favorites:'我的收藏',review:'待核对'}[state.page]||'资料');

  const chips=[...p].filter(([key,value])=>savedSearchKeys.has(key)&&!['sort','feed'].includes(key)&&value);
  const dateField=p.get('date_field')||'published';
  const mergeTool=state.schema>=4?(isMaintenancePage()?(state.me.role==='admin'?linkButton('整理重复','duplicates','record'):''):linkButton('整理个人成果重复','duplicates','personal')):'';
  const tools=linkButton('批量整理','reading-organize')+mergeTool+linkButton('导出完整内容','export-content','','button tiny').replace('data-id=""','data-query="'+esc(p)+'"')+'<a class="button tiny" href="/api/export?'+esc(p)+'">导出清单</a>';
  return '<div class="ux-library reading-library"><div class="page-heading between"><h1>'+esc(title)+'</h1>'+(state.page==='compilations'?linkButton('导入成品','import-output','','button primary tiny'):linkButton('补充资料','new-record','','button tiny'))+'</div>'
    +(state.page==='library'?'<nav class="reading-tabs" aria-label="资料范围"><button type="button" data-action="reading-feed" data-feed="new" aria-current="'+(isNew?'page':'false')+'">新文章</button><button type="button" data-action="reading-feed" data-feed="all" aria-current="'+(!isNew?'page':'false')+'">全部资料</button></nav>':'')
    +(state.page==='compilations'?'<p class="small">旧笔记、说明和摘录可在'+linkButton('全部资料与旧研究积累','work-old-content')+'继续查阅。</p>':'')
    +(batch?'<div class="reading-batch"><div><strong>新增 '+data.total+' 条</strong><span>'+ (batch.reason==='return_visit'?'未确认浏览':p.get('batch_scope')==='all'?'全部未确认':'近30天收录')+' · 共 '+batch.pending_total+' 条待浏览</span></div><div class="row wrap"><button type="button" class="button tiny" data-action="reading-scope">'+(p.get('batch_scope')==='all'?'只看近期新增':'查看全部新增')+'</button><button type="button" class="button tiny" data-action="reading-finish">结束本次浏览</button></div></div>':'')
    +'<form data-reading-filters><div class="reading-quick"><label class="reading-keyword"><span>资料关键词</span><input name="q" value="'+esc(p.get('q'))+'" placeholder="中文题名、摘要、作者或原文（按 / 聚焦）"></label>'+readingFacet(data,'country','研究对象国')+'<label class="reading-time-label"><span class="sr-only">时间类型</span><select name="date_field" aria-label="时间类型">'+selectOptions({published:'发表时间',collected:'首次收录',updated:'最近修订'},dateField,'选择时间')+'</select></label><button type="button" class="button tiny" data-action="reading-days" data-days="30">近30天</button><button type="submit" class="button primary">查找</button></div>'
    +'<details class="reading-more"><summary>时间与更多筛选'+(chips.length?' · 已选 '+chips.length+' 项':'')+'</summary><div class="reading-date-range"><label>起始日期<input type="date" name="from" value="'+esc(p.get('from'))+'"></label><label>截止日期<input type="date" name="to" value="'+esc(p.get('to'))+'"></label><label><input type="checkbox" name="date_unknown" value="1" '+(p.get('date_unknown')==='1'?'checked':'')+'>只看日期未知</label><button type="button" class="button tiny" data-action="reading-days" data-days="7">近7天</button><button type="button" class="button tiny" data-action="reading-days" data-days="90">近90天</button></div>'
    +'<p class="small muted">发表年份或年月按可能日期范围相交；研究对象按文章内容登记，与来源国别分开。</p><div class="reading-facets">'+(p.has('source')&&p.get('source_filter')!=='1'?'<p class="small">固定来源：'+esc(p.get('source').split('|').map(id=>sourceById(id)?.name||id).join('、'))+'</p>':readingFacet(data,'source','来源'))+readingFacet(data,'source_country','来源国别')+readingFacet(data,'source_group','来源类型',{institution:'机构',journal:'期刊',publication:'其他出版物'})+readingFacet(data,'kind','文章类型',kinds)+readingFacet(data,'topic','主题')+readingFacet(data,'language','原文语言',languages)+readingFacet(data,'availability','内容可用性',readingAvailability)+'</div><div class="row wrap"><button type="submit" class="button">应用筛选</button><button type="button" class="button light" data-action="reading-reset">重置筛选</button></div></details><div class="form-error" role="alert"></div></form>'
    +(chips.length?'<div class="reading-current small">当前：'+esc(savedSearchSummary(Object.fromEntries(chips)))+' '+linkButton('重置筛选','reading-reset','','ux-read-link')+'</div>':'')
    +'<div class="results-head"><span>共 <strong>'+data.total+'</strong> 条'+(isNew?'本批新增':'资料')+'</span><select id="sort-select" aria-label="排序方式" '+(isNew?'disabled':'')+'>'+selectOptions(isNew?{collected:'按本批收录顺序'}:{collected:'按首次收录',date:'按发表时间',updated:'按最近修订',title:'按题名'},isNew?'collected':p.get('sort')||'collected')+'</select><details class="reading-tools"><summary>整理与导出</summary><div data-library-tools>'+tools+'</div></details></div><div class="record-list"></div>'
    +'<div class="pagination"><button class="button tiny" data-action="page" data-id="'+(data.page-1)+'" '+(data.page<=1?'disabled':'')+'>上一页</button><span>第 '+data.page+' / '+Math.max(1,Math.ceil(data.total/data.size))+' 页</span><button class="button tiny" data-action="page" data-id="'+(data.page+1)+'" '+(data.page*data.size>=data.total?'disabled':'')+'>下一页</button></div></div>';
}
function readingArchiveTabs(){return '<nav class="reading-tabs" aria-label="档案类型">'+[['sources','机构与刊物'],['people','作者']].map(([id,label])=>'<button type="button" data-action="nav" data-id="'+id+'" aria-current="'+(state.page===id?'page':'false')+'">'+label+'</button>').join('')+'</nav>';}
async function readingPersonalPage(){
  const saved=await api('/api/saved-searches?size=1');
  return '<div class="page-heading"><h1>我的</h1><p>'+esc(state.me.name)+'</p></div><div class="reading-personal-links">'+[['favorites','收藏资料'],['collections','资料夹'],['drafts','未提交草稿']].map(([id,label])=>'<button class="panel reading-personal-link" data-action="nav" data-id="'+id+'">'+label+icon('arrow')+'</button>').join('')+'<button class="panel reading-personal-link" data-action="saved-manage">关注条件 · '+saved.total+' 项'+icon('arrow')+'</button></div><section class="system-card section-gap"><h2>个人账号与导出</h2><div class="row wrap">'+linkButton('修改我的密码','own-password')+linkButton('导出可见内容','export-content')+linkButton('提供采集来源','new-source')+'</div><p class="small muted">仅导出当前账号可读取的内容。</p></section>';
}
function readingAbstract(record){
  if(isResearchContent(record.kind))return record.abstract?'<section class="detail-section"><h3>摘要与说明</h3><p class="prose">'+esc(record.abstract)+'</p></section>':'';
  const origin={human:'人工中文 · 当前校订版本',machine:'机器中文 · 尚未人工校订',original:record.has_chinese?'原始中文资料':'原始信息 · 中文待处理'}[record.translation_origin]||'原始信息';
  return '<section class="detail-section reading-language"><div class="row wrap"><span>'+origin+'</span>'+(record.has_chinese?'<button class="button tiny" data-action="reading-language" data-language="chinese" aria-pressed="true">中文</button><button class="button tiny" data-action="reading-language" data-language="original" aria-pressed="false">原文</button>':'')+'</div><div data-reading-abstract="chinese">'+(record.display_abstract?'<h3>'+(record.abstract_is_chinese?'中文摘要':'原文摘要')+'</h3><p class="prose">'+esc(record.display_abstract)+'</p>':'<p>原始摘要缺失。</p>')+'</div><div data-reading-abstract="original" hidden>'+(record.abstract?'<h3>原文摘要</h3><p class="prose">'+esc(record.abstract)+'</p>':'<p>原始摘要缺失。</p>')+'</div>'+'<p class="small muted">发表 '+esc(record.published_on||'未知')+' · 首次收录 '+esc(record.created_at?.slice(0,10)||'未知')+' · 最近修订 '+esc(record.updated_at?.slice(0,10)||'未知')+'</p></section>';
}
function readingChooseLanguage(article,record,original){
  if(!article||!record)return;
  article.dataset.readingLanguage=original?'original':'chinese';
  article.querySelector('[data-reading-title]').textContent=original?(record.original_title||record.title):(record.display_title||record.title);
  article.querySelectorAll('[data-reading-abstract]').forEach(el=>el.hidden=el.dataset.readingAbstract!==(original?'original':'chinese'));
  article.querySelectorAll('[data-action="reading-language"]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.language===(original?'original':'chinese'))));
  uxUpdateReadingStats(article);
}

document.addEventListener('submit',event=>{
  const form=event.target.closest('[data-reading-filters]');if(!form)return;event.preventDefault();
  const data=new FormData(form),p=readingResetParams();
  for(const key of new Set([...data.keys()])){const value=data.getAll(key).filter(Boolean).join('|');if(value)p.set(key,value);}
  if(p.get('from')&&p.get('to')&&p.get('from')>p.get('to')){form.querySelector('.form-error').textContent='起始日期不能晚于截止日期。';return;}
  if(data.has('source')&&!p.has('source_section')&&!(state.params.has('source')&&state.params.get('source_filter')!=='1'))p.set('source_filter','1');
  p.delete('page');go(state.page,p);
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action^="reading-"]');if(!button)return;
  const action=button.dataset.action,account=state.me?.id,load=state.loadId;
  try{
    if(action==='reading-feed'){const p=readingResetParams();p.set('feed',button.dataset.feed);p.delete('batch');p.delete('batch_scope');go('library',p);}
    else if(action==='reading-reset')go(state.page,readingResetParams());
    else if(action==='reading-scope')go(state.page,parameters({batch_scope:state.params.get('batch_scope')==='all'?'recent':'all',page:''}));
    else if(action==='reading-days'){const form=button.closest('form'),end=new Date(),start=new Date(end);start.setUTCDate(start.getUTCDate()-Number(button.dataset.days)+1);form.elements.from.value=start.toISOString().slice(0,10);form.elements.to.value=end.toISOString().slice(0,10);form.elements.date_unknown.checked=false;form.requestSubmit();}
    else if(action==='reading-organize'){libraryWorkspace.organizing=!libraryWorkspace.organizing;document.querySelector('.library-workspace')?.classList.toggle('library-organizing',libraryWorkspace.organizing);button.textContent=libraryWorkspace.organizing?'结束整理':'批量整理';}
    else if(action==='reading-finish'){
      const count=libraryWorkspace.total;
      libraryWorkspace.finishContext={conditions:Object.fromEntries(recordQuery()),confirmation:libraryWorkspace.readingConfirmation,batch:libraryWorkspace.batch.id};
      const explanation=count?'将当前筛选结果中的 '+count+' 条资料确认为已浏览。打开页面本身不会确认；被当前筛选排除的新增继续保留。':'当前筛选没有结果，本次确认 0 条。全部未浏览资料继续保留；结束后保留条件重新查找。';
      modal('结束本次浏览','<p>'+explanation+'</p><p class="small muted">'+esc(savedSearchSummary(savedSearchConditions()))+'</p><button class="button primary" data-action="reading-confirm-finish">'+(count?'确认这 '+count+' 条已浏览':'确认 0 条并重新查找')+'</button>');
    }else if(action==='reading-confirm-finish'){
      button.disabled=true;const pending=libraryWorkspace.finishContext;
      const result=await api('/api/reading-batches/'+encodeURIComponent(pending.batch)+'/finish',{method:'POST',body:{conditions:pending.conditions,confirmation:pending.confirmation}});
      if(account!==state.me?.id||load!==state.loadId||!button.isConnected)return;
      if(result.confirmed){toast('已确认当前结果 '+result.confirmed+' 条，其余新增继续保留。');go('library',{feed:'new'});}
      else{const next=new URLSearchParams(pending.conditions);next.delete('batch');next.delete('page');next.set('feed','new');toast('本次确认 0 条，全部未浏览资料继续保留。');go('library',next);}
    }else if(action==='reading-reread'){
      closeModal();go(state.page,parameters({page:''}));
    }else if(action==='reading-language'){
      const article=button.closest('.ux-reading-article'),record=libraryWorkspace.readerRecord||state.detail?.data;if(!article||!record)return;
      readingChooseLanguage(article,record,button.dataset.language==='original');
      if(typeof continuityRemember==='function')continuityRemember();
    }
  }catch(error){if(account===state.me?.id&&load===state.loadId){
    if(action==='reading-confirm-finish'&&error.status===409)modal('请重新读取结果','<p>'+esc(error.message)+'</p><button class="button primary" data-action="reading-reread">保留条件，重新读取</button>');
    else{toast(error.message);if(button.isConnected)button.disabled=false;}
  }}
});

function libraryRow(record) {
  const source=sourceById(record.serial_id||record.source_id)?.name||record.publication_title||'来源未登记';
  return '<article class="library-row" data-library-record="'+esc(record.id)+'">'+libraryCheckbox(record)+'<div class="library-row-main"><h2 class="record-title">'+linkButton(esc(record.display_title||record.title),'detail',record.id,'title-button')+'</h2><div class="library-row-source">'+esc(source)+'</div><div class="library-row-dates"><span title="发表时间">'+esc(record.published_on||'发表未知')+'</span><span title="首次收录">'+esc(record.created_at?.slice(0,10)||'收录未知')+'</span></div><div data-library-attachment-matches="'+esc(record.id)+'">'+(typeof attachmentMatchSection==='function'?attachmentMatchSection(record):'')+'</div></div><div class="library-row-status">'+(record.translation_origin==='machine'?'<span class="reading-origin">机器译题</span>':record.translation_origin==='human'?'<span class="reading-origin">人工中文</span>':'')+(record.visibility==='restricted'?'<span class="reading-origin">限授权成员</span>':'')+'</div></article>';
}
function libraryResultsHTML() {
  if(!libraryWorkspace.items.length)return empty('暂时没有符合条件的资料','','file')+'<div class="empty-actions">'+linkButton('重置筛选','reading-reset','','button primary')+linkButton('查看全部资料','work-read')+'</div>';
  return libraryWorkspace.items.map(record=>libraryWorkspace.view==='list'?libraryRow(record):'<div class="library-card-item" data-library-record="'+esc(record.id)+'">'+libraryCheckbox(record)+recordCard(record)+'</div>').join('');
}
async function libraryWorkspacePage() {
  const account=state.me?.id,loadId=state.loadId;
  const current=()=>account===state.me?.id&&loadId===state.loadId;
  const isNew=state.page==='library'&&(state.params.get('feed')||(!state.params.size?'new':'all'))==='new';
  if(isNew){
    const batch=await api('/api/reading-batches',{method:'POST',body:{}});
    if(!current())throw new Error('资料查找已更新。');
    libraryWorkspace.batch=batch;state.params.set('batch',batch.id);
    state.params.set('feed','new');
    if(!state.params.has('batch_scope'))state.params.set('batch_scope',batch.reason==='return_visit'?'all':'recent');
  }else{libraryWorkspace.batch=null;state.params.delete('batch');state.params.delete('batch_scope');}
  libraryRouteContext(savedSearchUI.active?.version??null);
  const query=recordQuery();if(!query.has('size'))query.set('size','20');
  const data=await api('/api/records?'+query);
  if(account!==state.me?.id||loadId!==state.loadId)throw new Error('资料查找已更新。');
  Object.assign(libraryWorkspace,{items:data.items,page:data.page,total:data.total,size:data.size,readingConfirmation:data.reading_confirmation});
  const root=document.createElement('div');root.innerHTML=await uxLibraryPage(data);
  const library=root.firstElementChild;
  library.classList.add('library-workspace');library.dataset.view=libraryWorkspace.view;
  library.classList.toggle('library-organizing',libraryWorkspace.organizing);
  const views=document.createElement('div');views.className='library-views';views.setAttribute('aria-label','资料显示方式');
  views.innerHTML=['list','cards'].map(view=>'<button class="button tiny" type="button" data-action="library-view" data-view="'+view+'" aria-pressed="'+(libraryWorkspace.view===view)+'">'+(view==='list'?'紧凑列表':'卡片视图')+'</button>').join('');
  library.querySelector('.results-head').append(views);
  const resultControls=document.createElement('div');resultControls.className='library-result-controls';
  const sort=library.querySelector('#sort-select');sort.before(resultControls);resultControls.append(sort,views);
  const selection=document.createElement('section');selection.className='library-selection';selection.setAttribute('aria-label','选择资料');
  selection.innerHTML='<strong data-library-selection-count>已选 '+libraryWorkspace.selected.size+' 条</strong><button class="button tiny" type="button" data-action="library-select-page" '+(!data.items.length?'disabled':'')+'>选择当前页</button><button class="button tiny" type="button" data-action="library-clear-selection" '+(!libraryWorkspace.selected.size?'disabled':'')+'>清空选择</button><span class="small muted" data-library-selection-scope>仅勾选的资料 · 最多 '+librarySelectionLimit+' 条</span><div data-library-batch-actions></div>';
  library.querySelector('.record-list').before(selection);
  library.querySelector('[data-library-tools]').append(views);
  const tabs=library.querySelector('.reading-tabs');if(tabs){const heading=library.querySelector('.page-heading');heading.querySelector('h1').after(tabs);}
  const columns=document.createElement('div');columns.className='reading-column-labels';columns.innerHTML='<span>题名</span><span>来源</span><span>发表 / 收录</span>';library.querySelector('.results-head').append(columns);
  const more=library.querySelector('.reading-more');library.querySelector('.reading-quick').append(more);
  library.querySelector('[data-library-tools]').prepend(resultControls);
  library.querySelector('.record-list').innerHTML=libraryResultsHTML();
  const workspace=document.createElement('div');workspace.className='library-results-workspace';
  const list=library.querySelector('.record-list');list.before(workspace);workspace.append(list);
  workspace.insertAdjacentHTML('beforeend','<section class="library-reader" aria-label="连续阅读" hidden></section>');
  return root.innerHTML;
}
function libraryCloseReader(restore=true) {
  if(state.detail?.type==='record'&&state.detail.data.id===libraryWorkspace.readerId)state.detail=null;
  libraryWorkspace.readerEpoch++;libraryWorkspace.readerId=null;libraryWorkspace.readerRecord=null;
  const panel=document.querySelector('.library-reader');if(panel){panel._readingProgressCleanup?.();panel.hidden=true;panel.replaceChildren();panel.closest('.library-workspace').classList.remove('library-reading');}
  document.querySelector('.library-workspace .record-list')?.removeAttribute('inert');
  document.querySelectorAll('.library-current').forEach(row=>row.classList.remove('library-current'));
  document.body.classList.remove('library-narrow-reading');
  libraryReaderBackground(false);
  if(restore){let focus=libraryWorkspace.returnFocus;if(!focus?.isConnected)focus=[...document.querySelectorAll('.record-list [data-action]')].find(button=>button.dataset.id===libraryWorkspace.returnFocus?.dataset.id&&button.dataset.action===libraryWorkspace.returnFocus?.dataset.action);focus?.focus({preventScroll:true});window.scrollTo(0,libraryWorkspace.returnY);if(typeof continuityRemember==='function')continuityRemember();}
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
    panel.innerHTML='<header class="library-reader-head"><button class="button tiny" type="button" data-action="library-reader-close">返回列表</button><div class="row"><button class="button tiny" type="button" data-action="library-reader-prev" title="上一条 (k / Alt+↑)" '+(index<=0?'disabled':'')+'>上一条</button><button class="button tiny" type="button" data-action="library-reader-next" title="下一条 (j / Alt+↓)" '+(index<0||index>=libraryWorkspace.items.length-1?'disabled':'')+'>下一条</button></div><p>本页第 '+(index+1)+' / '+libraryWorkspace.items.length+' 条</p></header><div class="drawer-body library-reader-body"></div>';
    const body=panel.querySelector('.library-reader-body');await uxReadRecord(record,body);
    if(epoch!==libraryWorkspace.readerEpoch||account!==state.me?.id||!panel.isConnected){body.replaceChildren();return;}
    panel.scrollTop=0;body.scrollTop=0;
    if(firstOpen&&!libraryReaderMedia.matches){const workspace=panel.closest('.library-results-workspace');window.scrollTo(0,Math.max(0,window.scrollY+workspace.getBoundingClientRect().top-16));}
    libraryWorkspace.readerRecord=record;if(typeof continuityRemember==='function')continuityRemember();
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
  const panel=document.querySelector('.library-reader:not([hidden])');if(event.defaultPrevented||event.isComposing||event.keyCode===229||!panel||!['library','compilations','favorites','review'].includes(state.page)||document.querySelector('#modal-root .overlay'))return;
  if(event.key==='Escape'&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&!event.shiftKey&&!keyboardEditing(event)){event.preventDefault();libraryCloseReader();}
  else if(!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&((event.altKey&&(event.key==='ArrowUp'||event.key==='ArrowDown'))||(!event.altKey&&(event.key==='j'||event.key==='k')))){
    if(keyboardEditing(event))return;
    event.preventDefault();
    const index=libraryWorkspace.items.findIndex(record=>record.id===libraryWorkspace.readerId),next=libraryWorkspace.items[index+(['ArrowUp','k'].includes(event.key)?-1:1)];
    if(next)libraryOpenReader(next.id).catch(error=>toast(error.message));
  }
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
