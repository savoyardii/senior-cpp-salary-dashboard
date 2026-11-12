"""Offline strict screening; unknown compensation fields deliberately remain null."""
from collect import *
from difflib import SequenceMatcher
P=ROOT
PROJECT=P.parents[2]
BASES=['work/expanded_sample/london_audited.json','work/api_connector/data/latest.json','work/source_expansion/candidates.json']
def walk(v):
 if isinstance(v,dict):
  if isinstance(v.get('title'),str):yield v
  for w in v.values():yield from walk(w)
 elif isinstance(v,list):
  for w in v:yield from walk(w)
def norm(s):return re.sub(r'[^a-z0-9]+',' ',str(s).lower()).strip()
def employer(r):
 for key in ['employer','employer_name','company','hiringOrganization']:
  v=r.get(key)
  if isinstance(v,str):return v
  if isinstance(v,dict):return v.get('display_name') or v.get('name') or v.get('value') or ''
 return ''
def canonical(u):return urllib.parse.unquote(str(u).split('?')[0].split('#')[0]).rstrip('/').lower()
def salary(s):
 m=re.search(r'£([\d,]+) to £([\d,]+) a year',s)
 return (int(m[1].replace(',','')),int(m[2].replace(',','')),'GBP','year') if m else (None,None,None,None)
def getlabel(t,label):
 m=re.search(r'(?:^|\n)'+re.escape(label)+r':\n([^\n]+)',t);return m[1] if m else None
