'use strict';

// Reading and continuation views share the existing records, drafts and permission checks.
function uxSafeExternal(value) {
  if(typeof value!=='string'||!value||/[\s\u0000-\u001f\u007f\\]/u.test(value))return '';
  try { const url=new URL(value),authority=value.match(/^[a-z]+:\/\/([^/?#]*)/i)?.[1]||'';return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password&&!authority.includes('@')?url.href:''; } catch { return ''; }
}
function uxAccess(record) {
  const access=record.reading_access||{},official=access.official_files??record.raw_json?.imported_attachments??[];
  const platform=access.platform_files??record.attachments??[];
  const unique=new Set(),officialFiles=[];
  for(const file of Array.isArray(official)?official:[]){
    const url=uxSafeExternal(file.url);if(!url||unique.has(url))continue;unique.add(url);
    officialFiles.push({url,label:file.label||file.name||'官方文件链接'});
  }
  const platformFiles=(Array.isArray(platform)?platform:[]).filter(file=>typeof file.id==='string'&&file.id).map(file=>({id:file.id,name:file.name||'平台附件',url:'/api/attachments/'+encodeURIComponent(file.id)}));
  return {original:uxSafeExternal(access.original_url??record.url),official:officialFiles,platform:platformFiles,hasBody:typeof access.has_body==='boolean'?access.has_body:!!record.body_html,unknownPlatform:!record.reading_access&&!!record.has_attachment&&!platformFiles.length};
}
function uxExternal(url,label,cls='button tiny') {
  const safe=uxSafeExternal(url);return safe?'<a class="'+cls+'" href="'+esc(safe)+'" target="_blank" rel="noopener noreferrer">'+icon('link')+esc(label)+'</a>':'';
}
function uxReadingActions(record,compact=false) {
  const access=uxAccess(record),actions=[];
  const add=(url,label,platform=false)=>actions.push({url,label,platform});
  if(access.platform[0])add(access.platform[0].url,compact?'平台附件':'打开平台附件',true);
  if(access.official[0])add(access.official[0].url,compact?'官方文件链接':'打开官方文件链接');
  if(access.original&&!access.official.some(file=>file.url===access.original))add(access.original,'原文网页');
  let html=actions.map((a,index)=>{
    const cls=index===0?'button tiny ux-read-primary':'ux-read-link';
    return a.platform?'<a class="'+cls+'" href="'+esc(a.url)+'" target="_blank" rel="noopener noreferrer">'+icon('file')+esc(a.label)+'</a>':uxExternal(a.url,a.label,cls);
  }).join('');
  if(access.hasBody)html+='<button type="button" class="'+(!actions.length?'button tiny ux-read-primary':'ux-read-link')+'" data-action="ux-read-body" data-id="'+esc(record.id)+'">'+icon('book')+'阅读正文</button>';
  if(access.unknownPlatform)html+=linkButton('查看平台附件','ux-files',record.id,'ux-read-link');
  return html;
}
function uxRecordCard(record) {
  const metadata=[recordAuthorLabel(record),record.published_on,languageLabel(record.language)].filter(Boolean),sources=recordSourceLabels(record),text=record.search_snippet||record.abstract||record.coverage;
  const reading=uxReadingActions(record,true);
  return '<article class="record-card ux-record-card"><div class="record-body"><div class="ux-card-top"><div class="row wrap">'+typeBadge(record.kind)+badge(record.status)+(record.visibility==='restricted'?'<span class="badge neutral">'+icon('lock')+'限授权成员</span>':'')+'</div><div class="card-actions"><button type="button" class="icon-button '+(record.favorite?'saved':'')+'" data-action="favorite" data-id="'+esc(record.id)+'" data-saved="'+!!record.favorite+'" aria-pressed="'+!!record.favorite+'" aria-label="'+(record.favorite?'取消收藏':'收藏')+'">'+icon('star')+'</button><button type="button" class="icon-button" data-action="add-to-collection" data-id="'+esc(record.id)+'" aria-label="加入专题">'+icon('folder')+'</button></div></div>'
    +'<h2 class="record-title">'+linkButton(esc(record.title),'detail',record.id,'title-button')+'</h2><div class="record-meta">'+metadata.map(value=>'<span>'+esc(value)+'</span>').join('')+'</div>'
    +(text?'<p class="'+(record.search_snippet?'search-snippet':'abstract')+'">'+esc(text)+'</p>':'')
    +(typeof attachmentMatchSection==='function'?attachmentMatchSection(record):'')
    +(sources.length?'<div class="record-meta ux-card-sources">'+sources.map(value=>'<span>'+esc(value)+'</span>').join('')+'</div>':'')
    +'<div class="ux-reading-actions">'+(reading||(record.reading_access?'<span class="ux-record-state">题录记录 · 暂无正文或可用原文链接</span>':linkButton('查看详情与阅读入口','detail',record.id,'ux-read-link')))+'</div>'
    +(state.params.has('collection')?linkButton('移出当前专题','remove-from-collection',record.id,'ux-read-link'):'')+'</div></article>';
}
function uxLocalDrafts() {
  const result=[],prefix=draftPrefix+encodeURIComponent(state.me.id)+':';
  try{
    for(let i=0;i<localStorage.length;i++){const key=localStorage.key(i);if(!key.startsWith(prefix))continue;try{const draft=JSON.parse(localStorage.getItem(key));if(draft?.user_id===state.me.id)result.push({key,...draft});}catch{}}
    return {items:result.sort((a,b)=>String(b.updated_at).localeCompare(String(a.updated_at))),available:true};
  }catch{return {items:[],available:false};}
}
function uxWorkRow(record) {
  return '<article class="ux-work-item"><h3>'+linkButton(esc(record.title),'detail',record.id,'title-button')+'</h3><p class="ux-time">'+esc(kinds[record.kind]||record.kind)+(record.updated_at?' · 更新于 '+dateTime(record.updated_at):'')+'</p>'+(record.can_edit?linkButton('继续编辑','edit-record',record.id,'ux-read-link'):'')+'</article>';
}
async function uxDashboard() {
  const data=await api('/api/dashboard'),drafts=uxLocalDrafts();
  const topics=state.collections.slice().sort((a,b)=>String(b.updated_at||b.created_at||'').localeCompare(String(a.updated_at||a.created_at||''))).slice(0,3);
  const work=Array.isArray(data.my_work)?data.my_work:[];
  const draftRows=drafts.items.slice(0,3).map(draft=>'<article class="ux-work-item"><h3>'+esc(draft.title)+'</h3><p class="ux-time">'+esc(draftTypeLabel(draft))+' · 保存于 '+dateTime(draft.updated_at)+(draft.file?' · 含附件':'')+'</p><button class="ux-read-link" type="button" data-action="open-draft" data-key="'+esc(draft.key)+'">继续草稿'+icon('arrow')+'</button></article>').join('');
  return '<div class="ux-dashboard"><section class="panel workspace-search" aria-label="资料检索"><h1>查找研究资料</h1><form data-form="hero-search" class="hero-search"><label class="sr-only" for="work-search">搜索资料</label>'+icon('search')+'<input id="work-search" name="q" placeholder="搜索题名、作者、关键词或正文"><button class="button primary" type="submit">搜索</button></form></section>'
    +'<section class="ux-continue"><div class="between wrap ux-section-head"><h2>继续研究</h2>'+linkButton(icon('plus')+'新建内容','new-record','','button tiny')+'</div><div class="ux-work-grid">'
    +'<section class="panel"><div class="panel-head"><h3>本机草稿</h3>'+linkButton('全部草稿','nav','drafts','ux-read-link')+'</div><div class="ux-work-items">'+(draftRows||'<p class="ux-empty">'+(drafts.available?'暂无未提交草稿。':'暂时无法读取本机草稿。')+'</p>')+'</div></section>'
    +'<section class="panel"><div class="panel-head"><h3>近期专题</h3>'+linkButton('全部专题','nav','collections','ux-read-link')+'</div><div class="ux-work-items">'+(topics.map(topic=>'<article class="ux-work-item"><h3>'+linkButton(esc(topic.name),'open-collection',topic.id,'title-button')+'</h3><p class="ux-time">'+topic.count+' 份资料'+(topic.updated_at?' · 更新于 '+dateTime(topic.updated_at):topic.created_at?' · 创建于 '+dateTime(topic.created_at):'')+'</p></article>').join('')||'<div class="ux-empty">'+linkButton('新建研究专题','new-collection','','ux-read-link')+'</div>')+'</div></section>'
    +'<section class="panel"><div class="panel-head"><h3>本人近期成果</h3></div><div class="ux-work-items">'+(work.map(uxWorkRow).join('')||'<p class="ux-empty">'+(Array.isArray(data.my_work)?'暂无本人负责的成果。':'暂时无法读取本人成果。')+'</p>')+'</div></section></div></section>'
    +'<section class="panel ux-latest"><div class="panel-head"><h2>最近入库</h2>'+linkButton('资料库'+icon('arrow'),'nav','library','ux-read-link')+'</div>'+(data.latest.map(recentRow).join('')||'<div class="ux-empty">暂无入库内容。</div>')+'</section>'
    +'<div class="ux-dashboard-summary" aria-label="资料概况"><span>资料 '+data.stats.records+'</span><span>来源 '+data.stats.source_entries+'</span><span>收藏 '+data.stats.favorites+'</span></div></div>';
}
async function uxLibraryPage(data=null) {
  const root=document.createElement('div');root.innerHTML=await baseLibraryPage(data);
  const labels={q:'关键词',kind:'类型',source:'来源',source_group:'来源类型',source_country:'来源国别',source_international:'国际办刊定位',language:'语言',status:'核对',country:'研究对象',from:'起始日期',to:'截止日期',collection:'专题'};
  const entries=[...state.params].filter(([key,value])=>labels[key]&&value);
  if(entries.length){
    const bar=document.createElement('section');bar.className='ux-filter-chips';bar.setAttribute('aria-label','已应用的筛选');
    bar.innerHTML='<span>已筛选</span>'+entries.map(([key,value])=>{
      const name=key==='source_group'?sourceGroups[value]:key==='source_country'?(value==='__pending__'?'待确认':value):key==='source_international'?internationalLabels[value]:key==='source'?sourceById(value)?.name:key==='collection'?state.collections.find(c=>c.id===value)?.name:key==='kind'?kinds[value]:key==='language'?languageLabel(value):key==='status'?{pending:'待核对',verified:'已核对'}[value]:value;
      return '<button class="ux-filter-chip" type="button" data-action="ux-clear-filter" data-key="'+esc(key)+'" aria-label="清除'+labels[key]+'：'+esc(name||value)+'">'+labels[key]+'：'+esc(name||value)+icon('close')+'</button>';
    }).join('')+(entries.some(([key])=>key!=='collection')?'<button class="ux-read-link" type="button" data-action="ux-clear-filters">清除筛选</button>':'');
    root.querySelector('.results-head').before(bar);
  }
  const toolbar=root.querySelector('.toolbar');
  const filters=root.querySelector('[data-form="filters"]');
  if(filters){
    const details=document.createElement('details');details.className='ux-filters';
    details.innerHTML='<summary>筛选条件</summary>';
    filters.before(details);details.append(filters);
  }
  if(toolbar){
    const secondary=[...toolbar.children].filter(el=>el.matches('a,[data-action="duplicates"],[data-action="export-content"]'));
    if(secondary.length){const details=document.createElement('details');details.className='ux-list-tools';details.innerHTML='<summary>整理与导出</summary><div class="row wrap"></div>';secondary.forEach(el=>details.lastElementChild.append(el));toolbar.append(details);}
  }
  const filterDisclosure=root.querySelector('.ux-filters');
  if(filterDisclosure){const options=document.createElement('div');options.className='ux-query-options';filterDisclosure.before(options);options.append(filterDisclosure);const tools=root.querySelector('.ux-list-tools');if(tools)options.append(tools);}
  root.className='ux-library';return root.outerHTML;
}
async function uxRefreshBackground() {
  const hash=location.hash,loadId=++state.loadId;
  let html;
  if(state.page==='dashboard')html=await dashboard();
  else if(state.page==='sources')html=await sourcesPage();
  else if(state.page==='people')html=await peoplePage();
  else if(state.page==='collections')html=await collectionsPage();
  else if(state.page==='system')html=await systemPage();
  else if(state.page==='drafts')html=await draftsPage();
  else html=await libraryPage();
  if(state.me&&location.hash===hash&&loadId===state.loadId){document.querySelector('#content').innerHTML=html;if(typeof libraryAfterRender==='function')libraryAfterRender();}
}
function uxCopyLabel(record) {
  return ['compilation','research_report'].includes(record.kind)?'复制引用清单':record.kind==='research_note'?(record.evidence_record_id?'复制摘录与出处':'复制笔记与出处'):'复制出处';
}
function uxFiles(record) {
  const access=uxAccess(record);
  if(access.platform.length<=1&&access.official.length<=1)return '';
  return '<section class="detail-section" id="ux-files"><h3>阅读文件</h3>'+(access.platform.length?'<h4>平台附件</h4>'+access.platform.map(file=>'<a class="detail-link" href="'+esc(file.url)+'" target="_blank" rel="noopener noreferrer">'+icon('file')+esc(file.name)+'</a>').join(''):'')
    +(access.official.length?'<h4>外部官方文件链接</h4>'+access.official.map(file=>uxExternal(file.url,file.label,'detail-link')).join(''):'')+'</section>';
}
function uxReadingNotes(record) {
  const notes=(record.cited_by||[]).filter(note=>note.kind==='research_note'&&!note.evidence_record_id),original=!isResearchContent(record.kind);
  if(!original)return '';
  return '<section class="detail-section ux-notes-section" data-reading-notes><div class="between wrap"><h3>阅读说明</h3>'+linkButton(icon('edit')+'写阅读说明','ux-reading-note',record.id,'button tiny')+'</div>'
    +(notes.map(note=>'<article class="ux-note-card" data-reading-note="'+esc(note.id)+'"><div class="between"><h4>'+linkButton(esc(note.title),'detail',note.id,'title-button')+'</h4><button class="ux-read-link" type="button" data-action="ux-expand-note" data-id="'+esc(note.id)+'" aria-expanded="false" aria-controls="note-body-'+esc(note.id)+'">展开说明</button></div><p class="ux-time">'+esc(note.authors||note.author_name||state.users.find(u=>u.id===note.author_id)?.name||'负责作者待确认')+(note.updated_at?' · 更新于 '+dateTime(note.updated_at):'')+'</p><div id="note-body-'+esc(note.id)+'" data-note-body hidden></div></article>').join('')||'<p class="ux-empty-line">记录这份资料的用途、局限或值得继续的问题。</p>')+'</section>';
}
async function uxReadRecord(record,target=null) {
  const bylines=typeof bylineSection==='function'?await bylineSection(record):'';
  const identities=bylines+await articleAffiliationSection(record);
  const abstractSection=record.abstract?'<section class="detail-section ux-abstract"><h3>摘要</h3><p class="prose">'+esc(record.abstract)+'</p></section>':'';
  const bodySection=record.body_html?'<section class="detail-section ux-main-body" id="ux-body"><h3>正文</h3><div class="rich-prose">'+readRich(record.body_html)+'</div></section>':'';
  const research=isResearchContent(record.kind),access=uxAccess(record),references=record.linked_records||[],hasEvidence=!!record.evidence_record_id||!!record.evidence_citations?.length;
  const meta=[record.authors,record.published_on,languageLabel(record.language)].filter(Boolean),sources=recordSourceLabels(record).filter(label=>!label.startsWith('关联来源：'));
  const maintenance=(record.can_edit?linkButton('编辑内容','edit-record',record.id)+linkButton('修改历史','history','record:'+record.id):'')+linkButton('加入专题','add-to-collection',record.id)+linkButton(record.favorite?'取消收藏':'收藏资料','favorite',record.id)
    +(state.me.role==='admin'&&record.status!=='verified'?linkButton('标记已核对','verify','record:'+record.id):'');
  const content='<article class="ux-reading-article"><div class="row wrap ux-reading-labels">'+typeBadge(record.kind)+badge(record.status)+'<span class="badge neutral">'+(record.visibility==='shared'?'中心共享':'限授权成员')+'</span><span class="ux-version">版本 '+record.version+'</span></div>'
    +'<h2 class="detail-title">'+esc(record.title)+'</h2>'+(record.original_title&&record.original_title!==record.title?'<p class="original-title">'+esc(record.original_title)+'</p>':'')
    +'<div class="ux-bibliography">'+(meta.length?'<p>'+meta.map(esc).join(' · ')+'</p>':'')+(sources.length?'<p>'+sources.map(esc).join(' · ')+'</p>':'')+(record.coverage?'<p>'+esc(record.coverage)+'</p>':'')+((record.related_source_ids||[]).length?'<p>关联来源：'+record.related_source_ids.map(sourceName).join(' / ')+'</p>':'')+'</div>'
    +'<div class="ux-reading-actions ux-reading-toolbar">'+uxReadingActions(record)+'<button class="button tiny" type="button" data-action="ux-copy" data-id="'+esc(record.id)+'">'+uxCopyLabel(record)+'</button></div><div data-copy-region></div>'
    +(target?'':identities)
    +(record.kind==='research_note'?authorPanel(record):authorControlledKinds.has(record.kind)&&!record.author_confirmed?authorPanel(record):authorControlledKinds.has(record.kind)?'<p class="ux-author">负责作者：'+esc(record.author_name||recordAuthorLabel(record))+' · 已由本人确认</p>':'<p class="ux-author">当前有权读取的有效成员共同编辑</p>')
    +(target?bodySection+abstractSection:abstractSection+bodySection)
    +(typeof translationPanel==='function'?translationPanel(record):'')
    +(!record.body_html&&!record.abstract&&!uxReadingActions(record)?'<p class="ux-empty-line">此条目目前仅保存题录。</p>':'')+uxFiles(record)
    +(target&&identities?'<details class="ux-identities"><summary>作品署名与文章单位</summary>'+identities+'</details>':'')
    +(record.original_catalogue?'<section class="detail-section"><h3>原目录 / 原文出处</h3><p class="prose">'+esc(record.original_catalogue)+'</p></section>':'')
    +(typeof attachmentIndexSection==='function'?attachmentIndexSection(record):'')
    +uxReadingNotes(record)
    +noteSubjectDetail(record)
    +(hasEvidence&&typeof evidenceDetail==='function'?evidenceDetail(record):'')
    +(!research&&typeof evidenceDetail==='function'?evidenceDetail(record):'')
    +(research&&references.length?'<section class="detail-section"><h3>'+(hasEvidence?'其他关联资料':'关联原始资料')+'</h3>'+references.map(r=>linkButton(esc(r.title),'detail',r.id,'detail-link')).join('')+'</section>':'')
    +(record.unresolved_refs?'<section class="detail-section"><h3>其他出处说明</h3><p class="prose">'+esc(record.unresolved_refs)+'</p></section>':'')
    +((record.cited_by||[]).some(r=>r.kind!=='research_note')?'<section class="detail-section"><h3>引用此资料的成果</h3>'+record.cited_by.filter(r=>r.kind!=='research_note').map(r=>linkButton(esc(r.title),'detail',r.id,'detail-link')).join('')+'</section>':'')
    +'<details class="ux-metadata"><summary>题录与维护信息</summary><dl class="detail-grid section-gap">'+detailPair('稳定编号',esc(record.id))+detailPair('上传者',esc(record.owner_name))+detailPair('最近修改',record.last_modifier?esc(record.last_modifier.name)+' · '+dateTime(record.last_modifier.created_at):dateTime(record.updated_at))+detailPair('DOI',esc(record.doi))+detailPair('关键词',esc(record.keywords))+detailPair('研究对象',esc(record.countries))+detailPair('发布机构',sourceName(record.source_id))+detailPair('所属刊物',sourceName(record.serial_id)||esc(record.publication_title))+'</dl>'+(record.aliases?'<p class="prose">其他题名：'+esc(record.aliases)+'</p>':'')+(record.upstream_status?'<p class="prose">上游核查信息：'+esc(record.upstream_status)+'</p>':'')+'</details>'
    +(typeof intakeEvidenceHtml==='function'?intakeEvidenceHtml(record.intake_evidence):'')
    +'<details class="ux-maintenance"><summary>整理、编辑与核对</summary><div class="detail-actions">'+maintenance+'</div></details>'
    +(!hasEvidence&&research&&typeof archivedLinks==='function'?archivedLinks('record',record):'')+'</article>';
  if(target)target.innerHTML=content;else modal(kinds[record.kind]||'阅读资料',content);
  const body=target||document.querySelector('.drawer-body');body.classList.add('ux-reader');body.closest('.drawer')?.classList.add('ux-reading-drawer');
  const favorite=body.querySelector('[data-action=favorite]');if(favorite)favorite.dataset.saved=!!record.favorite;
  for(const button of body.querySelectorAll('.icon-button[data-action=add-to-collection]'))button.setAttribute('aria-label','加入专题');
  state.detail={type:'record',data:record};
  document.dispatchEvent(new CustomEvent('library:reader-rendered',{detail:{record,root:body}}));
}
async function uxReadingNote(original) {
  await workflowRecordForm('','research_note','reading:'+original.id,'','',{title:'阅读说明｜'+original.title.slice(0,60),linked_records:[original]});
}
function uxPrepareReadingForm(form,sourceId) {
  if(!sourceId.startsWith('reading:'))return;
  form.dataset.readingOriginalId=sourceId.slice(8);form.dataset.readingNote='true';form.classList.add('ux-reading-form');
  form.elements.kind.disabled=true;form.elements.kind.closest('.field').hidden=true;form.querySelector('#reference-section').hidden=true;
  document.querySelector('#drawer-title').textContent='写阅读说明';
  form.querySelector('[data-evidence-editor]')?.setAttribute('hidden','');form.querySelector('[data-evidence-picker]')?.setAttribute('hidden','');
  const context=document.createElement('section');context.className='ux-note-context wide';context.innerHTML='<h3>阅读资料</h3><div data-reading-context></div>';
  form.querySelector('[data-rich-field=body_html]').before(context);
  form.querySelector('[data-rich-field=body_html] .field-label').textContent='阅读说明';
  form.querySelector('[data-rich-input]').setAttribute('aria-describedby','reading-note-hint');
  const hint=document.createElement('p');hint.className='form-help';hint.id='reading-note-hint';hint.textContent='可以记录用途、局限或下一步问题。';context.append(hint);
  const options=document.createElement('details');options.className='wide ux-note-options';options.innerHTML='<summary>署名、授权与附件</summary><div class="form-grid section-gap"></div>';
  const optional=[form.elements.authors.closest('.field'),form.querySelector('[data-author-new]'),form.elements.original_catalogue.closest('.field'),form.querySelector('.source-picker'),form.querySelector('.attachment-editor'),form.querySelector('[data-access-fields]')];
  optional.filter(Boolean).forEach(field=>options.lastElementChild.append(field));form.querySelector('.form-grid').append(options);
  uxRefreshReadingContext(form);
}
function uxRefreshReadingContext(form) {
  const root=form.querySelector('[data-reading-context]');if(root)root.innerHTML=state.links.map(r=>'<p>'+esc(r.title)+'</p><p class="ux-time">'+[r.authors,r.published_on].filter(Boolean).map(esc).join(' · ')+'</p>').join('');
}
async function uxCopyRecord(button) {
  const account=state.me?.id;button.disabled=true;
  document.querySelector('[data-copy-region]')?.replaceChildren();
  try{
    let result;try{result=await api('/api/records/'+encodeURIComponent(button.dataset.id)+'/copy-text');}catch{throw new Error('暂时无法准备复制内容，请稍后重试。');}
    if(state.me?.id!==account)return;
    const text=typeof result.text==='string'?result.text:'';
    if(!text.trim()||(result.mode==='references'&&text.trim()==='暂无可复制的引用。')){toast(text.trim()||result.notice||'暂无可复制的内容。');return;}
    try{if(!navigator.clipboard?.writeText)throw new Error('unavailable');await navigator.clipboard.writeText(text);toast(result.notice?'已复制。'+result.notice:'已复制');}
    catch{
      const region=document.querySelector('[data-copy-region]');if(!region)return;
      region.innerHTML='<section class="ux-copy-panel"><label for="manual-copy-text">选择下方文字后复制</label>'+(result.notice?'<p class="form-help">'+esc(result.notice)+'</p>':'')+'<textarea id="manual-copy-text" readonly rows="9"></textarea><div class="row wrap"><button type="button" class="button tiny" data-action="ux-select-copy">选择全部</button><button type="button" class="ux-read-link" data-action="ux-close-copy">收起</button></div></section>';
      const textarea=region.querySelector('textarea');textarea.value=text;textarea.focus();textarea.select();
    }
  }catch(error){toast(error.message);}finally{if(button.isConnected)button.disabled=false;}
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action]');if(!button)return;
  const action=button.dataset.action;if(!action.startsWith('ux-'))return;
  try{
    if(action==='ux-clear-filter'){const p=parameters({[button.dataset.key]:'',...(button.dataset.key==='source'?{source_section:''}:{}),page:''});go(state.page,p);}
    else if(action==='ux-clear-filters')go(state.page,state.params.has('collection')?{collection:state.params.get('collection')}:{});
    else if(action==='ux-read-body'||action==='ux-files'){
      if(state.detail?.type!=='record'||state.detail.data.id!==button.dataset.id||!document.querySelector('.ux-reader'))await openRecord(button.dataset.id);
      const section=document.querySelector(action==='ux-files'?'#ux-files':'#ux-body');if(section){section.tabIndex=-1;section.focus({preventScroll:true});section.scrollIntoView({block:'start'});}
    }
    else if(action==='ux-reading-note'){const record=state.detail?.data;if(record?.id===button.dataset.id)await uxReadingNote(record);}
    else if(action==='ux-expand-note'){
      const card=button.closest('[data-reading-note]'),region=card.querySelector('[data-note-body]');
      if(button.getAttribute('aria-expanded')==='true'){region.hidden=true;button.setAttribute('aria-expanded','false');button.textContent='展开说明';}
      else{button.disabled=true;if(!region.dataset.loaded){const note=await api('/api/records/'+encodeURIComponent(button.dataset.id));if(!card.isConnected)return;region.innerHTML='<div class="rich-prose">'+readRich(note.body_html)+'</div>'+(!note.body_html?'<p class="ux-empty-line">这份阅读说明尚无正文。</p>':'');region.dataset.loaded='true';}region.hidden=false;button.setAttribute('aria-expanded','true');button.textContent='收起说明';}
    }
    else if(action==='ux-copy')await uxCopyRecord(button);
    else if(action==='ux-select-copy'){const textarea=document.querySelector('#manual-copy-text');textarea?.focus();textarea?.select();}
    else if(action==='ux-close-copy'){document.querySelector('[data-copy-region]')?.replaceChildren();document.querySelector('[data-action=ux-copy]')?.focus();}
  }catch(error){toast(error.message);}finally{if(button.isConnected)button.disabled=false;}
});
