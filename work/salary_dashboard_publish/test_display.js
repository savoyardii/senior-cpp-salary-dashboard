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
const context={document,Intl,Map,Set,Date,Number,Event:class Event{},console};vm.createContext(context);
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
assert(cards.includes('100–120 тыс.')&&cards.includes('Зарплатных наблюдений: 3'),'Swiss card must use explicit-Senior API salary observations');
assert(cards.includes('40–200 тыс.')&&cards.includes('Зарплатных наблюдений: 4'),'London card must use explicit-Senior API salary observations');
assert(cards.includes('Зарплатных наблюдений: 1'),'Russia card must show the single API salary observation');
const explicit=Number(nodes['api-kpis'].children[0].children[0].textContent);
nodes.level.value='all';vm.runInContext('render();renderApi()',context);
const all=Number(nodes['api-kpis'].children[0].children[0].textContent);
const allCards=content(nodes.regions);
assert(allCards.includes('100–160 тыс.')&&allCards.includes('Зарплатных наблюдений: 4'),'All-level Swiss card must include the experience-based observation');
assert(allCards.includes('40–220 тыс.')&&allCards.includes('Зарплатных наблюдений: 5'),'All-level London card must include the experience-based observation');
assert(all>explicit,'API Senior filter must affect the displayed counts');
nodes.segment.value='finance';vm.runInContext('render();renderApi()',context);
assert(Number(nodes['api-kpis'].children[0].children[0].textContent)<all,'API segment filter must affect the counts');
assert(!content(nodes['api-notes']).includes('£2 026'));
console.log('Display checks passed: period/currency pairs, one scale suffix, API senior/segment filters.');
