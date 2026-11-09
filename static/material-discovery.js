'use strict';

// Presentation state is deliberately absent from recordQuery and frozen queries.
const materialDiscovery={account:null,open:true,view:'europe',role:'published',geometry:null,focus:null};
const materialDateNames={published:'发表时间',collected:'首次收录',updated:'最近修订'};
function materialDiscoveryHTML(){
  return '<details class="material-discovery"><summary>国别地球与时间探索</summary><div data-material-distribution></div></details>';
}
function materialCurrent(panel,epoch,account,load,hash){
  return panel.isConnected&&panel.open&&panel._materialEpoch===epoch&&state.me?.id===account&&state.loadId===load&&location.hash===hash;
}
async function materialLoad(panel){
  const epoch=(panel._materialEpoch||0)+1;panel._materialEpoch=epoch;
  const account=state.me?.id,load=state.loadId,hash=location.hash,body=panel.querySelector('[data-material-distribution]');
  materialDispose(panel);
  body.innerHTML='<p role="status">正在读取当前查询的分布…</p>';
  const query=recordQuery();query.delete('page');query.delete('size');
  try{
    const [data,geometry]=await Promise.all([api('/api/material-discovery?'+query),materialDiscovery.geometry||api('/static/geo/material-world-110m.json')]);
    if(!materialCurrent(panel,epoch,account,load,hash))return;
    materialDiscovery.geometry=geometry;panel._materialData=data;
    materialRender(panel);
  }catch(error){
    if(!materialCurrent(panel,epoch,account,load,hash))return;
    body.innerHTML='<p role="alert">无法读取地图与时间分布：'+esc(error.message)+'</p><button type="button" class="button" data-material-retry>重新读取分布</button>';
  }
}
function materialRender(panel){
  const data=panel._materialData,geometry=materialDiscovery.geometry;if(!data||!geometry)return;
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
  const date=data.dates[materialDiscovery.role],hasTime=Boolean(p.get('from')||p.get('to')||p.get('date_unknown'));
  const yearMax=Math.max(1,...date.years.map(item=>item.count));
  const legend=[['zero','0 条'],['low','1–'+low+' 条'],...(high>low?[['middle',(low+1)+'–'+high+' 条']]:[]),...(maximum>high?[['high',(high+1)+'–'+maximum+' 条']]:[])];
  materialDispose(panel);
  panel.querySelector('[data-material-distribution]').innerHTML=
    '<p class="material-scope" role="status">当前完整可见查询：<strong>'+data.total+' 条</strong>。多国资料在各国分别计数；数量表示库内资料，不表示研究热度或覆盖完整性。</p>'
    +'<section aria-label="研究对象国分布"><div class="material-heading"><h2>研究对象国</h2><div class="material-controls" role="group" aria-label="地图视角"><button type="button" class="button tiny" data-material-view="europe" aria-pressed="'+(materialDiscovery.view==='europe')+'">欧洲</button><button type="button" class="button tiny" data-material-view="world" aria-pressed="'+(materialDiscovery.view==='world')+'">全世界</button></div></div>'
    +'<p class="material-context">地球及国别列表：保留其他条件、排除研究对象国条件，共 '+countryScope.total+' 条。代表点只用于选择研究对象国。</p>'
    +'<div class="material-geography"><div class="material-stage"><div class="material-globe" data-material-globe></div><p data-material-globe-status role="status">正在加载地球…</p><div class="material-controls"><button type="button" class="button tiny" data-material-globe-retry>重试地球</button><button type="button" class="button tiny" data-material-flat aria-pressed="false">平面地图</button></div>'
    +'<p class="material-map-hint" hidden data-material-map-hint aria-live="polite">点击国界或下方国别按钮筛选资料</p>'
    +'<svg class="material-map" hidden viewBox="'+(materialDiscovery.view==='europe'?'385 38 230 125':geometry.viewBox)+'" role="group" aria-label="'+(materialDiscovery.view==='europe'?'欧洲':'全世界')+'研究对象国地图">'+paths+'</svg>'
    +'<div class="material-map-footer"><div class="material-legend" aria-label="库内资料数量图例">'+legend.map(([value,text])=>'<span><i class="material-count-'+value+'"></i>'+text+'</span>').join('')+'</div><span>底图：<a href="https://www.naturalearthdata.com/about/terms-of-use/" target="_blank" rel="noopener noreferrer">Natural Earth · 公共领域</a></span></div>'
    +'</div><div class="material-country-column"><div class="material-heading"><h3>国别列表</h3><button type="button" class="button tiny" data-material-clear="country" '+(!selected.size?'disabled':'')+'>清除研究对象国条件</button></div>'
    +'<div class="material-country-list" role="group" aria-label="国别文字筛选">'+(countries.length?countries.map(item=>'<button type="button" class="button tiny" data-material-country="'+esc(item.value)+'" aria-pressed="'+selected.has(item.value)+'">'+esc(label(item))+' <strong>'+item.count+'</strong>'+(!mapped.has(item.value)?'<span class="material-unmapped"> · 无地图</span>':'')+'</button>').join(''):'<p>当前查询没有国别分布。可清除筛选后重新查找。</p>')+'</div></div></div></section>'
    +'<section class="material-time" aria-label="时间分布"><div class="material-heading"><h2>时间分布</h2><label>浏览口径 <select data-material-role aria-label="分布时间口径">'+Object.entries(materialDateNames).map(([value,text])=>'<option value="'+value+'" '+(materialDiscovery.role===value?'selected':'')+'>'+text+'</option>').join('')+'</select></label><button type="button" class="button tiny" data-material-clear="time" '+(!hasTime?'disabled':'')+'>清除时间条件</button></div>'
    +'<p>'+materialDateNames[materialDiscovery.role]+'：仅年份 '+date.precision.year+' 条，精确到月 '+date.precision.month+' 条，精确到日 '+date.precision.day+' 条；未知 '+date.unknown+' 条。点击年份筛选，保留登记精度。</p>'
    +'<div class="material-years" role="group" aria-label="年份筛选">'+date.years.map(item=>{
      const active=(p.get('date_field')||'published')===materialDiscovery.role&&p.get('from')===item.year+'-01-01'&&p.get('to')===item.year+'-12-31';
      return '<button class="material-year" type="button" data-material-year="'+item.year+'" aria-pressed="'+active+'" aria-label="'+item.year+'年，'+item.count+'条，按'+materialDateNames[materialDiscovery.role]+'筛选"><span>'+item.year+'年</span><svg class="material-year-track" viewBox="0 0 100 12" preserveAspectRatio="none" aria-hidden="true"><rect width="'+Math.max(1,100*item.count/yearMax)+'" height="12"></rect></svg><strong>'+item.count+' 条</strong></button>';
    }).join('')+'</div><button type="button" class="button tiny" data-material-year="unknown" aria-pressed="'+((p.get('date_field')||'published')===materialDiscovery.role&&p.get('date_unknown')==='1')+'">'+materialDateNames[materialDiscovery.role]+'未知 · '+date.unknown+' 条</button>'
    +(!data.total?'<p>当前查询没有资料，可清除国别或时间条件，或调整上方筛选。</p>':'')+'</section>';
  materialMountGlobe(panel,countryScope,selected);
  if(materialDiscovery.focus){panel.querySelector(materialDiscovery.focus)?.focus({preventScroll:true});materialDiscovery.focus=null;}
}
function materialApply(change){
  const query=recordQuery();query.delete('saved_search');query.delete('page');query.delete('size');
  change(query);go(state.page,query);
}
document.addEventListener('library:rendered',event=>{
  const root=event.detail.root;if(!root||root.querySelector('.material-discovery'))return;
  if(materialDiscovery.account!==state.me?.id){Object.assign(materialDiscovery,{account:state.me?.id,open:true,view:'europe',role:recordQuery().get('date_field')||'published',focus:null});}
  root.querySelector('.results-head').insertAdjacentHTML('beforebegin',materialDiscoveryHTML());
  const panel=root.querySelector('.material-discovery');
  panel.addEventListener('toggle',()=>{if(!panel.isConnected)return;materialDiscovery.open=panel.open;if(panel.open)materialLoad(panel);else {panel._materialEpoch=(panel._materialEpoch||0)+1;materialDispose(panel);}});
  if(materialDiscovery.open)panel.open=true;
});
document.addEventListener('click',event=>{
  const panel=event.target.closest('.material-discovery');if(!panel)return;
  const button=event.target.closest('[data-material-country],[data-material-year],[data-material-view],[data-material-clear],[data-material-retry],[data-material-globe-retry],[data-material-flat]');if(!button)return;
  if(button.hasAttribute('data-material-globe-retry')){materialDispose(panel);materialMountGlobe(panel,panel._materialData.country_context||panel._materialData,new Set((recordQuery().get('country')||'').split('|').filter(Boolean).map(countryKey)));}
  else if(button.hasAttribute('data-material-flat')){const flat=panel.querySelector('.material-map');flat.toggleAttribute('hidden');const shown=!flat.hasAttribute('hidden');panel.querySelector('[data-material-globe]').hidden=shown;button.setAttribute('aria-pressed',String(shown));panel.querySelector('[data-material-map-hint]').hidden=!shown;if(shown)materialDispose(panel);else materialMountGlobe(panel,panel._materialData.country_context||panel._materialData,new Set((recordQuery().get('country')||'').split('|').filter(Boolean).map(countryKey)));}
  else if(button.hasAttribute('data-material-country')){materialDiscovery.focus='.material-country-list [aria-pressed="true"]';materialApply(query=>query.set('country',button.dataset.materialCountry));}
  else if(button.hasAttribute('data-material-view')){materialDiscovery.view=button.dataset.materialView;panel._globe?.reset(materialDiscovery.view);panel.querySelector('.material-map').setAttribute('viewBox',materialDiscovery.view==='europe'?'385 38 230 125':materialDiscovery.geometry.viewBox);panel.querySelector('[data-material-view="'+materialDiscovery.view+'"]').focus({preventScroll:true});}
  else if(button.hasAttribute('data-material-retry'))materialLoad(panel);
  else if(button.hasAttribute('data-material-clear')){materialDiscovery.focus='[data-material-role]';materialApply(query=>{for(const key of button.dataset.materialClear==='country'?['country']:['from','to','date_unknown','date_field'])query.delete(key);});}
  else if(button.hasAttribute('data-material-year')){materialDiscovery.focus='[data-material-year][aria-pressed="true"]';materialApply(query=>{query.delete('from');query.delete('to');query.delete('date_unknown');query.set('date_field',materialDiscovery.role);if(button.dataset.materialYear==='unknown')query.set('date_unknown','1');else{query.set('from',button.dataset.materialYear+'-01-01');query.set('to',button.dataset.materialYear+'-12-31');}});}
});
document.addEventListener('change',event=>{if(event.target.matches('[data-material-role]')){materialDiscovery.role=event.target.value;const panel=event.target.closest('.material-discovery');materialRender(panel);panel.querySelector('[data-material-role]').focus({preventScroll:true});}});
document.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)&&event.target.matches('path[data-material-country]')){event.preventDefault();event.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}});
for(const name of ['pointerover','focusin'])document.addEventListener(name,event=>{const path=event.target.closest('path[data-material-country]');if(!path)return;const panel=path.closest('.material-discovery');panel.querySelector('[data-material-map-hint]').textContent=path.querySelector('title').textContent+' · 点击筛选';});

