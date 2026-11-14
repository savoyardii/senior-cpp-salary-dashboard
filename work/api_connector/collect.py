"""One-shot market snapshot from registered job APIs. Keys stay in local .env."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import base64

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
        query_records = 0
        for page in range(5):
            params = urllib.parse.urlencode({"keyword": query, "count": 100, "page": page, "no_agreement": 0})
            try:
                data, _ = request_json("https://api.superjob.ru/2.0/vacancies/?" + params, headers)
                rows = data.get("objects", [])
                result["records"].extend({"region": "Russia", "query": query, "raw": row} for row in rows)
                result["requests"].append({"query": query, "page": page, "returned": len(rows), "total": data.get("total"), "status": "ok"})
                query_records += len(rows)
                total = data.get("total")
                # Trust total over an inconsistent `more` flag, but stay within SuperJob's 500-result cap.
                if not rows or (isinstance(total, int) and total > 0 and query_records >= total) or (not total and not data.get("more")):
                    break
            except RuntimeError as exc:
                result["requests"].append({"query": query, "page": page, "status": str(exc)})
                break
            time.sleep(0.55)
    result["status"] = "queried"
    return result


def hiring_index(key):
    """Read a bounded C++ slice from Hiring Index's free RapidAPI tier."""
    result = {"source": "Hiring Index", "requests": [], "errors": [], "records": [],
              "request_cap": 3, "result_cap": 300, "status": "missing_key" if not key else "queried"}
    if not key:
        return result
    headers = {"x-rapidapi-host": "hiringindex.p.rapidapi.com", "x-rapidapi-key": key,
               "Accept": "application/json", "Content-Type": "application/json"}
    # 300 rows per run keeps a weekly schedule below the free tier's 2,500 monthly result quota.
    regions = (("Switzerland", "CH", None), ("London, UK", "GB", "London"), ("Russia", "RU", None))
    for region, country, city in regions:
        for page in (1,):
            body = {"keywords": ["C++"], "country_codes": [country], "days_ago": 90,
                    "page": page, "limit": 100}
            if city:
                body["cities"] = [city]
            try:
                data, _ = request_json("https://hiringindex.p.rapidapi.com/jobs/search", headers, body)
            except RuntimeError as exc:
                result["errors"].append({"region": region, "page": page, "status": str(exc)})
                break
            rows = data.get("jobs", [])
            result["requests"].append({"region": region, "page": page, "returned": len(rows), "status": "ok"})
            for row in rows:
                pay = row.get("salary") or {}
                period = str(pay.get("period") or "").casefold()
                period = "year" if "year" in period else "month" if "month" in period else "day" if "day" in period else None
                raw = {
                    "id": row.get("_id"), "title": row.get("title") or "",
                    "employer": row.get("company_name") or "",
                    "description": row.get("description") or "",
                    "city": row.get("city") or "", "country": row.get("country_code") or country,
                    "remote": str(row.get("remote_flag") or "").casefold() == "true",
                    "url": row.get("posting_url") or row.get("apply_url") or "",
                    "application_url": row.get("apply_url") or row.get("posting_url") or "",
                    "source_posted_at": row.get("posted_at") or row.get("first_seen_at"),
                    "expires_at": row.get("validThrough"), "salary_min": pay.get("min"),
                    "salary_max": pay.get("max"), "currency": pay.get("currency"), "period": period,
                    "salary_basis": "job_board" if pay else None, "salary_snippet": row.get("salary_text"),
                }
                result["records"].append({"region": region, "query": "C++", "raw": raw})
    result["status"] = "queried" if result["requests"] else "error"
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


def jooble(keys):
    result = {"source": "Jooble API", "requests": [], "records": [], "request_cap": 3}
    markets = (("Russia", "ru.jooble.org", keys.get("JOOBLE_RU_API_KEY"), "Russia"),
               ("London, UK", "uk.jooble.org", keys.get("JOOBLE_UK_API_KEY"), "London"),
               ("Switzerland", "ch.jooble.org", keys.get("JOOBLE_CH_API_KEY"), "Switzerland"))
    available = [(region, host, key, location) for region, host, key, location in markets if key]
    result["missing_regions"] = [region for region, _, key, _ in markets if not key]
    if not available:
        result["status"] = "missing_key"
        return result
    for region, host, key, location in available:
        try:
            data, _ = request_json(f"https://{host}/api/{urllib.parse.quote(key, safe='')}",
                                   {"Accept": "application/json"},
                                   {"keywords": "C++", "location": location, "page": "1", "ResultOnPage": 50})
            if not isinstance(data, dict):
                raise RuntimeError("invalid_response")
            rows = data.get("jobs", [])
            if not isinstance(rows, list):
                raise RuntimeError("invalid_response")
            result["requests"].append({"region": region, "returned": len(rows), "total": data.get("totalCount"), "status": "ok"})
            for row in rows:
                if not isinstance(row, dict):
                    continue
                url = row.get("link") or ""
                salary = str(row.get("salary") or "")
                raw = {"id": str(row.get("id") or url), "title": row.get("title") or "",
                       "employer": row.get("company") or "", "description": (row.get("snippet") or "") + (f" Salary: {salary}" if salary else ""),
                       "location": row.get("location") or location, "city": row.get("location") or location,
                       "country": {"Russia": "RU", "London, UK": "GB", "Switzerland": "CH"}[region],
                       "url": url, "source_posted_at": row.get("updated"), "salary_snippet": salary,
                       "salary_basis": "job_board" if salary else None}
                result["records"].append({"region": region, "query": "C++", "raw": raw})
        except RuntimeError as exc:
            result["requests"].append({"region": region, "status": str(exc)})
    result["status"] = "queried" if result["requests"] else "missing_key"
    return result


