'use strict';

async function collaborationPage(){
  if(state.params.get('business')==='journal')return journalCollaborationPage();
  const tid=state.params.get('id');
  if(tid)return collaborationTopicPage(tid);
  const scope=state.params.get('scope')||'participating',d=await api('/api/collaboration/topics?scope='+encodeURIComponent(scope));
  return '<section class="collaboration-workspace"><div class="page-heading between wrap"><div><p class="eyebrow">本机写作 · 平台交接</p><h1>编译协作</h1>'+linkButton('期刊编译','journal-home')+'<p class="muted">找到参加的主题，提交选题报告并查阅本期原件。</p></div><div class="row wrap">'+(d.can_create?linkButton(icon('plus')+' 开启一期主题','collaboration-new','','button primary'):'')+(state.me.role==='admin'?linkButton('负责人资格','collaboration-qualifications'):'')+'</div></div><nav class="collaboration-tabs" aria-label="主题工作范围">'+[['participating','我参与的'],['leading','我负责的'],...(state.me.role==='admin'?[['maintenance','维护查阅']]:[])].map(([key,label])=>'<button class="button '+(key===scope?'primary':'')+'" data-action="collaboration-scope" data-id="'+key+'" aria-pressed="'+(key===scope)+'">'+label+'</button>').join('')+'</nav><div class="collaboration-grid">'+d.items.map(t=>'<article class="panel"><span class="badge neutral">主题编译</span><h2>'+linkButton(esc(t.theme),'collaboration-open',t.id,'title-button')+'</h2><p>负责人：'+esc(t.lead_name)+'</p><p>参与研究员：'+t.participants.map(p=>esc(p.name)+(p.active?'':'（已停用）')).join('、')+'</p><p class="small muted">'+(t.due_on?'提交日期：'+esc(t.due_on):'未设提交日期')+'</p></article>').join('')+(d.items.length?'':empty('暂无本期工作',d.can_create?'可开启一期主题并选择参与研究员。':'负责人开期并将你加入后，本期工作会显示在这里。','folder'))+'</div></section>';
}

