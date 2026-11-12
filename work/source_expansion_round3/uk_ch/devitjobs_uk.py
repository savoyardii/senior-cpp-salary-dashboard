"""Read DevITjobs UK's public XML feed and retain recent London C++ listings."""
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, urlunsplit
import json
import re
import xml.etree.ElementTree as ET

FEED = "https://devitjobs.uk/job_feed.xml"
OUT = Path(__file__).with_name("devitjobs_uk_candidates.json")
MAX_BYTES = 12_000_000
CPP = re.compile(r"\bc\s*\+\s*\+|\bc/c\s*\+\s*\+", re.I)
PAY = re.compile(
    r"(?P<currency>£|GBP)\s*(?P<low>\d[\d,.'’ ]*\d|\d)\s*"
    r"(?:[-–—]|\bto\b)\s*(?:£|GBP\s*)?(?P<high>\d[\d,.'’ ]*\d|\d)"
    r"\s*(?P<scale>k)?\s*(?P<period>per year|/year|annual(?:ly)?|per month|/month|monthly)", re.I,
)


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())


def plain(value):
    parser = Text()
    parser.feed(value or "")
    return " ".join(parser.parts)


def posted_date(value):
    try:
        return datetime.strptime(value, "%d.%m.%Y").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def salary(value):
    match = PAY.search(value or "")
    if not match:
        return {}

    def amount(text):
        result = float(re.sub(r"[ ,.'’]", "", text))
        return int(result * (1000 if match["scale"] else 1))

    period = "year" if "year" in match["period"].casefold() or "annual" in match["period"].casefold() else "month"
    return {
        "salary_min": amount(match["low"]),
        "salary_max": amount(match["high"]),
        "currency": "GBP",
        "period": period,
        "salary_basis": "job_board",
        "salary_snippet": match.group(0),
    }


def canonical_url(url):
    parts = urlsplit(url or "")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def parse_feed(body, observed_at, now=None):
    now = now or datetime.now(timezone.utc)
    root = ET.fromstring(body)
    records = []
    seen = set()
    for item in root.findall(".//job"):
        title = (item.findtext("title") or item.findtext("name") or "").strip()
        desc = plain(item.findtext("description"))
        city = (item.findtext("city") or "").strip()
        region = (item.findtext("region") or "").strip()
        location = (item.findtext("location") or "").strip()
        if not CPP.search(title + " " + desc) or "london" not in " ".join((city, region, location)).casefold():
            continue
        published = posted_date(item.findtext("pubdate"))
        if not published or published < now - timedelta(days=90) or published > now + timedelta(days=1):
            continue
        url = canonical_url(item.findtext("url") or item.findtext("link") or "")
        if urlsplit(url).netloc.casefold() not in {"devitjobs.uk", "www.devitjobs.uk"} or not url.startswith("https://devitjobs.uk/jobs/"):
            continue
        if url in seen:
            continue
        seen.add(url)
        raw = {
            "id": (item.findtext("id") or url.rsplit("/", 1)[-1]).strip(),
            "title": title,
            "employer": (item.findtext("company") or item.findtext("company-name") or "").strip(),
            "description": desc,
            "url": url,
            "location": location,
            "city": city or region,
            "country": "GB",
            "source_posted_at": published.isoformat(),
            "observed_at": observed_at,
            "is_closed": False,
        }
        raw.update(salary(item.findtext("salary") or ""))
        records.append({"region": "London, UK", "query": "C++", "raw": raw})
    return records


def collect():
    observed_at = datetime.now(timezone.utc).isoformat()
    request = Request(FEED, headers={
        "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.5",
        "User-Agent": "salary-market-dashboard/1.0 (public vacancy research)",
    })
    with urlopen(request, timeout=30) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("DevITjobs feed exceeded the 12 MB safety limit")
    return {
        "source": "DevITjobs UK RSS",
        "status": "queried",
        "observed_at": observed_at,
        "refresh_policy": "weekly; public XML feed; only London-tagged, last-90-day C++ records",
        "requests_used": 1,
        "records": parse_feed(body, observed_at),
    }


def self_check():
    fixture = '''<jobs><job><id>job-1</id><title>Senior C++ Engineer</title><url>https://devitjobs.uk/jobs/example?utm=feed</url><country>United Kingdom</country><region>London</region><location>City of London</location><city>London</city><salary>£60,000 - 80,000 per year</salary><company>Example Ltd</company><pubdate>10.11.2026</pubdate><description><![CDATA[<p>5+ years of C++ development.</p>]]></description></job><job><id>job-2</id><title>Senior C++ Engineer</title><url>https://devitjobs.uk/jobs/stale</url><country>United Kingdom</country><region>London</region><city>London</city><pubdate>10.01.2026</pubdate><description>5+ years C++</description></job><job><id>job-3</id><title>Senior Python Engineer</title><url>https://devitjobs.uk/jobs/python</url><region>London</region><city>London</city><pubdate>10.11.2026</pubdate><description>Python</description></job></jobs>'''.encode()
    rows = parse_feed(fixture, "2026-11-13T00:00:00+00:00", datetime(2026, 11, 13, tzinfo=timezone.utc))
    assert len(rows) == 1
    raw = rows[0]["raw"]
    assert raw["url"] == "https://devitjobs.uk/jobs/example"
    assert (raw["salary_min"], raw["salary_max"], raw["currency"], raw["period"]) == (60000, 80000, "GBP", "year")
    print("DevITjobs UK parser self-check passed")


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["--self-check"]:
        self_check()
    elif not sys.argv[1:]:
        snapshot = collect()
        OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
        print(f"{snapshot['source']}: {len(snapshot['records'])} C++ records; saved {OUT}")
    else:
        raise SystemExit("Usage: devitjobs_uk.py [--self-check]")
