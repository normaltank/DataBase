'use strict';

function topicReviewFile(item,label){
  return item.file_url?'<div class="collaboration-file"><div><strong>'+esc(item.name)+'</strong><p class="small muted">'+item.bytes+' 字节 · '+dateTime(item.created_at)+'</p></div><a class="button" href="'+esc(item.file_url)+'" download>'+esc(label)+'</a></div>':'';
}

function topicReviewDecision(m){
  return '<article><h3>会议决定 v'+m.version+' · '+esc(m.actor_name)+'</h3><p class="small muted">'+dateTime(m.created_at)+'</p>'+(m.note?'<p class="collaboration-note">'+esc(m.note)+'</p>':'')+topicReviewFile(m,'下载会议材料')+(m.assignments.length?'<details><summary>采用文章与分工 '+m.assignments.length+' 项</summary><ul>'+m.assignments.map(a=>'<li>'+esc(a.title)+(a.country?' · '+esc(a.country):'')+'</li>').join('')+'</ul></details>':'')+'</article>';
}

function topicReviewReturn(r,s){
  return '<section class="topic-return"><h4>退回版本 '+s.version+' · '+esc(r.actor_name)+'</h4><p class="small muted">'+dateTime(r.created_at)+'</p>'+(r.note?'<p class="collaboration-note">'+esc(r.note)+'</p>':'')+topicReviewFile(r,'下载批注文件')+'</section>';
}

function topicReviewManuscript(s,a){
  return collaborationFileCard(s)+a.returns.filter(r=>r.submission_id===s.id).map(r=>topicReviewReturn(r,s)).join('')+(a.finals||[]).filter(f=>f.submission_id===s.id).map(topicFinalDecision).join('');
}

function topicCurrentSubmission(a){return a?.submissions.find(s=>s.id===a.current_submission_id);}

function topicReviewForm(t,w,a,review=false){
  const latest=review?topicCurrentSubmission(a):a.submissions[0],kind=review?'return':'draft',id=kind+'-'+a.id;
  return '<details class="topic-handoff" data-topic-handoff="'+esc(a.id)+'" '+(!review&&!latest?'open':'')+'><summary>'+(review?'退回修改 · 针对版本 '+latest.version:'提交我的编译稿'+(latest?' · 新版本 '+(latest.version+1):''))+'</summary><form data-form="topic-review-'+kind+'" data-topic="'+esc(t.id)+'" data-assignment="'+esc(a.id)+'" data-topic-version="'+t.version+'" data-meeting-version="'+w.meeting_version+'" data-version="'+(latest?.version||0)+'" data-submission="'+esc(latest?.id||'')+'" data-request="'+crypto.randomUUID()+'"><div class="stack"><div class="field"><label for="'+id+'-note">'+(review?'退回意见':'交稿说明（可选）')+'</label><textarea id="'+id+'-note" name="note" maxlength="4000" rows="3"></textarea></div><div class="field"><label for="'+id+'-file">'+(review?'批注文件（可选）':'编译稿文件 *')+'</label><input id="'+id+'-file" name="file" type="file" accept=".docx,.pdf,.txt,.md" '+(review?'':'required')+'><p class="form-help">'+(review?'填写意见或提交批注文件。':'在本机写好后交稿，按本篇独立保存版本。')+'支持 DOCX、PDF、TXT、Markdown，最多20 MB。</p></div></div><div class="form-error" role="alert"></div><div data-topic-review-conflict></div><div class="form-actions"><button class="button primary" type="submit">'+(review?'退回版本 '+latest.version:'提交编译稿 v'+((latest?.version||0)+1))+'</button></div></form></details>';
}