async function collaborationTopicPage(tid){
  const [t,d,w]=await Promise.all([api('/api/collaboration/topics/'+encodeURIComponent(tid)),api('/api/collaboration/topics/'+encodeURIComponent(tid)+'/candidates'),api('/api/collaboration/topics/'+encodeURIComponent(tid)+'/workflow')]);
  const mine=d.items.filter(x=>x.author_id===state.me.id),latest=mine.reduce((n,x)=>Math.max(n,x.version),0);
  const submitted=new Set(d.items.map(x=>x.author_id)),authors=[...new Set([...t.participants.map(p=>p.id),...submitted])].sort((a,b)=>Number(submitted.has(b))-Number(submitted.has(a)));
  const summary='<details class="collaboration-summary"><summary>参与研究员 '+t.participants.length+' 人 · 已交 '+t.participants.filter(p=>submitted.has(p.id)).length+' 人</summary><p>'+t.participants.map(p=>esc(p.name)+(p.active?'':'（账号已停用）')).join('、')+'</p></details>';
  const reports='<section class="panel"><div class="between wrap"><h2>本期选题报告</h2><a class="button" href="/api/collaboration/topics/'+esc(t.id)+'/candidates/export" download>下载本期选题报告</a></div><p class="small muted">本期参与者和管理员可查阅原件及历史版本。</p>'+authors.map(uid=>{
    const items=d.items.filter(x=>x.author_id===uid).sort((a,b)=>b.version-a.version),person=t.participants.find(p=>p.id===uid),name=items[0]?.author_name||person?.name||uid;
    if(!items.length)return '<p class="collaboration-pending">'+esc(name)+' <span class="badge neutral">尚未提交</span></p>';
    return '<article class="collaboration-author"><h3>'+esc(name)+' <span class="badge neutral">已交 '+items.length+' 版</span></h3>'+collaborationFileCard(items[0])+(items.length>1?'<details><summary>查看此前 '+(items.length-1)+' 个原件版本</summary>'+items.slice(1).map(collaborationFileCard).join('')+'</details>':'')+'</article>';
  }).join('')+'</section>';
  const upload=t.can_submit?'<details class="panel" data-collaboration-upload '+(latest?'':'open')+'><summary>提交我的选题报告'+(latest?' · 再交将保存为版本 '+(latest+1):'')+'</summary><p>在电脑按原有模板编写后直接上传，所属期次、提交人及时间自动记录。</p><form data-form="collaboration-upload" data-topic="'+esc(t.id)+'" data-topic-version="'+t.version+'" data-version="'+latest+'" data-request="'+crypto.randomUUID()+'"><div class="stack"><div class="field"><label for="candidate-file">选题报告文件 *</label><input id="candidate-file" type="file" name="file" accept=".docx,.pdf,.txt,.md" required><p class="form-help">Word（DOCX）、PDF、TXT 或 Markdown；最多20 MB，保留此前全部版本。</p></div><div class="field"><label for="candidate-note">简短说明（可选）</label><textarea id="candidate-note" name="note" maxlength="4000" rows="2"></textarea></div></div><div class="form-error" role="alert"></div><div data-collaboration-conflict></div><div class="form-actions"><button class="button primary" type="submit">提交为版本 '+(latest+1)+'</button></div></form></details>':'';
  const process=topicReviewSections(t,w);
  return '<section class="collaboration-workspace" data-collaboration-topic="'+esc(t.id)+'">'+linkButton('← 返回主题工作','collaboration-home')+'<div class="page-heading between wrap"><div><h1>'+esc(t.theme)+'</h1><p>负责人：'+esc(t.lead_name)+' · '+(t.due_on?'提交日期：'+esc(t.due_on):'未设提交日期')+'</p>'+summary+'</div><div class="row wrap">'+(w.assignments.some(a=>a.can_submit)?linkButton('我的编译分工','topic-review-mine','','button primary'):'')+(t.can_manage?linkButton(w.meeting_version?'修改会议决定':'记录会议决定','topic-review-meeting',t.id):'')+(t.can_submit?linkButton('提交我的选题报告','collaboration-upload-open'):'')+(t.can_manage?linkButton('维护本期信息','collaboration-edit',t.id):'')+'</div></div>'+(w.meeting_version?process+'<details class="panel"><summary>选题报告与历史</summary>'+reports+upload+'</details>':reports+upload+process)+'<details class="panel"><summary>本期信息修改历史</summary><div data-collaboration-history>'+linkButton('读取修改记录','collaboration-history',t.id)+'</div></details></section>';
}

function collaborationFileCard(s){const longName=s.name.length>60,name=longName?s.name.slice(0,40)+'…':s.name;return '<div class="collaboration-file"><div><strong>版本 '+s.version+' · '+esc(name)+'</strong>'+(longName?'<details><summary>完整文件名</summary><p>'+esc(s.name)+'</p></details>':'')+'<p class="small muted">作者：'+esc(s.author_name)+' · 提交人：'+esc(s.uploader_name)+' · '+dateTime(s.created_at)+'</p>'+(s.note?'<p class="collaboration-note">'+esc(s.note)+'</p>':'')+'<details><summary>原件校验信息</summary><p class="small">'+s.bytes+' 字节</p><p class="small collaboration-hash">SHA-256：'+esc(s.sha256)+'</p></details></div><a class="button" href="'+esc(s.file_url)+'" download>下载原件 v'+s.version+'</a></div>';}

