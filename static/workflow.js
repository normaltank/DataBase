'use strict';

const personalKinds = new Set(['compilation', 'research_note', 'research_report']);
const authorControlledKinds = new Set(['compilation', 'research_report']);
const draftPrefix = 'zhihui:draft:v1:';
const draftTypeLabels = {collection:'研究专题',person:'人物档案',byline:'作品署名',employment:'任职经历',affiliation:'文章署名单位',source:'来源介绍'};
function draftTypeLabel(draft) { return draftTypeLabels[draft.type] || kinds[draft.kind] || '内容'; }
const richTags = new Set('p div br h2 h3 h4 strong b em i u ul ol li blockquote table thead tbody tfoot tr th td a hr'.split(' '));
let draftDatabase, draftFileWrites = 0;
function isResearchContent(kind) { return personalKinds.has(kind) || kind === 'directory_translation'; }
function canManageRecordAccess(record) {
  if (!record?.id) return true;
  if (typeof record.can_manage_access === 'boolean') return record.can_manage_access;
  if (personalKinds.has(record.kind)) return !!record.author_confirmed && record.author_id === state.me.id;
  return record.owner_id === state.me.id || state.me.role === 'admin';
}
function cleanRich(value) {
  const source = new DOMParser().parseFromString(String(value || ''), 'text/html');
  function copy(node) {
    if (node.nodeType === Node.TEXT_NODE) return document.createTextNode(node.textContent);
    const fragment = document.createDocumentFragment();
    if (node.nodeType !== Node.ELEMENT_NODE) return fragment;
    const tag = node.tagName.toLowerCase();
    if (['script','style','iframe','object','svg','math','template'].includes(tag)) return fragment;
    const result = richTags.has(tag) ? document.createElement(tag) : fragment;
    if (tag === 'a' && result.nodeType === Node.ELEMENT_NODE) {
      try { const u = new URL(node.getAttribute('href')); if (['http:','https:'].includes(u.protocol) && !u.username && !u.password) { result.href = u.href; result.rel = 'noopener noreferrer'; result.target = '_blank'; } } catch {}
    }
    if (['td','th'].includes(tag)) for (const name of ['colspan','rowspan']) { const n = Number(node.getAttribute(name)); if (Number.isInteger(n) && n > 0 && n <= 20) result.setAttribute(name, n); }
    for (const child of node.childNodes) result.append(copy(child));
    return result;
  }
  const holder = document.createElement('div');
  for (const node of source.body.childNodes) holder.append(copy(node));
  return holder.innerHTML;
}
function readRich(value) {
  const holder=document.createElement('div');holder.innerHTML=cleanRich(value);
  holder.querySelectorAll('table').forEach((table,index)=>{
    const region=document.createElement('div');region.className='reading-table';
    region.tabIndex=0;region.setAttribute('role','region');
    region.setAttribute('aria-label','内容表格 '+(index+1)+'，可横向滚动');
    table.before(region);region.append(table);
  });
  return holder.innerHTML;
}
function richEditor(name, label, value = '') {
  return '<section class="rich-field wide" data-rich-field="'+name+'"><label class="field-label" id="label-'+name+'">'+label+'</label>'
    + '<div class="rich-toolbar" role="toolbar" aria-label="'+label+'格式"><select data-rich-format aria-label="段落样式"><option value="p">正文段落</option><option value="h2">一级标题</option><option value="h3">二级标题</option><option value="h4">三级标题</option><option value="blockquote">引用段落</option></select>'
    + [['bold','加粗'],['italic','斜体'],['insertUnorderedList','项目列表'],['insertOrderedList','编号列表'],['link','链接'],['table','插入表格'],['row','加一行'],['column','加一列'],['afterTable','表后段落'],['removeTable','删除表格'],['undo','撤销'],['redo','重做']].map(([a,l])=>'<button type="button" data-rich-action="'+a+'" title="'+l+'">'+l+'</button>').join('')
    + '</div><div class="rich-insert" data-rich-link hidden><label>链接文字<input data-link-text></label><label>网页地址<input data-link-url type="url" placeholder="https://…"></label><button class="button tiny" type="button" data-rich-action="insertLink">插入链接</button></div>'
    + '<div class="rich-insert" data-rich-table hidden><label>行数<input data-table-rows type="number" min="1" max="20" value="3"></label><label>列数<input data-table-columns type="number" min="1" max="12" value="3"></label><button class="button tiny" type="button" data-rich-action="insertTable">插入表格</button></div>'
    + '<div class="rich-editor rich-prose" contenteditable="true" role="textbox" aria-multiline="true" aria-labelledby="label-'+name+'" data-rich-input spellcheck="true">'+cleanRich(value)+'</div><textarea name="'+name+'" hidden>'+esc(value)+'</textarea><div class="rich-message" role="status"></div></section>';
}
function syncRichForm(form) { form.querySelectorAll('[data-rich-field]').forEach(field => { field.querySelector('textarea').value = cleanRich(field.querySelector('[data-rich-input]').innerHTML); }); }
function editorSelection(editor) {
  const selection = window.getSelection();
  if (selection?.rangeCount && editor.contains(selection.anchorNode)) editor._range = selection.getRangeAt(0).cloneRange();
}
function restoreSelection(editor) {
  editor.focus();
  const selection = window.getSelection(), range = editor._range;
  if (range && editor.contains(range.startContainer)) { selection.removeAllRanges(); selection.addRange(range); }
  else { const end = document.createRange(); end.selectNodeContents(editor); end.collapse(false); selection.removeAllRanges(); selection.addRange(end); }
}
function selectedCell() { const n = window.getSelection()?.anchorNode; return (n?.nodeType === Node.ELEMENT_NODE ? n : n?.parentElement)?.closest('td,th'); }
function richAction(button) {
  const field = button.closest('[data-rich-field]'), editor = field.querySelector('[data-rich-input]'), action = button.dataset.richAction;
  const message = field.querySelector('.rich-message'); message.textContent = '';
  if (action === 'link' || action === 'table') {
    const panel = field.querySelector(action === 'link' ? '[data-rich-link]' : '[data-rich-table]'); panel.hidden = !panel.hidden;
    if (action === 'link') field.querySelector('[data-link-text]').value = editor._range?.toString() || '';
    if (!panel.hidden) panel.querySelector('input').focus(); return;
  }
  restoreSelection(editor);
  if (action === 'insertLink') {
    const url = field.querySelector('[data-link-url]').value.trim(), text = field.querySelector('[data-link-text]').value.trim() || url;
    let valid = false; try { const u = new URL(url); valid = ['http:','https:'].includes(u.protocol) && !u.username && !u.password; } catch {}
    if (!valid) { message.textContent = '请填写 http:// 或 https:// 网页地址。'; return; }
    document.execCommand('insertHTML', false, '<a href="'+esc(url)+'">'+esc(text)+'</a>'); field.querySelector('[data-rich-link]').hidden = true;
  } else if (action === 'insertTable') {
    const rows = Math.min(20, Math.max(1, Number(field.querySelector('[data-table-rows]').value) || 3));
    const columns = Math.min(12, Math.max(1, Number(field.querySelector('[data-table-columns]').value) || 3));
    document.execCommand('insertHTML', false, '<table><tbody>'+Array.from({length:rows},(_,r)=>'<tr>'+Array.from({length:columns},(_,c)=>r===0?'<th>栏目 '+(c+1)+'</th>':'<td><br></td>').join('')+'</tr>').join('')+'</tbody></table><p><br></p>'); field.querySelector('[data-rich-table]').hidden = true;
  } else if (['row','column','afterTable','removeTable'].includes(action)) {
    const cell = selectedCell(), table = cell?.closest('table');
    if (!table || !editor.contains(table)) { message.textContent = '请先点选表格中的单元格。'; return; }
    if (action === 'row') { const row = table.insertRow(cell.parentElement.rowIndex + 1); for (let i=0;i<cell.parentElement.cells.length;i++) row.insertCell().innerHTML='<br>'; }
    if (action === 'column') for (const row of table.rows) row.insertCell(Math.min(cell.cellIndex + 1,row.cells.length)).innerHTML='<br>';
    if (action === 'afterTable') { const p=document.createElement('p');p.innerHTML='<br>';table.after(p);const r=document.createRange();r.selectNodeContents(p);r.collapse(true);window.getSelection().removeAllRanges();window.getSelection().addRange(r); }
    if (action === 'removeTable') table.remove();
  } else document.execCommand(action, false);
  editorSelection(editor); const form=editor.closest('form');form._dirty=true;syncRichForm(form);saveEditorDraft(form);
}

