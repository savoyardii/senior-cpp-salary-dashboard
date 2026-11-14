#!/usr/bin/env python3
"""Bounded public HTML collection. No keys, packages, AI, registration or block retries."""
import json,re,urllib.request,urllib.error,hashlib,html,concurrent.futures
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent
class Parser(HTMLParser):
 def __init__(self):super().__init__();self.text=[];self.links=[];self.json=[];self.capture=False;self.buf='';self.skip=0
 def handle_starttag(self,t,a):
  a=dict(a)
  if t=='a' and a.get('href'):self.links.append(a['href'])
  if t in ['script','style']:self.skip+=1
  if t=='script' and a.get('type')=='application/ld+json':self.capture=True;self.buf=''
 def handle_endtag(self,t):
  if t=='script' and self.capture:
   try:self.json.append(json.loads(self.buf))
   except ValueError:pass
   self.capture=False
  if t in ['script','style']:self.skip=max(0,self.skip-1)
 def handle_data(self,d):
  if self.capture:self.buf+=d
  if not self.skip:self.text.append(d)
def parse(s):
 p=Parser();p.feed(s);return p
ATTEMPTS=[]
def fetch(url):
 name=hashlib.sha256(url.encode()).hexdigest()[:16]
 for previous_file in ['attempts.json','extra_attempts.json','reed_attempts.json']:
  previous_path=ROOT/previous_file
  if previous_path.exists():
   for previous in json.loads(previous_path.read_text()):
    if previous['url']==url and previous.get('http_status') in [401,403,405,410,451]:
     return dict(previous, access='previous denial/gone retained; not retried')
 try:
  with urllib.request.urlopen(url,timeout=22) as r:
   b=r.read();status=r.status;final=r.url
  (ROOT/'raw'/f'{name}.html').write_bytes(b);s=b.decode('utf-8',errors='replace');p=parse(s)
  (ROOT/'raw'/f'{name}.txt').write_text('\n'.join(x.strip() for x in p.text if x.strip()))
  out={'url':url,'final_url':final,'http_status':status,'raw_file':f'raw/{name}.html','text_file':f'raw/{name}.txt','bytes':len(b),'jsonld':p.json,'links':p.links}
 except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as e:out={'url':url,'http_status':getattr(e,'code',None),'error':str(e),'access':'not retried; no bypass'}
 return out
SEEDS=[
'https://www.jobs.service.gov.uk/jobs/search?keywords=C%2B%2B&location=London',
'https://www.jobs.service.gov.uk/jobs/search?keywords=Senior+Software+Engineer&location=London',
'https://www.reed.co.uk/jobs/c-plus-plus-developer-jobs-in-london',
'https://www.reed.co.uk/jobs/senior-c-plus-plus-developer-jobs-in-london',
'https://www.ecmselection.co.uk/jobs?keywords=C%2B%2B&location=London',
'https://www.client-server.com/jobs?keywords=C%2B%2B',
'https://www.hunterbond.com/job/senior-c%2B%2B-software-developer/',
'https://www.quant-capital.co.uk/jobs/c-enior-software-engineer-trading/',
'https://www.efinancialcareers.co.uk/jobs-C%2B%2B-London',
'https://www.totaljobs.com/jobs/senior-c%2b%2b/in-london',
'https://www.cv-library.co.uk/senior-cplusplus-developer-jobs-in-london',
'https://www.jobs.service.gov.uk/jobs/6af1e7909ec5a6cfe2a00adb',
'https://www.ecmselection.co.uk/jobs']
def main():
 ROOT.joinpath('raw').mkdir(exist_ok=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:attempts=list(ex.map(fetch,SEEDS))
 Path(ROOT/'seed_attempts.json').write_text(json.dumps(attempts,indent=2))
 links=[];reed_links=[]
 for x in attempts:
  if x.get('http_status')!=200:continue
  for link in x.get('links',[]):
   absolute=urllib.parse.urljoin(x['url'],link)
   if re.fullmatch(r'https://www.jobs.service.gov.uk/jobs/[a-f0-9]{20,}',absolute) and absolute not in SEEDS:links.append(absolute)
   if 'ecmselection.co.uk' in absolute and '/vacancies/' in absolute:links.append(absolute)
   if 'client-server.com' in absolute and re.search(r'/job/.*(senior|lead).*c-',absolute,re.I):links.append(absolute)
   reed_url=absolute.split('?')[0].split('#')[0]
   if re.fullmatch(r'https://www\.reed\.co\.uk/jobs/[^/]+/\d+',reed_url):reed_links.append(reed_url)
 links=list(dict.fromkeys(links))[:35]+list(dict.fromkeys(reed_links))[:20]
 with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:details=list(ex.map(fetch,links))
 attempts+=details
 (ROOT/'attempts.json').write_text(json.dumps(attempts,ensure_ascii=False,indent=2))
 print(json.dumps({'attempted':len(attempts),'statuses':[{k:x.get(k) for k in ['url','http_status','bytes','error']} for x in attempts]},indent=2))
if __name__=='__main__':main()