async function collaborationTopicForm(tid=''){
  const t=tid?await api('/api/collaboration/topics/'+encodeURIComponent(tid)):null;
  if(t&&!t.can_manage)throw new Error('当前没有本期维护权限。');
  const users=(await api('/api/users')).items;
  modal(t?'维护本期信息':'开启一期主题','<form data-form="collaboration-topic" data-id="'+esc(tid)+'" data-version="'+(t?.version||0)+'"><div class="stack"><div class="field"><label for="collaboration-theme">本期主题 *</label><input id="collaboration-theme" name="theme" maxlength="500" required value="'+esc(t?.theme||'')+'"></div><fieldset><legend>参与研究员</legend><p class="form-help">你作为当期负责人自动参与。可选择多位研究员。</p><div class="collaboration-members">'+users.filter(u=>u.id!==state.me.id).map(u=>'<label class="check-label"><input type="checkbox" name="participant_ids" value="'+esc(u.id)+'" '+(t?.participants.some(p=>p.id===u.id)?'checked':'')+'>'+esc(u.name)+'</label>').join('')+'</div></fieldset><div class="field"><label for="collaboration-due">提交日期（可选）</label><input id="collaboration-due" name="due_on" type="date" value="'+esc(t?.due_on||'')+'"></div></div><div class="form-error" role="alert"></div><div data-collaboration-conflict></div><div class="form-actions"><button class="button primary" type="submit">保存本期信息</button></div></form>',true);
}

async function collaborationQualifications(){
  const d=await api('/api/collaboration/qualifications');
  modal('负责人资格登记','<p>资格与系统管理员角色分别登记。停用账号即使保留资格，也无法开期或维护工作。</p><div class="stack">'+d.items.map(u=>'<article class="panel"><div class="between wrap"><div><strong>'+esc(u.name)+'</strong><p class="small muted">'+(u.active?'有效账号':'账号已停用')+' · '+(u.enabled?'已登记负责人资格':'未登记负责人资格')+'</p></div><button class="button" data-action="collaboration-qualification" data-id="'+esc(u.id)+'" data-version="'+u.version+'" data-enabled="'+!u.enabled+'">'+(u.enabled?'撤销资格':'登记资格')+'</button></div></article>').join('')+'</div><details><summary>资格登记历史</summary>'+d.events.map(e=>'<p>'+esc(d.items.find(u=>u.id===e.member_id)?.name||e.member_id)+' · '+(e.enabled?'登记':'撤销')+' · '+esc(e.actor_name)+' · '+dateTime(e.created_at)+'</p>').join('')+'</details>');
}

document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-action]');if(!b||!b.dataset.action.startsWith('collaboration-'))return;
  const a=b.dataset.action,id=b.dataset.id;
  try{
    if(a==='collaboration-upload-open'){const panel=document.querySelector('[data-collaboration-upload]');if(panel){panel.open=true;for(let parent=panel.parentElement;parent;parent=parent.parentElement){if(parent.tagName==='DETAILS')parent.open=true;}panel.scrollIntoView({block:'start'});panel.querySelector('[type=file]').focus({preventScroll:true});}}
    else if(a==='collaboration-home')go('collaboration');
    else if(a==='collaboration-open')go('collaboration',{id});
    else if(a==='collaboration-scope')go('collaboration',{scope:id});
    else if(a==='collaboration-new')await collaborationTopicForm();
    else if(a==='collaboration-edit')await collaborationTopicForm(id);
    else if(a==='collaboration-qualifications')await collaborationQualifications();
    else if(a==='collaboration-qualification'){b.disabled=true;try{await api('/api/collaboration/qualifications/'+encodeURIComponent(id),{method:'PUT',body:{version:Number(b.dataset.version),enabled:b.dataset.enabled==='true'}});await collaborationQualifications();}finally{b.disabled=false;}}
    else if(a==='collaboration-history'){const d=await api('/api/collaboration/topics/'+encodeURIComponent(id)+'/history');b.closest('[data-collaboration-history]').innerHTML=d.items.map(e=>'<article class="history-row"><div><strong>本期信息 v'+e.version+' · '+esc(e.actor_name)+'</strong><p>'+dateTime(e.created_at)+' · '+esc(e.theme)+'</p><p>参与研究员：'+e.participants.map(p=>esc(p.name)).join('、')+'</p></div></article>').join('');}
    else if(a==='collaboration-rebase'){const form=b.closest('form'),latest=await api('/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic||form.dataset.id));form.dataset.topicVersion=latest.version;if(form.dataset.form==='collaboration-topic')form.dataset.version=latest.version;else{const d=await api('/api/collaboration/topics/'+encodeURIComponent(latest.id)+'/candidates');form.dataset.version=d.items.filter(x=>x.author_id===state.me.id).reduce((n,x)=>Math.max(n,x.version),0);form.dataset.request=crypto.randomUUID();form.querySelector('[type=submit]').textContent='提交为版本 '+(Number(form.dataset.version)+1);}form._conflict=false;form.querySelector('[data-collaboration-conflict]').innerHTML='';form.querySelector('.form-error').textContent='已按最新版本继续。当前文件和输入已保留。';}
  }catch(e){toast(e.message);}
});

