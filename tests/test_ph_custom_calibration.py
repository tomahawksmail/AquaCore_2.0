import unittest

from sensor_conversion import calibrated_ph_from_points


class TestCustomPHCalibration(unittest.TestCase):
    def test_buffer_points(self):
        self.assertAlmostEqual(calibrated_ph_from_points(2.54, 6.86, 2.54, 4.01, 3.04), 6.86)
        self.assertAlmostEqual(calibrated_ph_from_points(3.04, 6.86, 2.54, 4.01, 3.04), 4.01)

    def test_drinking_water(self):
        self.assertAlmostEqual(calibrated_ph_from_points(2.089, 6.86, 2.54, 4.01, 3.04), 9.4307)

    def test_bad_calibration(self):
        with self.assertRaises(ValueError):
            calibrated_ph_from_points(2.54, 6.86, 2.54, 4.01, 2.54)


if __name__ == "__main__":
    unittest.main()
