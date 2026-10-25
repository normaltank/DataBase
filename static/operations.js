'use strict';

async function openResearchCollection(id) {
  const c=await api('/api/collections/'+encodeURIComponent(id));state.detail={type:'collection',data:c};
  const reports=c.items.filter(r=>['compilation','research_report'].includes(r.kind)),materials=c.items.filter(r=>!['compilation','research_report'].includes(r.kind));
  const row=r=>'<article class="topic-record"><div>'+typeBadge(r.kind)+linkButton(esc(r.title),'detail',r.id,'title-button')+'</div><button class="icon-button" data-action="topic-remove" data-id="'+esc(r.id)+'" data-collection="'+esc(c.id)+'" title="移出专题" aria-label="移出专题">'+icon('close')+'</button></article>';
  modal('研究专题','<div class="row wrap"><span class="badge blue">'+(c.visibility==='shared'?'中心共享':'仅创建者可见')+'</span><span class="muted">版本 '+c.version+'</span></div><h2 class="detail-title">'+esc(c.name)+'</h2><p class="prose">'+esc(c.description)+'</p><div class="detail-actions">'+(c.can_edit?linkButton(icon('edit')+' 编辑研究内容','edit-research-collection',c.id):'')+linkButton(icon('clock')+' 历史','topic-history',c.id)+linkButton(icon('plus')+' 编写报告','new-topic-report',c.id,'button primary')+'<button class="button tiny" data-action="export-content" data-query="collection='+encodeURIComponent(c.id)+'">'+icon('down')+' 导出专题内容</button></div>'
    +'<section class="detail-section"><h3>研究问题</h3><p class="prose">'+esc(c.research_question||'尚未填写研究问题。')+'</p></section><section class="detail-section"><h3>比较笔记</h3>'+(c.comparison_html?'<div class="rich-prose">'+readRich(c.comparison_html)+'</div>':'<p class="muted">尚无比较笔记。</p>')+'</section><section class="detail-section"><h3>阶段判断</h3><p class="prose">'+esc(c.stage_judgment||'尚未填写阶段判断。')+'</p></section>'
    +'<section class="detail-section"><h3>报告与成果</h3>'+(reports.map(row).join('')||'<p class="muted">可从上方编写一份报告。</p>')+'</section><section class="detail-section"><h3>资料与证据</h3>'+(materials.map(row).join('')||'<p class="muted">从资料详情加入，或在下面查找。</p>')+'<form data-form="topic-search" data-collection="'+esc(c.id)+'" class="section-gap"><label for="topic-record-search">查找资料 / 笔记</label><div class="row"><input id="topic-record-search" name="q" placeholder="题名、正文或作者"><button class="button" type="submit">查找并添加</button></div><div class="form-error" role="alert"></div><div data-topic-results></div></form></section>');
}
async function researchCollectionForm(id='',draftKey='') {
  const c=id?await api('/api/collections/'+encodeURIComponent(id)):{visibility:'shared',can_edit:true,can_manage_visibility:true};
  if(!c.can_edit)throw new Error('当前账号不能编辑此专题。');
  state.editing={type:'collection',id,version:c.version,original:c};state.links=[];
  modal(id?'编辑研究专题':'新建研究专题','<form data-form="research-collection"><div class="form-grid">'+inputField('name','专题名称 *',c.name,'',true)+textField('description','专题说明',c.description)+textField('research_question','研究问题',c.research_question,'这组资料用于回答什么问题？')+richEditor('comparison_html','比较笔记',c.comparison_html)+textField('stage_judgment','阶段判断',c.stage_judgment)+selectField('visibility','可见范围',{shared:'中心共享，成员共同整理',private:'仅创建者可见'},c.visibility)+'</div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">关闭并保留草稿</button><button type="submit" class="button primary">保存专题</button></div></form>');
  const form=document.querySelector('[data-form=research-collection]');form._editing=state.editing;form.elements.visibility.disabled=!c.can_manage_visibility;await enableEditorDraft(form,state.editing,'',draftKey);
}
async function collectionConflict(form) {
  const latest=await api('/api/collections/'+encodeURIComponent(form._editing.id));if(!form.isConnected)return;
  form._conflictPending=true;form._dirty=true;saveEditorDraft(form,true);form.querySelector('[data-conflict-panel]')?.remove();
  const panel=document.createElement('section');panel.className='conflict-panel';panel.dataset.conflictPanel='';panel._latest=latest;
  const local=collectDraft(form).values;
  panel.innerHTML='<h3>专题已有新版本，当前草稿已保留</h3><p>当前基于 v'+esc(form._editing.version)+'，最新为 v'+latest.version+'。</p><div class="comparison-grid"><section><h4>你的比较笔记</h4><div class="rich-prose">'+readRich(local.comparison_html)+'</div></section><section><h4>最新比较笔记</h4><div class="rich-prose">'+readRich(latest.comparison_html)+'</div></section></div><div class="table-scroll"><table class="comparison-table"><tr><th>项目</th><th>你的输入</th><th>最新内容</th></tr>'+[['name','名称'],['description','说明'],['research_question','研究问题'],['stage_judgment','阶段判断'],['visibility','可见范围']].map(([k,l])=>'<tr><th>'+l+'</th><td>'+esc(local[k])+'</td><td>'+esc(latest[k])+'</td></tr>').join('')+'</table></div><p>最新专题中有 '+latest.items.length+' 份可见资料与成果。</p><button class="button primary" type="button" data-action="accept-latest-version">我已对照，以新版本继续编辑</button>';
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
  const admin=state.me.role==='admin';
  return '<section class="system-card workspace-account" aria-labelledby="account-heading"><h2 id="account-heading">账号与成员</h2><p>'+esc(state.me.name)+' · '+(admin?'资料管理员':'中心成员')+'</p><div class="detail-actions">'+(admin?linkButton('管理本机成员','manage-members','','button primary'):'')+linkButton('修改我的密码','own-password')+'</div>'+(!admin?'<p class="small muted">成员账号由资料管理员维护。</p>':'')+'</section>'
    +'<section class="system-card workspace-exports" aria-labelledby="exports-heading"><h2 id="exports-heading">导出与备份</h2><h3>可阅读的内容导出</h3><p>导出当前账号可读取的正文、附件、专题与引用证据，解压后可打开目录阅读。</p>'+linkButton(icon('down')+' 导出可见内容','export-content','','button')
    +'<section class="workspace-backup"><h3>完整数据备份</h3><p>包含所有平台资料、来源、关联、专题、收藏、账号、修订历史，以及在本平台上传的附件。</p><div class="notice">备份含所有账号的个人与受限资料，请由管理员保管。恢复到新目录后，可验证数据再切换使用。</div><div class="section-gap">'+(admin?linkButton(icon('down')+' 下载完整备份','backup','','button primary'):'<p class="small muted">请由资料管理员进行完整备份。</p>')+'</div></section></section>';
}