function fileStore() {
  if (!draftDatabase) draftDatabase = new Promise((resolve,reject)=>{ const request=indexedDB.open('zhihui-editor-drafts-v1',1);request.onupgradeneeded=()=>request.result.createObjectStore('files');request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error); });
  return draftDatabase;
}
async function draftFileOperation(key, operation, value) {
  const db=await fileStore(); return new Promise((resolve,reject)=>{const tx=db.transaction('files',operation==='get'?'readonly':'readwrite'), store=tx.objectStore('files');const request=operation==='get'?store.get(key):operation==='put'?store.put(value,key):store.delete(key);let result;request.onsuccess=()=>{result=request.result;};tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});
}
function currentEditorForm() { return document.querySelector('form[data-draft-key]'); }
function draftStatus(form, text, failed=false) { const el=form?.querySelector('[data-draft-status]');if(el){el.textContent=text;el.classList.toggle('error-text',failed);} }
function collectDraft(form) {
  syncRichForm(form);
  if(typeof syncCollectionScopeLog==='function')syncCollectionScopeLog(form);
  const values={};for(const element of form.elements){if(!element.name||element.type==='file'||element.type==='password')continue;if(['checkbox','radio'].includes(element.type)){if(!values[element.name])values[element.name]=[];if(element.checked)values[element.name].push(element.value);}else if(element.multiple)values[element.name]=[...element.selectedOptions].map(o=>o.value);else values[element.name]=element.value;}
  const edit=form._editing;
  return {user_id:form.dataset.draftUser,type:edit.type,id:edit.id,kind:values.kind||edit.original.kind,context:form.dataset.draftContext||'',version:edit.version,title:values.title||values.name||'未命名草稿',values,links:form._links||[],relationships:[...form.querySelectorAll('[data-relation-row]')].map(row=>Object.fromEntries([...row.querySelectorAll('[data-rel]')].map(el=>[el.dataset.rel,el.value]))),specific:edit.draftSpecific||{},file:form._draftFile?{name:form._draftFile.name,size:form._draftFile.size}:null,updated_at:new Date().toISOString(),conflict_pending:!!form._conflictPending};
}
function saveEditorDraft(form, force=false) {
  if (!form?.dataset.draftKey || form._saved || form._draftOffer || (!force&&!form._dirty)) return true;
  try { localStorage.setItem(form.dataset.draftKey,JSON.stringify(collectDraft(form)));draftStatus(form,form._filePending?'正在保存附件草稿…':'草稿已保存在此浏览器');form._draftFailed=false;return true; }
  catch { form._draftFailed=true;draftStatus(form,'草稿未能保存到浏览器，请保持此页打开并提交保存。',true);return false; }
}
async function enableEditorDraft(form, edit, context='', existingKey='') {
  if(!form.isConnected)return;
  form._editing=edit;form._links=state.links.slice();form.dataset.draftUser=state.me.id;form.dataset.draftContext=context;
  const accountPrefix=draftPrefix+encodeURIComponent(state.me.id)+':';
  form.dataset.draftKey=existingKey.startsWith(accountPrefix)?existingKey:accountPrefix+edit.type+':'+(edit.id||'new-'+edit.original.kind+'-'+context);
  const bar=document.createElement('div');bar.className='draft-bar';bar.innerHTML='<span data-draft-status role="status">编辑时自动保存本机草稿</span><button type="button" class="button tiny" data-action="save-draft">保存草稿</button>';form.prepend(bar);
  let saved;try{saved=JSON.parse(localStorage.getItem(form.dataset.draftKey)||'null');}catch{}
  if(saved?.user_id===state.me.id){form._draftOffer=saved;const offer=document.createElement('div');offer.className='notice draft-offer';offer.innerHTML='<p>有一份 '+esc(dateTime(saved.updated_at))+' 保存的草稿'+(saved.file?'（含附件 '+esc(saved.file.name)+'）':'')+'。</p><div class="row wrap"><button type="button" class="button primary tiny" data-action="restore-draft">恢复草稿</button><button type="button" class="button tiny" data-action="discard-draft">舍弃这份草稿</button></div>';bar.after(offer);form.querySelector('[type=submit]').disabled=true;}
}
async function restoreEditorDraft(form) {
  const draft=form._draftOffer;if(!draft||draft.user_id!==state.me?.id)return;
  if(draft.type==='source'){state.editing.draftSpecific={...draft.specific,...draft.values,relationships:draft.relationships};form.querySelector('#source-specific-fields').innerHTML=sourceSpecific({...state.editing.draftSpecific,kind:draft.values.kind});}
  if(draft.type==='record'&&typeof prepareEvidenceDraft==='function')await prepareEvidenceDraft(form,draft.values);
  if(draft.type==='record'){
    const language=form.elements.language,value=draft.values.language;
    if(language&&typeof value==='string'&&value&&![...language.options].some(option=>option.value===value))language.add(new Option(value,value));
  }
  for(const el of form.elements){if(!el.name||el.type==='file')continue;const value=draft.values[el.name];if(value===undefined)continue;if(el.matches('[data-source-values]'))restoreSourceSelection(el,value);else if(['checkbox','radio'].includes(el.type))el.checked=Array.isArray(value)&&value.includes(el.value);else if(el.multiple)[...el.options].forEach(o=>o.selected=Array.isArray(value)&&value.includes(o.value));else el.value=value;}
  refreshSourcePickers(form);
  if(draft.type==='collection'&&typeof renderScopeLogRows==='function')renderScopeLogRows(form);
  if(draft.type==='record'&&typeof restoreIntakeForm==='function')restoreIntakeForm(form);
  if(draft.type==='byline')restoreBylineDraft(form,draft);
  if(draft.type==='employment'||draft.type==='affiliation')restoreRelationshipDraft(form,draft);
  form.querySelectorAll('[data-rich-field]').forEach(field=>field.querySelector('[data-rich-input]').innerHTML=cleanRich(draft.values[field.dataset.richField]));
  state.links=draft.links||[];form._links=state.links.slice();renderSelectedLinks();if(typeof uxRefreshReadingContext==='function')uxRefreshReadingContext(form);
  let fileMissing=false;
  if(draft.file){try{const file=await draftFileOperation(form.dataset.draftKey,'get');if(form.dataset.draftUser!==state.me?.id)return;if(file){form._draftFile=file;showDraftFile(form);}else fileMissing=true;}catch{fileMissing=true;}}
  const latestVersion=form._editing.version;form._editing.version=draft.version;form._draftOffer=null;form._dirty=true;form.querySelector('.draft-offer')?.remove();form.querySelector('[type=submit]').disabled=false;
  if(draft.type==='record'){updateRecordFormMode(form);form._updateInformationMode?.();}saveEditorDraft(form,true);
  if(fileMissing)draftStatus(form,'文字已恢复，附件草稿不可用，请重新选择附件。',true);
  if(form._editing.id&&(draft.version!==latestVersion||draft.conflict_pending||form._bylineBodyConflict||form._relationshipContextConflict))await showSaveConflict(form);
}
async function clearEditorDraft(form) {if(!form?.dataset.draftKey)return;form._saved=true;localStorage.removeItem(form.dataset.draftKey);try{await draftFileOperation(form.dataset.draftKey,'delete');}catch{} }
function showDraftFile(form){const el=form.querySelector('[data-file-status]');if(el)el.innerHTML=form._draftFile?'待上传：'+esc(form._draftFile.name)+' · '+(form._draftFile.size/1024).toFixed(1)+' KB <button type="button" class="link-button" data-action="remove-draft-file">移除本次附件</button>':'';}
async function persistSelectedFile(form,file){form._draftFile=file||null;form._dirty=true;form._filePending=true;draftFileWrites++;showDraftFile(form);saveEditorDraft(form,true);try{if(file)await draftFileOperation(form.dataset.draftKey,'put',file);else await draftFileOperation(form.dataset.draftKey,'delete');form._fileSaveFailed=false;}catch{form._fileSaveFailed=true;draftStatus(form,'附件尚未保存为本机草稿，请先提交或重新选择文件。',true);}finally{form._filePending=false;draftFileWrites--;if(!form._fileSaveFailed)saveEditorDraft(form,true);}}
async function draftsPage(){
  const prefix=draftPrefix+encodeURIComponent(state.me.id)+':',drafts=[];
  for(let i=0;i<localStorage.length;i++){const key=localStorage.key(i);if(key.startsWith(prefix)){try{const d=JSON.parse(localStorage.getItem(key));if(d.user_id===state.me.id)drafts.push({key,...d});}catch{}}}
  drafts.sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
  return '<section class="workspace-drafts"><div class="page-heading"><h1>我的草稿</h1><p>仅当前账号在此浏览器中可见；提交后自动移除。</p></div><div class="stack">'+(drafts.map(d=>'<article class="panel draft-card"><div><h2>'+esc(d.title)+'</h2><p><span>'+esc(draftTypeLabel(d))+'</span> · <time datetime="'+esc(d.updated_at)+'">'+dateTime(d.updated_at)+'</time>'+(d.file?' · 含附件':'')+'</p></div><button class="button" data-action="open-draft" data-key="'+esc(d.key)+'">继续编辑</button></article>').join('')||empty('没有待处理的草稿','编辑后的未提交内容会保存在这里。','file'))+'</div></section>';
}

