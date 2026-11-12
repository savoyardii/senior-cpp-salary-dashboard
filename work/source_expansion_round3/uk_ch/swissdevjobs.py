"""Read SwissDevJobs' public RSS feed and normalize C++ vacancy records."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
import json
import re
import xml.etree.ElementTree as ET

FEED = "https://swissdevjobs.ch/rss"
OUT = Path(__file__).with_name("candidates.json")
MAX_BYTES = 2_000_000
CPP = re.compile(r"\bc\s*\+\s*\+|\bc/c\s*\+\s*\+", re.I)
PAY = re.compile(
    r"(?P<currency>CHF)\s*(?P<low>\d[\d’'\u2019 ]{2,})\s*"
    r"(?:[-–—]|\bto\b)\s*(?:CHF\s*)?(?P<high>\d[\d’'\u2019 ]{2,})"
    r"\s*(?P<period>per year|/year|annual(?:ly)?|jährlich)", re.I,
)


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())


def plain(value):
    parser = Text()
    parser.feed(value or "")
    return " ".join(parser.parts)


def salary(text):
    match = PAY.search(text)
    if not match:
        return {}
    number = lambda value: int(re.sub(r"[ ’'\u2019]", "", value))
    return {
        "salary_min": number(match["low"]),
        "salary_max": number(match["high"]),
        "currency": "CHF",
        "period": "year",
        "salary_basis": "job_board",
        "salary_snippet": match.group(0),
    }


def canonical_url(url):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def parse_feed(body, observed_at):
    root = ET.fromstring(body)
    records = []
    for item in root.findall(".//item"):
        title = plain(item.findtext("title"))
        description = plain(item.findtext("description"))
        if not CPP.search(title + " " + description):
            continue
        link = canonical_url(item.findtext("link") or "")
        if not link.startswith("https://swissdevjobs.ch/jobs/"):
            continue
        posted = item.findtext("pubDate")
        try:
            posted_at = parsedate_to_datetime(posted).astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError):
            posted_at = None
        identity = urlsplit(link).path.rsplit("/", 1)[-1]
        employer_match = re.search(r"\s+@\s+(.+?)(?:\s+\[CHF\b|$)", title)
        raw = {
            "id": identity,
            "title": title,
            "employer": employer_match.group(1).strip() if employer_match else "",
            "description": description,
            "url": link,
            "location": "Switzerland",
            "country": "CH",
            "source_posted_at": posted_at,
            "observed_at": observed_at,
        }
        raw.update(salary(title + " " + description))
        records.append({"region": "Switzerland", "query": "C++", "raw": raw})
    return records


def collect():
    observed_at = datetime.now(timezone.utc).isoformat()
    request = Request(FEED, headers={
        "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.5",
        "User-Agent": "salary-market-dashboard/1.0 (public vacancy research)",
    })
    with urlopen(request, timeout=25) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("RSS feed exceeded the 2 MB safety limit")
    records = parse_feed(body, observed_at)
    return {
        "source": "SwissDevJobs",
        "status": "queried",
        "observed_at": observed_at,
        "refresh_policy": "weekly; public RSS feed",
        "requests_used": 1,
        "records": records,
    }


def self_check():
    assert salary("CHF 100'000 - 120'000 per year") == {
        "salary_min": 100000, "salary_max": 120000, "currency": "CHF",
        "period": "year", "salary_basis": "job_board",
        "salary_snippet": "CHF 100'000 - 120'000 per year",
    }
    fixture = b"""<rss><channel><item><title>Senior C++ Developer @ Example [CHF 100'000 - 120'000]</title><link>https://swissdevjobs.ch/jobs/example?utm_source=rss</link><pubDate>Wed, 28 Oct 2026 09:32:02 GMT</pubDate><description><![CDATA[<b>Salary: CHF 100'000 - 120'000 per year</b><p>5 years C++ experience</p>]]></description></item><item><title>Python Engineer @ Other</title><link>https://swissdevjobs.ch/jobs/other</link><description>Python only</description></item></channel></rss>"""
    rows = parse_feed(fixture, "2026-11-12T00:00:00+00:00")
    assert len(rows) == 1
    assert rows[0]["raw"]["salary_min"] == 100000
    assert rows[0]["raw"]["salary_max"] == 120000
    assert rows[0]["raw"]["country"] == "CH"
    print("SwissDevJobs parser self-check passed")


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["--self-check"]:
        self_check()
    elif not sys.argv[1:]:
        snapshot = collect()
        OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
        print(f"{snapshot['source']}: {len(snapshot['records'])} C++ listings; saved {OUT}")
    else:
        raise SystemExit("Usage: swissdevjobs.py [--self-check]")