document.addEventListener('submit',async event=>{
  const form=event.target,type=form.dataset.form;if(!['collaboration-topic','collaboration-upload'].includes(type))return;
  event.preventDefault();const error=form.querySelector('.form-error'),button=form.querySelector('[type=submit]'),account=state.me?.id;error.textContent='';button.disabled=true;
  try{
    if(form._conflict)throw new Error('请先核对最新版本，再继续提交。');
    let result;
    if(type==='collaboration-topic'){const fd=new FormData(form);result=await api('/api/collaboration/topics'+(form.dataset.id?'/'+encodeURIComponent(form.dataset.id):''),{method:form.dataset.id?'PUT':'POST',body:{theme:fd.get('theme'),due_on:fd.get('due_on'),participant_ids:fd.getAll('participant_ids'),version:Number(form.dataset.version)}});}
    else{const fd=new FormData(form);fd.set('data',JSON.stringify({version:Number(form.dataset.version),topic_version:Number(form.dataset.topicVersion),request_id:form.dataset.request,note:fd.get('note')}));result=await api('/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic)+'/candidates',{method:'POST',body:fd});}
    if(account!==state.me?.id||!form.isConnected)return;
    closeModal();toast(type==='collaboration-topic'?'本期信息已保存':'报告原件已提交，历史版本继续保留');
    if(type==='collaboration-topic')go('collaboration',{id:result.id});else{await route();document.querySelector('.collaboration-author')?.scrollIntoView({block:'start'});}
  }catch(e){if(!form.isConnected)return;error.textContent=e.message;if(e.status===409){form._conflict=true;try{const latest=await api('/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic||form.dataset.id)),reports=type==='collaboration-upload'?(await api('/api/collaboration/topics/'+encodeURIComponent(latest.id)+'/candidates')).items.filter(x=>x.author_id===state.me.id):[];form.querySelector('[data-collaboration-conflict]').innerHTML='<section class="notice"><h3>请核对本期最新信息</h3><p>'+esc(latest.theme)+' · 本期信息 v'+latest.version+'</p><p>参与研究员：'+latest.participants.map(p=>esc(p.name)).join('、')+'</p>'+(reports.length?'<p>最近交接：版本 '+reports[0].version+' · '+esc(reports[0].name)+' · '+dateTime(reports[0].created_at)+'</p><p>'+esc(reports[0].note)+'</p><a class="button" href="'+esc(reports[0].file_url)+'" download>下载最新原件核对</a>':'')+'<p>当前文件与输入已保留。核对最新报告后，再决定是否提交新版本。</p><button type="button" class="button" data-action="collaboration-rebase">已核对，保留输入继续</button></section>';}catch(checkError){error.textContent=checkError.message;}}}finally{if(form.isConnected)button.disabled=false;}
});
