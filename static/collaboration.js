'use strict';
const collaborationMemberLimit=200;
const collaborationMemberLimitMessage='最多选择 200 位其他参与研究员；本人自动参与不计入上限。请缩小查找范围或取消部分选择。';

async function collaborationPage(){
  if(state.params.get('full')==='1'&&state.params.get('id'))return state.params.get('business')==='journal'?journalWorkPage(state.params.get('id')):collaborationTopicPage(state.params.get('id'));
  return workbenchWorkspacePage();
}

async function collaborationTopicPage(tid){
  return workbenchTopic(tid);
}

function collaborationFileCard(s){
  const longName=s.name.length>60,name=longName?s.name.slice(0,40)+'…':s.name;
  const kb=Number.isFinite(s.bytes)?readableFileSize(s.bytes):'';
  return '<div class="collaboration-file"><div><strong>版本 '+s.version+' · '+esc(name)+'</strong>'+(longName?'<details><summary>完整文件名</summary><p>'+esc(s.name)+'</p></details>':'')+'<p class="small muted">'+(s.author_id===s.uploader_id?'作者、提交人：'+esc(s.author_name):'作者：'+esc(s.author_name)+' · 提交人：'+esc(s.uploader_name))+(kb?' · '+kb:'')+' · '+dateTime(s.created_at)+'</p>'+(s.note?'<p class="collaboration-note">'+esc(s.note)+'</p>':'')+'<details class="file-hash-details"><summary>原件校验信息</summary><p class="small">'+s.bytes+' 字节 · SHA-256：'+esc(s.sha256)+'</p></details></div><a class="button tiny" href="'+esc(s.file_url)+'" download>下载原件 v'+s.version+'</a></div>';
}

async function collaborationTopicForm(tid=''){
  const account=state.me?.id,t=tid?await api('/api/collaboration/topics/'+encodeURIComponent(tid)):null;
  if(t&&!t.can_manage)throw new Error('当前没有本期维护权限。');
  const users=(await api('/api/users')).items;if(account!==state.me?.id)return;
  modal(t?'维护本期信息':'开启一期主题','<form data-form="collaboration-topic" data-id="'+esc(tid)+'" data-version="'+(t?.version||0)+'"><div class="stack"><div class="field"><label for="collaboration-theme">本期主题 *</label><input id="collaboration-theme" name="theme" maxlength="500" required value="'+esc(t?.theme||'')+'"></div><fieldset data-collaboration-members><legend>参与研究员</legend><p class="form-help">你自动参与；另可选择最多200位成员。</p><label class="field">查找其他成员<input type="search" data-collaboration-member-search></label><div class="row wrap"><button class="button tiny" type="button" data-action="collaboration-members-all">全选当前查找成员</button><button class="button tiny" type="button" data-action="collaboration-members-clear">清空其他成员</button><button class="button tiny" type="button" data-action="collaboration-members-refresh">刷新成员</button></div><p role="status" aria-live="polite" data-collaboration-member-count></p><div class="collaboration-members" data-collaboration-member-list></div><div data-collaboration-member-selected></div><p class="form-error" role="alert" data-collaboration-member-error></p></fieldset><div class="field"><label for="collaboration-due">提交日期（可选）</label><input id="collaboration-due" name="due_on" type="date" value="'+esc(t?.due_on||'')+'"></div></div><div class="form-error" role="alert"></div><div data-collaboration-conflict></div><div class="form-actions"><button class="button primary" type="submit">保存本期信息</button></div></form>',true);
  const form=document.querySelector('[data-form=collaboration-topic]');form._memberUsers=users;form._memberAccount=state.me.id;
  renderCollaborationMembers(form,new Set(t?.participants.map(p=>p.id)||[]));
}

