"""Deterministic filters for the recurring job-market monitor. No model calls."""
import re
import unicodedata
import html
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlsplit, urlunsplit

CPP = re.compile(r'c\s*\+\s*\+|с\s*\+\s*\+', re.I)
ROLE = re.compile(r'engineer|developer|programmer|software|quant(?:itative)? developer|инженер|разработчик|программист', re.I)
SENIOR_TITLE = re.compile(r'\b(senior|sr\.?|lead|leader|staff|principal)\b|старш|ведущ|главн|тимлид', re.I)
EXPERIENCE = re.compile(r'(?<![\d–—-])\b(?P<low>\d{1,2})\s*(?:(?:[-–—]|\bto\b|\band\b|\bдо\b)\s*(?P<high>\d{1,2}))?\s*\+?\s*(?:years?|yrs?|лет|года?|год)\b', re.I)
JUNIOR = re.compile(r'\b(junior|graduate|intern|internship|trainee|entry[- ]level)\b|стаж[её]р|младш', re.I)
OUT_OF_SCOPE = re.compile(r'machine learning|\bml engineer|машинн\w*\s+обучен|researcher|\btrader\b|учител|военнослуж|chauffeur|driver|водител', re.I)
NUMBER = r'(?:\d{1,3}(?:[ ,.]\d{3})+(?:[,.]\d+)?|\d+(?:[,.]\d+)?)'
BONUS = re.compile(r'total comp|target comp|\bTC\b|\bOTE\b|bonus|equity|sign[- ]?on|one[- ]?time|единоврем|преми|бонус|подъ[её]мн', re.I)
NORMALIZED_SOURCES = {'SwissDevJobs', 'HeadHunter RSS', 'Himalayas', 'DevITjobs UK RSS', 'Hiring Index',
                      'ictjobs.ch RSS', 'YubHub', 'Active Vacancies', 'JobServe RSS', 'Habr Career RSS',
                      'Jooble API', 'Careerjet API', 'Techmap API'}
NORMALIZED_PREFIXES = ('Telegram @', 'Greenhouse:', 'HH RSS:', 'Lever:', 'Ashby:')


def normalized_source(source):
    return source in NORMALIZED_SOURCES or str(source or '').startswith(NORMALIZED_PREFIXES)


def value(item):
    return item.get('value', '') if isinstance(item, dict) else (item or '')


def clean(text):
    text = unicodedata.normalize('NFKC', str(text or '')).casefold().replace('с++', 'c++')
    return re.sub(r'[^\w+#]+', ' ', text, flags=re.UNICODE).strip()


def fields(source, record):
    raw = record['raw']
    if normalized_source(source):
        return str(raw.get('title') or ''), str(raw.get('employer') or ''), str(raw.get('description') or ''), raw
    if source in {'Zarplata', 'UK Government Work Hub', 'Yandex Delivery Careers', 'Kaspersky Careers', 'ITJobsWatch', 'Finder', 'Reed', 'Hunter Bond'}:
        return str(raw.get('title', '')), str(raw.get('employer') or ''), str(raw.get('description') or ''), raw
    if source == 'Headcount Labs':
        return str(value(raw.get('title'))), str(value(raw.get('employer_name'))), str(value(raw.get('description'))), raw
    if source == 'SuperJob':
        return str(raw.get('profession', '')), str(raw.get('firm_name') or value((raw.get('client') or {}).get('title'))), str(raw.get('vacancyRichText', '')), raw
    if source == 'Adzuna':
        return str(raw.get('title', '')), str(value((raw.get('company') or {}).get('display_name'))), str(raw.get('description', '')), raw
    if source == 'Работа России':
        description = ' '.join(str(raw.get(key) or '') for key in ('duty', 'requirement', 'requirements', 'qualification', 'skills'))
        return str(raw.get('job-name', '')), str((raw.get('company') or {}).get('name', '')), description, raw
    return '', '', '', raw


