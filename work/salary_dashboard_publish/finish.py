import json
import sys
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/api_connector'))
from auto_monitor import build_monitor

OUT = ROOT / 'outputs'
DIST = Path(__file__).parent / 'dist'
OUT.mkdir(exist_ok=True)
DIST.mkdir(exist_ok=True)

rows = []
for name in ('switzerland', 'london', 'russia'):
    audited = json.loads((ROOT / 'work/expanded_sample' / f'{name}_audited.json').read_text())
    assert audited and all('description_reviewed' in row for row in audited)
    rows.extend(audited)

template = (Path(__file__).parent / 'template.html').read_text()
snapshot_path = ROOT / 'work/api_connector/data/latest.json'
snapshot = json.loads(snapshot_path.read_text()) if snapshot_path.exists() else {'sources': []}
monitor = build_monitor(snapshot)
audit_json = json.dumps(monitor, ensure_ascii=False, indent=2)
(OUT / 'salary_api_audit.json').write_text(audit_json)
(DIST / 'salary_api_audit.json').write_text(audit_json)
page = template.replace('__DATA__', json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c'))
page = page.replace('__API_STATS__', json.dumps(monitor, ensure_ascii=False).replace('<', '\\u003c'))
assert '__DATA__' not in page and '__API_STATS__' not in page and '__MANUAL_STATS__' not in page

(OUT / 'salary_dashboard.html').write_text(page)
(ROOT / 'outputs/salary_sample_audited.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
(DIST / 'index.html').write_text(page)
def vacancy_count(count):
    last_two = count % 100
    last = count % 10
    word = 'вакансия' if last == 1 and last_two != 11 else 'вакансии' if 2 <= last <= 4 and not 12 <= last_two <= 14 else 'вакансий'
    return f'{count} {word}'


stat_cards = []
for region, region_label in (('Switzerland', 'Швейцария'), ('London, UK', 'Лондон'), ('Russia', 'Россия')):
    region_groups = [group for group in monitor['groups'] if group['region'] == region]
    salary_groups = [group for group in region_groups
                     if group['seniority'] == 'explicit' and group.get('salary')]
    structured = sum(any(pay.get('tax_basis') in {'gross', 'net'}
                         and pay.get('compensation') in {'base', 'package'}
                         and pay.get('period') in {'month', 'year'}
                         for pay in group.get('salary', [])) for group in salary_groups)
    qualified = next(item['qualified_roles'] for item in monitor['regions'] if item['region'] == region)
    stat_cards.append(
        '<div class="stat"><strong>{}: {}</strong><span>прошли фильтры роли и локального рынка</span>'
        '<p class="muted">Senior-вакансий с зарплатой: {}; из них явно указаны gross/net, base/package и период: {}.</p></div>'
        .format(region_label, vacancy_count(qualified), len(salary_groups), structured)
    )
methodology = (Path(__file__).parent / 'methodology_template.html').read_text()
observed_at = monitor.get('observed_at')
observed_label = (datetime.fromisoformat(observed_at).strftime('%d.%m.%Y %H:%M UTC')
                  if observed_at else 'нет успешного снимка')
methodology = methodology.replace(
    '__OBSERVED_AT__', escape(observed_label)
).replace('__REGION_STATS__', ''.join(stat_cards))
(DIST / 'methodology.html').write_text(methodology)
(ROOT / 'work/expanded_sample/dashboard_check.js').write_text(page.split('<script>')[1].split('</script>')[0])
print(f"Dashboard built: {len(rows)} audited reference records; {sum(r['qualified_roles'] for r in monitor['regions'])} code-filtered API roles")
