'use strict';

const personProfileLabels={introduction:'人物介绍',chinese_name:'中文姓名',original_name:'原名',aliases:'其他姓名写法',employment:'任职经历（单独选择）'};
const personProfileStates={queued:'等待后台取得',running:'正在取得与整理',paused:'暂停待恢复',failed:'取得或处理失败',invalidated:'人物或授权已变化',cancelled:'已取消',ready:'建议待人工核对',empty:'无新增适用建议',pending:'待人工核对',adopted:'已采用',rejected:'已拒绝'};
function personProfilePath(id){return '/api/people/'+encodeURIComponent(id)+'/profile-suggestions';}
function personProfileProse(value){if(Array.isArray(value))value=value.map(x=>[x.institution_name||state.sources.find(s=>s.id===x.institution_id)?.name||'既有任职机构',x.role,x.start_date||'起始不详',x.end_date||'结束不详'].join(' · ')).join('\n');else if(value&&typeof value==='object')value=[value.institution_name,value.role,value.start_date||'起始不详',value.end_date||'结束不详'].join(' · ');return '<p>'+esc(value||'未填写').replace(/\n/g,'<br>')+'</p>';}

function personProfileReview(data,selected=new Set(),opened=new Set()){
  const pending=data.candidates.filter(c=>c.status==='pending');
  return `<div data-person-profile-review data-version="${data.version}"><div class="between wrap"><h3>取得与整理进度</h3><button type="button" class="button" data-person-profile-action="refresh">刷新进度</button></div>${data.jobs.slice(0,4).map(j=>`<p role="status"><strong>${esc(personProfileStates[j.status]||j.status)}</strong> · ${dateTime(j.created_at)}${j.reason?'<br>'+esc(j.reason):''}${['queued','running','paused'].includes(j.status)?` <button type="button" class="button" data-person-profile-action="cancel" data-job="${esc(j.id)}">取消任务</button>`:''}</p>`).join('')||'<p class="muted">尚未排队。先选择明确的个人页，再生成有据建议。</p>'}
    <p class="muted">后台未配置、暂停或额度不足时，任务会等待；资料管理员可在“中文处理与费用”维护查看并恢复。</p><form data-person-profile-form="decide"><h3>原值、机器建议与实际依据</h3>${data.candidates.map(c=>`<section class="person-sources"><div class="between wrap"><h4>${c.status==='pending'?`<label class="check-label"><input type="checkbox" name="candidate" value="${esc(c.id)}" ${selected.has(c.id)?'checked':''}>${esc(personProfileLabels[c.field]||c.field)}</label>`:esc(personProfileLabels[c.field]||c.field)}</h4><span class="badge ${c.status==='pending'?'pending':'neutral'}">${esc(personProfileStates[c.status]||c.status)}</span></div><div class="comparison-grid"><section><strong>生成时原值</strong>${personProfileProse(c.before)}</section><section><strong>机器建议</strong>${personProfileProse(c.value)}</section></div>${c.stale&&c.status==='pending'?`<p class="notice">人物档案、身份或排队账号状态已有变化，旧建议不能直接采用。请对照当前值后重新排队。</p><details><summary>当前档案值</summary>${personProfileProse(data.current[c.field])}</details>`:''}<blockquote>${esc(c.evidence.quote)}</blockquote><p>${externalLink(c.evidence.url,'查看原页')} · 取得 ${dateTime(c.evidence.fetched_at)}</p><details data-profile-open="${esc(c.id)}" ${opened.has(c.id)?'open':''}><summary>建议版本与机器来历</summary><p class="prose">基于人物版本 ${c.base_version} · ${esc(c.machine.response_model||c.machine.requested_model||'合成演示，无模型调用')}<br>证据 ${esc(c.evidence.id)}<br>SHA256 ${esc(c.evidence.sha256)}</p></details>${c.decided_by?`<p class="muted">${esc(c.decided_by)} · ${dateTime(c.decided_at)}</p>`:''}</section>`).join('')||'<p class="muted">尚无机器建议。实际取得的原文可在下方独立查阅。</p>'}<p class="form-error" role="alert"></p><div class="form-actions"><button type="submit" class="button primary" name="decision" value="adopt" ${pending.length?'':'disabled'}>采用所选建议</button><button type="submit" class="button" name="decision" value="reject" ${pending.length?'':'disabled'}>拒绝所选建议</button></div></form>
    <h3>完整人物原文与出处</h3>${data.materials.map(m=>`<details class="person-history-item" data-profile-open="${esc(m.id)}" ${opened.has(m.id)?'open':''}><summary>${esc(m.subject||'未识别人物主标题')} · 取得 ${dateTime(m.fetched_at)}</summary>${m.problem?'<p class="notice">'+esc(m.problem)+'</p>':''}<div class="rich-prose">${personProfileProse(m.biography||'未取得可用人物介绍。')}</div><p>${externalLink(m.url,'查看原始个人页')}</p><p class="prose">SHA256 ${esc(m.sha256)}<br>证据版本 ${esc(m.id)}</p>${m.works.length?`<h4>页面列示作品题录与链接</h4><ul>${m.works.map(w=>`<li>${externalLink(w.url,w.title)}</li>`).join('')}</ul><p class="muted">仅保存题录和链接，未下载作品全文，也未确认作品归属。</p>`:''}</details>`).join('')||'<p class="muted">尚无实际取得的材料；排队或姓名候选不表示原文已取得。</p>'}
    <p><a class="button" href="${personProfilePath(data.target_id)}/export" download>导出原文、建议与决定</a></p><details data-profile-open="events" ${opened.has('events')?'open':''}><summary>取得与人工决定历史</summary>${data.events.map(e=>`<p>${esc(personProfileStates[e.action]||({acquired:'已保存实际材料',proposed:'已生成机器建议',retry:'人工恢复任务'}[e.action])||e.action)} · ${esc(e.actor_id)} · ${dateTime(e.created_at)}</p>`).join('')||'<p>暂无历史。</p>'}</details></div>`;
}

