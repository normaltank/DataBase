import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {init, use} from 'echarts/core';
import {BarChart} from 'echarts/charts';
import {GridComponent, TooltipComponent, BrushComponent, ToolboxComponent, DataZoomComponent} from 'echarts/components';
import {CanvasRenderer} from 'echarts/renderers';

use([BarChart, GridComponent, TooltipComponent, BrushComponent, ToolboxComponent, DataZoomComponent, CanvasRenderer]);

// Adapted from the MIT discovery prototype: instanced boxes, OrbitControls,
// instance-ID picking and demand-only drawing. No prototype data is imported.
export function mount(container, {snapshot, onRange=()=>{}, onSelect=()=>{}, onStatus=()=>{}}={}) {
  let disposed=false, current=snapshot, lens=null, updating=false;
  const overview=document.createElement('div');overview.className='material-time-chart';overview.setAttribute('role','img');overview.setAttribute('aria-label','年份概览；可刷选范围，或使用起止年输入');
  container.append(overview);
  const chart=init(overview,null,{renderer:'canvas'});
  function bounds(){const years=current.years.map(x=>Number(x.year));return years.length?[Math.min(...years),Math.max(...years)]:null;}
  function range(start,end){const domain=bounds();if(!domain||disposed||updating)return;onRange(Math.max(domain[0],Math.floor(start)),Math.min(domain[1],Math.ceil(end)));}
  chart.on('brushEnd',event=>{const area=event.areas?.[0];if(area?.coordRange)range(...area.coordRange);});
  chart.on('datazoom',event=>{const value=event.batch?.[0]||event,domain=bounds();if(!domain)return;range(value.startValue??domain[0]+(domain[1]-domain[0])*(value.start??0)/100,value.endValue??domain[0]+(domain[1]-domain[0])*(value.end??100)/100);});
  function update(data){if(disposed)return;current=data;const domain=bounds();updating=true;
    chart.setOption({animation:false,textStyle:{fontSize:14,fontFamily:'Microsoft YaHei, sans-serif',color:'#243347'},
      grid:{left:54,right:24,top:48,bottom:72},
      tooltip:{renderMode:'richText',trigger:'axis',confine:true,valueFormatter:value=>value+' 条'},
      toolbox:{right:12,feature:{brush:{type:['lineX','clear'],title:{lineX:'刷选年份范围',clear:'清除刷选'}}}},
      brush:{xAxisIndex:0,brushMode:'single',throttleType:'debounce',throttleDelay:100},
      dataZoom:[{type:'inside',xAxisIndex:0,filterMode:'none'},{type:'slider',xAxisIndex:0,filterMode:'none',bottom:8,height:24}],
      xAxis:{type:'value',min:domain?(domain[0]===domain[1]?domain[0]-.5:domain[0]):0,max:domain?(domain[0]===domain[1]?domain[1]+.5:domain[1]):1,minInterval:1,axisLabel:{formatter:value=>Number.isInteger(value)?String(value):''}},
      yAxis:{type:'value',minInterval:1,name:'资料数'},
      series:[{type:'bar',barMaxWidth:32,itemStyle:{color:'#174e9c'},data:data.years.map(x=>[Number(x.year),x.count])}]},true);
    chart.dispatchAction({type:'takeGlobalCursor',key:'brush',brushOption:{brushType:'lineX',brushMode:'single'}});
    updating=false;
    if(current.lens&&!lens){try{lens=createLens(container,current,onSelect,onStatus);}catch(error){onStatus('时间透镜暂不可用，可继续使用年份图、年输入和资料文字窗口。');}}
    else if(!current.lens&&lens){lens.dispose();lens=null;}
    else lens?.update(current);
  }
  function resize(){if(!disposed){chart.resize();lens?.resize();}}
  const observer=new ResizeObserver(resize);observer.observe(container);
  function visibility(){if(!document.hidden)resize();}
  document.addEventListener('visibilitychange',visibility);
  update(current);
  return {update,resize,reset(){lens?.reset();},dispose(){if(disposed)return;disposed=true;observer.disconnect();document.removeEventListener('visibilitychange',visibility);chart.dispose();lens?.dispose();container.replaceChildren();}};
}

