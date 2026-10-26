const reviewScopes={metadata_only:'题录',fulltext_and_bylines:'原文与署名',argument_and_translation:'论证与译文'};
function reviewEventHtml(event){
  const relation=key=>event[key]===null||event[key]===undefined?'历史未注明':event[key]?'同人':'不同账号';
  return `<p class="prose">核对基线：${esc(event.target_id)} · 版本 ${event.version}\n核对人：${esc(event.actor_name)} · ${dateTime(event.created_at)}\n范围：${esc(reviewScopes[event.review_scope]||'历史未注明')}\n依据与说明：${esc(event.review_note||'历史未注明')}\n与提交者：${relation('same_as_submitter')}；与负责作者：${relation('same_as_author')}；与当时最后内容修改者：${relation('same_as_last_modifier')}</p>`;
}
function reviewPanel(item){
  return `<section class="detail-section"><h3>最后实际核对基线</h3>${item.last_verified?reviewEventHtml(item.last_verified):'<p class="muted">未登记实际核对。</p>'}${item.last_verified&&item.can_edit!==false?`<button class="button tiny" type="button" data-action="review-baseline-content" data-id="${item.last_verified.revision_id}">查看核对时内容</button><div data-review-snapshot hidden></div>`:''}<p class="small muted">当前版本 ${item.version} · ${item.status==='verified'?'已核对':'待核对'}。账号关系只记录事实，不证明独立研究复核或研究结论成立。</p>${item.review_history?.length>1?`<details><summary>此前实际核对记录（${item.review_history.length-1}）</summary>${item.review_history.slice(1).map(reviewEventHtml).join('')}</details>`:''}</section>`;
}
function reviewForm(kind,rid){
  const current=state.detail.data,preview=kind==='source'&&state.sourcePreviewId===rid;
  modal('记录核对范围与依据',`<form data-form="review"><p data-review-target>核对“${esc(current.title||current.name)}” · 版本 ${current.version}。请按实际检查范围记录依据。</p><div class="stack"><label class="field"><span>核对范围 *</span><select name="review_scope" required><option value="">请选择范围</option>${Object.entries(reviewScopes).map(([key,value])=>`<option value="${key}">${value}</option>`).join('')}</select></label><label class="field"><span>核对依据与说明 *</span><textarea name="review_note" rows="6" maxlength="40000" required></textarea></label></div><p class="small muted">允许自核；系统保留核对者与提交者、负责作者及当时最后内容修改者的账号关系。</p><div class="form-error" role="alert"></div><div data-review-conflict></div><div class="form-actions"><button type="button" class="button" data-action="close">取消</button><button class="button primary" type="submit">记录核对</button></div></form>`);
  document.querySelector('[data-form=review]')._review={kind,rid,version:current.version,preview,label:current.title||current.name,account:state.me.id};
}
async function submitReview(form,values){
  const context=form._review;
  try{
    await api(`/api/review/${context.kind}/${encodeURIComponent(context.rid)}`,{method:'POST',body:{...values,version:context.version}});
  }catch(error){
    if(error.status===409){
      const latest=await api('/api/'+(context.kind==='record'?'records':'sources')+'/'+encodeURIComponent(context.rid));
      if(!form.isConnected||context.account!==state.me?.id)return;
      const panel=form.querySelector('[data-review-conflict]');
      panel.innerHTML=`<section class="notice"><h3>内容已更新，核对输入已保留</h3>${mergeSide(latest)}<button type="button" class="button" data-review-latest>已查看最新内容，以此版本重新核对</button></section>`;
      panel.querySelector('[data-review-latest]').onclick=()=>{context.version=latest.version;form.querySelector('[data-review-target]').textContent=`核对“${latest.title||latest.name}” · 版本 ${latest.version}。请按实际检查范围记录依据。`;panel.innerHTML=`<p class="notice">现在核对版本 ${latest.version}，范围和说明已保留。</p>`;form.querySelector('.form-error').textContent='';};
    }
    throw error;
  }
  if(!form.isConnected||context.account!==state.me?.id)return;
  toast('已记录核对范围与依据');await route();
  if(context.kind==='record')await openRecord(context.rid);else if(context.preview||state.page!=='sources'||!state.params.has('id'))await openSource(context.rid,context.preview);
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action=review-baseline-content]');if(!button)return;
  const target=button.parentElement.querySelector('[data-review-snapshot]'),account=state.me?.id;
  try{
    const result=await api('/api/history/'+button.dataset.id);
    if(!button.isConnected||account!==state.me?.id)return;
    target.hidden=false;target.innerHTML='<p class="notice">核对时保存的历史内容；当前正文可能已经更新。</p>'+mergeSide(result.snapshot);
  }catch(error){if(button.isConnected&&account===state.me?.id)toast(error.message);}
});
