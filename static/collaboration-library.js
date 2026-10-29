'use strict';

function workReturnButton(label,fallback){
  const target=state.params.get('return');
  return target&&/^#(collaboration|compilations|maintenance-work)(\?|$)/.test(target)?'<button class="button" data-action="work-return" data-target="'+esc(target)+'">'+esc(target.startsWith('#compilations')?'← 返回中心成果':label)+'</button>':linkButton(label,fallback);
}
function workMaterialTools(business,id){
  return '<details class="work-material-tools"><summary>下载本期材料包</summary><p>当前有权查阅的本期原件及版本；不含关联成果正文、附件或原文。</p><div class="row wrap">'+[['products','成果原件'],['process','过程材料'],['all','全部已提交材料']].map(([scope,label])=>'<a class="button tiny" href="/api/collaboration/materials/'+business+'/'+esc(id)+'?scope='+scope+'" download>'+label+'</a>').join('')+'</div></details>';
}
function workQuery(products){
  const p=new URLSearchParams(state.params);p.delete('return');p.set('view',products?'products':'works');
  if(isMaintenancePage())p.set('scope','maintenance');
  else if(!p.has('scope'))p.set('scope',products?'all':'participating');
  if(p.get('business')==='all')p.delete('business');
  else if(!p.has('business')&&!products)p.set('business','topic');
  return p;
}
function workBusinessTabs(products){
  const selected=state.params.get('business')||(products?'all':'topic');
  return '<nav class="collaboration-tabs collaboration-business-tabs" aria-label="编译业务">'+[['topic','主题编译'],['journal','期刊编译'],['all','全部业务']].map(([key,label])=>'<button class="button '+(key===selected?'primary':'')+'" data-action="work-filter" data-key="business" data-id="'+key+'" aria-pressed="'+(key===selected)+'">'+label+'</button>').join('')+'</nav>';
}
function workProductRow(p,w){
  const label={summary:'整期汇总',final:'单篇定稿',journal:'当前成品'}[p.product_kind],title=p.title||w.record_title||label;
  return '<article class="work-product"><div><strong>'+esc(title)+(title===label?'':' · '+label)+' v'+p.version+'</strong><p class="small muted">'+esc(p.author_name||p.uploader_name||'')+(p.country?' · '+esc(p.country):'')+' · '+dateTime(p.created_at)+'</p>'+(p.record?linkButton('查看成果正文','detail',p.record.id):w.business==='journal'?linkButton('查看成果正文','detail',w.record_id):'')+'</div><a class="button tiny" href="'+esc(p.file_url)+'" download>下载成果原件 v'+p.version+'</a></article>';
}
function workEmptyState(products,business){
  const actions=linkButton(products?'查看全部可读成果':'查看全部可读工作','work-browse','','button primary')
    +(!products&&business!=='journal'?linkButton('查看期刊编译','work-journals'):'')
    +(products?linkButton('独立成果与跨期译稿','work-legacy'):linkButton('浏览资料','work-read'));
  return empty(products?'当前范围暂无成果':'当前范围暂无工作','','folder')+'<div class="empty-actions">'+actions+'</div>';
}
async function collaborationWorkspacePage(products=false){
  const query=workQuery(products),d=await api('/api/collaboration/works?'+query),p=state.params,scope=query.get('scope'),business=p.get('business')||(products?'all':'topic');
  const heading=products?'中心成果':business==='journal'?'期刊编译':'编译协作';
  const actions=products?linkButton('独立成果与跨期译稿','work-legacy')+linkButton('导入成品','import-output','','button primary'):((business!=='journal'&&d.can_create?linkButton('开启一期主题','collaboration-new','','button primary'):'')+(business!=='topic'?linkButton('新建期刊工作','journal-new','','button primary'):''));
  const scopeLabels=isMaintenancePage()?[['maintenance','维护查阅']]:[['participating','我参与的'],['leading','我负责的'],['all','全部可读']];
  const hasFilters=['q','country','participant','from','to'].some(k=>p.get(k));
  const rows=d.items.map(w=>{
    const open='<button class="button tiny" data-action="work-open" data-id="'+esc(w.id)+'" data-business="'+w.business+'">进入'+(w.business==='topic'?'主题':'期刊')+'工作</button>';
    return '<article class="work-list-row" data-work-id="'+esc(w.id)+'"><div class="between wrap"><div class="work-row-main"><div class="row wrap"><span class="badge neutral">'+(w.business==='topic'?'主题编译':'期刊编译')+'</span>'+(w.business==='topic'?'<span class="small muted">负责人：'+esc(w.lead_name)+'</span>':'')+'<span class="small muted">最近修订 '+dateTime(w.updated_at)+'</span></div><h2><button class="title-button" data-action="work-open" data-id="'+esc(w.id)+'" data-business="'+w.business+'">'+esc(w.title)+'</button></h2><details class="work-row-context"><summary>参与人、分工与修订时间</summary><p>'+esc(w.participant_names.join('、'))+'</p>'+(w.countries.length?'<p>国家分工：'+w.countries.map(esc).join('、')+'</p>':'')+'<p>最近修订 '+dateTime(w.updated_at)+'</p></details></div>'+(!products?open:'')+'</div>'+(products?w.products.map(product=>workProductRow(product,w)).join(''):'')+'</article>';
  }).join('');
  return '<section class="collaboration-workspace work-discovery" data-work-discovery><div class="page-heading between wrap"><div><h1>'+heading+'</h1></div><div class="row wrap">'+actions+'</div></div><div class="collaboration-nav-bar">'+workBusinessTabs(products)+'<nav class="collaboration-tabs collaboration-scope-tabs" aria-label="工作范围">'+scopeLabels.map(([key,label])=>'<button class="button '+(key===scope?'primary':'')+'" data-action="work-filter" data-key="scope" data-id="'+key+'" aria-pressed="'+(key===scope)+'">'+label+'</button>').join('')+'</nav></div><form data-work-search><div class="work-search"><label><span class="sr-only">主题或期刊</span><input type="search" name="q" value="'+esc(p.get('q'))+'" placeholder="搜索主题、期刊或卷期范围 (按 / 聚焦)" aria-label="主题或期刊"></label><button class="button primary" type="submit">查找工作</button></div><details><summary>国家分工、参与人与时间'+(hasFilters?' · 已设条件':'')+'</summary><div class="work-search"><label>国家分工<input name="country" value="'+esc(p.get('country'))+'"></label><label>参与人<input name="participant" value="'+esc(p.get('participant'))+'"></label><label>起始日期<input type="date" name="from" value="'+esc(p.get('from'))+'"></label><label>截止日期<input type="date" name="to" value="'+esc(p.get('to'))+'"></label></div></details><div class="form-error" role="alert"></div></form><div class="results-head"><span>共 <strong>'+d.total+'</strong> 项工作 · 最新在前</span><button class="button tiny '+(hasFilters?'':'light')+'" data-action="work-reset">重置查找</button></div><div class="work-list">'+rows+(d.total?'':workEmptyState(products,business))+'</div>'+(products?'<div class="work-legacy-bar">'+linkButton('查阅全部资料与旧研究积累','work-old-content','','ux-read-link')+'</div>':'')+'</section>';
}
document.addEventListener('click',event=>{
  const b=event.target.closest('[data-action]');if(!b?.dataset.action.startsWith('work-'))return;
  if(b.dataset.action==='work-open')go(isMaintenancePage()?'maintenance-work':'collaboration',{business:b.dataset.business,id:b.dataset.id,return:location.hash});
  else if(b.dataset.action==='work-return'){const [page,query='']=b.dataset.target.slice(1).split('?');go(page,new URLSearchParams(query));}
  else if(b.dataset.action==='work-filter')go(state.page,parameters({[b.dataset.key]:b.dataset.id}));
  else if(b.dataset.action==='work-retry')route();
  else if(b.dataset.action==='work-back')go('collaboration');
  else if(b.dataset.action==='work-reset'){
    const p=new URLSearchParams();
    for(const key of ['business','scope'])if(state.params.has(key))p.set(key,state.params.get(key));
    go(state.page,p);
  }
  else if(b.dataset.action==='work-browse')go(state.page,{business:'all',scope:'all'});
  else if(b.dataset.action==='work-journals')go('collaboration',{business:'journal'});
  else if(b.dataset.action==='work-read')go('library',{feed:'all'});
  else if(b.dataset.action==='work-legacy')go('compilations',{legacy:'1'});
  else if(b.dataset.action==='work-old-content'){const p=new URLSearchParams(state.params);for(const k of ['legacy','business','scope','participant'])p.delete(k);p.set('feed','all');go('library',p);}
});
document.addEventListener('submit',event=>{
  const form=event.target.closest('[data-work-search]');if(!form)return;event.preventDefault();const fd=new FormData(form),p=new URLSearchParams(state.params);
  if(fd.get('from')&&fd.get('to')&&fd.get('from')>fd.get('to')){form.querySelector('.form-error').textContent='起始日期不能晚于截止日期。';return;}
  for(const key of ['q','country','participant','from','to']){p.delete(key);if(fd.get(key))p.set(key,fd.get(key));}go(state.page,p);
});
