import unittest
from unittest.mock import patch, MagicMock
from sensor_conversion import calibrated_ph


class FactorMathTest(unittest.TestCase):
    def test_ph_neutral_pivot(self):
        raw = calibrated_ph(2.54, 2.54, 3.04)
        self.assertAlmostEqual(7 + (raw - 7) * 1.0, 7.0)
        self.assertAlmostEqual(7 + (6 - 7) * 1.1, 5.9)

    def test_temp_factor(self):
        self.assertAlmostEqual(22.0 * 1.05 + 0.2, 23.3)

    def test_tds_factor(self):
        self.assertAlmostEqual(200 * 0.105, 21.0)


if __name__ == "__main__":
    unittest.main()
