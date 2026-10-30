'use strict';
function historicalPreviewVersion(job){
  const p=job.preview_import;
  return '<article class="detail-section"><h4>历史机器结果 · 尚未人工校订'+(job.stale?' · 当前原文已变化':' · 本包题录与节选输入一致')+'</h4>'
    +'<p>本包导入历史结果，未调用翻译服务；原译节选独立截取，未必逐句或逐段对齐，完整摘要和译文未随包。</p>'
    +'<p>'+esc(job.provider)+' / '+esc(job.model)+' · 历史原资料版本 '+p.source_version+' · 本包调用 0 次</p>'
    +'<div class="comparison-grid"><section><h5>随包原题名与摘要'+(p.abstract_mode==='excerpt'?'节选':'')+'</h5><p class="prose">'+esc(job.input_title)+'</p><p class="prose">'+esc(job.input_abstract||'原摘要未取得；仅译题名。')+'</p></section>'
    +'<section><h5>历史机器中文'+(p.abstract_mode==='excerpt'?'节选':'题名')+'</h5><p class="prose">'+esc(job.output_title)+'</p><p class="prose">'+esc(job.output_abstract||'无原摘要，不补造摘要。')+'</p></section></div>'
    +'<details><summary>历史来源与节选依据</summary><p>历史任务 '+esc(p.source_job_id)+' · 原资料 '+esc(p.source_record_id)+'</p>'
    +'<p>取得路径：'+esc(p.acquisition_path)+'。'+esc(p.acquisition_limitation)+'</p>'
    +'<p class="prose">历史完整输入 SHA256：'+esc(p.source_input_hash)+'</p><p class="prose">本包节选输入 SHA256：'+esc(p.excerpt_input_hash)+'</p></details></article>';
}
function translationPanel(record) {
  if(isResearchContent(record.kind))return '';
  const labels={queued:'等待显式执行',running:'执行中',failed:'失败',succeeded:'机器译文 · 待人工复核'};
  const versions=(record.translations||[]).map(job=>job.preview_import?historicalPreviewVersion(job):'<article class="detail-section"><h4>'+esc(job.adopted_at?'机器译文 · 已人工采用':labels[job.status]||job.status)+(job.stale?' · 原文已变化，待复核':' · 与当前原题名／摘要一致')+'</h4><p class="small muted">原资料版本 '+job.source_version+' · '+esc(job.provider)+' / '+esc(job.model||'尚未生成')+' · '+dateTime(job.finished_at||job.created_at)+' · 执行 '+job.attempts+'/3 次</p>'
    +'<div class="comparison-grid"><section><h5>发送的原题名与摘要</h5><p class="prose">'+esc(job.input_title)+'</p><p class="prose">'+esc(job.input_abstract||'原摘要缺失；仅译题名。')+'</p></section><section><h5>独立机器中文版本</h5><p class="prose">'+esc(job.output_title||'尚无译文')+'</p><p class="prose">'+esc(job.output_abstract||(!job.input_abstract?'原摘要缺失':'尚无摘要译文'))+'</p></section></div>'
    +(job.version_changed&&!job.adopted_at?'<p class="form-help">资料版本已更新，采用前请基于当前版本重新生成。</p>':'')
    +(job.error?'<p class="notice error">'+esc(job.error)+'</p>':'')
    +(record.can_edit&&job.status==='queued'?'<button type="button" class="button" data-translation-action="run" data-job="'+esc(job.id)+'">执行本篇翻译</button>':'')
    +(record.can_edit&&['failed','running'].includes(job.status)&&job.attempts<3?'<button type="button" class="button" data-translation-action="retry" data-job="'+esc(job.id)+'">重试此任务</button>'+(job.status==='running'?'<p class="form-help">中断的执行满 60 秒后可显式重试。</p>':''):'')
    +(record.can_edit&&job.can_adopt?'<details data-translation-adoption><summary>校订并采用此机器版本</summary><div class="form-grid section-gap">'+'<label class="wide">校订中文题名<input name="chinese_title" value="'+esc(job.output_title)+'" maxlength="4000"></label><label class="wide">校订中文摘要<textarea name="chinese_abstract" rows="5" maxlength="40000">'+esc(job.output_abstract)+'</textarea></label>'+'</div><p class="form-help">采用后保存为人工中文字段并记录历史。请核对术语与原文；后续可用“编辑内容”共同修订。</p><button type="button" class="button primary" data-translation-action="adopt" data-job="'+esc(job.id)+'">采用此版本</button></details>':'')+'</article>').join('');
  return '<section data-translations data-record="'+esc(record.id)+'" data-version="'+record.version+'"><details '+((record.translations||[]).length?'open':'')+'><summary>辅助中文翻译'+((record.translations||[]).length?'（'+record.translations.length+' 个任务／版本）':'')+'</summary><p>仅向 DeepSeek 发送本篇题名和摘要。正文、附件和账号信息不发送。创建任务后，点击“执行本篇翻译”才会调用服务。</p>'
    +(record.chinese_title||record.chinese_abstract?'<section class="detail-section"><h4>人工中文 · 可共同修订</h4><p class="prose">'+esc(record.chinese_title)+'</p><p class="prose">'+esc(record.chinese_abstract)+'</p></section>':'')
    +(record.can_edit?'<button type="button" class="button" data-translation-action="queue">新建翻译任务</button><p class="form-help">再次生成会新增机器版本；正式人工中文保留。</p>':'')+'<p data-translation-status role="status" aria-live="polite"></p>'+versions+'</details></section>';
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-translation-action]');if(!button)return;
  event.preventDefault();const panel=button.closest('[data-translations]'),rid=panel.dataset.record,account=state.me?.id;
  const status=panel.querySelector('[data-translation-status]'),action=button.dataset.translationAction;
  button.disabled=true;status.textContent=action==='run'?'正在翻译，最长等待约 25 秒…':'正在保存…';
  try {
    const body={version:Number(panel.dataset.version)};
    let endpoint='/api/translations/'+encodeURIComponent(button.dataset.job)+'/'+action;
    if(action==='queue'){
      button.dataset.requestId ||= crypto.randomUUID();body.request_id=button.dataset.requestId;
      endpoint='/api/records/'+encodeURIComponent(rid)+'/translations';
    }
    if(action==='adopt')for(const input of button.closest('[data-translation-adoption]').querySelectorAll('input[name],textarea[name]'))body[input.name]=input.value;
    await api(endpoint,{method:'POST',body});
    const record=await api('/api/records/'+encodeURIComponent(rid));
    if(!panel.isConnected||account!==state.me?.id)return;
    panel.outerHTML=translationPanel(record);
    if(state.detail?.data?.id===rid)state.detail.data=record;
    if(typeof libraryWorkspace!=='undefined'&&libraryWorkspace.readerRecord?.id===rid)libraryWorkspace.readerRecord=record;
  } catch(error) {
    if(panel.isConnected&&account===state.me?.id){status.textContent=error.message;button.disabled=false;}
  }
});
