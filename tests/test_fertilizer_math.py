"""Offline regression tests for fertilizer pump volume conversion."""
import unittest
from fertilizer_math import calibrated_seconds, calibrate_rate


class FertilizerVolumeTests(unittest.TestCase):
    def test_calibration(self):
        self.assertEqual(str(calibrate_rate("20")), "2.00000")
        self.assertIsNone(calibrate_rate("0"))
        self.assertIsNone(calibrate_rate("nan"))

    def test_dose(self):
        self.assertEqual(calibrated_seconds("6", "2"), 3.0)
        self.assertEqual(calibrated_seconds("1", "2"), 0.5)
        self.assertIsNone(calibrated_seconds("5", None))
        self.assertIsNone(calibrated_seconds("0", "2"))
        self.assertIsNone(calibrated_seconds("100", "0.1"))
        self.assertIsNone(calibrated_seconds("nan", "2"))


if __name__ == "__main__":
    unittest.main()
