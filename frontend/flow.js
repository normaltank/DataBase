import React from 'react';
import {createRoot} from 'react-dom/client';
import {ReactFlow, applyNodeChanges,Position,MarkerType,Handle} from '@xyflow/react';
import ELK from 'elkjs/lib/elk-api.js';

// Material nodes use explicit semantic handles: version order stays on the
// submission axis; actual reviews stay inside their owning version column.
const MaterialNode=({data})=>React.createElement('div',{className:'material-flow-node'},data.label,
  React.createElement(Handle,{type:'target',position:Position.Left,id:'sequence-in'}),
  React.createElement(Handle,{type:'source',position:data.narrow?Position.Left:Position.Right,id:'sequence-out'}),
  React.createElement(Handle,{type:'source',position:Position.Bottom,id:'review-out'}),
  React.createElement(Handle,{type:'target',position:Position.Top,id:'review-in'}),
  React.createElement(Handle,{type:'source',position:Position.Right,id:'review-side-out'}),
  React.createElement(Handle,{type:'target',position:Position.Right,id:'review-side-in'}));
const materialNodeTypes={material:MaterialNode};

// A read-only local root. Stable IDs and relationships belong to the adapter;
// ELK only arranges them. No application forms or account data live here.
export function mount(container, options={}) {
  const root=createRoot(container);
  let disposed=false, generation=0, elk=null, timer=null, instance=null,cancelLayout=null,pendingFocus=false;
  let snapshot={nodes:[],edges:[],...options.snapshot},nodes=[],edges=[],topology='';
  const stop=()=>{clearTimeout(timer);cancelLayout?.();cancelLayout=null;elk?.terminateWorker();elk=null;};
  const keydown=event=>{if((event.key==='ContextMenu'||event.key==='F10'&&event.shiftKey)&&!event.target.closest('button,input,textarea,select,a')){const node=event.target.closest('.react-flow__node');if(node&&snapshot.nodes.find(n=>n.id===node.dataset.id)?.menuActions?.length){event.preventDefault();options.onMenu?.(node.dataset.id,event,node);return;}}if(event.target.closest('button,input,textarea,select,a'))return;const node=event.target.closest('.react-flow__node');if(node&&(event.key==='Enter'||event.key===' ')){event.preventDefault();options.onSelect?.(node.dataset.id);}};
  container.addEventListener('keydown',keydown);
  function focusSelected(){
    pendingFocus=true;if(disposed||elk||!instance)return;
    const selected=nodes.find(node=>(snapshot.selected||[]).includes(node.id));
    if(selected){instance.setCenter(selected.position.x+selected.style.width/2,selected.position.y+selected.style.height/2,{zoom:1,duration:0});pendingFocus=false;}
  }
  const showMenu=(node,event)=>{const anchor=event.currentTarget.closest('.react-flow__node');options.onMenu?.(node.id,event,anchor);};
  const label=node=>React.createElement('div',{className:'flow-node-object'},React.createElement('span',{},node.label),node.menuActions?.length?React.createElement('button',{type:'button',className:'object-more nodrag nopan','aria-label':'更多节点操作','aria-haspopup':'menu','aria-expanded':false,'data-object-more':'',onClick:event=>{event.stopPropagation();showMenu(node,event);},onKeyDown:event=>{if(event.key==='F10'&&event.shiftKey||event.key==='ContextMenu'){event.preventDefault();event.stopPropagation();showMenu(node,event);}}},React.createElement('svg',{viewBox:'0 0 24 24','aria-hidden':true},...[5,12,19].map(x=>React.createElement('circle',{key:x,cx:x,cy:12,r:1.5})))):null,node.actions?.length?React.createElement('div',{className:'flow-node-actions nodrag nopan'},...node.actions.map(action=>React.createElement('button',{key:action.id,type:'button',className:'button tiny '+(action.primary?'primary':''),disabled:action.disabled,onClick:event=>{event.stopPropagation();options.onAction?.(node.id,action.id);},onKeyDown:event=>{event.stopPropagation();if(event.key===' '){event.preventDefault();if(!event.repeat)event.currentTarget.click();}}},action.label))):null);
  function render(){
    if(disposed)return;
    const material=snapshot.layout==='material-lineage',fitLineage=snapshot.layout==='lineage'&&nodes.length<=8&&container.clientWidth>=500&&!options.viewport;
    root.render(React.createElement(ReactFlow,{
      nodes,edges,nodeTypes:material?materialNodeTypes:undefined,nodesDraggable:false,nodesConnectable:false,edgesReconnectable:false,
      deleteKeyCode:null,minZoom:.15,maxZoom:2,preventScrolling:false,fitView:fitLineage,fitViewOptions:snapshot.layout==='material-lineage'?{padding:.12,minZoom:.15,maxZoom:1}:{padding:.025,minZoom:.98,maxZoom:1},
      onInit:value=>{instance=value;const first=nodes.find(node=>(snapshot.selected||[]).includes(node.id))||nodes[0];if(options.viewport)value.setViewport(options.viewport,{duration:0});else if(material)value.setViewport({x:0,y:0,zoom:1},{duration:0});else if(first&&!fitLineage)value.setCenter(first.position.x+first.style.width/2,first.position.y+first.style.height/2,{zoom:1,duration:0});if(pendingFocus)focusSelected();},
      onNodesChange:changes=>{nodes=applyNodeChanges(changes,nodes);render();},
      onNodeClick:(_,node)=>options.onSelect?.(node.id),
      onNodeContextMenu:(event,node)=>{if(event.target.closest('a,input,textarea,select')||window.getSelection()?.toString())return;if(node.data.label&&snapshot.nodes.find(n=>n.id===node.id)?.menuActions?.length){event.preventDefault();options.onMenu?.(node.id,event,event.target.closest('.react-flow__node'));}},
      // ResizeObserver remeasures this fixed-size slot after disclosure/route
      // transitions. React Flow's zero-size measurement is transient there.
      onError:code=>{if(code!=='004')options.onStatus?.('流程图暂不可用；可继续使用下方文字入口。');},
      ariaLabelConfig:{'node.a11yDescription.default':'按 Enter 选择并阅读此节点。','controls.zoomIn.ariaLabel':'放大流程图','controls.zoomOut.ariaLabel':'缩小流程图'},
      className:'visual-flow',
    }));
  }
  function select(){
    const selected=new Set(snapshot.selected||[]);
    nodes=nodes.map(node=>({...node,data:{...node.data,label:label(snapshot.nodes.find(item=>item.id===node.id)||node)},selected:selected.has(node.id)}));
    edges=edges.map(edge=>({...edge,label:selected.has(edge.source)||selected.has(edge.target)?edge.data.label:undefined,selected:selected.has(edge.source)&&selected.has(edge.target)}));
    render();
  }
  async function update(next){
    if(disposed)return;
    snapshot=next;
    const narrow=next.layout==='material-lineage'&&container.clientWidth<700;
    const signature=JSON.stringify([narrow,next.nodes.map(({id,label,actions,menuActions})=>({id,label,actions:actions?.map(action=>action.id),menuActions:menuActions?.map(action=>action.id)})),next.edges,next.layout,next.groups]);
    if(signature===topology){if(!elk)select();return;}
    topology=signature;
    const turn=++generation;stop();
    if(!next.nodes.length){nodes=[];edges=[];render();options.onStatus?.('尚无图节点；实际记录出现后再显示流程图。');return;}
    let layout;
    try{
      const material=next.layout==='material-lineage',compact=material||next.layout==='lineage',width=material?176:compact?138:216,height=material?88:compact?80:112;
      let result;
      if(material){
        // Coordinates come from actual version membership, never DAG layers.
        // No review-to-next-version edge or synthetic approval event is added.
        let nextY=24;const children=[];
        for(const [column,group] of (next.groups||[]).entries()){
          const x=narrow?32:24+column*(width+80),top=narrow?nextY:24;
          for(const [row,id] of group.nodes.entries())children.push({id,x,y:top+row*(height+44),width,height});
          nextY=top+group.nodes.length*(height+44)+48;
        }
        result={children};
      }else{
        layout=new ELK({workerFactory:()=>new Worker('/static/vendor/visual/elk-worker.min.js'+(options.assetRevision?'?v='+encodeURIComponent(options.assetRevision):''))});elk=layout;
        options.onStatus?.('正在排列实际记录…');
        result=await Promise.race([
          layout.layout({id:'actual',layoutOptions:{'elk.algorithm':'layered','elk.direction':'RIGHT','elk.spacing.nodeNode':compact?'18':'36','elk.layered.spacing.nodeNodeBetweenLayers':compact?'24':'140'},
            children:next.nodes.map(node=>({id:node.id,width:node.actions?.length?224:width,height:node.actions?.length?156:height})),
            edges:next.edges.map(edge=>({id:edge.id,sources:[edge.source],targets:[edge.target]}))}),
          new Promise((_,reject)=>{cancelLayout=()=>reject(new Error('布局已取消'));timer=setTimeout(()=>reject(new Error('布局超时')),10000);}),
        ]);
      }
      if(disposed||turn!==generation)return;
      const positions=new Map(result.children.map(node=>[node.id,node]));
      if(compact)container.style.height=(material?Math.max(440,...result.children.map(node=>node.y+node.height+32)):Math.min(380,Math.max(210,...result.children.map(node=>node.y+node.height+32))))+'px';
      nodes=next.nodes.map(node=>({id:node.id,type:material?'material':undefined,data:{label:label(snapshot.nodes.find(item=>item.id===node.id)||node),narrow},position:{x:positions.get(node.id).x,y:positions.get(node.id).y},
        ariaLabel:node.label,sourcePosition:narrow?Position.Bottom:Position.Right,targetPosition:narrow?Position.Top:Position.Left,style:{width:positions.get(node.id).width,height:positions.get(node.id).height},selected:(snapshot.selected||[]).includes(node.id)}));
      const selected=new Set(snapshot.selected||[]);
      edges=next.edges.map(edge=>({...edge,sourceHandle:material?(edge.relation==='sequence'?'sequence-out':edge.parallel?'review-side-out':'review-out'):undefined,targetHandle:material?(edge.relation==='sequence'?'sequence-in':edge.parallel?'review-side-in':'review-in'):undefined,data:{label:edge.label},label:selected.has(edge.source)||selected.has(edge.target)?edge.label:undefined,type:'smoothstep',ariaLabel:edge.description||edge.label,markerEnd:{type:MarkerType.ArrowClosed,color:'#58697b'}}));
      render();if(material)instance?.setViewport({x:0,y:0,zoom:1},{duration:0});options.onStatus?.('');
    }catch(error){
      if(disposed||turn!==generation)return;
      topology='';nodes=[];edges=[];render();options.onStatus?.('流程图排列失败；可继续使用下方文字入口，或重试流程图。');
    }finally{
      if(elk===layout)stop();else layout?.terminateWorker();
      if(pendingFocus&&!disposed)requestAnimationFrame(focusSelected);
    }
  }
  update(snapshot);
  return {update,resize(){if(!disposed){if(snapshot.layout==='material-lineage')update(snapshot);else render();}},
    getViewport(){return instance?.getViewport();},
    zoomIn(){instance?.zoomIn({duration:0});},zoomOut(){instance?.zoomOut({duration:0});},
    focusSelected,
    fit(){if(snapshot.layout==='material-lineage')instance?.setViewport({x:0,y:0,zoom:1},{duration:0});else instance?.fitView({padding:.2,maxZoom:1,duration:0});},
    dispose(){if(disposed)return;disposed=true;generation++;stop();container.removeEventListener('keydown',keydown);root.unmount();container.replaceChildren();}};
}
