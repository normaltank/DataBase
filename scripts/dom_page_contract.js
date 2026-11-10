'use strict';
// Execute the page's ordered classic scripts, including the Jinja asset helper.
// This harness has no server; HTTP/browser checks cover rendered revision URLs.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
function loadPageScripts(dom){
  // jsdom destroys document synchronously; observers otherwise receive its
  // teardown mutations on a later microtask, after the browsing context is gone.
  const w=dom.window,Observer=w.MutationObserver,observers=new Set(),close=w.close.bind(w);
  w.MutationObserver=class extends Observer{constructor(callback){super(callback);observers.add(this);}};
  w.close=()=>{for(const observer of observers)observer.disconnect();observers.clear();close();};
  const root=path.join(__dirname,'..'),html=fs.readFileSync(path.join(root,'templates/index.html'),'utf8');
  const scripts=[...html.matchAll(/<script\b[^>]*\bsrc="([^"]+)"[^>]*>/g)];
  assert.ok(scripts.length,'page script entrypoints must be present');
  for(const [,src] of scripts){
    const asset=src.match(/^\{\{\s*asset\('([^']+)'\)\s*\}\}$/),literal=src.match(/^\/static\/([^?]+)(?:\?.*)?$/);
    assert.ok(asset||literal,'unsupported page script URL: '+src);
    const file=(asset||literal)[1];
    assert.ok(!file.includes('..')&&!path.isAbsolute(file),'local page asset required');
    vm.runInContext(fs.readFileSync(path.join(root,'static',file),'utf8'),dom.getInternalVMContext(),{filename:file});
  }
}
function jsonResponse(body,status=200,headers={}){
  return new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json',...headers}});
}
module.exports={loadPageScripts,jsonResponse};