function topicReviewSections(t,w){
  const sorted=[...w.assignments].sort((a,b)=>Number(b.can_submit)-Number(a.can_submit)||Number(b.active)-Number(a.active)||Number(!!b.submissions.length)-Number(!!a.submissions.length));
  const manuscripts=sorted.length?'<section class="panel" data-topic-manuscripts><h2>编译稿与返修</h2>'+sorted.map(a=>{
    const latest=topicCurrentSubmission(a),history=a.submissions.filter(s=>s.id!==latest?.id),longTitle=a.title.length>60,title=longTitle?a.title.slice(0,48)+'…':a.title,status=!a.active?'已调整分工':({awaiting_submission:'待交稿',pending:'待审',returned:'返修',final:'已定稿'}[a.status]||a.status);
    return '<article class="topic-assignment" data-assignment-card="'+esc(a.id)+'" data-mine="'+a.can_submit+'"><h3>'+esc(title)+' <span class="badge neutral">'+esc(status)+'</span></h3>'+(longTitle?'<details><summary>完整题名</summary><p>'+esc(a.title)+'</p></details>':'')+'<p>编译者：'+esc(a.author_name)+(a.country?' · 分工：'+esc(a.country):'')+'</p>'+(a.source||a.candidate_id?'<details><summary>采用出处与报告依据</summary>'+(a.source?'<p class="collaboration-note">'+esc(a.source)+'</p>':'')+(a.candidate_id?'<p>所据选题报告版本：'+esc(a.candidate_item||'未注明项目位置')+'</p><a class="button" href="/api/collaboration/topics/'+esc(t.id)+'/candidates/'+esc(a.candidate_id)+'/file" download>下载所据选题报告</a>':'')+'</details>':'')+(latest?topicReviewManuscript(latest,a):'<p class="muted">当前编译者尚未提交编译稿。</p>')+(history.length?'<details><summary>此前 '+history.length+' 版稿件及退回意见</summary>'+history.map(s=>topicReviewManuscript(s,a)).join('')+'</details>':'')+(a.can_submit?topicReviewForm(t,w,a):'')+(a.active&&t.can_manage&&latest&&a.status==='pending'?'<button class="button primary" data-action="topic-finals-confirm" data-topic="'+esc(t.id)+'" data-id="'+esc(a.id)+'">确认当前稿件定稿</button>'+topicReviewForm(t,w,a,true):'')+'</article>';
  }).join('')+'</section>':'';
  const meetings='<section class="panel"><div class="between wrap"><h2>选题会决定</h2>'+(w.meeting_version?'<a class="button" href="/api/collaboration/topics/'+esc(t.id)+'/materials/export" download>下载本期过程材料</a>':'')+'</div>'+(w.meetings.length?topicReviewDecision(w.meetings[0])+(w.meetings.length>1?'<details><summary>此前 '+(w.meetings.length-1)+' 版会议决定</summary>'+w.meetings.slice(1).map(topicReviewDecision).join('')+'</details>':''):'<p class="muted">尚未记录会议决定。负责人可保存实际会议材料及采用文章分工。</p>')+'</section>';
  return manuscripts+topicFinalSections(t,w)+meetings;
}

function topicReviewAssignmentRow(a,t,candidates){
  const id=a.id||crypto.randomUUID();
  const people=[...t.participants];if(a.author_id&&!people.some(p=>p.id===a.author_id))people.push({id:a.author_id,name:a.author_name||'原编译者（已不在当前参与者中）',active:0});
  return '<fieldset class="topic-decision-row" data-assignment-row data-id="'+esc(a.id||'')+'"><legend>采用文章与分工</legend><div class="field"><label for="title-'+id+'">题名或报告项目 *</label><input id="title-'+id+'" name="title" maxlength="500" value="'+esc(a.title||'')+'" required></div><div class="field"><label for="author-'+id+'">编译研究员 *</label><select id="author-'+id+'" name="author_id" required>'+people.map(p=>'<option value="'+esc(p.id)+'" '+(p.id===a.author_id?'selected':'')+'>'+esc(p.name)+(p.active?'':'（当前不可分工）')+'</option>').join('')+'</select></div><div class="field"><label for="source-'+id+'">出处或站外链接（可选）</label><textarea id="source-'+id+'" name="source" maxlength="4000" rows="2">'+esc(a.source||'')+'</textarea></div><details><summary>报告位置与国家分工（可选）</summary><div class="stack"><div class="field"><label for="candidate-'+id+'">所据选题报告版本</label><select id="candidate-'+id+'" name="candidate_id"><option value="">不指定报告</option>'+candidates.map(c=>'<option value="'+esc(c.id)+'" '+(c.id===a.candidate_id?'selected':'')+'>'+esc(c.author_name)+' · v'+c.version+' · '+esc(c.name)+'</option>').join('')+'</select></div><div class="field"><label for="item-'+id+'">报告项目或页码</label><input id="item-'+id+'" name="candidate_item" maxlength="1000" value="'+esc(a.candidate_item||'')+'"></div><div class="field"><label for="country-'+id+'">国家或范围分工</label><input id="country-'+id+'" name="country" maxlength="500" value="'+esc(a.country||'')+'"></div></div></details><button class="button" type="button" data-action="topic-review-remove">移除此项</button></fieldset>';
}