def location_rows(source, region, raw):
    if normalized_source(source):
        location = raw.get('location') or raw.get('city') or ''
        if isinstance(location, list):
            location = ', '.join(str(x) for x in location if x)
        country = raw.get('country') or ''
        return [{'city': str(raw.get('city') or location),
                 'country': str(country), 'remote': bool(raw.get('remote'))}]
    if source in {'Zarplata', 'UK Government Work Hub', 'Yandex Delivery Careers', 'Kaspersky Careers', 'ITJobsWatch', 'Finder', 'Reed', 'Hunter Bond'}:
        location = raw.get('location') or raw.get('city') or ''
        if isinstance(location, list):
            location = ', '.join(str(x) for x in location if x)
        city = raw.get('city') or str(location)
        return [{'city': str(city), 'country': raw.get('country') or ''}]
    if source == 'SuperJob':
        return [{'city': (raw.get('town') or {}).get('title', ''), 'country': 'RU', 'remote': False}]
    if source == 'Adzuna':
        loc = raw.get('location') or {}
        return [{'city': loc.get('display_name') or ' '.join(loc.get('area') or []),
                 'country': 'GB' if region == 'London, UK' else '', 'remote': False}]
    if source == 'Работа России':
        addresses = (raw.get('addresses') or {}).get('address') or []
        address = addresses[0].get('location', '') if addresses else ''
        region_name = (raw.get('region') or {}).get('name', '')
        return [{'city': address or region_name, 'country': 'RU', 'remote': False}]
    rows = []
    for posting in raw.get('postings', []):
        loc = value(posting.get('location'))
        if isinstance(loc, dict):
            rows.append(loc)
    if not rows:
        for loc in raw.get('locations', []):
            loc = value(loc)
            if isinstance(loc, dict):
                rows.append(loc)
    return rows


def local_market(region, locations):
    for loc in locations:
        country = str(loc.get('country') or '').upper()
        city = str(loc.get('city') or '').casefold()
        alternatives = loc.get('alternatives') or []
        alt_countries = {str((x.get('value', x)).get('country') or '').upper() for x in alternatives if isinstance(x, dict) and isinstance(x.get('value', x), dict)}
        swiss_city = re.search(r'\b(?:bern|zug|zürich|zurich|stefa|stäfa|geneva|genève|basel|lausanne|chur|winterthur|lucerne|luzern|st gallen|lugano|biel|bienna)\b', city, re.I)
        if region == 'Switzerland' and (country == 'CH' or ('CH' in alt_countries and loc.get('remote')) or (not country and swiss_city)):
            return True
        london_postcode = re.search(r'\b(?:EC|WC|N|NW|E|SE|SW|W|BR|CR|DA|EN|HA|IG|KT|RM|SM|TW|UB|WD)\d[A-Z]?\b', city, re.I)
        if region == 'London, UK' and (re.search(r'\blondon\b', city) or london_postcode) and country in {'GB', 'UK', ''}:
            return True
        if region == 'Russia' and (country == 'RU' or ('RU' in alt_countries and loc.get('remote'))):
            return True
    return False


