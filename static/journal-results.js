'use strict';

// The HTTP module owns versions and originals; this view preserves uncommitted
// form inputs and browser history while members inspect a concurrent change.
function jrHref(params={}){return '#journal-results?'+new URLSearchParams(params);}
function jrContext(overrides={}){const p=new URLSearchParams(state.params);for(const key of ['id','new','edit'])p.delete(key);for(const [k,v] of Object.entries(overrides)){if(v===null||v==='')p.delete(k);else p.set(k,v);}return p;}
function jrLink(label,params={},cls='button'){return '<a class="'+cls+'" href="'+esc(jrHref(params))+'">'+esc(label)+'</a>';}
function jrTitle(r){return r.journal_name+' · '+r.year+' · '+r.issue;}
function jrRow(r,params={}){return '<article class="journal-result-row" data-jr-row="'+esc(r.id)+'"><h3>'+jrLink(jrTitle(r),new URLSearchParams({...Object.fromEntries(params instanceof URLSearchParams?params:new URLSearchParams(params)),id:r.id}),'title-button')+'</h3><p>'+r.files.length+' 份文件'+(r.authors?' · '+esc(r.authors):'')+'</p><p class="muted">更新于 '+dateTime(r.updated_at)+'</p></article>';}
async function journalResultsHub(){
  const data=await api('/api/journal-results');
  return '<section class="journal-results-hub"><div class="between wrap"><h2>期刊成果</h2>'+jrLink('查看全部 '+data.total+' 期')+'</div><div class="row wrap">'+jrLink('保存一期成果',{new:1},'button primary')+'</div>'+data.items.slice(0,3).map(r=>jrRow(r)).join('')+'</section>';
}
async function journalSourceResults(s){
  const data=await api('/api/journal-results?'+new URLSearchParams({journal_id:s.id}));
  return '<section class="detail-section"><div class="between wrap"><h3>期刊成果</h3>'+jrLink('按本刊查找成果',{journal_id:s.id})+'</div>'+data.items.slice(0,3).map(r=>jrRow(r,{journal_id:s.id})).join('')+'</section>';
}
async function jrMetadataFields(r={}){
  const sources=await api('/api/sources?kind=journal&size=500');
  return '<div class="form-grid"><label class="field">刊名 *<input name="journal_name" maxlength="4000" required value="'+esc(r.journal_name||'')+'"></label><label class="field">年份 *<input name="year" type="number" min="1" max="9999" required value="'+esc(r.year||'')+'"></label><label class="field">成果期次 *<input name="issue" maxlength="4000" required value="'+esc(r.issue||'')+'" placeholder="如第1—2期、跨期或特刊"></label><label class="field">编译署名<input name="authors" maxlength="4000" value="'+esc(r.authors||'')+'"></label></div><details><summary>期刊档案关联与说明</summary><div class="field"><label for="jr-journal-id">关联已有期刊（可选）</label><select id="jr-journal-id" name="journal_id"><option value="">暂不关联</option>'+sources.items.map(s=>'<option value="'+esc(s.id)+'" '+(s.id===r.journal_id?'selected':'')+'>'+esc(s.name)+'</option>').join('')+'</select></div><label class="field">期次说明<textarea name="note" maxlength="4000" rows="3">'+esc(r.note||'')+'</textarea></label></details>';
}
function jrFileFields(label='成果文件 *',multiple=false){return '<label class="field">'+label+'<input type="file" name="files" accept=".pdf,.docx,.txt,.md" '+(multiple?'multiple':'')+' required></label><p class="form-help">PDF、DOCX、TXT 或 Markdown，单文件最多20 MB；本次上传合计最多20 MB。</p><label class="field">文件说明<textarea name="file_note" maxlength="4000" rows="2"></textarea></label>';}
function jrSaveForm(body,mode,r={},sid=''){
  return '<form data-jr-form="'+mode+'" data-id="'+esc(r.id||'')+'" data-version="'+(r.version||0)+'" data-series="'+esc(sid)+'" data-request="'+crypto.randomUUID()+'" class="journal-result-form">'+body+'<div class="form-error" role="alert"></div><div data-jr-conflict></div><div class="form-actions"><button type="submit" class="button primary">'+({create:'保存一期成果',metadata:'保存期次信息',files:sid?'保存这份文件的新版本':'添加并列文件'}[mode])+'</button></div></form>';
}
function jrVersion(v,s,r,current){
  return '<article class="journal-result-version"><h3>'+esc(v.name)+' <span class="muted">v'+v.version+'</span></h3><p>'+esc(v.actor_name)+' · '+dateTime(v.created_at)+' · '+readableFileSize(v.bytes)+'</p>'+(v.note?'<p>'+esc(v.note)+'</p>':'')+'<div class="row wrap"><button type="button" class="button" data-jr-preview="'+esc(v.preview_url)+'">预览'+(current?'':' v'+v.version)+'</button><a class="button" href="'+esc(v.file_url)+'" download>下载'+(current?'':' v'+v.version)+'</a>'+(current?'<button type="button" class="button" data-jr-update="'+esc(s.id)+'">更新这份文件</button>':'<button type="button" class="button" data-jr-restore-file="'+esc(s.id)+'" data-file-version="'+v.version+'" data-version="'+r.version+'" data-id="'+esc(r.id)+'">恢复此版为新版本</button>')+'</div><div data-jr-preview-content></div></article>';
}
async function journalResultsPage(){
  const p=state.params,id=p.get('id'),context=jrContext();
  if(p.has('new'))return '<section class="journal-results"><a class="back-link" href="'+esc(jrHref(context))+'">← 返回期刊成果</a><h1>保存一期期刊成果</h1>'+jrSaveForm(await jrMetadataFields()+jrFileFields('首批成果文件 *',true),'create')+'</section>';
  if(id){
    const r=await api('/api/journal-results/'+encodeURIComponent(id));
    if(p.has('edit'))return '<section class="journal-results"><a class="back-link" href="'+esc(jrHref(new URLSearchParams({...Object.fromEntries(context),id})))+'">← 返回本期成果</a><h1>修改期次信息</h1>'+jrSaveForm(await jrMetadataFields(r),'metadata',r)+'</section>';
    return '<section class="journal-results" data-jr-detail="'+esc(r.id)+'"><a class="back-link" href="'+esc(jrHref(context))+'" data-jr-return="'+esc(r.id)+'">← 返回期刊成果</a><div class="page-heading between wrap"><div><h1>'+esc(r.journal_name)+'</h1><p>'+esc(r.year+' · '+r.issue)+(r.authors?' · '+esc(r.authors):'')+'</p></div>'+jrLink('修改期次信息',new URLSearchParams({...Object.fromEntries(context),id,edit:1}))+'</div>'+(r.note?'<p class="prose">'+esc(r.note)+'</p>':'')+(r.journal_id?'<div class="row wrap"><a class="button" href="#library?'+esc(new URLSearchParams({source:r.journal_id,source_section:'published',feed:'all'}))+'">查找本刊文章</a><a class="button" href="#sources?'+esc(new URLSearchParams({id:r.journal_id}))+'">期刊档案</a></div>':'')+'<h2>本期文件</h2>'+r.files.map(s=>'<section class="journal-result-series" data-jr-series="'+esc(s.id)+'">'+jrVersion(s.versions[0],s,r,true)+'<div data-jr-update-form hidden>'+jrSaveForm('<h3>更新：'+esc(s.versions[0].name)+'</h3>'+jrFileFields('新版本文件 *'),'files',r,s.id)+'</div>'+(s.versions.length>1?'<details><summary>此前 '+(s.versions.length-1)+' 个版本</summary>'+s.versions.slice(1).map(v=>jrVersion(v,s,r,false)).join('')+'</details>':'')+'</section>').join('')+'<details class="journal-result-add"><summary>添加另一份并列文件</summary>'+jrSaveForm(jrFileFields('并列成果文件 *',true),'files',r)+'</details><details class="journal-result-history"><summary>期次修改历史与导出</summary><a class="button" href="/api/journal-results/export?ids='+encodeURIComponent(r.id)+'" download>导出本期及全部文件版本</a><button class="button" data-jr-history="'+esc(r.id)+'" data-version="'+r.version+'">读取修改历史</button><div data-jr-history-content></div></details><div class="form-error" role="alert" data-jr-page-error></div></section>';
  }
  const [data,sources]=await Promise.all([api('/api/journal-results?'+context),api('/api/sources?kind=journal&size=500')]);
  return '<section class="journal-results"><a class="back-link" href="#compilations">← 返回中心成果</a><div class="page-heading between wrap"><h1>期刊成果</h1>'+jrLink('保存一期成果',jrContext({new:1}),'button primary')+'</div><form data-jr-search class="journal-result-search"><label class="field">刊名、期次或文件名<input type="search" name="q" value="'+esc(p.get('q')||'')+'"></label><label class="field">年份<input type="number" name="year" min="1" max="9999" value="'+esc(p.get('year')||'')+'"></label><div class="field"><label for="jr-journal-filter">期刊档案</label><select id="jr-journal-filter" name="journal_id"><option value="">全部期刊</option>'+sources.items.map(s=>'<option value="'+esc(s.id)+'" '+(s.id===p.get('journal_id')?'selected':'')+'>'+esc(s.name)+'</option>').join('')+'</select></div><button class="button" type="submit">查找成果</button>'+jrLink('清除筛选')+'</form><p class="muted">共 '+data.total+' 期 · 年份从新到旧，期次按原标注倒序</p><div data-jr-list>'+data.items.map(r=>jrRow(r,context)).join('')+(data.total?'':'<p>尚无匹配成果。可清除筛选或直接保存一期成果。</p>')+'</div><details class="journal-result-history"><summary>历史成果入口</summary><a class="button" href="#collaboration?business=journal&scope=all">旧期刊工作</a><a class="button" href="#compilations?legacy=1">个人成果与目录译稿</a></details></section>';
}