async function topicReviewMeeting(tid){
  const base='/api/collaboration/topics/'+encodeURIComponent(tid),[t,w,c]=await Promise.all([api(base),api(base+'/workflow'),api(base+'/candidates')]);
  if(!t.can_manage)throw new Error('只有本期有效负责人可记录会议决定。');
  modal(w.meeting_version?'修改会议决定':'记录会议决定','<form data-form="topic-review-meeting" data-topic="'+esc(tid)+'" data-topic-version="'+t.version+'" data-meeting-version="'+w.meeting_version+'" data-request="'+crypto.randomUUID()+'"><p>保存实际决定；每篇分工只填题名或项目及编译者，出处和报告关联可以后补。修改会保留此前决定。</p><div class="stack"><div class="field"><label for="meeting-note">简短会议决定（可选）</label><textarea id="meeting-note" name="note" maxlength="4000" rows="3">'+esc(w.meetings[0]?.note||'')+'</textarea></div><div class="field"><label for="meeting-file">会议材料文件（可选）</label><input id="meeting-file" name="file" type="file" accept=".docx,.pdf,.txt,.md"><p class="form-help">DOCX、PDF、TXT、Markdown，最多20 MB。此前会议原件继续留在历史中。</p></div></div><div data-assignment-rows>'+w.assignments.filter(a=>a.active).map(a=>topicReviewAssignmentRow(a,t,c.items)).join('')+'</div><button class="button" type="button" data-action="topic-review-add">添加采用文章</button><div class="form-error" role="alert"></div><div data-topic-review-conflict></div><div class="form-actions"><button class="button primary" type="submit">保存会议决定 v'+(w.meeting_version+1)+'</button></div></form>',true);
  const form=document.querySelector('[data-form="topic-review-meeting"]');form._topic=t;form._candidates=c.items;
}

function topicReviewConflictContent(t,w,a,review){
  const latest=topicCurrentSubmission(a);
  return '<section class="notice"><h3>请核对最新交接</h3><p>'+esc(t.theme)+' · 本期信息 v'+t.version+' · 会议决定 v'+w.meeting_version+'</p>'+(w.meetings[0]?topicReviewDecision(w.meetings[0]):'')+(a?'<p>当前分工：'+esc(a.title)+' · '+esc(a.author_name)+' · '+esc({returned:'返修',pending:'待审',final:'已定稿'}[a.status]||'待交稿')+'</p>':'')+(latest?topicReviewFile(latest,'下载最新编译稿核对'):'')+'<p>当前文件与说明已保留。核对最新决定和原件后继续。</p><button type="button" class="button" data-action="topic-review-rebase">'+(review?'已核对，保留意见审阅最新稿':'已核对，保留输入继续交接')+'</button></section>';
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action]');if(!button?.dataset.action.startsWith('topic-review-'))return;
  try{
    const action=button.dataset.action,form=button.closest('form');
    if(action==='topic-review-meeting')await topicReviewMeeting(button.dataset.id);
    else if(action==='topic-review-mine'){const card=document.querySelector('[data-assignment-card][data-mine="true"]');card?.scrollIntoView({block:'start'});const panel=card?.querySelector('[data-topic-handoff]');if(panel){panel.open=true;panel.querySelector('textarea').focus({preventScroll:true});}}
    else if(action==='topic-review-add')form.querySelector('[data-assignment-rows]').insertAdjacentHTML('beforeend',topicReviewAssignmentRow({},form._topic,form._candidates));
    else if(action==='topic-review-remove')button.closest('[data-assignment-row]').remove();
    else if(action==='topic-review-rebase'){
      const base='/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic),[t,w]=await Promise.all([api(base),api(base+'/workflow')]),a=w.assignments.find(a=>a.id===form.dataset.assignment),latest=form.dataset.form==='topic-review-return'?topicCurrentSubmission(a):a?.submissions[0];
      if(form.dataset.form!=='topic-review-meeting'&&(!a?.active||(form.dataset.form==='topic-review-draft'&&!a.can_submit)||(form.dataset.form==='topic-review-return'&&(!t.can_manage||!latest||a.status!=='pending'))))throw new Error('当前分工或权限已经变化，原文件和说明仍在表单中，请联系负责人核对。');
      form.dataset.topicVersion=t.version;form.dataset.meetingVersion=w.meeting_version;form.dataset.version=latest?.version||0;form.dataset.submission=latest?.id||'';form.dataset.request=crypto.randomUUID();form._conflict=false;
      const type=form.dataset.form;form.querySelector('[type=submit]').textContent=type==='topic-review-meeting'?'保存会议决定 v'+(w.meeting_version+1):type==='topic-review-draft'?'提交编译稿 v'+((latest?.version||0)+1):'退回版本 '+latest?.version;
      form.querySelector('[data-topic-review-conflict]').innerHTML='';form.querySelector('.form-error').textContent='已按最新交接继续，当前文件和输入已保留。';
    }
  }catch(error){toast(error.message);}
});

