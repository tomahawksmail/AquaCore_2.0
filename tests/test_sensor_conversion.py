"""Sensor conversion sanity checks without I2C hardware or database."""
import unittest

from sensor_conversion import calibrated_ph, ntc_celsius


class SensorConversionTests(unittest.TestCase):
    def test_ntc_25c_midpoint(self):
        self.assertAlmostEqual(ntc_celsius(2.5), 25.0, places=3)

    def test_ntc_warm_cool(self):
        self.assertGreater(ntc_celsius(2.1), 25.0)
        self.assertLess(ntc_celsius(2.9), 25.0)

    def test_ntc_rejects_invalid(self):
        for voltage in (0, 5.0, 5.1, float("nan")):
            with self.subTest(voltage=voltage), self.assertRaises(ValueError):
                ntc_celsius(voltage)

    def test_ph_two_real_points(self):
        self.assertAlmostEqual(calibrated_ph(2.50, 2.50, 2.95), 7.0)
        self.assertAlmostEqual(calibrated_ph(2.95, 2.50, 2.95), 4.0)
        self.assertAlmostEqual(calibrated_ph(2.65, 2.50, 2.95), 6.0)

    def test_ph_rejects_bad_calibration(self):
        with self.assertRaises(ValueError):
            calibrated_ph(3.18, 3.18, 3.18)


if __name__ == "__main__":
    unittest.main()
