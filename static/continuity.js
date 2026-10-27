'use strict';

// A single browser history entry holds identifiers and position, never record bodies.
let continuityRouting=false,continuityRestoring=false,continuityHash=location.hash,continuityGeneration=0;
function continuityPosition(){
  if(!state.me)return null;
  const topic=typeof topicPosition==='function'?topicPosition():null;
  if(topic)return {account:state.me.id,hash:location.hash,topic,y:window.scrollY};
  if(document.querySelector('.library-workspace'))return {account:state.me.id,hash:location.hash,reader:libraryWorkspace.readerId,view:libraryWorkspace.view,selection:[...libraryWorkspace.selected],organizing:libraryWorkspace.organizing,focusId:libraryWorkspace.returnFocus?.dataset.id||null,focusAction:libraryWorkspace.returnFocus?.dataset.action||null,y:window.scrollY,returnY:libraryWorkspace.returnY,workspaceDetails:[...document.querySelectorAll('.library-workspace details:not(.library-reader details)')].flatMap((el,index)=>el.open?[index]:[]),readerDetails:[...document.querySelectorAll('.library-reader details')].flatMap((el,index)=>el.open?[index]:[]),readerY:document.querySelector('.library-reader')?.scrollTop||0,listY:document.querySelector('.record-list')?.scrollTop||0};
  return null;
}
function continuityRemember(){
  if(continuityRouting||continuityRestoring)return;
  const position=continuityPosition();
  if(position)history.replaceState({...history.state,position},'',location.href);
}
function continuityGo(page,params){
  const p=new URLSearchParams(params),hash='#'+page+(p.size?'?'+p:'');
  const form=currentEditorForm();if(form?.dataset.saving==='true'||(form&&!saveEditorDraft(form))){toast('请稍候，当前编辑内容尚未完成保存。');return;}
  continuityRemember();
  const position=history.state?.position||history.state?.returnPosition;
  if(hash===location.hash)return route();
  history.pushState(p.has('work')&&position?.account===state.me?.id?{returnPosition:position}:{},'',hash);return route();
}
function continuityRouteStart(){
  const form=currentEditorForm();
  if(form?.dataset.saving==='true'||(form&&!saveEditorDraft(form))){history.replaceState(history.state,'',continuityHash||'#dashboard');toast('请稍候，当前编辑内容尚未完成保存。');return false;}
  continuityGeneration++;continuityRestoring=false;
  continuityHash=location.hash;continuityRouting=true;
  return true;
}
function continuityBeforeRender(){
  const pos=history.state?.position;
  if(pos?.account===state.me?.id&&pos.hash===location.hash&&pos.view){libraryWorkspace.view=pos.view;libraryWorkspace.organizing=!!pos.organizing;}
}
function continuityRouteFailed(error){
  continuityRouting=false;
  if(![403,404].includes(error.status))return false;
  const params=new URLSearchParams(state.params);
  if(['sources','people'].includes(state.page)&&params.has('id')){params.delete('id');params.delete('work');}
  else if(document.querySelector('.library-workspace')||['library','compilations','favorites','review'].includes(state.page)){params.delete('source');params.delete('source_section');params.delete('collection');params.delete('page');}
  else return false;
  if(params.toString()===state.params.toString())return false;
  toast('原工作位置已失效，已返回可用列表。');go(state.page,params);return true;
}

