import React from 'react';
import {createRoot} from 'react-dom/client';
import {ReactFlow, applyNodeChanges,Position,MarkerType} from '@xyflow/react';
import ELK from 'elkjs/lib/elk-api.js';

// A read-only local root. Stable IDs and relationships belong to the adapter;
// ELK only arranges them. No application forms or account data live here.
export function mount(container, options={}) {
  const root=createRoot(container);
  let disposed=false, generation=0, elk=null, timer=null, instance=null,cancelLayout=null;
  let snapshot={nodes:[],edges:[],...options.snapshot},nodes=[],edges=[],topology='';
  const stop=()=>{clearTimeout(timer);cancelLayout?.();cancelLayout=null;elk?.terminateWorker();elk=null;};
  const keydown=event=>{const node=event.target.closest('.react-flow__node');if(node&&(event.key==='Enter'||event.key===' ')){event.preventDefault();options.onSelect?.(node.dataset.id);}};
  container.addEventListener('keydown',keydown);
  function render(){
    if(disposed)return;
    const fitLineage=snapshot.layout==='lineage'&&nodes.length<=8&&container.clientWidth>=500&&!options.viewport;
    root.render(React.createElement(ReactFlow,{
      nodes,edges,nodesDraggable:false,nodesConnectable:false,edgesReconnectable:false,
      deleteKeyCode:null,minZoom:.15,maxZoom:2,preventScrolling:false,fitView:fitLineage,fitViewOptions:{padding:.025,minZoom:.98,maxZoom:1},
      onInit:value=>{instance=value;const first=nodes[0];if(options.viewport)value.setViewport(options.viewport,{duration:0});else if(first&&!fitLineage)value.setCenter(first.position.x+first.style.width/2,first.position.y+first.style.height/2,{zoom:1,duration:0});},
      onNodesChange:changes=>{nodes=applyNodeChanges(changes,nodes);render();},
      onNodeClick:(_,node)=>options.onSelect?.(node.id),
      // ResizeObserver remeasures this fixed-size slot after disclosure/route
      // transitions. React Flow's zero-size measurement is transient there.
      onError:code=>{if(code!=='004')options.onStatus?.('流程图暂不可用；可继续使用下方文字入口。');},
      ariaLabelConfig:{'node.a11yDescription.default':'按 Enter 选择并阅读此节点。','controls.zoomIn.ariaLabel':'放大流程图','controls.zoomOut.ariaLabel':'缩小流程图'},
      className:'visual-flow',
    }));
  }
  function select(){
    const selected=new Set(snapshot.selected||[]);
    nodes=nodes.map(node=>({...node,selected:selected.has(node.id)}));
    edges=edges.map(edge=>({...edge,label:selected.has(edge.source)||selected.has(edge.target)?edge.data.label:undefined,selected:selected.has(edge.source)&&selected.has(edge.target)}));
    render();
  }
  async function update(next){
    if(disposed)return;
    snapshot=next;
    const signature=JSON.stringify([next.nodes,next.edges,next.layout]);
    if(signature===topology){if(!elk)select();return;}
    topology=signature;
    const turn=++generation;stop();
    if(!next.nodes.length){nodes=[];edges=[];render();return;}
    let layout;
    try{
      layout=new ELK({workerFactory:()=>new Worker('/static/vendor/visual/elk-worker.min.js')});elk=layout;
      const compact=next.layout==='lineage',width=compact?150:216,height=compact?80:112;
      options.onStatus?.('正在排列实际记录…');
      const result=await Promise.race([
        layout.layout({id:'actual',layoutOptions:{'elk.algorithm':'layered','elk.direction':'RIGHT','elk.spacing.nodeNode':compact?'24':'36','elk.layered.spacing.nodeNodeBetweenLayers':compact?'40':'140'},
          children:next.nodes.map(node=>({id:node.id,width,height})),
          edges:next.edges.map(edge=>({id:edge.id,sources:[edge.source],targets:[edge.target]}))}),
        new Promise((_,reject)=>{cancelLayout=()=>reject(new Error('布局已取消'));timer=setTimeout(()=>reject(new Error('布局超时')),10000);}),
      ]);
      if(disposed||turn!==generation)return;
      const positions=new Map(result.children.map(node=>[node.id,node]));
      nodes=next.nodes.map(node=>({id:node.id,data:{label:node.label},position:{x:positions.get(node.id).x,y:positions.get(node.id).y},
        ariaLabel:node.label,sourcePosition:Position.Right,targetPosition:Position.Left,style:{width,height},selected:(snapshot.selected||[]).includes(node.id)}));
      const selected=new Set(snapshot.selected||[]);
      edges=next.edges.map(edge=>({...edge,data:{label:edge.label},label:selected.has(edge.source)||selected.has(edge.target)?edge.label:undefined,type:'smoothstep',ariaLabel:edge.description||edge.label,markerEnd:{type:MarkerType.ArrowClosed,color:'#58697b'}}));
      render();options.onStatus?.('流程图可点选；连线只表示标明的实际关系。');
    }catch(error){
      if(disposed||turn!==generation)return;
      topology='';nodes=[];edges=[];render();options.onStatus?.('流程图排列失败；可继续使用下方文字入口，或重试流程图。');
    }finally{
      if(elk===layout)stop();else layout?.terminateWorker();
    }
  }
  update(snapshot);
  return {update,resize(){if(!disposed)render();},
    getViewport(){return instance?.getViewport();},
    zoomIn(){instance?.zoomIn({duration:0});},zoomOut(){instance?.zoomOut({duration:0});},
    focusSelected(){const selected=nodes.find(node=>(snapshot.selected||[]).includes(node.id));if(selected)instance?.setCenter(selected.position.x+selected.style.width/2,selected.position.y+selected.style.height/2,{zoom:1,duration:0});},
    fit(){instance?.fitView({padding:.2,maxZoom:1,duration:0});},
    dispose(){if(disposed)return;disposed=true;generation++;stop();container.removeEventListener('keydown',keydown);root.unmount();container.replaceChildren();}};
}
