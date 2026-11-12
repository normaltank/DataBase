/* Reading owns the UI; worker and shared ledger own execution and recovery. */
function fulltextHtml(record, selected='', mode='chinese') {
  const full=record.fulltext;if(!full)return '';
  const versions=full.versions||[],version=versions.find(v=>v.id===selected)||versions.find(v=>!v.stale)||versions[0];
  const saved=record.saved_originals||[],files=(record.original_file_candidates||[]).map(url=>{
    const existing=saved.find(s=>s.requested_url===url&&s.current);
    return '<div class="row wrap">'+(existing?'<a class="button tiny" href="/api/attachments/'+esc(existing.attachment_id)+'" download>下载已保存原文件</a>':'<button class="button tiny" data-action="fulltext-save-file" data-url="'+esc(url)+'">保存公开原文件</button>')+externalLink(url,'原文件出处')+'</div>'+(existing?.extraction?.message?'<p class="small muted">'+esc(existing.extraction.message)+'</p>':'');
  }).join('');
  if(!files&&!full.available&&!versions.length)return '';
  const status={queued:'等待后台处理',running:'正在翻译',paused:'暂停，后台会在条件恢复后续作',failed:'需要处理',succeeded:'全文翻译已完成'};
  const choices=versions.length>1?'<label>阅读版本 <select data-fulltext-version>'+versions.map(v=>'<option value="'+esc(v.id)+'" '+(v.id===version.id?'selected':'')+'>'+(v.input.kind==='pdf_text'?'PDF 已提取文字 · ':'网页正文 · ')+dateTime(v.created_at)+(v.stale?' · 历史原文':' · 当前原文')+'</option>').join('')+'</select></label>':'';
  let paragraphs='';
  const input=version?version.input:full.original;
  if(input)paragraphs=input.paragraphs.map((p,n)=>{
    const segment=version?.segments[n],chinese=segment?.reading_text;
    return '<div class="fulltext-paragraph"><p class="small muted">'+(p.page?'PDF 第 '+p.page+' 页（文件页码） · ':'')+'第 '+(n+1)+' 段'+(segment?.human?' · 人工校订':chinese?' · 机器译文，未经人工校订':'')+'</p>'
      +(mode!=='chinese'||!chinese?'<p class="prose" lang="'+esc(record.language||'en')+'">'+esc(p.original)+'</p>':'')
      +(mode!=='original'&&chinese?'<p class="prose" lang="zh-CN">'+esc(chinese)+'</p>':'')
      +(mode!=='original'&&segment&&!chinese?'<p class="small muted">本段'+(segment.status==='queued'?'等待翻译':'翻译暂停')+'，可先读原文。</p>':'')
      +(version&&record.can_edit&&chinese?'<details><summary>校订本段译文</summary><form data-fulltext-edit data-id="'+esc(version.id)+'" data-paragraph="'+n+'" data-revision="'+(version.edits.at(-1)?.id||0)+'"><label>第 '+(n+1)+' 段中文<textarea name="text" rows="5" required maxlength="12000">'+esc(chinese)+'</textarea></label><button class="button tiny" type="submit">保存校订</button><p role="status" data-edit-status></p></form></details>':'')+'</div>';
  }).join('');
  return '<section class="detail-section fulltext-reading" data-fulltext-record="'+esc(record.id)+'" data-fulltext-selected="'+esc(version?.id||'')+'" data-fulltext-mode="'+esc(mode)+'"><h3>原文件与全文阅读</h3>'+files
    +(full.can_request?(full.inputs||[]).filter(value=>!versions.some(v=>v.input_hash===value.input_hash)).map(value=>'<button class="button tiny" data-action="fulltext-request" data-input-hash="'+esc(value.input_hash)+'">'+(value.kind==='pdf_text'?'翻译此 PDF 已提取文字':'请求全文中文翻译')+'</button><p class="small muted">'+(value.kind==='pdf_text'?'仅翻译从此文件实际提取的文字，图像与扫描内容未识别。':'按当前网页正文逐段翻译。')+'使用中心共享月额度。</p>').join(''):'')
    +(!full.available?'<p class="muted">'+esc(full.reason)+'</p>':'')
    +(version?'<p role="status">'+esc(status[version.status]||version.status)+' · '+version.completed+' / '+version.total+' 段'+(version.stale?' · 所据原文为历史版本':'')+'</p>'+(version.reason?'<p>'+esc(version.reason)+'</p>':'')+(['paused','failed'].includes(version.status)&&!version.stale?'<button class="button tiny" data-action="fulltext-retry" data-id="'+esc(version.id)+'">继续未完成段落</button>':''):'')
    +choices+(input?'<div class="row wrap" role="group" aria-label="全文阅读语言">'+[['original','原文'],['chinese','中文'],['both','原译对照']].map(([value,label])=>'<button class="button tiny" data-action="fulltext-mode" data-mode="'+value+'" aria-pressed="'+(mode===value)+'">'+label+'</button>').join('')+'</div>':'')
    +'<p role="status" data-fulltext-message></p>'+(input?.kind==='pdf_text'?'<p class="small">阅读范围：此 PDF 共 '+input.pages_total+' 页，其中 '+input.pages_with_text.length+' 页取得可提取文字。请对照原文件；图像、扫描与提取缺漏不在译文中。</p>':'')+paragraphs
    +(version?'<details><summary>原文与处理依据</summary><p>原文'+(version.input.kind==='pdf_text'?'文件':'快照')+' '+esc(version.input.snapshot_id)+' · 输入版本 '+esc(version.input_hash)+'</p>'+externalLink(version.input.url,'原文出处')+(version.input.kind==='pdf_text'?'<p><a href="/api/fulltext-originals/'+esc(version.input.snapshot_id)+'" download>下载所据 PDF 原文件</a> · SHA256 '+esc(version.input.snapshot_sha256)+'</p>':'')+'<p class="small">'+esc(version.input.basis)+'</p><pre>'+esc(JSON.stringify({calls:version.segments.map(s=>s.calls),human_history:version.edits},null,2))+'</pre></details>':'')+'</section>';
}
async function fulltextRefresh(section, polling=false) {
  if(section._fulltextPending)return;
  const actor=state.me?.id, rid=section.dataset.fulltextRecord;
  section._fulltextPending=true;
  try{
    const record=await api('/api/records/'+encodeURIComponent(rid));
    if(!section.isConnected||state.me?.id!==actor)return;
    // A response started before a reader opened a correction must not erase it.
    if(polling&&(section.querySelector('details[open]')||section.contains(document.activeElement)))return;
    const template=document.createElement('template');
    template.innerHTML=fulltextHtml(record,section.dataset.fulltextSelected,section.dataset.fulltextMode);
    const next=template.content.firstElementChild;
    if(next&&!section.isEqualNode(next)){
      const active=document.activeElement,action=section.contains(active)?active.dataset.action:null;
      section.replaceWith(next);
      if(action)next.querySelector('[data-action="'+action+'"]')?.focus({preventScroll:true});
    }
  }catch(error){
    if(section.isConnected&&state.me?.id===actor){
      if([401,403,404].includes(error.status))section.remove();
      else section.querySelector('[data-fulltext-message]').textContent='阅读状态未更新：'+error.message;
    }
    throw error;
  }finally{section._fulltextPending=false;}
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action^="fulltext-"]'),section=button?.closest('[data-fulltext-record]');if(!section||button.disabled)return;
  const action=button.dataset.action,actor=state.me?.id;
  if(action==='fulltext-mode'){section.dataset.fulltextMode=button.dataset.mode;await fulltextRefresh(section).catch(()=>{});return;}
  button.disabled=true;
  const message=section.querySelector('[data-fulltext-message]');message.textContent=action==='fulltext-save-file'?'正在取得公开文件…':'正在安排全文处理…';
  try{
    const rid=encodeURIComponent(section.dataset.fulltextRecord);
    if(action==='fulltext-save-file')await api('/api/records/'+rid+'/original-file',{method:'POST',body:{url:button.dataset.url}});
    else if(action==='fulltext-request'){
      const result=await api('/api/records/'+rid+'/fulltext',{method:'POST',body:{input_hash:button.dataset.inputHash}});
      section.dataset.fulltextSelected=result.id;
    }
    else if(action==='fulltext-retry')await api('/api/fulltext/'+encodeURIComponent(button.dataset.id)+'/retry',{method:'POST',body:{}});
    if(section.isConnected&&state.me?.id===actor)await fulltextRefresh(section);
  }catch(error){if(section.isConnected&&state.me?.id===actor){message.textContent=error.message+'；已有材料继续保留。';button.disabled=false;}}
});
document.addEventListener('change',async event=>{
  if(event.target.matches('[data-fulltext-version]')){
    const section=event.target.closest('[data-fulltext-record]');section.dataset.fulltextSelected=event.target.value;await fulltextRefresh(section).catch(()=>{});
  }
});
document.addEventListener('submit',async event=>{
  const form=event.target.closest('[data-fulltext-edit]');if(!form)return;event.preventDefault();
  const button=form.querySelector('button'),section=form.closest('[data-fulltext-record]');button.disabled=true;
  try{await api('/api/fulltext/'+encodeURIComponent(form.dataset.id)+'/edit',{method:'POST',body:{paragraph:Number(form.dataset.paragraph),revision:Number(form.dataset.revision),text:new FormData(form).get('text')}});await fulltextRefresh(section);}
  catch(error){form.querySelector('[data-edit-status]').textContent=error.message;button.disabled=false;}
});
// Refresh only the reading section. Never replace a user's open correction form.
setInterval(()=>{
  if(document.hidden)return;
  for(const section of document.querySelectorAll('[data-fulltext-record]')){
    if(section.querySelector('details[open]')||section.contains(document.activeElement)||section.querySelector('button:disabled'))continue;
    if(/等待后台处理|正在翻译|暂停，后台/.test(section.textContent))fulltextRefresh(section,true).catch(()=>{});
  }
},5000);
