"""Regression tests for pH median sampling and shared dashboard history pipeline."""
import math
from pathlib import Path
import unittest

from tds_collector import median_ph_voltage

ROOT = Path(__file__).resolve().parents[1]


class PhMedianSamplingTests(unittest.TestCase):
    def test_five_samples_over_four_seconds_reject_one_large_spike(self):
        samples = iter([1.100, 1.101, 1.700, 1.099, 1.102])
        channels = []
        delays = []

        def reader(bus, address, channel):
            channels.append((bus, address, channel))
            return 9000, next(samples)

        result = median_ph_voltage(2, 0x48, count=5, spacing_s=1.0,
                                   reader=reader, sleeper=delays.append)
        self.assertAlmostEqual(result, 1.101, places=5)
        self.assertEqual(channels, [(2, 0x48, 0)] * 5)
        self.assertEqual(delays, [1.0] * 4)

    def test_three_readings_are_supported(self):
        samples = iter([1.5, 1.2, 1.3])
        result = median_ph_voltage(2, 0x48, count=3, spacing_s=0.5,
                                   reader=lambda *_: (10000, next(samples)),
                                   sleeper=lambda _: None)
        self.assertAlmostEqual(result, 1.3)

    def test_gradual_drift_is_not_falsely_hidden(self):
        samples = iter([1.1, 1.2, 1.3, 1.4, 1.5])
        result = median_ph_voltage(2, 0x48, count=5, spacing_s=1.0,
                                   reader=lambda *_: (10000, next(samples)),
                                   sleeper=lambda _: None)
        self.assertAlmostEqual(result, 1.3)

    def test_invalid_and_saturated_voltage_are_rejected(self):
        for raw, volts in ((32767, 4.095), (-32768, 0.3), (100, 0),
                           (100, 4.096), (100, float("nan")),
                           (100, float("inf"))):
            with self.subTest(raw=raw, volts=volts):
                with self.assertRaises(ValueError):
                    median_ph_voltage(2, 0x48, count=1, reader=lambda *_: (raw, volts),
                                      sleeper=lambda _: None)

    def test_invalid_configuration_rejected(self):
        for count in (0, -1, 31, 5.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                median_ph_voltage(2, 0x48, count=count, reader=lambda *_: (100, 1.0),
                                  sleeper=lambda _: None)
        for spacing in (-1, math.inf, math.nan, 6):
            with self.subTest(spacing=spacing), self.assertRaises(ValueError):
                median_ph_voltage(2, 0x48, spacing_s=spacing,
                                  reader=lambda *_: (100, 1.0),
                                  sleeper=lambda _: None)

    def test_dashboard_and_charts_use_stored_collector_reading(self):
        collector = (ROOT / "tds_collector.py").read_text(encoding="utf8")
        app = (ROOT / "app.py").read_text(encoding="utf8")
        live = (ROOT / "static" / "sensor-calibration.js").read_text(encoding="utf8")
        html = (ROOT / "templates" / "options.html").read_text(encoding="utf8")
        self.assertIn("ph_voltage = median_ph_voltage(", collector)
        self.assertIn("save_sample(ppm, water_temp, ph)", collector)
        self.assertIn("FROM data ORDER BY Datetime DESC, Id DESC LIMIT 2", app)
        self.assertIn("ROUND(AVG(ph), 3) AS ph", app)
        self.assertIn("livePhWindow.push(ph);", live)
        self.assertIn("livePhWindow.length > 5", live)
        self.assertIn("median(livePhWindow)", live)
        self.assertIn("Median of up to 5 recent readings", html)
        self.assertIn("Number(value).toFixed(5) + ' V'", live)


if __name__ == "__main__":
    unittest.main()
