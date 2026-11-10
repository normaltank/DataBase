'use strict';
// Fixed same-origin modules; failed loads are evicted so retry can recover.
window.visualLoader=(()=>{
  const names=new Set(['globe','timeline','network','flow','diff']),modules=new Map(),styles=new Map(),attempts=new Map();
  function style(name){
    if(styles.has(name))return styles.get(name);
    const css={network:'cytoscape-csp.css',flow:'flow.css',diff:'diff.css'}[name];
    if(!css)return Promise.resolve();
    const task=new Promise((resolve,reject)=>{
      const link=document.createElement('link');link.rel='stylesheet';link.href=clientAsset('/static/vendor/visual/'+css);
      if(name==='network')link.id='__________cytoscape_stylesheet';
      link.onload=resolve;link.onerror=()=>{link.remove();styles.delete(name);document.dispatchEvent(new Event('client:check'));reject(new Error('图形样式未能加载'));};document.head.append(link);
    });styles.set(name,task);return task;
  }
  function load(name){
    if(!names.has(name))return Promise.reject(new Error('未知可视化模块'));
    if(!modules.has(name))modules.set(name,Promise.all([style(name),import(clientAsset('/static/vendor/visual/'+name+'.js')+(attempts.get(name)?'&retry='+attempts.get(name):''))]).then(([,module])=>module).catch(error=>{modules.delete(name);attempts.set(name,(attempts.get(name)||0)+1);document.dispatchEvent(new Event('client:check'));throw error;}));
    return modules.get(name);
  }
  async function mount(name,container,options={},guard={}){
    const current=()=>container.isConnected&&(!guard.isCurrent||guard.isCurrent());
    const module=await load(name);if(!current())return null;
    const instance=await module.mount(container,{...options,assetRevision:document.querySelector('meta[name=client-revision]')?.content||''});
    if(!current()){instance?.dispose();return null;}return instance;
  }
  return Object.freeze({load,mount});
})();
