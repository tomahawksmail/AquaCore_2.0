"""Ensure an unavailable ADS1115 channel does not hide other live voltages."""
import unittest
from unittest.mock import patch

from flask import Flask
import pymysql

import sensor_calibration_api as calibration


class FakeDB:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self

    def execute(self, _query):
        pass

    def fetchone(self):
        return {"temp_offset_c": 0, "tds_factor": 0.2626,
                "temp_factor": 1.0, "ph_factor": 1.0,
                "ph7_voltage": None, "ph4_voltage": None}


class IndependentVoltageTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_a0_still_readable_when_a1_fails(self):
        def read(bus, address, channel):
            self.assertEqual((bus, address), (2, 0x48))
            if channel == 1:
                raise OSError("A1 thermistor disconnected")
            return (8000, 1.09331) if channel == 0 else (6000, 0.8125)

        with self.app.test_request_context("/api/sensors/calibration/live"), \
             patch.object(calibration, "_admin"), \
             patch.object(calibration, "_db", return_value=FakeDB()), \
             patch.object(calibration, "adc_read", side_effect=read), \
             patch.object(calibration.time, "sleep"):
            result = calibration.live().get_json()

        self.assertAlmostEqual(result["volts"]["a0"], 1.09331, places=5)
        self.assertIsNone(result["volts"]["a1"])
        self.assertAlmostEqual(result["volts"]["a3"], 0.8125)
        self.assertIn("A1 thermistor disconnected", result["voltage_errors"]["a1"])
        self.assertNotIn("a0", result["voltage_errors"])

    def test_selected_a3_channel_does_not_read_a0_or_a1(self):
        visited = []

        def read(_bus, _address, channel):
            visited.append(channel)
            return (6000, 0.8125)

        with self.app.test_request_context(
                "/api/sensors/calibration/live?channel=a3"), \
             patch.object(calibration, "_admin"), \
             patch.object(calibration, "_db", return_value=FakeDB()), \
             patch.object(calibration, "adc_read", side_effect=read), \
             patch.object(calibration.time, "sleep"):
            result = calibration.live().get_json()
        self.assertEqual(visited, [3, 3])
        self.assertEqual(result["requested_channel"], "a3")
        self.assertAlmostEqual(result["volts"]["a3"], 0.8125)
        self.assertIsNone(result["volts"]["a0"])
        self.assertIsNone(result["volts"]["a1"])
        self.assertEqual(result["voltage_errors"], {})

    def test_raw_a0_reading_survives_calibration_database_error(self):
        with self.app.test_request_context("/api/sensors/calibration/live"), \
             patch.object(calibration, "_admin"), \
             patch.object(calibration, "_db", side_effect=pymysql.MySQLError("missing calibration columns")), \
             patch.object(calibration, "adc_read", return_value=(8000, 1.09331)), \
             patch.object(calibration.time, "sleep"):
            result = calibration.live().get_json()
        self.assertAlmostEqual(result["volts"]["a0"], 1.09331)
        self.assertIn("missing calibration columns", result["calibration_db_error"])
        self.assertIsNone(result["ph_raw"])


if __name__ == "__main__":
    unittest.main()
