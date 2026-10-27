'use strict';

function discoveryCoverage(queue){
  if(!queue.window)return '<p class="form-help">从官方 Opinions RSS 手动取得最近 30 天题录；取得和预览不会写入正式资料。</p>';
  const labels={missing_date:'日期缺失',invalid_date:'日期无效',outside_window:'超出窗口',future:'未来日期',invalid_item:'题名或链接等条目无效',duplicate_url:'订阅内重复网址',duplicate_guid:'重复 GUID（只提示，不作资料身份）'};
  return '<section class="notice"><p>本次 UTC 日历窗口：'+esc(queue.window.start)+' 至 '+esc(queue.window.end)+'（含首尾，共 30 天）<br>取得时间：'+esc(queue.retrieved_at)+'<br>当前 RSS 返回 '+queue.returned+' 条；最早有效日期：'+esc(queue.earliest||'未知')+'</p>'+(queue.warnings||[]).map(w=>'<p>'+esc(w)+'</p>').join('')+'<p>'+Object.entries(labels).map(([k,label])=>label+' '+queue.counts[k]).join('；')+'</p><p>'+externalLink(queue.column_url,'官方 Opinions 栏目')+' · '+externalLink(queue.feed_url,'本次固定 RSS')+'</p><details><summary>排除条目及原因</summary>'+(queue.exclusions.length?queue.exclusions.map(e=>'<p>RSS 第 '+e.index+' 条：'+esc(labels[e.reason]||e.reason)+'</p>').join(''):'<p>无排除条目。</p>')+'</details></section>';
}
function discoveryQueueHtml(queue){
  return '<section class="ris-queue" data-ris-queue><h3>LIIA Opinions · '+queue.items.length+' 条候选</h3>'+discoveryCoverage(queue)+'<p class="form-help">逐条核对类型与题录后明确保存。署名、语言、摘要缺项保持空白；公开描述不是已核实摘要。切换、关闭及失败保留账号草稿。</p><ol>'+queue.items.map((item,i)=>'<li><div><strong>RSS 第 '+item.index+' 条</strong><span>'+esc(item.edit?.title||item.fields.title)+'</span><small>'+esc(item.fields.published_on)+' · '+esc(item.saved?'已保存':item.skipped?'已跳过':item.saveError?'保存失败，输入保留':'待人工核对')+'</small>'+(item.blocked?'<p>存在受限重复，请联系资料管理员核对。</p>':'')+(item.duplicates||[]).map(d=>'<p>可能重复：'+linkButton(esc(d.title),'detail',d.id,'link-button')+'</p>').join('')+'</div>'+(item.saved?'<button type="button" class="button tiny" data-ris-open="'+esc(item.saved)+'">查看资料</button>':'<button type="button" class="button tiny" data-ris-edit="'+i+'">核对本条</button>')+'<button type="button" class="button tiny" data-ris-skip="'+i+'" '+(item.saved?'disabled':'')+'>'+(item.skipped?'继续处理':'跳过')+'</button></li>').join('')+'</ol></section>';
}
function discoveryControls(queue){return '<section class="ris-upload"><button type="button" class="button" data-discovery-fetch>手动取得最近 30 天</button><p data-ris-status role="status" aria-live="polite"></p><a href="'+sourceHref(queue.source_id)+'" data-action="close">返回来源档案</a></section>';}
function discoveryItemHtml(item){return '<section><h3>来源公开描述</h3><p class="prose">'+esc(item.description||'未提供有效公开描述；摘要仍需人工补充。')+'</p><p>'+externalLink(item.fields.url,'打开原文核对')+'</p><details class="intake-evidence"><summary>RSS 原始字段与取得依据</summary><pre>'+esc(JSON.stringify(item.evidence,null,2))+'</pre></details></section>';}
function discoveryEvidenceHtml(items){return items?.length?'<details class="intake-evidence"><summary>来源发现依据</summary><p>公开描述可能只是系列介绍；原始字段与采用版本分别保留。</p>'+items.map(e=>'<pre>'+esc(JSON.stringify(e,null,2))+'</pre>').join('')+'</details>':'';}
async function discoveryOpen(source){
  const empty={format:'discovery',source_id:source,filename:'LIIA Opinions 近期发现',items:[]};
  return risOpenDraft(queueDraftKey(empty),empty);
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-discovery-start],[data-discovery-fetch]');if(!button)return;
  const form=button.closest('form');
  try{
    if(button.hasAttribute('data-discovery-start'))return await discoveryOpen(button.dataset.discoveryStart);
    risCaptureEditor(form);if(!saveEditorDraft(form,true))throw new Error('草稿未能保存，请保持当前编辑器打开。');
    const queue=form._risQueue,status=form.querySelector('[data-ris-status]');
    if(queue.items.length&&!button.dataset.confirmed){status.innerHTML='已有候选及编辑仍保留。<button type="button" class="button tiny" data-discovery-fetch data-confirmed="true">确认重新取得并替换本次队列</button>';return;}
    const actor=state.me.id,generation=modalGeneration;button.disabled=true;form.inert=true;status.textContent='正在取得固定官方 RSS；正式资料尚未写入…';
    try{
      const result=await api('/api/sources/'+encodeURIComponent(queue.source_id)+'/discovery',{method:'POST',body:{}});
      if(!form.isConnected||actor!==state.me?.id||generation!==modalGeneration)return;
      await risShowQueue(result);
    }finally{if(button.isConnected)button.disabled=false;if(form.isConnected)form.inert=false;}
  }catch(error){if(form?.isConnected){form.querySelector('.form-error').textContent=error.message;const status=form.querySelector('[data-ris-status]');if(status)status.textContent=error.message+' 已有候选和编辑仍保留。';}else toast(error.message);}
});
