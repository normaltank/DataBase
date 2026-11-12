import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';

const RADIUS=2.508, LIFT=.067;
const sphere=(lon,lat,r=RADIUS)=>{
  const p=THREE.MathUtils.degToRad(lat),t=THREE.MathUtils.degToRad(lon);
  return new THREE.Vector3(r*Math.cos(p)*Math.sin(t),r*Math.sin(p),r*Math.cos(p)*Math.cos(t));
};
function inside(x,y,ring){
  let yes=false;
  for(let i=0,j=ring.length-1;i<ring.length;j=i++){
    const [xi,yi]=ring[i],[xj,yj]=ring[j];
    if(((yi>y)!==(yj>y))&&x<(xj-xi)*(y-yi)/(yj-yi)+xi)yes=!yes;
  }
  return yes;
}
// SVG paths already split the date line. Nesting keeps islands and interior holes
// (for example Lesotho) distinct without changing the supplied map's geography.
function polygons(rings){
  const area=r=>Math.abs(r.reduce((sum,p,i)=>{const q=r[(i+1)%r.length];return sum+p[0]*q[1]-q[0]*p[1];},0));
  const ordered=rings.filter(r=>r.length>=3).map(ring=>({ring,area:area(ring),parent:null,depth:0})).sort((a,b)=>b.area-a.area);
  for(let i=0;i<ordered.length;i++){
    const item=ordered[i];
    item.parent=ordered.slice(0,i).reverse().find(p=>inside(...item.ring[0],p.ring))||null;
    item.depth=item.parent?item.parent.depth+1:0;
  }
  return ordered.filter(p=>p.depth%2===0).map(p=>({contour:p.ring,holes:ordered.filter(h=>h.parent===p&&h.depth%2).map(h=>h.ring)}));
}
function surface(rings){
  const vertices=[];
  const triangle=(a,b,c)=>{
    const lengths=[a.distanceToSquared(b),b.distanceToSquared(c),c.distanceToSquared(a)];
    const longest=Math.max(...lengths);
    // Curved tops, including large countries: no long chord can sink into the sea.
    if(longest>.0225){
      const edge=lengths.indexOf(longest);
      if(edge===0){const m=a.clone().add(b).normalize().multiplyScalar(RADIUS);triangle(a,m,c);triangle(m,b,c);}
      else if(edge===1){const m=b.clone().add(c).normalize().multiplyScalar(RADIUS);triangle(a,b,m);triangle(a,m,c);}
      else{const m=c.clone().add(a).normalize().multiplyScalar(RADIUS);triangle(a,b,m);triangle(m,b,c);}
    }else vertices.push(...a.toArray(),...b.toArray(),...c.toArray());
  };
  for(const {contour,holes} of polygons(rings)){
    const vectors=r=>r.map(([x,y])=>new THREE.Vector2(x,y));
    const faces=THREE.ShapeUtils.triangulateShape(vectors(contour),holes.map(vectors));
    const points=[...contour,...holes.flat()].map(p=>sphere(...p));
    for(const [a,b,c] of faces)triangle(points[a],points[b],points[c]);
  }
  return new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));
}
function segments(rings,radius){
  const values=[],seen=new Set();
  for(const ring of rings)for(let i=0;i<ring.length;i++){
    const p=ring[i].join(','),q=ring[(i+1)%ring.length].join(','),key=p<q?p+'|'+q:q+'|'+p;
    if(seen.has(key))continue;seen.add(key);
    const a=sphere(...ring[i],radius),b=sphere(...ring[(i+1)%ring.length],radius);
    const steps=Math.max(1,Math.ceil(a.angleTo(b)/.035));
    for(let j=0;j<steps;j++)values.push(...a.clone().lerp(b,j/steps).normalize().multiplyScalar(radius).toArray(),...a.clone().lerp(b,(j+1)/steps).normalize().multiplyScalar(radius).toArray());
  }
  return values;
}
function strokeGeometry(rings,radius){
  const points=segments(rings,radius),starts=[],ends=[],corners=[],indices=[];
  for(let i=0;i<points.length;i+=6){
    const base=starts.length/3;
    for(const [along,side] of [[0,-1],[0,1],[1,-1],[1,1]]){
      starts.push(...points.slice(i,i+3));ends.push(...points.slice(i+3,i+6));corners.push(along,side);
    }
    indices.push(base,base+2,base+1,base+2,base+3,base+1);
  }
  return new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(starts,3))
    .setAttribute('endpoint',new THREE.Float32BufferAttribute(ends,3)).setAttribute('corner',new THREE.Float32BufferAttribute(corners,2)).setIndex(indices);
}
function walls(rings){
  const vertices=[];
  for(const ring of rings)for(let i=0;i<ring.length;i++){
    const a=sphere(...ring[i]),b=sphere(...ring[(i+1)%ring.length]);
    const steps=Math.max(1,Math.ceil(a.angleTo(b)/.035));
    for(let j=0;j<steps;j++){
      const lowA=a.clone().lerp(b,j/steps).normalize().multiplyScalar(RADIUS),lowB=a.clone().lerp(b,(j+1)/steps).normalize().multiplyScalar(RADIUS);
      const highA=lowA.clone().normalize().multiplyScalar(RADIUS+LIFT),highB=lowB.clone().normalize().multiplyScalar(RADIUS+LIFT);
      vertices.push(...lowA.toArray(),...lowB.toArray(),...highB.toArray(),...lowA.toArray(),...highB.toArray(),...highA.toArray());
    }
  }
  return new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));
}

