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


if __name__ == "__main__":
    unittest.main()
