import unittest

import collect


class GreenhouseNormalizeTests(unittest.TestCase):
    def test_accepts_london_cpp_posting(self):
        row = collect.normalize("DV Trading", {
            "id": 1, "title": "Senior C++ Engineer", "absolute_url": "https://example.test/1",
            "location": {"name": "London, UK"}, "content": "Low latency C++ systems",
        }, "2026-11-12T00:00:00+00:00")
        self.assertEqual(row["region"], "London, UK")
        self.assertEqual(row["country"], "GB")
        self.assertEqual(row["source_id"], "1")

    def test_rejects_other_regions_and_non_cpp_roles(self):
        base = {"id": 1, "title": "Quant Developer", "location": {"name": "New York"}, "content": "Python and C++"}
        self.assertIsNone(collect.normalize("Example", base, "now"))
        base["location"] = {"name": "London, UK"}
        base["content"] = "Python and Java"
        self.assertIsNone(collect.normalize("Example", base, "now"))


if __name__ == "__main__":
    unittest.main()