const materialPanels=new Set();
function materialDispose(panel){panel._globeGeneration=(panel._globeGeneration||0)+1;panel._globe?.dispose();panel._globe=null;materialPanels.delete(panel);}
async function materialMountGlobe(panel,scope,selected){
  const generation=(panel._globeGeneration||0)+1;panel._globeGeneration=generation;materialPanels.add(panel);
  const epoch=panel._materialEpoch,account=state.me?.id,load=state.loadId,hash=location.hash;
  const isCurrent=()=>materialCurrent(panel,epoch,account,load,hash)&&panel._globeGeneration===generation;
  const status=panel.querySelector('[data-material-globe-status]');
  panel.querySelector('[data-material-globe]').hidden=false;
  try{
    const instance=await visualLoader.mount('globe',panel.querySelector('[data-material-globe]'),{
      geometry:materialDiscovery.geometry,snapshot:{countries:scope.countries,selected:[...selected]},
      onSelect:value=>{if(isCurrent())materialApply(query=>query.set('country',value));},
      onStatus:message=>{if(isCurrent())status.textContent=message;}
    },{isCurrent});
    if(!isCurrent()){instance?.dispose();return;}panel._globe=instance;
    instance?.reset(materialDiscovery.view);status.textContent='拖动旋转，滚轮或双指缩放；点击国界或代表点筛选。也可使用下方文字国别。';
  }catch(error){if(isCurrent()){status.textContent='地球暂不可用，可继续使用国别文字筛选或平面地图。';panel.querySelector('[data-material-globe]').hidden=true;}}
}
new MutationObserver(()=>{for(const panel of materialPanels)if(!panel.isConnected||state.me?.id!==materialDiscovery.account)materialDispose(panel);}).observe(document.getElementById('app'),{childList:true,subtree:true});
