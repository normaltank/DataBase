'use strict';

let handoffReadGeneration=0;
const handoffFlowRoots=new Set();
// Native draft nodes keep selected File objects across a local route change.
// Keys include account and concrete version; nothing is copied to another target.
const handoffDraftForms=new Set(),handoffDrafts=new Map();
function handoffDraftKey(form){return [form.dataset.account,form.dataset.topic,form.dataset.form,form.dataset.stage||'',form.dataset.material||'',form.dataset.version||''].join('|');}
function handoffRememberDrafts(){
  for(const form of handoffDraftForms)if(!form.isConnected){
    if(form._attempt||form._conflict||[...form.querySelectorAll('textarea,input')].some(input=>input.type==='file'?input.files.length:input.value))handoffDrafts.set(handoffDraftKey(form),form);
    handoffDraftForms.delete(form);
  }
  document.querySelectorAll('[data-form="handoff-review"],[data-form="handoff-upload"]').forEach(form=>{
    if(handoffDraftForms.has(form)||form.dataset.account!==state.me?.id)return;
    const saved=handoffDrafts.get(handoffDraftKey(form));
    if(saved&&saved!==form&&!saved.isConnected){
      saved.dataset.allowed='true';
      if(!saved._attempt&&!saved._conflict)saved.dataset.token=form.dataset.token;
      saved.querySelectorAll('[type=submit]').forEach(button=>button.disabled=saved.dataset.saving==='true'||!!saved._conflict||!!(saved._attempt&&saved.dataset.form==='handoff-review'&&button.value!==saved._decision));
      form.replaceWith(saved);handoffDraftForms.add(saved);handoffDrafts.delete(handoffDraftKey(saved));
    }else handoffDraftForms.add(form);
  });
  for(const [key,form] of handoffDrafts){
    if(form.isConnected||form.dataset.account!==state.me?.id)continue;
    const topic=document.querySelector('[data-collaboration-topic]');if(topic?.dataset.collaborationTopic!==form.dataset.topic)continue;
    const item=workbenchState.board?.materials.find(item=>item.versions.some(version=>version.ref===form.dataset.version));
    const material=[...topic.querySelectorAll('[data-material-ref]')].find(element=>element.dataset.materialRef===item?.ref);
    if(!material)continue;
    const version=item.versions.find(version=>version.ref===form.dataset.version);
    const wrapper=document.createElement('details');wrapper.className='handoff-retained-draft';
    wrapper.innerHTML='<summary>保留的版本 '+esc(version.version)+' 审阅草稿</summary>';
    form.dataset.allowed='false';form.querySelectorAll('[type=submit]').forEach(button=>button.disabled=true);
    form.querySelector('.form-error').textContent='此版当前不可提交，原草稿已保留。';
    wrapper.append(form);material.append(wrapper);handoffDraftForms.add(form);handoffDrafts.delete(key);
  }
}
function handoffSyncActions(form){
  const root=form.closest('[data-material-ref]')?.querySelector('.handoff-lineage');
  const material=workbenchState.board?.materials.find(item=>item.ref===form.closest('[data-material-ref]')?.dataset.materialRef);
  if(root&&material)handoffFlowUpdate(root,material,root.querySelector('[data-handoff-version]').value);
}
async function handoffRefreshNew(form){
  const account=state.me?.id,load=state.loadId;
  const t=await api('/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic)+'/handoffs');
  if(account!==state.me?.id||load!==state.loadId||!form.isConnected)return;
  workbenchState.board=t;
  const container=form.closest('.handoff-materials'),fresh=document.createElement('div');fresh.innerHTML=handoffMaterials(t,form.dataset.stage);
  for(const material of fresh.querySelectorAll('[data-material-ref]'))if(![...container.querySelectorAll('[data-material-ref]')].some(item=>item.dataset.materialRef===material.dataset.materialRef))container.append(material);
  container.querySelector('.handoff-empty')?.remove();
  container.querySelectorAll('form').forEach(item=>{if(!item._attempt&&!item._conflict)item.dataset.token=t.token;});
}
function handoffFlowUpdate(root,material,version=material.versions[0].ref,review=''){
  if(root.dataset.lineageAccount!==state.me?.id)return;
  let host=root.querySelector('.actual-flow');
  if(!host){root.querySelector('.handoff-graph').insertAdjacentHTML('beforeend',visualFlowHtml());host=root.querySelector('.actual-flow');}
  if(!root._graphPrepared){root._graphPrepared=true;root.querySelector('.handoff-graph').open=false;}
  const versions=[...material.versions].reverse(),nodes=[],edges=[];
  for(const [index,v] of versions.entries()){
    nodes.push({id:'version:'+v.ref,label:`${v.ref===material.versions[0].ref?'当前版':'版本'} ${v.version} · ${handoffStatus(v.status)}\n成员提交`});
    if(index)edges.push({id:'registered:'+v.ref,source:'version:'+versions[index-1].ref,target:'version:'+v.ref,label:'顺序'});
    for(const r of v.reviews){nodes.push({id:'review:'+r.id,label:`版本 ${v.version} · ${handoffStatus(r.decision)}\n负责人审阅`});edges.push({id:'reviewed:'+r.id,source:'version:'+v.ref,target:'review:'+r.id,label:'审阅'});}
  }
  visualFlowUpdate(host,{nodes,edges,layout:'material-lineage',legend:'',selected:['version:'+version,...(review?['review:'+review]:[])]},id=>{
    if(id.startsWith('version:'))handoffSelect(root,id.slice(8));
    else{const rid=id.slice(7),v=material.versions.find(v=>v.reviews.some(r=>r.id===rid));if(v)handoffSelect(root,v.ref,rid);}
  });
}
const handoffFlowObserver=new MutationObserver(()=>{
  handoffRememberDrafts();
  for(const root of handoffFlowRoots)if(!root.isConnected)handoffFlowRoots.delete(root);
  document.querySelectorAll('.handoff-lineage').forEach(root=>{if(handoffFlowRoots.has(root))return;const material=workbenchState.board?.materials?.find(m=>m.ref===root.closest('[data-material-ref]')?.dataset.materialRef);if(material){handoffFlowRoots.add(root);handoffFlowUpdate(root,material);}});
});
handoffFlowObserver.observe(document.documentElement,{childList:true,subtree:true});

function handoffStatus(status){return {pending:'待审',returned:'退回',approved:'通过',legacy_final:'旧定稿'}[status]||status;}
function handoffUpload(t,stage,material=null){
  if(!(material?material.can_submit:t.can_submit)||stage==='compilation'&&t.stage!=='compilation')return '';
  const id=material?.ref||'new',key='handoff-'+id.replaceAll(':','-');
  return '<details class="handoff-upload '+(!material&&!t.can_enter_compilation?'handoff-primary-upload':'')+'" '+(!material&&!t.materials.some(m=>m.stage===stage)?'open':'')+'><summary>'+(material?'提交新版本':'上传'+(stage==='selection'?'选题':'编译')+'材料')+'</summary><form data-form="handoff-upload" data-account="'+esc(state.me.id)+'" data-topic="'+esc(t.id)+'" data-stage="'+stage+'" data-material="'+esc(material?.ref||'')+'" data-source="'+esc(material?.legacy?material.versions[0].ref:'')+'" data-token="'+esc(t.token)+'" data-request="'+crypto.randomUUID()+'">'+(!material?'<label class="field" for="'+key+'-title">材料题名（可选）<input id="'+key+'-title" name="title" maxlength="500"></label>':'')+'<label class="field" for="'+key+'-file">文件<input id="'+key+'-file" name="file" type="file" accept=".pdf,.docx,.txt,.md" required></label><p class="form-help">PDF、DOCX、TXT 或 Markdown，最多 20 MB。</p><label class="field" for="'+key+'-note">说明（可选）<textarea id="'+key+'-note" name="note" maxlength="4000" rows="2"></textarea></label><div class="form-error" role="alert"></div><div data-handoff-conflict></div><button class="button primary" type="submit">'+(material?'保存新版本':'上传材料')+'</button></form></details>';
}
function handoffVersion(v){
  return '<div class="handoff-version" data-reading-version="'+esc(v.ref)+'"><strong>'+esc(v.name||'原件名称未记录')+'</strong>'+(v.file_url?'<div class="row wrap"><button class="link-button" data-action="handoff-view" data-version="'+esc(v.ref)+'" data-url="'+esc(v.file_url)+'">查看内容</button><a href="'+esc(v.file_url)+'" download>下载原件</a></div>':'<p>此版原件暂不可用。</p>')+'<details class="desk-file-meta"><summary>提交信息与说明</summary><p class="muted">'+(v.legacy?'原版本 ':'版本 ')+esc(v.version)+' · 提交人：'+esc(v.author_name||'未记录')+' · '+handoffTime(v.created_at)+'</p><p>'+esc(v.note||'')+'</p></details><div class="handoff-version-reviews">'+(v.reviews.length?v.reviews.map(r=>'<div class="handoff-review-result" data-reading-review="'+esc(r.id)+'"><strong>'+handoffStatus(r.decision)+'</strong> · 审阅人：'+esc(r.actor_name||r.author_name||'未记录')+'<p class="muted">'+handoffTime(r.created_at)+'</p><p>'+esc(r.note||'')+'</p>'+(r.file_url?'<a href="'+esc(r.file_url)+'" download>审阅附件：'+esc(r.name||'下载附件')+'</a>':'')+'</div>').join(''):'')+'</div></div>';
}
function handoffTime(value){return value?esc(/^\d{4}-\d{2}-\d{2}$/.test(value)?value:new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Singapore',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})):'时间未记录';}
function handoffLineageReading(m,v,review=''){
  return '<div class="between wrap desk-reading-label"><h3>'+(v.ref===m.versions[0].ref?'原件与意见':'历史版 '+esc(v.version)+' · '+handoffStatus(v.status))+'</h3><span class="muted">'+(review?'负责人审阅':'')+'</span></div>'+handoffVersion(v);
}
function handoffLineage(m){
  const current=m.versions[0],versions=[...m.versions].reverse();
  const record=v=>'<div class="handoff-lineage-row" data-lineage-version="'+esc(v.ref)+'"><div class="handoff-submission"><button type="button" class="handoff-version-link" data-action="handoff-select" data-version="'+esc(v.ref)+'" data-review="" aria-pressed="'+(v.ref===current.ref)+'" aria-label="查看版本 '+v.version+'"><strong>版本 '+v.version+(v.ref===current.ref?' · 当前版':'')+'</strong></button><span>'+esc(v.author_name||'责任人未记录')+' 提交 · '+handoffTime(v.created_at)+'</span></div><div class="handoff-review-events">'+(v.reviews.length?v.reviews.map(r=>'<button type="button" class="handoff-review-link" data-action="handoff-select" data-version="'+esc(v.ref)+'" data-review="'+esc(r.id)+'" aria-label="查看版本 '+v.version+' 的'+handoffStatus(r.decision)+'审阅" aria-pressed="false">'+handoffStatus(r.decision)+' · '+esc(r.actor_name||r.author_name||'责任人未记录')+' · '+handoffTime(r.created_at)+(r.note?'<span>'+esc(r.note)+'</span>':'')+'</button>').join(''):'<span class="muted">'+handoffStatus(v.status)+' · 暂无审阅记录</span>')+'</div></div>';
  return '<section class="handoff-lineage" data-lineage-account="'+esc(state.me.id)+'" aria-label="材料版本与审阅沿革"><div class="between wrap handoff-lineage-toolbar"><h3>材料沿革</h3><div class="row wrap"><button type="button" class="button" data-action="handoff-read-refresh">刷新材料状态</button><button type="button" class="button" data-action="handoff-current">回当前版</button></div></div><p data-lineage-status role="status"></p><label class="handoff-version-picker">所看版本<select data-handoff-version aria-label="选择材料版本">'+m.versions.map(v=>'<option value="'+esc(v.ref)+'">版本 '+esc(v.version)+(v.ref===current.ref?' · 当前版':'')+' · '+handoffStatus(v.status)+'</option>').join('')+'</select></label><button type="button" class="button handoff-lineage-jump" data-action="handoff-locate-reading">查看所选版本 '+esc(current.version)+' 的原件与意见</button>'+ '<details class="handoff-track-details"><summary>版本交接 · '+versions.length+' 版</summary><div class="handoff-lineage-tracks">'+versions.map(record).join('')+'</div></details><details class="handoff-graph"><summary>完整关系图</summary><p class="handoff-graph-hint">箭头分别表示版本顺序和该版的实际审阅。选择节点可阅读；审阅在材料动作区进行。</p>'+visualFlowHtml()+'</details><div class="handoff-lineage-reading" data-handoff-reading aria-live="polite">'+handoffLineageReading(m,current)+'</div></section>';
}
function handoffSelect(root,versionRef,review='',animate=true){
  window.objectActions?.close(false);
  if(root.dataset.lineageAccount!==state.me?.id)return;
  const material=root.closest('[data-material-ref]'),m=workbenchState.board?.materials.find(m=>m.ref===material.dataset.materialRef),v=m?.versions.find(v=>v.ref===versionRef);
  if(!v||review&&!v.reviews.some(r=>r.id===review))return;
  root.querySelectorAll('[data-action="handoff-select"]').forEach(b=>{const selected=b.dataset.version===v.ref&&(!b.dataset.review||b.dataset.review===review||!review);b.setAttribute('aria-pressed',String(selected));});
  root.querySelectorAll('[data-lineage-version]').forEach(row=>{const selected=row.dataset.lineageVersion===v.ref;row.classList.toggle('is-selected',selected);row.querySelectorAll('path').forEach(path=>path.classList.toggle('is-selected',selected&&(!review||path.dataset.lineageReview===review)));});
  root.querySelector('[data-handoff-version]').value=v.ref;
  root.querySelector('[data-action=handoff-current]').hidden=v.ref===m.versions[0].ref;
  const context=root.closest('.handoff-material').querySelector('.handoff-current-actions>h3');if(context)context.textContent='写入当前版 '+m.versions[0].version+' · '+handoffStatus(m.status);
  root.querySelector('[data-action="handoff-locate-reading"]').textContent='查看所选版本 '+v.version+' 的原件与意见';
  const reading=root.querySelector('[data-handoff-reading]');
  const signature=JSON.stringify([v,review]);
  if(reading._signature!==signature){const html=handoffLineageReading(m,v,review);if(reading.innerHTML!==html)reading.innerHTML=html;reading._signature=signature;}
  reading.querySelectorAll('[data-reading-review]').forEach(item=>item.classList.toggle('is-selected',item.dataset.readingReview===review));
  handoffFlowUpdate(root,m,v.ref,review);
  if(typeof deskPreview==='function')deskPreview(material);

}
async function handoffReadRefresh(root){
  if(root._refreshing)return;
  const account=state.me?.id,load=state.loadId,material=root.closest('[data-material-ref]'),tid=material.closest('[data-collaboration-topic]').dataset.collaborationTopic,status=root.querySelector('[data-lineage-status]');
  if(root.dataset.lineageAccount!==account)return;
  const generation=++handoffReadGeneration;
  root._refreshing=true;status.textContent='正在读取材料状态…';
  try{
    const t=await api('/api/collaboration/topics/'+encodeURIComponent(tid)+'/handoffs');
    if(account!==state.me?.id||load!==state.loadId||!root.isConnected)return;
    if(generation!==handoffReadGeneration){status.textContent='已有更新的材料读取，可刷新此材料继续查看。';return;}
    const m=t.materials.find(m=>m.ref===material.dataset.materialRef);if(!m)throw Object.assign(new Error('此材料已不可读，请返回工作查找重新读取。'),{status:403});
    const previous=workbenchState.board?.materials.find(m=>m.ref===material.dataset.materialRef),active=document.activeElement;
    const currentVersion=m.versions[0],reviewForms=[...material.querySelectorAll('[data-form=handoff-review]')];
    if(currentVersion.can_review&&!reviewForms.some(form=>form.dataset.version===currentVersion.ref)){
      const actions=material.querySelector('.handoff-current-actions');
      if(actions)actions.insertAdjacentHTML('afterbegin',handoffReview(t,currentVersion));
    }
    workbenchState.board=t;
    const selected=root.querySelector('[data-handoff-version]').value,review=root.querySelector('[data-reading-review].is-selected')?.dataset.readingReview||'',fresh=document.createElement('div');fresh.innerHTML=handoffLineage(m);
    for(const selector of ['.handoff-lineage-tracks','[data-handoff-version]']){
      const old=root.querySelector(selector),replacement=fresh.querySelector(selector);
      if(JSON.stringify(previous)!==JSON.stringify(m)&&old.innerHTML!==replacement.innerHTML)old.innerHTML=replacement.innerHTML;
    }
    handoffSelect(root,m.versions.some(v=>v.ref===selected)?selected:m.versions[0].ref,review,false);
    if(active?.dataset.action==='handoff-select'&&!active.isConnected)[...root.querySelectorAll('[data-action="handoff-select"]')].find(b=>b.dataset.version===active.dataset.version&&b.dataset.review===active.dataset.review)?.focus({preventScroll:true});
    material.querySelector(':scope>.between>h2').textContent=m.title;material.querySelector('.handoff-owner').textContent=m.owner_name+(m.owner_id===account?' · 我的材料':'')+(m.legacy?' · 旧材料':'');
    root.querySelector('[data-handoff-version]').disabled=false;root.querySelector('[data-action="handoff-current"]').disabled=false;
    root.querySelector('[data-action="handoff-locate-reading"]').disabled=false;
    const badge=material.querySelector(':scope>.between>.badge');badge.textContent='当前版 '+m.versions[0].version+' · '+handoffStatus(m.status);badge.className='badge '+(['approved','legacy_final'].includes(m.status)?'verified':'pending');
    material.closest('.handoff-materials').querySelectorAll('form').forEach(form=>{
      const v=t.materials.flatMap(item=>item.versions).find(v=>v.ref===form.dataset.version),target=t.materials.find(item=>item.ref===form.dataset.material),allowed=form.dataset.form==='handoff-review'?!!v?.can_review:form.dataset.material?!!target?.can_submit:t.can_submit;
      form.dataset.allowed=String(allowed);if(!form._attempt&&!form._conflict)form.dataset.token=t.token;
      form.querySelectorAll('[type=submit]').forEach(b=>b.disabled=!allowed||form.dataset.saving==='true'||!!(form._attempt&&form.dataset.form==='handoff-review'&&b.value!==form._decision));
      if(!allowed){form.querySelector('.form-error').textContent='此版当前不可提交。文件与输入仍保留。';if(form.dataset.form==='handoff-review'&&form.dataset.saved!=='true'&&!form.closest('.handoff-retained-draft')&&form.dataset.version!==t.materials.find(item=>item.versions.some(version=>version.ref===form.dataset.version))?.versions[0].ref){const wrapper=document.createElement('details');wrapper.className='handoff-retained-draft';wrapper.innerHTML='<summary>保留的旧版审阅草稿</summary>';const area=form.closest('.handoff-review');area.before(wrapper);wrapper.append(area);}}
    });
    const actions=material.querySelector('.handoff-current-actions>p'),bound=material.querySelector('[data-form=handoff-review]')?.dataset.version,boundVersion=m.versions.find(v=>v.ref===bound);
    if(actions)actions.textContent=boundVersion&&bound!==m.versions[0].ref?'草稿绑定版本 '+boundVersion.version+'，当前版 '+m.versions[0].version:'';
    material.closest('.handoff-materials').querySelectorAll('.handoff-lineage').forEach(item=>{const data=t.materials.find(data=>data.ref===item.closest('[data-material-ref]').dataset.materialRef);if(data)handoffFlowUpdate(item,data,item.querySelector('[data-handoff-version]').value);});
    handoffFlowUpdate(root,m,root.querySelector('[data-handoff-version]').value,review);
    root._lastUpdated=handoffTime(new Date().toISOString());status.textContent='已更新 · '+root._lastUpdated;
  }catch(error){
    if(account!==state.me?.id||load!==state.loadId||!root.isConnected)return;
    if(generation!==handoffReadGeneration){status.textContent='已有更新的材料读取，可刷新此材料继续查看。';return;}
    if([401,403,404].includes(error.status)){
      material.closest('.handoff-materials').querySelectorAll('form [type=submit]').forEach(b=>{b.disabled=true;const form=b.closest('form');if(form)form.dataset.allowed='false';});
      material.closest('.handoff-materials').querySelectorAll('.handoff-material').forEach(item=>{
        item.querySelector('.actual-flow')?.remove();
        item.querySelectorAll('.handoff-lineage-tracks,[data-handoff-reading],[data-handoff-version]').forEach(el=>{el.replaceChildren();delete el._signature;});
        item.querySelectorAll('[data-handoff-version],[data-action="handoff-current"],[data-action="handoff-locate-reading"],form [type=submit]').forEach(b=>{b.disabled=true;const form=b.closest('form');if(form)form.dataset.allowed='false';});
        item.querySelector(':scope>.between>h2').textContent='材料暂不可读';item.querySelector(':scope>.between>.badge').textContent='权限待重新核对';item.querySelector('.handoff-owner').textContent='';
        item.querySelectorAll(':scope>details:not(.handoff-upload)').forEach(el=>el.remove());
        const title=item.querySelector('.handoff-current-actions h3');if(title)title.textContent='当前草稿';
      });
      if(workbenchState.board?.id===tid)workbenchState.board=null;
    }
    status.textContent='材料状态未更新：'+error.message+(root._lastUpdated?' 最后成功更新：'+root._lastUpdated+'。':'')+' 可再次刷新。文件与输入仍保留。';
  }finally{root._refreshing=false;}
}
function handoffReview(t,v){
  if(!v.can_review)return '';
  const id=v.ref.replaceAll(':','-');
  return '<div class="handoff-review"><h4 class="sr-only">审阅版本 '+esc(v.version)+'</h4><form data-form="handoff-review" data-account="'+esc(state.me.id)+'" data-topic="'+esc(t.id)+'" data-version="'+esc(v.ref)+'" data-token="'+esc(t.token)+'" data-request="'+crypto.randomUUID()+'"><details><summary>意见与附件</summary><label class="field" for="review-'+id+'">意见（可选）<textarea id="review-'+id+'" name="note" rows="2" maxlength="4000"></textarea></label><label class="field" for="review-file-'+id+'">附件（可选）<input id="review-file-'+id+'" type="file" name="file" accept=".pdf,.docx,.txt,.md"></label></details><div class="form-error" role="alert"></div><div data-handoff-conflict></div><div class="row wrap"><button class="button" type="submit" name="decision" value="returned">退回</button><button class="button primary" type="submit" name="decision" value="approved">通过此版</button></div></form></div>';
}
function handoffMaterials(t,stage){
  const items=t.materials.filter(m=>m.stage===stage).sort((a,b)=>Number(b.status==='pending')-Number(a.status==='pending')||Number(b.owner_id===state.me.id)-Number(a.owner_id===state.me.id));
  return '<section class="handoff-materials" aria-label="'+(stage==='selection'?'选题':'编译')+'材料">'+handoffUpload(t,stage)+(items.length?items.map(m=>{const v=m.versions[0],prior=t.materials.find(p=>p.versions.some(v=>v.ref===m.source_ref));return '<article class="handoff-material" data-material-ref="'+esc(m.ref)+'"><div class="between wrap"><h2>'+esc(m.title)+'</h2><span class="badge '+(m.status==='approved'||m.status==='legacy_final'?'verified':'pending')+'">当前版 '+esc(v.version)+' · '+handoffStatus(m.status)+'</span></div><p class="handoff-owner">'+esc(m.owner_name)+(m.owner_id===state.me.id?' · 我的材料':'')+(m.legacy?' · 旧材料':'')+'</p>'+handoffLineage(m)+(v.can_review||m.can_submit?'<div class="handoff-current-actions"><h3>写入当前版 '+esc(v.version)+' · '+handoffStatus(m.status)+'</h3><p class="muted"></p>'+handoffReview(t,v)+handoffUpload(t,stage,m)+'</div>':'')+(prior?'<details><summary>接续的旧材料 · '+esc(prior.title)+'</summary>'+prior.versions.map(handoffVersion).join('')+'</details>':'')+'</article>';}).join(''):'<p class="handoff-empty">'+(stage==='compilation'&&t.stage==='selection'?'负责人进入编译后可上传编译材料。':'暂无'+(stage==='selection'?'选题':'编译')+'材料。')+'</p>')+'</section>';
}

document.addEventListener('click',event=>{
  const b=event.target.closest('[data-action="handoff-select"],[data-action="handoff-current"]');if(!b)return;
  const root=b.closest('.handoff-lineage');
  handoffSelect(root,b.dataset.action==='handoff-current'?root.querySelector('[data-handoff-version] option').value:b.dataset.version,b.dataset.review||'');
  if(b.dataset.action==='handoff-current'){root.querySelector('.handoff-graph').open=true;const model=root.querySelector('.actual-flow')?._actualFlow;if(model?.instance)model.instance.focusSelected();else if(model)model.focusOnMount=true;}
});
document.addEventListener('change',event=>{if(event.target.matches('[data-handoff-version]'))handoffSelect(event.target.closest('.handoff-lineage'),event.target.value);});

document.addEventListener('click',event=>{
  const button=event.target.closest('[data-action="handoff-locate-reading"]');if(!button)return;
  const root=button.closest('.handoff-lineage');if(root.dataset.lineageAccount!==state.me?.id)return;
  root.querySelector('[data-handoff-reading]').scrollIntoView({block:'start',behavior:'instant'});
});
document.addEventListener('click',event=>{const b=event.target.closest('[data-action="handoff-read-refresh"]');if(b)handoffReadRefresh(b.closest('.handoff-lineage'));});

async function handoffLegacy(tid){
  const account=state.me?.id,load=state.loadId,generation=modalGeneration;
  const w=await api('/api/collaboration/topics/'+encodeURIComponent(tid)+'/workflow');
  if(account!==state.me?.id||load!==state.loadId||generation!==modalGeneration)return;
  const t=await api('/api/collaboration/topics/'+encodeURIComponent(tid));
  if(account!==state.me?.id||load!==state.loadId||generation!==modalGeneration)return;
  modal('旧会议、定稿与汇总',(w.meetings.length?w.meetings.map(topicReviewDecision).join(''):'<p>暂无旧会议记录。</p>')+workbenchTopicProducts(t,w));
  // Former meeting decisions stay historical; optional summaries retain their own permissions.
  document.querySelector('.drawer-body')?.querySelectorAll('button[data-action="topic-finals-confirm"],button[data-action^="topic-review"]').forEach(b=>b.remove());
}

document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-action="handoff-legacy"],[data-action="handoff-refresh"],[data-action="handoff-view"]');if(!b)return;
  event.preventDefault();
  try{
    if(b.dataset.action==='handoff-view'){
      const account=state.me?.id,tid=b.closest('[data-collaboration-topic]')?.dataset.collaborationTopic||workbenchState.topic?.id;
      const result=await api('/api/collaboration/topics/'+encodeURIComponent(tid)+'/handoff-preview?version_ref='+encodeURIComponent(b.dataset.version));
      if(account!==state.me?.id||!b.isConnected)return;
      deskRenderPreview(b,result);return;
    }
    if(b.dataset.action==='handoff-legacy'){await handoffLegacy(b.dataset.id);return;}
    const form=b.closest('form');if(form.dataset.account!==state.me?.id)throw new Error('账号已切换，请重新打开材料。');
    const t=await api('/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic)+'/handoffs');
    if(form.dataset.account!==state.me?.id||!form.isConnected)return;
    const material=t.materials.find(m=>m.ref===form.dataset.material),v=t.materials.flatMap(m=>m.versions).find(v=>v.ref===form.dataset.version);
    if(form.dataset.form==='handoff-review'?!v?.can_review:!(material?material.can_submit:t.can_submit)){form.dataset.allowed='false';form.querySelectorAll('[type=submit]').forEach(button=>button.disabled=true);const root=form.closest('[data-material-ref]')?.querySelector('.handoff-lineage');if(root)await handoffReadRefresh(root);throw new Error('此版或权限已变化，原草稿已保留。');}
    form.dataset.token=t.token;form.dataset.request=crypto.randomUUID();form._attempt=null;form._decision=null;form._conflict=false;form.querySelectorAll('input,textarea').forEach(input=>input.disabled=false);
    form.querySelector('[data-handoff-conflict]').innerHTML='';form.querySelector('.form-error').textContent='状态已刷新，文件与输入已保留。';
  }catch(error){const form=b.closest('form');if(form)form.querySelector('.form-error').textContent=error.message;else toast(error.message);}
});

document.addEventListener('submit',async event=>{
  const form=event.target,type=form.dataset.form;if(!['handoff-upload','handoff-review'].includes(type))return;
  event.preventDefault();if(form.dataset.saving==='true')return;
  const account=state.me?.id,load=state.loadId,error=form.querySelector('.form-error');
  if(form.dataset.allowed==='false'){error.textContent='此版当前不可提交，草稿已保留。';return;}
  if(form.dataset.account!==account){error.textContent='账号已切换，请重新打开材料。';return;}
  if(form._attempt&&type==='handoff-review'&&event.submitter?.value!==form._decision){error.textContent='请重试原审阅决定，先核对保存结果。';return;}
  if(form._conflict){error.textContent='请先刷新本期状态，当前输入仍保留。';return;}
  form.dataset.saving='true';handoffSyncActions(form);form.querySelectorAll('[type=submit]').forEach(b=>b.disabled=true);error.textContent='';
  try{
    if(!form._attempt){
      const fd=new FormData(form),data={token:form.dataset.token,request_id:form.dataset.request,note:String(fd.get('note')||'')};
      if(type==='handoff-upload'){data.stage=form.dataset.stage;if(form.dataset.material)data.material_ref=form.dataset.material;if(form.dataset.source)data.source_ref=form.dataset.source;const title=String(fd.get('title')||'').trim();if(title)data.title=title;}
      else{data.version_ref=form.dataset.version;data.decision=event.submitter?.value;if(!data.decision)throw new Error('请选择通过或退回。');}
      const body=new FormData();body.set('data',JSON.stringify(data));const file=fd.get('file');if(file?.size)body.set('file',file);else if(type==='handoff-upload')throw new Error('请选择材料文件。');
      form._attempt=body;form._decision=data.decision;
    }
    form.querySelectorAll('input,textarea').forEach(input=>input.disabled=true);
    const result=await api('/api/collaboration/topics/'+encodeURIComponent(form.dataset.topic)+(type==='handoff-upload'?'/handoffs':'/handoff-reviews'),{method:'POST',body:form._attempt});
    if(account!==state.me?.id||load!==state.loadId||!form.isConnected)return;
    form._attempt=null;form._decision=null;form.dataset.request=crypto.randomUUID();form.reset();form.querySelectorAll('input,textarea').forEach(input=>input.disabled=false);
    const root=form.closest('[data-material-ref]')?.querySelector('.handoff-lineage');
    if(root)await handoffReadRefresh(root);else await handoffRefreshNew(form);
    if(type==='handoff-review'){form.dataset.saved='true';form.closest('.handoff-review').hidden=true;}
    toast(result.reused?'已保存，已读取当前状态':type==='handoff-upload'?'材料已上传':'审阅已保存');
  }catch(e){
    if(account===state.me?.id&&load===state.loadId&&form.isConnected){if([401,403,404].includes(e.status)){form.dataset.allowed='false';const root=form.closest('[data-material-ref]')?.querySelector('.handoff-lineage')||form.closest('.handoff-materials')?.querySelector('.handoff-lineage');if(root)await handoffReadRefresh(root);}
      error.textContent=e.status?e.message:e.message+' 请重试核对这次提交。';if(e.status&&e.status!==409){form._attempt=null;form._decision=null;form.querySelectorAll('input,textarea').forEach(input=>input.disabled=false);}if(e.status===409){form._conflict=true;form.querySelectorAll('input,textarea').forEach(input=>input.disabled=false);form.querySelector('[data-handoff-conflict]').innerHTML='<button class="button" type="button" data-action="handoff-refresh">刷新状态，保留输入</button>';}}
  }finally{form.dataset.saving='false';if(form.isConnected)form.querySelectorAll('[type=submit]').forEach(b=>b.disabled=form.dataset.allowed==='false'||!!(form._attempt&&type==='handoff-review'&&b.value!==form._decision));handoffSyncActions(form);}
});
