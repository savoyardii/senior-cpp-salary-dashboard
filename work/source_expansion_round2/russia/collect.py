#!/usr/bin/env python3
"""Replay saved public pages, or refresh permitted HTTP200 endpoints with --live. Stdlib only."""
import argparse, datetime as dt, difflib, hashlib, html, json, pathlib, re, urllib.request
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
BASELINES = ['work/expanded_sample/russia_audited.json', 'work/expanded_sample/london_audited.json', 'work/api_connector/data/latest.json', 'work/source_expansion/candidates.json']

class Page(HTMLParser):
    def __init__(self, source):
        super().__init__(); self.skip=0; self.text=[]; self.links=[]; self.feed(source)
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style'): self.skip+=1
        if tag=='a': self.links.append(dict(attrs).get('href',''))
    def handle_endtag(self, tag):
        if tag in ('script','style'): self.skip=max(0,self.skip-1)
    def handle_data(self, data):
        if not self.skip: self.text.append(data)
    def plain(self): return ' '.join(' '.join(self.text).split())

def clean(text): return Page(text).plain()
def norm(s): return re.sub(r'[^\w+]+',' ',str(s).lower().replace('с++','c++')).strip()
def walk(d):
    if isinstance(d,dict):
        yield d
        for v in d.values(): yield from walk(v)
    elif isinstance(d,list):
        for v in d: yield from walk(v)
def value(v):
    return v.get('value') if isinstance(v,dict) else v

def baseline_matches(row):
    matches=[]
    for file in BASELINES:
        data=json.loads((ROOT/file).read_text())
        for b in walk(data):
            urls=[str(v) for k,v in b.items() if k in ('url','vac_url','final_url','source_url')]
            ids=[str(value(v)) for k,v in b.items() if k in ('id','source_id','job_id')]
            title=value(b.get('title') or b.get('job-name') or b.get('profession')) or ''
            employer=value(b.get('employer') or b.get('employer_name') or b.get('firm_name') or b.get('company') or '')
            if isinstance(employer,dict): employer=employer.get('name','')
            same_id=str(row['source_id']) in ids
            same_url=any(u.split('?')[0].rstrip('/')==row['url'].rstrip('/') for u in urls)
            title_sim=difflib.SequenceMatcher(None,norm(title),norm(row['title'])).ratio()
            emp_sim=difflib.SequenceMatcher(None,norm(employer),norm(row['employer'])).ratio() if row['employer'] else 0
            if same_id or same_url or (emp_sim>.80 and title_sim>.74):
                matches.append({'file':file,'url':urls[0] if urls else None,'title':title,'employer':employer,'reason':'url/id' if same_id or same_url else 'employer+similar_title'})
    return matches

def jsonlds(source):
    for text in re.findall(r'<script\b[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>',source,re.S):
        data=json.loads(text)
        for row in walk(data):
            if row.get('@type')=='JobPosting': yield row

def salary_header(text, title):
    start=text.find('Создать резюме '+title)
    if start<0: return None
    head=text[start+len('Создать резюме '+title):].split('Опыт работы')[0]
    if 'Уровень дохода не указан' in head: return None
    return head.strip()

