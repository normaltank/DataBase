'use strict';

function countryKey(value){const text=String(value||'').trim();return state.countryNames?.aliases?.[text.toLowerCase()]||text.toLowerCase();}
function countryLabel(value){return state.countryNames?.labels?.[countryKey(value)]||String(value||'');}
function countryOptions(data,key,current,unknown='待确认'){
  const selected=String(current||'').split('|').filter(Boolean).map(countryKey),items=[...(data.facet_options?.[key]||data.facets?.[key]||[])];
  for(const value of selected)if(!items.some(item=>item.value===value))items.push({value,label:countryLabel(value)});
  return Object.fromEntries(items.map(item=>[item.value,item.value==='__pending__'||item.value==='__unknown__'?unknown:item.label||countryLabel(item.value)]));
}

document.addEventListener('keydown',event=>{
  if(event.key!=='Escape')return;
  const facet=event.target.closest('.reading-facet[open]');
  if(facet){event.preventDefault();facet.open=false;facet.querySelector('summary').focus();}
});
document.addEventListener('click',event=>{
  document.querySelectorAll('.reading-facet[open]').forEach(facet=>{if(!facet.contains(event.target))facet.open=false;});
});
