// Offline rendering regressions; this is not a browser or accessibility test.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const page=fs.readFileSync(path.join(__dirname,'dist/index.html'),'utf8');
class Node {
 constructor(tag='div',text=''){this.tag=tag;this.textContent=text;this.children=[];this.style={};this.attrs={};this.listeners={};this.parentElement=this;this.value='';this.hidden=false}
 append(...nodes){this.children.push(...nodes)}
 replaceChildren(...nodes){this.children=nodes}
 setAttribute(k,v){this.attrs[k]=v}
 getAttribute(k){return this.attrs[k]}
 addEventListener(k,fn){this.listeners[k]=fn}
 querySelector(){return this.span||(this.span=new Node('span'))}
 querySelectorAll(){return this.items||[]}
 contains(){return false}
 focus(){}
}
const nodes={};
const document={getElementById(id){return nodes[id]||(nodes[id]=new Node())},createElement(tag){return new Node(tag)},addEventListener(){},activeElement:null};
for(const [id,values]of [['segment',['all','finance','general']],['level',['senior','all']]]){
 document.getElementById(id).value=values[0];const menu=document.getElementById(id+'-menu');menu.items=values.map(value=>{const n=new Node('button',value);n.dataset={value};return n});
}
for(const id of ['dataset','api-stats'])document.getElementById(id).textContent=page.match(new RegExp(`<script id="${id}" type="application/json">([\\s\\S]*?)</script>`))[1];
const context={document,Intl,Map,Set,Date,Number,URL,Event:class Event{},console};vm.createContext(context);
vm.runInContext(page.split('<script>')[1].split('</script>')[0],context);
const content=node=>[node.textContent,...node.children.map(content)].filter(Boolean).join(' ');
const jobs=()=>nodes.regions.children.flatMap(region=>region.children.filter(child=>child.className==='region-jobs')).map(content).join(' ');
for(const currency of ['local','usd'])for(const period of ['month','year']){
 vm.runInContext(`setCurrencyMode('${currency}');setPeriodMode('${period}')`,context);
 const text=jobs();assert(text.includes(period==='month'?'/ месяц':'/ год'));
 assert(!text.includes(period==='month'?'/ год':'/ месяц'));
 assert(!/тыс\.[^/]*тыс\./.test(text));
}
vm.runInContext("setCurrencyMode('local');setPeriodMode('year')",context);
const cards=content(nodes.regions);
assert(cards.includes('100–180 тыс.')&&cards.includes('Вакансий в расчёте: 3'),'Swiss card must combine manual and API salary records');
assert(cards.includes('40–250 тыс.')&&cards.includes('Вакансий в расчёте: 7'),'London card must combine manual and API salary records and dedupe duplicates');
assert(cards.includes('Вакансий в расчёте: 3'),'Russia card must combine manual and API salary records');
assert(cards.split('Senior Embedded C++ Engineer').length-1===1,'The same ALTEN vacancy must be deduplicated across sources');
assert(cards.includes('Senior Software Engineer C++')&&cards.includes('Cudos AG'),'Expanded vacancies must include the job link and employer');
assert(!/Налоговая база не уточнена|SwissDevJobs|Headcount Labs/.test(jobs()),'Expanded vacancies must show only pay range and employer under the link');
const explicit=Number(nodes['api-kpis'].children[0].children[0].textContent);
nodes.level.value='all';vm.runInContext('render();renderApi()',context);
const all=Number(nodes['api-kpis'].children[0].children[0].textContent);
const allCards=content(nodes.regions);
assert(allCards.includes('объединённой выборке'),'All-level cards must keep using the merged salary sample');
assert(allCards!==cards,'All-level filter must alter the merged sample');
assert(all>explicit,'API Senior filter must affect the displayed counts');
nodes.segment.value='finance';vm.runInContext('render();renderApi()',context);
assert(Number(nodes['api-kpis'].children[0].children[0].textContent)<all,'API segment filter must affect the counts');
assert(!content(nodes['api-notes']).includes('£2 026'));
console.log('Display checks passed: period/currency pairs, one scale suffix, merged manual/API sample, senior/segment filters.');
