from pathlib import Path
import importlib.util
import json
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from collect import adzuna as collect_adzuna
from collect import dedupe, secrets

SNAPSHOT = ROOT / "data/latest.json"
spec = importlib.util.spec_from_file_location("collect_module", ROOT / "collect.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def main():
    snapshot = json.loads(SNAPSHOT.read_text())
    source = next(row for row in snapshot["sources"] if row["source"] == "Adzuna")
    used = source.get("requests_used", 0)
    extra = 9
    if used + extra > 24:
        raise SystemExit(f"Request budget would exceed 24 (already used {used}).")
    keys = secrets()
    app_id, app_key = keys.get("ADZUNA_APP_ID", ""), keys.get("ADZUNA_APP_KEY", "")
    if not app_id or not app_key:
        raise SystemExit("Adzuna keys are missing.")
    additions = []
    # Reuse the same safe request implementation and the already-authorized 25-call limit.
    for page in range(3, 12):
        params = {"what": "C++", "where": "London", "results_per_page": 50, "content-type": "application/json"}
        query = dict(params, app_id=app_id, app_key=app_key)
        url = "https://api.adzuna.com/v1/api/jobs/gb/search/" + str(page) + "?" + module.urllib.parse.urlencode(query)
        try:
            response, _ = module.request_json(url, {"Accept": "application/json"})
            rows = response.get("results", [])
            additions.extend({"region": "London, UK", "query": "C++", "raw": row} for row in rows)
            source["requests"].append({"region": "London, UK", "query": "C++", "page": page, "returned": len(rows), "total": response.get("count"), "status": "ok"})
        except RuntimeError as exc:
            source["requests"].append({"region": "London, UK", "query": "C++", "page": page, "status": str(exc)})
            break
    source["records"].extend(additions)
    source["requests_used"] = used + 9
    source["records"] = dedupe(source)["records"]
    snapshot["sources"] = [source if s["source"] == "Adzuna" else s for s in snapshot["sources"]]
    SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    print(f"Adzuna London C++ pages 3–11 collected; total requests used: {source['requests_used']}/24; unique records: {len(source['records'])}.")


if __name__ == "__main__":
    main()
