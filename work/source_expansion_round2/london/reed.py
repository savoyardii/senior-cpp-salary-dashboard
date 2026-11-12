from collect import *
a=json.loads((ROOT/'extra_attempts.json').read_text());seed=next(x for x in a if 'reed.co.uk' in x['url']);links=[]
for z in seed['links']:
 z=z.split('?')[0]
 if re.fullmatch(r'/jobs/[^/]+/\d+',z) and any(q in z for q in ['software-engineer-c','senior-c','quant-developer-c','team-lead-c']):links.append(urllib.parse.urljoin(seed['url'],z))
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:rows=list(ex.map(fetch,dict.fromkeys(links)))
(ROOT/'reed_attempts.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
for x in rows:
 print(x['url'],x.get('http_status'))
 if x.get('http_status')==200:print((ROOT/x['text_file']).read_text()[350:4000])
