'use strict';
// One read-only surface for maintenance and object feedback. Callers supply a
// job; selection, evidence matching, readable values and DOM continuity live here.
const maintenanceTracePending=new Map();
const maintenanceTraceRoots=new Set();
const maintenanceTraceFields={keywords:'标签',introduction_html:'简介',bylines:'作者归属',affiliations:'署名单位',countries:'研究对象国',name:'姓名',original_name:'原名',chinese_name:'中文名',aliases:'其他名称',employments:'任职',abstract:'摘要',title:'题名',original_title:'原题名',orcid:'ORCID',doi:'DOI',issn:'ISSN',sources:'简介出处',country:'国家',location:'所在地',research_scope:'研究范围',website:'网站',serial_id:'所属刊物',source_id:'发布机构',version:'版本',id:'编号',target_id:'对象编号',institution_id:'机构编号',role:'角色',start_date:'开始日期',end_date:'结束日期',raw_name:'原始署名',status:'状态',target_type:'对象类型',url:'原文链接',publication_title:'刊物',volume:'卷',issue:'期',pages:'页码',published_on:'发表日期',language:'语种',relationships:'机构关系',institution_types:'机构类型',host_id:'主办机构',publisher_id:'出版机构',host_evidence:'主办依据',classification:'分类',kind:'类型',evidence:'依据',quote:'原文引句',human_status:'人工核对',machine:'机器来历',items:'关系条目'};
Object.assign(maintenanceTraceFields,{country_evidence:'国别依据',host_country_status:'主办国确认',international_status:'国际属性',international_evidence:'国际属性依据',catalogue_url:'目录网址',introduction_text:'简介文本',notes:'备注',type:'关系类型',byline_id:'署名编号',evidence_url:'依据网址',evidence_quote:'依据原句',verified:'人工核对',removed:'已移除'});
Object.assign(maintenanceTraceFields,{human_checked:'人工核对',record_id:'资料编号',person_id:'人物编号',origin_record_id:'原始署名资料编号',original_authors:'原始作者署名',original_target_id:'原关联对象编号',original_target_type:'原关联对象类型',selected_target_id:'所选对象编号',selected_target_type:'所选对象类型',selected_byline_id:'所选署名编号',position:'署名顺序',removed_at:'移除时间',raw_authors:'原始作者署名'});
Object.assign(maintenanceTraceFields,{byline:'署名',person:'人物',selected_institution_id:'所选机构编号',original_institution_id:'原机构编号',original_byline_id:'原署名编号',byline_snapshot_json:'署名引用快照',original_byline_json:'原始署名快照'});
const maintenanceRelationBookkeeping=new Set(['version','record_version','byline_version','manual_revision','created_at','updated_at','can_edit']);
function maintenanceStepStatus(step){return step.status==='pending'?'等待执行':step.result?.error?'执行遇到问题':step.status==='completed'?'已执行':step.status;}
function maintenanceTraceText(value){
  if(value===null||value===undefined||value==='')return '未填写';
  if(typeof value==='boolean')return value?'是':'否';
  if(typeof value!=='string')return String(value);
  const text=document.createElement('div');text.innerHTML=readRich(value);return text.textContent||'未填写';
}
function maintenanceTraceValue(value,depth=0,field='',historicalTarget=null){
  if(depth>7)return '<span>内容层级较深，请查看对象档案。</span>';
  if(typeof value==='string'&&['relationships','institution_types','byline_snapshot_json','original_byline_json'].includes(field)){try{const parsed=JSON.parse(value);if(parsed&&typeof parsed==='object')return maintenanceTraceValue(parsed,depth+1,field);}catch(failure){/* Preserve the actual unparsed historical value. */}}
  if(Array.isArray(value))return value.length?`<ul>${value.map((v,i)=>`<li data-key="value-${i}">${maintenanceTraceValue(v,depth+1,field)}</li>`).join('')}</ul>`:'<span>无条目</span>';
  if(value&&typeof value==='object'){
    if(Array.isArray(value.items)){
      const context=Object.fromEntries(Object.entries(value).filter(([key])=>key!=='items'&&!maintenanceRelationBookkeeping.has(key)));
      return maintenanceTraceValue(value.items,depth+1)+`${Object.keys(context).length?`<details class="trace-long"><summary>关系原始身份与引用</summary>${maintenanceTraceValue(context,depth+1)}</details>`:''}`;
    }
    const target=value.target||value.institution;
    const entries=Object.entries(value).filter(([k])=>!['target','institution','created_at','updated_at'].includes(k));
    return `${target?maintenanceObjectLink(target.type==='person'?'person':'source',target.id,target.name):''}<dl class="trace-values">${entries.map(([k,v])=>`<div data-key="field-${esc(k)}"><dt>${esc(maintenanceTraceFields[k]||k)}</dt><dd>${maintenanceTraceValue(v,depth+1,k,k==='institution_id'?value.institution:null)}</dd></div>`).join('')}</dl>`;
  }
  if(typeof value==='string'&&value&&['institution_id','serial_id','source_id','host_id','publisher_id'].includes(field))return value.split('|').map(raw=>{
    const id=raw.trim(),source=(state.sources||[]).find(item=>item.id===id);
    if(historicalTarget?.id===id&&historicalTarget.name)return `${maintenanceObjectLink('source',id,historicalTarget.name)} <span class="muted">历史记录名称 · 编号 ${esc(id)}</span>`;
    return `${maintenanceObjectLink('source',id,source?.name||id)} <span class="muted">${source?.name?'当前名称 · 编号 '+esc(id):'当前名称未读取'}；历史名称未记录。</span>`;
  }).join(' · ');
  const labels={person:'人物',institution:'机构',think_tank:'智库',journal:'期刊',serial:'其他出版物',record:'资料',part_of:'隶属',established_by:'共同设立',cooperates_with:'合作',funded_by:'资助',university:'大学',research_institute:'研究机构',faculty:'院系',confirmed:'已确认',pending:'待核对',unknown:'未知'};
  const text=['kind','type','target_type','institution_types','status','human_status'].includes(field)&&labels[value]?labels[value]:maintenanceTraceText(value);
  if(text.length>500)return `<p class="trace-value">${esc(text.slice(0,180))}…</p><details class="trace-long"><summary>展开完整内容（${text.length} 字符）</summary><span class="trace-value">${esc(text)}</span></details>`;
  return `<span class="trace-value">${esc(text)}</span>`;
}
function maintenanceTraceEvidence(job,step){
  const ids=new Set([step.arguments?.evidence_id,step.result?.evidence_id].filter(Boolean));
  return (job.evidence||[]).filter(e=>ids.has(e.id)||e.step_id===step.id);
}
function maintenanceTraceSource(job,evidence){
  if(evidence.method==='deepseek-search-json'){
    const source=job.steps.find(step=>step.id===evidence.step_id||step.result?.evidence_id===evidence.id);
    return maintenanceSearchLinks(source?.result?.results)||'<p class="muted">保存了搜索材料，未记录单项出处链接。</p>';
  }
  return `<p>${externalLink(evidence.url,evidence.url)}</p>`;
}
function maintenanceTraceChanged(field,change){
  if(field==='version')return false;
  if(['bylines','affiliations','employments'].includes(field)){
    // Preserve all recorded business fields, including basis, confirmation,
    // original identities and removal. Only revision bookkeeping is incidental.
    const substantive=value=>Array.isArray(value)?value.map(substantive):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).filter(key=>!maintenanceRelationBookkeeping.has(key)).sort().map(key=>[key,substantive(value[key])])):value;
    return JSON.stringify(substantive(change.before))!==JSON.stringify(substantive(change.after));
  }
  return JSON.stringify(change.before)!==JSON.stringify(change.after);
}
function maintenanceTraceDetail(job,step,selectedEvidence){
  if(!step)return `<div class="trace-empty"><h4>尚无执行步骤</h4><p>${job.status==='queued'?'任务正在等待后台处理。实际执行后会在这里出现步骤。':'此任务没有保存步骤记录。'}</p></div>`;
  const args=step.arguments||{},result=step.result||{},changes=Object.entries(result.changes||{}).filter(([field,change])=>maintenanceTraceChanged(field,change));
  const evidence=maintenanceTraceEvidence(job,step);
  return `<header data-key="identity"><p class="trace-step-meta">步骤 ${esc(step.position)} · ${esc(maintenanceStepStatus(step))}</p><h4>${esc(maintenanceTools[step.name]||step.name)}</h4><p class="muted">${dateTime(step.created_at)}${step.finished_at?' · 执行结束 '+dateTime(step.finished_at):''}</p></header>
    <section data-key="action" class="trace-section"><h5>当时的动作与结果</h5>${result.error?`<p class="form-error" role="status">${esc(result.error)}</p>`:''}${step.status==='pending'?'<p>此步等待执行，尚无执行结果。</p>':''}${args.query?`<p>查找：${esc(args.query)}</p>`:''}${args.url?`<p>${externalLink(args.url,'当时读取的网页')}</p>`:''}${args.field?`<p>读取字段：${esc(maintenanceTraceFields[args.field]||args.field)}</p>`:''}${result.reason||args.reason?`<p>${esc(result.reason||args.reason)}</p>`:''}${result.changed_target?`<p>${maintenanceObjectLink(...result.changed_target,result.object?.name||result.object?.title||'打开当前对象')} <span class="muted">当前档案${result.object?.version?'；当时保存为版本 '+esc(result.object.version):''}</span></p>`:''}${!result.changed_target&&!result.error&&step.status==='completed'?`<p>${step.name==='finish'?'此步记录处理结束；缺项以实际说明为准。':'此步已执行，未记录正式修改。'}</p>`:''}${result.results?maintenanceSearchLinks(result.results):''}</section>
    <section data-key="changes" class="trace-section"><h5>实际修改前后</h5>${changes.length?changes.map(([field,change])=>`<article class="trace-change" data-key="change-${esc(field)}"><h6>${esc(maintenanceTraceFields[field]||field)}</h6><div class="trace-diff"><div><strong>原值</strong>${maintenanceTraceValue(change.before,0,field)}</div><div><strong>新值</strong>${maintenanceTraceValue(change.after,0,field)}</div></div></article>`).join(''):'<p class="muted">此步没有记录字段或关系改动。</p>'}</section>
    <section data-key="evidence" class="trace-section"><h5>实际取得的材料 <span class="muted">${evidence.length} 份</span></h5>${args.quote?`<blockquote>${esc(args.quote)}</blockquote>`:''}${evidence.length?evidence.map(e=>`<details class="trace-evidence" data-key="evidence-${esc(e.id)}" data-evidence-id="${esc(e.id)}" ${selectedEvidence===e.id?'open':''}><summary>${e.method==='deepseek-search-json'?'搜索取得的材料':'网页取得的材料'} · ${dateTime(e.fetched_at)}</summary>${maintenanceTraceSource(job,e)}<p class="muted">材料编号 ${esc(e.id)} · ${esc(e.method)}</p><div class="trace-evidence-text" tabindex="0">${esc(e.text||'未保存材料正文。')}</div></details>`).join(''):'<p class="muted">此步没有显式关联已取得的材料。</p>'}</section>
    ${result.object&&!result.changed_target?`<details data-key="observation" class="trace-section"><summary>当时读取的档案</summary>${maintenanceTraceValue(result.object)}</details>`:''}`;
}
// Small, scoped DOM reconciliation. Keyed evidence/details and unchanged nodes
// retain native open state, scroll and focus. Forms are outside this surface.
function maintenancePatch(root,html){
  const focused=root.contains(document.activeElement)?document.activeElement:null;
  const positions=[root,...root.querySelectorAll('*')].filter(node=>node.scrollTop||node.scrollLeft).map(node=>[node,node.scrollTop,node.scrollLeft]);
  const template=document.createElement('template');template.innerHTML=html;
  function sync(parent,incoming){
    let cursor=parent.firstChild;
    for(const source of [...incoming.childNodes]){
      const key=source.nodeType===1?source.getAttribute('data-key'):null;
      let node=key?[...parent.children].find(e=>e.getAttribute('data-key')===key):cursor;
      if(!node||node.nodeType!==source.nodeType||(node.nodeType===1&&node.tagName!==source.tagName)){
        node=source.cloneNode(true);parent.insertBefore(node,cursor);
      }else{
        if(node!==cursor)parent.insertBefore(node,cursor);
        if(node.nodeType===3){if(node.data!==source.data)node.data=source.data;}
        else if(node.nodeType===1){
          if(source.matches('[data-maintenance-trace]')&&node._maintenanceTrace){
            const job=maintenanceTracePending.get(source.dataset.traceToken)?.job;maintenanceTracePending.delete(source.dataset.traceToken);
            if(job)maintenanceTraceUpdate(node,job);
            cursor=node.nextSibling;continue;
          }
          for(const attr of [...node.attributes])if(!['open','value'].includes(attr.name)&&!source.hasAttribute(attr.name))node.removeAttribute(attr.name);
          for(const attr of [...source.attributes])if(!['open','value'].includes(attr.name)&&node.getAttribute(attr.name)!==attr.value)node.setAttribute(attr.name,attr.value);
          sync(node,source);
        }
      }
      cursor=node.nextSibling;
    }
    while(cursor){const next=cursor.nextSibling;cursor.remove();cursor=next;}
  }
  sync(root,template.content);
  if(focused?.isConnected&&document.activeElement!==focused)focused.focus({preventScroll:true});
  for(const [node,top,left] of positions)if(node.isConnected){node.scrollTop=top;node.scrollLeft=left;}
}
function maintenanceTraceHtml(job){
  const token=crypto.randomUUID();maintenanceTracePending.set(token,{job,actor:state.me?.id,pageTurn:state.loadId});
  return `<div class="maintenance-trace" data-key="trace-${esc(job.id)}" data-maintenance-trace data-trace-token="${token}" data-trace-job="${esc(job.id)}"></div>`;
}
function maintenanceTraceUpdate(root,job){
  let model=root._maintenanceTrace;
  if(!model||model.job.id!==job.id){
    root.innerHTML='<div class="trace-summary" data-trace-summary></div><div class="trace-layout"><div class="trace-rail"><h4>实际步骤</h4><div class="trace-steps" data-trace-steps></div><details class="trace-material-index"><summary>按材料定位步骤</summary><div data-trace-materials></div></details></div><div class="trace-detail" data-trace-detail tabindex="-1"></div><svg class="trace-connector" aria-hidden="true"><path></path></svg></div>';
    model={job,step:job.steps?.[0]?.id||'',evidence:'',signature:''};root._maintenanceTrace=model;
    maintenanceTraceRoots.add(root);
    root.addEventListener('click',event=>{
      const button=event.target.closest('[data-trace-step],[data-trace-evidence]');if(!button)return;
      const old=model.step;
      if(button.dataset.traceEvidence){
        const e=model.job.evidence.find(item=>item.id===button.dataset.traceEvidence);
        const step=model.job.steps.find(item=>item.id===e?.step_id)||model.job.steps.find(item=>maintenanceTraceEvidence(model.job,item).some(x=>x.id===e?.id));
        if(!step)return;model.step=step.id;model.evidence=e.id;
      }else{model.step=button.dataset.traceStep;model.evidence='';}
      maintenanceTraceUpdate(root,model.job);
      if(old!==model.step)root.querySelector('[data-trace-detail]').scrollTop=0;
      if(model.evidence){const disclosure=[...root.querySelectorAll('[data-evidence-id]')].find(e=>e.dataset.evidenceId===model.evidence);if(disclosure){disclosure.open=true;disclosure.scrollIntoView({block:'nearest'});}}
      if(old!==model.step&&!matchMedia('(prefers-reduced-motion: reduce)').matches){const detail=root.querySelector('[data-trace-detail]');if(typeof detail.animate==='function')detail.animate([{backgroundColor:'#fff4d3'},{backgroundColor:'#ffffff'}],{duration:180,easing:'ease-out'});}
    });
    root.addEventListener('scroll',()=>maintenanceTraceConnect(root),true);
    if(typeof ResizeObserver==='function'){model.resize=new ResizeObserver(()=>maintenanceTraceConnect(root));model.resize.observe(root);}
  }
  model.job=job;
  if(!job.steps.some(s=>s.id===model.step))model.step=job.steps[0]?.id||'';
  const signature=JSON.stringify([job,model.step,model.evidence]);if(signature===model.signature)return;
  model.signature=signature;
  maintenancePatch(root.querySelector('[data-trace-summary]'),`<strong>${esc(maintenanceStatuses[job.status]||job.status)}</strong> · ${esc(job.title||job.target_id)}${job.reason?`<p>${esc(job.reason)}</p>`:''}${job.feedback?`<p>问题说明：${esc(job.feedback)}</p>`:''}<p class="muted">已记录 ${job.steps.length} 个实际步骤 · ${job.evidence.length} 份材料</p>`);
  maintenancePatch(root.querySelector('[data-trace-steps]'),job.steps.length?job.steps.map(step=>`<button type="button" class="trace-step" data-key="step-${esc(step.id)}" data-trace-step="${esc(step.id)}" aria-pressed="${step.id===model.step}"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 0v24"/><circle cx="12" cy="12" r="5"/></svg><span><strong>${esc(step.position)} · ${esc(maintenanceTools[step.name]||step.name)}</strong><span>${esc(maintenanceStepStatus(step))}</span></span></button>`).join(''):'<p class="muted">尚无步骤</p>');
  maintenancePatch(root.querySelector('[data-trace-materials]'),job.evidence.length?job.evidence.map((e,i)=>`<button type="button" class="trace-material" data-key="material-${esc(e.id)}" data-trace-evidence="${esc(e.id)}">材料 ${i+1} · ${esc(e.method==='deepseek-search-json'?'搜索结果':'网页内容')}</button>`).join(''):'<p class="muted">尚无材料</p>');
  maintenancePatch(root.querySelector('[data-trace-detail]'),maintenanceTraceDetail(job,job.steps.find(s=>s.id===model.step),model.evidence));
  requestAnimationFrame(()=>maintenanceTraceConnect(root));
}
function maintenanceTraceConnect(root){
  if(!root.isConnected)return;
  const layout=root.querySelector('.trace-layout'),svg=root.querySelector('.trace-connector'),selected=root.querySelector('[data-trace-step][aria-pressed="true"]'),detail=root.querySelector('[data-trace-detail]');
  if(!svg||!selected)return;
  const a=layout.getBoundingClientRect(),b=selected.getBoundingClientRect(),c=detail.getBoundingClientRect();
  if(![a.width,a.height,b.width,b.height,c.width,c.height].every(v=>Number.isFinite(v)&&v>0)){svg.querySelector('path').removeAttribute('d');return;}
  const x=b.right-a.left,y=Math.max(20,Math.min(a.height-20,b.top+b.height/2-a.top)),end=c.left-a.left;
  if(![x,y,end].every(Number.isFinite)){svg.querySelector('path').removeAttribute('d');return;}
  svg.setAttribute('viewBox',`0 0 ${a.width} ${a.height}`);svg.querySelector('path').setAttribute('d',`M ${x} ${y} H ${x+(end-x)/2} V 48 H ${end}`);
}
const maintenanceTraceObserver=new MutationObserver(()=>{
  for(const [token,pending] of maintenanceTracePending)if(pending.actor!==state.me?.id||pending.pageTurn!==state.loadId)maintenanceTracePending.delete(token);
  for(const root of maintenanceTraceRoots)if(!root.isConnected){root._maintenanceTrace?.resize?.disconnect();delete root._maintenanceTrace;maintenanceTraceRoots.delete(root);}
  document.querySelectorAll('[data-trace-token]').forEach(root=>{
    const job=maintenanceTracePending.get(root.dataset.traceToken)?.job;maintenanceTracePending.delete(root.dataset.traceToken);delete root.dataset.traceToken;
    if(job)maintenanceTraceUpdate(root,job);
  });
});
maintenanceTraceObserver.observe(document.documentElement,{childList:true,subtree:true});
