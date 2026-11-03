'use strict';

function handoffStatus(status){return {pending:'待审',returned:'退回',approved:'通过',legacy_final:'旧定稿'}[status]||status;}
function handoffUpload(t,stage,material=null){
  if(!(material?material.can_submit:t.can_submit)||stage==='compilation'&&t.stage!=='compilation')return '';
  const id=material?.ref||'new',key='handoff-'+id.replaceAll(':','-');
  return '<details class="handoff-upload '+(!material&&!t.can_enter_compilation?'handoff-primary-upload':'')+'" '+(!material&&!t.materials.some(m=>m.stage===stage)?'open':'')+'><summary>'+(material?'提交新版本':'上传'+(stage==='selection'?'选题':'编译')+'材料')+'</summary><form data-form="handoff-upload" data-account="'+esc(state.me.id)+'" data-topic="'+esc(t.id)+'" data-stage="'+stage+'" data-material="'+esc(material?.ref||'')+'" data-token="'+esc(t.token)+'" data-request="'+crypto.randomUUID()+'">'+(!material?'<label class="field" for="'+key+'-title">材料题名（可选）<input id="'+key+'-title" name="title" maxlength="500"></label>':'')+'<label class="field" for="'+key+'-file">文件<input id="'+key+'-file" name="file" type="file" accept=".pdf,.docx,.txt,.md" required></label><p class="form-help">PDF、DOCX、TXT 或 Markdown，最多 20 MB。</p><label class="field" for="'+key+'-note">说明（可选）<textarea id="'+key+'-note" name="note" maxlength="4000" rows="2"></textarea></label><div class="form-error" role="alert"></div><div data-handoff-conflict></div><button class="button primary" type="submit">'+(material?'保存新版本':'上传材料')+'</button></form></details>';
}
function handoffVersion(v){
  return '<div class="handoff-version"><strong>'+esc(v.name)+'</strong><div class="row wrap"><button class="link-button" data-action="handoff-view" data-version="'+esc(v.ref)+'" data-url="'+esc(v.file_url)+'">查看内容</button><a href="'+esc(v.file_url)+'" download>下载原件</a></div><p class="muted">'+(v.legacy?'原版本 ':'版本 ')+v.version+' · '+esc(v.author_name)+' · '+dateTime(v.created_at)+'</p>'+(v.note?'<p>'+esc(v.note)+'</p>':'')+v.reviews.map(r=>'<div class="handoff-review-result"><strong>'+handoffStatus(r.decision)+'</strong>'+(r.actor_name?' · '+esc(r.actor_name):'')+(r.note?'<p>'+esc(r.note)+'</p>':'')+(r.file_url?'<a href="'+esc(r.file_url)+'" download>审阅附件：'+esc(r.name)+'</a>':'')+'</div>').join('')+'</div>';
}
function handoffReview(t,v){
  if(!v.can_review)return '';
  const id=v.ref.replaceAll(':','-');
  return '<div class="handoff-review"><form data-form="handoff-review" data-account="'+esc(state.me.id)+'" data-topic="'+esc(t.id)+'" data-version="'+esc(v.ref)+'" data-token="'+esc(t.token)+'" data-request="'+crypto.randomUUID()+'"><details><summary>添加意见或附件</summary><label class="field" for="review-'+id+'">意见（可选）<textarea id="review-'+id+'" name="note" rows="2" maxlength="4000"></textarea></label><label class="field" for="review-file-'+id+'">附件（可选）<input id="review-file-'+id+'" type="file" name="file" accept=".pdf,.docx,.txt,.md"></label></details><div class="form-error" role="alert"></div><div data-handoff-conflict></div><div class="row wrap"><button class="button" type="submit" name="decision" value="returned">退回</button><button class="button primary" type="submit" name="decision" value="approved">通过此版</button></div></form></div>';
}
function handoffMaterials(t,stage){
  const items=t.materials.filter(m=>m.stage===stage).sort((a,b)=>Number(b.status==='pending')-Number(a.status==='pending')||Number(b.owner_id===state.me.id)-Number(a.owner_id===state.me.id));
  return '<section class="handoff-materials" aria-label="'+(stage==='selection'?'选题':'编译')+'材料">'+handoffUpload(t,stage)+(items.length?items.map(m=>{const v=m.versions[0],prior=t.materials.find(p=>p.versions.some(v=>v.ref===m.source_ref));return '<article class="handoff-material" data-material-ref="'+esc(m.ref)+'"><div class="between wrap"><h2>'+esc(m.title)+'</h2><span class="badge '+(m.status==='approved'||m.status==='legacy_final'?'verified':'pending')+'">'+handoffStatus(m.status)+'</span></div><p class="handoff-owner">'+esc(m.owner_name)+(m.owner_id===state.me.id?' · 我的材料':'')+'</p>'+handoffVersion(v)+handoffReview(t,v)+handoffUpload(t,stage,m)+(m.versions.length>1?'<details><summary>此前 '+(m.versions.length-1)+' 个版本</summary>'+m.versions.slice(1).map(handoffVersion).join('')+'</details>':'')+(prior?'<details><summary>接续的旧材料</summary>'+prior.versions.map(handoffVersion).join('')+'</details>':'')+'</article>';}).join(''):'<p class="handoff-empty">'+(stage==='compilation'&&t.stage==='selection'?'负责人进入编译后可上传编译材料。':'暂无'+(stage==='selection'?'选题':'编译')+'材料。')+'</p>')+'</section>';
}

