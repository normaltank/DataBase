'use strict';

// Views are projections of the same authorized response. Only a display preference
// is persisted; titles, cards, files and access decisions stay in the live page.
const bookshelfPreference='research-bookshelf-view';
let bookshelfMode='shelf',bookshelfMotion=null,bookshelfOpening=false,bookshelfAccount=null,bookshelfPartitionDraft=null;
try{if(localStorage.getItem(bookshelfPreference)==='list')bookshelfMode='list';}catch{}
const bookshelfPositions=new Map();
function bookshelfPositionKey(){const [page,query='']=location.hash.split('?'),p=new URLSearchParams(query);p.sort();return state.me?.id+'|'+page+(p.size?'?'+p:'');}
function bookshelfTone(id){let n=0;for(const c of String(id))n=(n*31+c.charCodeAt(0))>>>0;return ['ink','sage','plum','blue'][n%4];}
function bookshelfViews(shelf,list){return '<div data-bookshelf-view="shelf"'+(bookshelfMode==='shelf'?'':' hidden')+'>'+shelf+'</div><div data-bookshelf-view="list"'+(bookshelfMode==='list'?'':' hidden')+'>'+list+'</div>';}
function bookshelfToolbar(key){const hint=key==='sources'?'打开刊物，浏览档案、卷期与目次':'打开一期，查看文件与保留版本';return '<div class="bookshelf-toolbar"><div class="bookshelf-switch" role="group" aria-label="陈列方式">'+[['shelf','书架'],['list','列表']].map(([mode,label])=>'<button type="button" data-bookshelf-mode="'+mode+'" aria-pressed="'+(bookshelfMode===mode)+'">'+icon(mode==='shelf'?'library':'file')+label+'</button>').join('')+'</div><span class="bookshelf-hint">'+hint+'</span></div>';}
function bookshelfRoot(key,body,tools=''){return '<section class="bookshelf" data-bookshelf="'+key+'"><div class="bookshelf-tools">'+tools+bookshelfToolbar(key)+'</div>'+body+'</section>';}
function bookshelfPartitionButton(key,value,label,active=false,count=null){return '<button type="button" class="bookshelf-partition'+(active?' active':'')+'" data-bookshelf-select="'+key+'" data-value="'+esc(value)+'" aria-pressed="'+active+'"><span>'+esc(label)+'</span>'+(count===null?'':'<span class="bookshelf-partition-count">'+count+'</span>')+'</button>';}
function bookshelfDraftKey(){const p=new URLSearchParams(state.params);for(const key of [...p.keys()])if(key.startsWith('shelf_'))p.delete(key);return state.me?.id+'|'+state.page+'?'+p;}
function bookshelfSearch(){return '<form data-bookshelf-search class="bookshelf-global-search"><label class="sr-only" for="bookshelf-global-q">跨分区查找全部成果</label><input id="bookshelf-global-q" name="q" type="search" placeholder="跨分区查找刊名、主题或成果期次" value="'+esc(state.params.get('q')||'')+'"><button class="button primary" type="submit" aria-label="搜索全部分区">全区搜索</button>'+(state.params.get('q')?'<button type="button" class="button" data-bookshelf-select="query" data-value="">退出搜索</button>':'')+'</form>';}
function bookshelfGroup(title,books,subtitle=''){
  if(!books.length)return '';
  return '<section class="bookshelf-group"><header class="bookshelf-heading"><h2>'+esc(title)+'</h2>'+(subtitle?'<span>'+esc(subtitle)+'</span>':'')+'</header><div class="bookshelf-rail">'+books.join('')+'</div></section>';
}
function bookshelfBook({id,title,subtitle='',kind='',note='',href='',action='',business='',cover='',label=''}){
  const attrs=href?'href="'+esc(href)+'"':'type="button" data-action="'+action+'" data-id="'+esc(id)+'"'+(business?' data-business="'+business+'"':'');
  const tag=href?'a':'button';
  return '<article class="bookshelf-book bookshelf-'+bookshelfTone(id)+'" data-book-id="'+esc(id)+'"><'+tag+' class="bookshelf-open" '+attrs+(label?' aria-label="'+esc(label)+'"':'')+'><span class="bookshelf-cover"><span class="bookshelf-spine" aria-hidden="true"></span><span class="bookshelf-cover-type">'+esc(kind)+'</span>'+cover+'<strong class="bookshelf-cover-title">'+esc(title)+'</strong>'+(subtitle?'<span class="bookshelf-cover-subtitle">'+esc(subtitle)+'</span>':'')+'<span class="bookshelf-cover-label">'+(cover?'题名与封面依据见档案':'文字封面')+'</span></span><span class="bookshelf-caption"><span>打开查阅 · '+esc(note||'原件与保留版本')+'</span>'+icon('arrow')+'</span></'+tag+'></article>';
}
async function bookshelfCoverData(sid){
  try{return (await api('/api/journals/'+encodeURIComponent(sid))).profile.cover||{};}
  catch(error){if(error.status===401||error.status===403)throw error;return {};}
}
function bookshelfCoverHtml(cover){
  // Only the archive's authorized saved image is embedded. External clues and
  // non-image attachments remain in the archive, with its original permissions.
  if(!cover.file||!cover.url||!cover.evidence||cover.unavailable)return '';
  return '<img data-bookshelf-cover-image src="'+esc(cover.url)+'" alt="已登记期刊封面" loading="lazy"><span class="bookshelf-image-label">'+(cover.illustrative?'示意图，不代表本期':'已登记封面')+(cover.issue_id?' · 对应原刊卷期 '+esc(cover.issue_id):'')+'</span>';
}
async function bookshelfSources(items){
  const journals=items.filter(s=>s.kind==='journal').sort((a,b)=>(a.original_name||a.name).localeCompare(b.original_name||b.name,'en')),others=items.filter(s=>s.kind!=='journal');
  const bands=[['af','A–F'],['gl','G–L'],['mr','M–R'],['sz','S–Z'],['other','中文及其他题名']];
  const band=s=>{const text=(s.original_name||s.name||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/^[^\p{L}]+/u,'').toUpperCase();const c=text[0];return c>='A'&&c<='F'?'af':c>='G'&&c<='L'?'gl':c>='M'&&c<='R'?'mr':c>='S'&&c<='Z'?'sz':'other';};
  const groups=bands.map(([key,label])=>({key,label,items:journals.filter(s=>band(s)===key)})).filter(g=>g.items.length);
  const searching=!!state.params.get('q'),selected=groups.find(g=>g.key===state.params.get('shelf_letters'))||(searching?null:groups[0]),shown=selected?selected.items:searching?journals:[];
  const picker=groups.length?'<label class="bookshelf-mobile-picker">刊名分区<select data-bookshelf-picker="letters" aria-label="刊名分区">'+(searching?'<option value="">跨全部刊名分区</option>':'')+groups.map(g=>'<option value="'+g.key+'" '+(g===selected?'selected':'')+'>'+esc(g.label)+' · '+g.items.length+' 本</option>').join('')+'</select></label>':'';
  const nav=groups.length?picker+'<nav class="bookshelf-partitions" aria-label="按刊名索引分区">'+groups.map(g=>bookshelfPartitionButton('letters',g.key,g.label,g===selected,g.items.length)).join('')+'</nav><p class="bookshelf-context" role="status">'+(selected?(searching?'搜索内分区：':'当前分区：')+selected.label:'全局搜索 · 跨刊名分区')+' · '+shown.length+' / '+journals.length+' 本期刊</p><details class="bookshelf-index-note"><summary>分区依据与国别</summary><p>按已登记原名首字母分区；无拉丁字母原名的刊物单列。主办国别仍可在筛选中查找。</p></details>':'';
  const covers=await Promise.all(shown.map(s=>bookshelfCoverData(s.id)));
  const books=shown.map((s,i)=>bookshelfBook({id:s.id,title:s.name,subtitle:s.original_name&&s.original_name!==s.name?s.original_name:'',kind:'期刊档案',cover:bookshelfCoverHtml(covers[i]),note:countryText(s)+' · '+(s.issn?'ISSN '+s.issn:'ISSN 待补充'),href:sourceUrl(s.id)}));
  const otherHtml=others.length?'<section class="bookshelf-other"><h2>机构与其他来源</h2><div class="source-grid">'+others.map(sourceCard).join('')+'</div></section>':'';
  const shelf=(books.length?'<div class="bookshelf-rail" aria-label="'+esc(selected?.label||'搜索匹配的期刊')+'">'+books.join('')+'</div>':'')+otherHtml;
  return bookshelfRoot('sources',nav+bookshelfViews(shelf||empty('没有匹配的来源','','source'),'<div class="source-grid">'+[...shown,...others].map(sourceCard).join('')+'</div>'));
}
function bookshelfJournalGroups(items,context={},compact=false){
  const groups=new Map();
  for(const r of items){const key=(r.journal_id||r.journal_name)+'|'+r.year;if(!groups.has(key))groups.set(key,{name:r.journal_name,year:r.year,items:[]});groups.get(key).items.push(r);}
  return [...groups.values()].map(g=>{
    const books=g.items.map(r=>bookshelfBook({id:r.id,title:r.issue,subtitle:String(r.year||'年份待补充'),kind:'中心期刊成果',label:jrTitle(r),note:r.files.length+' 份并列文件'+(r.authors?' · '+r.authors:''),href:jrHref(new URLSearchParams({...Object.fromEntries(context instanceof URLSearchParams?context:new URLSearchParams(context)),id:r.id}))}));
    return compact?'<div class="bookshelf-rail">'+books.join('')+'</div>':bookshelfGroup(g.name+' · '+(g.year||'年份待补充'),books,'成果期次 · 依成果原标注');
  }).join('');
}
function bookshelfJournalViews(items,context={},compact=false){return bookshelfViews(bookshelfJournalGroups(items,context,compact)||'<p class="bookshelf-empty">尚无匹配成果。可清除筛选或保存一期成果。</p>','<div data-jr-list>'+items.map(r=>jrRow(r,context)).join('')+(items.length?'':'<p>尚无匹配成果。可清除筛选或保存一期成果。</p>')+'</div>');}
function bookshelfTopicViews(items){return bookshelfViews(bookshelfGroup('主题编译与旧期刊工作成果',items.map(w=>bookshelfBook({id:w.id,title:w.title,subtitle:w.coverage||'',kind:w.business==='topic'?'主题编译成果':'旧期刊工作成果',note:w.products.length+' 份成果 · '+(w.participant_names.join('、')||'署名未登记'),action:'workbench-select',business:w.business}))),'<div class="workbench-list">'+items.map(w=>workbenchWorkRow(w,false,true)).join('')+'</div>');}
function bookshelfJournalPartitions(items,context={},legacy=[]){
  const groups=new Map();for(const r of items){const key=r.journal_id?'id:'+r.journal_id:'name:'+r.journal_name;if(!groups.has(key))groups.set(key,{key,name:r.journal_name,items:[]});groups.get(key).items.push(r);}
  const selected=groups.get(state.params.get('shelf_journal')),old=state.params.get('shelf_journal')==='legacy';
  if(old&&legacy.length)return '<button class="button" data-bookshelf-select="journal" data-value="">← 返回刊物分区</button><p class="bookshelf-context" role="status">旧期刊工作成果 · '+legacy.length+' 项</p>'+bookshelfTopicViews(legacy);
  if(!selected)return '<div class="bookshelf-partition-heading"><h2>选择刊物</h2><p>先选刊物，再按成果年份查阅。共 '+items.length+' 期成果，分属 '+groups.size+' 种刊物。</p></div><nav class="bookshelf-catalogue" aria-label="刊物成果分区">'+[...groups.values()].map(g=>bookshelfPartitionButton('journal',g.key,g.name,false,g.items.length+' 期')).join('')+(legacy.length?bookshelfPartitionButton('journal','legacy','旧期刊工作成果',false,legacy.length+' 项'):'')+'</nav>'+(items.length||legacy.length?'':'<p class="bookshelf-empty">尚无匹配成果。可退出搜索或保存一期成果。</p>');
  const years=[...new Set(selected.items.map(r=>r.year))].sort((a,b)=>b-a),year=years.find(y=>String(y)===state.params.get('shelf_year'))??years[0],shown=selected.items.filter(r=>r.year===year);
  return '<button class="button" data-bookshelf-select="journal" data-value="" aria-label="返回刊物分区">更换刊物</button><details class="bookshelf-current-title"><summary>刊物：'+esc(selected.name)+'</summary><h2>'+esc(selected.name)+'</h2><p>本刊共 '+selected.items.length+' 期成果</p></details><p class="bookshelf-context" role="status">当前年份 '+esc(year||'未知')+' · '+shown.length+' 期成果</p><nav class="bookshelf-partitions" aria-label="成果年份">'+years.map(y=>bookshelfPartitionButton('year',String(y),String(y||'年份未知'),y===year,selected.items.filter(r=>r.year===y).length)).join('')+'</nav>'+bookshelfJournalViews(shown,context,true);
}
async function bookshelfCenter(data,filters,actions){
  const q=state.params.get('q')||'',journals=await api('/api/journal-results?'+new URLSearchParams(q?{q}:{}));
  const topics=data.items.filter(w=>w.business==='topic'),legacy=data.items.filter(w=>w.business==='journal'),section=state.params.get('shelf_section')==='topic'?'topic':'journal';
  const tabs='<nav class="bookshelf-sections" aria-label="成果分区">'+bookshelfPartitionButton('section','journal','期刊编译',section==='journal',journals.total)+bookshelfPartitionButton('section','topic','主题编译',section==='topic',topics.length)+'</nav>';
  const body=section==='topic'?'<section class="bookshelf-topics"><div class="bookshelf-partition-heading"><h2>主题编译成果</h2><p class="bookshelf-context" role="status">当前分区：主题编译 · '+topics.length+' 项工作成果</p></div><details class="bookshelf-work-filters"><summary>按分工、参与人与日期进一步查找</summary>'+filters+'</details>'+(topics.length?bookshelfTopicViews(topics):'<p class="bookshelf-empty">当前条件下没有主题成果。可退出搜索或调整筛选。</p>')+'</section>':bookshelfJournalPartitions(journals.items,{return:location.hash},legacy);
  return '<section class="workbench desk-results" data-work-discovery><section class="workbench-index"><div class="page-heading between wrap"><div><h1>中心成果</h1></div><div class="row wrap">'+jrLink('保存一期成果',{new:1,return:location.hash},'button primary')+actions+'</div></div>'+bookshelfRoot('center',tabs+(q?'<p class="bookshelf-search-state">全局搜索“'+esc(q)+'” · 期刊 '+journals.total+' 期 / 主题 '+topics.length+' 项</p>':'')+body,bookshelfSearch())+'<details class="workbench-legacy"><summary>独立成果与旧内容入口</summary><div class="row wrap">'+jrLink('期刊成果索引')+linkButton('独立成果与跨期译稿','work-legacy')+linkButton('查阅旧期刊工作','journal-home')+'</div></details></section></section>';
}
function bookshelfRemember(){
  const root=document.querySelector('[data-bookshelf]');if(!root||!state.me)return;
  const focus=document.activeElement?.closest('[data-book-id],[data-jr-row],[data-work-id],[data-object-id]');
  const forms=[...document.querySelectorAll('.source-search,[data-jr-search],[data-work-search],[data-bookshelf-search]')].map(form=>({selector:form.matches('.source-search')?'.source-search':form.matches('[data-jr-search]')?'[data-jr-search]':form.matches('[data-bookshelf-search]')?'[data-bookshelf-search]':'[data-work-search]',values:Object.fromEntries(new FormData(form)),outerOpen:form.closest('details')?.open,open:[...form.querySelectorAll('details')].map(el=>el.open)}));
  bookshelfPositions.set(bookshelfPositionKey(),{y:scrollY,focus:focus?.dataset.bookId||focus?.dataset.jrRow||focus?.dataset.workId||focus?.dataset.objectId,forms,mode:bookshelfMode});
}
function bookshelfAfterRender(){
  if(bookshelfAccount!==state.me?.id){bookshelfPositions.clear();bookshelfAccount=state.me?.id;}
  const back=document.querySelector('[data-jr-return]'),returnHash=state.params.get('return');
  if(back&&/^#(compilations|sources)(\?|$)/.test(returnHash||'')){back.href=returnHash;back.textContent=returnHash.startsWith('#sources')?'← 返回期刊档案':'← 返回中心成果';}
  const root=document.querySelector('[data-bookshelf]');
  if(bookshelfOpening){bookshelfOpening=false;bookshelfMotion?.shelfTransition?.(document.querySelector('[data-jr-detail],.source-page,.desk-workspace')||root);}
  if(!root)return;
  // Settle progressive filter wrappers before restoring their open state/scroll.
  if(typeof deskPrepare==='function')deskPrepare();
  const saved=bookshelfPositions.get(bookshelfPositionKey())||(bookshelfPartitionDraft?.key===bookshelfDraftKey()?{...bookshelfPartitionDraft,y:0}:null);
  if(saved){for(const entry of saved.forms){const form=document.querySelector(entry.selector);if(!form)continue;for(const [name,value] of Object.entries(entry.values))if(form.elements[name])form.elements[name].value=value;form.querySelectorAll('details').forEach((el,i)=>el.open=entry.open[i]);if(form.closest('details')&&entry.outerOpen!==undefined)form.closest('details').open=entry.outerOpen;}
    const selectors=bookshelfMode==='shelf'?'[data-book-id]':'[data-jr-row],[data-work-id],[data-object-id]';
    [...root.querySelectorAll(selectors)].find(el=>(el.dataset.bookId||el.dataset.jrRow||el.dataset.workId||el.dataset.objectId)===saved.focus)?.querySelector('a,button')?.focus({preventScroll:true});window.scrollTo(0,saved.y);
  }
}
function bookshelfCancel(){bookshelfMotion?.cancel();}
function bookshelfResetAccount(){bookshelfCancel();bookshelfPositions.clear();bookshelfAccount=null;bookshelfOpening=false;bookshelfPartitionDraft=null;}
document.addEventListener('click',event=>{
  const partition=event.target.closest('[data-bookshelf-select]');
  if(partition){event.preventDefault();bookshelfRemember();const saved=bookshelfPositions.get(bookshelfPositionKey());bookshelfPartitionDraft={key:bookshelfDraftKey(),forms:saved?.forms||[]};const p=new URLSearchParams(state.params),key=partition.dataset.bookshelfSelect,value=partition.dataset.value;
    if(key==='section'){p.set('shelf_section',value);p.delete('shelf_journal');p.delete('shelf_year');}
    else if(key==='journal'){value?p.set('shelf_journal',value):p.delete('shelf_journal');p.delete('shelf_year');}
    else if(key==='year')p.set('shelf_year',value);
    else if(key==='letters')p.set('shelf_letters',value);
    else if(key==='query'){p.delete('q');for(const k of [...p.keys()])if(k.startsWith('shelf_'))p.delete(k);bookshelfPartitionDraft=null;}
    go(state.page,p);return;
  }
  const button=event.target.closest('[data-bookshelf-mode]');
  if(button){event.preventDefault();bookshelfCancel();const y=scrollY;bookshelfMode=button.dataset.bookshelfMode;
    try{localStorage.setItem(bookshelfPreference,bookshelfMode);}catch{}
    document.querySelectorAll('[data-bookshelf-view]').forEach(el=>el.hidden=el.dataset.bookshelfView!==bookshelfMode);
    document.querySelectorAll('[data-bookshelf-mode]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.bookshelfMode===bookshelfMode)));
    window.scrollTo(0,y);bookshelfMotion?.shelfTransition?.(document.querySelector('[data-bookshelf-view]:not([hidden])'));return;
  }
  if(event.target.closest('[data-bookshelf] a,[data-bookshelf] [data-action],.desk-primary [data-action]'))bookshelfRemember();
  if(event.target.closest('.bookshelf-open'))bookshelfOpening=true;
},true);
document.addEventListener('submit',event=>{const form=event.target.closest('[data-bookshelf-search]');if(!form)return;event.preventDefault();const p=new URLSearchParams(state.params),q=String(new FormData(form).get('q')||'').trim();for(const key of [...p.keys()])if(key.startsWith('shelf_'))p.delete(key);q?p.set('q',q):p.delete('q');bookshelfPartitionDraft=null;go(state.page,p);});
document.addEventListener('error',event=>{if(event.target.matches?.('[data-bookshelf-cover-image]')){const cover=event.target.closest('.bookshelf-cover');event.target.remove();cover.querySelector('.bookshelf-image-label')?.remove();cover.querySelector('.bookshelf-cover-label').textContent='文字封面 · 图片暂不可用';}},true);
document.addEventListener('change',event=>{const picker=event.target.closest('[data-bookshelf-picker]');if(!picker)return;const p=new URLSearchParams(state.params);picker.value?p.set('shelf_'+picker.dataset.bookshelfPicker,picker.value):p.delete('shelf_'+picker.dataset.bookshelfPicker);go(state.page,p);});
window.addEventListener('hashchange',bookshelfCancel);
document.addEventListener('visibilitychange',()=>{if(document.hidden)bookshelfCancel();});
matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change',bookshelfCancel);
import(clientAsset('/static/vendor/visual/desk-motion.js')).then(module=>{bookshelfMotion=module;}).catch(()=>{});