function sourcePicker(ids=[]) {
  return '<section class="wide">'+searchableSourceField('related_source_ids','关联来源（可多选）',ids,{multiple:true})+'<p class="form-help">在这些来源下展示同一份内容；发布机构另行登记。</p></section>';
}

function updateRecordInformationMode(form){
  const research=isResearchContent(form.elements.kind.value),metadata=form.querySelector('[data-record-basic-metadata]');
  form.querySelector('[data-record-required-help]').textContent=form.elements.kind.value==='directory_translation'?'请填写题名、编译者和覆盖范围；其余信息可按需要补充。':'题名必填；其余信息可按需要补充。';
  if(research&&form._intakePending&&form._informationKind!==form.elements.kind.value){form._intakeGeneration=(form._intakeGeneration||0)+1;form._intakePending=false;form.querySelector('[data-intake-status]').textContent='已切换内容类型，旧请求不会应用；已有填写内容保留。';}
  const target=form.querySelector(research?'[data-record-extra-metadata]':'[data-record-main-metadata]');
  if(metadata&&target&&metadata.parentElement!==target)target.append(metadata);
  const body=form.querySelector('[data-record-body]');
  if(body&&form._informationKind!==form.elements.kind.value)body.open=research||!!form.elements.body_html.value;
  const intake=form.querySelector('[data-intake-editor]');if(intake){intake.hidden=research&&!form.elements.intake_token.value;intake.querySelector('[data-intake-kind-warning]').hidden=!research;intake.querySelector('[data-intake-fetch]').disabled=research;}
  form._informationKind=form.elements.kind.value;
}

