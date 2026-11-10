'use strict';

// The research workbench owns composition; existing modules own validated writes,
// file identities, permission checks, conflict recovery and record editing.
const workbenchState={account:null,selected:null,topic:null,workflow:null,candidates:null};
const workbenchArchiveJournal=journalWorkPage;

function workbenchBrand(){return '<a class="workbench-brand" href="#collaboration" aria-label="北外中东欧研究中心内部使用首页"><strong>北外中东欧研究中心<wbr>内部使用</strong></a>';}
function workbenchNav(page,label){const n=navs.find(n=>n[0]===page);return nav([page,n?.[1]||'folder',label||n?.[2]||page]);}
function workbenchShell(){
  document.body.classList.remove('navigation-open','workbench-mobile-detail');
  const maintenance=state.me.role==='admin'&&isMaintenancePage();
  const group=(title,items)=>'<section class="nav-group"><h2 class="nav-caption">'+title+'</h2>'+items.join('')+'</section>';
  const navigation=maintenance?group('资料维护',maintenanceNavs.map(nav))+group('研究工作',[...(state.researchReturnAvailable?['<button class="nav-item workbench-return-identity" data-action="trial-return">返回研究身份</button>']:[]),workbenchNav('collaboration','返回研究界面')]):group('研究中心',[workbenchNav('collaboration'),workbenchNav('compilations'),workbenchNav('journal-results','期刊成果'),workbenchNav('library','资料检索'),workbenchNav('sources','来源与作者档案')])+group('我的工作',[workbenchNav('collections'),workbenchNav('favorites','收藏'),workbenchNav('personal','个人空间')])+(state.collections.length?group('最近的资料夹',state.collections.slice(0,4).map(c=>'<button class="nav-item workbench-collection" data-action="open-collection" data-id="'+esc(c.id)+'">'+icon('folder')+'<span>'+esc(c.name)+'</span></button>')):'')+(state.me.role==='admin'?group('资料管理',[workbenchNav('system','维护界面')]):'');
  document.querySelector('#app').innerHTML='<header class="topbar workbench-topbar">'+workbenchBrand()+'<div class="workbench-account">'+(state.me.temporary?'<span class="workbench-mode">临时体验</span>':'')+(maintenance?'<span class="workbench-mode">维护界面</span>':'')+(state.researchReturnAvailable?'<button class="workbench-account-link" data-action="trial-return">返回研究身份</button>':'')+'<button class="workbench-account-link" data-action="nav" data-id="personal">'+esc(state.me.name)+'</button><button class="icon-button" title="退出登录" aria-label="退出登录" data-action="logout">'+icon('logout')+'</button><button class="button navigation-toggle" data-action="navigation-open" aria-expanded="false" aria-controls="platform-navigation" aria-haspopup="dialog">打开导航</button></div></header><button class="navigation-backdrop" data-action="navigation-close" aria-label="关闭导航遮罩" tabindex="-1"></button><aside class="sidebar" id="platform-navigation"><button class="button navigation-close" data-action="navigation-close">关闭导航 '+icon('close')+'</button><nav aria-label="主导航">'+navigation+'</nav></aside><div class="main"><main class="content" id="content"><div class="boot" role="status">正在读取资料…</div></main></div>';
  setNavigation(false,false);
}

