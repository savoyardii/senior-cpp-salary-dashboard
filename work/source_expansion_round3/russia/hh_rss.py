#!/usr/bin/env python3
"""Bounded, anonymous HeadHunter RSS probe. No CAPTCHA or gate bypass."""
from argparse import ArgumentParser
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


QUERIES = ("C++", "Senior C++", "HFT", "low latency C++")
AREA = "113"  # Russia
FEED_URL = "https://hh.ru/search/vacancy/rss"
USER_AGENT = "salary-market-dashboard/1.0"
VACANCY_ID = re.compile(r"/vacancy/(\d+)")


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "p", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value):
    parser = PlainText()
    parser.feed(html.unescape(value or ""))
    return " ".join(" ".join(parser.parts).split())


def parse_feed(payload, query):
    root = ET.fromstring(payload)
    if root.tag.rsplit("}", 1)[-1].lower() != "rss":
        raise ValueError("unexpected_feed_root")
    channel = next((node for node in root if node.tag.rsplit("}", 1)[-1] == "channel"), None)
    if channel is None:
        raise ValueError("missing_rss_channel")
    records = []
    for item in channel:
        if item.tag.rsplit("}", 1)[-1] != "item":
            continue
        fields = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in item}
        url = fields.get("link", "").strip()
        if not url.startswith("https://hh.ru/vacancy/"):
            continue
        title = plain_text(fields.get("title", ""))
        if not title:
            continue
        description = plain_text(fields.get("description", ""))
        employer_match = re.search(
            r"Вакансия компании:\s*(.+?)(?=\s+(?:Направление\b|Создана\s*:|Регион\s*:|Предполагаемый уровень месячного дохода\s*:)|$)",
            description,
            re.IGNORECASE,
        )
        location_match = re.search(
            r"Регион:\s*(.+?)(?=\s+(?:Вакансия компании|Направление|Создана|Предполагаемый уровень месячного дохода):|$)",
            description,
            re.IGNORECASE,
        )
        pub_date = fields.get("pubDate")
        try:
            published_at = parsedate_to_datetime(pub_date).astimezone(timezone.utc).isoformat() if pub_date else None
        except (TypeError, ValueError, OverflowError):
            published_at = None
        if not published_at:
            created = re.search(r"\bСоздана:\s*(\d{2}\.\d{2}\.\d{4})", description)
            if created:
                try:
                    published_at = datetime.strptime(created.group(1), "%d.%m.%Y").replace(tzinfo=timezone.utc).isoformat()
                except ValueError:
                    pass
        match = VACANCY_ID.search(url)
        guid = plain_text(fields.get("guid", ""))
        record_id = match.group(1) if match else (guid or url)
        records.append({
            "id": record_id,
            "title": title,
            "employer": employer_match.group(1).strip() if employer_match else None,
            "region": "Russia",
            "country": "RU",
            "city": location_match.group(1).strip() if location_match else None,
            "location": location_match.group(1).strip() if location_match else "Russia",
            "url": url,
            "published_at": published_at,
            "description": description,
            "salary_min": None,
            "salary_max": None,
            "currency": None,
            "period": None,
            "salary_basis": None,
            "source": "HeadHunter RSS",
            "query": query,
        })
    return records


def dedupe(records):
    found = {}
    for row in records:
        key = row["url"]
        query = row["query"]
        if key not in found:
            found[key] = {field: value for field, value in row.items() if field != "query"}
            found[key]["queries"] = [query]
        elif query not in found[key]["queries"]:
            found[key]["queries"].append(query)
    return list(found.values())


def collect(queries=QUERIES, opener=urllib.request.urlopen):
    if not 1 <= len(queries) <= len(QUERIES):
        raise ValueError(f"use 1–{len(QUERIES)} queries")
    observed_at = datetime.now(timezone.utc).isoformat()
    result = {"source": "HeadHunter RSS", "observed_at": observed_at, "status": "queried", "requests": [], "records": []}
    records = []
    for query in queries:
        url = FEED_URL + "?" + urllib.parse.urlencode({"area": AREA, "clusters": "true", "enable_snippets": "true", "text": query})
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml"})
        try:
            with opener(request, timeout=20) as response:
                payload = response.read(2_000_001)
                if len(payload) > 2_000_000:
                    raise ValueError("feed_too_large")
                rows = parse_feed(payload, query)
        except urllib.error.HTTPError as exc:
            result["status"] = "blocked" if exc.code in {401, 403, 407, 429} else "error"
            result["requests"].append({"query": query, "status": f"HTTP {exc.code}"})
            exc.close()
            break
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, ET.ParseError) as exc:
            result["status"] = "blocked" if str(exc) in {"unexpected_feed_root", "missing_rss_channel"} else "error"
            result["requests"].append({"query": query, "status": type(exc).__name__ if not isinstance(exc, ValueError) else str(exc)})
            break
        result["requests"].append({"query": query, "returned": len(rows), "status": "ok"})
        records.extend(rows)
    result["records"] = dedupe(records)
    return result


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--query", action="append", help=f"Override search queries; at most {len(QUERIES)} requests")
    parser.add_argument("--fixture", type=Path, help="Parse one saved RSS XML file without network access")
    args = parser.parse_args()
    if args.fixture:
        result = {"source": "HeadHunter RSS", "status": "fixture", "records": parse_feed(args.fixture.read_bytes(), "fixture")}
    else:
        result = collect(tuple(args.query) if args.query else QUERIES)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
