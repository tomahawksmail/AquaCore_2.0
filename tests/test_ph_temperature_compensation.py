"""Automatic temperature integration for pH calibration and Nernst slope."""
import unittest
from unittest.mock import patch

from flask import Flask

import sensor_calibration_api as api
from sensor_conversion import (buffer_reference_ph, calibrated_ph_three_points,
                               temperature_compensated_ph_three_points)


class FakeCalibrationDB:
    def __init__(self, settings):
        self.settings = settings

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self

    def execute(self, _query):
        return None

    def fetchone(self):
        return self.settings


class PhTemperatureTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"

    def test_nist_buffer_references_change_with_temperature(self):
        self.assertAlmostEqual(buffer_reference_ph("ph686", 20), 6.88)
        self.assertAlmostEqual(buffer_reference_ph("ph918", 20), 9.22)
        self.assertAlmostEqual(buffer_reference_ph("ph401", 25), 4.01)

    def test_atc_matches_calibrated_curve_when_same_temp(self):
        values = (1.8, 2.5, 3.0, 4.01, 6.86, 9.18)
        for volts in (1.6, 1.8, 2.5, 2.8, 3.0, 3.2):
            with self.subTest(volts=volts):
                base = calibrated_ph_three_points(volts, *values)
                atc = temperature_compensated_ph_three_points(
                    volts, *values, 25, 25, 25, 25)
                self.assertAlmostEqual(atc, base, places=10)

    def test_atc_responds_to_temperature_around_neutral_anchor(self):
        values = (1.8, 2.5, 3.0, 4.01, 6.86, 9.18)
        colder = temperature_compensated_ph_three_points(
            1.8, *values, 25, 25, 25, 20)
        warmer = temperature_compensated_ph_three_points(
            1.8, *values, 25, 25, 25, 30)
        self.assertLess(colder, 4.01)
        self.assertGreater(warmer, 4.01)
        self.assertAlmostEqual(temperature_compensated_ph_three_points(
            2.5, *values, 25, 25, 25, 20), 6.86)

    def test_reject_invalid_temperature(self):
        values = (1.8, 2.5, 3.0, 4.01, 6.86, 9.18)
        for t in (-1, 51, float("nan")):
            with self.subTest(temp=t), self.assertRaises(ValueError):
                temperature_compensated_ph_three_points(
                    2.0, *values, 25, 25, 25, t)

    def test_buffer_capture_reads_calibrated_a1_only_when_requested(self):
        called = []
        def sample(channel):
            called.append(channel)
            return 2.5 if channel == 1 else 1.8
        with self.app.test_request_context(
            "/api/sensors/calibration/sample", method="POST",
            json={"kind": "ph686", "temperature_source": "ntc"}), \
             patch.object(api, "_admin"), \
                          patch.object(api, "_db", return_value=FakeCalibrationDB({
                 "ntc_enabled": 1, "ntc_supply_v": 5.0,
                 "temp_updated_at": "saved", "temp_factor": 1.0,
                 "temp_offset_c": 0.0})), \
             patch.object(api, "_sample", side_effect=sample):
            response = api.sample().get_json()
            self.assertEqual(response["temperature_source"], "ntc")
            self.assertAlmostEqual(response["temperature_c"], 25.0, places=3)
            self.assertAlmostEqual(response["reference_ph"], 6.86)
            self.assertEqual(called, [1, 0])

    def test_uncalibrated_ntc_cannot_be_used_as_buffer_temperature(self):
        with self.app.test_request_context(
            "/api/sensors/calibration/sample", method="POST",
            json={"kind": "ph401", "temperature_source": "ntc"}), \
             patch.object(api, "_admin"), \
                          patch.object(api, "_db", return_value=FakeCalibrationDB({
                 "ntc_enabled": 1, "ntc_supply_v": 5.0,
                 "temp_updated_at": None})), \
             patch.object(api, "_sample", return_value=2.5):
            result, status = api.sample()
            self.assertEqual(status, 409)
            self.assertIn("Calibrate the A1", result.get_json()["error"])

    def test_manual_buffer_temperature_still_available(self):
        called = []
        with self.app.test_request_context(
            "/api/sensors/calibration/sample", method="POST",
            json={"kind": "ph918", "temperature_source": "manual",
                  "temperature_c": 20.0}), \
             patch.object(api, "_admin"), \
             patch.object(api, "_sample",
                          side_effect=lambda ch: (called.append(ch), 2.9)[1]):
            result = api.sample().get_json()
            self.assertEqual(called, [0])
            self.assertEqual(result["temperature_source"], "manual")
            self.assertAlmostEqual(result["reference_ph"], 9.22)

    def test_live_a0_uses_a1_if_ntc_calibrated(self):
        config = {
            "ntc_enabled": 1, "ntc_supply_v": 5.0,
            "temp_updated_at": "saved", "temp_factor": 1, "temp_offset_c": 0,
            "ph401_voltage": 1.8, "ph686_voltage": 2.5, "ph918_voltage": 3,
            "ph401_reference": 4.01, "ph686_reference": 6.86,
            "ph918_reference": 9.18, "ph401_temp_c": 25,
            "ph686_temp_c": 25, "ph918_temp_c": 25,
        }
        calls = []
        def adc_read(_bus, _addr, channel):
            calls.append(channel)
            return (10000, 2.5 if channel == 1 else 1.8)
        with self.app.test_request_context(
            "/api/sensors/calibration/live?channel=a0"), \
             patch.object(api, "_admin"), \
                          patch.object(api, "_db", return_value=FakeCalibrationDB(config)), \
             patch.object(api, "adc_read", side_effect=adc_read), \
             patch.object(api.time, "sleep"):
            result = api.live().get_json()
        self.assertEqual(calls, [0, 0, 1, 1])
        self.assertTrue(result["ph_temperature_compensated"])
        self.assertAlmostEqual(result["ph_temperature_c"], 25, places=3)
        self.assertAlmostEqual(result["ph_raw"], 4.01, places=3)

    def test_a1_failure_does_not_hide_a0_ph(self):
        config = {
            "ntc_enabled": 1, "ntc_supply_v": 5.0, "temp_updated_at": "saved",
            "ph401_voltage": 1.8, "ph686_voltage": 2.5, "ph918_voltage": 3,
            "ph401_reference": 4.01, "ph686_reference": 6.86,
            "ph918_reference": 9.18, "ph401_temp_c": 25,
            "ph686_temp_c": 25, "ph918_temp_c": 25,
        }
        def read(_bus, _addr, channel):
            if channel == 1:
                raise OSError("A1 disconnected")
            return 10000, 1.8
        with self.app.test_request_context(
            "/api/sensors/calibration/live?channel=a0"), \
             patch.object(api, "_admin"), \
                          patch.object(api, "_db", return_value=FakeCalibrationDB(config)), \
             patch.object(api, "adc_read", side_effect=read), \
             patch.object(api.time, "sleep"):
            result = api.live().get_json()
        self.assertAlmostEqual(result["ph_raw"], 4.01)
        self.assertFalse(result["ph_temperature_compensated"])
        self.assertIn("a1", result["voltage_errors"])


if __name__ == "__main__":
    unittest.main()