function workbenchParams(overrides={}){const p=new URLSearchParams(state.params);p.delete('return');for(const [k,v] of Object.entries(overrides)){if(v===null||v==='')p.delete(k);else p.set(k,v);}return p;}
function workbenchQuery(products){const p=workbenchParams();for(const key of ['id','tab','assignment','full','selected_business'])p.delete(key);p.set('view',products?'products':'works');if(isMaintenancePage())p.set('scope','maintenance');else if(!p.has('scope'))p.set('scope',products||state.me?.temporary?'all':'participating');if(p.get('business')==='all')p.delete('business');return p;}
function workbenchWorkLink(w,label,cls='title-button'){return '<button class="'+cls+'" data-action="workbench-select" data-id="'+esc(w.id)+'" data-business="'+w.business+'">'+esc(label)+'</button>';}
function workbenchWorkRow(w,selected,products){
  const meta=[w.business==='topic'?(w.lifecycle_state==='closed'?'已结束 · ':'')+(w.stage==='compilation'?'第二阶段：编译':'第一阶段：选题'):'期刊编译'];
  if(w.business==='journal'&&w.coverage)meta.push(w.coverage);
  if(w.business==='topic'&&w.lead_name)meta.push('负责人：'+w.lead_name);
  if(w.business==='topic'&&w.due_on)meta.push('约定提交 '+w.due_on);
  let status=w.trial_sample?'示例 · 只读':w.products.length?'已有成果 '+w.products.length+' 份':w.leading?'我负责':w.participating?'我参与':'可查阅';
  return '<article class="workbench-row '+(selected?'workbench-selected':'')+'" data-object-kind="work" data-object-id="'+esc(w.id)+'" data-object-business="'+esc(w.business)+'" data-work-id="'+esc(w.id)+'" '+(selected?'aria-current="true"':'')+'><div class="workbench-row-top"><span class="object-kind-mark">'+icon(w.business==='topic'?'folder':'book')+'</span><div class="workbench-row-title">'+workbenchWorkLink(w,w.title)+'</div><span class="badge '+(selected&&status.startsWith('待审稿')?'pending':'neutral')+'">'+esc(status)+'</span>'+objectActions.more('更多工作操作')+'</div><div class="workbench-row-meta">'+meta.map(x=>'<span>'+esc(x)+'</span>').join('')+'</div><div class="workbench-row-secondary"><span>'+esc(w.participant_names.join('、')||'参与信息未登记')+'</span><span>最近交接 '+dateTime(w.updated_at)+'</span></div>'+(products?'<div class="workbench-product-rows">'+w.products.map(p=>workProductRow(p,w)).join('')+'</div>':'')+'</article>';
}
function workbenchTopicProducts(t,w){
  const card=f=>'<article data-workbench-final="'+esc(f.id)+'"><h3>'+esc(f.title)+'</h3>'+topicReviewFile(f,'下载定稿 v'+f.version)+topicFinalDecision(f)+'</article>';
  const groups=w.assignments.filter(a=>a.finals?.length).map(a=>{
    const finals=[...a.finals].sort((a,b)=>b.version-a.version);
    return card(finals[0])+(finals.length>1?'<details><summary>此前 '+(finals.length-1)+' 版单篇定稿</summary>'+finals.slice(1).map(card).join('')+'</details>':'');
  });
  return '<section class="workbench-section" data-topic-single-finals><h2>单篇定稿</h2>'+(groups.length?groups.join(''):'<p class="muted">尚无已确认的单篇定稿。</p>')+'</section>'+topicFinalSections(t,w);
}
async function workbenchTopic(tid){
  const account=state.me?.id,load=state.loadId;
  const t=await api('/api/collaboration/topics/'+encodeURIComponent(tid)+'/handoffs');
  if(account!==state.me?.id||load!==state.loadId)throw new Error('工作查找已更新。');
  Object.assign(workbenchState,{topic:t,board:t});
  const tab=['candidates','selection'].includes(state.params.get('tab'))?'selection':['manuscripts','compilation'].includes(state.params.get('tab'))?'compilation':t.stage;
  const role=t.trial_sample?'示例 · 只读':t.is_lead?'负责人':t.is_participant?'参与成员':'查阅成员';
  const tabs='<nav class="workbench-tabs" aria-label="查看阶段材料">'+[['selection','选题材料'],['compilation','编译材料']].map(([key,label])=>'<button data-action="workbench-tab" data-id="'+key+'" '+(tab===key?'aria-current="page"':'')+'>'+label+'</button>').join('')+'</nav>';
  const controls=(t.can_enter_compilation?linkButton('进入编译','topic-review-enter',t.id,'button primary'):'')+(t.can_reopen?linkButton('重开本期','topic-closure-reopen',t.id,'button primary'):'');
  return '<article data-collaboration-topic="'+esc(t.id)+'"><h1 class="workbench-detail-title">'+esc(t.theme)+'</h1><p class="workbench-detail-meta">'+(t.lifecycle_state==='closed'?'已结束':t.stage==='selection'?'选题阶段':'编译阶段')+' · 当前身份：'+role+' · 负责人：'+esc(t.lead_name)+'</p>'+ (controls?'<div class="row wrap workbench-primary-actions">'+controls+'</div>':'')+tabs+handoffMaterials(t,tab)+'<details class="workbench-actions"><summary>本期信息与收尾</summary><p>参与成员：'+t.participants.map(p=>esc(p.name)).join('、')+'</p><div class="row wrap">'+(t.can_manage?linkButton('维护本期信息','collaboration-edit',t.id):'')+(t.can_end?linkButton('结束本期','topic-closure-end',t.id):'')+'</div></details><details class="workbench-actions"><summary>材料包与历史</summary>'+workMaterialTools('topic',t.id)+topicStageHistory(t)+topicClosureHistory(t)+linkButton('旧会议、定稿与汇总','handoff-legacy',t.id)+'</details></article>';
}
async function workbenchJournal(id){
  const html=await workbenchArchiveJournal(id),root=document.createElement('div');root.innerHTML=html;
  root.querySelector('[data-action="work-return"],[data-action="journal-home"]')?.remove();
  root.querySelector('.page-heading')?.insertAdjacentHTML('beforebegin','<div class="workbench-detail-context"><button class="link-button" data-action="workbench-full">完整档案</button></div>');
  return root.innerHTML;
}
async function workbenchWorkspacePage(products=false){
  const account=state.me?.id,load=state.loadId,p=new URLSearchParams(state.params),query=workbenchQuery(products),data=await api('/api/collaboration/works?'+query);
  if(account!==state.me?.id||load!==state.loadId)throw new Error('工作查找已更新。');
  if(workbenchState.account!==state.me.id){Object.assign(workbenchState,{account:state.me.id,selected:null,topic:null,workflow:null,candidates:null});}
  const requested=p.get('id'),selected=data.items.find(w=>w.id===requested)||(!requested?data.items[0]:null),business=selected?.business||p.get('selected_business')||p.get('business')||'topic',sid=requested||selected?.id;
  Object.assign(workbenchState,{selected:sid,topic:null,workflow:null,candidates:null});
  let detail='';
  if(sid){try{detail=business==='journal'?await workbenchJournal(sid):await workbenchTopic(sid);}catch(error){detail='<div class="notice error" role="alert"><h2>暂时无法读取所选工作</h2><p>'+esc(error.message)+'</p><p>请返回全部可读查找示例，或开启自己的练习主题。</p>'+linkButton('返回全部可读','work-reset')+linkButton('重新读取','work-retry')+'</div>';}}
  else detail=empty('选择工作后接续材料','打开一项工作，在此查看原件、具体版本及交接。','folder');
  if(account!==state.me?.id||load!==state.loadId)throw new Error('工作查找已更新。');
  const resultHub=products?await journalResultsHub():'';
  const journalHistory='<details class="workbench-legacy"><summary>旧期刊工作</summary><div class="row wrap">'+linkButton('查阅旧期刊工作','journal-home')+linkButton('新建期刊工作','journal-new')+'</div></details>';
  const scope=query.get('scope'),tabs=isMaintenancePage()?[['maintenance','维护查阅']]:[['participating','我参与'],['leading','我负责'],['all','全部可读']];
  const actions=products?linkButton('导入成品','import-output','','button primary'):(data.can_create?linkButton('开启一期主题','collaboration-new','','button primary'):'');
  const actionMenu=actions?'<details class="workbench-new"><summary>'+(products?'提交成果':'发起工作')+'</summary><div class="stack">'+actions+'</div></details>':'';
  return trialWelcome(!!requested)+'<section class="workbench '+(p.get('id')?'workbench-has-selection':'')+'" data-work-discovery><section class="workbench-index"><div class="workbench-index-head"><div class="page-heading between"><div><h1>'+(products?'中心成果':isMaintenancePage()?'协作维护查阅':query.get('business')==='journal'?'期刊编译':'编译协作')+'</h1></div>'+actionMenu+'</div>'+resultHub+(tabs.length>1?'<nav class="workbench-tabs" aria-label="工作范围">'+tabs.map(([value,label])=>'<button data-action="work-filter" data-key="scope" data-id="'+value+'" '+(scope===value?'aria-current="page" aria-pressed="true"':'aria-pressed="false"')+'>'+label+'</button>').join('')+'</nav>':'')+'<form data-work-search><div class="workbench-search"><label class="sr-only" for="workbench-query">主题或期刊</label><input id="workbench-query" type="search" name="q" value="'+esc(p.get('q'))+'" placeholder="查找工作标题"><button class="button" type="submit">查找工作</button><select aria-label="编译业务" data-workbench-business>'+[['all','全部业务'],['topic','主题编译'],['journal','期刊编译']].map(([value,label])=>'<option value="'+value+'" '+((query.get('business')||'all')===value?'selected':'')+'>'+label+'</option>').join('')+'</select></div><details class="workbench-more"><summary>分工、参与人与最近活动日期</summary><div class="form-grid"><label class="field">国家分工<input name="country" value="'+esc(p.get('country'))+'"></label><label class="field">参与人<input name="participant" value="'+esc(p.get('participant'))+'"></label><label class="field">最近活动起始日<input type="date" name="from" value="'+esc(p.get('from'))+'"></label><label class="field">最近活动截止日<input type="date" name="to" value="'+esc(p.get('to'))+'"></label></div><button class="button tiny" type="submit">应用筛选</button></details><div class="form-error" role="alert"></div></form></div><div class="workbench-list-head"><span>共 '+data.total+' 项工作 · 最近活动在前</span>'+linkButton('重置查找','work-reset')+'</div><div class="workbench-list">'+data.items.map(w=>workbenchWorkRow(w,w.id===sid,products)).join('')+(data.total?'':workEmptyState(products,p.get('business')||'all'))+'</div>'+(products?'<div class="workbench-legacy">'+linkButton('独立成果与跨期译稿','work-legacy')+linkButton('查阅全部资料与旧研究积累','work-old-content')+'</div>':'')+journalHistory+'</section><aside class="workbench-detail" aria-label="工作交接详情"><button class="button workbench-back" data-action="workbench-back">← 返回'+(products?'中心成果':isMaintenancePage()?'协作维护查阅':'编译协作')+'</button>'+detail+'</aside></section>';
}


