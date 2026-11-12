#!/usr/bin/env python3
"""Fetch recent posts from public Telegram channel previews; no account or API key."""
import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHANNELS = {
    "cppdevjob": "RU",
    "c_rabota": "RU",
    "switzerlanddevjobs": "CH",
    "devitjobs": "GB",
    "jobsineu": None,
    "visasponsor": None,
}
PAGE_LIMIT = 3
VACANCY_RE = re.compile(r"(?:c/c\+\+|c\+\+|c\s*\+\+|\bhft\b|\bhigh[- ]frequency\b|\blow[- ]latency\b|\bquant(?:itative)? developer\b|\btrading systems\b)", re.I)
SALARY_RE = re.compile(r"[^\n]*(?:₽|руб\w*|CHF|£|GBP|\$|USD|EUR|€)[^\n]*", re.I)


class TelegramHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.posts = []
        self.current = None
        self.div_depth = 0
        self.capture_link = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag == "div" and self.current is None and "tgme_widget_message_wrap" in classes:
            self.current = {"text": [], "links": [], "post": attrs.get("data-post"), "date": None}
            self.div_depth = 1
            return
        if self.current is None:
            return
        if tag == "div":
            self.div_depth += 1
        if tag == "time" and attrs.get("datetime"):
            self.current["date"] = attrs["datetime"]
        if tag == "a" and attrs.get("href"):
            self.current["links"].append(attrs["href"])
        if tag == "br":
            self.current["text"].append("\n")

    def handle_endtag(self, tag):
        if self.current is None or tag != "div":
            return
        self.div_depth -= 1
        if self.div_depth == 0:
            self.current["text"] = "".join(self.current["text"])
            self.posts.append(self.current)
            self.current = None

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)


def post_segments(text):
    chunks = re.split(r"➡️", text)[1:] if "➡️" in text else [text]
    return [chunk.strip() for chunk in chunks if VACANCY_RE.search(chunk)]


def _salary_fields(segment):
    matches = [m.group(0).strip() for m in SALARY_RE.finditer(segment)]
    if not matches:
        return {"salary_min": None, "salary_max": None, "currency": None,
                "period": None, "salary_raw_snippet": None}
    snippet = " | ".join(matches)
    currency = next((code for token, code in (("₽", "RUB"), ("руб", "RUB"),
                     ("CHF", "CHF"), ("£", "GBP"), ("GBP", "GBP"),
                     ("$", "USD"), ("USD", "USD"), ("€", "EUR"), ("EUR", "EUR"))
                    if re.search(re.escape(token), snippet, re.I)), None)
    amounts = []
    for token in matches:
        for number in re.findall(r"(?<![\w])\d[\d,'’]*(?:\.\d+)?\s*[kK]?", token):
            number = number.replace("'", "").replace("’", "").replace(",", "").replace(" ", "")
            multiplier = 1000 if number.lower().endswith("k") else 1
            try:
                amounts.append(float(number.rstrip("kK")) * multiplier)
            except ValueError:
                pass
    period = "year" if re.search(r"\b(?:per year|per annum|yearly|annually|annual|p\.a\.)\b|/(?:year|yr)\b", snippet, re.I) else None
    if re.search(r"\b(?:per month|monthly|month)\b|/(?:month|mo)\b", snippet, re.I):
        period = "month"
    if re.search(r"\b(?:per day|daily|day rate)\b|/day\b", snippet, re.I):
        period = "day"
    return {"salary_min": min(amounts) if amounts else None,
            "salary_max": max(amounts) if amounts else None,
            "currency": currency, "period": period, "salary_raw_snippet": snippet}


def _location(segment):
    match = re.search(r"(?:📍\s*|Location\s*:\s*)([^\]\n]+)", segment, re.I)
    return match.group(1).strip() if match else None


def _normalized_region(channel, location, salary):
    location_l = (location or "").lower()
    if channel == "switzerlanddevjobs" or "switzerland" in location_l or "schweiz" in location_l or "zurich" in location_l or "zürich" in location_l or "geneva" in location_l or "basel" in location_l or "chur" in location_l:
        return "Switzerland", "CH"
    if channel == "devitjobs" and "london" in location_l:
        return "London, UK", "GB"
    if channel in {"cppdevjob", "c_rabota"} and (salary.get("currency") == "RUB" or re.search(r"\b(?:Russia|Россия|РФ|Москва|Санкт-Петербург|Петербург|Казань|Новосибирск)\b", (location or "") + " " + (salary.get("salary_raw_snippet") or ""), re.I)):
        return "Russia", "RU"
    if "london" in location_l:
        return "London, UK", "GB"
    return None, None