def active(source, raw):
    if str(source or '').startswith('Telegram @'):
        stamp = raw.get('published_at')
        try:
            published = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - timedelta(days=90) <= published <= datetime.now(timezone.utc) + timedelta(days=1)
        except (TypeError, ValueError):
            return False
    if normalized_source(source):
        if source.startswith('Greenhouse:'):
            return not raw.get('is_closed')
        expiry = raw.get('expires_at') or raw.get('validThrough')
        published = raw.get('published_at') or raw.get('source_posted_at') or raw.get('first_published')
        stamp = expiry or published
        try:
            if isinstance(stamp, (int, float)):
                if stamp > 100_000_000_000:
                    stamp /= 1000
                date = datetime.fromtimestamp(stamp, timezone.utc)
            else:
                try:
                    date = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
                except ValueError:
                    from email.utils import parsedate_to_datetime
                    date = parsedate_to_datetime(str(stamp))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return date >= datetime.now(timezone.utc) if expiry else date >= datetime.now(timezone.utc) - timedelta(days=90)
        except (TypeError, ValueError, OverflowError):
            return False
    if source == 'Headcount Labs':
        postings = raw.get('postings', [])
        return not raw.get('stale') and (not postings or any(p.get('posting_status') == 'listed' for p in postings))
    if source == 'Adzuna':
        created = raw.get('created')
        if created:
            try:
                if isinstance(created, (int, float)):
                    date = datetime.fromtimestamp(created, timezone.utc)
                else:
                    date = datetime.fromisoformat(str(created).replace('Z', '+00:00'))
                    if date.tzinfo is None:
                        date = date.replace(tzinfo=timezone.utc)
                return date >= datetime.now(timezone.utc) - timedelta(days=90)
            except (TypeError, ValueError, OverflowError, OSError):
                return False
        return True  # The pilot API result was live at collection; age is unknown without `created`.
    if source == 'Работа России':
        stamp = raw.get('date_modify') or raw.get('creation-date')
        try:
            updated = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            return updated >= datetime.now(timezone.utc) - timedelta(days=90)
        except (AttributeError, ValueError):
            return False
    if source in {'Zarplata', 'UK Government Work Hub', 'Yandex Delivery Careers', 'Kaspersky Careers', 'ITJobsWatch', 'Finder', 'Reed', 'Hunter Bond'}:
        expiry = raw.get('expires_at') or raw.get('validThrough')
        if expiry:
            try:
                stamp = datetime.fromisoformat(str(expiry).replace('Z', '+00:00'))
            except ValueError:
                try:
                    stamp = datetime.strptime(str(expiry), '%d %b %Y').replace(tzinfo=timezone.utc)
                except ValueError:
                    return False
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return stamp >= datetime.now(timezone.utc)
        observed = raw.get('observed_at')
        try:
            stamp = datetime.fromisoformat(str(observed).replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return stamp >= datetime.now(timezone.utc) - timedelta(days=90)
        except (TypeError, ValueError):
            return False
    return not raw.get('is_closed') and not raw.get('is_archive')


def senior(title, description):
    if JUNIOR.search(title):
        return False
    explicit_senior = bool(SENIOR_TITLE.search(title))
    # Only experience requirements qualify; company age and contract duration do not.
    for match in EXPERIENCE.finditer(description):
        context = description[max(0, match.start() - 70):match.end() + 90]
        if re.search(r'is ideal|preferred|nice to have|желател', description[match.end():match.end() + 35], re.I):
            continue
        if re.search(r'sales|marketing|recruit|accounting|продаж|маркетинг|бухгалтер', context, re.I):
            continue
        if explicit_senior and int(match['low']) <= 3 and re.search(r'experience|professional|commercial|опыт|стаж|разработ', context, re.I):
            return False
        if int(match['low']) >= 5 and re.search(r'experience|professional|commercial|опыт|стаж|разработ', context, re.I):
            if not re.search(r'up to|at most|до\s*$', description[max(0, match.start() - 15):match.start()], re.I):
                return True
    return explicit_senior


def exclusion_reasons(source, record):
    title, employer, description, raw = fields(source, record)
    reasons = []
    if not ROLE.search(title) or OUT_OF_SCOPE.search(title):
        reasons.append('not_software_development_role')
    if JUNIOR.search(title):
        reasons.append('junior_role')
    core = cpp_is_required(title, description)
    if not core:
        reasons.append('cpp_not_core_requirement')
    if not senior(title, description):
        reasons.append('seniority_not_established')
    if not active(source, raw):
        reasons.append('inactive_or_old')
    if not local_market(record.get('region', ''), location_rows(source, record.get('region', ''), raw)):
        reasons.append('outside_local_market')
    return reasons


OPTIONAL_CPP = re.compile(
    r'\b(?:nice to have|nice-to-have|preferred|preferably|a plus|plus|bonus|advantage|optional|desirable|'
    r'not required|not essential|желател\w*|будет плюсом|не обязател\w*|на выбор)\b', re.I)
CPP_ALTERNATIVE = re.compile(
    r'(?:c\s*\+\s*\+|с\s*\+\s*\+).{0,45}\b(?:or|oder|либо|или)\b.{0,45}\b(?:rust|go|c#|java|kotlin|python|kdb)\b|'
    r'\b(?:rust|go|c#|java|kotlin|python|kdb)\b.{0,45}\b(?:or|oder|либо|или)\b.{0,45}(?:c\s*\+\s*\+|с\s*\+\s*\+)|'
    r'(?:c\s*\+\s*\+|с\s*\+\s*\+)[^.;\n]{0,80}\bor another (?:statically typed )?language\b', re.I)
CPP_NOT_REQUIRED = re.compile(
    r'(?:if you don.t know|we can teach|can be taught|не знаете|научим).{0,80}(?:c\s*\+\s*\+|с\s*\+\s*\+)|'
    r'(?:c\s*\+\s*\+|с\s*\+\s*\+).{0,80}(?:if you don.t know|we can teach|can be taught|не знаете|научим)', re.I)


def cpp_optional(text):
    for sentence in re.split(r'[.!?;\n]', text or ''):
        if CPP.search(sentence) and (OPTIONAL_CPP.search(sentence) or CPP_ALTERNATIVE.search(sentence) or CPP_NOT_REQUIRED.search(sentence)):
            return True
    return False


def cpp_is_required(title, description):
    if CPP.search(title):
        other_languages = sum(bool(re.search(pattern, title, re.I)) for pattern in
                              (r'\bpython\b', r'\bkdb\b', r'\brust\b', r'\bgo\b', r'\bc#\b', r'\bjava\b', r'\bkotlin\b'))
        return other_languages < 2 and not cpp_optional(title) and not cpp_optional(description)
    for match in CPP.finditer(description):
        context = description[max(0, match.start() - 100):match.end() + 100]
        if cpp_optional(context):
            continue
        if re.search(r'\b(?:required|must[- ]have|proficien\w*|expert\w*|strong|experience|experienced|develop|development|'
                     r'knowledge|skills?)\b|(?:разработ\w*|знани\w*|опыт\w*|владени\w*)', context, re.I):
            return True
    return False


def description_market_conflict(region, description):
    """Reject a listing when its explicit Location field contradicts the source location."""
    description = html.unescape(re.sub(r'<[^>]+>', ' ', description or ''))
    match = re.search(r'\b(?:location|office location|место работы|локация)\s*:\s*([^\n.;|]{2,100})', description, re.I)
    if not match:
        # Some boards omit a Location label and put the hiring office in the first sentence.
        match = re.search(r'\b(?:team|office|role|position)\s+in\s+((?:Amsterdam|Cambridge|Oxford|Manchester|Bristol|Edinburgh|London|'
                          r'Zurich|Zürich|Geneva|Genève|Basel|Lausanne|Bern|Moscow|Москва|Санкт-Петербург|Казань|Новосибирск|Екатеринбург)\b[^\n.;|]{0,50})',
                          description[:900], re.I)
    if not match:
        return False
    stated = match.group(1).casefold()
    markets = {
        'Switzerland': re.compile(r'\b(?:switzerland|schweiz|zurich|zürich|geneva|genève|basel|lausanne|bern|zug|chur)\b', re.I),
        'London, UK': re.compile(r'\blondon\b', re.I),
        'Russia': re.compile(r'\b(?:russia|росси\w*|москв\w*|санкт[- ]?петербург\w*|казан\w*|новосибирск\w*|екатеринбург\w*)\b', re.I),
    }
    # A location label that only says remote/Europe/UK does not identify a local pay market.
    return not markets[region].search(stated)


def relevant(source, record):
    return not exclusion_reasons(source, record)


def currency_code(text):
    m = re.search(r'CHF|GBP|USD|EUR|RUB|руб(?:лей|ля)?|£|\$|€|₽', text, re.I)
    if not m:
        return None
    token = m.group(0).casefold()
    return {'£': 'GBP', 'gbp': 'GBP', '$': 'USD', 'usd': 'USD', '€': 'EUR', 'eur': 'EUR', 'chf': 'CHF', '₽': 'RUB', 'rub': 'RUB', 'руб': 'RUB', 'рублей': 'RUB', 'рубля': 'RUB'}.get(token)


def period_code(text):
    if re.search(r'daily|per day|/day|в день|за день|дневн', text, re.I):
        return 'day'
    if re.search(r'annual|per year|per annum|/year|/yr|в год|годовой|годовых', text, re.I):
        return 'year'
    if re.search(r'monthly|per month|/month|/mo|в месяц|в мес\.?|месячн', text, re.I):
        return 'month'
    return None


def number_value(raw_number, scale):
    number = raw_number.replace(' ', '')
    if ',' in number and '.' in number:
        decimal = ',' if number.rfind(',') > number.rfind('.') else '.'
        number = number.replace('.' if decimal == ',' else ',', '').replace(decimal, '.')
    elif ',' in number or '.' in number:
        separator = ',' if ',' in number else '.'
        parts = number.split(separator)
        number = ''.join(parts) if len(parts[-1]) == 3 and all(part.isdigit() for part in parts) else '.'.join(parts)
    number = float(number)
    if scale and scale.casefold() in {'k', 'тыс', 'тыс.'}:
        number *= 1000
    if scale and scale.casefold() in {'m', 'млн'}:
        number *= 1_000_000
    return round(number)


CURRENCY = r'(?:CHF|GBP|USD|EUR|RUB|руб(?:лей|ля)?\.?|£|\$|€|₽)'
SCALE = r'(?:тыс\.?|млн|[km])(?![A-Za-z])'
PAY_EXPRESSION = re.compile(
    rf'(?<![\w])(?P<cur>{CURRENCY})?\s*(?P<low>{NUMBER})\s*(?P<scale1>{SCALE})?'
    rf'(?P<range>\s*(?:[-–—]|\bto\b|\bдо\b)\s*(?P<cur2>{CURRENCY})?\s*(?P<high>{NUMBER})\s*(?P<scale2>{SCALE})?)?'
    rf'\s*(?P<cur3>{CURRENCY}(?!\s*\d))?', re.I)


def pay_metadata(text):
    return {'tax_basis': 'net' if re.search(r'after tax|net salary|на руки|после налог', text, re.I) else
                         'gross' if re.search(r'before tax|gross|до налог|до вычета', text, re.I) else 'unknown',
            'compensation': 'base' if re.search(r'base(?: salary| pay)?|salary|оклад|зарплат', text, re.I) else 'unknown',
            'employment_basis': 'contractor' if re.search(r'contractor|через ИП|самозанят', text, re.I) else 'unknown'}


def valid_pay(low, high):
    values = [x for x in (low, high) if x is not None]
    return bool(values) and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0 for x in values) and (low is None or high is None or low <= high <= low * 10)