// Capture only composition changes; validated write handlers continue unchanged.
document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-action]');if(!b)return;const a=b.dataset.action;
  if(b.closest('.workbench'))workbenchRemember();
  const navigate=(overrides)=>go(state.page,workbenchParams(overrides));
  if(a==='workbench-select'){event.preventDefault();event.stopImmediatePropagation();navigate({id:b.dataset.id,selected_business:b.dataset.business,tab:'',assignment:''});}
  else if(a==='workbench-tab'){event.preventDefault();event.stopImmediatePropagation();navigate({id:workbenchState.selected,selected_business:workbenchState.topic?'topic':'journal',tab:b.dataset.id});}
  else if(a==='workbench-assignment'){event.preventDefault();event.stopImmediatePropagation();navigate({id:workbenchState.selected,tab:'manuscripts',assignment:b.dataset.id});}
  else if(a==='workbench-full'){event.preventDefault();event.stopImmediatePropagation();go('collaboration',{id:workbenchState.selected,business:workbenchState.topic?'topic':'journal',full:'1',return:location.hash});}
  else if(a==='workbench-back'){event.preventDefault();event.stopImmediatePropagation();navigate({id:'',selected_business:'',tab:'',assignment:''});}
  else if(a==='work-filter'&&b.closest('.workbench')){event.preventDefault();event.stopImmediatePropagation();navigate({[b.dataset.key]:b.dataset.id,id:'',selected_business:'',tab:'',assignment:''});}
  else if(a==='collaboration-upload-open'&&b.closest('.workbench')&&state.params.get('tab')!=='candidates'){
    event.preventDefault();event.stopImmediatePropagation();await go(state.page,workbenchParams({id:workbenchState.selected,tab:'candidates'}));const panel=document.querySelector('[data-collaboration-upload]');if(panel){panel.open=true;panel.querySelector('[type=file]').focus();}
  }else if(a==='topic-review-mine'&&b.closest('.workbench')&&workbenchState.workflow){
    const mine=workbenchState.workflow.assignments.find(a=>a.can_submit);if(mine){event.preventDefault();event.stopImmediatePropagation();await navigate({id:workbenchState.selected,tab:'manuscripts',assignment:mine.id});const panel=document.querySelector('[data-assignment-card] [data-topic-handoff]');if(panel){panel.open=true;panel.querySelector('textarea')?.focus();}}
  }
},true);
document.addEventListener('change',event=>{if(event.target.matches('[data-workbench-business]'))go(state.page,workbenchParams({business:event.target.value,id:'',selected_business:'',tab:'',assignment:''}));});

