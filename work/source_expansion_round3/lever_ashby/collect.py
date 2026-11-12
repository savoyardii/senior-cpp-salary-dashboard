#!/usr/bin/env python3
"""Fetch public Lever/Ashby job-board APIs for selected trading employers."""
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

BOARDS = {
    "Lever: MARGO Group": ("lever", "margo-group"),
    "Lever: Crypto.com": ("lever", "crypto"),
    "Lever: Wintermute": ("lever", "wintermute-trading"),
    "Lever: Zurich Instruments": ("lever", "zurichinstruments"),
    "Ashby: Teza Technologies": ("ashby", "teza-technologies"),
    "Ashby: TradingHub": ("ashby", "TRADINGHUB"),
    "Ashby: Smarkets": ("ashby", "smarkets"),
    "Ashby: Keyrock": ("ashby", "Keyrock"),
}
CPP = re.compile(r"(?<![a-z])c\s*\+\s*\+(?!\+)|c/c\+\+|с\s*\+\s*\+", re.I)


def _locations(v):
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, dict):
        return [str(v.get("name") or v.get("location") or "").strip()]
    if isinstance(v, list):
        result = []
        for item in v:
            result.extend(_locations(item))
        return [x for x in result if x]
    return []


def regions_for(locations):
    regions = []
    for location in locations:
        if re.search(r"\bLondon\b", location, re.I) and "London, UK" not in regions:
            regions.append("London, UK")
        if re.search(r"Switzerland|Schweiz|Zürich|Zurich|Geneva|Genève|Basel|Lausanne|Bern|Zug|Chur", location, re.I) and "Switzerland" not in regions:
            regions.append("Switzerland")
    return regions


def _salary(interval, currency, minimum, maximum):
    if not currency or not isinstance(minimum, (int, float)) and not isinstance(maximum, (int, float)):
        return {"salary_min": None, "salary_max": None, "currency": None, "period": None}
    interval = str(interval or "").casefold()
    period = "year" if "year" in interval or "annual" in interval else "month" if "month" in interval else "day" if "day" in interval else None
    return {"salary_min": minimum, "salary_max": maximum, "currency": currency, "period": period}


def normalize(board, vendor, job, observed_at):
    if vendor == "lever":
        categories = job.get("categories") or {}
        locations = _locations(categories.get("allLocations") or categories.get("location"))
        title = job.get("text") or ""
        description = job.get("descriptionPlain") or job.get("openingPlain") or ""
        salary = job.get("salaryRange") or {}
        pay = _salary(salary.get("interval"), salary.get("currency"), salary.get("min"), salary.get("max"))
        source_id = str(job.get("id") or "")
        url = job.get("hostedUrl") or ""
        published = job.get("createdAt") or job.get("firstPublishedAt")
    else:
        locations = _locations(job.get("location")) + _locations(job.get("secondaryLocations"))
        title = job.get("title") or ""
        description = job.get("descriptionPlain") or job.get("descriptionHtml") or job.get("description") or ""
        comp = job.get("compensation") or {}
        components = comp.get("summaryComponents") or []
        salary_row = next((x for x in components if str(x.get("compensationType", "")).casefold() == "salary"), {})
        pay = _salary(salary_row.get("interval"), salary_row.get("currencyCode"), salary_row.get("minValue"), salary_row.get("maxValue"))
        source_id = str(job.get("id") or job.get("jobId") or "")
        url = job.get("jobUrl") or ""
        published = job.get("publishedAt") or job.get("openedAt")
    if not title or not CPP.search(title + " " + description):
        return []
    out = []
    for region in regions_for(locations):
        out.append({
            "region": region,
            "query": "public ATS board C++",
            "raw": {
                "source_id": source_id,
                "id": source_id,
                "url": url,
                "title": title,
                "employer": board,
                "description": description,
                "location": locations,
                "country": "GB" if region == "London, UK" else "CH",
                "published_at": published,
                "observed_at": observed_at,
                "status": "published_by_public_employer_ats",
                **pay,
                "salary_raw_snippet": (job.get("salaryDescriptionPlain") if vendor == "lever" else (job.get("compensation") or {}).get("scrapeableCompensationSalarySummary")),
                "salary_provenance": "public ATS salary field" if pay["currency"] else None,
                "workplace_type": job.get("workplaceType") if vendor == "lever" else ("remote" if job.get("isRemote") else None),
                "source_vendor": vendor,
                "segment": "trading_finance" if re.search(r"trading|quant|market maker|hedge|finance|HFT|low latency", title + " " + description, re.I) else "general_cpp",
            },
        })
    return out


def request_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "salary-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def fetch(board, vendor, token, timeout=20):
    observed = datetime.now(timezone.utc).isoformat()
    if vendor == "lever":
        url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    else:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"
    try:
        data = request_json(url, timeout)
        jobs = data if isinstance(data, list) else data.get("jobs", [])
        records = [row for job in jobs for row in normalize(board, vendor, job, observed)]
        return {"source": board, "status": "queried", "observed_at": observed, "retrieved_at": observed,
                "refresh_policy": "weekly", "records": records,
                "requests": [{"url": url, "status": "ok", "returned": len(jobs), "matched": len(records)}]}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        return {"source": board, "status": "error", "observed_at": observed, "refresh_policy": "weekly", "records": [],
                "requests": [{"url": url, "status": getattr(exc, "code", None) or type(exc).__name__}]}


def collect():
    return [fetch(name, vendor, token) for name, (vendor, token) in BOARDS.items()]


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
