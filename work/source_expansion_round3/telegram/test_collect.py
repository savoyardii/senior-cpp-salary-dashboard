import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import collect


class TelegramParserTests(unittest.TestCase):
    def test_collects_public_post_and_salary_without_account(self):
        fixture = '''<div class="tgme_widget_message_wrap" data-post="switzerlanddevjobs/42">
          <div class="tgme_widget_message"><div class="tgme_widget_message_text">Weekly C++ roles<br>
          ➡️ Senior C++ Engineer | Example AG<br>[📍 Zurich] [💰 CHF 140'000 - 180'000]
          <a href="https://example.org/job">Apply</a></div><time datetime="2026-11-12T08:00:00+00:00"></time></div></div>'''
        rows, posts = collect.parse_page("switzerlanddevjobs", fixture)
        self.assertEqual(len(posts), 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://t.me/switzerlanddevjobs/42")
        self.assertEqual(rows[0]["region"], "Switzerland")
        self.assertEqual(rows[0]["country"], "CH")
        self.assertIn("CHF 140'000 - 180'000", rows[0]["salary_raw_snippet"])
        self.assertEqual((rows[0]["salary_min"], rows[0]["salary_max"]), (140000, 180000))
        self.assertEqual(rows[0]["published_at"], "2026-11-12T08:00:00+00:00")

    def test_ignores_non_cpp_post(self):
        fixture = '<div class="tgme_widget_message_wrap" data-post="devitjobs/3"><div>Python Developer</div></div>'
        rows, _ = collect.parse_page("devitjobs", fixture)
        self.assertEqual(rows, [])

    def test_post_without_identifier_does_not_break_pagination(self):
        fixture = '<div class="tgme_widget_message_wrap"><div>Channel notice</div></div>'
        with patch.object(collect, "fetch", return_value=fixture):
            result = collect.collect(channels=("cppdevjob",), page_limit=1, delay=0)
        self.assertEqual(result["attempts"][0]["status"], "ok")

    def test_current_markup_reads_inner_post_id_and_skips_channel_header(self):
        fixture = '''<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message" data-post="cppdevjob/2569">
          <div class="tgme_widget_message_text">Вакансии по C++ — си-плюс-плюс<br>💻 Senior C++ Engineer | Example<br>📍 Москва<br>380 000–450 000 ₽ на руки</div>
          ➡️ Откликнуться<br><time datetime="2026-11-12T08:00:00+00:00"></time></div></div>'''
        rows, _ = collect.parse_page("cppdevjob", fixture)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://t.me/cppdevjob/2569")
        self.assertEqual(rows[0]["title"], "Senior C++ Engineer | Example")
        self.assertEqual(rows[0]["region"], "Russia")

    def test_russian_channel_header_is_not_used_as_job_title(self):
        fixture = '''<div class="tgme_widget_message_wrap" data-post="c_rabota/1241"><div>
          C/C++ Работа вакансии #senior<br>Прософт-Системы<br>Старший инженер-программист C++/Qt<br>Опыт работы: 3–6 лет<br>Формат работы: офис (Екатеринбург)
          </div></div>'''
        rows, _ = collect.parse_page("c_rabota", fixture)
        self.assertEqual(rows[0]["title"], "Старший инженер-программист C++/Qt")
        self.assertEqual(rows[0]["region"], "Russia")

    def test_new_channels_strip_channel_name_and_keep_salary_scale(self):
        fixture = '''<div class="tgme_widget_message_wrap" data-post="forcpp/42"><div>
          Job for C, C++ Developers<br>Senior C++ Engineer<br>Location: Russia<br>Salary: $5–7k per month
        </div></div>'''
        rows, _ = collect.parse_page("forcpp", fixture)
        self.assertEqual(rows[0]["title"], "Senior C++ Engineer")
        self.assertEqual(rows[0]["region"], "Russia")
        self.assertEqual((rows[0]["salary_min"], rows[0]["salary_max"]), (5000, 7000))
        self.assertEqual(rows[0]["period"], "month")

    def test_multi_grade_pay_is_not_merged_and_worldwide_rub_is_unassigned(self):
        salary = collect._salary_fields("Salary: 5–7k USD/month (middle), 7–14k USD/month (senior)")
        self.assertIsNone(salary["salary_min"])
        self.assertIsNone(salary["period"])
        self.assertEqual(collect._normalized_region("ProCxxJobs", "remote по всему миру", {
            "currency": "RUB", "salary_raw_snippet": "200000 RUB/month"}), (None, None))

    def test_period_is_not_guessed_from_unrelated_description(self):
        salary = collect._salary_fields("Оплата — 288–316 тыс. ₽. Рабочий день с 9 до 18 часов.")
        self.assertIsNone(salary["period"])

    def test_direct_job_link_is_preserved(self):
        fixture = '''<div class="tgme_widget_message_wrap" data-post="forcpp/43"><div>
          Job for C, C++ Developers<br>Senior C++ Engineer<br>Location: Russia<br>
          <a href="https://jobs.example/role">https://jobs.example/role</a>
        </div></div>'''
        rows, _ = collect.parse_page("forcpp", fixture)
        self.assertEqual(rows[0]["application_url"], "https://jobs.example/role")

    def test_company_about_page_is_not_a_job_link(self):
        fixture = '''<div class="tgme_widget_message_wrap" data-post="ProCxxJobs/43"><div>
          Pro.* Jobs<br>Senior C++ Engineer<br>Location: Russia<br>
          <a href="https://example.com/about">https://example.com/about</a>
        </div></div>'''
        rows, _ = collect.parse_page("ProCxxJobs", fixture)
        self.assertIsNone(rows[0]["application_url"])

    def test_company_name_next_to_about_link_is_not_used_as_job_url(self):
        fixture = '''<div class="tgme_widget_message_wrap" data-post="ProCxxJobs/44"><div>
          Pro.* Jobs<br>NS Digital (https://example.com/about)<br>
          Senior C++ Developer<br>Salary: 230–345 тыс. ₽ в месяц
        </div></div>'''
        rows, _ = collect.parse_page("ProCxxJobs", fixture)
        self.assertEqual(rows[0]["employer"], "NS Digital")
        self.assertIsNone(rows[0]["application_url"])


if __name__ == "__main__":
    unittest.main()
