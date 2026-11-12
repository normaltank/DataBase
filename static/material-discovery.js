'use strict';

// Presentation state is deliberately absent from recordQuery and frozen queries.
const materialDiscovery={account:null,open:!matchMedia('(max-width:1199px)').matches,view:'europe',role:'published',geometry:null,focus:null,lens:false,scene:'country',yearsOpen:false,multiCountry:false};
const materialDateNames={published:'发表时间',collected:'首次收录',updated:'最近修订'};
function materialDiscoveryHTML(){
  return '<details class="material-discovery"><summary>国别地球与时间探索</summary><div data-material-distribution></div></details>';
}
function materialViewCurrent(panel,account,load,hash){
  return panel.isConnected&&panel.open&&!document.hidden&&state.me?.id===account&&panel._page===state.page;
}
function materialCurrent(panel,epoch,account,load,hash){
  return materialViewCurrent(panel,account,load,hash)&&panel._materialEpoch===epoch&&location.hash===hash;
}
async function materialLoad(panel){
  const epoch=(panel._materialEpoch||0)+1;panel._materialEpoch=epoch;
  const account=state.me?.id,load=state.loadId,hash=location.hash,body=panel.querySelector('[data-material-distribution]');
  panel._materialLoading=true;panel.setAttribute('aria-busy','true');
  // Selection is URL-owned feedback; it need not wait for distribution HTTP.
  if(panel._materialData)materialSyncGlobeSelection(panel);
  const inputs=panel.querySelector('[data-material-from]');
  if(inputs)panel._timeDraft={from:inputs.value,to:panel.querySelector('[data-material-to]').value};
  if(!panel._materialData){materialDispose(panel);body.innerHTML='<p role="status">正在读取当前查询的分布…</p>';}
  materialPanels.add(panel);
  const query=recordQuery();query.delete('page');query.delete('size');
  query.set('visual_window','1');
  try{
    const session=await api('/api/session');
    if(session.user?.id!==account)throw Object.assign(new Error('账号已切换，请重新登录。'),{status:401});
    if(!materialCurrent(panel,epoch,account,load,hash))return;
    const [data,geometry]=await Promise.all([api('/api/material-discovery?'+query),materialDiscovery.geometry||api(clientAsset('/static/geo/material-world-110m.json'))]);
    if(!materialCurrent(panel,epoch,account,load,hash))return;
    const latestSession=await api('/api/session');
    if(latestSession.user?.id!==account)throw Object.assign(new Error('账号已切换，请重新登录。'),{status:401});
    if(!materialCurrent(panel,epoch,account,load,hash))return;
    materialDiscovery.geometry=geometry;
    panel._materialData=data;
    // Query selection can change even when the distribution counts do not.
    // Patch native controls every time; module-owned canvases stay in place.
    // Clear stale errors before rendering restores the current selection status.
    if(panel._materialStale)for(const target of panel.querySelectorAll('[data-material-time-status],[data-material-globe-status]'))target.textContent='';
    panel._materialStale=false;
    materialRender(panel);
  }catch(error){
    if(!materialCurrent(panel,epoch,account,load,hash))return;
    if(panel._materialData&&![401,403,404].includes(error.status)){panel._materialStale=true;for(const target of panel.querySelectorAll('[data-material-time-status],[data-material-globe-status]'))target.textContent='读取失败，保留上次分布与输入。可重试：'+error.message;}
    else {materialDispose(panel);panel._materialData=null;panel._globeView=null;panel._timeView=null;body.innerHTML='<p role="alert">无法读取地图与时间分布：'+esc(error.message)+'</p><button type="button" class="button" data-material-retry>重新读取分布</button>';}
  }finally{if(panel._materialEpoch===epoch){panel._materialLoading=false;panel.removeAttribute('aria-busy');}}
}
function materialSyncGlobeSelection(panel){
  const selected=(recordQuery().get('country')||'').split('|').filter(Boolean).map(countryKey);
  const scope=panel._materialData.country_context||panel._materialData;
  panel._globe?.update({countries:scope.countries,selected});
  for(const button of panel.querySelectorAll('.material-country-list [data-material-country]'))button.setAttribute('aria-pressed',String(selected.includes(button.dataset.materialCountry)));
  const clear=panel.querySelector('[data-material-clear=country]');if(clear)clear.disabled=!selected.length;
}
function materialRender(panel){
  const data=panel._materialData,geometry=materialDiscovery.geometry;if(!data||!geometry)return;
  const flat=panel._flat===true;
  const p=recordQuery(),selected=new Set((p.get('country')||'').split('|').filter(Boolean).map(countryKey));
  const countryScope=data.country_context||{total:data.total,countries:data.countries};
  const countries=[...countryScope.countries],counts=new Map(countries.map(item=>[item.value,item.count]));
  const mapped=new Set(geometry.features.filter(f=>f.country).map(f=>f.country));
  for(const code of selected)if(!counts.has(code))countries.push({value:code,label:countryLabel(code),count:0});
  const maximum=Math.max(1,...countryScope.countries.map(item=>item.count)),low=Math.ceil(maximum/3),high=Math.ceil(2*maximum/3);
  const tone=count=>!count?'zero':count<=low?'low':count<=high?'middle':'high';
  const label=item=>item.value==='__unknown__'?'国别未知':item.label;
  const paths=geometry.features.map(feature=>{
    const count=counts.get(feature.country)||0,chosen=selected.has(feature.country);
    const inView=materialDiscovery.view==='world'||feature.bounds.some(([left,top,right,bottom])=>left<615&&right>385&&top<163&&bottom>38);
    return '<path d="'+feature.path+'" class="material-land material-count-'+tone(count)+(chosen?' material-land-selected':'')+'"'+(feature.country?' role="button" tabindex="'+(count||chosen?'0':'-1')+'" data-material-country="'+esc(feature.country)+'" aria-pressed="'+chosen+'" aria-label="'+esc(feature.name)+'：'+count+' 条，筛选研究对象国"':' aria-hidden="true"')+'><title>'+esc(feature.name)+' · '+count+' 条</title></path>';
  }).join('');
  const date=(data.time_context?.dates||data.dates)[materialDiscovery.role],hasTime=Boolean(p.get('from')||p.get('to')||p.get('date_unknown'));
  const yearMax=Math.max(1,...date.years.map(item=>item.count));
  const legend=[['zero','0 条'],['low','1–'+low+' 条'],...(high>low?[['middle',(low+1)+'–'+high+' 条']]:[]),...(maximum>high?[['high',(high+1)+'–'+maximum+' 条']]:[])];
  const retainedInputs=Boolean(panel.querySelector('[data-material-from]'));
  const markup=
    '<p class="material-scope" role="status">匹配 <strong>'+data.total+' 条</strong></p>'
    +'<div class="material-controls material-scene-controls" role="group" aria-label="资料探索视图"><button type="button" class="button tiny" data-material-scene="country" aria-pressed="'+(materialDiscovery.scene==='country')+'">国别地球</button><button type="button" class="button tiny" data-material-scene="time" aria-pressed="'+(materialDiscovery.scene==='time')+'">时间探索</button><button type="button" class="button tiny" data-material-retry>刷新分布</button></div>'
    +'<section data-material-country-scene '+(materialDiscovery.scene!=='country'?'hidden':'')+' aria-label="研究对象国分布"><div class="material-heading"><h2 class="sr-only">研究对象国</h2><div class="material-controls" role="group" aria-label="地图视角"><button type="button" class="button tiny" data-material-view="europe" aria-pressed="'+(materialDiscovery.view==='europe')+'">欧洲</button><button type="button" class="button tiny" data-material-view="world" aria-pressed="'+(materialDiscovery.view==='world')+'">全世界</button></div></div>'
    +'<details class="material-context"><summary>统计口径 · '+countryScope.total+' 条</summary><p>国别分布保留其他条件、排除对象国条件。多国资料分别计数。</p></details>'
    +'<div class="material-geography"><div class="material-stage"><div class="material-globe" '+(flat?'hidden':'')+' data-material-globe></div><p data-material-globe-status role="status">正在加载地球…</p><div class="material-controls"><button type="button" class="button tiny" data-material-globe-retry hidden>重试地球</button><button type="button" class="button tiny" data-material-globe-zoom="1" '+(flat?'hidden':'')+'>放大地球</button><button type="button" class="button tiny" data-material-globe-zoom="-1" '+(flat?'hidden':'')+'>缩小地球</button><button type="button" class="button tiny" data-material-flat aria-pressed="'+flat+'">平面地图</button></div>'
    +'<p class="material-globe-help" '+(flat?'hidden':'')+' data-material-globe-help>聚焦地球后：方向键旋转，+ / − 缩放，Home 复位。也可使用国别文字筛选。</p>'
    +'<p class="material-map-hint" '+(!flat?'hidden':'')+' data-material-map-hint aria-live="polite">点击国界或下方国别按钮筛选资料</p>'
    +'<svg class="material-map" '+(!flat?'hidden':'')+' viewBox="'+(materialDiscovery.view==='europe'?'385 38 230 125':geometry.viewBox)+'" role="group" aria-label="'+(materialDiscovery.view==='europe'?'欧洲':'全世界')+'研究对象国地图">'+paths+'</svg>'
    +'<details class="material-map-footer"><summary>图例与底图依据</summary><div class="material-legend" aria-label="库内资料数量图例">'+legend.map(([value,text])=>'<span><i class="material-count-'+value+'"></i>'+text+'</span>').join('')+'</div><span>底图：<a href="https://www.naturalearthdata.com/about/terms-of-use/" target="_blank" rel="noopener noreferrer">Natural Earth · 公共领域</a></span></details>'
    +'</div><div class="material-country-column"><div class="material-heading"><h3 class="sr-only">国别列表</h3><label class="material-multiselect"><input type="checkbox" data-material-country-multi '+(materialDiscovery.multiCountry?'checked':'')+'>多选国家</label><button type="button" class="button tiny" data-material-clear="country" '+(!selected.size?'disabled':'')+'>清除研究对象国条件</button></div>'
    +'<div class="material-country-list" role="group" aria-label="国别文字筛选">'+(countries.length?countries.map(item=>'<button type="button" class="button tiny" data-material-country="'+esc(item.value)+'" aria-pressed="'+selected.has(item.value)+'">'+esc(label(item))+' <strong>'+item.count+'</strong>'+(!mapped.has(item.value)?'<span class="material-unmapped"> · 无地图</span>':'')+'</button>').join(''):'<p>当前查询没有国别分布。可清除筛选后重新查找。</p>')+'</div></div></div></section>'
    +'<section class="material-time" '+(materialDiscovery.scene!=='time'?'hidden':'')+' aria-label="时间分布"><div class="material-heading"><h2>时间分布</h2><label>浏览口径 <select data-material-role aria-label="分布时间口径">'+Object.entries(materialDateNames).map(([value,text])=>'<option value="'+value+'" '+(materialDiscovery.role===value?'selected':'')+'>'+text+'</option>').join('')+'</select></label><button type="button" class="button tiny" data-material-clear="time" '+(!hasTime?'disabled':'')+'>清除时间条件</button></div>'
    +'<details class="material-precision"><summary>日期精度 · 未知 '+date.unknown+' 条</summary><p>'+materialDateNames[materialDiscovery.role]+'：仅年份 '+date.precision.year+' 条，精确到月 '+date.precision.month+' 条，精确到日 '+date.precision.day+' 条；未知 '+date.unknown+' 条。</p></details>'
    +'<p>年份概览 · '+(data.time_context?.total??data.total)+' 条</p>'
    +'<div class="material-time-range"><label>起始年 <input type="number" min="1" max="9999" step="1" data-material-from aria-label="起始年" value="'+esc((p.get('from')||'').slice(0,4))+'"></label><label>结束年 <input type="number" min="1" max="9999" step="1" data-material-to aria-label="结束年" value="'+esc((p.get('to')||'').slice(0,4))+'"></label><button type="button" class="button tiny" data-material-apply>应用时间范围</button><button type="button" class="button tiny" data-material-lens aria-pressed="'+materialDiscovery.lens+'">'+(materialDiscovery.lens?'关闭时间透镜':'打开时间透镜')+'</button><button type="button" class="button tiny" data-material-time-retry hidden>重试时间图</button></div><p data-material-range-status role="status"></p>'
    +'<button type="button" class="button tiny" data-material-camera-reset '+(!materialDiscovery.lens?'hidden':'')+'>重置透镜视角</button><div data-material-timeline></div><p data-material-time-status role="status">正在加载年份概览…</p>'
    +(data.timeline_window?'<p class="material-window-scope">当前查询窗口：已加载 '+data.timeline_window.loaded+' / '+data.timeline_window.total+' 条'+(data.timeline_window.has_more?'，还有更多资料，请缩小查询。':'')+'</p><details class="material-window"><summary>资料文字窗口（'+data.timeline_window.loaded+' 条，含未知日期）</summary><div class="material-window-list">'+data.timeline_window.items.map(item=>'<button type="button" class="button tiny" data-material-record="'+esc(item.id)+'">'+esc(item.title)+' · '+esc(item.date||'日期未知')+' · '+esc(item.kind)+'</button>').join('')+'</div></details>':'')
    +'<details class="material-native-years" '+(materialDiscovery.yearsOpen?'open':'')+'><summary>按单年选择（文字入口）</summary><div class="material-years" role="group" aria-label="年份筛选">'+date.years.map(item=>{
      const active=(p.get('date_field')||'published')===materialDiscovery.role&&p.get('from')===item.year+'-01-01'&&p.get('to')===item.year+'-12-31';
      return '<button class="material-year" type="button" data-material-year="'+item.year+'" aria-pressed="'+active+'" aria-label="'+item.year+'年，'+item.count+'条，按'+materialDateNames[materialDiscovery.role]+'筛选"><span>'+item.year+'年</span><svg class="material-year-track" viewBox="0 0 100 12" preserveAspectRatio="none" aria-hidden="true"><rect width="'+Math.max(1,100*item.count/yearMax)+'" height="12"></rect></svg><strong>'+item.count+' 条</strong></button>';
    }).join('')+'</div></details><button type="button" class="button tiny" data-material-year="unknown" aria-pressed="'+((p.get('date_field')||'published')===materialDiscovery.role&&p.get('date_unknown')==='1')+'">'+materialDateNames[materialDiscovery.role]+'未知 · '+date.unknown+' 条</button>'
    +(!data.total?'<p>当前查询没有资料，可清除国别或时间条件，或调整上方筛选。</p>':'')+'</section>';
  materialPatch(panel.querySelector('[data-material-distribution]'),markup);
  if(panel._globe)panel._globe.update({countries:countryScope.countries,selected:[...selected]});
  else if(materialDiscovery.scene==='country'&&!flat)materialMountGlobe(panel,countryScope,selected);
  if(panel._timeline)panel._timeline.update(materialTimeSnapshot(panel));
  else if(materialDiscovery.scene==='time')materialMountTimeline(panel);
  panel._materialSuspended=false;
  if(!retainedInputs&&panel._timeDraft){panel.querySelector('[data-material-from]').value=panel._timeDraft.from;panel.querySelector('[data-material-to]').value=panel._timeDraft.to;}
  if(materialDiscovery.focus){panel.querySelector(materialDiscovery.focus)?.focus({preventScroll:true});materialDiscovery.focus=null;}
}
// Patch the native representation without detaching focused inputs, disclosures or
// module-owned slots. Stable country/year/record identities survive insertions.
function materialPatch(body,markup){
  const template=document.createElement('template');template.innerHTML=markup;
  const key=node=>node.nodeType===1?['data-material-country','data-material-year','data-material-record','data-material-scene'].find(attr=>node.hasAttribute(attr)):null;
  const same=(a,b)=>a.nodeType===b.nodeType&&(a.nodeType!==1||a.tagName===b.tagName&&key(a)===key(b)&&(!key(a)||a.getAttribute(key(a))===b.getAttribute(key(b))));
  function patch(target,source){
    const wanted=[...source.childNodes];
    wanted.forEach((next,index)=>{
      let node=target.childNodes[index];
      if(!node||!same(node,next)){
        const match=[...target.childNodes].slice(index+1).find(candidate=>same(candidate,next));
        if(match){target.insertBefore(match,node||null);node=match;}
        else{node=next.cloneNode(true);target.insertBefore(node,target.childNodes[index]||null);return;}
      }
      if(node.nodeType!==1){if(node.nodeValue!==next.nodeValue)node.nodeValue=next.nodeValue;return;}
      if(node.matches('[data-material-globe],[data-material-timeline],[data-material-range-status],[data-material-time-status],[data-material-globe-status]'))return;
      for(const attr of [...node.attributes])if(!next.hasAttribute(attr.name)&&!(attr.name==='open'&&node.tagName==='DETAILS'))node.removeAttribute(attr.name);
      for(const attr of next.attributes)if(!(node.tagName==='DETAILS'&&attr.name==='open')&&!(node.tagName==='INPUT'&&attr.name==='value')&&node.getAttribute(attr.name)!==attr.value)node.setAttribute(attr.name,attr.value);
      patch(node,next);
    });
    while(target.childNodes.length>wanted.length)target.lastChild.remove();
  }
  patch(body,template.content);
}
function materialResume(panel){
  if(materialDiscovery.scene==='time')materialMountTimeline(panel);
  else if(panel.querySelector('[data-material-flat]').getAttribute('aria-pressed')!=='true')materialMountGlobe(panel,panel._materialData.country_context||panel._materialData,new Set((recordQuery().get('country')||'').split('|').filter(Boolean).map(countryKey)));
}
function materialSelectCountry(value){
  materialApply(query=>{
    if(!materialDiscovery.multiCountry){query.set('country',value);return;}
    const chosen=new Set((query.get('country')||'').split('|').filter(Boolean).map(countryKey));
    chosen.has(value)?chosen.delete(value):chosen.add(value);
    chosen.size?query.set('country',[...chosen].join('|')):query.delete('country');
  });
}
function materialApply(change){
  const query=recordQuery();query.delete('saved_search');query.delete('page');query.delete('size');
  change(query);go(state.page,query);
}
document.addEventListener('library:rendered',event=>{
  const root=event.detail.root;if(!root||root.querySelector('.material-discovery'))return;
  if(materialDiscovery.account!==state.me?.id){Object.assign(materialDiscovery,{account:state.me?.id,open:!matchMedia('(max-width:1199px)').matches,view:'europe',role:recordQuery().get('date_field')||'published',focus:null,scene:'country',lens:false,yearsOpen:false});}
  const work=document.createElement('div');work.className='material-workspace';const results=document.createElement('div');results.className='library-results-area';
  root.querySelector('.results-head').before(work);work.insertAdjacentHTML('afterbegin',materialDiscoveryHTML());work.append(results);
  for(const selector of ['.results-head','.library-selection','.library-results-workspace','.pagination']){const item=root.querySelector(selector);if(item)results.append(item);}
  materialDiscovery.role=recordQuery().get('date_field')||'published';
  const panel=root.querySelector('.material-discovery');panel._page=state.page;
  panel.addEventListener('toggle',event=>{if(event.target.matches('.material-native-years'))materialDiscovery.yearsOpen=event.target.open;},true);
  panel.addEventListener('toggle',()=>{if(!panel.isConnected)return;materialDiscovery.open=panel.open;if(panel.open)materialLoad(panel);else {panel._materialEpoch=(panel._materialEpoch||0)+1;materialDispose(panel);}});
  if(materialDiscovery.open)panel.open=true;
});
document.addEventListener('click',event=>{
  if(event.target.closest('[data-material-return]')){libraryCloseReader();const panel=document.querySelector('.material-discovery');panel.open=true;panel.querySelector('[data-material-scene][aria-pressed="true"]')?.focus({preventScroll:true});return;}
  const panel=event.target.closest('.material-discovery');if(!panel)return;
  const button=event.target.closest('[data-material-country],[data-material-year],[data-material-view],[data-material-clear],[data-material-retry],[data-material-globe-retry],[data-material-flat],[data-material-apply],[data-material-lens],[data-material-time-retry],[data-material-record],[data-material-scene],[data-material-camera-reset],[data-material-globe-zoom]');if(!button)return;
  if(button.hasAttribute('data-material-scene')){
    materialDiscovery.scene=button.dataset.materialScene;
    panel.querySelector('[data-material-country-scene]').hidden=materialDiscovery.scene!=='country';panel.querySelector('.material-time').hidden=materialDiscovery.scene!=='time';
    for(const item of panel.querySelectorAll('[data-material-scene]'))item.setAttribute('aria-pressed',String(item===button));
    if(materialDiscovery.scene==='time'){materialDisposeGlobe(panel);materialMountTimeline(panel);}
    else {materialDisposeTimeline(panel);if(!panel._flat)materialMountGlobe(panel,panel._materialData.country_context||panel._materialData,new Set((recordQuery().get('country')||'').split('|').filter(Boolean).map(countryKey)));}
  }
  else if(button.hasAttribute('data-material-record')){libraryOpenReader(button.dataset.materialRecord,button);}
  else if(button.hasAttribute('data-material-lens')){materialDiscovery.lens=!materialDiscovery.lens;button.setAttribute('aria-pressed',String(materialDiscovery.lens));button.textContent=materialDiscovery.lens?'关闭时间透镜':'打开时间透镜';panel.querySelector('[data-material-camera-reset]').hidden=!materialDiscovery.lens;panel._timeline?.update(materialTimeSnapshot(panel));}
  else if(button.hasAttribute('data-material-camera-reset'))panel._timeline?.reset();
  else if(button.hasAttribute('data-material-time-retry'))materialMountTimeline(panel);
  else if(button.hasAttribute('data-material-apply'))materialApplyRange(panel);
  else if(button.hasAttribute('data-material-globe-retry')){materialDisposeGlobe(panel);materialMountGlobe(panel,panel._materialData.country_context||panel._materialData,new Set((recordQuery().get('country')||'').split('|').filter(Boolean).map(countryKey)));}
  else if(button.hasAttribute('data-material-flat')){const flat=panel.querySelector('.material-map');flat.toggleAttribute('hidden');const shown=!flat.hasAttribute('hidden');panel._flat=shown;panel.querySelector('[data-material-globe]').hidden=shown;button.setAttribute('aria-pressed',String(shown));panel.querySelector('[data-material-map-hint]').hidden=!shown;for(const control of panel.querySelectorAll('[data-material-globe-zoom],[data-material-globe-help]'))control.hidden=shown;if(shown)materialDisposeGlobe(panel);else materialMountGlobe(panel,panel._materialData.country_context||panel._materialData,new Set((recordQuery().get('country')||'').split('|').filter(Boolean).map(countryKey)));}
  else if(button.hasAttribute('data-material-country')){materialDiscovery.focus='.material-country-list [aria-pressed="true"]';materialSelectCountry(button.dataset.materialCountry);}
  else if(button.hasAttribute('data-material-globe-zoom'))panel._globe?.zoom(Number(button.dataset.materialGlobeZoom));
  else if(button.hasAttribute('data-material-view')){materialDiscovery.view=button.dataset.materialView;panel._globe?.reset(materialDiscovery.view);panel.querySelector('.material-map').setAttribute('viewBox',materialDiscovery.view==='europe'?'385 38 230 125':materialDiscovery.geometry.viewBox);panel.querySelector('[data-material-view="'+materialDiscovery.view+'"]').focus({preventScroll:true});}
  else if(button.hasAttribute('data-material-retry'))materialLoad(panel);
  else if(button.hasAttribute('data-material-clear')){materialDiscovery.focus='[data-material-role]';materialApply(query=>{for(const key of button.dataset.materialClear==='country'?['country']:['from','to','date_unknown','date_field'])query.delete(key);});}
  else if(button.hasAttribute('data-material-year')){materialDiscovery.focus='[data-material-year][aria-pressed="true"]';materialApply(query=>{query.delete('from');query.delete('to');query.delete('date_unknown');query.set('date_field',materialDiscovery.role);if(button.dataset.materialYear==='unknown')query.set('date_unknown','1');else{query.set('from',button.dataset.materialYear+'-01-01');query.set('to',button.dataset.materialYear+'-12-31');}});}
});
document.addEventListener('change',event=>{if(event.target.matches('[data-material-country-multi]')){materialDiscovery.multiCountry=event.target.checked;return;}if(event.target.matches('[data-material-role]')){materialDiscovery.role=event.target.value;materialDiscovery.focus='[data-material-role]';materialApply(query=>query.set('date_field',materialDiscovery.role));}});
document.addEventListener('keydown',event=>{if(event.key==='Enter'&&event.target.matches('[data-material-from],[data-material-to]')){event.preventDefault();materialApplyRange(event.target.closest('.material-discovery'));}});
document.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)&&event.target.matches('path[data-material-country]')){event.preventDefault();event.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}});
for(const name of ['pointerover','focusin'])document.addEventListener(name,event=>{const path=event.target.closest('path[data-material-country]');if(!path)return;const panel=path.closest('.material-discovery');panel.querySelector('[data-material-map-hint]').textContent=path.querySelector('title').textContent+' · 点击筛选';});