def techmap(key, previous=None):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    used = (previous or {}).get("requests_used_month", 0) if (previous or {}).get("quota_month") == month else 0
    result = {"source": "Techmap API", "requests": [], "records": [], "request_cap_month": 15,
              "requests_used_month": used, "quota_month": month}
    if not key:
        result["status"] = "missing_key"
        return result
    if used + 3 > result["request_cap_month"]:
        result["status"] = "monthly_free_request_cap_reached"
        return result
    headers = {"X-RapidAPI-Key": key, "X-RapidAPI-Host": "daily-international-job-postings.p.rapidapi.com",
               "Accept": "application/json"}
    markets = (("Switzerland", "ch"), ("London, UK", "uk"), ("Russia", "ru"))
    for region, country in markets:
        params = urllib.parse.urlencode({"countryCode": country, "title": "C++", "page": 1, "pageSize": 10, "sort": "newest"})
        try:
            result["requests_used_month"] += 1
            data, _ = request_json("https://daily-international-job-postings.p.rapidapi.com/api/v2/jobs/search?" + params, headers)
            if not isinstance(data, dict):
                raise RuntimeError("invalid_response")
            rows = data.get("result", data.get("jobs", []))
            if not isinstance(rows, list):
                raise RuntimeError("invalid_response")
            result["requests"].append({"region": region, "returned": len(rows), "status": "ok"})
            country_code = {"Switzerland": "CH", "London, UK": "GB", "Russia": "RU"}[region]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                schema = row.get("jsonLD") or {}
                if not isinstance(schema, dict):
                    schema = {}
                place = schema.get("jobLocation") or {}
                if not isinstance(place, dict):
                    place = {}
                address = place.get("address") or {}
                if isinstance(address, list):
                    address = address[0] if address else {}
                address_city = address if isinstance(address, str) else address.get("addressLocality") if isinstance(address, dict) else ""
                city = row.get("city") or address_city or place.get("name") or region
                pay = schema.get("baseSalary") or {}
                if not isinstance(pay, dict):
                    pay = {}
                value = pay.get("value") or {}
                if not isinstance(value, dict):
                    value = {}
                unit = str(value.get("unitText") or "").casefold()
                period = "year" if "year" in unit or "annual" in unit else "month" if "month" in unit else "day" if "day" in unit else None
                raw = {"id": str(schema.get("identifier") or row.get("id") or row.get("url") or ""),
                       "title": row.get("title") or schema.get("title") or "", "employer": row.get("company") or "",
                       "description": schema.get("description") or row.get("description") or "",
                       "location": city, "city": city, "country": country_code,
                       "url": schema.get("url") or row.get("url") or "", "source_posted_at": row.get("dateCreated") or schema.get("datePosted"),
                       "expires_at": schema.get("validThrough"), "salary_min": value.get("minValue"),
                       "salary_max": value.get("maxValue"), "currency": pay.get("currency") or row.get("salaryCurrency"),
                       "period": period, "salary_basis": "job_board" if pay else None}
                result["records"].append({"region": region, "query": "C++", "raw": raw})
        except RuntimeError as exc:
            result["requests"].append({"region": region, "status": str(exc)})
    result["status"] = "queried" if result["requests"] else "missing_key"
    return result


def careerjet(key, user_ip):
    result = {"source": "Careerjet API", "requests": [], "records": []}
    if not key or not user_ip:
        result["status"] = "missing_key_or_user_ip"
        return result
    auth = base64.b64encode((key + ":").encode()).decode()
    markets = (("Switzerland", "de_CH", "Switzerland", "CH"),
               ("London, UK", "en_GB", "London", "GB"),
               ("Russia", "ru_RU", "Russia", "RU"))
    for region, locale, location, country in markets:
        params = urllib.parse.urlencode({"keywords": "C++", "location": location, "locale_code": locale,
                                         "sort": "date", "page": 1, "page_size": 50,
                                         "user_ip": user_ip, "user_agent": "SpectralSalaryDashboard/1.0"})
        try:
            data, _ = request_json("https://search.api.careerjet.net/v4/query?" + params,
                                   {"Authorization": "Basic " + auth, "Accept": "application/json"})
            if not isinstance(data, dict):
                raise RuntimeError("invalid_response")
            rows = data.get("jobs", [])
            if not isinstance(rows, list):
                raise RuntimeError("invalid_response")
            result["requests"].append({"region": region, "returned": len(rows), "total": data.get("hits"), "status": "ok"})
            for row in rows:
                if not isinstance(row, dict):
                    continue
                pay_period = {"Y": "year", "M": "month", "D": "day"}.get(str(row.get("salary_type") or "").upper())
                raw = {"id": str(row.get("url") or row.get("title") or ""), "title": row.get("title") or "",
                       "employer": row.get("company") or "", "description": row.get("description") or "",
                       "location": row.get("locations") or location, "city": row.get("locations") or location,
                       "country": country, "url": row.get("url") or "", "source_posted_at": row.get("date"),
                       "salary_min": row.get("salary_min"), "salary_max": row.get("salary_max"),
                       "currency": row.get("salary_currency_code"), "period": pay_period,
                       "salary_basis": "job_board" if pay_period else None, "salary_snippet": row.get("salary")}
                result["records"].append({"region": region, "query": "C++", "raw": raw})
        except RuntimeError as exc:
            result["requests"].append({"region": region, "status": str(exc)})
    result["status"] = "queried" if result["requests"] else "missing_key"
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