async function handoffLegacy(tid){
  const account=state.me?.id,w=await api('/api/collaboration/topics/'+encodeURIComponent(tid)+'/workflow');
  if(account!==state.me?.id)return;
  const t=await api('/api/collaboration/topics/'+encodeURIComponent(tid));if(account!==state.me?.id)return;
  modal('旧会议与成果',(w.meetings.length?w.meetings.map(topicReviewDecision).join(''):'<p>暂无旧会议记录。</p>')+workbenchTopicProducts({...t,can_submit_summary:false},w));
  // Historical reading never offers mutation of the former meeting workflow.
  document.querySelector('.drawer-body')?.querySelectorAll('button[data-action^="topic-final"],button[data-action^="topic-review"]').forEach(b=>b.remove());
}

document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-action="handoff-legacy"],[data-action="handoff-refresh"],[data-action="handoff-view"]');if(!b)return;
  event.preventDefault();
  try{
    if(b.dataset.action==='handoff-view'){
      const account=state.me?.id,tid=b.closest('[data-collaboration-topic]')?.dataset.collaborationTopic||workbenchState.topic?.id;
      const result=await api('/api/collaboration/topics/'+encodeURIComponent(tid)+'/handoff-preview?version_ref='+encodeURIComponent(b.dataset.version));
      if(account!==state.me?.id||!b.isConnected)return;
      modal(result.name||'材料内容','<div class="handoff-preview">'+(result.status==='ready'?result.segments.map(s=>'<p>'+esc(s.text)+'</p>').join(''):'<p>此文件暂不能预览，请下载原件查看。</p>')+'</div><a class="button" href="'+esc(b.dataset.url)+'" download>下载原件</a>');return;
    }
    if(b.dataset.action==='handoff-legacy'){await handoffLegacy(b.dataset.id);return;}
    const form=b.closest('form');if(form.dataset.account!==state.me?.id)throw new Error('账号已切换，请重新打开材料。');
    const t=await api('/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic)+'/handoffs');
    if(form.dataset.account!==state.me?.id||!form.isConnected)return;
    const material=t.materials.find(m=>m.ref===form.dataset.material),v=t.materials.flatMap(m=>m.versions).find(v=>v.ref===form.dataset.version);
    if(form.dataset.form==='handoff-review'?!v?.can_review:!(material?material.can_submit:t.can_submit))throw new Error('此材料或权限已变化，请查看最新材料。当前输入仍保留。');
    form.dataset.token=t.token;form.dataset.request=crypto.randomUUID();form._attempt=null;form._decision=null;form._conflict=false;form.querySelectorAll('input,textarea').forEach(input=>input.disabled=false);
    form.querySelector('[data-handoff-conflict]').innerHTML='';form.querySelector('.form-error').textContent='状态已刷新，文件与输入已保留。';
  }catch(error){const form=b.closest('form');if(form)form.querySelector('.form-error').textContent=error.message;else toast(error.message);}
});

document.addEventListener('submit',async event=>{
  const form=event.target,type=form.dataset.form;if(!['handoff-upload','handoff-review'].includes(type))return;
  event.preventDefault();if(form.dataset.saving==='true')return;
  const account=state.me?.id,error=form.querySelector('.form-error');
  if(form.dataset.account!==account){error.textContent='账号已切换，请重新打开材料。';return;}
  if(form._attempt&&type==='handoff-review'&&event.submitter?.value!==form._decision){error.textContent='请重试原审阅决定，先核对保存结果。';return;}
  if(form._conflict){error.textContent='请先刷新本期状态，当前输入仍保留。';return;}
  form.dataset.saving='true';form.querySelectorAll('[type=submit]').forEach(b=>b.disabled=true);error.textContent='';
  try{
    if(!form._attempt){
      const fd=new FormData(form),data={token:form.dataset.token,request_id:form.dataset.request,note:String(fd.get('note')||'')};
      if(type==='handoff-upload'){data.stage=form.dataset.stage;if(form.dataset.material)data.material_ref=form.dataset.material;const title=String(fd.get('title')||'').trim();if(title)data.title=title;}
      else{data.version_ref=form.dataset.version;data.decision=event.submitter?.value;if(!data.decision)throw new Error('请选择通过或退回。');}
      const body=new FormData();body.set('data',JSON.stringify(data));const file=fd.get('file');if(file?.size)body.set('file',file);else if(type==='handoff-upload')throw new Error('请选择材料文件。');
      form._attempt=body;form._decision=data.decision;
    }
    form.querySelectorAll('input,textarea').forEach(input=>input.disabled=true);
    const result=await api('/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic)+(type==='handoff-upload'?'/handoffs':'/handoff-reviews'),{method:'POST',body:form._attempt});
    if(account!==state.me?.id||!form.isConnected)return;
    await route();toast(result.reused?'已保存，已读取当前状态':type==='handoff-upload'?'材料已上传':'审阅已保存');
  }catch(e){
    if(form.isConnected){error.textContent=e.status?e.message:e.message+' 请重试核对这次提交。';if(e.status&&e.status!==409){form._attempt=null;form._decision=null;form.querySelectorAll('input,textarea').forEach(input=>input.disabled=false);}if(e.status===409){form._conflict=true;form.querySelectorAll('input,textarea').forEach(input=>input.disabled=false);form.querySelector('[data-handoff-conflict]').innerHTML='<button class="button" type="button" data-action="handoff-refresh">刷新状态，保留输入</button>';}}
  }finally{form.dataset.saving='false';if(form.isConnected)form.querySelectorAll('[type=submit]').forEach(b=>b.disabled=!!(form._attempt&&type==='handoff-review'&&b.value!==form._decision));}
});