const materialPanels=new Set();
function materialDisposeGlobe(panel){panel._globeGeneration=(panel._globeGeneration||0)+1;if(panel._globe)panel._globeView=panel._globe.getViewState();panel._globe?.dispose();panel._globe=null;}
function materialDisposeTimeline(panel){panel._timeGeneration=(panel._timeGeneration||0)+1;if(panel._timeline)panel._timeView=panel._timeline.getViewState();panel._timeline?.dispose();panel._timeline=null;}
function materialDispose(panel){panel._materialSuspended=true;materialDisposeGlobe(panel);materialDisposeTimeline(panel);materialPanels.delete(panel);}
async function materialMountGlobe(panel,scope,selected){
  const generation=(panel._globeGeneration||0)+1;panel._globeGeneration=generation;materialPanels.add(panel);
  const account=state.me?.id,load=state.loadId,hash=location.hash;
  const isCurrent=()=>materialViewCurrent(panel,account,load,hash)&&panel._globeGeneration===generation;
  const status=panel.querySelector('[data-material-globe-status]');
  panel.querySelector('[data-material-globe]').hidden=false;
  try{
    const instance=await visualLoader.mount('globe',panel.querySelector('[data-material-globe]'),{
      geometry:materialDiscovery.geometry,viewState:panel._globeView,snapshot:{countries:scope.countries,selected:[...selected]},
      onSelect:value=>{if(isCurrent())materialSelectCountry(value);},
      onStatus:message=>{if(isCurrent())status.textContent=message;}
    },{isCurrent});
    if(!isCurrent()){instance?.dispose();return;}panel._globe=instance;
    if(!panel._globeView)instance?.reset(materialDiscovery.view);panel.querySelector('[data-material-globe-retry]').hidden=true;
  }catch(error){if(isCurrent()){status.textContent='地球未加载，可使用国别或平面地图。';panel.querySelector('[data-material-globe-retry]').hidden=false;panel.querySelector('[data-material-globe]').hidden=true;}}
}
new MutationObserver(()=>{for(const panel of materialPanels)if(!panel.isConnected||state.me?.id!==materialDiscovery.account)materialDispose(panel);}).observe(document.getElementById('app'),{childList:true,subtree:true});