document.addEventListener('submit',async event=>{
  const form=event.target,type=form.dataset.form;if(!['topic-review-meeting','topic-review-draft','topic-review-return'].includes(type))return;
  event.preventDefault();const button=form.querySelector('[type=submit]'),error=form.querySelector('.form-error'),account=state.me?.id;button.disabled=true;error.textContent='';
  const base='/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic);
  try{
    if(form._conflict)throw new Error('请先核对最新交接，当前文件与说明已保留。');
    const fd=new FormData(form),data={request_id:form.dataset.request,topic_version:Number(form.dataset.topicVersion),meeting_version:Number(form.dataset.meetingVersion),note:fd.get('note')};
    let path;
    if(type==='topic-review-meeting'){
      data.version=Number(form.dataset.meetingVersion);data.assignments=[...form.querySelectorAll('[data-assignment-row]')].map(row=>{const a={};for(const key of ['title','author_id','source','candidate_id','candidate_item','country'])a[key]=row.querySelector('[name="'+key+'"]').value;if(row.dataset.id)a.id=row.dataset.id;return a;});path=base+'/meetings';
    }else if(type==='topic-review-draft'){data.version=Number(form.dataset.version);path=base+'/assignments/'+encodeURIComponent(form.dataset.assignment)+'/submissions';}
    else{data.submission_id=form.dataset.submission;path=base+'/assignments/'+encodeURIComponent(form.dataset.assignment)+'/returns';}
    // Only this actual handoff is posted; optional links are retained as text.
    const upload=new FormData();upload.set('data',JSON.stringify(data));const file=form.querySelector('[name=file]').files[0];if(file)upload.set('file',file);
    await api(path,{method:'POST',body:upload});if(account!==state.me?.id||!form.isConnected)return;
    closeModal();await route();toast(type==='topic-review-meeting'?'会议决定已留档':type==='topic-review-draft'?'编译稿已提交，等待负责人审阅':'退回意见已保存到具体版本');
    if(type!=='topic-review-meeting')document.querySelector('[data-assignment-card="'+form.dataset.assignment+'"]')?.scrollIntoView({block:'start'});
  }catch(e){if(!form.isConnected)return;error.textContent=e.message;if(e.status===409){form._conflict=true;try{const [t,w]=await Promise.all([api(base),api(base+'/workflow')]);form.querySelector('[data-topic-review-conflict]').innerHTML=topicReviewConflictContent(t,w,w.assignments.find(a=>a.id===form.dataset.assignment),type==='topic-review-return');}catch(check){error.textContent=check.message;}}}finally{if(form.isConnected)button.disabled=false;}
});
