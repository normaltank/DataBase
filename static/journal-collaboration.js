'use strict';

const journalMaterialLabels={manuscript:'编译稿',review:'审稿材料',product:'成品文件'};
function journalBusinessTabs(){return '<nav class="collaboration-tabs" aria-label="编译业务">'+linkButton('主题编译','collaboration-home')+linkButton('期刊编译','journal-home','','button primary')+'</nav>';}

async function journalCollaborationPage(){
  const id=state.params.get('id');
  if(id)return journalWorkPage(id);
  return collaborationWorkspacePage();
}

function journalFileCard(s,w){
  const longName=s.name.length>60,name=longName?s.name.slice(0,40)+'…':s.name;
  return '<article class="collaboration-file"><div class="journal-file-content"><strong>'+esc(journalMaterialLabels[s.material_kind])+' · 版本 '+s.version+' · '+esc(name)+'</strong>'+(longName?'<details><summary>完整文件名</summary><p>'+esc(s.name)+'</p></details>':'')+(s.id===w.current_product_id?' <span class="badge verified">当前成品</span>':'')+'<p class="small muted">提交人：'+esc(s.uploader_name)+' · '+dateTime(s.created_at)+'</p>'+(s.note?'<p class="collaboration-note">'+esc(s.note)+'</p>':'')+'<details><summary>原件校验信息</summary><p>'+s.bytes+' 字节</p><p class="collaboration-hash small">SHA-256：'+esc(s.sha256)+'</p></details></div><div class="stack journal-file-actions"><a class="button" href="'+esc(s.file_url)+'" download>下载期刊原件 v'+s.version+'</a>'+(w.can_edit&&s.material_kind!=='review'&&s.id!==w.current_product_id?'<button class="button" data-action="journal-product" data-id="'+esc(w.id)+'" data-submission="'+esc(s.id)+'" data-version="'+w.version+'">作为当前成品 v'+s.version+'</button>':'')+'</div></article>';
}

async function journalWorkPage(id){
  const w=await api('/api/collaboration/journals/'+encodeURIComponent(id)),latest=w.submissions[0],product=w.submissions.find(s=>s.id===w.current_product_id);
  const shown=[...new Set([product,latest].filter(Boolean))],old=w.submissions.filter(s=>!shown.includes(s));
  return '<section class="collaboration-workspace" data-journal-work="'+esc(w.id)+'">'+workReturnButton('← 返回期刊工作','journal-home')+'<div class="page-heading between wrap"><div><p class="eyebrow">期刊编译 · '+esc(kinds[w.record_kind])+'</p><h1>'+esc(w.journal_name)+'</h1><p>'+esc(w.coverage)+'</p></div><div class="row wrap">'+(w.can_edit?linkButton('提交文件','journal-upload-open')+linkButton('补充期刊信息','journal-edit',w.id):'')+linkButton('查看正文与原文关联','detail',w.record_id)+'</div></div>'+workMaterialTools('journal',w.id)+(w.source_clue?'<details><summary>刊名与出处线索'+(w.journal_id?' · 已关联期刊档案':' · 档案待补')+'</summary><p class="collaboration-note">'+esc(w.source_clue)+'</p>'+(w.journal_id?linkButton('查看期刊档案','source-detail',w.journal_id):'')+'</details>':'')+'<section class="panel"><h2>最新材料与成品</h2>'+(!product?'<p class="small muted">尚未选择当前成品。成品采用由有编辑权限的成员记录，不表示执行了主题审稿。</p>':'')+(shown.length?shown.map(s=>journalFileCard(s,w)).join(''):'<p>尚未提交文件。直接上传已在本机写好的整体稿件。</p>')+(old.length?'<details><summary>查看此前 '+old.length+' 个文件版本</summary>'+old.map(s=>journalFileCard(s,w)).join('')+'</details>':'')+'</section>'+(w.can_edit?'<details class="panel" data-journal-upload '+(latest?'':'open')+'><summary>提交文件'+(latest?' · 保留此前原件':'')+'</summary><form data-form="journal-upload" data-id="'+esc(w.id)+'" data-version="'+w.version+'" data-request="'+crypto.randomUUID()+'"><div class="stack"><div class="field"><label for="journal-file">期刊编译文件 *</label><input id="journal-file" name="file" type="file" accept=".docx,.pdf,.txt,.md" required><p class="form-help">DOCX、PDF、TXT 或 Markdown，最多20 MB。原件及每次修订分别保存。</p></div><div class="field"><label for="journal-material">材料类型</label><select id="journal-material" name="material_kind"><option value="manuscript">编译稿</option><option value="review">实际审稿材料</option><option value="product">成品文件</option></select></div><div class="field"><label for="journal-note">简短说明（可选）</label><textarea id="journal-note" name="note" rows="2" maxlength="4000"></textarea></div></div><div class="form-error" role="alert"></div><div data-journal-conflict></div><div class="form-actions"><button class="button primary" type="submit">保存文件新版本</button></div></form></details>':'<p class="muted">可查阅已提交原件。个人成果的新版本仍需负责作者授权。</p>')+'<details class="panel"><summary>期刊工作与成品采用历史</summary><div data-journal-history>'+linkButton('读取期刊历史','journal-history',w.id)+'</div></details></section>';
}