def salary_from_description(description, expected_currency):
    text = html.unescape(re.sub(r'<[^>]+>', ' ', description)).replace('\xa0', ' ')
    for match in PAY_EXPRESSION.finditer(text):
        currencies = [currency_code(match[g]) for g in ('cur', 'cur2', 'cur3') if match[g]]
        if not currencies or any(c != expected_currency for c in currencies):
            continue
        # Anchor to the currency-bearing expression, never an arbitrary nearby number/date.
        before = text[max(0, match.start() - 65):match.start()]
        after = text[match.end():match.end() + 65]
        before = re.split(r'[;\n!?]|(?<=[a-z])\.\s', before, flags=re.I)[-1]
        after = re.split(r'[;\n!?]|(?<=[a-z])\.\s', after, flags=re.I)[0]
        prefix_period = period_code(before)
        suffix_period = period_code(after)
        if prefix_period and suffix_period and prefix_period != suffix_period:
            continue
        period = suffix_period or prefix_period
        if not period or re.search(r'revenue|funding|turnover|market cap|выручк|оборот', before + after, re.I):
            continue
        # Bonus after a completed salary expression is separate; total-package amounts are excluded.
        close_prefix = before[-40:]
        close_suffix = after[:re.search(r'\b(?:plus|and)\b|[+;,]', after, re.I).start()] if re.search(r'\b(?:plus|and)\b|[+;,]', after, re.I) else after
        if (BONUS.search(close_prefix) and not re.search(r'base(?: salary| pay)?[^;]*$|оклад[^;]*$', close_prefix, re.I)) or BONUS.search(close_suffix):
            continue
        scale1 = match['scale1'] or match['scale2']
        scale2 = match['scale2'] or match['scale1']
        try:
            low = number_value(match['low'], scale1)
            high = number_value(match['high'], scale2) if match['high'] else low
        except (ValueError, OverflowError):
            continue
        if not match['range'] and re.search(r'\bfrom\s*$|\bот\s*$', before, re.I):
            high = None
        elif not match['range'] and re.search(r'up to\s*$|\bдо\s*$', before, re.I):
            low = None
        if valid_pay(low, high):
            snippet = (before + match.group(0) + after).strip()
            return {'min': low, 'max': high, 'currency': expected_currency, 'period': period,
                    'basis': 'text', 'snippet': snippet[:250], **pay_metadata(snippet)}
    return None