document.addEventListener('submit',async event=>{
  const f=event.target;if(!f.matches('[data-jr-form],[data-jr-search]'))return;event.preventDefault();
  if(f.hasAttribute('data-jr-search')){const p=new URLSearchParams();for(const [k,v] of new FormData(f))if(String(v).trim())p.set(k,String(v).trim());go('journal-results',p);return;}
  if(f.dataset.saving==='true')return;f.dataset.saving='true';
  const b=f.querySelector('[type=submit]'),error=f.querySelector('.form-error'),account=state.me?.id,fd=new FormData(f);b.disabled=true;error.textContent='';
  try{
    if(f.dataset.conflict==='true')throw new Error('请先读取最新状态并核对后继续。');
    const mode=f.dataset.jrForm,data={request_id:f.dataset.request};
    if(mode!=='create')data.version=Number(f.dataset.version);
    if(mode==='metadata'||mode==='create'){for(const key of ['journal_name','issue','authors','note','journal_id'])data[key]=String(fd.get(key)||'');data.year=Number(fd.get('year'));}
    if(mode!=='metadata'){data.file_note=String(fd.get('file_note')||'');if(f.dataset.series)data.series_id=f.dataset.series;fd.set('data',JSON.stringify(data));}
    const path='/api/journal-results'+(f.dataset.id?'/'+encodeURIComponent(f.dataset.id):'')+(mode==='files'?'/files':'');
    const r=await api(path,{method:mode==='metadata'?'PUT':'POST',body:mode==='metadata'?data:fd});
    if(account!==state.me?.id||!f.isConnected)return;
    toast('期刊成果已保存');go('journal-results',jrContext({id:r.id}));
  }catch(e){
    if(account!==state.me?.id||!f.isConnected)return;error.textContent=e.message;
    if(e.status===409&&f.dataset.id){f.dataset.conflict='true';f.querySelector('[data-jr-conflict]').innerHTML='<button type="button" class="button" data-jr-rebase>读取最新状态，保留当前输入</button><div data-jr-latest></div>';}
    else if(f.dataset.jrForm==='create'){
      const id=e.status===409?e.message.match(/编号：([a-f0-9]{32})/)?.[1]:null;
      f.querySelector('[data-jr-conflict]').innerHTML='<button type="button" class="button" data-jr-recover>查询本次保存结果，保留当前输入</button><div data-jr-latest></div>'+(id?jrLink('打开已有一期，添加文件',{id}):'');
    }
  }finally{f.dataset.saving='false';if(f.isConnected)b.disabled=false;}
});

