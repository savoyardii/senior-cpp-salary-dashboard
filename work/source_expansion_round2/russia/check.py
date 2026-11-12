"""Small saved-evidence checks: financial boundaries, false C++ tags, dedupe."""
import json,pathlib
b=pathlib.Path(__file__).resolve().parent
rows=json.loads((b/'candidates.json').read_text())['records'];by={r['source_id']:r for r in rows}
z=by['138515561']
assert (z['salary_min'],z['salary_max'],z['period'],z['tax_basis'])==(400000,400000,'MONTH','net')
assert z['strict_eligible'] and z['net_new'] and 'знание С/С++' in z['description']
assert by['139351881']['salary_max'] is None
assert by['139121325']['salary_max'] is None
assert not by['45543']['strict_eligible']
assert not by['138782073']['strict_eligible']
assert not by['aae698e5-1579-4388-90e6-b1b6bd2c5300']['strict_eligible']
assert not by['25783']['net_new'] and by['25783']['baseline_matches']
q=by['112846'];assert q['salary_min'] is None and q['salary_max']==320000 and q['period']=='MONTH' and not q['strict_eligible']
strict=[r for r in rows if r['strict_eligible'] and r['net_new']]
assert len(strict)==3 and sum(r['salary_min'] is not None or r['salary_max'] is not None for r in strict)==1
assert {r['source_id'] for r in strict}=={'138515561','138678458','delivery-infrastructure-developer'}
assert len([r for r in rows if r['source']=='Zarplata'])==15
print('PASS: saved-evidence salary bounds, C-only/optional exclusions, status/dedupe, all15 Zarplata pages')
