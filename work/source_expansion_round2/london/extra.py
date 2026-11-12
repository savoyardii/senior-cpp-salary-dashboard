from collect import *
URLS=['https://www.ecmselection.co.uk/jobs?keywords=C%2B%2B&location=London&page=2','https://www.ecmselection.co.uk/jobs?keywords=C%2B%2B&location=London&page=3','https://www.ecmselection.co.uk/jobs/27712/senior-engineer','https://www.ecmselection.co.uk/jobs/26626/c-plus-plus-software-developer','https://www.reed.co.uk/jobs/senior-c-plus-plus-developer-jobs-in-london','https://www.jobs.service.gov.uk/jobs/search?keywords=Senior+C%2B%2B&location=London&pageNumber=2']
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:a=list(ex.map(fetch,URLS))
p=ROOT/'extra_attempts.json';p.write_text(json.dumps(a,ensure_ascii=False,indent=2))
for x in a:
 print(x['url'],x.get('http_status'),str(x.get('jsonld'))[:1000])
 if x.get('http_status')==200:
  t=(ROOT/x['text_file']).read_text();print(t[1600:4500] if 'page=' in x['url'] else t[0:4500])
