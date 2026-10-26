'use strict';

async function openResearchCollection(id,position=null) {
  const generation=modalGeneration,account=state.me?.id,hash=location.hash;
  const c=await api('/api/collections/'+encodeURIComponent(id));if(generation!==modalGeneration||account!==state.me?.id||hash!==location.hash)return;state.detail={type:'collection',data:c};
  const reports=c.items.filter(r=>['compilation','research_report'].includes(r.kind)),materials=c.items.filter(r=>!['compilation','research_report'].includes(r.kind));
  const row=r=>'<article class="topic-record"><div>'+typeBadge(r.kind)+linkButton(esc(r.title),'detail',r.id,'title-button')+(r.rationale?'<p class="prose">'+esc(r.rationale)+'</p>':'')+'<div class="row wrap">'+linkButton('纳入／排除与理由','topic-decision',r.id)+'</div></div><button class="icon-button" data-action="topic-remove" data-id="'+esc(r.id)+'" data-collection="'+esc(c.id)+'" data-version="'+c.version+'" title="移出专题" aria-label="移出专题">'+icon('close')+'</button></article>';
  const chapters=[{id:'topic-question',label:'研究问题'},{id:'topic-content',label:'研究内容'},{id:'topic-reports',label:'报告与成果'},{id:'topic-materials',label:'资料与证据'},{id:'topic-review',label:'排除与检索覆盖'}];
  modal('研究专题','<article class="workspace-topic" data-collection="'+esc(c.id)+'" data-section-scope><div class="row wrap"><span class="badge blue">'+(c.visibility==='shared'?'中心共享':'仅创建者可见')+'</span><span class="small muted">版本 '+c.version+'</span></div><h2 class="detail-title">'+esc(c.name)+'</h2>'+(c.description?'<p class="prose">'+esc(c.description)+'</p>':'')+'<div class="detail-actions">'+linkButton(icon('plus')+' 编写报告','new-topic-report',c.id,'button primary')+(c.can_edit?linkButton(icon('edit')+' 编辑研究内容','edit-research-collection',c.id):'')+'<details class="topic-tools"><summary>历史与导出</summary><div class="detail-actions">'+linkButton(icon('clock')+' 修改历史','topic-history',c.id)+'<button class="button" data-action="export-content" data-query="collection='+encodeURIComponent(c.id)+'">'+icon('down')+' 导出专题内容</button></div></details></div>'
    +sectionNavigation(chapters,'专题章节')
    +'<section class="detail-section"><h3 id="topic-question">研究问题</h3><p class="prose">'+esc(c.research_question||'尚未填写研究问题。')+'</p></section><section class="detail-section"><h3 id="topic-content">研究内容</h3><h4>比较笔记</h4>'+(c.comparison_html?'<div class="rich-prose">'+readRich(c.comparison_html)+'</div>':'<p class="muted">尚无比较笔记。</p>')+'<h4>阶段判断</h4><p class="prose">'+esc(c.stage_judgment||'尚未填写阶段判断。')+'</p></section>'
    +'<section class="detail-section"><h3 id="topic-reports">报告与成果</h3>'+(reports.map(row).join('')||'<p class="muted">暂无报告与成果。</p>')+'</section><section class="detail-section"><h3 id="topic-materials">资料与证据</h3><p class="small muted">默认范围和计数仅含已纳入项。</p><p class="small muted">移出专题只解除关联，资料仍保留。</p>'+(materials.map(row).join('')||'<p class="muted">暂无资料，可在下面查找并加入。</p>')+'<form data-form="topic-search" data-collection="'+esc(c.id)+'" class="section-gap"><label for="topic-record-search">查找资料 / 笔记</label><div class="row"><input id="topic-record-search" name="q" placeholder="题名、正文或作者"><button class="button" type="submit">查找并添加</button></div><div class="form-error" role="alert"></div><div data-topic-results></div></form></section><section class="detail-section"><h3 id="topic-review">已排查并排除</h3>'+((c.excluded_items||[]).map(row).join('')||'<p class="muted">未登记排除项。</p>')+'<h3>检索覆盖日志</h3>'+scopeLogHTML(c.scope_log)+'</section></article>');
  if(position){const form=document.querySelector('[data-form=topic-search]');form.elements.q.value=position.q||'';if(position.searched)await searchTopic(form,position.page||1);document.querySelector('#modal-root .drawer-body').scrollTop=position.scroll||0;}
  if(typeof continuityRemember==='function')continuityRemember();
}
async function researchCollectionForm(id='',draftKey='') {
  const c=id?await api('/api/collections/'+encodeURIComponent(id)):{visibility:'shared',can_edit:true,can_manage_visibility:true};
  if(!c.can_edit)throw new Error('当前账号不能编辑此专题。');
  state.editing={type:'collection',id,version:c.version,original:c};state.links=[];
  modal(id?'编辑研究专题':'新建研究专题','<form data-form="research-collection"><div class="form-grid">'+inputField('name','专题名称 *',c.name,'',true)+textField('description','专题说明',c.description)+textField('research_question','研究问题',c.research_question,'这组资料用于回答什么问题？')+richEditor('comparison_html','比较笔记',c.comparison_html)+textField('stage_judgment','阶段判断',c.stage_judgment)+scopeLogEditor(c.scope_log)+selectField('visibility','可见范围',{shared:'中心共享，成员共同整理',private:'仅创建者可见'},c.visibility)+'</div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">关闭并保留草稿</button><button type="submit" class="button primary">保存专题</button></div></form>');
  const form=document.querySelector('[data-form=research-collection]');form._editing=state.editing;form.elements.visibility.disabled=!c.can_manage_visibility;renderScopeLogRows(form);await enableEditorDraft(form,state.editing,'',draftKey);
}
async function collectionConflict(form) {
  const latest=await api('/api/collections/'+encodeURIComponent(form._editing.id));if(!form.isConnected)return;
  form._conflictPending=true;form._dirty=true;saveEditorDraft(form,true);form.querySelector('[data-conflict-panel]')?.remove();
  const panel=document.createElement('section');panel.className='conflict-panel';panel.dataset.conflictPanel='';panel._latest=latest;
  const local=collectDraft(form).values;
  panel.innerHTML='<h3>专题已有新版本，当前草稿已保留</h3><p>当前基于 v'+esc(form._editing.version)+'，最新为 v'+latest.version+'。</p><div class="comparison-grid"><section><h4>你的比较笔记</h4><div class="rich-prose">'+readRich(local.comparison_html)+'</div></section><section><h4>最新比较笔记</h4><div class="rich-prose">'+readRich(latest.comparison_html)+'</div></section></div><div class="table-scroll"><table class="comparison-table"><tr><th>项目</th><th>你的输入</th><th>最新内容</th></tr>'+[['name','名称'],['description','说明'],['research_question','研究问题'],['stage_judgment','阶段判断'],['visibility','可见范围']].map(([k,l])=>'<tr><th>'+l+'</th><td>'+esc(local[k])+'</td><td>'+esc(latest[k])+'</td></tr>').join('')+'</table></div><p>最新专题中有 '+latest.items.length+' 份已纳入资料与成果。</p><div class="comparison-grid"><section><h4>你的排查日志</h4>'+scopeLogHTML(JSON.parse(local.scope_log_json||'[]'))+'</section><section><h4>最新排查日志</h4>'+scopeLogHTML(latest.scope_log)+'</section></div><button class="button primary" type="button" data-action="accept-latest-version">我已对照，以新版本继续编辑</button>';
  form.querySelector('.form-actions').before(panel);panel.scrollIntoView({block:'nearest'});
}
async function topicHistory(id) {
  const [h,c]=await Promise.all([api('/api/collections/'+encodeURIComponent(id)+'/history'),api('/api/collections/'+encodeURIComponent(id))]);state.detail={type:'collection',data:c};
  modal('专题修改历史','<p class="muted">恢复包括研究内容与当时的资料关联，可见范围保持当前设置。</p>'+h.items.map((r,i)=>'<article class="history-row"><div><strong>版本 '+r.version+' · '+esc(r.action)+'</strong><p>'+esc(r.actor_name)+' · '+dateTime(r.created_at)+'</p></div>'+'<div class="row wrap"><button class="button tiny" data-action="history-snapshot" data-id="'+r.id+'">查看内容</button>'+(i===0?'<span class="badge verified">当前版本</span>':'<button class="button tiny" data-action="restore-topic" data-id="'+r.id+'" data-collection="'+esc(id)+'" data-version="'+c.version+'">恢复此版本</button>')+'</div></article>').join('')+'<section data-history-snapshot class="detail-section" hidden></section>');
}
async function downloadContent(query='',button) {
  if(button)button.disabled=true;
  try{const response=await fetch('/api/export/content'+(query?'?'+query:''));if(!response.ok){const error=await response.json();throw new Error(error.error||'导出未完成。');}const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='research-content-'+new Date().toISOString().slice(0,10)+'.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);toast('完整内容已生成，正在下载');}finally{if(button)button.disabled=false;}
}
async function membersView() {
  const d=await api('/api/members');state.members=d.items;
  modal('本机成员管理','<div class="between wrap"><p>停用保留历史署名；需要时可重新启用。</p>'+linkButton(icon('plus')+' 创建成员','new-member','','button primary')+'</div><div class="table-scroll section-gap"><table class="member-table"><thead><tr><th>姓名 / 账号</th><th>角色</th><th>状态</th><th>操作</th></tr></thead><tbody>'+d.items.map(m=>'<tr><td><strong>'+esc(m.name)+'</strong><br><span class="muted">'+esc(m.username)+'</span></td><td>'+(m.role==='admin'?'资料管理员':'中心成员')+'</td><td>'+(m.active?'有效':'已停用')+'</td><td>'+linkButton('维护','edit-member',m.id)+'</td></tr>').join('')+'</tbody></table></div>');
}
function memberForm(id='') {
  const m=id?state.members.find(x=>x.id===id):{active:true,role:'researcher'};if(!m)throw new Error('请重新打开成员列表。');
  const lastAdmin=m.active&&m.role==='admin'&&state.members.filter(x=>x.active&&x.role==='admin').length===1;
  modal(id?'维护成员':'创建成员','<form data-form="member" data-id="'+esc(id)+'"><div class="stack">'+inputField('name','姓名 *',m.name)+(id?'<p>账号：'+esc(m.username)+'</p>':inputField('username','登录账号 *','','3–64 位字母、数字、点、下划线或连字符'))+selectField('role','角色',{researcher:'中心成员',admin:'资料管理员'},m.role)+(id?'<label class="check-label"><input type="checkbox" name="active" '+(m.active?'checked':'')+'>账号有效</label>':'')+'<div class="field"><label for="member-password">'+(id?'重置密码（留空则保持）':'初始密码 *')+'</label><input id="member-password" name="password" type="password" autocomplete="new-password" minlength="12" maxlength="200" '+(!id?'required':'')+'><p class="form-help">12–200 个字符。</p></div>'+(lastAdmin?'<p class="notice">这是最后一位有效管理员，不能停用或降为普通成员。</p>':'')+'</div><div class="form-error" role="alert"></div><div class="form-actions"><button class="button primary" type="submit">保存成员</button></div></form>',true);
  if(!id)document.querySelector('[name=username]').required=true;
}
function ownPasswordForm(){modal('修改我的密码','<form data-form="own-password"><div class="stack"><div class="field"><label for="old-password">当前密码</label><input id="old-password" type="password" name="old_password" required autocomplete="current-password"></div><div class="field"><label for="new-password">新密码（至少12个字符）</label><input id="new-password" type="password" name="new_password" required minlength="12" maxlength="200" autocomplete="new-password"></div><div class="field"><label for="repeat-password">再次输入新密码</label><input id="repeat-password" type="password" name="repeat_password" required autocomplete="new-password"></div></div><div class="form-error" role="alert"></div><div class="form-actions"><button class="button primary" type="submit">更新密码</button></div></form>',true);}
function operationsSystemCards(){
  const admin=state.me.role==='admin',role=admin?'资料管理员':'中心成员';
  return '<section class="system-card workspace-account" aria-labelledby="account-heading"><h2 id="account-heading">账号与成员</h2><p>'+esc(state.me.name)+(state.me.name.trim()!==role?' · '+role:'')+'</p><div class="detail-actions">'+(admin?linkButton('管理本机成员','manage-members','','button primary'):'')+linkButton('修改我的密码','own-password')+'</div>'+(!admin?'<p class="small muted">成员账号由资料管理员维护。</p>':'')+'</section>'
    +'<section class="system-card workspace-exports" aria-labelledby="exports-heading"><h2 id="exports-heading">导出与备份</h2><h3>可阅读的内容导出</h3><p>导出当前账号可读取的正文、附件、专题与引用证据，解压后可打开目录阅读。</p>'+linkButton(icon('down')+' 导出可见内容','export-content','','button')
    +'<section class="workspace-backup"><h3>完整数据备份</h3><p>包含所有平台资料、来源、关联、专题、收藏、账号、修订历史，以及在本平台上传的附件。</p><div class="notice">备份含所有账号的个人与受限资料，请由管理员保管。恢复到新目录后，可验证数据再切换使用。</div><div class="section-gap">'+(admin?linkButton(icon('down')+' 下载完整备份','backup','','button primary'):'<p class="small muted">请由资料管理员进行完整备份。</p>')+'</div></section></section>';
}

document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-action]');if(!b)return;const a=b.dataset.action,id=b.dataset.id;
  try{
    if(a==='edit-research-collection')await researchCollectionForm(id);
    else if(a==='topic-decision')await topicDecisionForm(id);
    else if(a==='scope-log-add'||a==='scope-log-remove'){const form=b.closest('form');syncCollectionScopeLog(form);const rows=JSON.parse(form.elements.scope_log_json.value);if(a==='scope-log-add')rows.push({outcome:'found'});else rows.splice(Number(b.dataset.id),1);form.elements.scope_log_json.value=JSON.stringify(rows);renderScopeLogRows(form);form._dirty=true;saveEditorDraft(form,true);}
    else if(a==='topic-item-rebase'){const form=b.closest('form');form.dataset.version=b.dataset.version;form.querySelector('[data-item-conflict]').remove();form._conflictPending=false;}
    else if(a==='topic-history')await topicHistory(id);
    else if(a==='restore-topic'){await api('/api/collections/'+encodeURIComponent(b.dataset.collection)+'/restore/'+id,{method:'POST',body:{version:Number(b.dataset.version)}});await loadLookups();await openResearchCollection(b.dataset.collection);toast('专题版本已恢复');}
    else if(a==='new-topic-report'){await workflowRecordForm('','research_report','collection:'+id);const f=currentEditorForm();if(f)f.dataset.collectionId=id;}
    else if(a==='topic-add'||a==='topic-remove'){const buttons=[...b.closest('.drawer').querySelectorAll('button')].map(el=>[el,el.disabled]);buttons.forEach(([el])=>el.disabled=true);try{await api('/api/collections/'+encodeURIComponent(b.dataset.collection)+'/items',{method:'POST',body:{record_id:id,remove:a==='topic-remove',version:state.detail.data.version}});const position=topicPosition();await loadLookups();await openResearchCollection(b.dataset.collection,position);}finally{buttons.forEach(([el,disabled])=>{if(el.isConnected)el.disabled=disabled;});}}
    else if(a==='export-content')await downloadContent(b.dataset.query||'',b);
    else if(a==='manage-members')await membersView();
    else if(a==='new-member')memberForm();
    else if(a==='edit-member')memberForm(id);
    else if(a==='own-password')ownPasswordForm();
  }catch(error){toast(error.message);}
});
document.addEventListener('submit',async event=>{
  const form=event.target,type=form.dataset.form;if(!['research-collection','topic-decision','topic-search','member','own-password'].includes(type))return;
  event.preventDefault();const account=state.me?.id,generation=modalGeneration,active=()=>form.isConnected&&account===state.me?.id&&generation===modalGeneration;const error=form.querySelector('.form-error'),button=form.querySelector('[type=submit]');button.disabled=type!=='topic-search';error.textContent='';
  try{
    if(type==='topic-search'){await searchTopic(form);}
    else if(type==='topic-decision'){if(form._conflictPending)throw new Error('请先对照专题最新版本。');const values=Object.fromEntries(new FormData(form));values.version=Number(form.dataset.version);values.record_id=form.dataset.record;await api('/api/collections/'+encodeURIComponent(form.dataset.collection)+'/items',{method:'POST',body:values});if(!active())return;await loadLookups();if(!active())return;await openResearchCollection(form.dataset.collection);toast('专题条目决定已保存');}
    else if(type==='research-collection'){if(form._draftOffer||form._conflictPending)throw new Error('请先恢复草稿或完成版本对照。');syncRichForm(form);const edit=form._editing,values=Object.fromEntries(new FormData(form));values.version=edit.version;values.visibility=form.elements.visibility.disabled?edit.original.visibility:form.elements.visibility.value;const r=await api('/api/collections'+(edit.id?'/'+encodeURIComponent(edit.id):''),{method:edit.id?'PUT':'POST',body:values});if(!active())return;await clearEditorDraft(form);await loadLookups();if(!active())return;await uxRefreshBackground();if(!active())return;await openResearchCollection(r.id);toast('专题研究内容已保存');}
    else if(type==='member'){const values=Object.fromEntries(new FormData(form));if(!values.password)delete values.password;if(form.dataset.id)values.active=form.elements.active.checked;const r=await api('/api/members'+(form.dataset.id?'/'+encodeURIComponent(form.dataset.id):''),{method:form.dataset.id?'PUT':'POST',body:values});if(r.reauthenticate){state.me=null;state.loadId++;announceAccount();const session=await api('/api/session');state.csrf=session.csrf;showLogin();toast('账号信息已更新，请重新登录。');}else{await loadLookups();await membersView();toast('成员信息已保存');}}
    else{const values=Object.fromEntries(new FormData(form));if(values.new_password!==values.repeat_password)throw new Error('两次新密码不一致。');delete values.repeat_password;await api('/api/account/password',{method:'POST',body:values});closeModal();toast('密码已更新');}
  }catch(e){error.textContent=e.message;if(type==='research-collection'&&e.status===409)await collectionConflict(form);if(type==='topic-decision'&&e.status===409)await topicDecisionConflict(form);}finally{if(button.isConnected)button.disabled=false;}
});

