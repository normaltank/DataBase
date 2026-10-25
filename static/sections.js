'use strict';

// Callers provide real headings inside a data-section-scope. Buttons leave routing intact.
function sectionNavigation(items, label='本页章节') {
  return '<nav class="section-navigation" aria-label="'+esc(label)+'"><span>本页内容</span><div>'+items.map(item=>'<button type="button" data-section-target="'+esc(item.id)+'">'+esc(item.label)+'</button>').join('')+'</div></nav>';
}

document.addEventListener('click',event=>{
  const button=event.target.closest('[data-section-target]');if(!button)return;
  const scope=button.closest('[data-section-scope]');if(!scope)return;
  const target=[...scope.querySelectorAll('[id]')].find(element=>element.id===button.dataset.sectionTarget);
  if(!target)return;
  event.preventDefault();
  for(let parent=target.parentElement;parent&&parent!==scope;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
  target.classList.add('section-target');target.tabIndex=-1;
  target.focus({preventScroll:true});target.scrollIntoView({block:'start'});
});