def predicted(raw):
    return str(raw.get('salary_is_predicted', '1')).casefold() not in {'0', 'false'}


def salary_rows(source, region, raw, description):
    expected = {'Switzerland': 'CHF', 'London, UK': 'GBP', 'Russia': 'RUB'}[region]
    # Must precede every fallback: predicted/unknown Adzuna fields never become observations.
    if source == 'Adzuna' and predicted(raw):
        return []
    found = []
    blocked = False
    if source == 'Headcount Labs':
        for posting in raw.get('postings', []):
            if posting.get('posting_status') != 'listed':
                continue
            locations = location_rows(source, region, {'postings': [posting]})
            if not local_market(region, locations):
                continue
            pay = posting.get('pay') or {}
            item = pay.get('value') if pay.get('state') == 'known' else None
            if not isinstance(item, dict):
                continue
            for item in item.get('ranges') or [item]:
                low, high = item.get('min'), item.get('max')
                if item.get('currency') == expected and item.get('interval') in {'month', 'year', 'day'} and valid_pay(low, high):
                    found.append({'min': low, 'max': high, 'currency': expected, 'period': item['interval'],
                                  'basis': 'api_field', 'snippet': f"API pay: {low}–{high} {expected}/{item['interval']}",
                                  'tax_basis': 'unknown', 'compensation': 'unknown', 'employment_basis': 'unknown'})
    if source in {'Zarplata', 'UK Government Work Hub', 'Yandex Delivery Careers', 'Kaspersky Careers', 'ITJobsWatch', 'Finder', 'Reed', 'Hunter Bond'}:
        low, high, currency, period = (raw.get(k) for k in ('salary_min', 'salary_max', 'currency', 'period'))
        flags = ' '.join(str(x) for x in (raw.get('flags') or []))
        blocked = 'suspicious' in flags.casefold() or 'period_not_stated' in flags
        if ('suspicious' not in flags.casefold() and 'period_not_stated' not in flags and
                currency == expected and period in {'month', 'MONTH', 'year', 'YEAR', 'day', 'DAY'} and valid_pay(low, high)):
            basis = str(raw.get('tax_basis') or raw.get('gross_net') or 'unknown').casefold()
            basis = 'net' if 'net' in basis else 'gross' if 'gross' in basis else 'unknown'
            compensation = str(raw.get('compensation_kind') or raw.get('comp_type') or '').casefold()
            compensation = 'base' if any(term in compensation for term in ('base', 'salary', 'оклад')) else 'unknown'
            found.append({'min': low, 'max': high, 'currency': expected, 'period': period.casefold(),
                          'basis': raw.get('salary_basis') or 'job_board',
                          'snippet': raw.get('salary_snippet') or raw.get('salary_raw_snippet') or raw.get('raw_salary_snippet'),
                          'tax_basis': basis, 'compensation': compensation, 'employment_basis': 'unknown'})
    if normalized_source(source):
        low, high, currency, period = (raw.get(k) for k in ('salary_min', 'salary_max', 'currency', 'period'))
        if currency == expected and period in {'month', 'MONTH', 'year', 'YEAR', 'day', 'DAY'} and valid_pay(low, high):
            found.append({'min': low, 'max': high, 'currency': expected, 'period': period.casefold(),
                          'basis': raw.get('salary_basis') or 'job_board',
                          'snippet': raw.get('salary_snippet') or raw.get('salary_raw_snippet'),
                          'tax_basis': raw.get('tax_basis') if raw.get('tax_basis') in {'gross', 'net'} else 'unknown',
                          'compensation': raw.get('compensation_kind') or 'unknown', 'employment_basis': 'unknown'})
    # SuperJob/Trudvsem numeric fields omit period: only explicit text evidence can qualify.
    if not found and not blocked:
        parsed = salary_from_description(description, expected)
        if parsed:
            found.append(parsed)
    return found