let topicSearchEpoch=0;
function topicPosition(){const form=document.querySelector('[data-form=topic-search]');return form?{id:form.dataset.collection,q:form.elements.q.value,page:Number(form.dataset.page||1),searched:form.dataset.searched==='true',scroll:document.querySelector('#modal-root .drawer-body').scrollTop}:null;}
async function searchTopic(form,page=1){
 const epoch=++topicSearchEpoch,q=form.elements.q.value.trim(),account=state.me?.id,el=form.querySelector('[data-topic-results]');form.dataset.searched='true';
 el.innerHTML='<p role="status">正在查找资料…</p>';
 try{const data=await api('/api/record-candidates?'+new URLSearchParams({purpose:'collection',target_collection:form.dataset.collection,size:30,q,page}));
 if(epoch!==topicSearchEpoch||account!==state.me?.id||!form.isConnected||form.elements.q.value.trim()!==q)return;
 form.dataset.page=data.page;el.innerHTML=candidatePager(data,'topic-page')+data.items.map(r=>'<button class="detail-link" type="button" data-action="topic-add" data-id="'+esc(r.id)+'" data-collection="'+esc(form.dataset.collection)+'">'+icon('plus')+' '+esc(r.title)+' · '+esc(kinds[r.kind])+'</button>').join('')+(data.total?'':'<p class="muted">没有匹配的可添加内容，已加入的资料不再列出。</p>');
 if(typeof continuityRemember==='function')continuityRemember();
 }catch(error){if(epoch===topicSearchEpoch&&form.isConnected&&form.elements.q.value.trim()===q)el.innerHTML='<p class="notice error" role="alert">'+esc(error.message)+'</p>';}
}
document.addEventListener('click',event=>{const b=event.target.closest('[data-action="topic-page"]');if(b)searchTopic(b.closest('form'),Number(b.dataset.page));});
document.addEventListener('input',event=>{if(event.target.id==='topic-record-search'){topicSearchEpoch++;const form=event.target.form;form.dataset.searched='false';form.querySelector('[data-topic-results]').innerHTML='';if(typeof continuityRemember==='function')continuityRemember();}});