def parse_page(source, html_text):
    parser = TelegramHTML()
    parser.feed(html_text)
    out = []
    for post in parser.posts:
        text = re.sub(r"[ \t]+", " ", post["text"])
        text = re.sub(r" *\n *", "\n", text).strip()
        if not text or not post.get("post"):
            continue
        post_url = "https://t.me/" + post["post"]
        for index, segment in enumerate(post_segments(text)):
            lines = [line.strip() for line in segment.splitlines() if line.strip()]
            title = re.sub(r"^➡️\s*", "", lines[0])[:180] if lines else ""
            salary = _salary_fields(segment)
            location = _location(segment)
            region, country = _normalized_region(source, location, salary)
            seniority = "senior" if re.search(r"\b(senior|lead|staff|principal|ведущ\w*|старш\w*)\b", title, re.I) else None
            role_match = bool(VACANCY_RE.search(title))
            senior_match = seniority == "senior" or bool(re.search(r"\b(hft|low[- ]latency|high[- ]frequency)\b", title, re.I))
            employer = None
            if " | " in title:
                employer = title.rsplit(" | ", 1)[-1].strip() or None
            out.append({
                "source": f"Telegram @{source}",
                "source_id": f"{post['post']}:{index}",
                "url": post_url,
                "title": title,
                "employer": employer,
                "region": region,
                "country": country,
                "location": [location] if location else [],
                "description": segment,
                **salary,
                "published_at": post.get("date"),
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "links": post["links"],
                "status": "listed_current_status_unverified",
                "strict_eligible": bool(role_match and senior_match),
                "strict_evidence": [title] if role_match and senior_match else [],
                "seniority_evidence": title if seniority else None,
                "cohort": seniority,
                "salary_provenance": "explicit Telegram post text" if salary["salary_raw_snippet"] else None,
                "needs_manual_currentness_check": True,
            })
    return out, parser.posts


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; salary-dashboard/1.0)"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", "replace")


def collect(channels=None, page_limit=PAGE_LIMIT, delay=0.7):
    candidates, attempts = [], []
    for channel in channels or CHANNELS:
        before = None
        seen_before = set()
        for page in range(1, page_limit + 1):
            url = f"https://t.me/s/{channel}"
            if before:
                url += "?" + urllib.parse.urlencode({"before": before})
            attempt = {"channel": channel, "page": page, "url": url}
            try:
                html_text = fetch(url)
                rows, posts = parse_page(channel, html_text)
                candidates.extend(rows)
                ids = [p.get("post", "").rsplit("/", 1)[-1] for p in posts]
                next_before = min((int(i) for i in ids if i.isdigit()), default=None)
                attempt.update(status="ok", posts=len(posts), candidates=len(rows))
                if next_before is None or str(next_before) in seen_before:
                    attempts.append(attempt)
                    break
                seen_before.add(str(next_before))
                before = str(next_before)
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                attempt.update(status="error", error=type(exc).__name__)
                attempts.append(attempt)
                break
            attempts.append(attempt)
            if page < page_limit:
                time.sleep(delay)
    deduped = {row["source_id"]: row for row in candidates}
    return {"observed_at": datetime.now(timezone.utc).isoformat(), "sources": list(CHANNELS),
            "attempts": attempts, "records": list(deduped.values())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channels", nargs="+", choices=CHANNELS)
    parser.add_argument("--pages", type=int, default=PAGE_LIMIT)
    parser.add_argument("--output", type=Path, default=ROOT / "candidates.json")
    args = parser.parse_args()
    result = collect(args.channels, max(1, min(args.pages, 5)))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    summary = {"attempts": len(result["attempts"]), "ok": sum(a.get("status") == "ok" for a in result["attempts"]),
               "candidate_posts": len(result["records"]), "by_source": {}}
    for row in result["records"]:
        summary["by_source"][row["source"]] = summary["by_source"].get(row["source"], 0) + 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