function workbenchSourceCard(s){
  const meta=isInstitution(s)?[(s.country_labels||[]).join(' / ')||s.country,...(s.institution_types||[]).map(t=>institutionTypes[t]||t)]:s.kind==='journal'?[(s.country_labels||[]).length?'主办国别：'+countryText(s):'',s.international_status&&s.international_status!=='unknown'?'国际定位：'+(internationalLabels[s.international_status]||s.international_status):'']:[serialTypes[s.classification]||''];
  const title=s.kind==='portal'?linkButton(esc(s.name),'source-preview',s.id,'title-button'):'<a class="title-button" href="'+sourceHref(s.id)+'">'+esc(s.name)+'</a>';
  return '<article class="workbench-source-row" data-object-kind="source" data-object-id="'+esc(s.id)+'"><div class="workbench-source-main"><span class="object-kind-mark">'+icon(isInstitution(s)?'source':'book')+'</span><div class="workbench-source-copy"><h2>'+title+'</h2>'+(s.original_name&&s.original_name!==s.name?'<p class="muted">'+esc(s.original_name)+'</p>':'')+'<div class="workbench-source-meta">'+meta.filter(Boolean).map(x=>'<span>'+esc(x)+'</span>').join('')+'</div>'+(s.search_snippet?'<p class="search-snippet">'+esc(s.search_snippet)+'</p>':'')+'</div></div><div class="workbench-source-side"><div class="row wrap"><span class="badge neutral">'+sourceLabel(s)+'</span>'+badge(s.status)+'</div><span class="muted">'+scopeLabel(s.scope_status)+'</span><div class="row">'+linkButton('快速预览','source-preview',s.id,'link-button object-open')+objectActions.more('更多来源操作')+'</div></div></article>';
};
async function workbenchPeoplePage(){
  const result=await api('/api/people?'+state.params),query=state.params.get('q')||'';
  const filterNames={q:'关键词',employment_country:'任职机构国别',subject_country:'作品研究对象国'};
  const applied=Object.entries(filterNames).filter(([key])=>state.params.get(key));
  return `<section class="people-page"><div class="page-heading between wrap"><div><h1>作者目录</h1><p>整理资料来源中的作者信息；平台成员账号在个人空间与维护界面管理。</p></div>${linkButton(icon('plus')+' 添加作者档案','new-person','','button primary')}</div>
    <form data-form="people-search" class="people-search"><div class="toolbar"><div class="search-input">${icon('search')}<input name="q" type="search" aria-label="搜索作者" placeholder="原名、中文名或别名" value="${esc(query)}"></div><button class="button primary" type="submit">查找</button>${linkButton('清除筛选','people-clear')}</div><div class="people-country-filters">${readingFacet(result,'employment_country','任职机构国别')}${readingFacet(result,'subject_country','作品研究对象国')}</div></form>${applied.length?`<div class="person-applied" aria-label="已应用的作者搜索"><span>已用条件</span>${applied.map(([key,label])=>`<button class="ux-filter-chip" data-action="people-clear-filter" data-id="${key}" aria-label="移除${label}">${esc(label)}：${esc(key==='q'?query:state.params.get(key).split('|').map(value=>value==='__unknown__'?(key==='employment_country'?'任职国别待补充':'无可见已确认作品研究对象'):countryLabel(value)).join('、'))} <span aria-hidden="true">×</span></button>`).join('')}</div>`:''}
    <div class="results-head"><p>共 ${result.total} 位人物</p></div><div class="workbench-people-list">${result.items.map(p=>`<article class="workbench-person-row" data-object-kind="person" data-object-id="${esc(p.id)}">${personAvatar(p,true)}<div><h2><a href="#people?${esc(parameters({id:p.id}))}">${esc(p.name)}</a></h2>${personNames(p).length?`<p class="person-names">${esc(personNames(p).join(' · '))}</p>`:''}<p class="person-summary">${esc(personHint(p)||'介绍待补充')}</p></div><div class="workbench-person-actions"><p class="workbench-person-version muted">版本 ${p.version}</p><a class="object-open" href="#people?id=${encodeURIComponent(p.id)}">打开档案</a>${objectActions.more('更多人物操作')}</div></article>`).join('')||empty(applied.length?'未找到符合条件的人物':'还没有人物档案','','person')+(applied.length?linkButton('清除筛选','people-clear'):linkButton('添加作者档案','new-person'))}</div>
    ${result.total>result.page_size?`<div class="pagination">${result.page>1?linkButton('上一页','page',String(result.page-1)):''}<span>第 ${result.page} / ${Math.ceil(result.total/result.page_size)} 页</span>${result.page*result.page_size<result.total?linkButton('下一页','page',String(result.page+1)):''}</div>`:''}</section>`;
};
async function workbenchCollectionsPage(){const d=await api('/api/collections');state.collections=d.items;return '<section class="workspace-collections"><div class="page-heading between"><div><h1>资料夹</h1><p>移出资料夹不会删除原资料。</p></div>'+linkButton('新建资料夹','new-collection','','button primary')+'</div><div class="workbench-folder-list">'+d.items.map(c=>'<article class="workbench-folder-row"><div><h2>'+linkButton(esc(c.name),'open-collection',c.id,'title-button')+'</h2>'+(c.description?'<p>'+esc(c.description)+'</p>':'')+'<p class="muted">创建者：'+esc(c.owner_name)+'</p></div><div class="workbench-folder-meta"><span class="badge '+(c.visibility==='shared'?'verified':'neutral')+'">'+(c.visibility==='shared'?'中心共享':'仅我可见')+'</span><span>'+c.count+' 份资料</span></div></article>').join('')+(d.items.length?'':empty('暂无资料夹','按名称收集已有资料和成果，可写简短备注。','folder'))+'</div></section>';};
async function workbenchPersonalPage(){const saved=await api('/api/saved-searches?size=1');return '<section class="workbench-personal"><div class="page-heading"><h1>个人空间</h1><p>'+esc(state.me.name)+'</p></div><nav class="workbench-personal-links" aria-label="个人工作">'+[['favorites','收藏资料'],['collections','资料夹'],['drafts','未提交草稿']].map(([id,label])=>'<button data-action="nav" data-id="'+id+'"><strong>'+label+'</strong>'+icon('arrow')+'</button>').join('')+'<button data-action="saved-manage"><strong>常用检索</strong><span>'+saved.total+' 项已保存条件</span>'+icon('arrow')+'</button></nav><section class="workbench-personal-account"><h2>个人账号与导出</h2><div class="row wrap">'+(state.me.temporary?'<form data-form="trial-nickname"><label class="field">我的临时称呼<input name="name" maxlength="40" value="'+esc(state.me.name)+'" required></label><button class="button" type="submit">保存称呼</button><div class="form-error" role="alert"></div></form>':linkButton('修改我的密码','own-password'))+linkButton('导出可见内容','export-content')+linkButton('提供采集来源','new-source')+'</div><p class="muted">仅导出当前账号可读取的内容。</p></section></section>';};