const scopeOutcomes={found:'找到结果',zero_results:'无结果',access_blocked:'访问受阻'};
function scopeLogHTML(log=[]){
  return log.length?log.map(entry=>'<article class="scope-log-entry"><h4>'+esc(scopeOutcomes[entry.outcome]||entry.outcome)+'</h4><dl class="comparison-fields">'+[['source','来源'],['query','检索词'],['time_range','时间范围'],['language','语种'],['searched_on','实际检索日期'],['notes','说明']].filter(([key])=>entry[key]).map(([key,label])=>detailPair(label,esc(entry[key]))).join('')+'</dl></article>').join(''):'<p class="muted">未登记检索。</p>';
}
function scopeLogEditor(log=[]){return '<section class="wide" data-scope-log-editor><h3>检索覆盖日志</h3><p class="form-help">记录实际排查范围。没有日志仅表示未登记检索。</p><textarea name="scope_log_json" hidden>'+esc(JSON.stringify(log))+'</textarea><div data-scope-log-rows></div><button type="button" class="button" data-action="scope-log-add">添加排查记录</button></section>';}
function renderScopeLogRows(form){
  const root=form.querySelector('[data-scope-log-rows]');if(!root)return;
  const entries=JSON.parse(form.elements.scope_log_json.value||'[]');
  root.innerHTML=entries.map((entry,index)=>'<fieldset class="scope-log-entry" data-scope-log-row><legend>排查记录 '+(index+1)+'</legend><div class="form-grid">'+[['source','来源'],['query','检索词'],['time_range','时间范围'],['language','语种'],['searched_on','实际检索日期 *'],['notes','说明']].map(([key,label])=>'<label class="field">'+label+'<'+(key==='notes'?'textarea':'input')+' data-scope-key="'+key+'" '+(key==='searched_on'?'type="date" required':'')+(key==='notes'?'>'+esc(entry[key]||'')+'</textarea>':' value="'+esc(entry[key]||'')+'">')+'</label>').join('')+'<label class="field">结果状态 *<select data-scope-key="outcome">'+selectOptions(scopeOutcomes,entry.outcome||'found')+'</select></label></div><button type="button" class="button tiny" data-action="scope-log-remove" data-id="'+index+'">移除此条排查记录</button></fieldset>').join('');
}
function syncCollectionScopeLog(form){
  if(!form.querySelector('[data-scope-log-editor]'))return;
  form.elements.scope_log_json.value=JSON.stringify([...form.querySelectorAll('[data-scope-log-row]')].map(row=>Object.fromEntries([...row.querySelectorAll('[data-scope-key]')].map(el=>[el.dataset.scopeKey,el.value]))));
}
async function topicDecisionForm(id){
  const c=state.detail.data,r=[...c.items,...(c.excluded_items||[])].find(r=>r.id===id);if(!r)return;
  modal('专题条目决定','<form data-form="topic-decision" data-collection="'+esc(c.id)+'" data-record="'+esc(id)+'" data-version="'+c.version+'"><h3>'+esc(r.title)+'</h3><div class="form-grid">'+selectField('disposition','条目决定',{included:'已纳入',excluded:'已排查并排除'},r.disposition)+textField('rationale','纳入／排除理由',r.rationale,'排除资料必须说明理由。')+'</div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="open-collection" data-id="'+esc(c.id)+'">返回专题</button><button type="submit" class="button primary">保存条目决定</button></div></form>');
}
async function topicDecisionConflict(form){
  try{const latest=await api('/api/collections/'+encodeURIComponent(form.dataset.collection));if(!form.isConnected)return;
    form._conflictPending=true;form.querySelector('[data-item-conflict]')?.remove();const panel=document.createElement('section');panel.dataset.itemConflict='';panel.className='conflict-panel';
    const item=[...latest.items,...(latest.excluded_items||[])].find(r=>r.id===form.dataset.record);
    panel.innerHTML='<h3>专题已有新版本，当前输入已保留</h3><p>最新专题版本 '+latest.version+'。</p><p>'+esc(item?((item.disposition==='excluded'?'已排查并排除':'已纳入')+'；理由：'+(item.rationale||'未登记')):'当前条目已移出专题或不可见。')+'</p><button type="button" class="button primary" data-action="topic-item-rebase" data-version="'+latest.version+'">我已对照，继续保存决定</button>';
    form.querySelector('.form-actions').before(panel);
  }catch(error){if(form.isConnected)form.querySelector('.form-error').textContent=error.message+' 当前输入已保留。';}
}