function materialTimeSnapshot(panel){
  const data=panel._materialData,window=data.timeline_window;
  return {years:(data.time_context?.dates||data.dates)[materialDiscovery.role].years,items:window?.items||[],lens:materialDiscovery.lens,kindLabels:kinds};
}
function materialApplyRange(panel){
  const from=panel.querySelector('[data-material-from]'),to=panel.querySelector('[data-material-to]'),status=panel.querySelector('[data-material-range-status]');
  if(!from.checkValidity()||!to.checkValidity()||(!from.value&&!to.value)||from.value&&to.value&&Number(from.value)>Number(to.value)){
    status.textContent='请输入1至9999之间的年份，起始年不能晚于结束年。';from.focus();return;
  }
  materialDiscovery.focus='[data-material-from]';
  materialApply(query=>{query.delete('date_unknown');query.delete('from');query.delete('to');query.set('date_field',materialDiscovery.role);if(from.value)query.set('from',String(Number(from.value)).padStart(4,'0')+'-01-01');if(to.value)query.set('to',String(Number(to.value)).padStart(4,'0')+'-12-31');});
}
async function materialMountTimeline(panel){
  materialDisposeTimeline(panel);
  const generation=panel._timeGeneration,account=state.me?.id,load=state.loadId,hash=location.hash;
  materialPanels.add(panel);
  const isCurrent=()=>materialViewCurrent(panel,account,load,hash)&&panel._timeGeneration===generation;
  const slot=panel.querySelector('[data-material-timeline]'),status=panel.querySelector('[data-material-time-status]');slot.replaceChildren();
  try{
    const instance=await visualLoader.mount('timeline',slot,{snapshot:materialTimeSnapshot(panel),viewState:panel._timeView,
      onRange:(from,to)=>{if(!isCurrent())return;panel.querySelector('[data-material-from]').value=from;panel.querySelector('[data-material-to]').value=to;panel.querySelector('[data-material-range-status]').textContent='待应用范围：'+from+'—'+to+' 年。';},
      onSelect:id=>{if(isCurrent()&&panel._materialData.timeline_window.items.some(item=>item.id===id))libraryOpenReader(id,panel.querySelector('[data-material-lens]'));},
      onStatus:message=>{if(isCurrent())status.textContent=message;}
    },{isCurrent});
    if(!isCurrent()){instance?.dispose();return;}panel._timeline=instance;if(!materialDiscovery.lens)status.textContent='';panel.querySelector('[data-material-time-retry]').hidden=true;
  }catch(error){if(isCurrent()){status.textContent='时间图未加载，可使用年份筛选。';panel.querySelector('[data-material-time-retry]').hidden=false;}}
}
function materialRefreshVisible(){if(document.hidden)return;for(const panel of materialPanels)if(panel.isConnected&&panel.open&&!panel._materialLoading)materialLoad(panel);}
document.addEventListener('visibilitychange',()=>{
  if(!document.hidden){materialRefreshVisible();return;}
  for(const panel of materialPanels){
    panel._materialEpoch=(panel._materialEpoch||0)+1;panel._materialLoading=false;panel.removeAttribute('aria-busy');panel._materialSuspended=true;
    materialDisposeGlobe(panel);materialDisposeTimeline(panel);
  }
});
window.addEventListener('focus',materialRefreshVisible);