document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-jr-update],[data-jr-rebase],[data-jr-recover],[data-jr-continue],[data-jr-preview],[data-jr-history],[data-jr-restore-file],[data-jr-restore-meta]');if(!b)return;
  const account=state.me?.id,load=state.loadId;b.disabled=true;
  const current=()=>account===state.me?.id&&load===state.loadId&&b.isConnected;
  try{
    if(b.hasAttribute('data-jr-update')){const f=b.closest('[data-jr-series]').querySelector('[data-jr-update-form]');f.hidden=false;f.querySelector('input').focus();}
    else if(b.hasAttribute('data-jr-recover')){
      const f=b.closest('form'),receipt=await api('/api/journal-results/requests/'+encodeURIComponent(f.dataset.request));if(!current())return;
      if(receipt.action!=='create')throw new Error('本次请求并非创建成果，请核对保存请求。');
      const r=receipt.result;f.jrRecovered=r;
      f.querySelector('[data-jr-latest]').innerHTML='<p>本次已创建：'+esc(jrTitle(r))+' · v'+r.version+'</p><p>已保存说明：'+esc(r.note||'无')+'</p><ul>'+r.files.map(s=>'<li>'+esc(s.versions[0].name)+' · v'+s.versions[0].version+'</li>').join('')+'</ul><p>当前输入、文件选择和文件说明仍保留。可仅修订这期的期次信息；文件不会重复上传，若要更换原件，请打开本期成果明确更新。</p><button type="button" class="button" data-jr-continue>接续已创建成果，仅修订期次信息</button><a class="button" target="_blank" rel="noopener" href="'+esc(jrHref({id:r.id}))+'">新窗口查看已保存成果</a>';
    }else if(b.hasAttribute('data-jr-continue')){
      const f=b.closest('form'),r=f.jrRecovered;if(!r)return;
      f.dataset.id=r.id;f.dataset.version=r.version;f.dataset.jrForm='metadata';f.dataset.request=crypto.randomUUID();f.dataset.conflict='false';
      f.querySelector('[type=submit]').textContent='仅保存期次信息（不重复上传文件）';
      f.querySelector('.form-error').textContent='已接续本次创建的一期。当前文件选择与文件说明仍保留；此次保存仅更新期次信息。';
    }else if(b.hasAttribute('data-jr-rebase')){
      const f=b.closest('form'),r=await api('/api/journal-results/'+encodeURIComponent(f.dataset.id));if(!current())return;
      f.dataset.version=r.version;f.dataset.request=crypto.randomUUID();f.dataset.conflict='false';
      f.querySelector('[data-jr-latest]').innerHTML='<p>最新：'+esc(jrTitle(r))+' · v'+r.version+'</p><ul>'+r.files.map(s=>'<li>'+esc(s.versions[0].name)+' · v'+s.versions[0].version+'</li>').join('')+'</ul><p>当前输入和文件已保留。核对后可继续保存。</p>';
    }else if(b.hasAttribute('data-jr-preview')){
      const data=await api(b.dataset.jrPreview);if(!current())return;
      b.closest('.journal-result-version').querySelector('[data-jr-preview-content]').innerHTML=data.kind==='pdf'?'<a class="button" href="'+esc(data.url)+'" target="_blank" rel="noopener">打开PDF预览</a>':'<pre class="journal-result-preview">'+esc(data.text)+'</pre>'+(data.truncated?'<p>已显示前30000字，完整内容请下载原件。</p>':'');
    }else if(b.hasAttribute('data-jr-history')){
      const d=await api('/api/journal-results/'+encodeURIComponent(b.dataset.jrHistory)+'/history');if(!current())return;
      b.closest('details').querySelector('[data-jr-history-content]').innerHTML=d.items.map(e=>'<article class="history-row"><h3>v'+e.version+' · '+esc(e.action)+'</h3><p>'+esc(e.actor_name)+' · '+dateTime(e.created_at)+'</p><p>'+esc(jrTitle(e.snapshot))+'</p><button class="button" data-jr-restore-meta="'+e.version+'" data-id="'+esc(b.dataset.jrHistory)+'" data-version="'+b.dataset.version+'">恢复此版期次信息</button></article>').join('');
    }else{
      const data={version:Number(b.dataset.version),request_id:b.dataset.request||(b.dataset.request=crypto.randomUUID())};
      if(b.hasAttribute('data-jr-restore-file')){data.series_id=b.dataset.jrRestoreFile;data.file_version=Number(b.dataset.fileVersion);}else data.history_version=Number(b.dataset.jrRestoreMeta);
      await api('/api/journal-results/'+encodeURIComponent(b.dataset.id)+'/restore',{method:'POST',body:data});if(!current())return;await route();toast('已恢复为新版本');
    }
  }catch(e){if(current()){const error=document.querySelector('[data-jr-page-error]')||b.closest('form')?.querySelector('.form-error');if(error)error.textContent=e.message;else toast(e.message);}}
  finally{if(current())b.disabled=false;}
});

// Browser history carries only position and unfinished search terms, never files.
const jrPositions=new Map();
document.addEventListener('click',event=>{
  const link=event.target.closest('.journal-results a,.journal-results-hub a');if(!link)return;
  const list=document.querySelector('[data-jr-list]'),form=document.querySelector('[data-jr-search]');
  if(list)jrPositions.set(state.me?.id+'|'+location.hash,{y:scrollY,focus:link.closest('[data-jr-row]')?.dataset.jrRow,search:form?Object.fromEntries(new FormData(form)):null});
},true);
function jrAfterRender(){
  if(state.page!=='journal-results'||state.params.has('id')||state.params.has('new'))return;
  const saved=jrPositions.get(state.me?.id+'|'+location.hash);if(!saved)return;
  const form=document.querySelector('[data-jr-search]');if(form&&saved.search)for(const [k,v] of Object.entries(saved.search))if(form.elements[k])form.elements[k].value=v;
  [...document.querySelectorAll('[data-jr-row]')].find(r=>r.dataset.jrRow===saved.focus)?.querySelector('a')?.focus({preventScroll:true});window.scrollTo(0,saved.y||0);
}
