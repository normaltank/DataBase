import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';

// Natural Earth paths and prototype sphere/raycast mechanism, with application data only.
const sphere=(lon,lat,r=2.5)=>{const p=THREE.MathUtils.degToRad(lat),t=THREE.MathUtils.degToRad(lon);return new THREE.Vector3(r*Math.cos(p)*Math.sin(t),r*Math.sin(p),r*Math.cos(p)*Math.cos(t));};
function inside(x,y,ring){let yes=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){const [xi,yi]=ring[i],[xj,yj]=ring[j];if(((yi>y)!==(yj>y))&&x<(xj-xi)*(y-yi)/(yj-yi)+xi)yes=!yes;}return yes;}
export function mount(container,{geometry,snapshot,onSelect,onStatus=()=>{}}){
  const renderer=new THREE.WebGLRenderer({antialias:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio,1.7));renderer.setClearColor(0xf0f4f9);
  container.append(renderer.domElement);renderer.domElement.setAttribute('aria-label','可拖动旋转的研究对象国地球；使用下方文字国别按钮进行键盘筛选');
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(40,1,.1,100),resources=new Set(),lands=[],pins=[];
  const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=false;controls.enablePan=false;controls.minDistance=3.4;controls.maxDistance=15;controls.autoRotate=false;
  let disposed=false,frame=0,current=snapshot,down=null;
  const track=obj=>{if(obj.geometry)resources.add(obj.geometry);if(obj.material)resources.add(obj.material);scene.add(obj);return obj;};
  const draw=()=>{frame=0;if(!disposed&&!document.hidden&&container.isConnected&&container.clientWidth&&container.clientHeight)renderer.render(scene,camera);};
  const requestDraw=()=>{if(!disposed&&!frame&&!document.hidden)frame=requestAnimationFrame(draw);};
  const globe=track(new THREE.Mesh(new THREE.SphereGeometry(2.49,80,60),new THREE.MeshBasicMaterial({color:0xbdd0e4})));
  const features=geometry.features.map(f=>({...f,rings:[...f.path.matchAll(/M([^Z]+)Z/g)].map(m=>m[1].split('L').map(pair=>{const [x,y]=pair.split(',').map(Number);return [x/2.5-180,90-y/2.5];}))}));
  const line=(points,color,opacity=1)=>track(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color,transparent:opacity<1,opacity})));
  for(const feature of features){
    const material=new THREE.MeshBasicMaterial({color:0xd6e0eb,side:THREE.DoubleSide});resources.add(material);
    for(const ring of feature.rings){
      line(ring.map(([lon,lat])=>sphere(lon,lat,2.506)),0x718eac,.85);
      if(ring.length<4||Math.max(...ring.map(p=>p[0]))-Math.min(...ring.map(p=>p[0]))>180)continue;
      const contour=ring.slice(0,-1).map(([x,y])=>new THREE.Vector2(x,y)),faces=THREE.ShapeUtils.triangulateShape(contour,[]),geo=new THREE.BufferGeometry(),vertices=[];
      // Subdivide long spherical chords: broad planar triangles otherwise sink
      // through the ocean sphere and hide the data colour on large countries.
      const triangle=(a,b,c)=>{
        const lengths=[a.distanceToSquared(b),b.distanceToSquared(c),c.distanceToSquared(a)],longest=Math.max(...lengths);
        if(longest>.04){const edge=lengths.indexOf(longest);if(edge===0){const mid=a.clone().add(b).normalize().multiplyScalar(2.508);triangle(a,mid,c);triangle(mid,b,c);}else if(edge===1){const mid=b.clone().add(c).normalize().multiplyScalar(2.508);triangle(a,b,mid);triangle(a,mid,c);}else{const mid=c.clone().add(a).normalize().multiplyScalar(2.508);triangle(a,b,mid);triangle(mid,b,c);}return;}
        vertices.push(...a.toArray(),...b.toArray(),...c.toArray());
      };
      const points=contour.map(p=>sphere(p.x,p.y,2.508));for(const [a,b,c] of faces)triangle(points[a],points[b],points[c]);
      geo.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));track(new THREE.Mesh(geo,material));
    }
    lands.push({feature,material});
    if(feature.country){
      // Largest polygon's mean is a representative discovery point, never a source location.
      const ring=[...feature.rings].sort((a,b)=>b.length-a.length)[0];
      const position=ring.reduce((sum,[lon,lat])=>sum.add(sphere(lon,lat,1)),new THREE.Vector3()).normalize().multiplyScalar(2.56);
      const pin=track(new THREE.Mesh(new THREE.SphereGeometry(.045,12,8),new THREE.MeshBasicMaterial({color:0x174e9c})));pin.position.copy(position);pin.userData.country=feature.country;pins.push(pin);
    }
  }
  for(let lat=-60;lat<=60;lat+=30)line(Array.from({length:181},(_,i)=>sphere(i*2-180,lat,2.51)),0x9aafc5,.3);
  for(let lon=-180;lon<180;lon+=30)line(Array.from({length:91},(_,i)=>sphere(lon,i*2-90,2.51)),0x9aafc5,.3);
  function reset(view='europe'){camera.position.copy(view==='world'?sphere(10,10,10):sphere(22,45,8.6));controls.target.set(0,0,0);controls.update();requestDraw();}
  function update(data){current=data;const counts=new Map(data.countries.map(c=>[c.value,c.count])),max=Math.max(1,...counts.values()),selected=new Set(data.selected||[]);
    for(const {feature,material} of lands){const count=counts.get(feature.country)||0;material.color.set(selected.has(feature.country)?0xb47d00:!count?0xd6e0eb:count<=max/3?0xcadcf3:count<=2*max/3?0x6d99d2:0x174e9c);}
    for(const pin of pins){pin.visible=Boolean(counts.get(pin.userData.country)||selected.has(pin.userData.country));pin.material.color.set(selected.has(pin.userData.country)?0xb47d00:0x174e9c);pin.scale.setScalar(selected.has(pin.userData.country)?1.7:1);}
    requestDraw();
  }
  function resize(){if(disposed||!container.clientWidth||!container.clientHeight)return;renderer.setSize(container.clientWidth,container.clientHeight,false);camera.aspect=container.clientWidth/container.clientHeight;camera.updateProjectionMatrix();requestDraw();}
  const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();
  function pointerDown(e){down={x:e.clientX,y:e.clientY};}
  function pointerUp(e){if(!down||Math.hypot(e.clientX-down.x,e.clientY-down.y)>6)return;down=null;const rect=renderer.domElement.getBoundingClientRect();pointer.set((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);
    const hit=raycaster.intersectObject(globe)[0],pin=raycaster.intersectObjects(pins.filter(p=>p.visible))[0];
    if(pin&&(!hit||pin.distance<hit.distance+.08)){onSelect(pin.object.userData.country);return;}
    if(hit){const p=hit.point.clone().normalize(),lon=THREE.MathUtils.radToDeg(Math.atan2(p.x,p.z)),lat=THREE.MathUtils.radToDeg(Math.asin(p.y));const feature=features.find(f=>f.country&&f.rings.some(r=>inside(lon,lat,r)));if(feature)onSelect(feature.country);}
  }
  function visibility(){if(document.hidden){cancelAnimationFrame(frame);frame=0;}else requestDraw();}
  function lost(event){event.preventDefault();onStatus('地球图形不可用，可继续使用下方国别文字筛选并重试。');}
  controls.addEventListener('change',requestDraw);renderer.domElement.addEventListener('pointerdown',pointerDown);renderer.domElement.addEventListener('pointerup',pointerUp);renderer.domElement.addEventListener('webglcontextlost',lost);document.addEventListener('visibilitychange',visibility);
  const observer=new ResizeObserver(resize);observer.observe(container);reset();resize();update(current);
  return {update,resize,reset,dispose(){if(disposed)return;disposed=true;cancelAnimationFrame(frame);observer.disconnect();controls.dispose();document.removeEventListener('visibilitychange',visibility);renderer.domElement.removeEventListener('pointerdown',pointerDown);renderer.domElement.removeEventListener('pointerup',pointerUp);renderer.domElement.removeEventListener('webglcontextlost',lost);resources.forEach(r=>r.dispose());renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();}};
}