const workbenchPositions=new Map();
function workbenchPositionKey(){const p=workbenchQuery(state.page==='compilations');return state.me?.id+'|'+state.page+'|'+p;}
function workbenchRemember(){
  const root=document.querySelector('.workbench');if(!root)return;
  const key=workbenchPositionKey(),prior=workbenchPositions.get(key)||{},index=root.querySelector('.workbench-index');
  if(!index.checkVisibility())return;
  const form=index.querySelector('[data-work-search]');
  workbenchPositions.set(key,{...prior,list:index.scrollTop,window:window.scrollY,focus:document.activeElement?.closest('[data-work-id]')?.dataset.workId||workbenchState.selected,search:Object.fromEntries(new FormData(form)),expanded:form.querySelector('details').open});
}
function workbenchAfterRender(){
  const root=document.querySelector('.workbench');if(!root)return;
  const saved=workbenchPositions.get(workbenchPositionKey());
  if(saved){const index=root.querySelector('.workbench-index'),form=index.querySelector('[data-work-search]');index.scrollTop=saved.list||0;if(saved.search)for(const [name,value] of Object.entries(saved.search)){if(form.elements[name])form.elements[name].value=value;}form.querySelector('details').open=!!saved.expanded;if(!state.params.get('id')){window.scrollTo(0,saved.window||0);const button=[...root.querySelectorAll('[data-action="workbench-select"]')].find(b=>b.dataset.id===saved.focus);button?.focus({preventScroll:true});}}
  if(state.params.get('id')&&matchMedia('(max-width:1199px)').matches){const heading=root.querySelector('.workbench-detail h1');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});window.scrollTo(0,0);}}
}
document.addEventListener('click',event=>{if(event.target.closest('.workbench [data-action],.sidebar [data-action]'))workbenchRemember();},true);
function workbenchAfterWrite(type,assignment=''){
  if(!document.querySelector('.workbench'))return;
  if(type==='topic-review-meeting')state.params.set('tab',workbenchState.topic?.stage==='compilation'?'manuscripts':'candidates');
  else if(type==='topic-stage-enter'||assignment){state.params.set('tab','manuscripts');if(assignment)state.params.set('assignment',assignment);else state.params.delete('assignment');}
  history.replaceState(history.state,'','#'+state.page+'?'+state.params);
}
document.addEventListener('submit',event=>{
  const form=event.target.closest('.workbench [data-work-search]');if(!form)return;event.preventDefault();event.stopImmediatePropagation();
  const fd=new FormData(form),p=workbenchParams({id:'',selected_business:'',tab:'',assignment:''});
  if(fd.get('from')&&fd.get('to')&&fd.get('from')>fd.get('to')){form.querySelector('.form-error').textContent='起始日期不能晚于截止日期。';return;}
  for(const key of ['q','country','participant','from','to']){p.delete(key);const value=String(fd.get(key)||'').trim();if(value)p.set(key,value);}workbenchRemember();go(state.page,p);
},true);
