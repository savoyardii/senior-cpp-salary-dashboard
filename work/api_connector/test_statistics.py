"""Offline regressions for demonstrated classification and salary defects."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import auto_monitor as m
import collect
import refresh


class SalaryEvidenceTests(unittest.TestCase):
    def test_dates_and_durations_never_become_money(self):
        for text in ('Start Date: July 2026. End Date: 6 months. Daily Rate: Inside IR35',
                     'Annual salary 120000; start date July 2026',
                     'Company revenue £120000 per year; salary competitive'):
            self.assertIsNone(m.salary_from_description(text, 'GBP'))
        self.assertEqual(m.salary_from_description('Posted 12 November 2026. Salary £600 per day', 'GBP')['min'], 600)

    def test_shared_scale_and_currency_ranges(self):
        for text in ('Base salary £100-150k per year', 'Salary £100k–£150k per year', 'Salary 100–150k GBP per annum'):
            pay = m.salary_from_description(text, 'GBP')
            self.assertEqual((pay['min'], pay['max']), (100000, 150000))
        self.assertIsNone(m.salary_from_description('Salary £100k–$150k per year', 'GBP'))
        self.assertEqual(m.salary_from_description('от 300 тыс. руб. в месяц', 'RUB')['max'], None)

    def test_bonus_and_total_pay(self):
        for text in ('£100k total compensation per year', 'Bonus £10000 per year', '£10000 bonus per year', 'OTE £120000 per year'):
            self.assertIsNone(m.salary_from_description(text, 'GBP'))
        for text in ('Salary £120,000 per year; bonus 20%', 'Base salary £120000 per year plus bonus', '20% bonus, base salary £120k per year'):
            self.assertEqual(m.salary_from_description(text, 'GBP')['min'], 120000)

    def test_predicted_flag_is_a_hard_gate(self):
        for flag in ('1', True, 'true', None):
            raw = {} if flag is None else {'salary_is_predicted': flag}
            self.assertEqual(m.salary_rows('Adzuna', 'London, UK', raw, 'Salary £120000 per year'), [])
        self.assertEqual(m.salary_rows('Adzuna', 'London, UK', {'salary_is_predicted': '0'}, 'Salary £120000 per year')[0]['min'], 120000)

    def test_trust_boundary_on_api_money(self):
        for bounds in ((-1, 100), (100, 1), (float('inf'), 100), (True, 100)):
            self.assertFalse(m.valid_pay(*bounds))


class ScopeAndDedupTests(unittest.TestCase):
    def test_senior_uses_lower_bound_not_upper(self):
        for text in ('5+ years of experience', '6 years of software development experience', '7+ years experience in C++', '10 years professional experience', 'опыт работы от 6 лет'):
            self.assertTrue(m.senior('C++ Developer', text), text)
        self.assertTrue(m.senior('C++ тимлид', ''))
        for text in ('3–5 years of experience', '2 to 5 years of experience', 'between 3 and 5 years of experience', '6 months experience in C++', 'C++ experience; 10 years is ideal', '5 years of sales experience; C++ experience 6 months', 'Company founded 10 years ago'):
            self.assertFalse(m.senior('C++ Developer', text), text)
        self.assertFalse(m.senior('Junior C++ Developer', '10 years experience'))

    def test_remote_alternatives(self):
        for region, code in (('Switzerland', 'CH'), ('Russia', 'RU')):
            self.assertTrue(m.local_market(region, [{'city': 'Remote', 'remote': True, 'alternatives': [{'country': code}]}]))

    def test_source_id_dedupe_preserves_markets(self):
        src = {'source': 'Headcount Labs', 'records': [{'region': r, 'query': 'C++', 'raw': {'job_id': 'one'}} for r in ('Switzerland', 'London, UK')]}
        out = collect.dedupe(src)
        self.assertEqual(len(out['records']), 1)
        self.assertEqual(out['records'][0]['regions'], ['Switzerland', 'London, UK'])

    def test_real_snapshot_preserves_trace_and_removes_false_salary(self):
        snapshot = json.loads((Path(__file__).parent / 'data/latest.json').read_text())
        out = m.build_monitor(snapshot)
        self.assertTrue(out['excluded'])
        self.assertIsNone(next(s for s in out['sources'] if s['source'] == 'Adzuna')['updated_at'])
        for group in out['groups']:
            for pay in group['salary']:
                self.assertTrue(pay['urls'])
                self.assertTrue(pay['snippet'])
                self.assertTrue(pay['observed_at'])
                self.assertNotEqual((pay['min'], pay['period']), (2026, 'day'))
        wintermute = [g for g in out['groups'] if 'wintermute' in g['employer'].lower() and 'C++' in g['title']]
        self.assertEqual(wintermute, [])  # These real postings do not establish Senior/5+ experience.

    def test_cross_source_london_variants_and_description_evidence(self):
        description = 'Strong C++ software development skills, automated tests and scalable production systems. ' * 5
        headcount = {'region': 'London, UK', 'raw': {'job_id': 'hc', 'title': {'value': 'Senior C++ Developer'},
                     'employer_name': {'value': 'Example'}, 'description': {'value': description},
                     'postings': [{'posting_status': 'listed', 'location': {'value': {'city': 'London', 'country': 'GB'}}}]}}
        adzuna = {'region': 'London, UK', 'raw': {'id': 'az', 'title': 'Senior C++ Developer', 'company': {'display_name': 'Example'},
                  'description': description[:300], 'location': {'display_name': 'London, UK'}, 'salary_is_predicted': '1'}}
        snapshot = {'sources': [{'source': 'Headcount Labs', 'records': [headcount]}, {'source': 'Adzuna', 'records': [adzuna]}]}
        groups = m.build_monitor(snapshot)['groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['sources'], ['Headcount Labs', 'Adzuna'])

    def test_cross_source_title_variants_dedupe_only_with_matching_description(self):
        description = 'Senior C++ engineer designs and maintains production trading systems. ' * 5
        rows = [
            {'region': 'London, UK', 'raw': {'id': 'one', 'title': 'Senior C++ Software Engineer',
             'company': {'display_name': 'Example'}, 'description': description,
             'location': {'display_name': 'London, UK'}, 'salary_is_predicted': '1'}},
            {'region': 'London, UK', 'raw': {'title': 'Senior Software Engineer C++',
             'employer': 'Example', 'description': description, 'city': 'London', 'country': 'GB',
             'observed_at': datetime.now(timezone.utc).isoformat()}},
        ]
        snapshot = {'sources': [{'source': 'Adzuna', 'records': [rows[0]]}, {'source': 'ITJobsWatch', 'records': [rows[1]]}]}
        groups = m.build_monitor(snapshot)['groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]['sources']), {'Adzuna', 'ITJobsWatch'})

    def test_jobboard_suspicious_salary_is_not_reparsed_from_description(self):
        raw = {'salary_min': 10000, 'salary_max': 80000, 'currency': 'GBP', 'period': 'year',
               'flags': ['salary_suspicious'], 'url': 'https://example.test/job'}
        self.assertEqual(m.salary_rows('Reed', 'London, UK', raw, 'Salary £10,000–£80,000 per year'), [])

    def test_jobboard_segment_can_distinguish_hft_context_from_the_role(self):
        raw = {'title': 'Senior C++ Software Engineer', 'employer': 'Example', 'description':
               'Build trading platforms. Company founders have HFT backgrounds.', 'city': 'London',
               'country': 'GB', 'segment': 'trading_finance', 'observed_at': datetime.now(timezone.utc).isoformat(),
               'url': 'https://example.test/job'}
        group = m.build_monitor({'sources': [{'source': 'UK Government Work Hub',
                                   'records': [{'region': 'London, UK', 'raw': raw}]}]})['groups'][0]
        self.assertEqual(group['segment'], 'trading_finance')

    def test_same_title_different_requisitions_not_silently_collapsed(self):
        raw = {'title': {'value': 'Senior C++ Developer'}, 'employer_name': {'value': 'Example'},
               'description': {'value': 'Develop C++ software. ' * 30}, 'postings': [{'posting_status': 'listed', 'location': {'value': {'city': 'London', 'country': 'GB'}}}]}
        records = [{'region': 'London, UK', 'raw': {**copy.deepcopy(raw), 'job_id': str(i)}} for i in range(2)]
        out = m.build_monitor({'sources': [{'source': 'Headcount Labs', 'records': records, 'retrieved_at': datetime.now(timezone.utc).isoformat()}]})
        self.assertEqual(len(out['groups']), 2)

    def test_snapshot_archive_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(refresh, 'SNAPSHOT', Path(directory) / 'latest.json'):
            refresh.archive_snapshot({'observed_at': '2026-11-12T12:00:00Z', 'sources': []})
            refresh.archive_snapshot({'observed_at': '2026-11-12T12:00:00Z', 'sources': []})
            files = list((Path(directory) / 'snapshots').glob('*.json'))
            self.assertEqual(len(files), 1)
            self.assertEqual(json.loads(files[0].read_text())['sources'], [])


if __name__ == '__main__':
    unittest.main()
