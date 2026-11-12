"""Refresh recurring APIs and rebuild the static dashboard; Adzuna is pilot-only."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import hashlib
import importlib.util
import subprocess
import sys

import collect

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = collect.OUT_FILE


def successful(source):
    requests = source.get('requests', [])
    return bool(requests) and all(row.get('status') == 'ok' for row in requests)


def update_fx(previous=None):
    now = datetime.now(timezone.utc).isoformat()
    try:
        data, _ = collect.request_json('https://open.er-api.com/v6/latest/USD')
        rates = data.get('rates', {})
        selected = {code: rates[code] for code in ('USD', 'CHF', 'GBP', 'RUB')}
        if data.get('result') != 'success' or data.get('base_code') != 'USD' or any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in selected.values()):
            raise ValueError('invalid_rate_response')
        return {'provider': 'ExchangeRate-API', 'base': 'USD', 'updated_at': data.get('time_last_update_utc'),
                'fetched_at': now, 'rates': selected}
    except Exception as exc:
        kept = deepcopy(previous) if previous else {'provider': 'ExchangeRate-API', 'base': 'USD', 'rates': {}}
        kept['refresh_error'] = type(exc).__name__
        return kept


def archive_snapshot(snapshot):
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
    stamp = str(snapshot.get('observed_at') or 'unknown').replace(':', '-').replace('/', '-')
    archive = SNAPSHOT.parent / 'snapshots'
    archive.mkdir(parents=True, exist_ok=True)
    target = archive / f"{stamp}-{hashlib.sha256(payload.encode()).hexdigest()[:12]}.json"
    if not target.exists():
        with target.open('x') as handle:
            handle.write(payload)


def public_jobboards(previous, now):
    sources = []
    tracked = {}
    for prior in previous.get('sources', []):
        for record in prior.get('records', []):
            raw = record.get('raw', {})
            tracked.setdefault(prior.get('source'), set()).add(str(raw.get('source_id') or raw.get('id') or ''))
            tracked[prior.get('source')].add(str(raw.get('url') or ''))
    tasks = [
        (ROOT / 'work/source_expansion_round2/russia/collect.py', ['--live'], None),
        (ROOT / 'work/source_expansion_round2/london/collect.py', [], ROOT / 'work/source_expansion_round2/london'),
    ]
    errors = {}
    for script, args, cwd in tasks:
        try:
            subprocess.run([sys.executable, str(script), *args], cwd=cwd or ROOT, check=True, capture_output=True, text=True, timeout=240)
            if 'london' in str(script):
                subprocess.run([sys.executable, str(script.parent / 'normalize.py')], cwd=script.parent, check=True, capture_output=True, text=True, timeout=120)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            errors['Russia' if 'russia' in str(script) else 'London'] = type(exc).__name__

    for country, folder, region_filter in (
        ('Russia', ROOT / 'work/source_expansion_round2/russia', {'Russia'}),
        ('London', ROOT / 'work/source_expansion_round2/london', {'London, UK'}),
    ):
        previous_sources = {row.get('source'): row for row in previous.get('sources', [])}
        path = folder / 'candidates.json'
        rows = []
        collected_at = now
        try:
            data = json.loads(path.read_text())
            collected_at = data.get('observed_at') or now
            for raw in data.get('records', []):
                if not raw.get('strict_eligible'):
                    continue
                prior_keys = tracked.get(raw.get('source'), set())
                already_tracked = str(raw.get('source_id') or raw.get('id') or '') in prior_keys or str(raw.get('url') or '') in prior_keys
                is_new = not raw.get('baseline_matches') and bool(raw.get('net_new', raw.get('net_new_strict', False)))
                if not already_tracked and not is_new:
                    continue
                region = raw.get('region') or ('London, UK' if country == 'London' else None)
                if region not in region_filter:
                    continue
                raw = deepcopy(raw)
                raw['observed_at'] = collected_at
                if country == 'London':
                    raw['country'] = raw.get('country') or 'GB'
                rows.append({'region': region, 'queries': ['public jobboard'], 'raw': raw})
        except (OSError, ValueError):
            pass
        grouped = {}
        for record in rows:
            grouped.setdefault(record['raw']['source'], []).append(record)
        for name, records in grouped.items():
            sources.append({'source': name, 'records': records, 'status': 'queried', 'observed_at': collected_at,
                            'retrieved_at': collected_at, 'refresh_policy': 'weekly',
                            'refresh_error': errors.get(country)})
        old_country = [row for row in previous_sources.values() if row.get('source') in ({'Zarplata', 'Yandex Delivery Careers', 'Kaspersky Careers', 'Sobes.tech', 'Quick Offer'} if country == 'Russia' else {'UK Government Work Hub', 'Reed', 'Hunter Bond', 'ECM Selection'})]
        fresh_names = {row['source'] for row in sources}
        for old in old_country:
            if old['source'] not in fresh_names:
                kept = deepcopy(old)
                kept['refresh_attempted_at'] = now
                kept['refresh_error'] = errors.get(country) or 'no_strict_current_records; retained prior snapshot'
                sources.append(kept)
    static_names = {'ITJobsWatch', 'Finder'}
    for row in previous.get('sources', []):
        if row.get('source') in static_names and row.get('refresh_policy') == 'one_time_static':
            sources.append(row)
    return sources


def load_collector(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expanded_public_sources(previous, now):
    """Collect permitted public feeds and employer ATS listings; retain last good data per feed."""
    folder = ROOT / 'work/source_expansion_round3'
    old = {row.get('source'): row for row in previous.get('sources', [])}
    fresh = []
    errors = {}

    def add(source, records, error=None, observed=None):
        if error:
            kept = deepcopy(old[source]) if source in old else {
                'source': source, 'records': [], 'observed_at': None, 'status': 'error', 'refresh_policy': 'weekly'}
            kept.update(refresh_attempted_at=now, refresh_error=error)
            fresh.append(kept)
            return
        fresh.append({'source': source, 'records': records, 'status': 'queried',
                      'observed_at': observed or now, 'retrieved_at': now, 'refresh_policy': 'weekly'})

    def collect(name, relative_path, function='collect', **kwargs):
        module = load_collector(name, folder / relative_path)
        return getattr(module, function)(**kwargs)

    try:
        rows = collect('greenhouse_collector', 'ats/collect.py')
        for row in rows:
            source = row['source']
            records = [{'region': item['region'], 'query': 'public ATS board C++', 'raw': item}
                       for item in row.get('records', [])]
            add(source, records, None if row.get('status') == 'queried' else str(row.get('request', {}).get('status')),
                row.get('observed_at'))
    except Exception as exc:
        errors['greenhouse'] = type(exc).__name__
        for source in ('Greenhouse: DV Trading', 'Greenhouse: DRW', 'Greenhouse: Engineers Gate',
                       'Greenhouse: GSR', 'Greenhouse: iSAM', 'Greenhouse: Qube Research & Technologies',
                       'Greenhouse: Maven Securities', 'Greenhouse: Point72'):
            add(source, [], errors['greenhouse'])

    try:
        rows = collect('lever_ashby_collector', 'lever_ashby/collect.py')
        for row in rows:
            add(row['source'], row.get('records', []), None if row.get('status') == 'queried' else
                ', '.join(str(req.get('status')) for req in row.get('requests', [])), row.get('observed_at'))
    except Exception as exc:
        errors['lever_ashby'] = type(exc).__name__
        for source in ('Lever: MARGO Group', 'Lever: Crypto.com', 'Lever: Wintermute',
                       'Lever: Zurich Instruments', 'Ashby: Teza Technologies', 'Ashby: TradingHub',
                       'Ashby: Smarkets', 'Ashby: Keyrock'):
            add(source, [], errors['lever_ashby'])

    try:
        result = collect('telegram_collector', 'telegram/collect.py', channels=(
            'cppdevjob', 'c_rabota', 'switzerlanddevjobs', 'devitjobs'))
        channel_status = {row['channel']: row['status'] for row in result.get('attempts', []) if row.get('page') == 1}
        for channel in ('cppdevjob', 'c_rabota', 'switzerlanddevjobs', 'devitjobs'):
            source = f'Telegram @{channel}'
            records = [{'region': row['region'], 'query': 'public Telegram preview', 'raw': row}
                       for row in result.get('records', []) if row.get('source') == source and row.get('region')]
            status = channel_status.get(channel)
            add(source, records, None if status == 'ok' else str(status or 'no successful page'), result.get('observed_at'))
    except Exception as exc:
        errors['telegram'] = type(exc).__name__
        for channel in ('cppdevjob', 'c_rabota', 'switzerlanddevjobs', 'devitjobs'):
            add(f'Telegram @{channel}', [], errors['telegram'])

    try:
        result = collect('hh_rss_collector', 'russia/hh_rss.py')
        records = [{'region': 'Russia', 'query': 'HeadHunter public RSS', 'raw': row}
                   for row in result.get('records', [])]
        error = None if result.get('status') == 'queried' and any(r.get('status') == 'ok' for r in result.get('requests', [])) else result.get('status', 'no successful query')
        add('HeadHunter RSS', records, error, result.get('observed_at'))
    except Exception as exc:
        add('HeadHunter RSS', [], type(exc).__name__)

    for name, path in (('SwissDevJobs', 'uk_ch/swissdevjobs.py'), ('Himalayas', 'uk_ch/himalayas.py')):
        try:
            result = collect(name.lower() + '_collector', path)
            records = result.get('records', [])
            if name == 'SwissDevJobs':
                records = [{'region': row['region'], 'query': 'SwissDevJobs RSS', 'raw': row['raw']} for row in records]
            add(name, records, None if result.get('status') == 'queried' else result.get('status'), result.get('observed_at'))
        except Exception as exc:
            add(name, [], type(exc).__name__)
    return fresh


def save_and_build(snapshot):
    if SNAPSHOT.exists():
        archive_snapshot(json.loads(SNAPSHOT.read_text()))
    archive_snapshot(snapshot)
    temp = SNAPSHOT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    temp.replace(SNAPSHOT)
    subprocess.run([sys.executable, str(ROOT / 'work/salary_dashboard_publish/finish.py')], check=True)


def refresh():
    now = datetime.now(timezone.utc).isoformat()
    old = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else {'sources': []}
    previous = {row.get('source'): row for row in old.get('sources', [])}
    fx = update_fx(old.get('fx'))
    keys = collect.secrets()
    fresh = [
        collect.dedupe(collect.headcount(keys.get('HEADCOUNTLABS_API_KEY', ''))),
        collect.dedupe(collect.superjob(keys.get('SUPERJOB_APP_SECRET', ''))),
        collect.dedupe(collect.trudvsem()),
    ]
    sources = []
    for source in fresh:
        if successful(source):
            source['retrieved_at'] = now
            sources.append(source)
        elif source['source'] in previous:
            kept = deepcopy(previous[source['source']])
            kept['refresh_attempted_at'] = now
            kept['refresh_error'] = ', '.join(sorted({row.get('status', 'unknown') for row in source.get('requests', []) if row.get('status') != 'ok'})) or source.get('status') or 'no_successful_requests'
            sources.append(kept)
        else:
            source['retrieved_at'] = None
            sources.append(source)
    sources.extend(public_jobboards(old, now))
    sources.extend(expanded_public_sources(old, now))
    adzuna = previous.get('Adzuna')
    if adzuna:
        adzuna = deepcopy(adzuna)
        adzuna['refresh_policy'] = 'one-time pilot; excluded from recurring refreshes'
        adzuna.setdefault('pilot_observed_at', adzuna.get('observed_at'))
        sources.append(adzuna)
    snapshot = {
        'observed_at': now,
        'fx': fx,
        'refresh_policy': 'Weekly API, public RSS/Telegram preview, and employer ATS refresh. Adzuna is a static pilot snapshot and is never queried here.',
        'sources': sources,
    }
    assert all(row['source'] != 'Adzuna' or row.get('requests_used', 0) <= row.get('request_cap', 0) for row in sources)
    SNAPSHOT.parent.mkdir(exist_ok=True)
    save_and_build(snapshot)
    print('Dashboard refreshed:', now)
    for source in sources:
        age = source.get('retrieved_at') or source.get('observed_at') or 'not available'
        print(f"{source['source']}: {len(source.get('records', []))} records; data date={age}")


def refresh_fx_only():
    snapshot = json.loads(SNAPSHOT.read_text())
    snapshot['fx'] = update_fx(snapshot.get('fx'))
    save_and_build(snapshot)
    print('FX rates refreshed:', snapshot['fx'].get('updated_at') or snapshot['fx'].get('refresh_error'))


if __name__ == '__main__':
    if sys.argv[1:] == ['--fx-only']:
        refresh_fx_only()
    elif not sys.argv[1:]:
        refresh()
    else:
        raise SystemExit('Usage: refresh.py [--fx-only]')