def job_urls(source, raw):
    if normalized_source(source):
        # Related links often point to channel home pages or referral lists; they are not job identity.
        values = [raw.get('application_url'), raw.get('url'), raw.get('applyUrl'), raw.get('activevacancies_url')]
        return list(dict.fromkeys(url for url in values if isinstance(url, str) and url.startswith(('https://', 'http://'))))
    values = [value(p.get('posting_url')) or value(p.get('application_url')) for p in raw.get('postings', [])] if source == 'Headcount Labs' else [raw.get('link') or raw.get('vac_url') or raw.get('redirect_url') or raw.get('url')]
    return list(dict.fromkeys(url for url in values if isinstance(url, str) and url.startswith(('https://', 'http://'))))


def canonical_job_url(url):
    parts = urlsplit(url)
    host = parts.netloc.casefold().removeprefix('www.')
    return urlunsplit((parts.scheme.casefold(), host, unquote(parts.path).rstrip('/'), '', ''))


def meaningful_title_tokens(title, employer=''):
    generic = {'senior', 'sr', 'lead', 'leader', 'staff', 'principal', 'software', 'engineer',
               'engineering', 'developer', 'development', 'programmer', 'c', 'c++', 'role', 'the',
               'and', 'for', 'in', 'of', 'a', 'an'}
    tokens = set(clean(title).split()) - generic - set(clean(employer).split())
    return {'quant' if token.startswith('quantit') else token for token in tokens}


def segment(title, description):
    text = title + ' ' + description
    if re.search(r'\bHFT\b|high[- ]frequency|low[- ]latency.*trad|высокочастот|низколатент.*торг', text, re.I):
        return 'hft'
    if re.search(r'\btrading\b|\bfinance\b|financial|hedge fund|investment bank|финанс|бирж|трейдинг', text, re.I):
        return 'trading_finance'
    return 'general_cpp'


def record_regions(source, record):
    raw = record['raw']
    locations = location_rows(source, record.get('region'), raw)
    claimed = set(record.get('regions') or [record.get('region')])
    # Search-query labels are candidate markets, not proof of location. Headcount postings
    # can expose several source locations for one job; accept only markets those locations prove.
    if source == 'Headcount Labs':
        claimed = set(r for r in ('Switzerland', 'London, UK', 'Russia') if local_market(r, locations))
    return [r for r in ('Switzerland', 'London, UK', 'Russia')
            if r in claimed and local_market(r, locations)]


