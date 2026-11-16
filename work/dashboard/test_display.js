// Offline rendering regressions; this is not a browser or accessibility test.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const page=fs.readFileSync(path.join(__dirname,'dist/index.html'),'utf8');
const methodology=fs.readFileSync(path.join(__dirname,'dist/methodology.html'),'utf8');
assert(!page.includes('Что добавил расширенный поиск'),'Expanded search block must be removed');
for(const evidence of ['Решение по выборке:','Разница в предлагаемых зарплатах велика','прокси ожиданий работников','Кейс GitLab:','75-й перцентиль вместо 50-го','обычно примерно 20% от неё','три вилки для трёх рынков','handbook.gitlab.com/handbook/total-rewards/compensation'])assert(page.includes(evidence),`Hiring decision must include sample evidence and the GitLab case: ${evidence}`);
assert(methodology.includes('Локация учитывается при определении конкурентного диапазона оплаты'),'Methodology must align with the regional-market hiring recommendation');
for(const name of ['Швейцария','Лондон','Россия'])assert(methodology.includes(`<strong>${name}:`),`${name} methodology count must be labeled`);
for(const evidence of ['общая вилка для двух Senior C++ ролей','₽260–390 тыс.','до налогов и без бонусов','P25–P75 середин объявленных вилок','/2025/10/RUS_Job_market_25-26.pdf'])assert(methodology.includes(evidence),`Methodology must include ${evidence}`);
for(const evidence of ['CHF 125–170 тыс.','общая вилка для двух Senior C++ ролей','£95–140 тыс.','₽3,1–4,7 млн','₽1,8–3,4 млн','P25–P75 середин объявленных вилок'])assert(page.includes(evidence),`External salary evidence must show ${evidence}`);
assert(page.includes('gross/net не раскрыты'),'Swiss salary basis limitations must remain visible');
assert(page.includes('https://antaltalent.ru/wp-content/uploads/2025/10/RUS_Job_market_25-26.pdf'),'Antal link must use the live PDF');
assert(!page.includes('2025/09/RUS_Job_market_25-26.pdf'),'Broken Antal link must be removed');
assert(page.includes('Senior (83 вакансии) и Lead (17 вакансий)'),'HireHi Senior/Lead statistics must be combined transparently');
assert(page.includes('Lead (17 вакансий)'),'Dashboard must show the Lead sample size in its combined range');
assert(!page.includes('не являются пересчитанными общими перцентилями'),'Removed percentile caveat must stay absent');
const benchmarkScript=page.match(/const benchmarkValues=(\{[\s\S]*?\});\s*function benchmarkText/);
assert(benchmarkScript,'Benchmark values must be present');
const missingBenchmarkIds=[...benchmarkScript[1].matchAll(/"([^"]+)":\{/g)].map(match=>match[1]).filter(id=>!page.includes(`id="${id}"`));
assert.deepEqual(missingBenchmarkIds,[],'Every benchmark value must target an element in the dashboard');
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
const correctedRussianNet=JSON.parse(nodes.dataset.textContent).filter(row=>['https://career.habr.com/vacancies/1000167693','https://finder.work/vacancies/37562430'].includes(row.url));
assert.equal(correctedRussianNet.length,2,'Both Russian net vacancies with monthly salary must remain in the sample');
assert(correctedRussianNet.every(row=>row.period==='month'&&row.gross_net==='net'),'Both Russian net amounts must be classified as monthly');
const context={document,Intl,Map,Set,Date,Number,URL,Event:class Event{},console};vm.createContext(context);
vm.runInContext(page.split('<script>')[1].split('</script>')[0],context);
const content=node=>[node.textContent,...node.children.map(content)].filter(Boolean).join(' ');
const comparableKpi=nodes.kpis.children.find(card=>content(card).includes('сопоставимых условий оплаты'));
assert(!comparableKpi||Number(comparableKpi.children[0].textContent)>0,'Show the comparable-pay KPI only when its count is positive');
const offerSummary=()=>nodes.regions.children.map(card=>content(card.children[0].children.find(child=>child.className==='offer-summary'))).join(' ');
const offerCards=nodes.regions.children.map(card=>card.children[0].children.find(child=>child.className==='offer-summary'));
assert.equal(offerCards.length,3,'Each location must display a salary summary');
assert(offerCards.every(card=>card&&card.children.length>0),'Each location must show salary observations');
const defaultOffers=offerSummary();
assert(defaultOffers.includes('Gross/net не указано'),'Salary summaries must identify unknown tax basis');
vm.runInContext("setCurrencyMode('usd');setPeriodMode('month')",context);
assert(offerSummary().includes('$')&&offerSummary().includes('в месяц'),'Salary summaries must follow currency and period filters');
vm.runInContext("setCurrencyMode('local');setPeriodMode('year')",context);
const apiAudit=JSON.parse(nodes['api-stats'].textContent);
const sourceSnapshot=apiAudit.sources.filter(source=>source.status==='queried'&&source.records>0);
const sourceNames=sourceSnapshot.map(source=>source.source==='HeadHunter RSS'?'HeadHunter':source.source);
assert(page.includes('<details id="source-list" class="source-details">'),'Source list must be collapsed by default');
const uniqueRoles=apiAudit.groups.filter(group=>group.sources.some(source=>sourceSnapshot.some(item=>item.source===source))).length;
assert.deepEqual(nodes['source-rows'].children.map(row=>row.children[0].textContent),sourceNames,'Source list must contain only sources that returned data');
assert(nodes['source-rows'].children.every(row=>row.children.length===4),'Source rows must omit status and expose snapshot date');
assert(!page.includes('<th>Статус</th>'),'Source table must omit the status column');
assert(page.includes('<th>Снимок</th>'),'Source table must show last successful snapshot date');
assert(content(nodes['source-kpis']).includes(String(sourceNames.length)),'Source summary must show the current count of sources with data');
assert.equal(nodes['source-list-summary'].textContent,`Список источников (${sourceNames.length})`,'Expandable list summary must show source count');
assert.equal(nodes['source-kpis'].children[2].children[0].textContent,new Intl.NumberFormat('ru-RU').format(uniqueRoles),'Source summary must show deduplicated unique roles');
assert(nodes['source-kpis'].children[2].children[1].textContent.includes('дедупа'),'Deduplicated count must be labeled');
assert(!sourceNames.includes('HeadHunter RSS')&&sourceNames.includes('HeadHunter'),'HeadHunter RSS must be shown as HeadHunter');
const jobs=()=>nodes.regions.children.flatMap(region=>region.children.filter(child=>child.className==='region-jobs')).map(content).join(' ');
assert(!page.includes('Среднее:'),'Dashboard must not display the misleading midpoint average');
for(const currency of ['local','usd'])for(const period of ['month','year']){
 vm.runInContext(`setCurrencyMode('${currency}');setPeriodMode('${period}')`,context);
 const text=jobs();assert(text.includes(period==='month'?'в месяц':'в год'));
 assert(!text.includes(period==='month'?'в год':'в месяц'));
}
vm.runInContext("setCurrencyMode('local');setPeriodMode('year')",context);
assert.equal(nodes['bench-hirehi-combined'].textContent,'₽1,8–3,4 млн','Combined Senior/Lead band must annualize from monthly local values');
vm.runInContext("setPeriodMode('month')",context);assert.equal(nodes['bench-hirehi-combined'].textContent,'₽150–283 тыс.','Combined band must envelope both grade ranges in monthly mode');
vm.runInContext("setCurrencyMode('usd');setPeriodMode('year')",context);assert(nodes['bench-hirehi-combined'].textContent.startsWith('$'),'Combined band must follow the currency control');
vm.runInContext("setCurrencyMode('local');setPeriodMode('year')",context);
assert.equal(vm.runInContext("salaryText({salary_min:500000,salary_max:null,currency:'RUB',period:null},'Russia')",context),'от ₽500 тыс. · период не указан','An open salary floor without period must stay open and unannualized');
assert.equal(vm.runInContext("salaryText({salary_min:null,salary_max:365000,currency:'RUB',period:null},'Russia')",context),'до ₽365 тыс. · период не указан','An upper-only amount must stay upper-only');
vm.runInContext("setPeriodMode('month')",context);
assert.equal(vm.runInContext("salaryText({salary_min:200000,salary_max:200000,currency:'RUB',period:'month'},'Russia')",context),'₽200 тыс. · в месяц','Equal bounds must render once');
assert.equal(vm.runInContext("compensationKind({comp_type:'annual range; base vs total compensation not stated'})",context),'состав не указан','A sentence saying composition is unstated must not classify salary as package');
assert.equal(vm.runInContext("compensationKind({comp_type:'package (base/bonus split unspecified)'})",context),'пакет','An explicit package remains a package when its split is unspecified');
const unknownPeriodAnnual=vm.runInContext("salaryText({salary_min:500000,salary_max:null,currency:'RUB',period:null},'Russia')",context);
vm.runInContext("setPeriodMode('month')",context);
assert.equal(vm.runInContext("salaryText({salary_min:500000,salary_max:null,currency:'RUB',period:null},'Russia')",context),unknownPeriodAnnual,'Period toggle must not annualize an unspecified period');
const cards=content(nodes.regions);
for(const name of ['Швейцария','Лондон','Россия']){
 const card=nodes.regions.children.find(region=>content(region).includes(name));
 assert(card,`${name} card must be rendered`);
 const offers=card.children.find(child=>child.className==='region-summary').children.find(child=>child.className==='offer-summary');
 const count=offers.children.reduce((total,line)=>total+Number(line.children[0].textContent.match(/· (\d+)/)?.[1]||0),0);
 const jobsNode=card.children.find(child=>child.className==='region-jobs');
 assert(count>0&&jobsNode?.children.length===count,`${name} card must match its rendered salary vacancies`);
}
assert(!cards.includes('Senior Embedded C++ Engineer')&&!cards.includes('Embedded Software Engineer'),'Embedded/firmware roles must be excluded from the target salary sample');
assert(cards.includes('Senior Software Engineer C++')&&cards.includes('Cudos AG'),'Expanded vacancies must include the job link and employer');
assert(jobs().includes('gross/net не указано'),'Expanded offers must label unknown tax basis');
assert(!jobs().includes('период не указан'),'Unverified salary posts must stay out of the expanded vacancy list');
assert(!jobs().includes('Алабуга')&&!page.includes('37562275')&&!page.includes('139133285'),'Alabuga C++ vacancy must be absent from the sample and API dashboard data');
assert(!page.includes('Объявленные суммы'),'Dashboard must not label salary cards as "Объявленные суммы"');
assert(nodes['source-summary'].textContent.includes('Ошибок обновления:'),'Dashboard must surface source failures and retained snapshots');
const mixedGrade=JSON.parse(nodes.dataset.textContent).find(row=>row.url?.endsWith('/139326350/'));
assert.equal(mixedGrade?.seniority,'inferred_senior','The Russian HFT Middle/Senior role is included as salary-inferred Senior');
assert(cards.includes('C++ / Rust Developer (Middle / Senior) HFT'),'Salary-inferred Russian HFT vacancy must appear in the default Senior view');
assert(mixedGrade?.seniority_basis?.includes('₽350 тыс.')&&mixedGrade.seniority_basis.includes('Middle/Senior'),'Salary-based Senior inference and its basis must remain in the dataset');
nodes.level.value='all';vm.runInContext('render()',context);
const allCards=content(nodes.regions);
assert(allCards!==cards,'All-level filter must alter the merged sample');
assert(allCards.includes('C++ / Rust Developer (Middle / Senior) HFT'),'Mixed-grade HFT vacancy must remain visible in the adjacent-level context');
nodes.segment.value='finance';vm.runInContext('render()',context);
assert(content(nodes.regions)!==allCards,'Segment filter must alter the displayed sample');
console.log('Display checks passed: pay bounds, periods/currencies, source freshness, deduplicated sample and filters.');