async function personProfileSection(person){
  const data=await api(personProfilePath(person.id));
  if(data.jobs.some(j=>['queued','running'].includes(j.status))){const account=state.me.id;setTimeout(()=>{const root=document.querySelector('[data-person-profile="'+CSS.escape(person.id)+'"]');if(root&&personProfileActive(root,account))refreshPersonProfile(root).catch(()=>{});},0);}
  return `<section class="person-section" id="person-profile-enrichment" data-person-profile="${esc(person.id)}" data-profile-account="${esc(state.me.id)}"><h2>公开介绍与有据补全</h2><p>按姓名查找百科候选，或选用明确的大学、机构、ORCID 个人页。完整原文与机器中文概括分别保存，采用前由成员核对。</p><details data-person-profile-find><summary>查找公开介绍／生成有据补全</summary><form data-person-profile-form="search" class="workflow-form"><div class="form-grid">${inputField('name','检索姓名',person.original_name||person.name)}<label class="field">百科语种<select name="language"><option value="en">英语</option><option value="et">爱沙尼亚语</option><option value="lv">拉脱维亚语</option><option value="de">德语</option><option value="fr">法语</option><option value="zh">中文</option></select></label></div><button type="submit" class="button">查找百科候选</button><p class="form-error" role="alert"></p><div data-profile-search-result aria-live="polite"></div></form>${data.profile_links?.length?`<h3>已有个人页线索</h3><ul>${data.profile_links.map(link=>`<li>${externalLink(link.url,link.url)}<br>${esc(link.origin)} <button type="button" class="button" data-person-profile-action="select-url" data-url="${esc(link.url)}">选用此页</button></li>`).join('')}</ul>`:''}<form data-person-profile-form="queue" class="workflow-form"><div class="field"><label>明确的公开个人页网址<input name="url" type="url" required placeholder="粘贴大学、机构、百科或 ORCID 个人页"></label></div><label class="check-label"><input name="identity_confirmation" type="checkbox" required>我已打开原页，核对这是本档案人物的介绍页；同名检索本身不作依据。</label><p class="muted">只取得选定个人页的完整介绍、履历与出处；作品保存题录及链接。此操作不会确认其他作品、合并人物或标记已核对。</p><button type="submit" class="button primary">取得原文并生成有据建议</button><p class="form-error" role="alert"></p><p data-profile-queue-status role="status"></p></form></details><div data-person-profile-results>${personProfileReview(data)}</div></section>`;
}

function personProfileActive(root,account){return root.isConnected&&state.me?.id===account&&root.dataset.profileAccount===account;}
async function refreshPersonProfile(root){
  const account=root.dataset.profileAccount,turn=(root._profileTurn||0)+1;root._profileTurn=turn;
  const data=await api(personProfilePath(root.dataset.personProfile));
  if(!personProfileActive(root,account)||root._profileTurn!==turn)return;
  const results=root.querySelector('[data-person-profile-results]');
  const selected=new Set([...results.querySelectorAll('[name=candidate]:checked')].map(x=>x.value));
  const opened=new Set([...results.querySelectorAll('[data-profile-open][open]')].map(x=>x.dataset.profileOpen));
  const active=document.activeElement,focus=results.contains(active)?{name:active.name,value:active.value,action:active.dataset.personProfileAction,job:active.dataset.job}:null;
  results.innerHTML=personProfileReview(data,selected,opened);
  if(focus){const target=focus.name?results.querySelector('[name="'+CSS.escape(focus.name)+'"][value="'+CSS.escape(focus.value||'')+'"]'):focus.action?results.querySelector('[data-person-profile-action="'+CSS.escape(focus.action)+'"]'+(focus.job?'[data-job="'+CSS.escape(focus.job)+'"]':'')):null;target?.focus({preventScroll:true});}
  clearTimeout(root._profileTimer);
  if(data.jobs.some(j=>['queued','running'].includes(j.status)))root._profileTimer=setTimeout(()=>{if(personProfileActive(root,account))refreshPersonProfile(root).catch(error=>{const slot=root.querySelector('[data-profile-queue-status]');if(slot)slot.textContent=error.message;});},3000);
}

