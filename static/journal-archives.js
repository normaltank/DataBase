'use strict';

const jaCoverage={complete:'完整目次',partial:'部分收录',unverified:'覆盖范围未核实'};
const jaKinds={abstract_translation:'摘要译文',editor_summary:'编者概述',unverified_extract:'来源未核实的摘编',original_abstract:'原文摘要'};
const jaMetricKinds={impact_factor:'普通影响因子',five_year:'五年影响因子',original:'原始口径待核实'};
const jaPositions=new Map(),jaDrafts=new Map();
let jaContext=null;
function jaUrl(changes={}){const p=new URLSearchParams(state.params);for(const [k,v] of Object.entries(changes))v?p.set(k,v):p.delete(k);return '#'+state.page+'?'+p;}
function jaLink(label,changes,cls='button tiny'){return `<a class="${cls}" href="${esc(jaUrl(changes))}" data-ja-link>${esc(label)}</a>`;}
function jaButton(label,action,attrs=''){return `<button type="button" class="button tiny" data-ja="${action}" ${attrs}>${esc(label)}</button>`;}
function jaField(name,label,value='',type='text'){return `<label class="field">${esc(label)}<input name="${name}" type="${type}" value="${esc(value)}"></label>`;}
function jaText(name,label,value=''){return `<label class="field ja-wide">${esc(label)}<textarea name="${name}" rows="3">${esc(value)}</textarea></label>`;}
function jaSelect(name,label,choices,value){return `<label class="field">${esc(label)}<select name="${name}">${Object.entries(choices).map(([key,text])=>`<option value="${key}" ${key===value?'selected':''}>${esc(text)}</option>`).join('')}</select></label>`;}
function jaValue(value,fallback='待补充'){return esc(value===0?'0':value||fallback);}
function jaFacts(fields){return `<dl class="ja-facts">${fields.filter(([,v])=>v!==undefined&&v!=='').map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${jaValue(v)}</dd></div>`).join('')}</dl>`;}
function jaCover(cover,fallback=false){
  if(!cover||!Object.keys(cover).length)return '';
  if(cover.unavailable)return '<p class="muted">封面附件当前不可读取。</p>';
  return `<figure class="ja-cover">${cover.file?`<img src="${esc(cover.url)}" alt="期刊封面" loading="lazy">`:cover.url?`<a href="${esc(cover.url)}">${esc(cover.attachment_name||'封面附件')}</a>`:''}<figcaption>${fallback?'沿用期刊封面 · ':''}${cover.illustrative?'示意图，不代表本期':'已登记封面'}${cover.issue_id?' · 对应原刊卷期 '+esc(cover.issue_id):''}${cover.external_url?'<p>'+externalLink(cover.external_url,'外部图片线索（尚未保存文件）')+'</p>':''}<p>${esc(cover.note)}</p><details><summary>封面出处</summary><p class="prose">${esc(cover.evidence)}</p></details></figcaption></figure>`;
}
function jaProfileRead(s,p){
  const metrics=p.metrics||[],rankings=p.rankings||[];
  return `<div class="ja-introduction">${jaCover(p.cover)}<div>${s.introduction_html?`<div class="rich-prose">${readRich(s.introduction_html)}</div>`:'<p class="muted">期刊介绍待补充。</p>'}${jaFacts([['创刊',p.founded],['发行周期',p.frequency],['聚焦领域',s.research_scope],['纸本 ISSN',p.print_issn],['电子 ISSN',p.electronic_issn],['旧未分类标识',s.issn],['出版方原始名称',p.publisher_text]])}</div></div><section class="ja-section"><div class="between wrap"><h2>年度指标</h2>${jaLink('维护期刊信息与指标',{ja_edit:'profile',ja_issue:'',ja_compilation:''})}</div>${metrics.length?`<div class="ja-metrics">${metrics.map(m=>`<article><h3>${esc(m.name)}</h3><p class="ja-metric-value">${jaValue(m.value,'缺失')}<span>${jaValue(m.year,'年度未知')}</span></p><p class="small muted">${esc(jaMetricKinds[m.kind]||m.kind)}${m.released_year?' · 发布于 '+esc(m.released_year):''}</p>${m.raw_label?'<p>来源原词：'+esc(m.raw_label)+'</p>':''}<details><summary>出处与核对说明</summary>${evidenceHtml(m.evidence)}<p class="prose">${esc(m.note)}</p></details></article>`).join('')}</div>`:'<p class="muted">尚未登记年度指标。</p>'}${rankings.map(r=>`<section class="ja-ranking"><h3>中科院分区 · ${jaValue(r.year,'年度未知')} ${esc(r.edition)}</h3><ul>${r.subjects.map(x=>`<li>${x.level==='major'?'大类':'小类'}：${esc(x.chinese_name||x.original_name)}${x.chinese_name&&x.original_name?' / '+esc(x.original_name):''} · ${x.quartile?esc(x.quartile)+'区':'分区待核实'}${x.evidence?' · '+esc(x.evidence):''}</li>`).join('')}</ul>${r.raw_label?'<p>原始标注：'+esc(r.raw_label)+'</p>':''}<details><summary>版本出处</summary>${evidenceHtml(r.evidence)}<p>${esc(r.note)}</p></details></section>`).join('')}${p.indexing?'<p class="prose">收录与原始表述：'+esc(p.indexing)+'</p>':''}<p class="small muted">数值保留所据年度和口径；缺项与零值分别显示。</p></section>`;
}
function jaIssueRead(s,issue,profile,history=false){
  return `<div class="ja-issue-heading">${jaCover(issue.cover?.evidence?issue.cover:profile.cover,!issue.cover?.evidence)}<div><h1>${esc(issue.label||[issue.year,issue.volume&&'卷 '+issue.volume,issue.number&&'期 '+issue.number].filter(Boolean).join(' · '))}</h1><p class="original-title">${esc(s.name)}</p>${jaFacts([['原刊年份',issue.year],['卷',issue.volume],['期',issue.number],['原刊出版日期',issue.published_on],['专刊／合刊',issue.special_note]])}<p class="ja-coverage">${jaCoverage[issue.coverage]||'覆盖范围未核实'}${issue.checked_on?' · 核对于 '+esc(issue.checked_on):''}</p><p class="prose">${esc(issue.coverage_note)}</p><details><summary>原目次依据</summary>${evidenceHtml(issue.catalogue_evidence)}</details></div></div><section class="ja-section"><div class="between wrap"><h2>目次</h2>${history?'':jaLink('维护卷期与目次',{ja_edit:'issue',ja_history:''})}</div>${(issue.sections||[]).map(section=>`<section class="ja-toc-section"><h3>${esc(section.title||'未分栏目')}</h3><ol>${section.entries.map(entry=>`<li id="ja-entry-${entry.id}" data-ja-entry="${entry.id}"><article><h4>${esc(entry.chinese_title||entry.title)}</h4>${entry.chinese_title?'<p class="original-title">'+esc(entry.title)+'</p>':''}<p class="small">${esc(entry.authors||'署名待补充')}${entry.pages?' · '+esc(entry.pages):''}${entry.article_number?' · 文章编号 '+esc(entry.article_number):''}</p><div class="row wrap">${entry.kind?'<span class="small muted">'+esc(entry.kind)+'</span>':''}${entry.record_id?jaButton('阅读已入库资料','read-record',`data-id="${esc(entry.record_id)}" data-entry="${entry.id}"`):'<span class="small muted">'+(entry.record_unavailable?'关联资料当前不可读':'尚未关联入库资料')+'</span>'}${entry.url?externalLink(entry.url,'原文链接'):''}${history?'':jaButton('选编中文内容','select-entry',`data-entry="${entry.id}"`)}</div><details><summary>题录与关联依据</summary>${jaFacts([['DOI',entry.doi],['原始单位',entry.affiliations],['归属依据',entry.relation_evidence],['题录差异说明',entry.conflict_note]])}</details></article></li>`).join('')}</ol></section>`).join('')||'<p class="muted">尚未登记目次；缺少摘要或全文不影响登记。</p>'}</section>`;
}
function jaSelectionRead(item){
  if(item.unavailable)return '<p class="notice">此条选编依据当前不可读，内容已按权限收起。</p>';
  const b=item.basis||{},snap=b.snapshot||{},entry=item.entry_snapshot||{};
  return `<section class="ja-selected-content"><p class="small muted">${esc(jaKinds[item.kind])} · ${esc(item.compiler)}</p><h3>${esc(entry.chinese_title||entry.title)}</h3><div class="rich-prose">${readRich(item.body_html)}</div>${item.needs_review?'<p class="notice">原文已更新至版本 '+item.current_record_version+'，请复核；本条仍保留采用时版本 '+b.record_version+'。</p>':''}<details><summary>所据原文与采用版本</summary>${jaFacts([['原文题名',snap.title||entry.title],['原始署名',snap.authors||entry.authors],['资料版本',b.record_version],['来源／样稿版本',b.source_version],['位置',b.locator],['原文链接',b.url||snap.url]])}${b.record_id?jaButton('打开当前资料','read-record',`data-id="${esc(b.record_id)}"`):''}${snap.abstract?'<h4>采用时原文摘要</h4><p class="prose">'+esc(snap.abstract)+'</p>':''}${snap.body_html?'<details><summary>采用时网页正文</summary><div class="rich-prose">'+readRich(snap.body_html)+'</div></details>':''}</details></section>`;
}
function jaCompilationRead(record,doc,history=false){
  return `<header><h1>${esc(record.title)}</h1><p class="small muted">${esc(record.coverage)} · ${esc(record.authors||'署名待补充')} · ${esc(kinds[record.kind])}</p>${history?'':`<div class="row wrap">${record.can_edit?jaLink('编写选编内容与原文依据',{ja_edit:'compilation',ja_history:''}):''}${record.can_edit?linkButton('编辑整体正文与附件','edit-record',record.id):''}${linkButton('正文历史','history','record:'+record.id)}</div>`}</header>${jaFacts([['编译时间',doc.compiled_on],['中心发布日期',doc.released_on],['覆盖说明',doc.coverage_note],['编译／审校署名',doc.credits]])}<section class="ja-section">${record.body_html?`<div class="rich-prose">${readRich(record.body_html)}</div>`:'<p class="muted">整体译稿可先保存，结构关联可随后补齐。</p>'}${(record.attachments||[]).map(a=>`<a class="detail-link" href="/api/attachments/${encodeURIComponent(a.id)}">${esc(a.name)}</a>`).join('')}</section><section class="ja-section"><h2>选编内容</h2>${(doc.selections||[]).map(jaSelectionRead).join('')||'<p class="muted">尚未编写选编内容。</p>'}</section>`;
}
async function journalArchivePage(s){
  const data=await api('/api/journals/'+encodeURIComponent(s.id));
  const iid=state.params.get('ja_issue'),rid=state.params.get('ja_compilation'),edit=state.params.get('ja_edit'),historyKind=state.params.get('ja_history');
  const issue=iid?data.issues.find(i=>i.id===iid):null;
  let record=null,doc=null;
  if(rid){[record,doc]=await Promise.all([api('/api/records/'+encodeURIComponent(rid)),api(`/api/journals/${encodeURIComponent(s.id)}/compilations/${encodeURIComponent(rid)}`)]);}
  jaContext={s,data,issue,record,doc};
  const base=jaLink('返回期刊档案',{ja_issue:'',ja_compilation:'',ja_edit:'',ja_history:'',ja_entry:''},'back-link');
  let content='';
  if(historyKind){
    const kind=historyKind==='profile'?'profile':historyKind==='issue'?'issues/'+iid:'compilations/'+rid;
    const history=await api(`/api/journals/${encodeURIComponent(s.id)}/${kind}/history`);
    content=`<h1>修改历史</h1>${history.items.map(event=>`<details class="ja-history"><summary>版本 ${event.version} · ${esc(event.actor_name)} · ${dateTime(event.created_at)}</summary>${historyKind==='profile'?jaProfileRead(s,event.snapshot):historyKind==='issue'?jaIssueRead(s,event.snapshot,data.profile,true):jaCompilationRead(record,event.snapshot,true)}</details>`).join('')||'<p>暂无修改历史。</p>'}`;
  }else if(edit==='profile')content=jaProfileForm(s,data.profile);
  else if(edit==='issue')content=jaIssueForm(issue||{});
  else if(edit==='compilation'&&record)content=jaCompilationForm(record,doc,data.issues);
  else if(edit==='new-compilation')content=jaNewCompilationForm();
  else if(edit==='attach-compilation'){
    const records=await api('/api/records?'+new URLSearchParams({source:s.id,kind:'directory_translation|compilation|research_report',size:100}));
    content='<h1>接续已有译稿或成果</h1><p>保留原正文、附件、身份和授权，逐步补充原刊卷期及选编关系。</p>'+records.items.map(r=>jaLink(r.title,{ja_compilation:r.id,ja_edit:'compilation',ja_issue:''},'detail-link')).join('');
  }else if(rid)content=jaCompilationRead(record,doc)+jaLink('选编与依据历史',{ja_history:'compilation'});
  else if(issue)content=jaIssueRead(s,issue,data.profile)+jaLink('卷期与目次历史',{ja_history:'issue'});
  else content=`<header class="ja-heading"><h1>${esc(s.name)}</h1>${s.original_name&&s.original_name!==s.name?'<p class="original-title">'+esc(s.original_name)+'</p>':''}<div class="row wrap">${s.website?externalLink(s.website,'期刊官网'):''}${linkButton('维护名称、介绍与机构关系','edit-source',s.id)}${jaLink('信息与指标历史',{ja_history:'profile'})}</div></header>${jaProfileRead(s,data.profile)}<section class="ja-section"><div class="between wrap"><h2>原刊卷期</h2>${jaLink('登记原刊卷期',{ja_edit:'issue',ja_issue:''})}</div><div class="ja-index">${data.issues.map(i=>`<article>${jaLink(i.label||[i.year,i.volume,i.number].filter(Boolean).join(' · '),{ja_issue:i.id,ja_compilation:'',ja_edit:''},'ja-index-title')}<p class="small muted">${jaCoverage[i.coverage]} · ${i.sections?.reduce((n,s)=>n+s.entries.length,0)||0} 条目次</p></article>`).join('')||'<p class="muted">尚未登记。成果期次和近期文章不会自动成为原刊卷期。</p>'}</div></section><section class="ja-section"><div class="between wrap"><h2>目录译稿与选编</h2><div class="row wrap">${jaLink('新建目录译稿',{ja_edit:'new-compilation'})}${jaLink('接续已有译稿或成果',{ja_edit:'attach-compilation'})}</div></div><div class="ja-index">${data.compilations.map(c=>`<article>${jaLink(c.title,{ja_compilation:c.id,ja_issue:'',ja_edit:''},'ja-index-title')}<p class="small muted">${esc(c.coverage)} · 关联 ${c.issue_ids?.length||0} 期 · ${c.selections?.length||0} 条选编</p></article>`).join('')||'<p class="muted">可先保存跨期整体译稿，再补充目次与原文对应。</p>'}</div></section><details class="ja-section"><summary>同刊资料、旧目录译稿与成果</summary>${await journalSourceResults(s)}${await sourceContentSection(s,'published','刊载资料')}${await sourceContentSection(s,'translations','原有目录译稿')}${await sourceContentSection(s,'outputs','中心成果')}</details><details class="ja-section"><summary>主办、出版与国别依据</summary>${jaFacts([['主办国别',countryText(s)],['出版机构国家',s.publisher_countries?.join(' / ')],['国际定位',internationalLabels[s.international_status]],['其他名称',s.aliases]])}${evidenceHtml(s.host_evidence)}${evidenceHtml(s.international_evidence)}</details>`;
  return `<article class="journal-archive" data-ja-source="${esc(s.id)}">${iid||rid||edit||historyKind?base:`<a class="back-link" data-action="source-directory-back" href="#sources?group=journal">返回期刊目录</a>`}${content}</article>`;
}
function jaCoverForm(cover={}){
  return `<details class="ja-edit-section"><summary>有据封面</summary><div class="ja-form-grid" data-ja-cover>${jaField('cover_file_id','已保存封面编号',cover.file_id)}<label class="field">上传封面图片（JPEG／PNG／WebP）<input type="file" data-ja-cover-upload accept="image/jpeg,image/png,image/webp"></label>${jaField('cover_attachment_id','已有资料附件编号',cover.attachment_id)}${jaField('cover_external_url','外部图片线索',cover.external_url,'url')}${jaText('cover_evidence','封面出处',cover.evidence)}${jaText('cover_note','封面用途及说明',cover.note)}${jaField('cover_issue_id','封面所对应的原刊卷期编号（可空）',cover.issue_id)}<label class="check-label"><input name="cover_illustrative" type="checkbox" ${cover.illustrative?'checked':''}>这是示意图，不代表当前卷期</label></div><p class="small muted">选择已保存图片、原有附件或外部线索之一；外部线索不会自动下载。</p></details>`;
}
function jaFormFrame(kind,title,value,body){return `<h1>${esc(title)}</h1><form data-ja-form="${kind}" data-version="${value.version||0}" class="ja-form">${body}<div class="form-error" role="alert"></div><div data-ja-conflict></div><div class="ja-savebar"><span data-ja-draft-status class="small muted">输入保留在当前页，保存后形成历史版本。</span>${jaButton('保存本机草稿','draft')}<button type="submit" class="button primary">保存${kind==='profile'?'期刊信息':kind==='issue'?'卷期与目次':'选编内容'}</button></div></form>`;}
function jaMetricRow(m={}){return `<fieldset data-ja-metric data-id="${m.id||crypto.randomUUID()}"><legend>影响因子记录</legend><div class="ja-form-grid">${jaSelect('kind','指标口径',jaMetricKinds,m.kind||'impact_factor')}${jaField('name','指标名称',m.name||'普通影响因子')}${jaField('value','数值（缺失留空，零值填0）',m.value)}${jaField('year','指标年度（未知留空）',m.year)}${jaField('released_year','资料发布年份',m.released_year)}${jaText('evidence','指标出处',m.evidence)}${jaText('raw_label','来源原始标注',m.raw_label)}${jaText('note','核对说明',m.note)}</div>${jaButton('移除此记录','remove-row')}</fieldset>`;}
function jaSubjectRow(x={}){return `<fieldset data-ja-subject><legend>学科分区</legend><div class="ja-form-grid">${jaSelect('level','学科层级',{major:'大类',minor:'小类'},x.level||'minor')}${jaField('original_name','学科原名',x.original_name)}${jaField('chinese_name','学科中文名',x.chinese_name)}${jaSelect('quartile','分区',{'':'待核实','1':'1区','2':'2区','3':'3区','4':'4区'},x.quartile||'')}${jaText('evidence','本学科依据（可沿用版本出处）',x.evidence)}</div>${jaButton('移除此学科','remove-row')}</fieldset>`;}
function jaRankingRow(r={}){return `<fieldset data-ja-ranking data-id="${r.id||crypto.randomUUID()}"><legend>中科院分区版本</legend><div class="ja-form-grid">${jaField('year','分区年度',r.year)}${jaField('edition','版本名称',r.edition)}${jaText('evidence','版本出处',r.evidence)}${jaText('raw_label','原始混合标注（不自动推导分区）',r.raw_label)}${jaText('note','核对说明',r.note)}</div><div data-ja-subjects>${(r.subjects||[]).map(jaSubjectRow).join('')}</div>${jaButton('添加学科','add-subject')}${jaButton('移除此版本','remove-row')}</fieldset>`;}
function jaProfileForm(s,p){return jaFormFrame('profile','期刊信息与年度指标',p,`<p class="small muted">${esc(s.name)} · 名称、官网、介绍及机构关系沿用原档案维护。</p><div class="ja-form-grid">${jaField('founded','创刊时间（保留实际精度）',p.founded)}${jaField('frequency','发行周期',p.frequency)}${jaField('print_issn','纸本 ISSN',p.print_issn)}${jaField('electronic_issn','电子 ISSN',p.electronic_issn)}${jaField('publisher_text','出版方原始名称',p.publisher_text)}${jaText('frequency_evidence','周期及变更依据',p.frequency_evidence)}${jaText('publisher_evidence','出版方依据',p.publisher_evidence)}${jaText('indexing','收录信息与来源原始表述',p.indexing)}</div>${s.issn?'<p class="notice">旧未分类标识继续保留：'+esc(s.issn)+'</p>':''}${jaCoverForm(p.cover)}<section class="ja-edit-section"><h2>影响因子</h2><div data-ja-metrics>${(p.metrics||[]).map(jaMetricRow).join('')}</div>${jaButton('添加影响因子记录','add-metric')}</section><section class="ja-edit-section"><h2>按版本保存中科院分区</h2><div data-ja-rankings>${(p.rankings||[]).map(jaRankingRow).join('')}</div>${jaButton('添加分区版本','add-ranking')}</section>`);}
function jaEntryRow(e={}){return `<fieldset data-ja-entry-row data-id="${e.id||crypto.randomUUID()}"><legend>目次条目</legend><div class="ja-form-grid">${jaField('title','原文题名 *',e.title)}${jaField('chinese_title','中文译题',e.chinese_title)}${jaField('authors','原始署名',e.authors)}${jaField('kind','原刊类型（文章／书评等）',e.kind)}${jaField('url','原文链接',e.url,'url')}${jaField('doi','DOI',e.doi)}${jaField('pages','页码',e.pages)}${jaField('article_number','文章编号',e.article_number)}${jaText('affiliations','原始署名单位',e.affiliations)}<details class="ja-wide"><summary>关联已有资料</summary>${jaField('record_id','所选资料编号',e.record_id)}<div class="row wrap"><input data-ja-record-query aria-label="查找已有资料" placeholder="按题名或 DOI 查找">${jaButton('查找已有资料','search-record')}</div><div data-ja-record-results></div>${jaText('relation_evidence','本期归属依据',e.relation_evidence)}${jaText('conflict_note','题录差异核对说明',e.conflict_note)}</details></div><div class="row wrap">${jaButton('上移','move-up')}${jaButton('下移','move-down')}${jaButton('移除此条目','remove-row')}</div></fieldset>`;}
function jaSectionRow(s={}){return `<fieldset data-ja-section data-id="${s.id||crypto.randomUUID()}"><legend>目次栏目（顺序保存）</legend>${jaField('section_title','栏目原名',s.title)}<div data-ja-entries>${(s.entries||[]).map(jaEntryRow).join('')}</div><div class="row wrap">${jaButton('添加目次条目','add-entry')}${jaButton('栏目上移','move-up')}${jaButton('栏目下移','move-down')}${jaButton('移除此栏目','remove-row')}</div></fieldset>`;}
function jaIssueForm(issue){return jaFormFrame('issue',issue.id?'维护原刊卷期与目次':'登记原刊卷期',issue,`<p class="notice">这里登记原刊出版标识。中心编译期次与编译日期另记，未知信息可以留空。</p><div class="ja-form-grid">${jaField('label','原刊卷期标识／已知范围',issue.label)}${jaField('year','原刊年份',issue.year)}${jaField('volume','原刊卷号',issue.volume)}${jaField('number','原刊期号',issue.number)}${jaField('published_on','原刊出版日期',issue.published_on)}${jaField('special_note','专刊／合刊说明',issue.special_note)}${jaSelect('coverage','目次覆盖',jaCoverage,issue.coverage||'unverified')}${jaField('checked_on','目次核对时间',issue.checked_on,'date')}${jaText('catalogue_evidence','原目次出处（完整目次必填）',issue.catalogue_evidence)}${jaText('coverage_note','覆盖范围与未明信息',issue.coverage_note)}</div>${jaCoverForm(issue.cover)}<section class="ja-edit-section"><h2>有序目次</h2><p class="small muted">可只保存题名、原始署名与链接；不会自动创建文章或确认人物。</p><div data-ja-sections>${(issue.sections||[]).map(jaSectionRow).join('')}</div>${jaButton('添加栏目','add-section')}</section>`);}
function jaSelectionRow(item={},issues=[]){
  const basis=item.basis||{},entries=issues.flatMap(i=>(i.sections||[]).flatMap(s=>s.entries.map(e=>({issue:i,entry:e}))));
  return `<fieldset data-ja-selection data-id="${item.id||crypto.randomUUID()}"><legend>选编内容</legend><div class="ja-form-grid">${jaSelect('entry_key','所选目次',Object.fromEntries(entries.map(x=>[x.issue.id+':'+x.entry.id,(x.issue.label||x.issue.year)+' · '+x.entry.title])),item.issue_id+':'+item.entry_id)}${jaSelect('kind','内容类别',jaKinds,item.kind||'editor_summary')}${jaField('compiler','编译／录入署名 *',item.compiler)}${richEditor('selection_'+(item.id||crypto.randomUUID()).replaceAll('-',''),'中文／原文内容',item.body_html)}<details class="ja-wide" open><summary>采用的原文版本与位置</summary><div class="ja-form-grid">${jaField('record_id','所据入库资料编号',basis.record_id)}${jaField('record_version','所据资料版本',basis.record_version||'','number')}${jaField('url','原文地址（未入库时必填）',basis.url,'url')}${jaField('source_version','来源／样稿版本',basis.source_version)}${jaText('locator','原文位置',basis.locator)}${jaText('original_abstract','未入库原文摘要（标为摘要译文时需要）',item.original_abstract)}</div></details></div>${jaButton('移除此选编','remove-row')}</fieldset>`;
}
function jaCompilationForm(record,doc,issues){return jaFormFrame('compilation','选编内容与原文依据',doc,`<h2>${esc(record.title)}</h2><p class="small muted">${esc(record.coverage)} · ${record.kind==='directory_translation'?'全体成员共编':'按原有作者授权编辑'} · 正文版本 ${record.version}</p><div class="ja-form-grid">${jaField('compiled_on','编译时间',doc.compiled_on)}${jaField('released_on','中心发布日期',doc.released_on)}${jaText('credits','编译、审校等署名（不改变账号授权）',doc.credits)}${jaText('coverage_note','补充覆盖说明',doc.coverage_note)}</div><fieldset class="ja-issue-choices"><legend>关联原刊卷期（可跨期）</legend>${issues.map(i=>`<label class="check-label"><input type="checkbox" name="issue_ids" value="${i.id}" ${(doc.issue_ids||[]).includes(i.id)?'checked':''}>${esc(i.label||i.year||i.id)}</label>`).join('')||'<p>可以先保存整体译稿，之后登记卷期。</p>'}</fieldset><section class="ja-edit-section"><h2>逐条编译</h2><div data-ja-selections>${(doc.selections||[]).filter(i=>!i.unavailable).map(i=>jaSelectionRow(i,issues)).join('')}</div>${jaButton('添加选编内容','add-selection')}</section>`);}
function jaNewCompilationForm(){return `<h1>新建目录译稿</h1><form data-ja-form="new-compilation" class="ja-form"><div class="ja-form-grid">${jaField('title','译稿题名 *')}${jaField('authors','编译者署名 *')}${jaField('coverage','年份／卷期／跨期覆盖范围 *')}${richEditor('body_html','整体译稿（可先写，之后补齐条目）')}</div><div class="form-error" role="alert"></div><button class="button primary" type="submit">保存整体目录译稿</button></form>`;}
function jaCollect(root){const result={};for(const el of root.querySelectorAll(':scope > .ja-form-grid > .field > input,:scope > .ja-form-grid > .field > textarea,:scope > .ja-form-grid > .field > select,:scope > .field > input'))result[el.name]=el.value;return result;}
function jaCollectCover(form){const box=form.querySelector('[data-ja-cover]');if(!box)return {};const data={};for(const el of box.querySelectorAll('[name]'))data[el.name.replace('cover_','')]=el.type==='checkbox'?el.checked:el.value;return ['file_id','attachment_id','external_url'].some(k=>data[k])?data:{};}
function jaPayload(form){
  syncRichForm(form);const kind=form.dataset.jaForm,data={...jaCollect(form),version:Number(form.dataset.version)};
  if(kind==='new-compilation')return {...Object.fromEntries(new FormData(form)),kind:'directory_translation',related_source_ids:[jaContext.s.id],visibility:'shared'};
  if(kind==='profile'){
    data.metrics=[...form.querySelectorAll('[data-ja-metric]')].map(row=>({...jaCollect(row),id:row.dataset.id}));
    data.rankings=[...form.querySelectorAll('[data-ja-ranking]')].map(row=>({...jaCollect(row),id:row.dataset.id,subjects:[...row.querySelectorAll('[data-ja-subject]')].map(jaCollect)}));
  }else if(kind==='issue')data.sections=[...form.querySelectorAll('[data-ja-section]')].map(section=>({id:section.dataset.id,title:section.querySelector('[name=section_title]').value,entries:[...section.querySelectorAll('[data-ja-entry-row]')].map(row=>({...Object.fromEntries([...row.querySelectorAll('[name]')].map(el=>[el.name,el.value])),id:row.dataset.id}))}));
  else if(kind==='compilation'){
    data.record_version=jaContext.record.version;data.issue_ids=[...form.querySelectorAll('[name=issue_ids]:checked')].map(el=>el.value);
    data.selections=[...form.querySelectorAll('[data-ja-selection]')].map(row=>{const values=Object.fromEntries([...row.querySelectorAll('[name]')].map(el=>[el.name,el.value]));const [issue_id,entry_id]=values.entry_key.split(':');return {id:row.dataset.id,issue_id,entry_id,kind:values.kind,compiler:values.compiler,original_abstract:values.original_abstract,body_html:row.querySelector('[data-rich-field] textarea').value,basis:{record_id:values.record_id,url:values.url,source_version:values.source_version,locator:values.locator,record_version:values.record_version?Number(values.record_version):null}};});
  }
  if(kind==='profile'||kind==='issue')data.cover=jaCollectCover(form);
  return data;
}
function jaDraftKey(){return [state.me?.id,jaContext?.s.id,state.params.get('ja_edit'),state.params.get('ja_issue')||state.params.get('ja_compilation')||'new'].join(':');}
function jaRememberDraft(form){try{const payload=jaPayload(form);sessionStorage.setItem('journal-draft:'+jaDraftKey(),JSON.stringify(payload));jaDrafts.set(jaDraftKey(),payload);form.querySelector('[data-ja-draft-status]').textContent='草稿已保存在当前浏览器会话';return true;}catch{const status=form.querySelector('[data-ja-draft-status]');if(status)status.textContent='草稿尚未保存，请保持本页打开。';return false;}}
function jaFormReady(){
  const form=document.querySelector('[data-ja-form]');if(!form)return;
  form.dataset.jaAccount=state.me.id;form._jaRecordVersion=jaContext.record?.version;
  let draft=jaDrafts.get(jaDraftKey());try{draft=draft||JSON.parse(sessionStorage.getItem('journal-draft:'+jaDraftKey())||'null');}catch{}
  if(draft){const bar=document.createElement('div');bar.className='notice';bar.innerHTML='有一份本机草稿。'+jaButton('恢复本机草稿','restore-draft')+jaButton('舍弃本机草稿','discard-draft');form.prepend(bar);form._jaDraft=draft;}
}
document.addEventListener('click',async event=>{
  const link=event.target.closest('[data-ja-link]');if(link){const form=document.querySelector('[data-ja-form]');if(form?.dataset.saving==='true'){event.preventDefault();return;}if(form&&!jaRememberDraft(form)){event.preventDefault();return;}jaPositions.set(location.hash,{account:state.me.id,y:scrollY});}
  const b=event.target.closest('[data-ja]');if(!b)return;
  const action=b.dataset.ja,form=b.closest('form');
  if(form?.dataset.saving==='true')return;
  try{
    if(action==='add-metric')form.querySelector('[data-ja-metrics]').insertAdjacentHTML('beforeend',jaMetricRow());
    else if(action==='add-ranking')form.querySelector('[data-ja-rankings]').insertAdjacentHTML('beforeend',jaRankingRow());
    else if(action==='add-subject')b.closest('[data-ja-ranking]').querySelector('[data-ja-subjects]').insertAdjacentHTML('beforeend',jaSubjectRow());
    else if(action==='add-section')form.querySelector('[data-ja-sections]').insertAdjacentHTML('beforeend',jaSectionRow());
    else if(action==='add-entry')b.closest('[data-ja-section]').querySelector('[data-ja-entries]').insertAdjacentHTML('beforeend',jaEntryRow());
    else if(action==='add-selection')form.querySelector('[data-ja-selections]').insertAdjacentHTML('beforeend',jaSelectionRow({},jaContext.data.issues));
    else if(action==='remove-row')b.closest('fieldset').remove();
    else if(action==='move-up'||action==='move-down'){const row=b.closest('fieldset'),other=action==='move-up'?row.previousElementSibling:row.nextElementSibling;if(other)action==='move-up'?other.before(row):other.after(row);}
    else if(action==='draft')jaRememberDraft(form);
    else if(action==='restore-draft'){
      const d=form._jaDraft,kind=form.dataset.jaForm;
      const html=kind==='profile'?jaProfileForm(jaContext.s,d):kind==='issue'?jaIssueForm(d):kind==='compilation'?jaCompilationForm(jaContext.record,d,jaContext.data.issues):'';
      if(html){form.closest('.journal-archive').innerHTML=jaLink('返回期刊档案',{ja_edit:'',ja_issue:'',ja_compilation:''},'back-link')+html;const restored=document.querySelector('[data-ja-form]');restored.dataset.jaAccount=state.me.id;restored._jaDirty=true;}
    }else if(action==='discard-draft'){sessionStorage.removeItem('journal-draft:'+jaDraftKey());jaDrafts.delete(jaDraftKey());b.parentElement.remove();}
    else if(action==='read-record'){jaPositions.set(location.hash,{account:state.me.id,y:scrollY,entry:b.dataset.entry});await openRecord(b.dataset.id);}
    else if(action==='select-entry'){
      const choices=jaContext.data.compilations.filter(c=>c.can_edit);
      const links=choices.map(c=>jaLink(c.title,{ja_compilation:c.id,ja_issue:'',ja_edit:'compilation',ja_entry:b.dataset.entry},'detail-link')).join('');
      modal('选择目录译稿',links||'<p>请先在期刊档案建立或接续一份目录译稿。</p>');
    }else if(action==='search-record'){
      const row=b.closest('[data-ja-entry-row]'),query=row.querySelector('[data-ja-record-query]').value.trim();
      if(!query)throw new Error('请输入题名或 DOI。');const account=state.me.id;
      const data=await api('/api/records?'+new URLSearchParams({q:query,size:20}));if(!row.isConnected||account!==state.me?.id)return;
      row.querySelector('[data-ja-record-results]').innerHTML=data.items.filter(r=>!isResearchContent(r.kind)).map(r=>jaButton(r.title+' · '+r.id,'choose-record',`data-id="${esc(r.id)}"`)).join('')||'<p>未找到可关联的原始资料；可先保存未入库目次。</p>';
    }else if(action==='choose-record'){const row=b.closest('[data-ja-entry-row]');row.querySelector('[name=record_id]').value=b.dataset.id;row.querySelector('[data-ja-record-results]').textContent='已选：'+b.textContent;}
    else if(action==='load-latest'){
      const kind=form.dataset.jaForm,base='/api/journals/'+encodeURIComponent(jaContext.s.id);
      const latest=kind==='profile'?(await api(base)).profile:kind==='issue'?await api(base+'/issues/'+jaContext.issue.id):await api(base+'/compilations/'+jaContext.record.id);
      form.querySelector('[data-ja-conflict]').innerHTML='<details open><summary>最新保存内容（当前输入继续保留）</summary>'+(kind==='profile'?jaProfileRead(jaContext.s,latest):kind==='issue'?jaIssueRead(jaContext.s,latest,jaContext.data.profile,true):jaCompilationRead(jaContext.record,latest,true))+'</details><p>逐项对照后，可以将当前输入作为新版本保存。</p>'+jaButton('我已对照，继续编辑当前输入','accept-latest',`data-version="${latest.version}" data-record-version="${latest.record_version||''}"`);
    }else if(action==='accept-latest'){form.dataset.version=b.dataset.version;if(b.dataset.recordVersion)jaContext.record.version=Number(b.dataset.recordVersion);delete form.dataset.conflict;form.querySelector('[data-ja-conflict]').innerHTML='<p class="notice">已对照；下一次保存会形成新版本，旧稿继续留存。</p>';}
  }catch(error){const target=form?.querySelector('.form-error');if(target)target.textContent=error.message;else toast(error.message);}
});
document.addEventListener('input',event=>{const form=event.target.closest('[data-ja-form]');if(form){form._jaDirty=true;jaRememberDraft(form);}});
document.addEventListener('change',event=>{const form=event.target.closest('[data-ja-form]');if(form){form._jaDirty=true;jaRememberDraft(form);}});
document.addEventListener('submit',async event=>{
  const form=event.target.closest('[data-ja-form]');if(!form)return;event.preventDefault();
  if(form.dataset.saving==='true'||form.dataset.conflict)return;
  if(form.dataset.jaAccount!==state.me?.id)return;
  form.dataset.saving='true';const button=form.querySelector('[type=submit]');button.disabled=true;
  const account=state.me.id,hash=location.hash,error=form.querySelector('.form-error');error.textContent='';
  try{
    const kind=form.dataset.jaForm,data=jaPayload(form),base='/api/journals/'+encodeURIComponent(jaContext.s.id);
    const upload=form.querySelector('[data-ja-cover-upload]')?.files[0];
    if(upload){const files=new FormData();files.set('file',upload);const cover=await api(base+'/covers',{method:'POST',body:files});if(!form.isConnected||account!==state.me?.id)return;data.cover={...data.cover,file_id:cover.id,attachment_id:'',external_url:''};form.querySelector('[name=cover_file_id]').value=cover.id;}
    let result;
    if(kind==='new-compilation'){
      result=await api('/api/records',{method:'POST',body:data});
    }else{
      const path=kind==='profile'?'/profile':kind==='issue'?'/issues'+(jaContext.issue?'/'+jaContext.issue.id:''):'/compilations/'+jaContext.record.id;
      result=await api(base+path,{method:kind==='issue'&&!jaContext.issue?'POST':'PUT',body:data});
    }
    if(!form.isConnected||account!==state.me?.id||hash!==location.hash)return;
    sessionStorage.removeItem('journal-draft:'+jaDraftKey());jaDrafts.delete(jaDraftKey());form._jaDirty=false;
    toast('已保存，历史版本继续保留');
    const changes={ja_edit:'',ja_entry:''};if(kind==='issue')changes.ja_issue=result.id;if(kind==='new-compilation'){changes.ja_compilation=result.id;changes.ja_edit='compilation';}
    const target=new URL(jaUrl(changes),location.href);history.pushState({},'',target.hash);await route();
  }catch(e){
    if(account!==state.me?.id||!form.isConnected)return;
    error.textContent=e.message;jaRememberDraft(form);
    if(e.status===409){form.dataset.conflict='true';form.querySelector('[data-ja-conflict]').innerHTML=(e.message.includes('题录')?'<p class="notice">当前题名、署名、顺序与链接均已保留。请核对关联资料，在“题录差异核对说明”中记录依据后继续。</p>'+jaButton('继续核对当前输入','accept-latest',`data-version="${form.dataset.version}"`):jaButton('读取最新版本并对照，保留当前输入','load-latest'));}
  }finally{if(form.isConnected){delete form.dataset.saving;button.disabled=false;}}
});
function journalArchiveMounted(){
  if(!document.querySelector('.journal-archive'))return;jaFormReady();
  const selected=state.params.get('ja_entry');
  if(selected&&state.params.get('ja_edit')==='compilation'){
    const issue=jaContext.data.issues.find(i=>i.sections.some(s=>s.entries.some(e=>e.id===selected)));
    const entry=issue?.sections.flatMap(s=>s.entries).find(e=>e.id===selected),form=document.querySelector('[data-ja-form]');
    if(issue&&entry&&form){form.querySelector('[data-ja-selections]').insertAdjacentHTML('beforeend',jaSelectionRow({issue_id:issue.id,entry_id:entry.id,basis:{record_id:entry.record_id,record_version:entry.record?.version}},jaContext.data.issues));const choice=form.querySelector(`[name=issue_ids][value="${issue.id}"]`);if(choice)choice.checked=true;}
  }
  const pos=jaPositions.get(location.hash);if(pos?.account===state.me.id)requestAnimationFrame(()=>scrollTo(0,pos.y));
}
window.addEventListener('beforeunload',event=>{const form=document.querySelector('[data-ja-form]');if(form?._jaDirty&&!jaRememberDraft(form)){event.preventDefault();event.returnValue='';}});