def build():
 attempts=[]
 for file in ['attempts.json','extra_attempts.json','reed_attempts.json']:
  attempts+=json.loads((P/file).read_text())
 baseline=[(path,r) for path in BASES for r in walk(json.loads((PROJECT/path).read_text()))]
 records=[];seen=set()
 for a in attempts:
  if a.get('http_status')!=200:continue
  u=a['url'];cu=canonical(u)
  if cu in seen:continue
  seen.add(cu)
  if not re.fullmatch(r'https://www.jobs.service.gov.uk/jobs/[a-f0-9]+',u) and not re.fullmatch(r'https://www.reed.co.uk/jobs/[^/]+/\d+',u) and 'hunterbond.com/job/' not in u and not re.search(r'ecmselection.co.uk/jobs/\d+/',u):continue
  t=(P/a['text_file']).read_text();js=next((x for x in a.get('jsonld',[]) if isinstance(x,dict) and x.get('@type')=='JobPosting'),{})
  if 'jobs.service.gov.uk' in u:
   body=t.split('Cymraeg\n',1)[-1];title=body.split('\nCompany:')[0].strip();desc=body.split('\nSummary\n',1)[-1].split('\nApply for this job')[0].strip()
   emp=getlabel(body,'Company');location=getlabel(body,'Location');snippet=getlabel(body,'Salary') or '';lo,hi,cur,period=salary(snippet);posted=getlabel(body,'Posting date');expires=getlabel(body,'Closing date');typ=getlabel(body,'Job type');source='UK Government Work Hub'
  elif js:
   title=js['title'];desc=' '.join(parse(js.get('description','')).text);emp=employer(js);loc=js.get('jobLocation',{})
   if isinstance(loc,list):loc=loc[0] if loc else {}
   location=loc.get('address',{}) if isinstance(loc,dict) else loc
   source='Reed' if 'reed.co.uk' in u else 'Hunter Bond';posted=js.get('datePosted');expires=js.get('validThrough');typ=js.get('employmentType');base=js.get('baseSalary') or {};val=base.get('value',{})
   snippet='';lo=val.get('minValue');hi=val.get('maxValue');cur=base.get('currency');period={'YEAR':'year','MONTH':'month','DAY':'day'}.get(val.get('unitText'))
   if 'Full job description\n' in t:
    pre=t.split('Full job description\n')[0];snippet='; '.join(q for q in pre.splitlines() if '£' in q)
  else:
   title=t.splitlines()[0];desc=t;emp='ECM Selection';source='ECM Selection';location='Central London';snippet='£40k - £70k DoE + benefits';lo=40000;hi=70000;cur='GBP';period=None;posted=None;expires=None;typ=None
  r={'source':source,'source_id':u.rstrip('/').split('/')[-1],'url':u,'title':title,'employer':emp,'location':location,'description':desc,'description_reviewed':True,'raw_salary_snippet':snippet,'salary_min':lo,'salary_max':hi,'currency':cur,'period':period,'gross_net':None,'comp_type':None,'published_at':posted,'expires_at':expires,'employment_type':typ,'http_status':200,'raw_file':a['raw_file'],'observed_at':datetime.now(timezone.utc).isoformat(),'status':'page reachable, source closing date if supplied; not independently employer-verified','independent_end_employer_confirmed':False,'flags':[]}
  if source=='Hunter Bond':r.update(raw_salary_snippet='Up to £300k Total Compensation (1st Year)',salary_min=None,salary_max=300000,currency='GBP',period='first_year',comp_type='total_compensation');r['flags']+=['possible_same_recruiter_mandate_as_baseline_2026-09-04; excluded_from_net_new_minimum']
  if '57480626' in u:r.update(raw_salary_snippet='Salary: £600-800k target range; Significant salary + bonus',salary_min=600000,salary_max=800000,currency='GBP',period=None,comp_type='target_salary_plus_bonus_split_unknown');r['flags']+=['period_not_stated']
  if '57428662' in u:r['flags']+=['salary_10000_80000_source_value_suspicious_possible_typo_not_corrected; excluded_from_comparable_salary']
  level=bool(re.search(r'\b(senior|lead|principal)\b',title,re.I))
  cxx='C++' in title or 'C++' in desc
  locstr=str(location);london=bool(re.search(r'London|Enfield|EC1M',locstr,re.I))
  if 'Waltham Cross' in locstr:london=False;r['flags']+=['outside_London_Waltham_Cross']
  if '57459421' in u:london=False;level=False;r['flags']+=['header_London_but_body_Cambridge; minimum_2_to_5_years; optional_Cpp_or_Rust']
  if '27712' in u:london=False;r['flags']+=['actual_location_Surrey_not_London; optional_C_or_Cpp']
  if '26626' in u:r['flags']+=['explicit_Filled'];level=True
  if '6af1e6d5' in u:r['flags']+=['same_Hadteg_Senior_Cpp_mandate_as_6af1e790']
  r['geography_evidence']=locstr;r['seniority_evidence']='explicit title' if level else 'not established';r['segment']='trading_finance' if re.search(r'quant|trading|hedge|market.mak',title+' '+desc,re.I) else 'general_cpp'
  r['strict_eligible']=cxx and level and london and 'explicit_Filled' not in r['flags']
  matches=[]
  for path,b in baseline:
   bu=b.get('url') or b.get('redirect_url') or b.get('source_url') or ''
   sameurl=canonical(bu)==cu
   title_score=SequenceMatcher(None,norm(title),norm(b.get('title',''))).ratio()
   sameemp=norm(emp) and (norm(emp) in norm(employer(b)) or norm(employer(b))==norm(emp))
   bd=b.get('description','');desc_score=SequenceMatcher(None,norm(desc)[:300],norm(bd)[:300]).ratio() if isinstance(bd,str) and len(bd)>100 else 0
   if sameurl or (sameemp and title_score>=.83) or (desc_score>=.90 and title_score>=.60):
    matches.append({'baseline':path,'title':b.get('title'),'employer':employer(b),'url':bu,'basis':'url' if sameurl else 'same_employer_similar_title' if sameemp and title_score>=.83 else 'description_similarity','description_similarity':round(desc_score,3)})
  r['baseline_matches']=matches;r['net_new_strict']=r['strict_eligible'] and not matches and not any('same_' in z or 'possible_same_recruiter' in z for z in r['flags'])
  r['salary_with_amount_period']=r['salary_min'] is not None or r['salary_max'] is not None
  r['salary_with_amount_period']=bool(r['salary_with_amount_period'] and r['period'])
  r['comparable_salary_candidate']=r['net_new_strict'] and r['salary_with_amount_period'] and not any('suspicious' in f for f in r['flags'])
  records.append(r)
 out={'observed_at':datetime.now(timezone.utc).isoformat(),'notice':'Bounded experiment. Anonymous recruiter mandates are not independent employers. New strict is a conservative attributed-ad minimum, not independence. Source listings can be stale. Unknown pay period/tax remains null.','records':records}
 (P/'candidates.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));(P/'new_strict_candidates.json').write_text(json.dumps([r for r in records if r['net_new_strict']],ensure_ascii=False,indent=2))
 summary={'http_attempts':len(attempts),'raw_unique_detail_records':len(records),'strict_records':sum(r['strict_eligible'] for r in records),'new_strict_records':sum(r['net_new_strict'] for r in records),'new_strict_with_amount_and_period':sum(r['net_new_strict'] and r['salary_with_amount_period'] for r in records),'new_strict_salary_candidates_excluding_source_anomaly':sum(r['comparable_salary_candidate'] for r in records)}
 (P/'summary.json').write_text(json.dumps(summary,indent=2));print(summary)
 for r in records:
  if r['strict_eligible']:print(r['title'],r['employer'],r['net_new_strict'],r['raw_salary_snippet'],[(x['title'],x['basis']) for x in r['baseline_matches']])
 assert salary('£60,000 to £65,000 a year')==(60000,65000,'GBP','year')
 assert salary('£600-800k target range')==(None,None,None,None)
 assert not any(r['net_new_strict'] and ('Waltham Cross' in str(r['location']) or 'explicit_Filled' in r['flags']) for r in records)
if __name__=='__main__':build()
