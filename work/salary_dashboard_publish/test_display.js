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
for(const [id,values]of [['segment',['all','finance']],['level',['senior','all']]]){
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
for(const name of ['Switzerland','London, UK','Russia']){
 const card=nodes.regions.children.find(region=>content(region).includes(name));
 assert(card,`${name} card must be rendered`);
 const count=Number(content(card).match(/Вакансий в расчёте: (\d+)/)?.[1]);
 const jobsNode=card.children.find(child=>child.className==='region-jobs');
 assert(count>0&&jobsNode?.children.length===count,`${name} card must match its rendered salary vacancies`);
}
assert(cards.split('Senior Embedded C++ Engineer').length-1===1,'The same ALTEN vacancy must be deduplicated across sources');
assert(cards.includes('Senior Software Engineer C++')&&cards.includes('Cudos AG'),'Expanded vacancies must include the job link and employer');
assert(!/Налоговая база не уточнена|SwissDevJobs|Headcount Labs/.test(jobs()),'Expanded vacancies must show only pay range and employer under the link');
nodes.level.value='all';vm.runInContext('render()',context);
const allCards=content(nodes.regions);
assert(allCards!==cards,'All-level filter must alter the merged sample');
nodes.segment.value='finance';vm.runInContext('render()',context);
assert(content(nodes.regions)!==allCards,'Segment filter must alter the displayed sample');
console.log('Display checks passed: period/currency pairs, one scale suffix, merged manual/API sample, level/segment filters.');
