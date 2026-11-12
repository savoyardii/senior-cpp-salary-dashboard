import unittest
from collect import normalize


class LeverAshbyNormalizeTests(unittest.TestCase):
    def test_lever_accepts_explicit_london_cpp_role(self):
        rows = normalize("Lever: Wintermute", "lever", {
            "id": "a1", "text": "C++ Quant Developer", "hostedUrl": "https://jobs.lever.co/wintermute/a1",
            "categories": {"location": "London"}, "descriptionPlain": "Build C++ trading systems.",
            "salaryRange": {"currency": "GBP", "interval": "per year", "min": 100000, "max": 160000},
        }, "2026-11-12T00:00:00+00:00")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["region"], "London, UK")
        self.assertEqual(rows[0]["raw"]["salary_min"], 100000)
        self.assertEqual(rows[0]["raw"]["period"], "year")

    def test_ashby_filters_non_target_location_and_missing_cpp(self):
        job = {"id": "b2", "title": "Senior Engineer", "location": "New York", "descriptionPlain": "C++"}
        self.assertEqual(normalize("Ashby: Teza", "ashby", job, "now"), [])
        job.update(location="London", descriptionPlain="Python and Java")
        self.assertEqual(normalize("Ashby: Teza", "ashby", job, "now"), [])

    def test_ashby_normalizes_switzerland_compensation(self):
        rows = normalize("Ashby: Example", "ashby", {
            "id": "c3", "title": "Senior C++ Engineer", "location": "Zürich, Switzerland",
            "descriptionPlain": "Develop C++ systems.", "jobUrl": "https://jobs.ashbyhq.com/example/c3",
            "compensation": {"summaryComponents": [{"compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "CHF", "minValue": 150000, "maxValue": 180000}]},
        }, "2026-11-12T00:00:00+00:00")
        self.assertEqual(rows[0]["region"], "Switzerland")
        self.assertEqual(rows[0]["raw"]["currency"], "CHF")
        self.assertEqual(rows[0]["raw"]["period"], "year")


if __name__ == "__main__":
    unittest.main()
