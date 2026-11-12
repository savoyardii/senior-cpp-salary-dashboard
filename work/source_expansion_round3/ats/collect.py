#!/usr/bin/env python3
"""Read public Greenhouse job boards for C++ roles in the target locations."""
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone


BOARDS = {
    "DV Trading": "dvtrading",
    "DRW": "drweng",
    "Engineers Gate": "engineersgate",
    "GSR": "gsrmarkets",
    "iSAM": "isam",
    "Qube Research & Technologies": "quberesearchandtechnologies",
    "Maven Securities": "mavensecuritiesholdingltd",
    "Point72": "point72",
}
CPP = re.compile(r"(?<![A-Za-z])c\s*\+\s*\+(?!\+)|c/c\+\+", re.I)


def region_for(location):
    location = str(location or "")
    if re.search(r"london", location, re.I):
        return "London, UK", "GB"
    if re.search(r"zurich|zürich|geneva|basel|lausanne|bern|zug|chur|switzerland|schweiz", location, re.I):
        return "Switzerland", "CH"
    if re.search(r"moscow|росси|россия", location, re.I):
        return "Russia", "RU"
    return None, None


def normalize(board, job, observed_at):
    location = ((job.get("location") or {}).get("name") if isinstance(job.get("location"), dict)
                else job.get("location")) or ""
    region, country = region_for(location)
    title = job.get("title") or ""
    description = job.get("content") or ""
    if not region or not CPP.search(title + " " + description):
        return None
    return {
        "source": f"Greenhouse: {board}",
        "source_id": str(job.get("id") or ""),
        "url": job.get("absolute_url") or "",
        "title": title,
        "employer": board,
        "description": description,
        "location": location,
        "city": location,
        "country": country,
        "region": region,
        "published_at": job.get("first_published"),
        "expires_at": job.get("application_deadline"),
        "observed_at": observed_at,
        "status": "listed_by_public_employer_board",
        "salary_min": None,
        "salary_max": None,
        "currency": None,
        "period": None,
        "salary_provenance": None,
    }


def fetch_board(board, token, timeout=20):
    observed_at = datetime.now(timezone.utc).isoformat()
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "salary-dashboard/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
        records = [row for job in data.get("jobs", []) if (row := normalize(board, job, observed_at))]
        return {"source": f"Greenhouse: {board}", "status": "queried", "observed_at": observed_at,
                "retrieved_at": observed_at, "refresh_policy": "weekly", "records": records,
                "request": {"url": url, "status": "ok", "returned": len(data.get("jobs", [])), "matched": len(records)}}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        return {"source": f"Greenhouse: {board}", "status": "error", "observed_at": observed_at,
                "refresh_policy": "weekly", "records": [],
                "request": {"url": url, "status": getattr(exc, "code", None) or type(exc).__name__}}


def collect():
    return [fetch_board(name, token) for name, token in BOARDS.items()]


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