function renderCollaborationMembers(form,selected){
  const users=form._memberUsers.filter(u=>u.id!==state.me.id&&u.active!==false&&u.active!==0),q=form.querySelector('[data-collaboration-member-search]').value.toLocaleLowerCase().trim();
  const visible=users.filter(u=>(u.name+' '+(u.username||'')).toLocaleLowerCase().includes(q));
  selected=selected||new Set([...form.querySelectorAll('[name=participant_ids]:checked')].map(x=>x.value));
  const picked=users.filter(u=>selected.has(u.id));
  form.querySelector('[data-collaboration-member-list]').innerHTML=users.map(u=>'<label class="check-label" '+(visible.includes(u)?'':'hidden')+'><input type="checkbox" name="participant_ids" value="'+esc(u.id)+'" '+(selected.has(u.id)?'checked':picked.length>=collaborationMemberLimit?'disabled':'')+'>'+esc(u.name)+'</label>').join('')||'<p class="notice">目前没有其他有效成员，你仍可单人开期。其他成员入场后，点击“刷新成员”再选择。</p>';
  form.querySelector('[data-collaboration-member-count]').textContent='本人自动参与 · 已选其他成员 '+picked.length+' / '+collaborationMemberLimit+' 人 · 当前查找 '+visible.length+' 人'+(users.length&&!visible.length?'；没有匹配成员，请调整查找。':'');
  form.querySelector('[data-collaboration-member-selected]').textContent=picked.length?'已选其他成员（含查找隐藏项）：'+picked.map(u=>u.name).join('、'):'';
  const additions=visible.filter(u=>!selected.has(u.id)).length,overLimit=picked.length+additions>collaborationMemberLimit;
  form.querySelector('[data-action=collaboration-members-all]').disabled=!additions||overLimit;
  if(overLimit)form.querySelector('[data-collaboration-member-count]').textContent+='；全选当前查找会超过上限，请缩小查找范围。';
  form.querySelector('[data-action=collaboration-members-clear]').disabled=!picked.length;
}
async function refreshCollaborationMembers(form){
  const turn=(form._membersTurn||0)+1;form._membersTurn=turn;const result=await api('/api/users');
  if(!form.isConnected||form._membersTurn!==turn||form._memberAccount!==state.me?.id)return;
  // Read after the response so new clicks made during the request win.
  const selected=new Set([...form.querySelectorAll('[name=participant_ids]:checked')].map(x=>x.value));
  form._memberUsers=result.items;renderCollaborationMembers(form,selected);
}
document.addEventListener('input',event=>{if(event.target.matches('[data-collaboration-member-search]'))renderCollaborationMembers(event.target.closest('form'));});
document.addEventListener('change',event=>{if(event.target.name==='participant_ids'){
  const form=event.target.closest('form'),id=event.target.value;form.querySelector('[data-collaboration-member-error]').textContent='';
  if(event.target.checked&&form.querySelectorAll('[name=participant_ids]:checked').length>collaborationMemberLimit){event.target.checked=false;form.querySelector('[data-collaboration-member-error]').textContent=collaborationMemberLimitMessage;}
  renderCollaborationMembers(form);[...form.querySelectorAll('[name=participant_ids]')].find(x=>x.value===id)?.focus({preventScroll:true});
}});

async function collaborationQualifications(){
  const d=await api('/api/collaboration/qualifications');
  modal('负责人资格登记','<p class="small muted">资格与系统管理员角色分别登记。</p><div class="stack">'+d.items.map(u=>'<article class="panel"><div class="between wrap"><div><strong>'+esc(u.name)+'</strong><p class="small muted">'+(u.active?'有效账号':'账号已停用')+' · '+(u.enabled?'已登记负责人资格':'未登记负责人资格')+'</p></div><button class="button tiny" data-action="collaboration-qualification" data-id="'+esc(u.id)+'" data-version="'+u.version+'" data-enabled="'+!u.enabled+'">'+(u.enabled?'撤销资格':'登记资格')+'</button></div></article>').join('')+'</div><details><summary>资格登记历史</summary>'+d.events.map(e=>'<p>'+esc(d.items.find(u=>u.id===e.member_id)?.name||e.member_id)+' · '+(e.enabled?'登记':'撤销')+' · '+esc(e.actor_name)+' · '+dateTime(e.created_at)+'</p>').join('')+'</details>');
}

document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-action]');if(!b||!b.dataset.action.startsWith('collaboration-'))return;
  const a=b.dataset.action,id=b.dataset.id;
  try{
    if(a.startsWith('collaboration-members-')){
      const form=b.closest('form');
      if(a==='collaboration-members-refresh'){b.disabled=true;try{await refreshCollaborationMembers(form);}finally{if(b.isConnected)b.disabled=false;}}
      else{
        const inputs=[...form.querySelectorAll('[name=participant_ids]')],selected=inputs.filter(input=>input.checked),additions=inputs.filter(input=>!input.checked&&!input.closest('label').hidden);
        const error=form.querySelector('[data-collaboration-member-error]');error.textContent='';
        if(a==='collaboration-members-all'&&selected.length+additions.length>collaborationMemberLimit){error.textContent=collaborationMemberLimitMessage;return;}
        for(const input of inputs)if(a==='collaboration-members-clear'||!input.closest('label').hidden)input.checked=a==='collaboration-members-all';renderCollaborationMembers(form);
      }
    }
    else if(a==='collaboration-upload-open'){const panel=document.querySelector('[data-collaboration-upload]');if(panel){panel.open=true;for(let parent=panel.parentElement;parent;parent=parent.parentElement){if(parent.tagName==='DETAILS')parent.open=true;}panel.scrollIntoView({block:'start'});panel.querySelector('[type=file]').focus({preventScroll:true});}}
    else if(a==='collaboration-home')go('collaboration');
    else if(a==='collaboration-open')go('collaboration',{id});
    else if(a==='collaboration-scope')go('collaboration',{scope:id});
    else if(a==='collaboration-new')await collaborationTopicForm();
    else if(a==='collaboration-edit')await collaborationTopicForm(id);
    else if(a==='collaboration-qualifications')await collaborationQualifications();
    else if(a==='collaboration-qualification'){b.disabled=true;try{await api('/api/collaboration/qualifications/'+encodeURIComponent(id),{method:'PUT',body:{version:Number(b.dataset.version),enabled:b.dataset.enabled==='true'}});await collaborationQualifications();}finally{b.disabled=false;}}
    else if(a==='collaboration-history'){const d=await api('/api/collaboration/topics/'+encodeURIComponent(id)+'/history');b.closest('[data-collaboration-history]').innerHTML=d.items.map(e=>'<article class="history-row"><div><strong>本期信息 v'+e.version+' · '+esc(e.actor_name)+'</strong><p>'+dateTime(e.created_at)+' · '+esc(e.theme)+'</p><p>参与研究员：'+e.participants.map(p=>esc(p.name)).join('、')+'</p></div></article>').join('');}
    else if(a==='collaboration-rebase'){const form=b.closest('form'),latest=await api('/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic||form.dataset.id));if(form.dataset.form==='collaboration-topic'?!latest.can_manage:!latest.can_submit)throw new Error('本期已结束或当前权限已变化。文件与输入仍保留，请联系负责人核对。');form.dataset.topicVersion=latest.version;if(form.dataset.form==='collaboration-topic')form.dataset.version=latest.version;else{const d=await api('/api/collaboration/topics/'+encodeURIComponent(latest.id)+'/candidates');form.dataset.version=d.items.filter(x=>x.author_id===state.me.id).reduce((n,x)=>Math.max(n,x.version),0);form.dataset.request=crypto.randomUUID();form.querySelector('[type=submit]').textContent='提交为版本 '+(Number(form.dataset.version)+1);}form._conflict=false;form.querySelector('[data-collaboration-conflict]').innerHTML='';form.querySelector('.form-error:not([data-collaboration-member-error])').textContent='已按最新版本继续。当前文件和输入已保留。';}
  }catch(e){toast(e.message);}
});

