'use strict';

function topicClosedNotice(t){
  return t.lifecycle_state==='closed'?'<p class="notice" data-topic-closed>本期已结束。已保存材料仍按原权限查阅、下载和导出。</p>':'';
}
function topicClosureActions(t){
  return (t.can_end?linkButton('结束本期','topic-closure-end',t.id):'')+(t.can_reopen?linkButton('重新开启本期','topic-closure-reopen',t.id,'button primary'):'');
}
function topicClosureHistory(t){
  const events=t.lifecycle_events||[];
  if(!events.length)return '';
  return '<details class="panel"><summary>结束与重开记录 · '+events.length+' 次</summary>'+events.map(e=>'<article><h3>'+(e.action==='end'?'结束本期':'重新开启本期')+' · '+esc(e.actor_name)+'</h3><p>'+dateTime(e.created_at)+' · '+(e.stage==='compilation'?'编译阶段':'选题阶段')+'</p>'+(e.action==='end'&&e.basis?.format_version!==2?'<p>当时未完成分工：'+e.incomplete.length+' 项</p>'+topicClosureGaps(e.incomplete):'')+'</article>').join('')+'</details>';
}
function topicClosureGaps(items){
  return items.length?'<ul class="meeting-assignments">'+items.map(a=>{
    const long=a.title.length>60,title=long?a.title.slice(0,48)+'…':a.title;
    return '<li><strong class="meeting-assignment-title">'+esc(a.author_name)+' — '+esc(title)+'</strong>'+(long?'<details><summary>完整题名</summary><p>'+esc(a.title)+'</p></details>':'')+'<p>'+esc({awaiting_submission:'待交稿',pending:'待审',returned:'返修'}[a.status]||a.status)+(a.submission_version?' · 当前稿 v'+a.submission_version:'')+' · 缺当前定稿</p></li>';
  }).join('')+'</ul>':'';
}
function topicClosurePreview(p){
  return '<p>结束后暂停本期上传和审阅，材料继续可读。负责人可重开。</p>'+(p.incomplete.length?topicClosureGaps(p.incomplete):'');
}
async function topicClosureForm(tid,reopen=false){
  const account=state.me?.id,root='/api/collaboration/topics/'+encodeURIComponent(tid),t=await api(root);
  if(account!==state.me?.id)return;
  if(reopen?!t.can_reopen:!t.can_end)throw new Error('当前状态或负责人资格不允许此操作。');
  const p=reopen?null:await api(root+'/closure-preview');
  if(account!==state.me?.id)return;
  modal(reopen?'重新开启本期':'结束本期','<form data-form="topic-closure" data-account="'+esc(account)+'" data-topic="'+esc(tid)+'" data-operation="'+(reopen?'reopen':'end')+'" data-version="'+(p?.lifecycle_version||t.lifecycle_version)+'" data-request="'+crypto.randomUUID()+'"><div data-closure-preview>'+(reopen?'<p>恢复'+(t.closed_stage==='compilation'?'编译':'选题')+'阶段，保留现有稿件、决定及固定采用版本。</p>':topicClosurePreview(p))+'</div><div class="form-error" role="alert"></div><div data-closure-conflict></div><div class="form-actions"><button class="button primary" type="submit">'+(reopen?'确认重新开启':'确认结束本期')+'</button></div></form>',true);
  document.querySelector('[data-form="topic-closure"]')._preview=p;
}
document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-action]');if(!b?.dataset.action.startsWith('topic-closure-'))return;
  try{
    if(b.dataset.action==='topic-closure-refresh'){
      const form=b.closest('form'),p=await api('/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic)+'/closure-preview');
      form._preview=p;form.dataset.version=p.lifecycle_version;form.dataset.request=crypto.randomUUID();form._conflict=false;
      form.querySelector('[data-closure-preview]').innerHTML=topicClosurePreview(p);form.querySelector('[data-closure-conflict]').innerHTML='';form.querySelector('.form-error').textContent='已刷新本期状态，请再次确认。';
    }else await topicClosureForm(b.dataset.id,b.dataset.action==='topic-closure-reopen');
  }catch(e){toast(e.message);}
});
document.addEventListener('submit',async event=>{
  const form=event.target;if(form.dataset.form!=='topic-closure')return;
  event.preventDefault();if(form.dataset.saving==='true'||form.dataset.account!==state.me?.id)return;form.dataset.saving='true';const button=form.querySelector('[type=submit]'),error=form.querySelector('.form-error'),account=state.me?.id;button.disabled=true;error.textContent='';
  try{
    if(form._conflict)throw new Error('请先刷新本期状态后确认。');
    const operation=form.dataset.operation,data={request_id:form.dataset.request,lifecycle_version:Number(form.dataset.version)};
    if(operation==='end'){data.basis_token=form._preview.basis_token;data.confirm=true;}
    const result=await api('/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic)+'/'+operation,{method:'POST',body:data});
    if(account!==state.me?.id||!form.isConnected)return;
    closeModal();await route();toast(result.reused?'操作已记录，已显示当前状态':operation==='end'?'本期已结束，材料继续保留':'本期已重新开启');
  }catch(e){if(form.isConnected){error.textContent=e.message;if(e.status===409){form._conflict=true;form.querySelector('[data-closure-conflict]').innerHTML=form.dataset.operation==='end'?'<button type="button" class="button" data-action="topic-closure-refresh">重新核对结束内容</button>':'';}button.disabled=false;}}finally{form.dataset.saving='false';}
});