async function journalWorkForm(id=''){
  const w=id?await api('/api/collaboration/journals/'+encodeURIComponent(id)):null;
  const [sources,options]=await Promise.all([api('/api/sources?kind=journal'),w?Promise.resolve({items:[]}):api('/api/collaboration/journals/options')]);
  modal(w?'补充期刊信息':'新建期刊工作','<form data-form="journal-work" data-id="'+esc(id)+'" data-version="'+(w?.version||0)+'"><div class="stack"><div class="field"><label for="journal-source">已有期刊档案（可选）</label><select id="journal-source" name="journal_id"><option value="">尚未建档，先留刊名与出处</option>'+sources.items.map(s=>'<option value="'+esc(s.id)+'" '+(s.id===w?.journal_id?'selected':'')+'>'+esc(s.name)+'</option>').join('')+'</select></div><div class="field"><label for="journal-name">已知刊名 *</label><input id="journal-name" name="journal_name" maxlength="4000" required value="'+esc(w?.journal_name||'')+'"></div><div class="field"><label for="journal-coverage">原刊卷期或覆盖范围 *</label><input id="journal-coverage" name="coverage" maxlength="4000" required value="'+esc(w?.coverage||'')+'"></div><div class="field"><label for="journal-clue">出处线索（可选）</label><textarea id="journal-clue" name="source_clue" rows="2" maxlength="4000">'+esc(w?.source_clue||'')+'</textarea></div>'+(!w?'<div class="field"><label for="journal-existing">继续已有内容（可选）</label><select id="journal-existing" name="record_id"><option value="">为本工作新建内容身份</option>'+options.items.map(r=>'<option value="'+esc(r.id)+'">'+esc(kinds[r.kind]+' · '+r.title)+'</option>').join('')+'</select></div><div class="field"><label for="journal-kind">新建内容的编辑责任</label><select id="journal-kind" name="content_kind"><option value="directory_translation">目录译稿 · 中心成员共同编辑</option><option value="compilation">个人编译成果 · 作者授权</option></select></div>':'<p class="small muted">既有正文、原文关联和作者授权继续保留。</p>')+'</div><div class="form-error" role="alert"></div><div data-journal-conflict></div><div class="form-actions"><button class="button primary" type="submit">保存期刊工作</button></div></form>',true);
}

document.addEventListener('change',event=>{if(event.target.id==='journal-source'&&event.target.value){const form=event.target.closest('form');form.elements.journal_name.value=event.target.selectedOptions[0].textContent;}});

