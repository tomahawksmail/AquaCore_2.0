"""NTC configuration is in MariaDB; 3.3 V divider defaults OFF until installed."""
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

import sensor_calibration_api as calibration
from sensor_conversion import ntc_celsius

ROOT = Path(__file__).resolve().parents[1]


class FakeDB:
    def __init__(self, record):
        self.record = record
        self.queries = []
        self.rowcount = 1
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self

    def execute(self, query, params=None):
        self.queries.append((query, params))
        self.rowcount = 1

    def fetchone(self):
        return self.record

    def commit(self):
        self.committed = True


class NTCDBSettingsTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "ntc-test-session"

    def test_nominal_33v_divider_gives_25c_at_1p65v(self):
        self.assertAlmostEqual(ntc_celsius(1.65), 25.0, places=3)
        self.assertAlmostEqual(ntc_celsius(1.65, supply_v=3.3), 25.0, places=3)

    def test_default_row_is_off_and_3p3_volts(self):
        self.assertEqual(calibration._ntc_settings({}), (False, 3.3))
        self.assertEqual(calibration._ntc_settings(
            {"ntc_enabled": 0, "ntc_supply_v": 3.3}), (False, 3.3))
        migration = (ROOT / "deploy/sql/ntc_settings_migration.sql").read_text()
        fresh = (ROOT / "deploy/sql/sensor_calibration.sql").read_text()
        for sql in (migration, fresh):
            self.assertIn("ntc_enabled TINYINT(1) NOT NULL DEFAULT 0", sql)
            self.assertIn("ntc_supply_v DOUBLE NOT NULL DEFAULT 3.3", sql)

    def test_upgrade_from_disabled_5v_default_preserves_uninstalled_state(self):
        upgrade = (ROOT / "deploy/sql/ntc_33v_divider_migration.sql").read_text()
        self.assertIn("MODIFY COLUMN ntc_supply_v DOUBLE NOT NULL DEFAULT 3.3", upgrade)
        self.assertIn("SET ntc_supply_v = 3.3", upgrade)
        self.assertIn("WHERE ntc_enabled = 0", upgrade)
        self.assertIn("ABS(ntc_supply_v - 5.0)", upgrade)
        self.assertNotIn("UPDATE sensor_calibration SET ntc_enabled = 1", upgrade)

    def test_disabled_db_ignores_old_env_and_does_not_sample(self):
        record = {"ntc_enabled": 0, "ntc_supply_v": 3.3}
        db = FakeDB(record)
        with self.app.test_request_context(
            "/api/sensors/calibration/sample", method="POST",
            json={"kind":"temp"}), \
             patch.object(calibration, "_admin"), \
             patch.dict(calibration.os.environ,
                        {"NTC_ENABLED":"1", "NTC_SUPPLY_V":"5.0"}), \
             patch.object(calibration, "_db", return_value=db), \
             patch.object(calibration, "_sample",
                          side_effect=AssertionError("A1 must stay off")):
            response, status = calibration.sample()
        self.assertEqual(status, 409)
        self.assertIn("enable a1", response.get_json()["error"].lower())

    def test_a0_still_reads_when_ntc_disabled(self):
        channels = []
        def adc(_bus, _address, channel):
            channels.append(channel)
            return 9000, 1.2
        with self.app.test_request_context("/api/sensors/calibration/live?channel=a0"), \
             patch.object(calibration, "_admin"), \
             patch.object(calibration, "_db", return_value=FakeDB({
                 "ntc_enabled": 0, "ntc_supply_v": 3.3})), \
             patch.object(calibration, "adc_read", side_effect=adc), \
             patch.object(calibration.time, "sleep"):
            body = calibration.live().get_json()
        self.assertEqual(channels, [0, 0])
        self.assertFalse(body["ntc_enabled"])
        self.assertFalse(body["ph_temperature_compensated"])
        self.assertEqual(body["volts"]["a0"], 1.2)

    def test_ntc_calibrated_temperature_requires_db_enabled(self):
        record = {"ntc_enabled":1, "ntc_supply_v":3.3,
                  "temp_updated_at":"saved", "temp_factor":1.0,
                  "temp_offset_c":0}
        self.assertAlmostEqual(calibration._calibrated_ntc_temperature(
            1.65, record), 25.0, places=3)
        record["ntc_enabled"] = 0
        with self.assertRaises(ValueError):
            calibration._calibrated_ntc_temperature(1.65, record)

    def test_admin_can_save_off_3p3v_to_db(self):
        db = FakeDB({"id":1})
        with self.app.test_request_context(
            "/api/sensors/calibration/ntc-settings", method="POST",
            json={"enabled":False, "supply_v":3.3}), \
             patch.object(calibration, "_admin"), \
             patch.object(calibration, "_db", return_value=db):
            result = calibration.save_ntc_settings().get_json()
        self.assertTrue(db.committed)
        self.assertEqual(result["ntc_enabled"], False)
        self.assertEqual(result["ntc_supply_v"], 3.3)
        update, params = db.queries[0]
        self.assertIn("temp_updated_at=CASE WHEN", update)
        self.assertIn("ntc_enabled=%s,ntc_supply_v=%s", update)
        self.assertEqual(params[-2:], (0, 3.3))

    def test_reject_invalid_config(self):
        for payload in (
            {"enabled":1, "supply_v":3.3},
            {"enabled":True, "supply_v":5.0},
            {"enabled":True, "supply_v":float("nan")},
            {"enabled":False},
        ):
            with self.subTest(payload=payload), self.app.test_request_context(
                "/api/sensors/calibration/ntc-settings", method="POST",
                json=payload), patch.object(calibration, "_admin"):
                response, status = calibration.save_ntc_settings()
                self.assertEqual(status, 400)

    def test_collector_reads_ntc_db_settings_not_environment(self):
        code = (ROOT / "tds_collector.py").read_text()
        self.assertIn("ntc_enabled = bool(int(calibration.get('ntc_enabled') or 0))", code)
        self.assertIn("ntc_supply_v", code)
        self.assertNotIn("os.getenv(\"NTC_ENABLED\"", code)
        self.assertNotIn("os.getenv(\"NTC_SUPPLY_V\"", code)
        self.assertIn("calibration.get('temp_updated_at') is not None", code)

    def test_ui_has_ntc_configuration_controls(self):
        html = (ROOT / "templates/options.html").read_text()
        js = (ROOT / "static/sensor-calibration.js").read_text()
        for control in ("sensor-ntc-enabled", "sensor-ntc-supply",
                        "sensor-save-ntc-settings", "sensor-ntc-config-status"):
            self.assertIn(f'id="{control}"', html)
        self.assertIn("api('/ntc-settings', {enabled, supply_v})", js)
        self.assertIn("settings.ntc_enabled", js)


if __name__ == "__main__":
    unittest.main()