function yearStart(year){const date=new Date(0);date.setUTCFullYear(year,0,1);date.setUTCHours(0,0,0,0);return date.getTime();}
function dateSpan(item){const parts=item.date.split('-').map(Number),start=new Date(yearStart(parts[0]));
  if(parts.length>1)start.setUTCMonth(parts[1]-1);
  if(parts.length>2)start.setUTCDate(parts[2]);
  const end=new Date(start);if(parts.length===1)end.setUTCFullYear(parts[0]+1);else if(parts.length===2)end.setUTCMonth(parts[1]);else end.setUTCDate(parts[2]+1);
  return [start.getTime(),end.getTime()];
}
function createLens(container,snapshot,onSelect,onStatus){
  const host=document.createElement('div');host.className='material-time-lens';container.append(host);
  let renderer;try{renderer=new THREE.WebGLRenderer({antialias:true});}catch(error){host.remove();throw error;}
  renderer.setPixelRatio(Math.min(devicePixelRatio,1.7));renderer.setClearColor(0xf0f4f9);host.append(renderer.domElement);
  renderer.domElement.setAttribute('aria-label','时间透镜，拖动观察；资料也可从文字窗口打开');
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(40,1,.1,100),controls=new OrbitControls(camera,renderer.domElement);
  camera.position.set(0,.08,1);controls.enableDamping=false;controls.minDistance=5;controls.maxDistance=45;controls.update();
  const geometry=new THREE.BoxGeometry(1,.18,.18),material=new THREE.MeshBasicMaterial({color:0xffffff});
  const mesh=new THREE.InstancedMesh(geometry,material,300);scene.add(mesh);
  let disposed=false,frame=0,items=[],down=null,selected=null,fitDistance=1;
  const ticks=[],tickResources=[];
  const axisGeometry=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-6,-2,0),new THREE.Vector3(6,-2,0)]),axisMaterial=new THREE.LineBasicMaterial({color:0x58697b});scene.add(new THREE.Line(axisGeometry,axisMaterial));
  const axis=document.createElement('p');axis.className='material-time-axis';host.after(axis);
  function draw(){frame=0;if(!disposed&&!document.hidden)renderer.render(scene,camera);}
  function requestDraw(){if(!disposed&&!document.hidden&&!frame)frame=requestAnimationFrame(draw);}
  function update(data){items=data.items.filter(item=>item.precision!=='unknown');const years=data.years.map(x=>Number(x.year));
    const low=years.length?Math.min(...years):0,high=years.length?Math.max(...years):0,from=yearStart(low),to=yearStart(high+1),x=value=>-6+12*(value-from)/(to-from);
    const kinds=[...new Set(data.items.map(item=>item.kind))].sort(),transform=new THREE.Object3D();mesh.count=items.length;
    items.forEach((item,index)=>{const [a,b]=dateSpan(item);transform.position.set((x(a)+x(b))/2,1.5-kinds.indexOf(item.kind)*(kinds.length>1?3/(kinds.length-1):0)+(index%3)*.15,(Math.floor(index/3)%9-4)*.32);transform.scale.set(Math.max(.055,x(b)-x(a)),1,1);transform.updateMatrix();mesh.setMatrixAt(index,transform.matrix);});
    mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();
    highlight(selected);
    ticks.forEach(tick=>scene.remove(tick));ticks.length=0;tickResources.forEach(resource=>resource.dispose());tickResources.length=0;
    if(years.length){
      const values=[...new Set([low,...Array.from({length:3},(_,i)=>Math.round(low+(high+1-low)*(i+1)/4)),high+1])];
      for(const year of values){
        const canvas=document.createElement('canvas');canvas.width=128;canvas.height=40;const context=canvas.getContext('2d');context.fillStyle='#243347';context.font='26px sans-serif';context.textAlign='center';context.fillText(String(year),64,30);
        const texture=new THREE.CanvasTexture(canvas),labelMaterial=new THREE.SpriteMaterial({map:texture,transparent:true,depthTest:false}),label=new THREE.Sprite(labelMaterial);
        label.position.set(x(yearStart(year)),-2.35,0);label.scale.set(1.4,.44,1);scene.add(label);ticks.push(label);tickResources.push(texture,labelMaterial);
        const geometry=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(x(yearStart(year)),-1.88,0),new THREE.Vector3(x(yearStart(year)),-2.08,0)]),material=new THREE.LineBasicMaterial({color:0x58697b}),tick=new THREE.Line(geometry,material);scene.add(tick);ticks.push(tick);tickResources.push(geometry,material);
      }
      kinds.forEach((kind,index)=>{
        const canvas=document.createElement('canvas');canvas.width=256;canvas.height=40;const context=canvas.getContext('2d');context.fillStyle='#243347';context.font='24px sans-serif';context.textAlign='center';context.fillText(data.kindLabels?.[kind]||kind,128,30);
        const texture=new THREE.CanvasTexture(canvas),material=new THREE.SpriteMaterial({map:texture,transparent:true,depthTest:false}),label=new THREE.Sprite(material);label.position.set(-7.5,1.5-index*(kinds.length>1?3/(kinds.length-1):0),0);label.scale.set(2.6,.41,1);label.userData.typeLabel=true;label.visible=camera.aspect>2;scene.add(label);ticks.push(label);tickResources.push(texture,material);
      });
    }
    axis.textContent=years.length?`${low} 年 — ${high} 年；横轴与年份概览共用范围。方块宽度表示登记日期的可能区间（过窄时保留可点击宽度）；类型自上至下：${kinds.map(kind=>data.kindLabels?.[kind]||kind).join('、')}。纵深仅用于避让。`:'没有已知日期，未知资料请从文字窗口打开。';requestDraw();
  }
  const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();
  function highlight(id){selected=id;items.forEach((item,index)=>mesh.setColorAt(index,new THREE.Color(item.id===id?0xb47d00:0x174e9c)));if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;requestDraw();}
  function pointerDown(event){down={x:event.clientX,y:event.clientY};}
  function pointerUp(event){if(!down)return;const distance=Math.hypot(event.clientX-down.x,event.clientY-down.y);down=null;if(distance>6)return;
    const rect=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);
    const hit=raycaster.intersectObject(mesh)[0];if(hit&&items[hit.instanceId]){const item=items[hit.instanceId];highlight(item.id);onStatus('已选中：'+item.title+' · '+item.date+'。');onSelect(item.id);}
  }
  function resize(){if(disposed||!host.clientWidth||!host.clientHeight)return;renderer.setSize(host.clientWidth,host.clientHeight,false);camera.aspect=host.clientWidth/host.clientHeight;const nextFit=Math.max(7.4,7/(Math.tan(THREE.MathUtils.degToRad(20))*camera.aspect));camera.position.sub(controls.target).multiplyScalar(nextFit/fitDistance).add(controls.target);fitDistance=nextFit;camera.updateProjectionMatrix();ticks.filter(tick=>tick.userData.typeLabel).forEach(label=>label.visible=camera.aspect>2);controls.update();requestDraw();}
  function reset(){controls.target.set(0,0,0);camera.position.set(0,.08*fitDistance,fitDistance);controls.update();requestDraw();}
  function visibility(){if(document.hidden){cancelAnimationFrame(frame);frame=0;}else requestDraw();}
  function lost(event){event.preventDefault();onStatus('时间透镜图形已中断，可使用文字窗口，或切换视图后重试。');}
  controls.addEventListener('change',requestDraw);renderer.domElement.addEventListener('pointerdown',pointerDown);renderer.domElement.addEventListener('pointerup',pointerUp);renderer.domElement.addEventListener('webglcontextlost',lost);document.addEventListener('visibilitychange',visibility);
  const observer=new ResizeObserver(resize);observer.observe(host);resize();update(snapshot);onStatus('拖动观察、滚轮缩放；点击真实资料方块打开阅读器。未知日期不放入时间轴。');
  return {update,resize,reset,dispose(){if(disposed)return;disposed=true;cancelAnimationFrame(frame);observer.disconnect();controls.dispose();document.removeEventListener('visibilitychange',visibility);renderer.domElement.removeEventListener('pointerdown',pointerDown);renderer.domElement.removeEventListener('pointerup',pointerUp);renderer.domElement.removeEventListener('webglcontextlost',lost);geometry.dispose();material.dispose();axisGeometry.dispose();axisMaterial.dispose();tickResources.forEach(resource=>resource.dispose());renderer.dispose();renderer.forceContextLoss();host.remove();axis.remove();}};
}
