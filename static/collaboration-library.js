'use strict';

function workReturnButton(label,fallback){
  const target=state.params.get('return');
  return target&&/^#(collaboration|compilations|maintenance-work)(\?|$)/.test(target)?'<button class="button" data-action="work-return" data-target="'+esc(target)+'">'+esc(target.startsWith('#compilations')?'← 返回中心成果':label)+'</button>':linkButton(label,fallback);
}
function workMaterialTools(business,id){
  return '<details class="work-material-tools"><summary>下载本期材料包</summary><p>当前有权查阅的本期原件及版本；不含关联成果正文、附件或原文。</p><div class="row wrap">'+[['products','成果原件'],['process','过程材料'],['all','全部已提交材料']].map(([scope,label])=>'<a class="button tiny" href="/api/collaboration/materials/'+business+'/'+esc(id)+'?scope='+scope+'" download>'+label+'</a>').join('')+'</div></details>';
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
async function collaborationWorkspacePage(products=false){return workbenchWorkspacePage(products);}
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
