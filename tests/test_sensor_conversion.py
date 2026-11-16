"""Two-buffer pH, temperature and missing-sensor regression tests."""
import unittest
from sensor_conversion import (ntc_celsius, calibrated_ph_from_points,
                               temperature_compensated_ph_two_points, buffer_reference_ph)

class ConversionTests(unittest.TestCase):
    def test_ntc_midpoint(self):
        self.assertAlmostEqual(ntc_celsius(1.65),25.0,places=3)
        self.assertGreater(ntc_celsius(1.3),25)
        self.assertLess(ntc_celsius(2.0),25)

    def test_ntc_invalid(self):
        for v in (0,3.3,4.095,float("nan")):
            with self.subTest(v=v),self.assertRaises(ValueError):
                ntc_celsius(v)

    def test_two_reference_points_and_2p4_voltage(self):
        self.assertAlmostEqual(calibrated_ph_from_points(2.54,6.86,2.54,4.01,3.04),6.86)
        self.assertAlmostEqual(calibrated_ph_from_points(3.04,6.86,2.54,4.01,3.04),4.01)
        self.assertAlmostEqual(temperature_compensated_ph_two_points(2.4,2.54,3.04,25,25,25),7.658)

    def test_compensation_uses_ntc_kelvin_slope(self):
        cool=temperature_compensated_ph_two_points(3.04,2.54,3.04,25,25,20)
        warm=temperature_compensated_ph_two_points(3.04,2.54,3.04,25,25,30)
        self.assertLess(cool,4.01)
        self.assertGreater(warm,4.01)
        self.assertAlmostEqual(temperature_compensated_ph_two_points(2.54,2.54,3.04,25,25,20),6.86)

    def test_buffer_reference_temperature(self):
        self.assertAlmostEqual(buffer_reference_ph("ph686",20),6.88)
        self.assertAlmostEqual(buffer_reference_ph("ph401",25),4.01)
        for kind in ("ph918","ph700","ph_unknown"):
            with self.assertRaises(ValueError):
                buffer_reference_ph(kind,25)

    def test_invalid_calibration_is_not_clipped_to_artificial_ph(self):
        with self.assertRaises(ValueError):
            calibrated_ph_from_points(2.5,6.86,2.54,4.01,2.54)
        for t in (-1,51,float("nan")):
            with self.assertRaises(ValueError):
                temperature_compensated_ph_two_points(2.54,2.54,3.04,25,25,t)

if __name__=="__main__":
    unittest.main()
