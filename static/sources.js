'use strict';
const institutionTypes={think_tank:'智库',university:'大学 / 高校',research_institute:'研究所 / 研究中心',faculty:'学院',other:'其他机构'};
const internationalLabels={yes:'是 · 有依据',no:'否 · 有依据',unknown:'未知 · 待核实'};
const relationLabels={part_of:'隶属于',established_by:'由这些机构共同设立',cooperates_with:'合作机构',funded_by:'接受资助'};
const inverseRelationLabels={part_of:'下属机构',established_by:'参与设立的机构',cooperates_with:'合作机构',funded_by:'资助的机构'};
const isInstitution=s=>['institution','think_tank'].includes(s.kind);
const isPublication=s=>['journal','serial','registry_publication'].includes(s.kind);
const sourceLabel=s=>isInstitution(s)?'机构':s.kind==='journal'?'期刊':s.kind==='portal'?'资料发现网站':'其他出版物';
const countryText=s=>s.national_status==='recorded'?s.national_countries.join(' / '):'待确认';
function evidenceHtml(text){
  if(!text)return '<p class="small muted">依据待补充；不据此作肯定或否定判断。</p>';
  const urls=[...new Set((text.match(/https?:\/\/[^\s|<>]+/g)||[]).map(u=>u.replace(/[。；），,)]+$/,'')))];
  return `<p class="prose evidence-text">${esc(text)}</p><div class="row wrap">${urls.map((u,i)=>externalLink(u,'依据链接 '+(i+1),'link-button')).join('')}</div>`;
}
function sourceCard(s){
  const meta=isInstitution(s)?`${esc(s.country||'国家待确认')} · ${esc(s.location||'所在地待补充')}`:s.kind==='journal'?`主办国别：${esc(countryText(s))}`:esc(serialTypes[s.classification]||'');
  return `<article class="source-card"><div class="row wrap source-status"><span class="badge blue">${sourceLabel(s)}</span>${badge(s.status)}</div><div><h2>${s.kind==='portal'?linkButton(esc(s.name),'source-preview',s.id,'title-button'):`<a class="title-button" href="${sourceHref(s.id)}">${esc(s.name)}</a>`}</h2>${s.original_name?.trim()&&s.original_name.trim()!==s.name.trim()?`<p class="source-english">${esc(s.original_name)}</p>`:''}</div>${meta?`<p class="small muted">${meta}</p>`:''}<div class="row wrap">${isInstitution(s)?s.institution_types.map(t=>`<span class="badge neutral">${esc(institutionTypes[t])}</span>`).join(''):s.kind==='journal'?`<span class="badge neutral">国际定位：${esc(internationalLabels[s.international_status])}</span>`:''}</div>${s.search_snippet?`<p class="search-snippet">${esc(s.search_snippet)}</p>`:''}<div class="source-foot"><span class="small muted">${scopeLabel(s.scope_status)}</span>${linkButton('快速预览','source-preview',s.id,'link-button')}</div></article>`;
}
function sourceAppliedFilters(p){
  const entries=[['q','关键词',p.get('q')],['institution_type','机构类型',institutionTypes[p.get('institution_type')]],['country','期刊主办国别',p.get('country')==='__pending__'?'待确认':p.get('country')],['international','国际定位',internationalLabels[p.get('international')]],['scope','收录范围',p.get('scope')==='active'?'当前收录范围':p.get('scope')]];
  const active=entries.filter(([key,,value])=>p.get(key)&&value);
  return active.length?`<div class="source-applied" aria-label="已应用的来源筛选"><span>已用条件</span>${active.map(([key,label,value])=>`<button type="button" class="ux-filter-chip" data-action="source-clear-filter" data-id="${key}" aria-label="移除筛选：${esc(label+'：'+value)}">${esc(label+'：'+value)} <span aria-hidden="true">×</span></button>`).join('')}</div>`:'';
}
async function sourcesPage(){
  if(state.params.get('id'))return sourcePage(state.params.get('id'));
  const p=state.params,maintenance=p.get('group')==='maintenance',query=new URLSearchParams(p);
  if(!maintenance)query.set('directory','1');
  const d=await api('/api/sources?'+query),g=p.get('group')||'';
  const groups=[['','全部'],['institution','机构'],['journal','期刊'],['publication','其他出版物']];
  return `<section class="sources-page"><div class="page-heading between wrap"><div><h1>${maintenance?'资料发现网站':'来源目录'}</h1>${maintenance?'<p>登记用于发现资料的门户与检索网站，当前不自动采集。机构与期刊官网保存在原档案，无需重复登记。</p>':''}</div><div class="row wrap">${!maintenance&&state.schema>=4?linkButton('整理重复','duplicates','source'):''}${linkButton(icon('plus')+' '+(maintenance?'新增资料发现网站':'提交来源'),maintenance?'new-portal':'new-source','','button primary')}</div></div>${maintenance?linkButton('返回数据与维护','nav','system'): `<div class="tabs" aria-label="来源类型">${groups.map(([key,name])=>`<button class="tab ${g===key?'active':''}" data-action="source-group" data-id="${key}" aria-pressed="${g===key}">${name}</button>`).join('')}</div>`}<form data-form="source-search" class="source-search"><div class="toolbar"><div class="search-input">${icon('search')}<input type="search" name="q" value="${esc(p.get('q'))}" placeholder="名称、介绍或别名" aria-label="来源关键词"></div><button class="button primary" type="submit">搜索</button></div><details class="source-filter-options"><summary>筛选条件</summary><div class="source-filters">${!maintenance&&['','institution'].includes(g)?`<label>机构类型<select name="institution_type" aria-label="机构类型">${selectOptions(institutionTypes,p.get('institution_type'),'全部机构类型')}</select></label>`:''}${!maintenance&&['','journal'].includes(g)?`<label>期刊主办国别<select name="country" aria-label="期刊主办国别">${selectOptions({...Object.fromEntries(d.countries.map(c=>[c,c])),__pending__:'待确认'},p.get('country'),'全部国别')}</select></label><label>国际定位<select name="international" aria-label="国际定位">${selectOptions(internationalLabels,p.get('international'),'全部国际定位')}</select></label>`:''}<label>收录范围<select name="scope" aria-label="收录范围">${selectOptions({active:'当前收录范围'},p.get('scope'),'全部范围')}</select></label><button class="button primary" type="submit">应用筛选</button>${linkButton('清除筛选','source-group',g)}</div></details></form>${sourceAppliedFilters(p)}${!maintenance?'<details class="directory-help"><summary>分类与国别说明</summary><p>机构类型与隶属关系分别登记。年鉴、工作论文系列和旧出版物登记在“其他出版物”；资料发现网站在“数据与维护”。</p><p>期刊国别按主办关系及机构国家登记生成，出版方国家另记。依据不足或冲突时为待确认；国际定位独立记录，无依据时为未知。中心核对状态另计。</p></details>':''}<div class="results-head"><span>找到 <strong>${d.total}</strong> 条${maintenance?'资料发现网站':'来源'}</span></div><div class="source-grid">${d.items.map(sourceCard).join('')||empty('没有匹配的来源','调整筛选条件，或补充有依据的来源信息。','source')}</div></section>`;
}
async function systemPage(){
  const base=await baseSystemPage(),d=await api('/api/sources?group=maintenance');
  return `<section class="workspace-system"><div class="page-heading"><h1>数据与维护</h1></div><div class="system-grid">${state.schema>=5&&typeof operationsSystemCards==='function'?operationsSystemCards():''}<section class="system-card workspace-portals" aria-labelledby="portals-heading"><div class="between wrap"><h2 id="portals-heading">资料发现网站</h2>${linkButton('管理入口（'+d.total+'）','source-group','maintenance','button')}</div><p>门户与检索网站登记在此，用于发现资料；当前不自动采集。机构与期刊官网保存在原档案，无需重复登记。后续采集可关联官网的文章列表、刊期或订阅地址。</p>${d.items.length?`<ul class="portal-list">${d.items.map(s=>`<li>${linkButton(esc(s.name),'source-detail',s.id,'title-button')}</li>`).join('')}</ul>`:'<p class="muted">暂无资料发现网站。</p>'}</section>${base}</div></section>`;
}
function relationDetails(s){
  const outgoing=(s.relationships||[]).map(r=>({label:relationLabels[r.type],id:r.target_id,evidence:r.evidence,checked_on:r.checked_on,owner:s.id}));
  const incoming=(s.related_from||[]).map(r=>({label:inverseRelationLabels[r.type],id:r.source_id,evidence:r.evidence,checked_on:r.checked_on,owner:r.source_id}));
  return `<section class="detail-section"><h3>机构关系</h3>${[...outgoing,...incoming].map(r=>`<div class="relation-detail"><strong>${esc(r.label)}</strong><div>${sourceName(r.id)}</div>${evidenceHtml(r.evidence)}<div class="between small muted"><span>依据核查日期：${esc(r.checked_on||'未登记')}</span>${linkButton('编辑关系起点','edit-source',r.owner,'link-button')}</div></div>`).join('')||'<p class="small muted">尚无已登记的机构关系，可在编辑来源时补充依据。</p>'}</section>`;
}
function sourceHref(id){
  const params=state.page==='sources'?parameters({id}):new URLSearchParams({id});
  return '#sources?'+esc(params.toString());
}
async function openSource(id,preview=false){
  const known=state.sources.find(source=>source.id===id);
  if(!preview&&known?.kind!=='portal'){
    const work=state.detail?.type==='record'?state.detail.data.id:state.bylineSourceReturn?.id===id?state.bylineSourceReturn.record:state.params.get('work');
    if(closeModal(false)===false)return;
    return go('sources',state.page==='sources'?parameters({id,work:work||'',note_page:'',content_published:'',content_associated:'',content_translations:'',content_outputs:''}):{id,...(work?{work}:{})});
  }
  const hash=location.hash,account=state.me?.id,loadId=state.loadId;
  const s=await api('/api/sources/'+encodeURIComponent(id));
  const html=await sourceProfile(s,true,id);
  if(location.hash!==hash||state.me?.id!==account||loadId!==state.loadId)return;
  state.detail={type:'source',data:s};state.sourcePreviewId=s.id;
  modal('来源快速预览',html);
}
async function sourcePage(id){
  let s;
  try{s=await api('/api/sources/'+encodeURIComponent(id));}
  catch(error){if(error.status!==404)throw error;return '<section class="source-page"><a class="back-link" href="#sources?'+esc(parameters({id:''}))+'">← 返回来源目录</a><h1>无法打开来源档案</h1><p class="notice">该编号不存在或当前不可访问，请核实链接。</p></section>';}
  if(s.kind==='portal')return '<h1>'+esc(s.name)+'</h1><p>资料发现网站在数据与维护区管理。</p>'+linkButton('打开维护预览','source-preview',s.id)+linkButton('返回资料发现网站','source-group','maintenance');
  const html=await sourceProfile(s,false,id);
  state.sourceProfile={requested:id,data:s};
  if(!document.querySelector('#modal-root .overlay'))state.detail={type:'source',data:s};return html;
}
async function sourceContentSection(s,key,label,page=Number(state.params.get('content_'+key)||1)){
  const query=new URLSearchParams({source:s.id,source_section:key,size:12,page});
  const d=await api('/api/records?'+query);
  return `<section class="detail-section source-content-section" data-source-content="${key}" data-label="${label}"><div class="between wrap"><h3 id="source-${key}">${label}</h3>${key==='translations'?linkButton(icon('plus')+' 新建目录译稿','new-source-translation',s.id,'button primary tiny'):''}</div><p class="small muted">当前可阅读 ${d.total} 份${key==='associated'?' · 仅表示已登记的一般关联':key==='outputs'?' · 中心成果，与该来源的公开作品分别保存':''}</p><div class="source-content-list">${d.items.map(r=>`<article><div class="row wrap">${typeBadge(r.kind)}<span class="muted">${esc(r.coverage||r.published_on)}</span>${r.has_attachment?'<span class="badge neutral">有附件</span>':''}</div>${linkButton(esc(r.title),'detail',r.id,'title-button')}<p class="small muted">${esc(r.author_name||r.authors||'署名待补充')} · 版本 ${r.version}</p></article>`).join('')||'<p class="muted">当前尚无可阅读的已收录内容；这不表示该对象没有成果。</p>'}</div>${d.total>d.size?`<div class="pagination"><button class="button tiny" data-action="source-content-page" data-key="${key}" data-id="${d.page-1}" ${d.page<=1?'disabled':''}>上一页</button><span>第 ${d.page} / ${Math.ceil(d.total/d.size)} 页</span><button class="button tiny" data-action="source-content-page" data-key="${key}" data-id="${d.page+1}" ${d.page*d.size>=d.total?'disabled':''}>下一页</button></div>`:''}</section>`;
}
async function sourceProfile(s,preview=false,requested=s.id){
  const common=detailPair('来源研究覆盖范围',esc(s.research_scope))+detailPair('稳定编号',esc(s.id));
  let fields='',relations='',evidence='';
  if(isInstitution(s)){
    fields=detailPair('机构类型',s.institution_types.map(t=>esc(institutionTypes[t])).join(' / '))+detailPair('机构所在地',esc(s.location))+detailPair('机构国家',esc(s.country));
    evidence=`<section class="detail-section"><h4>机构国家依据</h4>${evidenceHtml(s.country_evidence)}</section>`;
    relations=relationDetails(s)+await bylineWorksSection('institution',s.id)+await employmentSection(s.id,true)+await institutionAffiliationsSection(s.id);
  }else if(isPublication(s)){
    fields=detailPair('主办机构',sourceName(s.host_id))+detailPair('出版机构',sourceName(s.publisher_id))+detailPair('主办方国别',esc(countryText(s)))+detailPair('出版方国家（另记）',esc(s.publisher_countries.join(' / ')))+detailPair('ISSN',esc(s.issn));
    evidence=`<section class="detail-section"><h4>主办国别的依据</h4><p class="small">${s.national_status==='recorded'?'根据下列既有登记归类；不等同中心已核对。':esc(s.country_gaps.join('；'))}</p>${evidenceHtml(s.host_evidence)}${s.country_basis.map(h=>`<div class="relation-detail">${sourceName(h.id)} · ${esc(h.countries.join(' / ')||'国家待确认')}${evidenceHtml(h.evidence)}</div>`).join('')}</section>`;
    if(s.kind==='journal'){fields+=detailPair('国际办刊定位',esc(internationalLabels[s.international_status]));evidence+=`<section class="detail-section"><h4>国际定位依据</h4>${evidenceHtml(s.international_evidence)}</section>`;}
  }
  const publications=(s.related||[]).map(x=>linkButton(esc(x.name),'source-detail',x.id,'detail-link')).join('');
  if(publications)relations+=`<section class="detail-section"><h4>主办或出版的刊物</h4>${publications}</section>`;
  const content=s.kind==='portal'?'':(await Promise.all([['published',isInstitution(s)?'机构发布资料':'刊物刊载资料'],['associated','一般关联资料'],['translations','目录译稿'],['outputs','中心成果']].map(([key,label])=>sourceContentSection(s,key,label)))).join('');
  const notes=isInstitution(s)||s.kind==='journal'?await noteSubjectProfile(isInstitution(s)?'institution':'journal',s.id,Number(state.params.get('note_page')||1)):'';
  const items=[{id:'source-introduction',label:'来源介绍'},{id:'source-information',label:'来源信息'}];
  if(relations)items.push({id:'source-relations',label:'关系与作品'});
  if(content)items.push({id:'source-content',label:'来源内容'});
  if(notes)items.push({id:'source-notes',label:'研究笔记'});
  items.push({id:'source-evidence',label:'依据与核查'});
  return `<article class="source-profile ${preview?'source-preview':'source-page'}" data-section-scope>${preview?(s.kind==='portal'?'':`<a class="back-link" href="${sourceHref(s.id)}">打开完整档案 ${icon('arrow')}</a>`):`<a class="back-link" data-action="source-directory-back" href="#sources?${esc(parameters({id:'',work:'',note_page:'',content_published:'',content_associated:'',content_translations:'',content_outputs:''}))}">← 返回来源目录</a>`}${requested!==s.id?`<p class="notice">旧编号 ${esc(requested)} 已合并至当前档案 ${esc(s.id)}。${linkButton('查看合并前内容','view-archived',requested,'link-button').replace('data-id=','data-type="source" data-id=')}</p>`:''}${state.params.get('work')?linkButton('返回资料','byline-back',state.params.get('work')):state.bylineSourceReturn?.id===s.id?linkButton('返回资料','byline-back',state.bylineSourceReturn.record):''}<header class="source-profile-heading"><div class="row wrap"><span class="badge blue">${sourceLabel(s)}</span>${badge(s.status)}<span class="small muted">版本 ${s.version}</span></div><${preview?'h2':'h1'} class="detail-title">${esc(s.name)}</${preview?'h2':'h1'}>${s.original_name?.trim()&&s.original_name.trim()!==s.name.trim()?`<p class="original-title">${esc(s.original_name)}</p>`:''}<div class="detail-actions source-main-actions">${safeUrl(s.website)?externalLink(s.website,'官方网站'):''}${safeUrl(s.catalogue_url)?externalLink(s.catalogue_url,'资料目录'):''}${linkButton(icon('edit')+' 编辑来源','edit-source',s.id,'button primary tiny')}</div><details class="source-maintenance"><summary>历史与维护</summary><div class="detail-actions">${linkButton(icon('clock')+' 修改历史','history','source:'+s.id)}${linkButton('整理重复来源','duplicates','source')}${state.me.role==='admin'&&s.status!=='verified'?linkButton('标记已核对','verify','source:'+s.id,'button tiny'):''}</div></details></header>${sectionNavigation(items,'来源章节')}<section class="source-profile-group source-introduction"><h3 id="source-introduction">来源介绍</h3>${s.introduction_html?`<div class="rich-prose">${readRich(s.introduction_html)}</div>`:'<p class="muted">介绍待补充，可由中心成员共同维护。</p>'}${s.aliases?`<p class="prose"><strong>其他名称：</strong>${esc(s.aliases)}</p>`:''}</section><section class="source-profile-group"><h3 id="source-information">来源信息</h3><dl class="detail-grid">${fields}${common}</dl></section>${relations?`<section class="source-profile-group source-profile-relations"><h3 id="source-relations">关系与作品</h3>${relations}</section>`:''}${content?`<section class="source-profile-group"><h3 id="source-content">来源内容</h3>${content}</section>`:''}${notes.replace('<h2>','<h3 id="source-notes">').replace('</h2>','</h3>')}<section class="source-profile-group source-profile-evidence"><h3 id="source-evidence">依据与核查</h3>${evidence}<details class="section-gap"><summary>原始分类、备注与上游核查信息</summary><dl>${detailPair('原始分类',esc(s.classification))}${detailPair('旧国别登记',esc(s.country))}</dl><p class="prose">${esc(s.notes||'无原始备注')}</p><p class="prose">${esc(s.upstream_status||'无上游核查状态')}</p><p class="small muted">中文工作译名未经审定；上游核验不等于中心已核对。</p></details>${typeof archivedLinks==='function'?archivedLinks('source',s):''}</section></article>`;
}
let relationRowCounter=0;
function relationEditor(r={}){
  const index=++relationRowCounter;
  return `<div class="relation-editor" data-relation-row><div class="form-grid"><div class="field"><label for="rel-type-${index}">关系方向（本机构为起点）</label><select id="rel-type-${index}" data-rel="type">${selectOptions(relationLabels,r.type||'part_of')}</select></div>${searchableSourceField('','关联机构',r.target_id,{groups:['institution'],exclude:state.editing.id,rel:true})}<div class="field wide"><label for="rel-evidence-${index}">关系依据（必填）</label><textarea id="rel-evidence-${index}" data-rel="evidence" required placeholder="官方说明、链接、证据范围">${esc(r.evidence)}</textarea></div><div class="field"><label for="rel-date-${index}">依据核查日期</label><input id="rel-date-${index}" type="date" data-rel="checked_on" value="${esc(r.checked_on)}"></div><div>${linkButton('移除这项关系','source-remove-relation')}</div></div></div>`;
}
function sourceSpecific(s){
  if(isInstitution(s))return `<div class="field wide"><label>机构类型（可多选）</label><div class="check-group">${Object.entries(institutionTypes).map(([v,l])=>`<label class="check-label"><input type="checkbox" name="institution_types" value="${v}" ${(s.institution_types||[]).includes(v)?'checked':''}>${l}</label>`).join('')}</div></div>${inputField('location','机构所在地',s.location)}${inputField('country','机构国家',s.country,'多国用 | 分隔')}${textField('country_evidence','机构国家依据',s.country_evidence,'登记出处、链接与核查边界')}<div class="wide"><h3>机构关系</h3><p class="form-help">本机构 → 上级 / 共同设立方 / 合作方 / 资助方。合作和资助不表示隶属；共同设立可逐项添加多个设立方。</p><div id="relation-editors">${(s.relationships||[]).map(relationEditor).join('')}</div>${linkButton('添加机构关系','source-add-relation')}</div>`;
  if(isPublication(s)){
    return `${searchableSourceField('host_id','主办机构（可多选）',s.host_id,{groups:['institution'],multiple:true})}${searchableSourceField('publisher_id','出版机构（可多选）',s.publisher_id,{groups:['institution'],multiple:true})}${inputField('issn','ISSN',s.issn)}${selectField('host_country_status','主办关系依据状态',{auto:'按已登记关系及机构国家归类',pending:'角色存疑 / 冲突，国别待确认'},s.host_country_status||'auto','请选择')}${textField('host_evidence','主办关系依据',s.host_evidence,'明确哪些机构承担主办角色；缺少依据时不会归入确定国别。')}${s.kind==='journal'?selectField('international_status','国际办刊定位',internationalLabels,s.international_status||'unknown','请选择')+textField('international_evidence','国际定位依据',s.international_evidence,'选择是或否均需依据；不以英语、刊名或外国出版社推断。'):''}<p class="form-help wide">主办国别由机构国家与依据生成；出版方国家独立展示。更正机构国家请进入该机构记录。</p>`;
  }
  return '<p class="form-help wide">资料发现网站用于登记门户与检索网站，当前不自动采集。机构与期刊官网保存在原档案，无需重复登记；后续采集可关联官网的文章列表、刊期或订阅地址。</p>';
}
async function sourceForm(id='',forcedKind='',draftKey=''){
  const s=id?await api('/api/sources/'+encodeURIComponent(id)):{kind:forcedKind||(state.params.get('group')==='maintenance'?'portal':'institution'),scope_status:'candidate',institution_types:[],relationships:[]};
  state.editing={type:'source',id,version:s.version,original:s,draftSpecific:{...s},preview:!!document.querySelector('.source-preview')};
  const options={institution:'机构',journal:'期刊',serial:'其他出版物',portal:'资料发现网站',...(s.kind==='think_tank'?{think_tank:'机构（原智库登记）'}:{}),...(s.kind==='registry_publication'?{registry_publication:'其他出版物（旧登记）'}:{})};
  modal(id?'修订公共来源':'提交新来源',`<div class="notice">来源由成员共同维护；保存后重新待核对，并保留历史。</div><form data-form="source" class="section-gap"><div class="form-grid">${inputField('name','显示名称 *',s.name,'中文名或原名',true)}${inputField('original_name','原文 / 英文名称',s.original_name,'',true)}${selectField('kind','对象类型',options,s.kind,'请选择')}<p id="source-type-change-note" class="notice wide" hidden>保存类型更正时，新类型不适用的字段移入历史，适用字段继续保留。仍有机构关系或主办／出版引用的机构需先处理关联，才能改为其他对象类型。</p>${selectField('scope_status','收录范围',{candidate:'候选 · 待确认',core:'当前收录范围',mixed:'部分议题收录',historical:'历史来源',out_of_scope:'范围外保留',...(s.scope_status?{[s.scope_status]:scopeLabel(s.scope_status)}:{})},s.scope_status)}${inputField('website','官方网站',s.website,'https://…',true,'url')}${inputField('catalogue_url','资料目录入口',s.catalogue_url,'https://…',true,'url')}${inputField('research_scope','来源研究覆盖范围',s.research_scope,'',true)}<div id="source-specific-fields" class="wide form-grid">${sourceSpecific(s)}</div><details class="wide"><summary>原始分类和备注（核查用）</summary>${inputField('classification','原始登记类别',s.classification)}${textField('notes','原始备注及补充说明',s.notes)}</details></div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">取消</button><button type="submit" class="button primary">${id?'保存修订':'提交来源'}</button></div></form>`);
  enhanceSourceForm(document.querySelector('[data-form=source]'),draftKey);
}
async function submitSourceForm(form,data,values){
  if(form._conflictPending)throw new Error('请先对照最新版本，再继续保存。');
  if(form._draftOffer)throw new Error('请先恢复或舍弃已有草稿。');
  const edit=form._editing||state.editing,institution=['institution','think_tank'].includes(values.kind);
  values.institution_types=institution?data.getAll('institution_types'):[];
  values.relationships=institution?[...form.querySelectorAll('[data-relation-row]')].map(row=>Object.fromEntries([...row.querySelectorAll('[data-rel]')].map(el=>[el.dataset.rel,el.value]))):[];
  if(!institution&&values.kind!=='portal'){values.host_id=data.getAll('host_id').join(' | ');values.publisher_id=data.getAll('publisher_id').join(' | ');}
  values.version=edit.version;
  const r=await api('/api/sources'+(edit.id?'/'+encodeURIComponent(edit.id):''),{method:edit.id?'PUT':'POST',body:values});
  await clearEditorDraft(form);await loadLookups();closeModal();if(edit.preview){await uxRefreshBackground();await openSource(r.id,true);}else await openSource(r.id);toast('来源及关系已保存，等待核对');
}
document.addEventListener('click',event=>{
  const b=event.target.closest('[data-action]');if(!b)return;
  if(b.dataset.action==='source-preview')openSource(b.dataset.id,true).catch(e=>toast(e.message));
  if(b.dataset.action==='source-content-page'){
    const section=b.closest('[data-source-content]');
    if(b.closest('.source-preview'))sourceContentSection(state.detail.data,b.dataset.key,section.dataset.label,Number(b.dataset.id)).then(html=>{if(section.isConnected)section.outerHTML=html;}).catch(e=>toast(e.message));
    else go('sources',parameters({['content_'+b.dataset.key]:b.dataset.id}));
  }
  if(b.dataset.action==='source-group')go('sources',b.dataset.id?{group:b.dataset.id}:{});
  if(b.dataset.action==='source-clear-filter')go('sources',parameters({[b.dataset.id]:''}));
  if(b.dataset.action==='new-portal')sourceForm('','portal').catch(e=>toast(e.message));
  if(b.dataset.action==='source-add-relation')document.querySelector('#relation-editors').insertAdjacentHTML('beforeend',relationEditor());
  if(b.dataset.action==='source-remove-relation')b.closest('[data-relation-row]').remove();
});
document.addEventListener('change',event=>{
  const filter=event.target.closest('[data-form="source-search"]');
  if(filter&&event.target.value){
    const clear=event.target.name==='institution_type'?['country','international']:['country','international'].includes(event.target.name)?['institution_type']:[];
    clear.forEach(name=>{const el=filter.elements.namedItem(name);if(el)el.value='';});
  }
  const sourceFormElement=event.target.closest('[data-form="source"]');
  if(sourceFormElement&&['country','host_id'].includes(event.target.name)){
    const original=state.editing.original,key=event.target.name,evidenceKey=key==='country'?'country_evidence':'host_evidence';
    const evidence=sourceFormElement.elements.namedItem(evidenceKey);
    const currentValue=key==='host_id'?[...event.target.selectedOptions].map(o=>o.value).sort().join('|'):event.target.value;
    const oldValue=key==='host_id'?String(original.host_id||'').split(/[|;,]/).map(x=>x.trim()).filter(Boolean).sort().join('|'):original.country||'';
    if(currentValue!==oldValue&&evidence&&evidence.value===(original[evidenceKey]||'')){
      evidence.value='';evidence.placeholder='关联已改变，请填写适用于新信息的依据；旧依据保留在历史中。';
      toast('关联已改变，原依据已留在历史；请补充新依据。');
    }
  }
  if(event.target.id==='f-kind'&&event.target.closest('[data-form="source"]')){
    const draft=state.editing.draftSpecific,data=new FormData(sourceFormElement);
    for(const key of ['location','country','country_evidence','issn','host_country_status','host_evidence','international_status','international_evidence']){
      if(sourceFormElement.elements.namedItem(key))draft[key]=data.get(key);
    }
    for(const key of ['host_id','publisher_id'])if(sourceFormElement.elements.namedItem(key))draft[key]=data.getAll(key).join(' | ');
    if(sourceFormElement.querySelector('#relation-editors')){
      draft.institution_types=data.getAll('institution_types');
      draft.relationships=[...sourceFormElement.querySelectorAll('[data-relation-row]')].map(row=>Object.fromEntries([...row.querySelectorAll('[data-rel]')].map(el=>[el.dataset.rel,el.value])));
    }
    document.querySelector('#source-specific-fields').innerHTML=sourceSpecific({...draft,kind:event.target.value});
    document.querySelector('#source-type-change-note').hidden=!state.editing.id||event.target.value===state.editing.original.kind;
  }
});

let sourceDirectoryPosition=null,sourceRestorePosition=false;
document.addEventListener('click',event=>{
  const link=event.target.closest('a[href^="#sources?"]');
  if(link&&!state.params.has('id')&&state.page==='sources'&&new URLSearchParams(link.hash.split('?')[1]).has('id'))sourceDirectoryPosition={hash:location.hash,y:window.scrollY};
  if(event.target.closest('[data-action="source-directory-back"]'))sourceRestorePosition=true;
},true);
function sourceAfterRender(){
  if(state.page!=='sources'||state.params.has('id'))return;
  if(sourceRestorePosition&&sourceDirectoryPosition?.hash===location.hash)requestAnimationFrame(()=>window.scrollTo(0,sourceDirectoryPosition.y));
  sourceRestorePosition=false;
}

function restoreSourceDetail(){
  state.sourcePreviewId=null;
  if(state.page==='sources'&&state.params.get('id')===state.sourceProfile?.requested)state.detail={type:'source',data:state.sourceProfile.data};
  else if(state.page==='sources'&&!state.params.has('id'))state.detail=null;
}
