import cytoscape from 'cytoscape';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';

// One application snapshot owns identities and edges in both views. Geometry,
// on-demand drawing and picking adapt the licensed discovery prototype.
export function mount(container,{snapshot,onSelect=()=>{},onStatus=()=>{},mode='plane',viewState}){
  let current=snapshot,view=null,disposed=false;
  const cameras=structuredClone(viewState||{});
  function createPlane(){
    let atHome=cameras.plane?.atHome!==false;
    const labels=[];
    const cy=cytoscape({container,elements:[],layout:{name:'preset'},wheelSensitivity:.2,
      minZoom:.15,maxZoom:4,style:[
        {selector:'node',style:{'background-color':'#174e9c','width':24,'height':24}},
        {selector:'node[type="person"]',style:{'background-color':'#795200'}},
        {selector:'node[type="source"]',style:{'background-color':'#24634f'}},
        {selector:'node:selected',style:{'border-width':4,'border-color':'#b47d00'}},
        {selector:'edge',style:{'width':1.5,'line-color':'#718eac','target-arrow-color':'#718eac','target-arrow-shape':'triangle','curve-style':'bezier'}}]});
    cy.on('tap','node',e=>onSelect(e.target.id()));
    cy.on('dragpan scrollzoom pinchzoom',()=>{atHome=false;});
    function placeLabels(){for(const {key,el} of labels){const p=cy.getElementById(key).renderedPosition(),half=Math.min(65,container.clientWidth*.2);el.style.left=Math.max(half,Math.min(container.clientWidth-half,p.x))+'px';el.style.top=p.y+'px';}}
    cy.on('pan zoom resize render',placeLabels);
    function update(data){
      const previous=cy.nodes().length>0,pan=cy.pan(),zoom=cy.zoom();
      cy.elements().remove();
      labels.splice(0).forEach(l=>l.el.remove());
      cy.add([...data.nodes.map((n,i)=>({data:{id:n.key,label:n.name,type:n.type},position:position(i,data.nodes.length,105)})),
        ...data.edges.map(e=>({data:{id:e.key,source:e.from,target:e.to}}))]);
      cy.getElementById(data.selected).select();
      for(const node of data.nodes){const el=document.createElement('span');el.className='record-network-label';el.textContent=node.name;el.setAttribute('aria-hidden','true');container.append(el);labels.push({key:node.key,el});}
      if(previous){cy.zoom(zoom);cy.pan(pan);}else if(cameras.plane){cy.zoom(cameras.plane.zoom);cy.pan(cameras.plane.pan);}else cy.fit(undefined,60);
      placeLabels();
    }
    return {update,getViewState(){return {zoom:cy.zoom(),pan:cy.pan(),atHome};},resize(){cy.resize();if(atHome)cy.fit(undefined,40);placeLabels();},reset(){atHome=true;cy.fit(undefined,40);},dispose(){cameras.plane={zoom:cy.zoom(),pan:cy.pan(),atHome};cy.destroy();labels.splice(0).forEach(l=>l.el.remove());}};
  }
  function createSpace(){
    const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.7));renderer.setClearColor(0xf0f4f9);container.append(renderer.domElement);
    renderer.domElement.setAttribute('aria-label','主体空间关系图；可拖动旋转、平移、缩放，文字列表提供相同选择');
    const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(40,1,.1,100);
    const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=false;controls.autoRotate=false;controls.minDistance=4;controls.maxDistance=40;
    const resources=new Set(),objects=[],labels=[];let frame=0,down=null,closed=false,atHome=cameras.space?.atHome!==false;
    const track=o=>{scene.add(o);objects.push(o);if(o.geometry)resources.add(o.geometry);if(o.material)resources.add(o.material);return o;};
    function clear(){for(const o of objects)scene.remove(o);objects.length=0;resources.forEach(r=>r.dispose());resources.clear();labels.splice(0).forEach(l=>l.el.remove());}
    function draw(){frame=0;if(closed||document.hidden||!container.isConnected||!container.clientWidth)return;renderer.render(scene,camera);
      for(const {object,el} of labels){const p=object.position.clone().project(camera),half=Math.min(65,container.clientWidth*.2);el.hidden=Math.abs(p.z)>1;el.style.left=Math.max(half,Math.min(container.clientWidth-half,(p.x+1)*container.clientWidth/2))+'px';el.style.top=((-p.y+1)*container.clientHeight/2)+'px';}
    }
    const requestDraw=()=>{if(!closed&&!document.hidden&&!frame)frame=requestAnimationFrame(draw);};
    function reset(){atHome=true;camera.position.set(0,1,Math.max(14,10/camera.aspect));controls.target.set(0,0,0);controls.update();requestDraw();}
    function update(data){clear();const nodes=new Map();
      data.nodes.forEach((n,i)=>{const p=position(i,data.nodes.length,3.4),object=track(new THREE.Mesh(n.key===data.center?new THREE.BoxGeometry(.4,.4,.4):new THREE.SphereGeometry(.22,16,12),new THREE.MeshBasicMaterial({color:n.key===data.selected?0xb47d00:n.type==='person'?0x795200:n.type==='source'?0x24634f:0x174e9c})));
        object.position.set(p.x,p.y,i===0?0:Math.sin(i*2.4)*1.3);object.userData.key=n.key;nodes.set(n.key,object);
        const el=document.createElement('span');el.className='record-network-label';el.textContent=n.name;el.dataset.networkLabel=n.key;el.setAttribute('aria-hidden','true');container.append(el);labels.push({object,el});
      });
      for(const e of data.edges){const a=nodes.get(e.from),b=nodes.get(e.to);if(!a||!b)continue;const direction=b.position.clone().sub(a.position),arrow=new THREE.ArrowHelper(direction.clone().normalize(),a.position,direction.length()-.25,0x718eac,.18,.1);track(arrow);for(const o of [arrow.line,arrow.cone]){o.geometry=o.geometry.clone();resources.add(o.geometry);resources.add(o.material);}}
      requestDraw();
    }
    function resize(){if(closed||!container.clientWidth||!container.clientHeight)return;renderer.setSize(container.clientWidth,container.clientHeight,false);camera.aspect=container.clientWidth/container.clientHeight;camera.updateProjectionMatrix();if(atHome)reset();requestDraw();}
    const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();
    const pointerDown=e=>{down={x:e.clientX,y:e.clientY};};
    const pointerUp=e=>{if(!down)return;const start=down;down=null;if(Math.hypot(e.clientX-start.x,e.clientY-start.y)>6)return;const r=renderer.domElement.getBoundingClientRect();pointer.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);raycaster.setFromCamera(pointer,camera);const hit=raycaster.intersectObjects([...labels.map(l=>l.object)])[0];if(hit)onSelect(hit.object.userData.key);};
    const visibility=()=>{if(document.hidden){cancelAnimationFrame(frame);frame=0;}else requestDraw();};
    const lost=e=>{e.preventDefault();onStatus('空间图形不可用，请切换平面关系或使用下方文字，并可重试。');};
    controls.addEventListener('start',()=>{atHome=false;});controls.addEventListener('change',requestDraw);renderer.domElement.addEventListener('pointerdown',pointerDown);renderer.domElement.addEventListener('pointerup',pointerUp);renderer.domElement.addEventListener('webglcontextlost',lost);document.addEventListener('visibilitychange',visibility);
    if(cameras.space){camera.position.fromArray(cameras.space.position);controls.target.fromArray(cameras.space.target);controls.update();}else reset();
    return {update,resize,reset,getViewState(){return {position:camera.position.toArray(),target:controls.target.toArray(),atHome};},dispose(){if(closed)return;closed=true;cameras.space={position:camera.position.toArray(),target:controls.target.toArray(),atHome};cancelAnimationFrame(frame);clear();controls.dispose();document.removeEventListener('visibilitychange',visibility);renderer.domElement.removeEventListener('pointerdown',pointerDown);renderer.domElement.removeEventListener('pointerup',pointerUp);renderer.domElement.removeEventListener('webglcontextlost',lost);renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();}};
  }
  function setMode(next){if(disposed)return;view?.dispose();view=null;mode=next;
    if(document.hidden)return;
    try{view=mode==='space'?createSpace():createPlane();view.update(current);view.resize();onStatus('');}catch(error){view?.dispose();view=null;container.replaceChildren();onStatus('图形未能加载，可继续使用下方文字关系，或重试图形。');throw error;}
  }
  function update(data){if(disposed)return;current=data;view?.update(data);}
  const observer=new ResizeObserver(()=>view?.resize());observer.observe(container);
  const visibility=()=>{if(document.hidden)dispose();};
  document.addEventListener('visibilitychange',visibility);
  try{setMode(mode);}catch(error){observer.disconnect();document.removeEventListener('visibilitychange',visibility);throw error;}
  function getViewState(){return {...cameras,[mode]:view?.getViewState()||cameras[mode]};}
  function dispose(){if(disposed)return;disposed=true;observer.disconnect();document.removeEventListener('visibilitychange',visibility);view?.dispose();view=null;container.replaceChildren();}
  return {update,setMode,getViewState,resize(){view?.resize();},reset(){view?.reset();},dispose};
}
function position(index,total,radius){if(!index)return {x:0,y:0};const angle=(index-1)*Math.PI*2/Math.max(1,total-1)-Math.PI/2;return {x:Math.cos(angle)*radius,y:Math.sin(angle)*radius};}
