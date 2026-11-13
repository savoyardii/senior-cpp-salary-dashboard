"""Free public feeds found during the latest source expansion."""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
import json
import re
import xml.etree.ElementTree as ET

MAX_BYTES = 8_000_000
CPP = re.compile(r"c\s*\+\s*\+|c/c\s*\+\s*\+", re.I)


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())


def text(value):
    parser = PlainText()
    parser.feed(value or "")
    return " ".join(parser.parts)


def fetch(url, accept="application/json,application/xml,text/xml;q=0.9,*/*;q=0.5"):
    request = Request(url, headers={"Accept": accept, "User-Agent": "salary-market-dashboard/1.0 (public vacancy research)"})
    with urlopen(request, timeout=30) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Source response exceeded the 8 MB safety limit")
    return body


def valid_url(value, hosts):
    parts = urlsplit(value or "")
    return parts.scheme == "https" and bool(parts.hostname) and parts.hostname.lower().removeprefix("www.") in hosts


def dated(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def records_from_rss(body, region, domain, country, now=None):
    now = now or datetime.now(timezone.utc)
    root = ET.fromstring(body)
    records = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        description = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or item.findtext("description") or ""
        link = (item.findtext("link") or "").strip()
        posted = dated(item.findtext("pubDate"))
        if not title or not valid_url(link, {domain}) or not posted or not now - timedelta(days=90) <= posted <= now + timedelta(days=1):
            continue
        creator = item.findtext("{http://purl.org/dc/elements/1.1/}creator") or ""
        records.append({"region": region, "query": "C++ RSS", "raw": {
            "id": item.findtext("guid") or link, "title": title, "employer": creator.strip(),
            "description": description, "url": link, "location": region, "city": region,
            "country": country, "source_posted_at": posted.isoformat(),
            "observed_at": now.isoformat(), "is_closed": False,
        }})
    return records


def collect_ictjobs():
    now = datetime.now(timezone.utc).isoformat()
    body = fetch("https://ictjobs.ch/feed/", "application/rss+xml,application/xml,text/xml;q=0.9")
    records = records_from_rss(body, "Switzerland", "ictjobs.ch", "CH")
    return {"source": "ictjobs.ch RSS", "status": "queried", "observed_at": now,
            "refresh_policy": "weekly; public RSS of the 10 newest listings; Swiss market",
            "requests_used": 1, "records": records}


def company_name(value):
    return value.get("name", "") if isinstance(value, dict) else str(value or "")


def location_parts(value):
    rows = value if isinstance(value, list) else [value]
    for row in rows:
        if not isinstance(row, dict):
            continue
        address = row.get("address", row)
        if isinstance(address, str):
            return address, ""
        city = str(address.get("addressLocality") or address.get("addressRegion") or "")
        country = str(address.get("addressCountry") or "")
        if isinstance(address.get("addressCountry"), dict):
            country = str(address["addressCountry"].get("name") or address["addressCountry"].get("@id") or "")
        return city, country
    return "", ""


def salary_fields(salary):
    if not isinstance(salary, dict):
        return {}
    value = salary.get("value") or {}
    if not isinstance(value, dict):
        value = {"minValue": value, "maxValue": value}
    interval = str(value.get("unitText") or salary.get("interval") or "").casefold()
    period = next((label for terms, label in ((('year', 'annual'), 'year'), (('month',), 'month'), (('day',), 'day'))
                   if any(term in interval for term in terms)), None)
    low = value.get("minValue", salary.get("min"))
    high = value.get("maxValue", salary.get("max", low))
    try:
        low = float(low) if low is not None else None
        high = float(high) if high is not None else None
    except (TypeError, ValueError):
        return {}
    if not period or low is None or high is None or low <= 0 or high < low:
        return {}
    return {"salary_min": low, "salary_max": high,
            "currency": salary.get("currency") or value.get("currency"),
            "period": period, "salary_basis": "job_board"}


def normalize_yubhub(job, region_hint, observed_at):
    title = str(job.get("title") or "")
    description = str(job.get("description") or "")
    city, country = location_parts(job.get("jobLocation"))
    country_code = {"united kingdom": "GB", "uk": "GB", "switzerland": "CH"}.get(country.casefold(), country.upper())
    if region_hint == "London, UK" and not country_code:
        country_code = "GB"
    company = company_name(job.get("hiringOrganization") or job.get("company"))
    url = str(job.get("url") or "")
    job_host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if not CPP.search(title + " " + text(description)) or not valid_url(url, {job_host}):
        return None
    market = "Switzerland" if country_code == "CH" else "London, UK" if country_code == "GB" and re.search(r"london|\bEC\d|\bWC\d|\bSW\d|\bW\d", city, re.I) else None
    if not market and region_hint == "London, UK" and re.search(r"london|\bEC\d|\bWC\d|\bSW\d|\bW\d", city, re.I):
        market = "London, UK"
    if not market:
        return None
    raw = {"id": str((job.get("identifier") or {}).get("value") or url), "title": title,
           "employer": company, "description": description, "url": url,
           "application_url": str(job.get("applyUrl") or url), "location": city or market,
           "city": city or market, "country": country_code, "source_posted_at": job.get("datePosted"),
           "observed_at": observed_at, "is_closed": False,
           "source_attribution": "Data by YubHub", "source_attribution_url": "https://yubhub.co"}
    raw.update(salary_fields(job.get("baseSalary") or job.get("salary")))
    return {"region": market, "query": "C++ feed; local market", "raw": raw}


def collect_yubhub():
    now = datetime.now(timezone.utc).isoformat()
    feeds = (
        ("Switzerland", "https://feeds.yubhub.co/facet/skill/c-plus-plus.json"),
        ("London, UK", "https://feeds.yubhub.co/facet/country/united-kingdom.json"),
    )
    rows = {}
    for hint, url in feeds:
        payload = json.loads(fetch(url))
        for job in payload.get("jobs", []):
            record = normalize_yubhub(job, hint, now)
            if record:
                rows[record["raw"]["id"]] = record
    return {"source": "YubHub", "status": "queried", "observed_at": now,
            "refresh_policy": "weekly; free public feeds capped at 100 per feed; attribution required",
            "requests_used": len(feeds), "records": list(rows.values())}


def collect_active_vacancies():
    now = datetime.now(timezone.utc).isoformat()
    rows = {}
    requests_used = 0
    for region, location in (("Switzerland", "Switzerland"), ("London, UK", "London")):
        url = "https://activevacancies.com/api/v1/jobs?" + urlencode({"q": "C++", "location": location, "limit": 50, "sort": "recent"})
        payload = json.loads(fetch(url))
        requests_used += 1
        for job in payload.get("data", []):
            title, description = str(job.get("title") or ""), str(job.get("description") or "")
            if not CPP.search(title + " " + text(description)):
                continue
            location_text = str(job.get("location") or "")
            if region == "London, UK" and not re.search(r"london|\bEC\d|\bWC\d|\bSW\d|\bW\d", location_text, re.I):
                continue
            if region == "Switzerland" and not re.search(
                r"switzerland|schweiz|suisse|svizzera|zürich|zurich|geneva|genève|basel|bern|zug|lausanne|chur|winterthur|st\. gallen|lugano",
                location_text, re.I):
                continue
            salary = job.get("salary") or {}
            interval = str(salary.get("interval") or "").casefold()
            period = next((p for marker, p in (("year", "year"), ("annual", "year"), ("month", "month"), ("day", "day")) if marker in interval), None)
            company = company_name(job.get("company"))
            apply_url = str(job.get("applyUrl") or "")
            listing_url = str(job.get("url") or "")
            apply_host = (urlsplit(apply_url).hostname or "").lower().removeprefix("www.")
            if not valid_url(apply_url, {apply_host}):
                apply_url = listing_url
            raw = {"id": str(job.get("id") or listing_url), "title": title, "employer": company,
                   "description": description, "url": apply_url, "application_url": apply_url,
                   "activevacancies_url": listing_url, "location": location_text,
                   "city": location_text, "country": "CH" if region == "Switzerland" else "GB",
                   "remote": job.get("remoteStatus") == "remote", "source_posted_at": job.get("postedAt"),
                   "observed_at": now, "is_closed": False,
                   "source_attribution": "Active Vacancies", "source_attribution_url": "https://activevacancies.com"}
            if period and salary.get("currency"):
                raw.update(salary_min=salary.get("min"), salary_max=salary.get("max"),
                           currency=salary["currency"], period=period, salary_basis="job_board")
            rows[raw["id"]] = {"region": region, "query": "C++", "raw": raw}
    return {"source": "Active Vacancies", "status": "queried", "observed_at": now,
            "refresh_policy": "weekly; public API, 2 searches per refresh; link back to source required",
            "requests_used": requests_used, "records": list(rows.values())}


def collect_jobserve(feed_url):
    if not feed_url:
        return {"source": "JobServe RSS", "status": "requires_login", "records": [],
                "refresh_policy": "requires a saved London C++ search RSS URL from an authenticated account"}
    now = datetime.now(timezone.utc)
    body = fetch(feed_url, "application/rss+xml,application/xml,text/xml;q=0.9")
    records = records_from_rss(body, "London, UK", "jobserve.com", "GB", now)
    records = [row for row in records if CPP.search(row["raw"]["title"] + " " + text(row["raw"]["description"]))
               and re.search(r"london", row["raw"]["description"] + " " + row["raw"]["title"], re.I)]
    return {"source": "JobServe RSS", "status": "queried", "observed_at": now.isoformat(),
            "refresh_policy": "weekly; saved-search RSS; C++ roles with explicit London evidence",
            "requests_used": 1, "records": records}