document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-action]');if(!b||!b.dataset.action.startsWith('journal-'))return;
  const a=b.dataset.action,id=b.dataset.id;
  try{
    if(a==='journal-home')go('collaboration',{business:'journal'});
    else if(a==='journal-open')go('collaboration',{business:'journal',id});
    else if(a==='journal-new')await journalWorkForm();
    else if(a==='journal-edit')await journalWorkForm(id);
    else if(a==='journal-upload-open'){const panel=document.querySelector('[data-journal-upload]');panel.open=true;panel.scrollIntoView({block:'start'});panel.querySelector('[type=file]').focus({preventScroll:true});}
    else if(a==='journal-product'){b.disabled=true;await api('/api/collaboration/journals/'+encodeURIComponent(id)+'/product',{method:'POST',body:{version:Number(b.dataset.version),submission_id:b.dataset.submission}});toast('已记录当前成品对应的原件');await route();}
    else if(a==='journal-history'){const d=await api('/api/collaboration/journals/'+encodeURIComponent(id)+'/history');b.closest('[data-journal-history]').innerHTML=d.items.map(e=>'<article class="history-row"><div><strong>工作 v'+e.version+' · '+esc(e.action)+'</strong><p>'+esc(e.actor_name)+' · '+dateTime(e.created_at)+'</p><p>'+esc(e.snapshot.journal_name+' · '+e.snapshot.coverage)+'</p></div></article>').join('');}
    else if(a==='journal-rebase'){const f=b.closest('form'),w=await api('/api/collaboration/journals/'+encodeURIComponent(f.dataset.id));f.dataset.version=w.version;f.dataset.request=crypto.randomUUID();f._conflict=false;f.querySelector('[data-journal-conflict]').innerHTML='';f.querySelector('.form-error').textContent='已读取最新状态，当前文件和说明保留。';}
  }catch(e){b.disabled=false;toast(e.message);}
});

document.addEventListener('submit',async event=>{
  const form=event.target,type=form.dataset.form;if(!['journal-work','journal-upload'].includes(type))return;
  event.preventDefault();const error=form.querySelector('.form-error'),button=form.querySelector('[type=submit]'),account=state.me?.id;button.disabled=true;error.textContent='';
  try{
    if(form._conflict)throw new Error('请先核对最新状态，再继续保存。');
    const fd=new FormData(form),id=form.dataset.id;let result;
    if(type==='journal-work'){const data=Object.fromEntries(fd);if(id)data.version=Number(form.dataset.version);result=await api('/api/collaboration/journals'+(id?'/'+encodeURIComponent(id):''),{method:id?'PUT':'POST',body:data});}
    else{fd.set('data',JSON.stringify({version:Number(form.dataset.version),request_id:form.dataset.request,material_kind:fd.get('material_kind'),note:fd.get('note')}));result=await api('/api/collaboration/journals/'+encodeURIComponent(id)+'/submissions',{method:'POST',body:fd});}
    if(account!==state.me?.id||!form.isConnected)return;
    closeModal();toast('期刊材料已保存');if(type==='journal-work')go('collaboration',{business:'journal',id:result.id});else await route();
  }catch(e){if(!form.isConnected)return;error.textContent=e.message;if(e.status===409&&form.dataset.id){form._conflict=true;const w=await api('/api/collaboration/journals/'+encodeURIComponent(form.dataset.id));form.querySelector('[data-journal-conflict]').innerHTML='<section class="notice"><h3>请核对期刊最新材料</h3><p>'+esc(w.journal_name+' · '+w.coverage)+' · 工作 v'+w.version+'</p>'+(w.submissions[0]?'<p>'+esc(w.submissions[0].name)+' · '+esc(w.submissions[0].note)+'</p><a class="button" href="'+esc(w.submissions[0].file_url)+'" download>下载最新期刊原件核对</a>':'')+'<p>当前文件和说明已保留。</p><button type="button" class="button" data-action="journal-rebase">已核对，保留文件继续</button></section>';}}finally{if(form.isConnected)button.disabled=false;}
});
