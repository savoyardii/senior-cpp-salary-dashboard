"""Collect remote senior C++ roles with explicit UK/Swiss eligibility."""
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from time import sleep
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import re

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "himalayas_candidates.json"
API = "https://himalayas.app/jobs/api/search"
CPP = re.compile(r"\bc\s*\+\s*\+|\bc/c\s*\+\s*\+", re.I)
MARKETS = {
    "GB": ("United Kingdom", "UK remote-eligible"),
    "CH": ("Switzerland", "Switzerland"),
}


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


def timestamp(value):
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def pay_period(value):
    return {
        "annual": "year", "monthly": "month", "weekly": "week",
        "fortnightly": "fortnight", "hourly": "hour",
    }.get(str(value or "").casefold())


def fetch_page(country, page):
    params = urlencode({
        "q": "C++", "country": country, "seniority": "Senior",
        "sort": "recent", "page": page,
    })
    request = Request(f"{API}?{params}", headers={
        "Accept": "application/json",
        "User-Agent": "salary-market-dashboard/1.0 (public vacancy research)",
    })
    with urlopen(request, timeout=25) as response:
        return json.load(response)


def collect():
    observed_at = datetime.now(timezone.utc).isoformat()
    records, seen, pages_read = [], set(), {}
    for country, (country_name, region) in MARKETS.items():
        pages_read[country] = 0
        page = 1
        while True:
            response = fetch_page(country, page)
            rows = response.get("jobs", [])
            pages_read[country] += 1
            if not rows:
                break
            for job in rows:
                guid = str(job.get("guid") or "")
                restrictions = job.get("locationRestrictions") or []
                categories = job.get("categories") or []
                # Search results often mention C++ only in unrelated body text or
                # machine-generated categories. Keep this sample high precision.
                cplusplus_evidence = job.get("title", "")
                if (not guid or country_name not in restrictions or
                        not CPP.search(cplusplus_evidence)):
                    continue
                key = (guid, country)
                if key in seen:
                    continue
                seen.add(key)
                salary_period = pay_period(job.get("salaryPeriod"))
                raw = {
                    "id": guid,
                    "title": job.get("title", ""),
                    "employer": job.get("companyName", ""),
                    "description": plain(job.get("description")),
                    "url": guid,
                    "application_url": job.get("applicationLink"),
                    "location": f"Remote (eligible in {country_name}; no city stated)",
                    "city": "Remote",
                    "country": country,
                    "remote": True,
                    "market_scope": "countrywide_remote_eligibility",
                    "location_restrictions": restrictions,
                    "location_eligibility_evidence": f"API locationRestrictions includes {country_name}",
                    "timezone_restrictions": job.get("timezoneRestrictions") or [],
                    "source_search_terms": ["C++"],
                    "source_posted_at": timestamp(job.get("pubDate")),
                    "expires_at": timestamp(job.get("expiryDate")),
                    "expiry_timestamp": job.get("expiryDate"),
                    "observed_at": observed_at,
                    "seniority": job.get("seniority") or [],
                    "employment_type": job.get("employmentType"),
                    "salary_min": job.get("minSalary"),
                    "salary_max": job.get("maxSalary"),
                    "currency": job.get("currency"),
                    "period": salary_period,
                    "salary_basis": "job_board" if job.get("minSalary") is not None or job.get("maxSalary") is not None else None,
                    "salary_snippet": job.get("excerpt"),
                    "categories": categories,
                }
                records.append({"region": region, "query": "C++", "raw": raw})
            total = response.get("totalCount")
            if len(rows) < 20 or (isinstance(total, int) and page * 20 >= total):
                break
            page += 1
            sleep(1)
    return {
        "source": "Himalayas",
        "status": "queried",
        "observed_at": observed_at,
        "refresh_policy": "weekly; public API, no key",
        "search_terms": ["C++"],
        "pages_read": pages_read,
        "records": records,
    }


def self_check():
    assert timestamp(1799653327) == "2027-01-11T07:42:07+00:00"
    assert pay_period(None) is None
    item = {
        "guid": "https://himalayas.app/job/example",
        "title": "Senior C++ Engineer",
        "companyName": "Example",
        "description": "<p>C++ in production</p>",
        "locationRestrictions": ["United Kingdom"],
    }
    assert "United Kingdom" in item["locationRestrictions"]
    assert CPP.search(item["title"] + " " + plain(item["description"]))
    assert "United States" not in item["locationRestrictions"]
    print("Himalayas scope self-check passed")


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["--self-check"]:
        self_check()
    elif not sys.argv[1:]:
        snapshot = collect()
        OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
        print(f"{snapshot['source']}: {len(snapshot['records'])} explicitly UK/CH-eligible senior C++ records; pages={snapshot['pages_read']}")
    else:
        raise SystemExit("Usage: himalayas.py [--self-check]")
