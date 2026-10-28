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
  return '<article class="record-card ux-record-card"><div class="record-body"><div class="ux-card-top"><div class="row wrap">'+typeBadge(record.kind)+badge(record.status)+(record.visibility==='restricted'?'<span class="badge neutral">'+icon('lock')+'限授权成员</span>':'')+'</div><div class="card-actions"><button type="button" class="icon-button '+(record.favorite?'saved':'')+'" data-action="favorite" data-id="'+esc(record.id)+'" data-saved="'+!!record.favorite+'" aria-pressed="'+!!record.favorite+'" aria-label="'+(record.favorite?'取消收藏':'收藏')+'">'+icon('star')+'</button><button type="button" class="icon-button" data-action="add-to-collection" data-id="'+esc(record.id)+'" aria-label="加入资料夹">'+icon('folder')+'</button></div></div>'
    +'<h2 class="record-title">'+linkButton(esc(record.display_title||record.title),'detail',record.id,'title-button')+'</h2><div class="record-meta">'+metadata.map(value=>'<span>'+esc(value)+'</span>').join('')+'</div>'
    +(text?'<p class="'+(record.search_snippet?'search-snippet':'abstract')+'">'+esc(text)+'</p>':'')
    +(typeof attachmentMatchSection==='function'?attachmentMatchSection(record):'')
    +(sources.length?'<div class="record-meta ux-card-sources">'+sources.map(value=>'<span>'+esc(value)+'</span>').join('')+'</div>':'')
    +'<div class="ux-reading-actions">'+(reading||(record.reading_access?'<span class="ux-record-state">题录记录 · 暂无正文或可用原文链接</span>':linkButton('查看详情与阅读入口','detail',record.id,'ux-read-link')))+'</div>'
    +(state.params.has('collection')?linkButton('移出当前资料夹','remove-from-collection',record.id,'ux-read-link'):'')+'</div></article>';
}
async function uxLibraryPage(data=null) {
  return readingLibraryHTML(data||await api('/api/records?'+recordQuery()));
}
async function uxRefreshBackground() {
  const hash=location.hash,loadId=++state.loadId;
  let html;
  if(state.page==='dashboard')html=await dashboard();
  else if(state.page==='sources')html=readingArchiveTabs()+await sourcesPage();
  else if(state.page==='people')html=readingArchiveTabs()+await peoplePage();
  else if(state.page==='personal')html=await readingPersonalPage();
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
  if(!original||!notes.length)return '';
  return '<section class="detail-section ux-notes-section" data-reading-notes><div class="between wrap"><h3>阅读说明</h3>'+'</div>'
    +(notes.map(note=>'<article class="ux-note-card" data-reading-note="'+esc(note.id)+'"><div class="between"><h4>'+linkButton(esc(note.title),'detail',note.id,'title-button')+'</h4><button class="ux-read-link" type="button" data-action="ux-expand-note" data-id="'+esc(note.id)+'" aria-expanded="false" aria-controls="note-body-'+esc(note.id)+'">展开说明</button></div><p class="ux-time">'+esc(note.authors||note.author_name||state.users.find(u=>u.id===note.author_id)?.name||'负责作者待确认')+(note.updated_at?' · 更新于 '+dateTime(note.updated_at):'')+'</p><div id="note-body-'+esc(note.id)+'" data-note-body hidden></div></article>').join(''))+'</section>';
}
async function uxReadRecord(record,target=null) {
  const bylines=typeof bylineSection==='function'?await bylineSection(record):'';
  const identities=bylines+await articleAffiliationSection(record);
  const abstractSection=readingAbstract(record);
  const bodySection=record.body_html?'<section class="detail-section ux-main-body" id="ux-body"><h3>正文</h3><div class="rich-prose">'+readRich(record.body_html)+'</div></section>':'';
  const research=isResearchContent(record.kind),access=uxAccess(record),references=record.linked_records||[],hasEvidence=!!record.evidence_record_id||!!record.evidence_citations?.length;
  const meta=[record.authors,record.published_on,languageLabel(record.language)].filter(Boolean),sources=recordSourceLabels(record).filter(label=>!label.startsWith('关联来源：'));
  const maintenance=(record.can_edit?linkButton('编辑内容','edit-record',record.id)+linkButton('修改历史','history','record:'+record.id):'')+linkButton('加入资料夹','add-to-collection',record.id)+linkButton(record.favorite?'取消收藏':'收藏资料','favorite',record.id)
    +(state.me.role==='admin'?linkButton('标记已核对','verify','record:'+record.id):'');
  const content='<article class="ux-reading-article"><div class="row wrap ux-reading-labels">'+typeBadge(record.kind)+badge(record.status)+'<span class="badge neutral">'+(record.visibility==='shared'?'中心共享':'限授权成员')+'</span><span class="ux-version">版本 '+record.version+'</span></div>'
    +'<h2 class="detail-title" data-reading-title>'+esc(record.display_title||record.title)+'</h2>'+(record.original_title&&record.original_title!==record.title?'<p class="original-title">'+esc(record.original_title)+'</p>':'')
    +'<div class="ux-bibliography">'+(meta.length?'<p>'+meta.map(esc).join(' · ')+'</p>':'')+(sources.length?'<p>'+sources.map(esc).join(' · ')+'</p>':'')+(record.coverage?'<p>'+esc(record.coverage)+'</p>':'')+((record.related_source_ids||[]).length?'<p>关联来源：'+record.related_source_ids.map(sourceName).join(' / ')+'</p>':'')+'</div>'
    +'<div class="ux-reading-actions ux-reading-toolbar">'+uxReadingActions(record)+'<button class="button tiny" type="button" data-action="ux-copy" data-id="'+esc(record.id)+'">'+uxCopyLabel(record)+'</button></div><div data-copy-region></div>'
    +(target?'':identities)
    +(record.kind==='research_note'?authorPanel(record):authorControlledKinds.has(record.kind)&&!record.author_confirmed?authorPanel(record):authorControlledKinds.has(record.kind)?'<p class="ux-author">负责作者：'+esc(record.author_name||recordAuthorLabel(record))+' · 已由本人确认</p>':'<p class="ux-author">当前有权读取的有效成员共同编辑</p>')
    +(research?bodySection+abstractSection:abstractSection+bodySection)
    +(typeof automaticProcessingHtml==='function'?automaticProcessingHtml(record):'')
    +(typeof automaticAcquisitionHtml==='function'?automaticAcquisitionHtml(record.automatic_acquisition):'')
    +(!research&&(record.translations?.length||record.chinese_title||record.chinese_abstract)?'<details class="reading-translation-history"><summary>译文来历与处理版本</summary>'+translationPanel(record)+'</details>':'')
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
    +'<details class="reading-review"><summary>核对依据</summary>'+reviewPanel(record)+'</details>'
    +'<details class="ux-metadata"><summary>题录与维护信息</summary><dl class="detail-grid section-gap">'+detailPair('稳定编号',esc(record.id))+detailPair('上传者',esc(record.owner_name))+detailPair('首次收录',dateTime(record.created_at))+detailPair('最近修订',record.last_modifier?esc(record.last_modifier.name)+' · '+dateTime(record.last_modifier.created_at):dateTime(record.updated_at))+detailPair('卷',esc(record.volume))+detailPair('期',esc(record.issue))+detailPair('页码 / 文章编号',esc(record.pages))+detailPair('ISSN',esc(record.issn))+detailPair('DOI',esc(record.doi))+detailPair('关键词',esc(record.keywords))+detailPair('研究对象',esc(record.countries))+detailPair('发布机构',sourceName(record.source_id))+detailPair('所属刊物',sourceName(record.serial_id)||esc(record.publication_title))+'</dl>'+(record.aliases?'<p class="prose">其他题名：'+esc(record.aliases)+'</p>':'')+(record.upstream_status?'<p class="prose">上游核查信息：'+esc(record.upstream_status)+'</p>':'')+'</details>'
    +(typeof intakeEvidenceHtml==='function'?intakeEvidenceHtml(record.intake_evidence):'')
    +(typeof discoveryEvidenceHtml==='function'?discoveryEvidenceHtml(record.discovery_evidence):'')
    +(typeof risEvidenceHtml==='function'?risEvidenceHtml(record.ris_evidence):'')
    +'<details class="ux-maintenance"><summary>整理、编辑与核对</summary><div class="detail-actions">'+maintenance+'</div>'+(!research&&!record.translations?.length&&!record.chinese_title&&!record.chinese_abstract?translationPanel(record):'')+'</details>'
    +(!hasEvidence&&research&&typeof archivedLinks==='function'?archivedLinks('record',record):'')+'</article>';
  if(target)target.innerHTML=content;else modal(kinds[record.kind]||'阅读资料',content);
  const body=target||document.querySelector('.drawer-body');body.classList.add('ux-reader');body.closest('.drawer')?.classList.add('ux-reading-drawer');
  const favorite=body.querySelector('[data-action=favorite]');if(favorite)favorite.dataset.saved=!!record.favorite;
  for(const button of body.querySelectorAll('.icon-button[data-action=add-to-collection]'))button.setAttribute('aria-label','加入资料夹');
  state.detail={type:'record',data:record};
  document.dispatchEvent(new CustomEvent('library:reader-rendered',{detail:{record,root:body}}));
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