document.addEventListener('click',async event=>{
  const open=event.target.closest('[data-person-profile-open]');if(open){const root=document.querySelector('[data-person-profile="'+CSS.escape(open.dataset.personProfileOpen)+'"]');if(root){root.querySelector('[data-person-profile-find]').open=true;root.scrollIntoView({block:'start'});root.querySelector('[name=name]').focus({preventScroll:true});}return;}
  const button=event.target.closest('[data-person-profile-action]');if(!button)return;
  const root=button.closest('[data-person-profile]');if(!root)return;
  const account=root.dataset.profileAccount;if(!personProfileActive(root,account))return;
  button.disabled=true;
  try{
    if(button.dataset.personProfileAction==='select-url'){
      const form=root.querySelector('[data-person-profile-form=queue]');form.elements.url.value=button.dataset.url;form.elements.identity_confirmation.checked=false;form.elements.url.focus();return;
    }
    if(button.dataset.personProfileAction==='cancel')await api('/api/archive-jobs/'+encodeURIComponent(button.dataset.job)+'/cancel',{method:'POST',body:{}});
    if(personProfileActive(root,account))await refreshPersonProfile(root);
  }catch(error){if(personProfileActive(root,account))toast(error.message);}finally{if(button.isConnected)button.disabled=false;}
});

document.addEventListener('submit',async event=>{
  const form=event.target;if(!form.dataset.personProfileForm)return;event.preventDefault();
  if(form.dataset.saving==='true')return;
  const root=form.closest('[data-person-profile]'),account=root.dataset.profileAccount;if(!personProfileActive(root,account))return;
  const button=event.submitter,errorSlot=form.querySelector('.form-error');errorSlot.textContent='';form.dataset.saving='true';if(button)button.disabled=true;
  const value=Object.fromEntries(new FormData(form));
  try{
    const version=Number(root.querySelector('[data-person-profile-review]').dataset.version);
    if(form.dataset.personProfileForm==='search'){
      const result=await api('/api/people/'+encodeURIComponent(root.dataset.personProfile)+'/profile-candidates',{method:'POST',body:value});
      if(!personProfileActive(root,account))return;
      form.querySelector('[data-profile-search-result]').innerHTML=`<p>${esc(result.reason)}</p>${result.candidates.map(c=>`<section><h4>${esc(c.title)}</h4><p>${esc(c.snippet)}</p>${externalLink(c.url,'打开百科原页')} <button type="button" class="button" data-person-profile-action="select-url" data-url="${esc(c.url)}">选用此页</button></section>`).join('')}`;
    }else if(form.dataset.personProfileForm==='queue'){
      const result=await api(personProfilePath(root.dataset.personProfile),{method:'POST',body:{url:value.url,version,identity_confirmation:form.elements.identity_confirmation.checked,request_id:form._requestId||(form._requestId=crypto.randomUUID())}});
      if(!personProfileActive(root,account))return;
      form._requestId=null;form.querySelector('[data-profile-queue-status]').textContent='已加入统一后台队列。取得结果及待采用建议在下方显示。';await refreshPersonProfile(root);
    }else{
      const ids=new FormData(form).getAll('candidate');if(!ids.length)throw new Error('请先勾选具体建议，再采用或拒绝。');
      await api(personProfilePath(root.dataset.personProfile)+'/decide',{method:'POST',body:{version,[button.value]:ids}});
      if(!personProfileActive(root,account))return;
      if(button.value==='adopt'){await route();document.getElementById('person-profile-enrichment')?.scrollIntoView({block:'start'});}else await refreshPersonProfile(root);toast(button.value==='adopt'?'已形成新的人物档案版本，人工决定与原文已留档':'已拒绝所选建议，原始材料保留');
    }
  }catch(error){if(personProfileActive(root,account)){if(error.status===409)await refreshPersonProfile(root).catch(()=>{});const slot=form.isConnected?errorSlot:root.querySelector('[data-person-profile-form=decide] .form-error');if(slot)slot.textContent=error.message;}}
  finally{form.dataset.saving='false';if(button?.isConnected)button.disabled=false;}
});

document.addEventListener('input',event=>{const form=event.target.closest('[data-person-profile-form=queue]');if(form)form._requestId=null;});
