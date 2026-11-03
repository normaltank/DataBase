'use strict';
// Exercise the real queue modal, item editor metadata and saved-item return offline.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let activeForm,shown,metadata,stored;
const node=()=>({hidden:false,textContent:'',remove(){},prepend(){},after(){}});
function form(){
  const elements=[];elements.kind={options:[{value:'other',remove(){}}]};elements.intake_token={value:''};
  const nodes=new Map();
  return {elements,dataset:{draftUser:'synthetic'},isConnected:true,_editing:{},
    append(el){elements.push(el);if(el.name)elements[el.name]=el;},
    querySelector(selector){if(selector==='.draft-offer'||selector.includes('detach'))return null;if(!nodes.has(selector))nodes.set(selector,node());return nodes.get(selector);},
    querySelectorAll(){return [];}};
}
const context={console,document:{addEventListener(){},createElement:node,querySelector:()=>activeForm},
  crypto:{randomUUID:()=> 'synthetic'},state:{me:{id:'synthetic'}},draftPrefix:'synthetic:',modalGeneration:1,
  esc:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;'),externalLink:(url,label)=>`<a href="${url}">${label}</a>`,linkButton:()=>'',sourceHref:id=>'#source/'+id,
  modal(title,html){shown={title,html};activeForm=form();},currentEditorForm:()=>activeForm,
  enableEditorDraft:async()=>{},saveEditorDraft(form){stored=JSON.stringify({user_id:'synthetic',values:{ris_queue_json:JSON.stringify(form._risQueue)}});return true;},
  localStorage:{getItem:()=>stored||null},api:async()=>({saved:false,duplicates:[],blocked:false}),
  workflowRecordForm:async()=>{activeForm=form();return activeForm;},setIntakePreview(editor,value){metadata=value;editor._intakePreview=value;},
  fillIntakeBlanks(){},restoreIntakeForm(){},isResearchContent:()=>false,refreshSourcePickers(){},loadLookups:async()=>{},toast(){},intakeBylines:()=>[]};
vm.createContext(context);
for(const file of ['static/ris.js','static/discovery.js'])vm.runInContext(fs.readFileSync(file,'utf8'),context);
async function exercise(queue,source,format){
  context.queue=queue;
  await vm.runInContext('risShowQueue(queue)',context);
  assert.ok(shown.title.includes(source),JSON.stringify(shown));
  if(source!=='LIIA Opinions')assert.ok(!shown.title.includes('LIIA'),shown.title);
  const initial=shown.title;
  await vm.runInContext('risEdit(currentEditorForm(),0)',context);
  assert.equal(metadata.format,format);
  assert.equal(metadata.fields.title,'Synthetic item');
  await vm.runInContext('risRecordSaved(currentEditorForm(),{id:"synthetic-saved"})',context);
  assert.equal(shown.title,initial);
  assert.ok(shown.html.includes('已保存'));
  await vm.runInContext('risOpenDraft(queueDraftKey(queue),queue)',context);
  assert.equal(shown.title,initial);
  if(!activeForm._risQueue.items[0].saved)await vm.runInContext('risEdit(currentEditorForm(),0)',context);
  assert.equal(metadata.format,format);
}
(async()=>{
  for(const [source,entry,format,adapter] of [['CJIR RSS','rss','CJIR RSS','cjir-rss-v1'],['GSSC Publications','html','GSSC HTML listing','gssc-publications-v1'],['Intersections RSS','rss','Intersections RSS','intersections-rss-v1'],['LIIA Opinions','rss','LIIA RSS','liia-opinions-v1']]){
    const item={index:1,type:'待人工确认类别',fields:{kind:'other',title:'Synthetic item',url:'https://synthetic.example/item',published_on:'2026-10-22'},
      evidence:{format,adapter,retrieved_at:'2026-11-03T00:00:00Z',provenance:{}},errors:[],warnings:[],file_duplicates:[],authors:[],duplicates:[],candidates:{},token:'synthetic'};
    const queue={format:'discovery',source_id:'synthetic',source_name:source,entry_type:entry,filename:source+' 近期发现',items:[item]};
    await exercise(queue,source,format);
    // Older drafts retain per-item evidence but have no new queue metadata.
    await exercise({format:'discovery',source_id:'synthetic',filename:source+' 近期发现',items:[{...item,saved:undefined}]},source,format);
  }
  await exercise({format:'discovery',source_id:'synthetic',filename:'近期资料发现',window:{start:'2026-10-05',end:'2026-11-03'},counts:{},exclusions:[],returned:1,items:[{index:1,type:'other',fields:{kind:'other',title:'Synthetic item'},evidence:{},errors:[],warnings:[],file_duplicates:[],authors:[],duplicates:[],candidates:{}}]},'近期资料发现','官方来源发现（入口类型未记录）');
  assert.ok(!shown.html.includes('固定 RSS')&&!shown.html.includes('官方 HTML 列表'));
  context.queue={format:'discovery',source_id:'synthetic',filename:'LIIA Opinions 近期发现',items:[]};
  await vm.runInContext('risShowQueue(queue)',context);assert.equal(shown.title,'近期资料发现');assert.ok(!shown.html.includes('LIIA'));
  console.log('PASS: 4 sources × current/legacy queue open→edit metadata→saved return→draft restore; unknown metadata and empty queue');
})().catch(error=>{console.error(error);process.exitCode=1;});