async function continuityRestore(){
  continuityRouting=false;
  const pos=history.state?.position,hash=location.hash,account=state.me?.id,generation=continuityGeneration,loadId=state.loadId;
  const current=()=>generation===continuityGeneration&&loadId===state.loadId&&account===state.me?.id&&hash===location.hash;
  continuityRestoring=false;
  if(!pos||pos.account!==account||pos.hash!==hash)return;
  continuityRestoring=true;
  try{
    document.querySelectorAll('.library-workspace details:not(.library-reader details)').forEach((el,index)=>{el.open=(pos.workspaceDetails||[]).includes(index);});
    if(document.querySelector('.library-workspace')&&Array.isArray(pos.selection)){
      const valid=[];
      for(const id of pos.selection.slice(0,librarySelectionLimit)){
        try{const record=await api('/api/records/'+encodeURIComponent(id));if(record.id===id)valid.push(id);}catch(error){if(![403,404].includes(error.status))throw error;}
        if(!current())return;
      }
      libraryWorkspace.selected=new Set(valid);librarySelectionChanged();
    }
    if(pos.topic){await openResearchCollection(pos.topic.id,pos.topic);if(!current())return;if(pos.record)await workflowOpenRecord(pos.record);}
    else if(pos.reader&&document.querySelector('.library-workspace')){
      if(libraryWorkspace.items.some(r=>r.id===pos.reader)){libraryWorkspace.returnY=pos.returnY||0;await libraryOpenReader(pos.reader);if(!current())return;libraryWorkspace.returnY=pos.returnY||0;const panel=document.querySelector('.library-reader');if(panel){panel.querySelectorAll('details').forEach((el,index)=>{el.open=(pos.readerDetails||[]).includes(index);});panel.scrollTop=pos.readerY||0;}const list=document.querySelector('.record-list');if(list)list.scrollTop=pos.listY||0;}
      else{history.replaceState({...history.state,position:{...pos,reader:null}},'',location.href);toast('原资料已不在当前结果中，已返回查找列表。');}
    }
    if(current()){
      if(pos.focusId)libraryWorkspace.returnFocus=[...document.querySelectorAll('.record-list [data-action]')].find(el=>el.dataset.id===pos.focusId&&el.dataset.action===(pos.focusAction||'detail'))||null;
      if(!pos.reader)libraryWorkspace.returnFocus?.focus({preventScroll:true});
      window.scrollTo(0,pos.y||0);
    }
  }catch(error){if(current()){history.replaceState({...history.state,position:null},'',location.href);toast('原工作位置已失效，已返回当前页面。'+error.message);}}
  finally{if(generation===continuityGeneration)continuityRestoring=false;}
}
function continuityRecord(id){
  if(continuityRouting||continuityRestoring)return;
  const pos=continuityPosition();
  if(pos?.topic){history.pushState({position:{...pos,record:id}},'',location.href);}
}
async function continuityReturn(id){
  const pos=history.state?.returnPosition;
  if(!pos||pos.account!==state.me?.id||(pos.reader||pos.record)!==id){
    if(!['sources','people'].includes(state.page)||state.params.get('work')!==id)return false;
    const hash='#library?'+new URLSearchParams({q:id});history.pushState({position:{account:state.me.id,hash,reader:id,view:'list'}},'',hash);await route();return true;
  }
  if(closeModal(false)===false)return true;
  history.pushState({position:pos},'',pos.hash);await route();return true;
}
function continuityClosed(){
  if(continuityRouting||continuityRestoring)return;
  const pos=history.state?.position;
  if(!state.me||!pos||pos.account!==state.me.id)return;
  if(pos.topic&&pos.record){
    history.replaceState({position:{...pos,record:null}},'',location.href);
    openResearchCollection(pos.topic.id,pos.topic).catch(error=>toast(error.message));
  }else if(pos?.topic)history.replaceState({...history.state,position:null},'',location.href);
  else if(pos.reader&&document.querySelector('.library-reader[hidden]'))libraryOpenReader(pos.reader).catch(error=>toast(error.message));
}
document.addEventListener('click',event=>{if(event.target.closest('[data-action="library-view"]'))queueMicrotask(continuityRemember);});
document.addEventListener('scroll',()=>{if(!continuityRouting&&!continuityRestoring){const pos=history.state?.position;if(pos?.account===state.me?.id){const current=continuityPosition();if(current)history.replaceState({...history.state,position:{...pos,...current,record:pos.record}},'',location.href);}}},true);

window.addEventListener('popstate',()=>{if(location.hash===continuityHash)route();});
