'use strict';
// Offline rendering only: no DOM service, provider, or network connection.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context={document:{addEventListener(){}},esc:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;'),externalLink:(url,label)=>`<a href="${url}">${label}</a>`,linkButton:()=>'',sourceHref:id=>'#source/'+id};
vm.createContext(context);vm.runInContext(fs.readFileSync('static/discovery.js','utf8'),context);
for(const [source,entryType,dateBasis,dateLabel] of [
  ['LIIA Opinions','rss','published','发表日期'],['CJIR RSS','rss','rss_online','RSS 上线／发布标签日期'],
  ['Intersections RSS','rss','rss_online','RSS 上线／发布标签日期'],['GSSC Publications','html','published','发表日期']]){
  context.queue={source_name:source,filename:source+' 近期发现',entry_type:entryType,date_basis:dateBasis,source_id:'synthetic',
    window:{start:'2026-10-05',end:'2026-11-03'},feed_url:'https://synthetic.example/list',column_url:'https://synthetic.example/column',
    retrieved_at:'2026-11-03T00:00:00Z',returned:1,earliest:'2026-10-22',warnings:[],counts:{},exclusions:[],
    items:[{fields:{title:'Synthetic item',published_on:'2026-10-22',url:'https://synthetic.example/item'},evidence:{format:source}}]};
  const rendered=vm.runInContext('discoveryQueueHtml(queue)',context);
  assert.ok(rendered.includes(`<h3>${source} · 1 条候选</h3>`),rendered);
  assert.ok(rendered.includes(dateLabel+'范围：'),rendered);
  assert.ok(rendered.includes(entryType==='html'?'本次官方 HTML 列表':'本次固定 RSS'),rendered);
  assert.ok(rendered.includes(entryType==='html'?'列表第':'RSS 第')||rendered.includes('无排除条目'));
  if(source!=='LIIA Opinions')assert.ok(!rendered.includes('Opinions'),rendered);
  if(entryType==='html')assert.ok(!rendered.includes('RSS'),rendered);
  if(dateBasis==='rss_online')assert.ok(rendered.includes('不替代原文发表日期、引用年份或首次入库时间'),rendered);
  const evidence=vm.runInContext('discoveryItemHtml(queue.items[0])',context);
  assert.ok(evidence.includes('原始字段与取得依据'));
}
context.queue={filename:'近期资料发现',items:[]};
assert.ok(!vm.runInContext('discoveryQueueHtml(queue)',context).includes('Opinions'));
console.log('PASS: 4 source renderings and unopened empty discovery queue');
