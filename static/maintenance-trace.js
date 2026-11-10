'use strict';
// One read-only surface for maintenance and object feedback. Callers supply a
// job; selection, evidence matching, readable values and DOM continuity live here.
const maintenanceTracePending=new Map();
const maintenanceTraceRoots=new Set();
const visualFlowHosts=new Set(),visualDiffHosts=new Set();
function visualFlowHtml(){return '<div class="actual-flow"><div class="row wrap actual-flow-tools"><strong>流程图</strong><button type="button" class="button" data-flow-command="in">放大</button><button type="button" class="button" data-flow-command="out">缩小</button><button type="button" class="button" data-flow-command="selected">定位所选节点</button><button type="button" class="button" data-flow-command="fit">显示全图</button><button type="button" class="button" data-flow-command="retry" hidden>重试流程图</button></div><p class="muted" data-flow-status role="status">正在读取流程图…</p><p class="muted actual-flow-legend" data-flow-legend></p><div class="actual-flow-slot" data-flow-slot aria-label="实际记录流程图"></div></div>';}
function visualFlowUpdate(host,snapshot,onSelect,onAction){
  let model=host._actualFlow;
  if(!model){
    model={actor:state.me?.id,page:state.loadId,snapshot,onSelect,instance:null,loading:false};host._actualFlow=model;visualFlowHosts.add(host);
    if(typeof ResizeObserver==='function'){model.resize=new ResizeObserver(()=>{if(host.getBoundingClientRect().width<=0)return;if(model.instance)model.instance.resize();else visualFlowMount(host);});model.resize.observe(host);}
    host.addEventListener('click',event=>{const command=event.target.closest('[data-flow-command]')?.dataset.flowCommand;if(!command)return;if(command==='retry'){model.instance?.dispose();model.instance=null;model.failed=false;host.querySelector('[data-flow-slot]').hidden=false;visualFlowMount(host);}else if(command==='in')model.instance?.zoomIn();else if(command==='out')model.instance?.zoomOut();else if(command==='selected')model.instance?.focusSelected();else model.instance?.fit();});
  }
  model.snapshot=snapshot;model.onSelect=onSelect;model.onAction=onAction;const legend=host.querySelector('[data-flow-legend]');if(legend.textContent!==(snapshot.legend||''))legend.textContent=snapshot.legend||'';
  const empty=!snapshot.nodes.length;host.querySelector('[data-flow-slot]').hidden=empty||!!model.failed;
  host.querySelectorAll('[data-flow-command]').forEach(button=>{button.disabled=empty;});
  if(empty){model.instance?.dispose();model.instance=null;host.querySelector('[data-flow-status]').textContent='尚无图节点；实际步骤出现后再显示流程图。';return;}
  if(model.instance)model.instance.update(snapshot);else visualFlowMount(host);
}
function visualFlowStatus(host,model,message){
  model.failed=/失败|未能|暂不可用/.test(message);host.querySelector('[data-flow-status]').textContent=message;
  host.querySelector('[data-flow-slot]').hidden=model.failed||!model.snapshot.nodes.length;
  host.querySelectorAll('[data-flow-command]').forEach(button=>{button.hidden=button.dataset.flowCommand==='retry'?!model.failed:model.failed;});
  if(model.failed){const text=host.closest('.handoff-lineage')?.querySelector('.handoff-track-details');if(text)text.open=true;}
}
function visualFlowCurrent(host,model){return host.isConnected&&host._actualFlow===model&&state.me?.id===model.actor&&state.loadId===model.page&&!document.hidden&&(!host.closest('.trace-graph,.handoff-graph')||host.closest('.trace-graph,.handoff-graph').open)&&model.snapshot.nodes.length>0;}
async function visualFlowMount(host){
  const model=host._actualFlow;if(!model||model.failed||model.loading||model.instance||!visualFlowCurrent(host,model)||host.getBoundingClientRect().width<=0||host.querySelector('[data-flow-slot]').getBoundingClientRect().height<=0)return;
  model.loading=true;
  try{
    model.instance=await window.visualLoader.mount('flow',host.querySelector('[data-flow-slot]'),{snapshot:model.snapshot,viewport:model.viewport,onSelect:id=>{if(visualFlowCurrent(host,model))model.onSelect(id);},onAction:(id,action)=>{if(visualFlowCurrent(host,model))model.onAction?.(id,action);},onStatus:message=>{if(visualFlowCurrent(host,model)){visualFlowStatus(host,model,message);}}},{isCurrent:()=>visualFlowCurrent(host,model)});
    if(model.instance){model.instance.update(model.snapshot);if(model.focusOnMount){model.instance.focusSelected();model.focusOnMount=false;}}
  }catch(error){if(visualFlowCurrent(host,model)){visualFlowStatus(host,model,'流程图未能加载，可继续查看文字记录。');}}
  finally{model.loading=false;}
}
function visualDiffMount(host){
  if(host._diffLoading||host._diff||!host.isConnected||!host.closest('details')?.open||document.hidden)return;
  const actor=state.me?.id,page=state.loadId,signature=host.dataset.diffBefore+'\0'+host.dataset.diffAfter;
  host._diffLoading=true;visualDiffHosts.add(host);
  window.visualLoader.mount('diff',host,{snapshot:{before:host.dataset.diffBefore,after:host.dataset.diffAfter}},{isCurrent:()=>state.me?.id===actor&&state.loadId===page&&host.isConnected&&signature===host.dataset.diffBefore+'\0'+host.dataset.diffAfter}).then(instance=>{host._diff=instance;}).catch(()=>{if(host.isConnected)host.textContent='差异视图未能加载；完整原值与新值仍可展开阅读。';}).finally(()=>{host._diffLoading=false;});
}
document.addEventListener('toggle',event=>{if(event.target.open)event.target.querySelectorAll('[data-trace-diff]').forEach(visualDiffMount);},true);
document.addEventListener('visibilitychange',()=>{
  for(const host of visualFlowHosts){const model=host._actualFlow;if(document.hidden){model.viewport=model.instance?.getViewport();model.instance?.dispose();model.instance=null;}else visualFlowMount(host);}
});
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
function maintenanceTraceValue(value,depth=0,field='',historicalTarget=null,technical=false){
  if(depth>7)return '<span>内容层级较深，请查看对象档案。</span>';
  if(typeof value==='string'&&['relationships','institution_types','byline_snapshot_json','original_byline_json'].includes(field)){try{const parsed=JSON.parse(value);if(parsed&&typeof parsed==='object')return maintenanceTraceValue(parsed,depth+1,field);}catch(failure){/* Preserve the actual unparsed historical value. */}}
  if(Array.isArray(value))return value.length?`<ul>${value.map((v,i)=>`<li data-key="value-${i}">${maintenanceTraceValue(v,depth+1,field,null,technical)}</li>`).join('')}</ul>`:'<span>'+({bylines:'无作者归属',affiliations:'无署名单位',employments:'无任职关系'}[field]||'无条目')+'</span>';
  if(value&&typeof value==='object'){
    if(Array.isArray(value.items)){
      const context=Object.fromEntries(Object.entries(value).filter(([key])=>key!=='items'));
      return maintenanceTraceValue(value.items,depth+1,field,null,technical)+`${Object.keys(context).length?`<details class="trace-long"><summary>关系原始身份与引用</summary>${maintenanceTraceValue(context,depth+1,field,null,true)}</details>`:''}`;
    }
    const target=value.target||value.institution;
    const all=Object.entries(value).filter(([key])=>!['target','institution'].includes(key));
    const relation=['bylines','affiliations','employments','relationships'].includes(field)||!!target;
    const incidental=key=>maintenanceRelationBookkeeping.has(key)||key==='id'||key.endsWith('_id')||key.endsWith('_json')||key.endsWith('_version')||['byline','person','original_target_type','selected_target_type','position','maintenance_job'].includes(key);
    const entries=all.filter(([key,item])=>technical||!relation||!incidental(key)&&item!==null&&item!==''&&!(key==='original_authors'&&item===value.raw_name));
    const extra=!technical&&relation?all.filter(([key])=>incidental(key)):[];
    return `${target?maintenanceObjectLink(target.type==='person'?'person':'source',target.id,target.name):''}<dl class="trace-values">${entries.map(([k,v])=>`<div data-key="field-${esc(k)}"><dt>${esc(maintenanceTraceFields[k]||k)}</dt><dd>${maintenanceTraceValue(!technical&&k==='evidence'&&typeof v==='string'?v.replace(/\nAI维护：[^\n]+$/,''):v,depth+1,k,k==='institution_id'?value.institution:null,technical)}</dd></div>`).join('')}</dl>${extra.length?`<details class="trace-long trace-technical"><summary>完整关系记录</summary>${maintenanceTraceValue(Object.fromEntries(all),depth+1,field,null,true)}</details>`:''}`;
  }
  if(typeof value==='string'&&value&&['institution_id','serial_id','source_id','host_id','publisher_id'].includes(field))return value.split('|').map(raw=>{
    const id=raw.trim(),source=(state.sources||[]).find(item=>item.id===id);
    if(historicalTarget?.id===id&&historicalTarget.name)return `${maintenanceObjectLink('source',id,historicalTarget.name)} <span class="muted">历史记录名称</span><details class="trace-long"><summary>对象编号</summary>${esc(id)}</details>`;
    return `${source?.name?maintenanceObjectLink('source',id,source.name):''} <span class="muted">${source?.name?'当前名称':'当前名称未读取'}；历史名称未记录。</span><details class="trace-long"><summary>对象编号</summary>${esc(id)}</details>`;
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
    const relationValue=value=>field==='affiliations'&&Array.isArray(value?.items)?Object.fromEntries(Object.entries(value).filter(([key])=>key!=='bylines')):value;
    return JSON.stringify(substantive(relationValue(change.before)))!==JSON.stringify(substantive(relationValue(change.after)));
  }
  return JSON.stringify(change.before)!==JSON.stringify(change.after);
}
function maintenanceTraceIdentityChange(field,change){
  const collect=value=>Array.isArray(value)?value.flatMap(collect):value&&typeof value==='object'?Object.entries(value).flatMap(([key,item])=>['target_id','institution_id','host_id','publisher_id'].includes(key)&&item?[key+':'+item]:key==='items'?collect(item):[]):[];
  const before=['serial_id','source_id','host_id','publisher_id'].includes(field)?[change.before].filter(Boolean):collect(change.before);
  const after=['serial_id','source_id','host_id','publisher_id'].includes(field)?[change.after].filter(Boolean):collect(change.after);
  return before.length&&after.length&&JSON.stringify(before)!==JSON.stringify(after)?'<p class="trace-identity-change">关联对象已更换 · 完整身份可展开核对</p>':'';
}
function maintenanceTraceDetail(job,step,selectedEvidence){
  if(!step)return `<div class="trace-empty"><h4>尚无执行步骤</h4><p>${job.status==='queued'?'任务正在等待后台处理。实际执行后会在这里出现步骤。':'此任务没有保存步骤记录。'}</p></div>`;
  const args=step.arguments||{},result=step.result||{},changes=Object.entries(result.changes||{}).filter(([field,change])=>maintenanceTraceChanged(field,change));
  const evidence=maintenanceTraceEvidence(job,step);
  return `<header data-key="identity"><p class="trace-step-meta">步骤 ${esc(step.position)} · ${esc(maintenanceStepStatus(step))}</p><h4>${esc(maintenanceTools[step.name]||step.name)}</h4><p class="muted">${dateTime(step.created_at)}${step.finished_at?' · 执行结束 '+dateTime(step.finished_at):''}</p></header>
    <section data-key="action" class="trace-section"><h5>当时的动作与结果</h5>${result.error?`<p class="form-error" role="status">${esc(result.error)}</p>`:''}${step.status==='pending'?'<p>此步等待执行，尚无执行结果。</p>':''}${args.query?`<p>查找：${esc(args.query)}</p>`:''}${args.url?`<p>${externalLink(args.url,'当时读取的网页')}</p>`:''}${args.field?`<p>读取字段：${esc(maintenanceTraceFields[args.field]||args.field)}</p>`:''}${result.reason||args.reason?`<p>${esc(result.reason||args.reason)}</p>`:''}${result.changed_target?`<p>${maintenanceObjectLink(...result.changed_target,result.object?.name||result.object?.title||'打开当前对象')} <span class="muted">当前档案${result.object?.version?'；当时保存为版本 '+esc(result.object.version):''}</span></p>`:''}${!result.changed_target&&!result.error&&step.status==='completed'?`<p>${step.name==='finish'?'此步记录处理结束；缺项以实际说明为准。':'此步已执行，未记录正式修改。'}</p>`:''}${result.results?maintenanceSearchLinks(result.results):''}</section>
    <section data-key="changes" class="trace-section"><h5>实际修改前后</h5>${changes.length?changes.map(([field,change])=>`<article class="trace-change" data-key="change-${esc(field)}"><h6>${esc(maintenanceTraceFields[field]||field)}</h6>${maintenanceTraceIdentityChange(field,change)}${typeof change.before==='string'&&typeof change.after==='string'&&Math.max(change.before.length,change.after.length)>500?`<details class="trace-long-diff" data-key="long-diff-${esc(field)}"><summary>逐行阅读文本差异</summary><div data-trace-diff data-diff-before="${esc(change.before)}" data-diff-after="${esc(change.after)}"></div></details>`:''}<div class="trace-diff"><div><strong>原值</strong>${maintenanceTraceValue(change.before,0,field)}</div><div><strong>新值</strong>${maintenanceTraceValue(change.after,0,field)}</div></div></article>`).join(''):'<p class="muted">此步没有记录字段或关系改动。</p>'}</section>
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
          if(source.matches('[data-trace-diff]')&&node._diff&&source.dataset.diffBefore===node.dataset.diffBefore&&source.dataset.diffAfter===node.dataset.diffAfter){cursor=node.nextSibling;continue;}
          if(source.matches('[data-trace-diff]')&&node._diff){node._diff.dispose();delete node._diff;}
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
    root.innerHTML='<button type="button" class="button trace-locate" data-trace-locate>查看修改与依据</button><div class="trace-summary" data-trace-summary></div><details class="trace-graph"><summary>步骤与材料关系图</summary>'+visualFlowHtml()+'</details><div class="trace-layout"><div class="trace-rail"><h4>实际步骤</h4><div class="trace-filters" role="group" aria-label="步骤筛选"><button type="button" class="button tiny" data-trace-filter="all">全部</button><button type="button" class="button tiny" data-trace-filter="changed">有改动</button><button type="button" class="button tiny" data-trace-filter="error">执行问题</button></div><p data-trace-filter-status role="status"></p><div class="trace-steps" data-trace-steps></div><details class="trace-material-index"><summary>按材料定位步骤</summary><div data-trace-materials></div></details><div data-trace-task-info></div></div><div class="trace-detail" data-trace-detail tabindex="-1"></div><svg class="trace-connector" aria-hidden="true"><path></path></svg></div>';
    model={job,step:job.steps?.[0]?.id||'',evidence:'',filter:'all',signature:''};root._maintenanceTrace=model;
    maintenanceTraceRoots.add(root);
    root.addEventListener('click',event=>{
      const filter=event.target.closest('[data-trace-filter]');if(filter){model.filter=filter.dataset.traceFilter;maintenanceTraceUpdate(root,model.job);return;}
      if(event.target.closest('[data-trace-locate]')){const detail=root.querySelector('[data-trace-detail]');detail.scrollIntoView({block:'start'});window.scrollBy(0,detail.getBoundingClientRect().top-76);detail.focus({preventScroll:true});return;}
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
  const listed=!!root.closest('.maintenance-selected')&&[...root.closest('.maintenance-agent').querySelectorAll('[data-maintenance-select]')].some(button=>button.dataset.maintenanceSelect===job.id);
  const signature=JSON.stringify([job,model.step,model.evidence,model.filter,listed]);if(signature===model.signature)return;
  model.signature=signature;
  maintenancePatch(root.querySelector('[data-trace-summary]'),`${listed?'':`<strong>${esc(maintenanceStatuses[job.status]||job.status)}</strong> · ${esc(job.title||job.target_id)}${job.reason?`<p>${esc(job.reason)}</p>`:''}`}${job.feedback?`<p>问题说明：${esc(job.feedback)}</p>`:''}<p class="muted">${job.steps.length} 个实际步骤 · ${job.evidence.length} 份材料</p>`);
  maintenancePatch(root.querySelector('[data-trace-task-info]'),`<details class="trace-task-info"><summary>任务时间与状态</summary><p>${esc(maintenanceStatuses[job.status]||job.status)} · ${dateTime(job.created_at)}</p>${job.last_step?`<p>末步：${esc(maintenanceTools[job.last_step.name]||job.last_step.name)}</p>`:''}</details>`);
  const visible=job.steps.filter(step=>model.filter==='all'||model.filter==='error'?(model.filter==='all'||!!step.result?.error||step.status==='failed'):Object.entries(step.result?.changes||{}).some(([field,change])=>maintenanceTraceChanged(field,change)));
  root.querySelectorAll('[data-trace-filter]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.traceFilter===model.filter)));
  root.querySelector('[data-trace-filter-status]').textContent=visible.length+' / '+job.steps.length+' 步'+(visible.some(step=>step.id===model.step)?'':' · 当前步骤在筛选外');
  root.querySelector('[data-trace-locate]').title='步骤 '+(job.steps.find(step=>step.id===model.step)?.position||'')+' · '+(maintenanceTools[job.steps.find(step=>step.id===model.step)?.name]||'');
  maintenancePatch(root.querySelector('[data-trace-steps]'),visible.length?visible.map(step=>`<button type="button" class="trace-step" data-key="step-${esc(step.id)}" data-trace-step="${esc(step.id)}" aria-pressed="${step.id===model.step}"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 0v24"/><circle cx="12" cy="12" r="5"/></svg><span><strong>${esc(step.position)} · ${esc(maintenanceTools[step.name]||step.name)}</strong><span>${esc(maintenanceStepStatus(step))}</span></span></button>`).join(''):'<p class="muted">尚无步骤</p>');
  maintenancePatch(root.querySelector('[data-trace-materials]'),job.evidence.length?job.evidence.map((e,i)=>`<button type="button" class="trace-material" data-key="material-${esc(e.id)}" data-trace-evidence="${esc(e.id)}">材料 ${i+1} · ${esc(e.method==='deepseek-search-json'?'搜索结果':'网页内容')}</button>`).join(''):'<p class="muted">尚无材料</p>');
  maintenancePatch(root.querySelector('[data-trace-detail]'),maintenanceTraceDetail(job,job.steps.find(s=>s.id===model.step),model.evidence));
  const nodes=job.steps.map(step=>({id:'step:'+step.id,label:`${step.position} · ${maintenanceTools[step.name]||step.name}\n${maintenanceStepStatus(step)}`}));
  const edges=job.steps.slice(1).map((step,i)=>({id:'order:'+step.id,source:'step:'+job.steps[i].id,target:'step:'+step.id,label:'顺序',description:'已记录步骤顺序'}));
  for(const [index,evidence] of job.evidence.entries()){nodes.push({id:'evidence:'+evidence.id,label:'材料 '+(index+1)+'\n'+(evidence.method==='deepseek-search-json'?'搜索结果':'网页内容')});for(const step of job.steps)if(maintenanceTraceEvidence(job,step).some(item=>item.id===evidence.id))edges.push({id:step.id+':'+evidence.id,source:'step:'+step.id,target:'evidence:'+evidence.id,label:'材料',description:evidence.step_id===step.id?'实际取得的材料':'显式材料引用'});}
  visualFlowUpdate(root.querySelector('.actual-flow'),{nodes,edges,legend:'',selected:['step:'+model.step,...(model.evidence?['evidence:'+model.evidence]:[])]},id=>{const prefix=id.startsWith('evidence:')?'evidence':'step',value=id.slice(prefix.length+1),button=[...root.querySelectorAll(prefix==='step'?'[data-trace-step]':'[data-trace-evidence]')].find(button=>button.dataset[prefix==='step'?'traceStep':'traceEvidence']===value);button?.click();});
  root.querySelectorAll('[data-trace-diff]').forEach(visualDiffMount);
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
  for(const host of visualFlowHosts)if(!host.isConnected||state.me?.id!==host._actualFlow.actor||state.loadId!==host._actualFlow.page){host._actualFlow.instance?.dispose();host._actualFlow.resize?.disconnect();delete host._actualFlow;visualFlowHosts.delete(host);}
  for(const host of visualDiffHosts)if(!host.isConnected){host._diff?.dispose();visualDiffHosts.delete(host);}
  for(const [token,pending] of maintenanceTracePending)if(pending.actor!==state.me?.id||pending.pageTurn!==state.loadId)maintenanceTracePending.delete(token);
  for(const root of maintenanceTraceRoots)if(!root.isConnected){root._maintenanceTrace?.resize?.disconnect();delete root._maintenanceTrace;maintenanceTraceRoots.delete(root);}
  document.querySelectorAll('[data-trace-token]').forEach(root=>{
    const job=maintenanceTracePending.get(root.dataset.traceToken)?.job;maintenanceTracePending.delete(root.dataset.traceToken);delete root.dataset.traceToken;
    if(job)maintenanceTraceUpdate(root,job);
  });
});
maintenanceTraceObserver.observe(document.documentElement,{childList:true,subtree:true});

document.addEventListener('toggle',event=>{
  if(!event.target.matches('.trace-graph,.handoff-graph'))return;
  const host=event.target.querySelector('.actual-flow'),model=host?._actualFlow;if(!model)return;
  if(event.target.open)visualFlowMount(host);else{model.viewport=model.instance?.getViewport();model.instance?.dispose();model.instance=null;}
},true);