def build_monitor(snapshot):
    expected_sources = {'Headcount Labs', 'SuperJob', 'Adzuna', 'Работа России', 'Zarplata', 'UK Government Work Hub', 'Yandex Delivery Careers', 'Kaspersky Careers', 'ITJobsWatch', 'Finder', 'Reed', 'Hunter Bond'}
    candidates, source_rows, excluded = [], [], []
    for source in snapshot.get('sources', []):
        name = source.get('source')
        if name not in expected_sources and not normalized_source(name):
            continue
        # A rebuild timestamp is not evidence of a source retrieval.
        observed = (source.get('pilot_observed_at') or source.get('observed_at')) if name == 'Adzuna' else (source.get('retrieved_at') or source.get('observed_at'))
        qualified = 0
        for entry in source.get('records', []):
            record = entry if isinstance(entry.get('raw'), dict) else {'region': entry.get('region'), 'raw': entry}
            title, employer, description, raw = fields(name, record)
            identity = str(raw.get('job_id') or raw.get('id') or raw.get('source_id') or raw.get('link') or '')
            for region in record_regions(name, record):
                regional = {**record, 'region': region}
                reasons = exclusion_reasons(name, regional)
                if name == 'Adzuna' and description_market_conflict(region, description):
                    reasons.append('description_location_conflicts_with_source_location')
                urls = job_urls(name, raw)
                if name == 'Headcount Labs':
                    urls = list(dict.fromkeys(
                        url for posting in raw.get('postings', [])
                        if posting.get('posting_status') == 'listed' and
                        local_market(region, location_rows(name, region, {'postings': [posting]}))
                        for url in (value(posting.get('posting_url')) or value(posting.get('application_url')),)
                        if isinstance(url, str) and url.startswith(('https://', 'http://'))))
                reference = {'source': name, 'id': identity, 'urls': urls, 'observed_at': observed}
                if reasons:
                    excluded.append({**reference, 'region': region, 'title': title, 'employer': employer, 'reasons': reasons})
                    continue
                qualified += 1
                locations = location_rows(name, region, raw)
                city = 'London' if region == 'London, UK' else next((str(x.get('city') or '') for x in locations if local_market(region, [x])), '')
                pay = salary_rows(name, region, raw, description)
                source_segment = raw.get('segment')
                candidates.append({'source': name, 'region': region, 'title': title, 'employer': employer,
                                   'city': city, 'description': clean(description), 'salary': pay, 'reference': reference,
                                   'seniority': 'explicit' if SENIOR_TITLE.search(title) else 'experience',
                                   'segment': source_segment if source_segment in {'hft', 'trading_finance', 'general_cpp'} else segment(title, description),
                                   'salary_estimate': name == 'Adzuna' and predicted(raw),
                                   'salary_unresolved': not pay and not (name == 'Adzuna' and predicted(raw)) and any(raw.get(k) is not None for k in ('salary_min', 'salary_max', 'payment_from', 'payment_to'))})
        source_rows.append({'source': name, 'records': len(source.get('records', [])),
                            'qualified_records': qualified, 'updated_at': observed,
                            'status': source.get('status', 'unknown'), 'refresh_error': source.get('refresh_error'),
                            'refresh_policy': source.get('refresh_policy') or ('pilot_static' if name == 'Adzuna' else 'weekly')})

    from difflib import SequenceMatcher
    groups = []
    buckets = {}
    for row in candidates:
        key = (row['region'], clean(row['city']))
        group = None
        for possible in buckets.get(key, []):
            row_id = row['reference']['id']
            same_identity = bool(row_id) and any(r['source'] == row['source'] and r['id'] == row_id for r in possible['records'])
            row_urls = {canonical_job_url(url) for url in row['reference']['urls']}
            group_urls = {canonical_job_url(url) for ref in possible['records'] for url in ref['urls']}
            shared_url = bool(row_urls & group_urls)
            cross_source = row['source'] not in possible['sources']
            old_title_tokens = meaningful_title_tokens(possible['title'], possible['employer'])
            new_title_tokens = meaningful_title_tokens(row['title'], row['employer'])
            title_match = old_title_tokens == new_title_tokens and SequenceMatcher(
                None, clean(possible['title']), clean(row['title'])).ratio() >= .72
            description_match = any(
                min(len(d), len(row['description'])) >= 250 and
                (d.startswith(row['description']) or row['description'].startswith(d) or
                 SequenceMatcher(None, d, row['description']).ratio() >= .96)
                for d in possible['_descriptions'])
            same_employer = clean(possible['employer']) == clean(row['employer']) and bool(clean(row['employer']))
            if same_identity or shared_url or (same_employer and cross_source and title_match and description_match):
                group = possible
                break
        if group is None:
            group = {'group_id': f'g{len(groups) + 1}', 'region': row['region'], 'title': row['title'],
                     'employer': row['employer'], 'city': row['city'], 'sources': [], 'records': [],
                     'salary_candidates': [], 'salary': [], 'salary_estimate': False, 'salary_unresolved': False,
                     'seniority': row['seniority'], 'segment': row['segment'], '_descriptions': []}
            groups.append(group)
            buckets.setdefault(key, []).append(group)
        if row['source'] not in group['sources']:
            group['sources'].append(row['source'])
        group['records'].append(row['reference'])
        group['_descriptions'].append(row['description'])
        group['salary_candidates'].extend({**pay, 'source': row['source'], 'urls': row['reference']['urls'], 'observed_at': row['reference']['observed_at']} for pay in row['salary'])
        group['salary_estimate'] |= row['salary_estimate']
        group['salary_unresolved'] |= row['salary_unresolved']
        if row['seniority'] == 'explicit':
            group['seniority'] = 'explicit'

    for group in groups:
        group.pop('_descriptions')
        dated = []
        for pay in group['salary_candidates']:
            try:
                date = datetime.fromisoformat(pay['observed_at'].replace('Z', '+00:00'))
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                if date >= datetime.now(timezone.utc) - timedelta(days=90):
                    dated.append(pay)
            except (TypeError, ValueError, AttributeError):
                pass
        unique = {(x['min'], x['max'], x['currency'], x['period']) for x in dated}
        group['salary_conflict'] = len(unique) > 1
        reasons = []
        if len(unique) > 1:
            reasons.append('conflicting_salary_evidence')
        elif unique:
            pay = dict(dated[0])
            for dimension in ('tax_basis', 'compensation', 'employment_basis'):
                known = {x.get(dimension, 'unknown') for x in dated} - {'unknown'}
                if len(known) > 1:
                    reasons.append('conflicting_' + dimension)
                pay[dimension] = next(iter(known)) if len(known) == 1 else 'unknown'
            if not reasons:
                group['salary'] = [pay]
        elif group['salary_candidates']:
            reasons.append('salary_source_date_unknown_or_older_than_90_days')
        elif group['salary_estimate']:
            reasons.append('predicted_or_unverified_salary_excluded')
        else:
            reasons.append('no_explicit_local_salary_currency_and_period')
        group['salary_exclusion_reasons'] = reasons
        group['salary_conflict'] |= any(r.startswith('conflicting_') for r in reasons)

    regions = summarize_groups(groups)
    return {'observed_at': snapshot.get('observed_at'), 'fx': snapshot.get('fx'),
            'method': 'Код требует подтверждения обязательного C++ и seniority; проверяет рынок по географии публикации, сверяет её с явной локацией в описании. Дубли объединяются по непустому ID/прямой ссылке или совпадающей роли и почти идентичному описанию; сопутствующие ссылки не считаются ID вакансии. Это группы вакансий, не независимые работодатели. Неизвестные форматы оплаты выделены отдельно; прогнозы и зарплаты без даты источника исключены.',
            'sources': source_rows, 'regions': regions, 'groups': groups, 'excluded': excluded}


