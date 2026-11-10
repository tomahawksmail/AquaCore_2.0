"""Regression coverage: MySQL TIME fields render valid HTML time values."""
import ast
from datetime import datetime, time, timedelta
from pathlib import Path
import unittest

from time_utils import html_time

ROOT = Path(__file__).resolve().parents[1]


class HtmlTimeTests(unittest.TestCase):
    def test_mysql_time_round_trip(self):
        self.assertEqual(html_time(timedelta(hours=8)), "08:00")
        self.assertEqual(html_time(timedelta(hours=0, minutes=5)), "00:05")
        self.assertEqual(html_time(timedelta(hours=23, minutes=59)), "23:59")
        self.assertEqual(html_time(timedelta(hours=12, minutes=30)), "12:30")

    def test_python_and_text_times(self):
        self.assertEqual(html_time(time(8, 0)), "08:00")
        self.assertEqual(html_time(datetime(2026, 11, 9, 8, 15)), "08:15")
        self.assertEqual(html_time("8:00:00"), "08:00")
        self.assertEqual(html_time("08:00:00"), "08:00")
        self.assertEqual(html_time("8:00"), "08:00")
        self.assertEqual(html_time("20:45:00"), "20:45")

    def test_invalid_or_missing(self):
        for value in (None, "8:00:", "24:00", "08:60", "", timedelta(hours=25), timedelta(hours=-1)):
            with self.subTest(value=value):
                self.assertEqual(html_time(value), "")

    def test_both_pumps_and_other_time_fields_use_filter(self):
        page = (ROOT / "templates" / "options.html").read_text()
        for text in ("fertilizer.start_time|html_time",
                     "fertilizer2.start_time|html_time",
                     "options[on]|html_time", "options[off]|html_time"):
            self.assertIn(text, page)
        self.assertNotIn("start_time|string|truncate(5", page)

    def test_api_round_trip_verification(self):
        app = (ROOT / "app.py").read_text()
        ast.parse(app)
        self.assertIn("app.jinja_env.filters['html_time']", app)
        self.assertIn("html_time(confirmed['start_time'])", app)


if __name__ == "__main__":
    unittest.main()
