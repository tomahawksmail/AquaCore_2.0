"""Unit tests for Telegram's system chart filtering and line smoothing."""
import math
import unittest
from datetime import datetime, timedelta
from telegram_system_trends import split_system_samples, trailing_mean


class TelegramSystemTrendTests(unittest.TestCase):
    def setUp(self):
        self.t = datetime(2026, 11, 10, 12, 0)

    def test_valid_rows_and_outage_gaps(self):
        rows = [
            {"Datetime": self.t, "RAM_total": 970, "cpus_percent_0": 20},
            {"Datetime": self.t + timedelta(minutes=1), "RAM_total": 0, "cpus_percent_0": 0},
            {"Datetime": self.t + timedelta(minutes=10), "RAM_total": 970, "cpus_percent_0": 40},
            {"Datetime": self.t + timedelta(minutes=40), "RAM_total": 970, "cpus_percent_0": 60},
        ]
        segments = split_system_samples(rows)
        self.assertEqual([len(segment) for segment in segments], [2, 1])
        self.assertEqual([r["cpus_percent_0"] for r in segments[0]], [20, 40])

    def test_rolling_cpu_smoothing(self):
        rows = [{"cpus_percent_0": v} for v in (0, 90, 0, 60)]
        self.assertEqual(trailing_mean(rows, "cpus_percent_0", window=3,
                                       minimum=0, maximum=100), [0, 45, 30, 50])

    def test_missing_values_break_line_without_zero_spikes(self):
        rows = [{"cpu_thermal_cur": v} for v in (55, None, 0, 56)]
        result = trailing_mean(rows, "cpu_thermal_cur", window=1,
                               minimum=0.1, maximum=130)
        self.assertEqual(result[0], 55)
        self.assertTrue(math.isnan(result[1]))
        self.assertTrue(math.isnan(result[2]))
        self.assertEqual(result[3], 56)

    def test_zero_cpu_is_valid(self):
        self.assertEqual(trailing_mean(
            [{"cpus_percent_0": 0}, {"cpus_percent_0": 10}],
            "cpus_percent_0", window=3, minimum=0, maximum=100), [0, 5])


if __name__ == "__main__":
    unittest.main()