def summarize_groups(groups):
    regions = []
    for region in ('Switzerland', 'London, UK', 'Russia'):
        matched = [g for g in groups if g['region'] == region]
        observations = [pay for group in matched for pay in group['salary']]
        by_basis = {}
        for pay in observations:
            key = tuple(pay[k] for k in ('currency', 'period', 'tax_basis', 'compensation', 'employment_basis'))
            by_basis.setdefault(key, []).append(pay)
        ranges = []
        for key, values in sorted(by_basis.items()):
            lows = [x['min'] for x in values if x['min'] is not None]
            highs = [x['max'] for x in values if x['max'] is not None]
            low, high = min(lows) if lows else None, max(highs) if highs else None
            ranges.append(dict(zip(('currency', 'period', 'tax_basis', 'compensation', 'employment_basis'), key),
                               count=len(values), min=low, max=high,
                               range=f'{low}–{high}' if len(values) >= 5 else None))
        regions.append({'region': region, 'qualified_roles': len(matched),
                        'employers': len({clean(g['employer']) for g in matched if g['employer']}),
                        'salary_estimates_excluded': sum(g['salary_estimate'] for g in matched),
                        'salary_fields_unresolved': sum(g['salary_unresolved'] for g in matched),
                        'salary_observations': len(observations),
                        'salary_conflicts': sum(g['salary_conflict'] for g in matched), 'salary_ranges': ranges})
    return regions

if __name__ == '__main__':
    assert number_value('150,000', None) == 150000
    assert number_value('150.000,50', None) == 150000
    assert salary_from_description('Base salary £120,000 per year plus bonus', 'GBP')['min'] == 120000
    assert salary_from_description('£100k total compensation per year', 'GBP') is None
    sample = {'region': 'Russia', 'raw': {'id': 'sample', 'job-name': 'Ведущий разработчик C++',
              'company': {'name': 'Работодатель'}, 'region': {'name': 'Москва'},
              'requirements': 'Опыт работы от 5 лет; знание C++',
              'date_modify': datetime.now(timezone.utc).isoformat()}}
    assert relevant('Работа России', sample)
    assert not relevant('Работа России', {**sample, 'raw': {**sample['raw'], 'job-name': 'Ведущий инженер по машинному обучению'}})
