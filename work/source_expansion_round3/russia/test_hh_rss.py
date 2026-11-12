import unittest
from pathlib import Path
from urllib.error import HTTPError

from hh_rss import collect, dedupe, parse_feed


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "hh_rss.xml"


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit):
        return self.body


class HhRssTest(unittest.TestCase):
    def test_fixture_normalizes_listing_and_ignores_external_url(self):
        rows = parse_feed(FIXTURE.read_bytes(), "C++")
        self.assertEqual(["123456789", "987654321"], [row["id"] for row in rows])
        self.assertEqual("Senior C++ Developer", rows[0]["title"])
        self.assertEqual("2026-11-11T07:30:00+00:00", rows[0]["published_at"])
        self.assertIn("от 300 000 руб.", rows[0]["description"])
        self.assertIsNone(rows[0]["salary_min"])
        self.assertIsNone(rows[1]["published_at"])

    def test_duplicate_urls_keep_all_query_labels(self):
        rows = parse_feed(FIXTURE.read_bytes(), "C++")
        again = parse_feed(FIXTURE.read_bytes(), "HFT")
        merged = dedupe(rows + again)
        self.assertEqual(2, len(merged))
        self.assertEqual(["C++", "HFT"], merged[0]["queries"])

    def test_access_gate_stops_remaining_queries(self):
        calls = []

        def gated(request, timeout):
            calls.append(request.full_url)
            raise HTTPError(request.full_url, 403, "Forbidden", {}, None)

        result = collect(("C++", "HFT"), opener=gated)
        self.assertEqual(1, len(calls))
        self.assertEqual("blocked", result["status"])
        self.assertEqual([], result["records"])
        self.assertEqual("HTTP 403", result["requests"][0]["status"])

    def test_query_limit_is_enforced(self):
        with self.assertRaises(ValueError):
            collect(("1", "2", "3", "4", "5"), opener=lambda *_args, **_kwargs: None)


if __name__ == "__main__":
    unittest.main()
