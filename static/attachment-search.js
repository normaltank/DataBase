'use strict';

function attachmentMatchSection(record) {
  const matches=record.attachment_matches||[];
  return matches.length?'<div class="attachment-matches" aria-label="附件命中">'+matches.map(match=>'<p><strong>附件命中</strong> · <a href="'+esc(match.url)+'" target="_blank" rel="noopener noreferrer">'+esc(match.name)+'</a><span class="attachment-locator">'+esc(match.locator)+'</span><span class="attachment-snippet">'+esc(match.snippet)+'</span></p>').join('')+'</div>':'';
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