export function mount(container,{geometry,snapshot,onSelect,onStatus=()=>{},viewState}){
  const renderer=new THREE.WebGLRenderer({antialias:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio,1.7));renderer.setClearColor(0xf0f4f9);
  const canvas=renderer.domElement;container.append(canvas);canvas.tabIndex=0;
  canvas.setAttribute('aria-label','研究对象国地球。方向键旋转，加减键缩放，Home复位；下方文字国别按钮可筛选资料。');
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(40,1,.1,100),resources=new Set(),lands=[],lineResolution=new THREE.Vector2(1,1);
  const controls=new OrbitControls(camera,canvas);
  controls.enableDamping=false;controls.enablePan=false;controls.minDistance=3.4;controls.maxDistance=15;controls.autoRotate=false;
  controls.rotateSpeed=.65;controls.zoomSpeed=.8;
  const motion=matchMedia('(prefers-reduced-motion: reduce)'),pointers=new Map();
  let disposed=false,frame=0,current=snapshot,hover=null,gesture=null,inertia=null,view='europe',lastMove=0;
  let velocity={theta:0,phi:0},previous=new THREE.Spherical();
  const track=obj=>{
    if(obj.geometry)resources.add(obj.geometry);if(obj.material)resources.add(obj.material);
    scene.add(obj);return obj;
  };
  function requestDraw(){if(!disposed&&!frame&&!document.hidden)frame=requestAnimationFrame(draw);}
  function draw(now){
    frame=0;
    if(disposed||document.hidden||!container.isConnected||!container.clientWidth||!container.clientHeight)return;
    if(inertia){
      const dt=Math.min(32,Math.max(0,now-inertia.last)),decay=Math.exp(-dt/55);
      rotate(inertia.theta*55*(1-decay),inertia.phi*55*(1-decay));
      inertia.theta*=decay;inertia.phi*=decay;inertia.last=now;
      if(now-inertia.start>=220||Math.hypot(inertia.theta,inertia.phi)<.00004)inertia=null;
    }
    renderer.render(scene,camera);
    if(inertia)requestDraw();
  }
  const globe=track(new THREE.Mesh(new THREE.SphereGeometry(2.49,80,60),new THREE.MeshBasicMaterial({color:0xbdd0e4})));
  const features=geometry.features.map(f=>({...f,rings:[...f.path.matchAll(/M([^Z]+)Z/g)].map(m=>{
    const ring=m[1].split('L').map(pair=>{const [x,y]=pair.split(',').map(Number);return [x/2.5-180,90-y/2.5];});
    // Closing duplicate vertices confuse triangulation and nesting.
    return ring.filter((p,i)=>!i||p[0]!==ring[i-1][0]||p[1]!==ring[i-1][1]).filter((p,i,a)=>i!==a.length-1||p[0]!==a[0][0]||p[1]!==a[0][1]);
  })}));
  function outline(rings,radius,width,color){
    // A square-capped segment uses two triangles and CSS-pixel offsets. The
    // globe always stays beyond the near plane, so it needs no generic line
    // clipping/dash/world-unit shader path or per-frame geometry rebuild.
    const material=new THREE.ShaderMaterial({
      uniforms:{resolution:{value:lineResolution},width:{value:width},color:{value:new THREE.Color(color)}},
      vertexShader:`attribute vec3 endpoint;attribute vec2 corner;uniform vec2 resolution;uniform float width;
        void main(){vec4 a=projectionMatrix*modelViewMatrix*vec4(position,1.0),b=projectionMatrix*modelViewMatrix*vec4(endpoint,1.0);
          vec2 delta=(b.xy/b.w-a.xy/a.w)*resolution;vec2 direction=delta/max(length(delta),0.0001);
          vec2 offset=(vec2(-direction.y,direction.x)*corner.y+direction*(corner.x*2.0-1.0))*width/resolution;
          gl_Position=mix(a,b,corner.x);gl_Position.xy+=offset*gl_Position.w;}`,
      fragmentShader:`uniform vec3 color;void main(){gl_FragColor=vec4(color,1.0);
        #include <colorspace_fragment>
      }`,side:THREE.DoubleSide,depthWrite:false
    });
    const stroke=track(new THREE.Mesh(strokeGeometry(rings,radius),material));
    stroke.renderOrder=width>2.5?1:2;return stroke;
  }
  const allRings=features.flatMap(f=>f.rings);
  // Triangle-expanded screen-space strokes work on WebGL implementations whose
  // native line width is fixed at one pixel. Light casing and dark core remain
  // legible against both dark data and pale no-data countries.
  outline(allRings,RADIUS+.006,2.7,0xfafcff);
  outline(allRings,RADIUS+.007,1.15,0x263d55);
  for(const feature of features){
    const material=new THREE.MeshBasicMaterial({color:0xd6e0eb,side:THREE.DoubleSide});
    const usable=feature.rings.filter(r=>Math.max(...r.map(p=>p[0]))-Math.min(...r.map(p=>p[0]))<=180);
    const top=track(new THREE.Mesh(surface(usable),material));
    top.userData.feature=feature;
    lands.push({feature,material,top,relief:null});
  }
  function relief(land){
    if(land.relief)return land.relief;
    const rings=land.feature.rings;
    const side=track(new THREE.Mesh(walls(rings),new THREE.MeshBasicMaterial({color:0x865515,side:THREE.DoubleSide})));
    side.userData.feature=land.feature;
    const casing=outline(rings,RADIUS+LIFT+.004,3.3,0xfff4d0),edge=outline(rings,RADIUS+LIFT+.005,1.7,0x65420e);
    land.relief={side,casing,edge};return land.relief;
  }
  const hoverEdge=outline([],RADIUS+.012,2.4,0x354ac5);hoverEdge.visible=false;
  function status(){
    const selected=current.selected||[],counts=new Map(current.countries.map(c=>[c.value,c.count]));
    const names=selected.map(code=>features.find(f=>f.country===code)?.name||code);
    const chosen=names.length?'已选：'+names.join('、')+'。':'';
    onStatus(chosen+(hover?'预览：'+hover.name+' · '+(counts.get(hover.country)||0)+' 条'+(!(counts.get(hover.country))?'，暂无资料':'')+'；释放选择。':chosen?'选中区域已抬升。':'拖动旋转，滚轮或双指缩放。'));
  }
  function paint(){
    const counts=new Map(current.countries.map(c=>[c.value,c.count])),max=Math.max(1,...counts.values()),selected=new Set(current.selected||[]);
    for(const land of lands){
      const {feature,material,top}=land,count=counts.get(feature.country)||0,chosen=Boolean(feature.country&&selected.has(feature.country));
      material.color.set(chosen?0xf2c45c:hover===feature?0x9fcbdf:!count?0xd6e0eb:count<=max/3?0xcadcf3:count<=2*max/3?0x6d99d2:0x174e9c);
      top.scale.setScalar(chosen?(RADIUS+LIFT)/RADIUS:1);
      if(chosen)relief(land);
      if(land.relief)for(const obj of Object.values(land.relief))obj.visible=chosen;
    }
    hoverEdge.visible=Boolean(hover&&!selected.has(hover.country));
    if(hoverEdge.visible&&hoverEdge.userData.feature!==hover){
      resources.delete(hoverEdge.geometry);hoverEdge.geometry.dispose();
      hoverEdge.geometry=strokeGeometry(hover.rings,RADIUS+.012);resources.add(hoverEdge.geometry);hoverEdge.userData.feature=hover;
    }
    status();requestDraw();
  }
  function update(data){current=data;paint();}
  function stop(){inertia=null;velocity={theta:0,phi:0};}
  function rotate(theta,phi){
    const spherical=new THREE.Spherical().setFromVector3(camera.position.clone().sub(controls.target));
    spherical.theta+=theta;spherical.phi=THREE.MathUtils.clamp(spherical.phi+phi,.03,Math.PI-.03);
    camera.position.setFromSpherical(spherical).add(controls.target);controls.update();requestDraw();
  }
  function zoom(step){
    stop();camera.position.sub(controls.target).multiplyScalar(Math.pow(1.16,-step));
    camera.position.clampLength(controls.minDistance,controls.maxDistance).add(controls.target);controls.update();requestDraw();
  }
  function reset(next='europe'){
    stop();view=next;camera.position.copy(next==='world'?sphere(10,10,10):sphere(22,45,8.6));controls.target.set(0,0,0);controls.update();requestDraw();
  }
  function resize(){
    if(disposed||!container.clientWidth||!container.clientHeight)return;
    renderer.setSize(container.clientWidth,container.clientHeight,false);lineResolution.set(container.clientWidth,container.clientHeight);camera.aspect=container.clientWidth/container.clientHeight;camera.updateProjectionMatrix();requestDraw();
  }
  const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2(),pickSphere=new THREE.Sphere(new THREE.Vector3(),RADIUS),hitPoint=new THREE.Vector3();
  function pick(event){
    const rect=canvas.getBoundingClientRect();
    if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)return null;
    pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);camera.updateMatrixWorld();raycaster.setFromCamera(pointer,camera);
    const hit=raycaster.ray.intersectSphere(pickSphere,hitPoint);
    // Raised silhouettes differ from the base projection. Pick their visible
    // top/wall first, while the near base intersection occludes the far side.
    const raised=lands.filter(land=>land.relief?.side.visible).flatMap(land=>[land.top,land.relief.side]);
    for(const obj of raised)obj.updateWorldMatrix(true,false);
    const raisedHit=raycaster.intersectObjects(raised,false)[0];
    if(raisedHit&&(!hit||raisedHit.distance<=camera.position.distanceTo(hit)+.0001))return raisedHit.object.userData.feature;
    if(!hit)return null;
    const p=hit.clone().normalize(),lon=THREE.MathUtils.radToDeg(Math.atan2(p.x,p.z)),lat=THREE.MathUtils.radToDeg(Math.asin(p.y));
    return features.find(f=>f.country&&f.rings.reduce((contained,r)=>contained!==inside(lon,lat,r),false))||null;
  }
  function pointerDown(event){
    stop();hover=null;paint();pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});
    if(pointers.size===1){gesture={id:event.pointerId,dragged:false,cancelled:event.button!==0,threshold:event.pointerType==='touch'?10:6,sampleTime:event.timeStamp,inputTime:event.timeStamp};previous.setFromVector3(camera.position.clone().sub(controls.target));}
    else if(gesture)gesture.cancelled=true;
    canvas.classList.add('is-dragging');
  }
  function pointerMove(event){
    const origin=pointers.get(event.pointerId);
    if(origin&&gesture){
      if(Math.hypot(event.clientX-origin.x,event.clientY-origin.y)>gesture.threshold)gesture.dragged=true;
      lastMove=event.timeStamp;gesture.inputTime=event.timeStamp;
    }else if(!pointers.size&&event.pointerType!=='touch'){
      const next=pick(event);if(next!==hover){hover=next;paint();}
    }
  }
  function changed(){
    if(pointers.size===1&&gesture&&!gesture.cancelled){
      const next=new THREE.Spherical().setFromVector3(camera.position.clone().sub(controls.target));
      const dt=Math.max(8,gesture.inputTime-gesture.sampleTime);
      velocity={theta:THREE.MathUtils.clamp(Math.atan2(Math.sin(next.theta-previous.theta),Math.cos(next.theta-previous.theta))/dt,-.004,.004),phi:THREE.MathUtils.clamp((next.phi-previous.phi)/dt,-.004,.004)};
      previous.copy(next);gesture.sampleTime=gesture.inputTime;
    }
    requestDraw();
  }
  function pointerUp(event){
    if(!pointers.has(event.pointerId))return;
    const sequence=gesture;pointers.delete(event.pointerId);
    if(pointers.size){if(gesture)gesture.cancelled=true;return;}
    gesture=null;canvas.classList.remove('is-dragging');
    if(!sequence||sequence.cancelled)return;
    if(sequence.dragged){
      if(!motion.matches&&event.timeStamp-lastMove<70&&Math.hypot(velocity.theta,velocity.phi)>.00004){const now=performance.now();inertia={...velocity,start:now,last:now};requestDraw();}
      return;
    }
    const feature=pick(event);
    if(feature){stop();onSelect(feature.country);}
  }
  function cancel(event){
    if(!pointers.has(event.pointerId))return;
    pointers.delete(event.pointerId);if(gesture)gesture.cancelled=true;
    if(!pointers.size){gesture=null;canvas.classList.remove('is-dragging');}
    stop();
    // OrbitControls listens for cancellation, not lost capture. Forward that
    // lifecycle event so its document listeners and pointer set also end.
    if(event.type==='lostpointercapture')canvas.dispatchEvent(new PointerEvent('pointercancel',{pointerId:event.pointerId,pointerType:event.pointerType,bubbles:true}));
  }
  function leave(){if(hover){hover=null;paint();}}
  function keydown(event){
    const turns={ArrowLeft:[.12,0],ArrowRight:[-.12,0],ArrowUp:[0,.12],ArrowDown:[0,-.12]};
    if(turns[event.key]){event.preventDefault();stop();rotate(...turns[event.key]);}
    else if(['+','=','-','_','Home'].includes(event.key)){event.preventDefault();event.key==='Home'?reset(view):zoom(['+','='].includes(event.key)?1:-1);}
  }
  function preference(){stop();requestDraw();}
  function visibility(){if(document.hidden){stop();for(const id of [...pointers.keys()])canvas.dispatchEvent(new PointerEvent('pointercancel',{pointerId:id,bubbles:true}));pointers.clear();gesture=null;canvas.classList.remove('is-dragging');cancelAnimationFrame(frame);frame=0;}else requestDraw();}
  function lost(event){event.preventDefault();stop();cancelAnimationFrame(frame);frame=0;onStatus('地球图形不可用，可继续使用下方国别文字筛选并重试。');}
  // Capture runs before OrbitControls and retains the whole sequence, including
  // document-captured releases, cancellation and the second finger joining.
  const events=[['pointerdown',pointerDown,true],['pointermove',pointerMove,true],['pointerup',pointerUp,true],['pointercancel',cancel,true],['lostpointercapture',cancel,true],['pointerleave',leave,false],['wheel',stop,true],['keydown',keydown,false],['webglcontextlost',lost,false]];
  for(const [name,handler,capture] of events)canvas.addEventListener(name,handler,capture);
  controls.addEventListener('change',changed);document.addEventListener('visibilitychange',visibility);motion.addEventListener('change',preference);
  const observer=new ResizeObserver(resize);observer.observe(container);reset();resize();update(current);
  function getViewState(){return {position:camera.position.toArray(),target:controls.target.toArray()};}
  function restoreViewState(value){if(!value)return;stop();camera.position.fromArray(value.position);controls.target.fromArray(value.target);controls.update();requestDraw();}
  restoreViewState(viewState);
  function dispose(){
    if(disposed)return;disposed=true;stop();pointers.clear();cancelAnimationFrame(frame);frame=0;observer.disconnect();controls.removeEventListener('change',changed);controls.dispose();
    document.removeEventListener('visibilitychange',visibility);motion.removeEventListener('change',preference);
    for(const [name,handler,capture] of events)canvas.removeEventListener(name,handler,capture);
    resources.forEach(r=>r.dispose());renderer.dispose();renderer.forceContextLoss();canvas.remove();
  }
  return {update,resize,reset,zoom,getViewState,restoreViewState,dispose};
}