def normalize(probe, source, job):
    text=Page(source).plain(); desc=clean(job.get('description',''))
    url=probe.get('final_url',probe['url']).split('?')[0].rstrip('/')
    title=html.unescape(job.get('title','')); employer=job.get('hiringOrganization',{}).get('name')
    ident=job.get('identifier',{}); source_id=str(ident.get('value') or url.rsplit('/',1)[-1])
    locations=job.get('jobLocation',[]);locations=locations if isinstance(locations,list) else [locations]
    addresses=[x.get('address',{}) for x in locations]; countries=[x.get('addressCountry') for x in addresses if x.get('addressCountry')]
    applicant=job.get('applicantLocationRequirements',[]);applicant=applicant if isinstance(applicant,list) else [applicant]
    countries += [x.get('name') for x in applicant if x.get('name')]
    salary=job.get('baseSalary') or {}; salvalue=salary.get('value') or {};salvalue=salvalue if isinstance(salvalue,dict) else {'value':salvalue}
    lo=salvalue.get('minValue'); hi=salvalue.get('maxValue');amount=salvalue.get('value')
    if amount is not None:lo=hi=amount
    snippet=salary_header(text,title) if 'zarplata.ru' in url else None
    currency=salary.get('currency');period=salvalue.get('unitText');tax=None
    if snippet:
        m=re.search(r'([\d\s]+)\s*₽\s*за\s*месяц',snippet)
        if m:
            lo=hi=int(re.sub(r'\s','',m.group(1)));currency='RUB';period='MONTH'
            if snippet.startswith('от '):hi=None
            if snippet.startswith('до '):lo=None
        tax='net' if 'на руки' in snippet else 'gross' if 'до вычета налогов' in snippet else None
    if 'quick-offer.ru' in url:
        m=re.search(r'Зарплата:\s*до ([\d\s]+) руб в месяц',desc)
        if m:lo=None;hi=int(re.sub(r'\s','',m.group(1)));currency='RUB';period='MONTH';snippet=m.group(0)
    if 'sobes.tech' in url:
        # Source original and publisher-normalized metadata are kept separate.
        m=re.search(r'ЗП:\s*[^<]+',job.get('description',''))
        snippet=html.unescape(m.group(0)) if m else None
        if snippet and 'на руки' in snippet:tax='net'
    cpp=bool(re.search(r'[cс](?:/[cс])?\+\+',title+' '+desc,re.I))
    senior=bool(re.search(r'senior|lead|ведущ|старш|architect',title+' '+desc,re.I))
    ru=any(x in ('RU','Russia','Россия') for x in countries)
    reasons=[]
    if not cpp:reasons.append('no_required_cpp_signal')
    if not employer or employer.lower() in ('confidential','nda','unknown'):reasons.append('employer_undisclosed')
    if not senior:reasons.append('seniority_not_confirmed')
    if not ru:reasons.append('russia_not_explicit')
    if 'и/или Verilog' in desc:reasons.append('cpp_optional_alternative_to_verilog')
    if '45543'==source_id:reasons.append('Go_required_cpp_tag_only')
    posted=job.get('datePosted');expires=job.get('validThrough')
    if 'sobes.tech' in url:reasons.append('publisher_current_employer_status_unverified_old_post')
    reviewed_exclusions={
        '139097088':'seniority_absent_title_body_senior_word_refers_to_other_context',
        '137307096':'flight_dynamics_engineer_cpp_is_desirable_not_core_required',
        '138927840':'ML_lead_cpp_not_required_core_language',
        '138661212':'data_architect_cpp_optional_language',
        '26051':'network_architect_cpp_category_only_programming_merely_desirable',
    }
    if source_id in reviewed_exclusions:reasons.append(reviewed_exclusions[source_id])
    if expires and expires[:10] < dt.date.today().isoformat():reasons.append('expired')
    if employer and 'spectral' in employer.lower():reasons.append('target_employer')
    r={'source':'Zarplata' if 'zarplata.ru' in url else 'Sobes.tech' if 'sobes.tech' in url else 'Quick Offer' if 'quick-offer.ru' in url else 'Rabota' if 'rabota.ru' in url else 'Yandex Careers', 'source_id':source_id,'url':url,'title':title,'employer':employer,'region':'Russia' if ru else None,'location':addresses,'country_evidence':countries,'published_at':posted,'expires_at':expires,'status':'listed_with_future_expiry' if expires and not 'expired' in reasons else 'listed_current_status_unverified','description':desc,'description_html':job.get('description'),'employment_type':job.get('employmentType'),'contract_evidence':'только по ИП' if 'только по ИП' in desc else 'ТК/ИП' if 'ТК/ИП' in desc else 'Трудовой договор' if 'Трудовой договор' in text else 'ТК РФ' if 'ТК РФ' in desc else None,'salary_min':lo,'salary_max':hi,'currency':currency,'period':period,'tax_basis':tax,'salary_raw_snippet':snippet,'seniority_evidence':title if re.search(r'senior|lead|ведущ|старш|architect',title,re.I) else None,'experience_evidence':re.findall(r'.{0,55}(?:от \d+ лет|\d+–\d+ лет|более \d+ лет).{0,55}',text)[:4],'cohort':'senior_plus_leadership' if re.search(r'lead|ведущ|architect',title,re.I) else 'senior' if senior else None,'salary_provenance':'visible employer ad header' if snippet and 'zarplata.ru' in url else 'description salary statement (not AI market estimate)' if 'quick-offer.ru' in url else 'publisher JobPosting JSON-LD; original post snippet separately retained','compensation_type':'advertised salary' if lo is not None or hi is not None else None,'base_vs_total':None,'raw_file':probe['raw'],'raw_sha256':hashlib.sha256(source.encode()).hexdigest(),'source_jsonld':job,'strict_eligible':not reasons,'exclusion_reasons':reasons}
    r['baseline_matches']=baseline_matches(r);r['net_new']=not r['baseline_matches'];return r

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
    probes=[]
    for f in ['probes.json','details_probes.json','expanded_probes.json','kaspersky_probes.json','zarplata_probes.json']:
        if (HERE/f).exists():probes+=json.loads((HERE/f).read_text())
    records=[];attempts=[];seen=set()
    for p in probes:
        if p.get('http')!=200:continue
        path=ROOT/p['raw']
        if args.live:
            try:
                with urllib.request.urlopen(p['url'],timeout=20) as response:
                    payload=response.read();path.write_bytes(payload)
                    attempts.append({'url':p['url'],'http':response.status,'final_url':response.url})
            except Exception as e:attempts.append({'url':p['url'],'error':str(e)});continue
        source=path.read_text()
        path.with_suffix('.txt').write_text(Page(source).plain())
        jobs=list(jsonlds(source))
        if 'careers.kaspersky.ru/vacancy/' in p['url']:
            sid=p['url'].rsplit('/',1)[-1];text=Page(source).plain();title=clean(re.search(r'<h1[^>]*>(.*?)</h1>',source,re.S).group(1))
            excerpt=text.split('Откликнуться на вакансию Поля,')[0]
            jobs=[{'title':title,'description':excerpt,'identifier':{'value':sid},'hiringOrganization':{'name':'Лаборатория Касперского'},'applicantLocationRequirements':{'name':'Россия'}}]
        if 'dostavka.yandex.ru/careers/jobs/infrastructure-developer/' in p['url']:
            text=Page(source).plain();jobs=[{'title':'Старший разработчик инфраструктуры на С++','description':text,'identifier':{'value':'delivery-infrastructure-developer'},'hiringOrganization':{'name':'Яндекс'},'applicantLocationRequirements':{'name':'Россия'}}]
        if not (re.search(r'/(?:vacancy|vacancies|job)/[\w-]+',p['url']) or '/careers/jobs/' in p['url']): continue
        for j in jobs:
            row=normalize(p,source,j)
            if 'careers.kaspersky.ru' in p['url'] or 'dostavka.yandex.ru' in p['url']:
                row['source_jsonld']=None;row['description_html']=None;row['extraction_evidence']='public visible employer page, not JSON-LD'
                row['source']='Kaspersky Careers' if 'kaspersky' in p['url'] else 'Yandex Delivery Careers'
            if row['url'] not in seen:records.append(row);seen.add(row['url'])
    out={'observed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'records':records,'live_attempts':attempts,'notice':'No AI, keys, login, paid API, CAPTCHA retry or user-agent spoofing. Salary estimates and market benchmarks never parsed.'}
    (HERE/'candidates.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
    strict=[r for r in records if r['net_new'] and r['strict_eligible']]
    (HERE/'new_strict_candidates.json').write_text(json.dumps(strict,ensure_ascii=False,indent=2))
    summary={'jobposting_records':len(records),'net_new_strict':len(strict),'net_new_strict_with_salary':sum(r['salary_min'] is not None or r['salary_max'] is not None for r in strict),'records':[{k:r[k] for k in ['source','source_id','employer','title','salary_min','salary_max','period','tax_basis','strict_eligible','net_new','exclusion_reasons']} for r in records]}
    (HERE/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
