import {createTwoFilesPatch} from 'diff';
import {html} from 'diff2html';

// Default precompiled templates only. The library escapes both HTML-like inputs;
// these strings are recorded text, never raw templates or an editable file model.
export function mount(container,options={}){
  let disposed=false,signature='';
  function update(snapshot){
    if(disposed)return;
    const next=JSON.stringify(snapshot);if(next===signature)return;signature=next;
    const patch=createTwoFilesPatch('原值','新值',String(snapshot.before??''),String(snapshot.after??''),'','',{context:4});
    container.innerHTML=html(patch,{drawFileList:false,outputFormat:'line-by-line',matching:'none',diffStyle:'word'});
  }
  update(options.snapshot||{});
  return {update,resize(){},dispose(){if(disposed)return;disposed=true;container.replaceChildren();}};
}