function updateRecordFormMode(form) {
  const kind=form.elements.kind.value,directory=kind==='directory_translation',personal=authorControlledKinds.has(kind),r=form._editing?.original||{};
  form.querySelector('[data-coverage]').hidden=!directory;form.elements.coverage.required=directory;form.elements.authors.required=directory;
  form.querySelector('[data-author-new]').hidden=!personal||!!r.id;
  const manages=canManageRecordAccess(r),proxy=personal&&!r.id&&form.elements.author_id.value!==state.me.id;
  form.querySelector('[data-access-fields]').hidden=directory||!manages;form.querySelector('[data-directory-rule]').hidden=!directory;
  const common=form.querySelector('[data-common-rule]');if(common)common.hidden=personal||directory;
  const grants=form.querySelector('.editor-grants');if(grants)grants.hidden=!personal&&form.elements.visibility.value!=='restricted';
  const grantsLabel=form.querySelector('[data-grants-label]');if(grantsLabel)grantsLabel.textContent=personal?'获授权共同编辑的成员':'获授权读取的成员';
  form.querySelectorAll('[name=editors]').forEach(el=>el.disabled=directory||!manages||proxy);
  form.elements.visibility.disabled=directory||!manages;
  form.querySelector('[data-acl-rule]').textContent=personal?'只有负责作者可以调整可见范围与编辑授权，管理员需获得作者授权。':kind==='research_note'?'所有可读成员共同编辑；原有可见范围仍由已确认负责作者管理。':'所有可读成员共同编辑；可见范围由提交者或资料管理员维护。';
  form.querySelector('#reference-section').hidden=!isResearchContent(kind);
  form.querySelector('[data-signature-label]').textContent=directory?'编译者 *':personalKinds.has(kind)?'作者 / 编译者署名':'原文作者';
  form.querySelector('[data-proxy-note]').textContent=proxy?'保存后等待负责作者本人确认；确认前不开放正文修订。':'本人提交直接生效。';
  if(typeof updateNoteSubjectMode==='function')updateNoteSubjectMode(form);if(typeof updateEvidenceMode==='function')updateEvidenceMode(form);if(form.dataset.readingNote){form.querySelector('[data-evidence-editor]')?.setAttribute('hidden','');form.querySelector('[data-evidence-picker]')?.setAttribute('hidden','');form.querySelector('#reference-section').hidden=true;}
}
async function workflowRecordForm(id='',kind='report',sourceId='',draftKey='',evidenceId='',initial={}) {
  const r=id?await api('/api/records/'+encodeURIComponent(id)):{kind,visibility:'shared',editors:[],related_source_ids:state.sources.some(s=>s.id===sourceId)?[sourceId]:[],linked_records:[],author_id:state.me.id,...initial};
  if(id&&!r.can_edit){await workflowOpenRecord(id);toast('当前账号没有正文编辑授权。');return;}
  state.editing={type:'record',id,version:r.version,owner_id:r.owner_id,editors:r.editors,visibility:r.visibility,original:r};state.links=r.linked_records||[];
  const html='<form data-form="record" class="workflow-form"><div class="form-grid">'
    +'<h3 class="wide record-info-heading">基本信息</h3><p class="wide form-help record-info-help" data-record-required-help>题名必填；其余信息可按需要补充。</p>'
    +inputField('title','题名 *',r.title,'',true)+selectField('kind','内容类型',kinds,r.kind)+'<div class="field"><label for="f-authors" data-signature-label>作者 / 编译者</label><input id="f-authors" name="authors" value="'+esc(r.authors)+'"></div>'
    +'<div class="wide" data-record-main-metadata><div class="form-grid" data-record-basic-metadata>'+inputField('published_on','发表 / 编译日期',r.published_on,'YYYY、YYYY-MM 或 YYYY-MM-DD')+inputField('publication_title','刊物名称 / 出处',r.publication_title)+inputField('volume','卷',r.volume)+inputField('issue','期',r.issue)+inputField('pages','页码 / 文章编号',r.pages)+inputField('issn','ISSN',r.issn,'多个标识按原题录保留')+inputField('doi','DOI',r.doi)+inputField('url','原文链接',r.url,'https://…',false,'url')+'</div></div>'
    +'<div class="wide" data-coverage>'+inputField('coverage','年份 / 卷期 / 覆盖范围 *',r.coverage,'例如：2026 年第 1–3 期',true)+'</div><div class="wide notice" data-directory-rule>目录译稿由全体有效成员共同编辑。</div>'
    +'<div class="wide" data-author-new>'+selectField('author_id','负责作者账号',Object.fromEntries(state.users.map(u=>[u.id,u.name])),r.author_id||state.me.id,'请选择负责作者')+'<p class="form-help" data-proxy-note></p></div>'
    +'<details class="wide record-form-section" data-record-body><summary>正文（选填）</summary><div class="form-grid section-gap">'+richEditor('body_html','正文',r.body_html)+'</div></details>'
    +'<details class="wide record-form-section" data-record-more><summary>更多信息（选填）</summary><div class="form-grid section-gap"><div class="wide" data-record-extra-metadata></div>'
    +inputField('original_title','原文题名',r.original_title,'',true)+textField('aliases','其他题名',r.aliases,'每行一个')+selectField('language','语言',languages,r.language,'暂不填写')
    +searchableSourceField('source_id','发布机构',r.source_id,{groups:['institution']})+searchableSourceField('serial_id','所属期刊 / 连续出版物',r.serial_id,{groups:['journal','publication']})+inputField('countries','研究的国家或地区',r.countries)+inputField('keywords','关键词',r.keywords)+textField('abstract','摘要与说明',r.abstract)+inputField('chinese_title','人工中文题名',r.chinese_title,'',true)+textField('chinese_abstract','人工中文摘要',r.chinese_abstract)+textField('original_catalogue','原目录 / 原文出处',r.original_catalogue,'刊物、年份、卷期、页码或目录链接')+sourcePicker(r.related_source_ids||[])+'</div></details>'
    +'<section class="wide" id="reference-section"><h3>关联原始资料</h3><div class="field section-gap"><label for="link-search">查找原文</label><input id="link-search" placeholder="输入题名或作者"><div id="link-results" class="link-results"></div><div id="selected-links" class="selected-links"></div></div>'+textField('unresolved_refs','尚未入库的原文出处',r.unresolved_refs)+'</section>'
    +'<details class="wide record-form-section" data-record-attachments '+(r.attachments?.length?'open':'')+'><summary>附件（选填）</summary><div class="attachment-editor section-gap">'+(r.attachments||[]).map(a=>'<p>'+icon('file')+' '+esc(a.name)+'</p>').join('')+'<label for="f-file">添加 Word、PDF 或文本文件（最多 20 MB）</label><input id="f-file" type="file" name="file" accept=".pdf,.docx,.txt,.md"><div data-file-status class="form-help"></div><label class="check-label"><input type="checkbox" name="sharing_confirmed">我确认本次附件可以在所选范围内共享。</label></div></details>'
    +'<section class="wide" data-access-fields><h3>可见范围与权限</h3><p class="form-help" data-common-rule>当前有权读取的有效成员共同编辑；共同编辑不改变可见范围。</p>'+selectField('visibility','可见范围',{shared:'中心成员可见',restricted:'限有读取权限的成员'},r.visibility)+'<fieldset class="editor-grants"><legend data-grants-label>获授权共同编辑的成员</legend>'
    +state.users.filter(u=>u.id!==(r.author_id||state.me.id)).map(u=>'<label class="check-label"><input type="checkbox" name="editors" value="'+esc(u.id)+'" '+(r.editors?.includes(u.id)?'checked':'')+'>'+esc(u.name)+(u.role==='admin'?'（管理员）':'')+'</label>').join('')+'</fieldset><p class="form-help" data-acl-rule></p></section>'
    +'</div><div class="form-error" role="alert"></div><div class="form-actions"><button type="button" class="button" data-action="close">关闭并保留草稿</button><button type="submit" class="button primary">'+(id?'保存修订':'保存内容')+'</button></div></form>';
  modal(id?'修订内容':'新建'+(kinds[kind]||'资料'),html);
  const form=document.querySelector('[data-form=record]');form._editing=state.editing;if(sourceId.startsWith('collection:'))form.dataset.collectionId=sourceId.slice(11);
  if(typeof prepareIntakeForm==='function')prepareIntakeForm(form);
  form._updateInformationMode=()=>updateRecordInformationMode(form);form._updateInformationMode();
  form.addEventListener('change',event=>{if(event.target.name==='kind')form._updateInformationMode();});
  if(id&&isResearchContent(r.kind))form.elements.kind.disabled=true;
  renderSelectedLinks();updateRecordFormMode(form);form.inert=true;
  // Keep inputs unavailable until their draft protection and references are ready.
  const preparing=document.createElement('fieldset');preparing.disabled=true;preparing.style.cssText='border:0;padding:0;margin:0;min-width:0';
  const grid=form.querySelector('.form-grid');grid.before(preparing);preparing.append(grid);
  const preparationStatus=document.createElement('p');preparationStatus.className='notice';preparationStatus.setAttribute('role','status');preparationStatus.textContent='正在准备编辑与草稿保护…';form.prepend(preparationStatus);
  form.querySelector('[type=submit]').disabled=true;
  try{if(state.schema>=4&&typeof enhanceEvidenceForm==='function')await enhanceEvidenceForm(form,r,evidenceId);await prepareNoteSubjectForm(form,r);await enableEditorDraft(form,form._editing,sourceId,draftKey);if(typeof uxPrepareReadingForm==='function')uxPrepareReadingForm(form,sourceId);}
  catch(error){form._evidenceLoadFailed=true;if(!form.dataset.draftKey)await enableEditorDraft(form,form._editing,sourceId,draftKey);form.querySelector('.form-error').textContent='关联证据未能读取，请关闭后重新打开。已有草稿仍保留。';form.querySelector('[type=submit]').disabled=true;throw error;}
  finally{preparing.replaceWith(...preparing.childNodes);preparationStatus.remove();form.inert=false;if(!form._evidenceLoadFailed&&!form._draftOffer)form.querySelector('[type=submit]').disabled=false;}
}
async function workflowSubmitRecord(form,data) {
  if(form._evidenceLoadFailed)throw new Error('请重新打开编辑器，完整读取关联证据后保存。');
  const edit=form._editing;syncRichForm(form);const values=Object.fromEntries(new FormData(form));delete values.file;
  values.kind=form.elements.kind.value;values.editors=data.getAll('editors');values.visibility=form.elements.visibility.value;
  if(edit.id&&!canManageRecordAccess(edit.original)){values.editors=edit.editors;values.visibility=edit.visibility;}
  if(values.kind==='directory_translation'){values.visibility='shared';values.editors=[];}
  if(!authorControlledKinds.has(values.kind)||edit.id)delete values.author_id;
  values.linked_ids=isResearchContent(values.kind)?state.links.map(r=>r.id):[];values.related_source_ids=data.getAll('related_source_ids');values.sharing_confirmed=data.get('sharing_confirmed')==='on';values.version=edit.version;
  if(values.kind==='research_note')values.research_subjects=noteSubjectValues(form);delete values.research_subject_choices;
  if(data.has('evidence_occurrence'))values.evidence_occurrence=Number(data.get('evidence_occurrence'));
  values.evidence_ids=['compilation','research_report'].includes(values.kind)?data.getAll('evidence_ids'):[];values.evidence_citations=values.evidence_ids.map(id=>({excerpt_id:id,stance:data.get('citation_stance_'+id)||'unclassified',claim_note:data.get('citation_claim_'+id)||''}));values.refresh_evidence=data.get('refresh_evidence')==='on';values.refresh_citations=data.get('refresh_citations')==='on';
  if(values.kind!=='research_note')for(const key of ['evidence_record_id','evidence_attachment_id','evidence_url','quote','translation','interpretation','locator'])delete values[key];
  if(form._conflictPending)throw new Error('请先对照最新版本，再继续保存。');
  if(form._draftOffer)throw new Error('请先选择恢复或舍弃已有草稿。');
  const file=form._draftFile||data.get('file');if(file?.size>20*1024*1024)throw new Error('附件超过 20 MB，请选择较小文件。');
  if(typeof intakeSaveValues==='function')intakeSaveValues(form,values);
  const multipart=new FormData();multipart.set('data',JSON.stringify(values));if(file?.size)multipart.set('file',file,file.name);
  form.dataset.saving='true';form.inert=true;
  try{
  const r=await api('/api/records'+(edit.id?'/'+encodeURIComponent(edit.id):''),{method:edit.id?'PUT':'POST',body:multipart});
  let topicError='';if(form.dataset.collectionId){try{await api('/api/collections/'+encodeURIComponent(form.dataset.collectionId)+'/items',{method:'POST',body:{record_id:r.id}});}catch(e){topicError=e.message;}}
  const readingOriginal=form.dataset.readingOriginalId;await clearEditorDraft(form);await loadLookups();if(typeof uxRefreshBackground==='function')await uxRefreshBackground();else{delete form.dataset.saving;form.inert=false;await route();}await workflowOpenRecord(readingOriginal||r.id);if(readingOriginal)document.querySelector('[data-reading-notes]')?.scrollIntoView({block:'start'});toast(topicError?'内容已保存，加入专题未完成：'+topicError:readingOriginal?'阅读说明已保存':'内容已保存');
  }finally{delete form.dataset.saving;if(form.isConnected)form.inert=false;}
}
function authorPanel(r) {
  const note=r.kind==='research_note';
  if(note&&r.author_confirmed)return '<section class="author-panel"><strong>当前有权读取的有效成员共同编辑</strong><span>原负责作者：'+esc(r.author_name)+'（已确认）</span></section>';
  if(!personalKinds.has(r.kind))return '';
  if(r.author_confirmed)return '<section class="author-panel"><strong>负责作者：'+esc(r.author_name)+'</strong><span>已由本人确认</span>'+(r.author_id===state.me.id?'<p>可在编辑中授权或撤销共同编辑成员。</p>':'')+'</section>';
  const canChoose=r.owner_id===state.me.id,canConfirm=r.author_id===state.me.id;
  const actions=canChoose?'<form data-form="author-assignment" data-record="'+esc(r.id)+'" data-version="'+r.version+'">'+selectField('author_id','负责作者',Object.fromEntries(state.users.map(u=>[u.id,u.name])),r.author_id||state.me.id,'请选择')+'<label class="check-label"><input type="checkbox" name="confirm">如选择本人，我确认由本人负责</label><div class="form-error" role="alert"></div><button type="submit" class="button tiny">保存作者安排</button></form>':canConfirm?'<button type="button" class="button primary" data-action="confirm-author" data-id="'+esc(r.id)+'" data-version="'+r.version+'">确认本人为负责作者</button>':'';
  return '<section class="author-panel notice"><h3>'+(note?'当前有权读取的有效成员共同编辑':r.author_id?'等待负责作者确认':'负责作者尚未确认')+'</h3><p>'+(note?'历史负责作者'+(r.author_name?'：'+esc(r.author_name):'')+'尚未确认；这不影响共同编辑。原有可见范围管理仍按负责作者规则维护。':r.author_id?esc(r.author_name)+' 确认后可修订正文。':'历史提交身份不代表作者身份，请明确确认。')+'</p>'
    +(note&&actions?'<details><summary>维护历史负责作者安排</summary>'+actions+'</details>':actions)+'</section>';
}
async function workflowOpenRecord(id) {
  const generation=modalGeneration,account=state.me?.id,hash=location.hash;
  const r=await api('/api/records/'+encodeURIComponent(id));if(generation!==modalGeneration||account!==state.me?.id||hash!==location.hash)return;state.detail={type:'record',data:r};if(typeof uxReadRecord==='function')return uxReadRecord(r);const raw=r.raw_json||{},research=isResearchContent(r.kind),hasEvidence=!!r.evidence_record_id||!!r.evidence_citations?.length;
  modal(kinds[r.kind]||'资料详情','<div class="row wrap">'+typeBadge(r.kind)+badge(r.status)+'<span class="badge neutral">'+(r.visibility==='shared'?'中心共享':'限授权成员')+'</span><span class="small muted">版本 '+r.version+'</span></div><h2 class="detail-title">'+esc(r.title)+'</h2>'+(r.original_title&&r.original_title!==r.title?'<p class="original-title">'+esc(r.original_title)+'</p>':'')
    +'<div class="detail-actions">'+(r.can_edit?linkButton(icon('edit')+' 编辑内容','edit-record',r.id,'button primary')+linkButton(icon('clock')+' 修改历史','history','record:'+r.id):'')+linkButton(icon('folder')+' 加入专题','add-to-collection',r.id)+'<button class="button tiny" data-action="favorite" data-id="'+esc(r.id)+'" data-saved="'+!!r.favorite+'">'+icon('star')+' '+(r.favorite?'取消收藏':'收藏')+'</button>'+(r.url?externalLink(r.url,'打开原文'):'')+(state.me.role==='admin'?linkButton('标记已核对','verify','record:'+r.id):'')+'</div>'
    +reviewPanel(r)+authorPanel(r)+'<dl class="detail-grid">'+detailPair(research?'作者 / 编译者署名':'原文作者',esc(r.authors))+(r.coverage?detailPair('覆盖范围',esc(r.coverage)):'')+detailPair('上传者',esc(r.owner_name))+detailPair('最近修改',r.last_modifier?esc(r.last_modifier.name)+' · '+dateTime(r.last_modifier.created_at):'暂无修订')+detailPair('日期',esc(r.published_on))+detailPair('稳定编号',esc(r.id))+'</dl>'
    +'<section class="detail-section"><h3>正文</h3>'+(r.body_html?'<div class="rich-prose">'+readRich(r.body_html)+'</div>':'<p class="muted">尚未填写网页正文。</p>')+'</section>'
    +(r.original_catalogue?'<section class="detail-section"><h3>原目录 / 原文出处</h3><p class="prose">'+esc(r.original_catalogue)+'</p></section>':'')
    +((r.related_source_ids||[]).length?'<section class="detail-section"><h3>关联来源</h3><div class="row wrap">'+r.related_source_ids.map(sourceName).join('')+'</div></section>':'')
    +'<section class="detail-section"><h3>附件</h3>'+((r.attachments||[]).map(a=>'<a class="detail-link" href="/api/attachments/'+encodeURIComponent(a.id)+'">'+icon('file')+' '+esc(a.name)+'<div class="mini-meta">'+(a.bytes/1024).toFixed(1)+' KB · '+dateTime(a.created_at)+'</div></a>').join('')||'<p class="muted">尚无平台附件。</p>')+'</section>'
    +'<details class="section-gap"><summary>题录、摘要与检索信息</summary><dl class="detail-grid section-gap">'+detailPair('其他题名',esc(r.aliases))+detailPair('发布机构',sourceName(r.source_id))+detailPair('所属期刊',sourceName(r.serial_id)||esc(r.publication_title))+detailPair('语言',esc(languageLabel(r.language)))+detailPair('研究对象',esc(r.countries))+detailPair('关键词',esc(r.keywords))+detailPair('DOI',esc(r.doi))+'</dl><p class="prose">'+esc(r.abstract)+'</p></details>'
    +(research&&(!hasEvidence||(r.linked_records||[]).length||r.unresolved_refs)?'<section class="detail-section"><h3>'+(hasEvidence?'其他关联资料':'关联原始资料')+'</h3>'+((r.linked_records||[]).map(x=>linkButton(esc(x.title),'detail',x.id,'detail-link')).join('')||(!hasEvidence&&!r.unresolved_refs?'<p class="muted">暂无关联原文。</p>':''))+(r.unresolved_refs?'<p class="prose section-gap">'+esc(r.unresolved_refs)+'</p>':'')+'</section>':'')
    +((r.cited_by||[]).length?'<section class="detail-section"><h3>引用此资料的成果</h3>'+r.cited_by.map(x=>linkButton(esc(x.title),'detail',x.id,'detail-link')).join('')+'</section>':'')
    +(raw.imported_attachments?.length?'<section class="detail-section"><h3>原资料库附件线索</h3>'+raw.imported_attachments.map(a=>externalLink(a.url,a.name)).join('')+'</section>':'')+(r.upstream_status?'<details class="section-gap"><summary>上游核查信息</summary><p class="prose">'+esc(r.upstream_status)+'</p></details>':'')+'<div data-workflow-record-extra></div>');
  if(state.schema>=4&&typeof evidenceDetail==='function')document.querySelector('[data-workflow-record-extra]').innerHTML=evidenceDetail(r);
}
async function showSaveConflict(form) {
  if(form.dataset.form==='byline')return bylineConflict(form);
  if(form.dataset.form==='relations')return relationshipConflict(form);
  const edit=form._editing||state.editing;if(!edit.id)return;if(edit.type==='person')return personConflict(form);if(edit.type==='collection'&&typeof collectionConflict==='function')return collectionConflict(form);
  form._conflictPending=true;form._dirty=true;saveEditorDraft(form,true);
  let latest;try{latest=await api('/api/'+(edit.type==='record'?'records':'sources')+'/'+encodeURIComponent(edit.id));}catch(error){form.querySelector('.form-error').textContent=error.message+' 当前草稿已保留。';return;}
  if(!form.isConnected||form.dataset.draftUser!==state.me?.id)return;
  if(latest.version===edit.version){form._conflictPending=false;saveEditorDraft(form,true);return;}
  form.querySelector('[data-conflict-panel]')?.remove();const panel=document.createElement('section');panel.className='conflict-panel';panel.dataset.conflictPanel='';
  const values=collectDraft(form).values,richName=edit.type==='record'?'body_html':'introduction_html';
  const labels={title:'题名',name:'名称',kind:'类型',authors:'作者 / 编译者',coverage:'覆盖范围',original_catalogue:'原文出处',aliases:'其他题名',original_title:'原题名',original_name:'原名称',published_on:'日期',volume:'卷',issue:'期',pages:'页码',issn:'ISSN',language:'语言',abstract:'摘要',chinese_title:'人工中文题名',chinese_abstract:'人工中文摘要',notes:'备注',url:'链接',website:'官网',catalogue_url:'目录入口',keywords:'关键词',countries:'研究对象',location:'所在地',country:'机构国家',country_evidence:'国家依据',host_id:'主办方',publisher_id:'出版方',host_evidence:'主办依据',international_status:'国际定位',international_evidence:'国际依据',related_source_ids:'关联来源',visibility:'可见范围',editors:'编辑授权'};
  const differences=Object.entries(labels).filter(([key])=>values[key]!==undefined&&JSON.stringify(values[key])!==JSON.stringify(latest[key]??''));
  const display=(key,value)=>['related_source_ids','editors'].includes(key)?(Array.isArray(value)?value:[]).map(id=>state.sources.find(s=>s.id===id)?.name||state.users.find(u=>u.id===id)?.name||id).join('；'):Array.isArray(value)?value.join('；'):String(value??'');
  panel.innerHTML='<h3>新版本已保存，你的输入仍保留</h3><p>当前编辑基于版本 '+esc(edit.version)+'，服务器为版本 '+latest.version+'。对照后可以继续整理，再保存为新修订。</p><details open><summary>对照最新版本</summary><div class="comparison-grid"><section><h4>你的正文草稿</h4><div class="rich-prose">'+readRich(values[richName])+'</div></section><section><h4>最新正文 · 版本 '+latest.version+'</h4><div class="rich-prose">'+readRich(latest[richName])+'</div></section></div><div class="table-scroll"><table class="comparison-table"><thead><tr><th>项目</th><th>你的输入</th><th>最新内容</th></tr></thead><tbody>'+differences.map(([key,label])=>'<tr><th>'+label+'</th><td>'+esc(display(key,values[key]))+'</td><td>'+esc(display(key,latest[key]))+'</td></tr>').join('')+'</tbody></table></div>'+(latest.attachments?'<p>最新附件：'+esc(latest.attachments.map(a=>a.name).join('；')||'无')+'</p>':'')+'</details>'+(edit.type==='record'?noteSubjectConflict(form,latest):'')+(edit.type==='record'&&!latest.can_edit?'<p class="error-text">当前账号已无编辑权限。草稿保留在“我的草稿”，不能提交。</p>':'<button type="button" class="button primary" data-action="accept-latest-version">我已对照，以新版本继续编辑</button>');
  panel._latest=latest;form.querySelector('.form-actions').before(panel);panel.scrollIntoView({block:'nearest'});
}
function enhanceSourceForm(form,draftKey='') {
  const s=state.editing.original;form.querySelector('#source-specific-fields').insertAdjacentHTML('beforebegin',richEditor('introduction_html','来源介绍',s.introduction_html)+textField('aliases','其他名称 / 别名',s.aliases,'每行一个'));
  form.querySelector('[data-action=close]').textContent='关闭并保留草稿';enableEditorDraft(form,state.editing,'',draftKey);
}