document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-action]');if(!b)return;const a=b.dataset.action,id=b.dataset.id;
  try{
    if(a==='edit-research-collection')await researchCollectionForm(id);
    else if(a==='topic-history')await topicHistory(id);
    else if(a==='restore-topic'){await api('/api/collections/'+encodeURIComponent(b.dataset.collection)+'/restore/'+id,{method:'POST',body:{version:Number(b.dataset.version)}});await loadLookups();await openResearchCollection(b.dataset.collection);toast('专题版本已恢复');}
    else if(a==='new-topic-report'){await workflowRecordForm('','research_report','collection:'+id);const f=currentEditorForm();if(f)f.dataset.collectionId=id;}
    else if(a==='topic-add'||a==='topic-remove'){const buttons=[...b.closest('.drawer').querySelectorAll('button')].map(el=>[el,el.disabled]);buttons.forEach(([el])=>el.disabled=true);try{await api('/api/collections/'+encodeURIComponent(b.dataset.collection)+'/items',{method:'POST',body:{record_id:id,remove:a==='topic-remove'}});await loadLookups();await route();await openResearchCollection(b.dataset.collection);}finally{buttons.forEach(([el,disabled])=>{if(el.isConnected)el.disabled=disabled;});}}
    else if(a==='export-content')await downloadContent(b.dataset.query||'',b);
    else if(a==='manage-members')await membersView();
    else if(a==='new-member')memberForm();
    else if(a==='edit-member')memberForm(id);
    else if(a==='own-password')ownPasswordForm();
  }catch(error){toast(error.message);}
});
document.addEventListener('submit',async event=>{
  const form=event.target,type=form.dataset.form;if(!['research-collection','topic-search','member','own-password'].includes(type))return;
  event.preventDefault();const error=form.querySelector('.form-error'),button=form.querySelector('[type=submit]');button.disabled=true;error.textContent='';
  try{
    if(type==='topic-search'){const d=await api('/api/records?size=30&q='+encodeURIComponent(form.elements.q.value));form.querySelector('[data-topic-results]').innerHTML=d.items.map(r=>'<button class="detail-link" type="button" data-action="topic-add" data-id="'+esc(r.id)+'" data-collection="'+esc(form.dataset.collection)+'">'+icon('plus')+' '+esc(r.title)+' · '+esc(kinds[r.kind])+'</button>').join('')||'<p class="muted">没有匹配的内容。</p>';}
    else if(type==='research-collection'){if(form._draftOffer||form._conflictPending)throw new Error('请先恢复草稿或完成版本对照。');syncRichForm(form);const edit=form._editing,values=Object.fromEntries(new FormData(form));values.version=edit.version;values.visibility=form.elements.visibility.disabled?edit.original.visibility:form.elements.visibility.value;const r=await api('/api/collections'+(edit.id?'/'+encodeURIComponent(edit.id):''),{method:edit.id?'PUT':'POST',body:values});await clearEditorDraft(form);await loadLookups();await route();await openResearchCollection(r.id);toast('专题研究内容已保存');}
    else if(type==='member'){const values=Object.fromEntries(new FormData(form));if(!values.password)delete values.password;if(form.dataset.id)values.active=form.elements.active.checked;const r=await api('/api/members'+(form.dataset.id?'/'+encodeURIComponent(form.dataset.id):''),{method:form.dataset.id?'PUT':'POST',body:values});if(r.reauthenticate){state.me=null;state.loadId++;announceAccount();const session=await api('/api/session');state.csrf=session.csrf;showLogin();toast('账号信息已更新，请重新登录。');}else{await loadLookups();await membersView();toast('成员信息已保存');}}
    else{const values=Object.fromEntries(new FormData(form));if(values.new_password!==values.repeat_password)throw new Error('两次新密码不一致。');delete values.repeat_password;await api('/api/account/password',{method:'POST',body:values});closeModal();toast('密码已更新');}
  }catch(e){error.textContent=e.message;if(type==='research-collection'&&e.status===409)await collectionConflict(form);}finally{if(button.isConnected)button.disabled=false;}
});