document.addEventListener('submit',async event=>{
  const form=event.target,type=form.dataset.form;if(!['collaboration-topic','collaboration-upload'].includes(type))return;
  event.preventDefault();const error=form.querySelector('.form-error:not([data-collaboration-member-error])'),button=form.querySelector('[type=submit]'),account=state.me?.id;error.textContent='';button.disabled=true;
  try{
    if(form._conflict)throw new Error('请先核对最新版本，再继续提交。');
    let result;
    if(type==='collaboration-topic'){const fd=new FormData(form);if(fd.getAll('participant_ids').length>collaborationMemberLimit)throw new Error(collaborationMemberLimitMessage);result=await api('/api/collaboration/topics'+(form.dataset.id?'/'+encodeURIComponent(form.dataset.id):''),{method:form.dataset.id?'PUT':'POST',body:{theme:fd.get('theme'),due_on:fd.get('due_on'),participant_ids:fd.getAll('participant_ids'),version:Number(form.dataset.version)}});}
    else{const fd=new FormData(form);fd.set('data',JSON.stringify({version:Number(form.dataset.version),topic_version:Number(form.dataset.topicVersion),request_id:form.dataset.request,note:fd.get('note')}));result=await api('/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic)+'/candidates',{method:'POST',body:fd});}
    if(account!==state.me?.id||!form.isConnected)return;
    closeModal();toast(type==='collaboration-topic'?'本期信息已保存':'报告原件已提交，历史版本继续保留');
    if(type==='collaboration-topic')go('collaboration',{id:result.id});else{await route();document.querySelector('.collaboration-author')?.scrollIntoView({block:'start'});}
  }catch(e){if(!form.isConnected)return;error.textContent=e.message;if(e.status===409){form._conflict=true;try{const latest=await api('/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic||form.dataset.id)),reports=type==='collaboration-upload'?(await api('/api/collaboration/topics/'+encodeURIComponent(latest.id)+'/candidates')).items.filter(x=>x.author_id===state.me.id):[];form.querySelector('[data-collaboration-conflict]').innerHTML='<section class="notice"><h3>请核对本期最新信息</h3><p>'+esc(latest.theme)+' · 本期信息 v'+latest.version+'</p>'+topicClosedNotice(latest)+'<p>参与研究员：'+latest.participants.map(p=>esc(p.name)).join('、')+'</p>'+(reports.length?'<p>最近交接：版本 '+reports[0].version+' · '+esc(reports[0].name)+' · '+dateTime(reports[0].created_at)+'</p><p>'+esc(reports[0].note)+'</p><a class="button" href="'+esc(reports[0].file_url)+'" download>下载最新原件核对</a>':'')+'<p>当前文件与输入已保留。</p>'+'<button type="button" class="button" data-action="collaboration-rebase">已核对，保留输入继续</button>'+'</section>';}catch(checkError){error.textContent=checkError.message;}}}finally{if(form.isConnected)button.disabled=false;}
});

function topicStageHistory(t){
  const events=t.stage_events||[];
  return '<details class="panel"><summary>阶段来历</summary>'+(t.stage_origin?.kind==='legacy_migration'?'<p>升级时依据既有分工及下游材料保留为'+(t.stage_origin.initial_stage==='compilation'?'编译':'选题')+'阶段；这不是过去的人工确认。</p>':'<p>开期时进入选题阶段。</p>')+events.map(e=>'<p>'+esc(e.actor_name)+' · '+dateTime(e.created_at)+' · 依据会议决定 v'+e.meeting_version+' 确认进入编译阶段</p>').join('')+'</details>';
}