document.addEventListener('selectionchange',()=>{const editor=window.getSelection()?.anchorNode?.parentElement?.closest('[data-rich-input]');if(editor)editorSelection(editor);});
document.addEventListener('mousedown',event=>{if(event.target.closest('[data-rich-action]'))event.preventDefault();});
document.addEventListener('paste',event=>{const editor=event.target.closest('[data-rich-input]');if(!editor)return;event.preventDefault();const html=event.clipboardData.getData('text/html'),text=event.clipboardData.getData('text/plain');document.execCommand('insertHTML',false,html?cleanRich(html):esc(text).replace(/\n/g,'<br>'));const form=editor.closest('form');form._dirty=true;saveEditorDraft(form);});
document.addEventListener('drop',event=>{if(event.target.closest('[data-rich-input]'))event.preventDefault();});
document.addEventListener('input',event=>{
  const form=event.target.closest('form[data-draft-key]');if(form){form._dirty=true;saveEditorDraft(form);}
  if(event.target.matches('[data-source-picker-search]')){const q=event.target.value.trim().toLowerCase();event.target.closest('.source-picker').querySelectorAll('[data-source-choice]').forEach(el=>el.hidden=!el.dataset.sourceChoice.includes(q));}
});
document.addEventListener('change',event=>{
  const form=event.target.closest('form[data-draft-key]');if(!form)return;
  if(event.target.matches('[data-rich-format]')){const editor=event.target.closest('[data-rich-field]').querySelector('[data-rich-input]');restoreSelection(editor);document.execCommand('formatBlock',false,event.target.value);}
  if(form.dataset.form==='record'&&['kind','author_id','visibility'].includes(event.target.name))updateRecordFormMode(form);
  if(event.target.type==='file'){persistSelectedFile(form,event.target.files[0]);return;}
  form._dirty=true;saveEditorDraft(form);
});
document.addEventListener('submit',event=>{if(event.target.matches('form[data-draft-key]')){syncRichForm(event.target);event.target._links=state.links.slice();saveEditorDraft(event.target,true);}},true);
document.addEventListener('click',async event=>{
  const rich=event.target.closest('[data-rich-action]');if(rich){richAction(rich);return;}
  const button=event.target.closest('[data-action]');if(!button)return;const action=button.dataset.action,form=button.closest('form[data-draft-key]');
  try{
    if(action==='save-draft'){form._dirty=true;saveEditorDraft(form,true);}
    else if(action==='restore-draft')await restoreEditorDraft(form);
    else if(action==='discard-draft'){await clearEditorDraft(form);form._saved=false;form._draftOffer=null;form.querySelector('.draft-offer')?.remove();form.querySelector('[type=submit]').disabled=false;draftStatus(form,'旧草稿已舍弃');}
    else if(action==='open-draft'){const d=JSON.parse(localStorage.getItem(button.dataset.key)||'null');if(d?.user_id!==state.me.id)return;if(d.type==='collection'&&typeof researchCollectionForm==='function')await researchCollectionForm(d.id,button.dataset.key);else if(d.type==='byline')await bylineForm(d.id,button.dataset.key);else if(d.type==='employment'||d.type==='affiliation')await relationshipForm(d.type,d.id,d.specific.return_source,button.dataset.key);else if(d.type==='person')await personForm(d.id,button.dataset.key);else if(d.type==='source')await sourceForm(d.id,d.kind,button.dataset.key);else await workflowRecordForm(d.id,d.kind,d.context,button.dataset.key);}
    else if(action==='remove-draft-file'){form.elements.file.value='';await persistSelectedFile(form,null);}
    else if(action==='new-source-translation')await workflowRecordForm('','directory_translation',button.dataset.id);
    else if(action==='accept-latest-version'){const panel=button.closest('[data-conflict-panel]'),latest=panel._latest;form._editing.version=latest.version;form._editing.original=latest;form._editing.visibility=latest.visibility;form._editing.editors=latest.editors;form._conflictPending=false;panel.remove();form.querySelector('.form-error').textContent='';saveEditorDraft(form,true);toast('已采用最新版本号，当前输入仍保留，请检查后保存。');}
    else if(action==='confirm-author'){await api('/api/records/'+encodeURIComponent(button.dataset.id)+'/author',{method:'POST',body:{version:Number(button.dataset.version),author_id:state.me.id,confirm:true}});await workflowOpenRecord(button.dataset.id);toast('负责作者已确认');}
    if(['select-link','unlink','source-add-relation','source-remove-relation'].includes(action)){const current=currentEditorForm();if(current){current._links=state.links.slice();current._dirty=true;saveEditorDraft(current,true);}}
  }catch(error){if(form?.querySelector('.form-error'))form.querySelector('.form-error').textContent=error.message;else toast(error.message);}
});
document.addEventListener('submit',async event=>{
  const form=event.target;if(form.dataset.form!=='author-assignment')return;event.preventDefault();
  const error=form.querySelector('.form-error'),button=form.querySelector('[type=submit]');button.disabled=true;
  try{const author=form.elements.author_id.value,confirm=form.elements.confirm.checked;if(confirm&&author!==state.me.id)throw new Error('只能由负责作者本人确认；代交请取消本人确认。');await api('/api/records/'+encodeURIComponent(form.dataset.record)+'/author',{method:'POST',body:{version:Number(form.dataset.version),author_id:author,confirm}});await workflowOpenRecord(form.dataset.record);}catch(e){error.textContent=e.message;}finally{button.disabled=false;}
});
window.addEventListener('beforeunload',event=>{const form=currentEditorForm();if(form)saveEditorDraft(form);if(draftFileWrites||form?._draftFailed||form?._fileSaveFailed){event.preventDefault();event.returnValue='';}});
window.addEventListener('pagehide',()=>saveEditorDraft(currentEditorForm()));
document.addEventListener('visibilitychange',()=>{if(document.hidden)saveEditorDraft(currentEditorForm());});
const accountChannel = typeof BroadcastChannel==='function' ? new BroadcastChannel('zhihui-account') : null;
function announceAccount(){accountChannel?.postMessage({user:state.me?.id||null});}
if(accountChannel)accountChannel.onmessage=async event=>{
  if(event.data.user===(state.me?.id||null))return;
  saveEditorDraft(currentEditorForm());closeModal();state.loadId++;state.me=null;state.sources=[];state.collections=[];state.users=[];state.links=[];showLogin();
  try{const session=await api('/api/session');state.me=session.user;state.csrf=session.csrf;if(state.me){await loadLookups();await route();}}catch(error){toast(error.message);}
};
