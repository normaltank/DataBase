'use strict';

function clientAsset(path){const revision=document.querySelector('meta[name="client-revision"]')?.content;return path+(revision?'?v='+encodeURIComponent(revision):'');}
function clientControlChanged(el){
  if(el.type==='file')return !!el.files.length;
  if(el.type==='checkbox'||el.type==='radio')return el.checked!==el.defaultChecked;
  if(el.tagName==='SELECT'){
    const options=[...el.options],defaults=options.map((o,i)=>o.defaultSelected?i:-1).filter(i=>i>=0);
    if(!el.multiple&&!defaults.length&&options.length)defaults.push(0);
    return options.some((o,i)=>o.selected!==defaults.includes(i));
  }
  return el.value!==el.defaultValue;
}

// Files remain in their native forms. A reload is allowed only after the user
// saves or clears drafts; no background refresh can destroy a selected File.
function clientDraftState(){
  let present=false,otherAccount=false;
  const forms=new Set(document.querySelectorAll('form'));
  if(typeof handoffDrafts!=='undefined')for(const form of handoffDrafts.values())forms.add(form);
  if(typeof handoffDraftForms!=='undefined')for(const form of handoffDraftForms)forms.add(form);
  for(const form of forms){
    if(form.dataset.saved==='true')continue;
    const pending=form.dataset.saving==='true'||form._attempt||form._conflict||form._dirty||form._draftFailed||form._fileSaveFailed;
    if(!pending&&(/search|filter|login|nickname/.test(form.dataset.form||'')||form.matches('[data-work-search]')))continue;
    if(pending||[...form.querySelectorAll('input,textarea,select')].some(clientControlChanged)){
      present=true;
      if(form.dataset.account&&form.dataset.account!==state.me?.id)otherAccount=true;
    }
  }
  return {present:present||(typeof draftFileWrites!=='undefined'&&!!draftFileWrites),otherAccount};
}
function clientHasDraft(){return clientDraftState().present;}
function clientGuardTransition(){if(!clientHasDraft())return true;toast('有未提交的文件或输入，请先保存或清空，再继续。');return false;}

(() => {
  const revision=document.querySelector('meta[name="client-revision"]')?.content;
  let available=false,checking=false;
  function offer(next){
    if(!next||next===revision||available)return;
    available=true;window.objectActions?.close(false);
    const bar=document.createElement('aside');bar.className='client-update';bar.setAttribute('aria-label','页面更新');
    bar.innerHTML='<span>有新版本</span><button type="button" class="button primary" data-client-update>更新页面</button>';
    bar.querySelector('button').addEventListener('click',()=>{
      if(!clientDraftState().otherAccount){if(clientGuardTransition())location.reload();return;}
      // A same-origin native new-page link keeps this page's File/unknown
      // requests alive. The new page authenticates normally as the current user.
      if(!bar.querySelector('[data-client-continue]')){
        const copy=document.createElement('span');copy.className='client-update-recovery';
        copy.textContent='其他账号的草稿留在本页，原账号登录后可接续。';
        const link=document.createElement('a');link.className='button';link.dataset.clientContinue='';
        link.target='_blank';link.rel='noopener';link.textContent='新页继续（保留本页）';
        bar.append(copy,link);
      }
      bar.querySelector('[data-client-continue]').href=location.href;
    });document.body.append(bar);
  }
  async function check(){
    if(checking||!state.me||document.hidden)return;checking=true;
    try{const response=await fetch('/api/client-revision',{cache:'no-store'});if(response.ok)offer((await response.json()).revision);}catch{/* Retry on the next focus or interval. */}finally{checking=false;}
  }
  window.addEventListener('focus',check);document.addEventListener('visibilitychange',check);setInterval(check,60000);
  document.addEventListener('client:check',check);
  window.addEventListener('beforeunload',event=>{if(clientHasDraft()){event.preventDefault();event.returnValue='';}});
  // Every API response can discover an upgrade without replacing the current UI.
  document.addEventListener('client:revision',event=>offer(event.detail));
})();
