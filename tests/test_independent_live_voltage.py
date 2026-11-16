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

    def test_a3_reads_a1_for_temperature_corrected_preview(self):
        visited = []
        def adc(_bus, _address, channel):
            visited.append(channel)
            return (6000, 1.65 if channel == 1 else 0.8125)
        with self.app.test_request_context("/api/sensors/calibration/live?channel=a3"), \
             patch.object(calibration, "_admin"), \
             patch.object(calibration, "_db", return_value=FakeDB()), \
             patch.object(calibration, "adc_read", side_effect=adc), \
             patch.object(calibration.time, "sleep"):
            result = calibration.live().get_json()
        # Default NTC is disabled in FakeDB, so only A3 is sampled.
        self.assertEqual(visited, [3, 3])
        self.assertAlmostEqual(result["volts"]["a3"], 0.8125)
        self.assertIsNone(result["ph_temperature_c"])

    def test_enabled_a1_is_sampled_for_a3(self):
        visited = []
        def adc(_bus, _address, channel):
            visited.append(channel)
            return (6000, 1.65 if channel == 1 else 0.8125)
        db = FakeDB()
        db.fetchone = lambda: {"ntc_enabled":1, "ntc_supply_v":3.3,
                               "temp_updated_at":"saved", "temp_factor":1.0,
                               "temp_offset_c":0.0}
        with self.app.test_request_context("/api/sensors/calibration/live?channel=a3"), \
             patch.object(calibration, "_admin"), \
             patch.object(calibration, "_db", return_value=db), \
             patch.object(calibration, "adc_read", side_effect=adc), \
             patch.object(calibration.time, "sleep"):
            result = calibration.live().get_json()
        self.assertEqual(visited, [1, 1, 3, 3])
        self.assertAlmostEqual(result["ph_temperature_c"], 25, places=3)
        self.assertAlmostEqual(result["volts"]["a3"], 0.8125)

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
