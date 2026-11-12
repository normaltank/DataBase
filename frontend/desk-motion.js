import { animate, createScope } from 'animejs';
let scope;
export function cancel(){scope?.revert();scope=null;}
export function transition(target){
  cancel();
  if(!target?.isConnected||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  scope=createScope({root:target}).add(()=>{animate(target,{opacity:[.82,1],translateY:[8,0],duration:220,ease:'outExpo'});});
}
export function shelfTransition(target){
  cancel();
  if(!target?.isConnected||document.hidden||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  scope=createScope({root:target}).add(()=>{animate(target,{opacity:[.84,1],translateY:[10,0],duration:240,ease:'outExpo'});});
}
