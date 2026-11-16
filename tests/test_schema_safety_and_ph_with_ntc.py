"""Schema and sensor fail-safe regressions (no hardware or live MariaDB needed)."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from flask import Flask

import app
import sensor_calibration_api as api
import tds_collector

ROOT = Path(__file__).resolve().parents[1]
REMOVED_METRICS = (
    "scpufreq_min", "scpufreq_max", "cpu_thermal_high", "cpu_thermal_crit",
    "gpu_thermal_cur", "gpu_thermal_high", "gpu_thermal_crit", "ve_thermal_cur",
)
CALIBRATION_FIELDS = (
    "ntc_enabled", "ntc_supply_v", "temp_offset_c", "temp_updated_at",
    "tds_factor", "ph_factor", "temp_factor", "ph7_voltage", "ph4_voltage",
    "ph401_voltage", "ph686_voltage", "ph918_voltage",
    "ph401_reference", "ph686_reference", "ph918_reference",
    "ph401_temp_c", "ph686_temp_c", "ph918_temp_c",
    "ph_provisional_enabled", "ph_provisional_neutral_v",
    "ph_provisional_started_at", "ph_updated_at",
)


class FakeDB:
    def __init__(self, result):
        self.result = result
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def cursor(self): return self
    def execute(self, sql, params=None): return None
    def fetchone(self): return self.result


class DatabaseSchemaSafetyTests(unittest.TestCase):
    def test_bootstraps_include_current_sensor_calibration(self):
        for name in ("aquacore_empty_bootstrap.sql", "clean_install.sql"):
            with self.subTest(name=name):
                text = (ROOT / "deploy" / "sql" / name).read_text()
                section = text.split("CREATE TABLE IF NOT EXISTS sensor_calibration (", 1)[1].split(") ENGINE", 1)[0]
                for field in CALIBRATION_FIELDS:
                    self.assertIn(field + " ", section, (name, field))

    def test_unused_metrics_not_created_in_new_install(self):
        for name in ("aquacore_empty_bootstrap.sql", "clean_install.sql"):
            with self.subTest(name=name):
                sql = (ROOT / "deploy" / "sql" / name).read_text()
                section = sql.split("CREATE TABLE IF NOT EXISTS `psutil` (", 1)[1].split(") ENGINE", 1)[0]
                for field in REMOVED_METRICS:
                    self.assertNotIn("`" + field + "`", section)

    def test_scheduler_never_inserts_fake_sensor_or_system_samples(self):
        source = (ROOT / "scheduler.py").read_text()
        self.assertNotIn("insert_missing_sensor_zeros()", source)
        self.assertNotIn("insert_missing_system_zeros()", source)
        self.assertNotIn("INSERT INTO `data`", source)
        self.assertNotIn("INSERT INTO `psutil`", source)

    def test_offline_readings_mask_live_data_without_modifying_history(self):
        now = datetime(2026, 11, 16, 12, 0)
        old = {"Datetime": now-timedelta(minutes=5), "temp": 24.1, "ph": 9.87, "tds": 201}
        masked, stale = app.mask_stale_sensor_reading(old, current_time=now)
        self.assertTrue(stale)
        self.assertEqual((masked["temp"], masked["ph"], masked["tds"]), (None, None, None))
        self.assertEqual(old["ph"], 9.87)
        fresh, stale = app.mask_stale_sensor_reading(
            dict(old, Datetime=now-timedelta(seconds=25)), current_time=now)
        self.assertFalse(stale)
        self.assertEqual(fresh["ph"], 9.87)

    def test_cleanup_is_opt_in_and_whitelisted(self):
        sql = (ROOT / "deploy/sql/cleanup_unused_db_fields.sql").read_text()
        self.assertIn("Column not on audited allowlist", sql)
        self.assertIn("WHERE `temp` <=> 0 AND `ph` <=> 0 AND `tds` <=> 0", sql)
        self.assertNotIn("DROP TABLE", sql)
        for field in REMOVED_METRICS:
            self.assertIn(field, sql)


class ProvisionalPhAndTemperatureTests(unittest.TestCase):
    def test_temperature_enabled_does_not_override_operator_neutral_anchor(self):
        config = {
            "ph_provisional_enabled": 1, "ph_provisional_neutral_v": 2.4,
            "ph401_voltage": 3.3875625, "ph686_voltage": 3.0879375,
            "ph918_voltage": 2.82625, "ph401_reference": 4.004,
            "ph686_reference": 6.872, "ph918_reference": 9.204,
            "ph401_temp_c": 25.0, "ph686_temp_c": 25.0, "ph918_temp_c": 25.0,
            "ntc_enabled": 1, "ntc_supply_v": 3.3,
            "temp_factor": 1.0, "temp_offset_c": 0.0,
            "temp_updated_at": datetime(2026, 11, 16),
        }
        test_app = Flask(__name__)
        test_app.secret_key = "test-only"
        def read_channel(bus, address, channel):
            return (12000, 2.4 if channel == 0 else 1.65)
        with test_app.test_request_context("/api/sensors/calibration/live?channel=a0"), \
             patch.object(api, "_admin"), \
             patch.object(api, "_db", return_value=FakeDB(config)), \
             patch.object(api, "adc_read", side_effect=read_channel), \
             patch.object(api.time, "sleep"):
            result = api.live().get_json()
        self.assertAlmostEqual(result["ph_raw"], 7.0)
        self.assertTrue(result["ph_provisional"])
        self.assertFalse(result["ph_temperature_compensated"])
        self.assertAlmostEqual(result["ph_temperature_c"], 25.0, places=3)

    def test_collector_logs_correctly_and_saves_neutral_with_ntc_on(self):
        calibration = {
            "ph_provisional_enabled": 1, "ph_provisional_neutral_v": 2.4,
            "ntc_enabled": 1, "ntc_supply_v": 3.3,
            "temp_updated_at": datetime(2026, 11, 16),
            "temp_factor": 1.0, "temp_offset_c": 0.0,
            "tds_factor": 0.2626, "ph_factor": 1.0,
            "ph401_voltage": 3.3875625, "ph686_voltage": 3.0879375,
            "ph918_voltage": 2.82625, "ph401_reference": 4.004,
            "ph686_reference": 6.872, "ph918_reference": 9.204,
            "ph401_temp_c": 25.0, "ph686_temp_c": 25.0, "ph918_temp_c": 25.0,
        }
        msgs = []
        def checked_log(format_string, *args):
            msgs.append(format_string % args)  # Catches %f/string argument errors.
        def read_channel(bus, address, channel):
            return (10000, 1.65 if channel == 1 else 1.0)
        with patch.object(sys, "argv", ["tds_collector.py", "--once", "--samples", "1"]), \
             patch.object(tds_collector, "calibration_settings", return_value=calibration), \
             patch.object(tds_collector, "adc_read", side_effect=read_channel), \
             patch.object(tds_collector, "median_ph_voltage", return_value=2.4), \
             patch.object(tds_collector, "save_sample") as saved, \
             patch.object(tds_collector.LOG, "info", side_effect=checked_log), \
             patch.object(tds_collector.time, "sleep"):
            self.assertEqual(tds_collector.main(), 0)
        ppm, temp, ph = saved.call_args.args
        self.assertGreater(ppm, 0)
        self.assertAlmostEqual(temp, 25.0, places=3)
        self.assertAlmostEqual(ph, 7.0, places=3)
        self.assertIn("PROVISIONAL_UNVERIFIED", msgs[-1])
        self.assertIn("A0=2.40000 V", msgs[-1])


if __name__ == "__main__":
    unittest.main()
