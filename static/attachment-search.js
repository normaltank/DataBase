'use strict';

function attachmentSelection(text,start,end) {
  // Match Python str.split whitespace, including controls JS \s omits and
  // excluding BOM; selection ranges use UTF-16, saved offsets use code points.
  const whitespace='[\\u0009-\\u000d\\u001c-\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]';
  const space=new RegExp(whitespace,'u');
  while(start<end&&space.test(text[start]))start++;
  while(end>start&&space.test(text[end-1]))end--;
  const before=text.slice(0,start).replace(new RegExp(whitespace+'+','gu'),' ').replace(/^ /u,'');
  return {quote:text.slice(start,end),start:Array.from(before).length};
}

function attachmentMatchSection(record) {
  const matches=record.attachment_matches||[];
  return matches.length?'<div class="attachment-matches" aria-label="附件命中">'+matches.map(match=>'<p><strong>附件命中</strong> · <a href="'+esc(match.url)+'" target="_blank" rel="noopener noreferrer">'+esc(match.name)+'</a><span class="attachment-locator">'+esc(match.locator)+'</span><span class="attachment-snippet">'+esc(match.snippet)+'</span><button type="button" class="button tiny" data-action="attachment-excerpt" data-id="'+esc(match.attachment_id)+'" data-locator="'+esc(match.locator)+'">查看片段并作为摘录</button></p>').join('')+'</div>':'';
}
function attachmentIndexSection(record) {
  const files=record.attachments||[];
  if(!files.length)return '';
  return '<section class="detail-section attachment-index"><h3>附件文字检索</h3><p class="attachment-help">只检索已提取文字，不支持 OCR。PDF 使用文件页码；DOCX 仅正文段落与表格；TXT / Markdown 使用行号。片段用于查找，请以原附件核对。</p>'+files.map(file=>'<div class="attachment-index-file"><a href="/api/attachments/'+encodeURIComponent(file.id)+'" target="_blank" rel="noopener noreferrer">'+esc(file.name)+'</a><span data-index-status role="status">'+esc(file.index?.message||'尚未建立索引')+'</span><button type="button" class="button tiny" data-action="attachment-index" data-id="'+esc(file.id)+'">'+(file.index?.status==='unindexed'?'建立索引':'重建索引')+'</button></div>').join('')+'<details class="attachment-help"><summary>处理范围与限制</summary><p>每份索引最多处理 10 MB 文件、300 页 PDF、20 MB 解压内容、100 万字符和 2 万段，限时 12 秒。加密或损坏文件可能提取失败，原文件仍保留。DOCX 图片、脚注、文本框及 PDF 图片不提取。</p></details></section>';
}

document.addEventListener('click', async event=>{
  const button=event.target.closest('[data-action="attachment-index"]');
  if(!button)return;
  event.preventDefault();event.stopPropagation();
  const row=button.closest('.attachment-index-file'),label=row.querySelector('[data-index-status]'),user=state.me?.id;
  button.disabled=true;label.textContent='正在提取文字…';
  try{
    const result=await api('/api/attachments/'+encodeURIComponent(button.dataset.id)+'/index',{method:'POST',body:{}});
    if(state.me?.id!==user||!row.isConnected)return;
    label.textContent=result.message;button.textContent='重建索引';
  }catch(error){
    if(state.me?.id!==user||!row.isConnected)return;
    label.textContent=error.message||'建立索引失败，请重试。';
  }finally{
    if(row.isConnected&&state.me?.id===user)button.disabled=false;
  }
},true);

// Fetch the complete location, then use the member's actual selection, never a shortened search snippet.
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action="attachment-excerpt"], [data-action="attachment-use-selection"]');
  if(!button)return;
  event.preventDefault();event.stopImmediatePropagation();
  try{
    if(button.dataset.action==='attachment-excerpt'){
      const user=state.me?.id,hash=location.hash,generation=modalGeneration;
      const segment=await api('/api/attachments/'+encodeURIComponent(button.dataset.id)+'/segment?locator='+encodeURIComponent(button.dataset.locator));
      if(user!==state.me?.id||hash!==location.hash||generation!==modalGeneration||!button.isConnected)return;
      modal('核对附件位置并选择原句','<p>'+esc(segment.name)+' · '+esc(segment.locator)+'</p><p class="form-help">以下为该位置的完整提取文字，请核对原附件。选择需要引用的文字后继续；也可在摘录编辑器调整。提取匹配不证明材料真实。</p><label for="attachment-segment">该位置提取文字（选择原句）</label><textarea id="attachment-segment" class="attachment-segment" data-attachment-segment readonly rows="12">'+esc(segment.text)+'</textarea><p data-attachment-selection-status role="status"></p><button type="button" class="button primary" data-action="attachment-use-selection">将选中文字作为摘录</button>');
      const textarea=document.querySelector('[data-attachment-segment]');textarea._segment=segment;
      textarea.focus();textarea.setSelectionRange(0,segment.text.length);
    }else{
      const textarea=document.querySelector('[data-attachment-segment]'),segment=textarea._segment;
      const selection=attachmentSelection(textarea.value,textarea.selectionStart,textarea.selectionEnd),quote=selection.quote;
      if(!quote||quote.length>40000){document.querySelector('[data-attachment-selection-status]').textContent='请选择1至40000字的原句。';return;}
      await workflowRecordForm('','research_note','excerpt-'+segment.record_id,'',segment.record_id,{evidence_attachment_id:segment.attachment_id,locator:segment.locator,quote,evidence_selection_start:selection.start});
    }
  }catch(error){toast(error.message);}
},true);
