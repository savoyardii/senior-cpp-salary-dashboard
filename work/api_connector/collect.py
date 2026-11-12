"""One-shot market snapshot from registered job APIs. Keys stay in local .env."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
OUT_DIR = ROOT / "data"
OUT_FILE = OUT_DIR / "latest.json"
ADZUNA_REQUEST_CAP = 24  # User-authorized maximum is 25; keep one call in reserve.
COUNTRIES = {"Switzerland": "ch", "London, UK": "gb", "Russia": "ru"}
QUERIES = ("C++", "Senior C++", "low latency C++")


def secrets():
    values = dict(os.environ)
    if ENV_FILE.exists():
        values.update(dict(line.split("=", 1) for line in ENV_FILE.read_text().splitlines() if "=" in line))
    return values


def request_json(url, headers=None, body=None, timeout=45):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read()), response.headers
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(type(exc).__name__) from None


def headcount(key):
    result = {"source": "Headcount Labs", "requests": [], "records": []}
    if not key:
        result["status"] = "missing_key"
        return result
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    for region, country in COUNTRIES.items():
        for query in QUERIES:
            cursor = None
            pages = 0
            while pages < 5:
                params = {"country": country, "q": query, "limit": 250, "include": "source_data"}
                if region == "London, UK":
                    params["city"] = "London"
                if cursor:
                    params["cursor"] = cursor
                url = "https://api.headcountlabs.com/v1/jobs?" + urllib.parse.urlencode(params)
                try:
                    data, _ = request_json(url, headers)
                    rows = data.get("data", [])
                    result["records"].extend({"region": region, "query": query, "raw": row} for row in rows)
                    result["requests"].append({"region": region, "query": query, "page": pages + 1, "returned": len(rows), "watermark": data.get("snapshot_watermark"), "status": "ok"})
                    pages += 1
                    cursor = data.get("next_cursor")
                    if not cursor:
                        break
                except RuntimeError as exc:
                    result["requests"].append({"region": region, "query": query, "page": pages + 1, "status": str(exc)})
                    break
    result["status"] = "queried"
    return result


def adzuna(key_id, key, budget=ADZUNA_REQUEST_CAP):
    result = {"source": "Adzuna", "requests": [], "records": [], "request_cap": budget}
    if not key_id or not key:
        result["status"] = "missing_key"
        return result
    used = 0

    def call(path, params):
        nonlocal used
        if used >= budget:
            raise RuntimeError("request_cap_reached")
        used += 1
        query = dict(params, app_id=key_id, app_key=key, **{"content-type": "application/json"})
        url = "https://api.adzuna.com/v1/api/" + path + "?" + urllib.parse.urlencode(query)
        return request_json(url, {"Accept": "application/json"})[0]

    supported = {}
    for region, country in COUNTRIES.items():
        try:
            response = call(f"jobs/{country}/categories", {})
            supported[country] = True
            result["requests"].append({"region": region, "type": "country_check", "status": "ok"})
        except RuntimeError as exc:
            supported[country] = False
            result["requests"].append({"region": region, "type": "country_check", "status": str(exc)})

    for region, country in COUNTRIES.items():
        if not supported.get(country):
            continue
        for query in QUERIES:
            for page in (1, 2):
                if used >= budget:
                    break
                params = {"what": query, "results_per_page": 50, "content-type": "application/json"}
                params["where"] = "London" if region == "London, UK" else ("Switzerland" if region == "Switzerland" else "Russia")
                try:
                    response = call(f"jobs/{country}/search/{page}", params)
                    rows = response.get("results", [])
                    result["records"].extend({"region": region, "query": query, "raw": row} for row in rows)
                    result["requests"].append({"region": region, "query": query, "page": page, "returned": len(rows), "total": response.get("count"), "status": "ok"})
                except RuntimeError as exc:
                    result["requests"].append({"region": region, "query": query, "page": page, "status": str(exc)})
            if used >= budget:
                break
        if used >= budget:
            break
    result["requests_used"] = used
    result["status"] = "queried"
    return result


def superjob(key):
    result = {"source": "SuperJob", "requests": [], "records": []}
    if not key:
        result["status"] = "missing_key"
        return result
    headers = {"X-Api-App-Id": key, "Accept": "application/json"}
    queries = ("C++", "С++", "Senior C++", "low latency", "HFT")
    for query in queries:
        for page in range(5):
            params = urllib.parse.urlencode({"keyword": query, "count": 100, "page": page, "no_agreement": 0})
            try:
                data, _ = request_json("https://api.superjob.ru/2.0/vacancies/?" + params, headers)
                rows = data.get("objects", [])
                result["records"].extend({"region": "Russia", "query": query, "raw": row} for row in rows)
                result["requests"].append({"query": query, "page": page, "returned": len(rows), "total": data.get("total"), "status": "ok"})
                if not data.get("more"):
                    break
            except RuntimeError as exc:
                result["requests"].append({"query": query, "page": page, "status": str(exc)})
                break
            time.sleep(0.55)
    result["status"] = "queried"
    return result


def trudvsem():
    result = {"source": "Работа России", "requests": [], "records": []}
    for query in ("C++ разработчик", "C++ инженер", "C++ программист", "ведущий C++"):
        offset = 0
        total = 0
        while offset < max(total, 1):
            params = urllib.parse.urlencode({"text": query, "limit": 100, "offset": offset})
            try:
                data, _ = request_json("https://opendata.trudvsem.ru/api/v1/vacancies?" + params,
                                       {"Accept": "application/json", "User-Agent": "salary-market-dashboard/1.0"})
                rows = data.get("results", {}).get("vacancies", [])
                total = int(data.get("meta", {}).get("total", 0))
                result["records"].extend({"region": "Russia", "query": query, "raw": row.get("vacancy", row)} for row in rows)
                result["requests"].append({"query": query, "offset": offset, "returned": len(rows), "total": total, "status": "ok"})
                if not rows:
                    break
                offset += len(rows)
            except (RuntimeError, ValueError) as exc:
                result["requests"].append({"query": query, "offset": offset, "status": str(exc) or "invalid_response"})
                break
    result["status"] = "queried"
    return result


def dedupe(source):
    unique = {}
    for record in source["records"]:
        raw = record["raw"]
        if source["source"] == "Headcount Labs":
            key = raw.get("job_id") or raw.get("job_first_seen_at")
        elif source["source"] == "Adzuna":
            key = raw.get("id") or raw.get("redirect_url")
        elif source["source"] == "Работа России":
            key = raw.get("id")
        else:
            key = raw.get("id") or raw.get("id_vacancy") or raw.get("link")
        if not key:
            key = json.dumps(raw, ensure_ascii=False, sort_keys=True)
        if key not in unique:
            unique[key] = {"region": record["region"], "regions": [], "queries": [], "raw": raw}
        for region in record.get("regions") or [record["region"]]:
            if region not in unique[key]["regions"]:
                unique[key]["regions"].append(region)
        if record["query"] not in unique[key]["queries"]:
            unique[key]["queries"].append(record["query"])
    source["records_before_dedupe"] = len(source["records"])
    source["records"] = list(unique.values())
    source["duplicate_hits_removed"] = source["records_before_dedupe"] - len(source["records"])
    return source


def main():
    keys = secrets()
    sources = [
        headcount(keys.get("HEADCOUNTLABS_API_KEY", "")),
        adzuna(keys.get("ADZUNA_APP_ID", ""), keys.get("ADZUNA_APP_KEY", "")),
            superjob(keys.get("SUPERJOB_APP_SECRET", "")),
    ]
    snapshot = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "notice": "Adzuna limited to 24 calls for the authorized 25-call evaluation; salary estimates and vacancy salary fields remain distinct.",
        "sources": [dedupe(source) for source in sources],
    }
    OUT_DIR.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    print("API snapshot saved:", OUT_FILE)
    for source in snapshot["sources"]:
        print(f"{source['source']}: {len(source['records'])} unique records; status={source['status']}")
        if source["source"] == "Adzuna":
            print(f"  Requests used: {source.get('requests_used', 0)}/{source['request_cap']}")


if __name__ == "__main__":
    main()
