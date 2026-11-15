"""Temporary user-requested 2.40V ~= pH7 display is labeled UNVERIFIED."""
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

from flask import Flask

import sensor_calibration_api as api
from sensor_conversion import provisional_ph_neutral_anchor
from app import mask_pre_provisional_ph

ROOT = Path(__file__).resolve().parents[1]
VOLTS = (3.3875625, 3.0879375)
REFERENCES = (4.004, 6.872)


class FakeDb:
    def __init__(self, row):
        self.row=row
        self.queries=[]
        self.committed=False
        self.rowcount=1

    def __enter__(self): return self
    def __exit__(self,*args): return False
    def cursor(self): return self
    def execute(self,sql,params=None): self.queries.append((sql,params))
    def fetchone(self): return self.row
    def commit(self): self.committed=True


class ProvisionalPhTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__)
        self.app.secret_key="test-provisional"

    def test_requested_neutral_anchor_is_exactly_pH7(self):
        self.assertAlmostEqual(provisional_ph_neutral_anchor(
            2.40, 2.40, *VOLTS, *REFERENCES), 7.0)

    def test_current_244638_volts_is_near_seven(self):
        value=provisional_ph_neutral_anchor(
            2.44638,2.40,*VOLTS,*REFERENCES)
        self.assertGreater(value,6.4)
        self.assertLess(value,6.8)

    def test_reject_invalid_voltage_and_slope(self):
        for volts in (0,4.096,float("nan")):
            with self.subTest(volts=volts), self.assertRaises(ValueError):
                provisional_ph_neutral_anchor(volts,2.4,*VOLTS,*REFERENCES)
        with self.assertRaises(ValueError):
            provisional_ph_neutral_anchor(2.4,2.4,2.50,2.49,*REFERENCES)

    def test_enabled_live_preview_uses_provisional_not_saved_curve(self):
        settings={"ph_provisional_enabled":1,"ph_provisional_neutral_v":2.4,
                  "ph401_voltage":VOLTS[0],"ph686_voltage":VOLTS[1],
                  "ph401_reference":REFERENCES[0],"ph686_reference":REFERENCES[1],
                  "ph918_voltage":2.82625,"ph918_reference":9.204,
                  "ntc_enabled":0,"ntc_supply_v":3.3}
        with self.app.test_request_context("/api/sensors/calibration/live?channel=a0"), \
             patch.object(api,"_admin"), \
             patch.object(api,"_db",return_value=FakeDb(settings)), \
             patch.object(api,"adc_read",return_value=(12345,2.44638)), \
             patch.object(api.time,"sleep"):
            result=api.live().get_json()
        self.assertTrue(result["ph_provisional"])
        self.assertGreater(result["ph_raw"],6.4)
        self.assertLess(result["ph_raw"],6.8)
        self.assertFalse(result["ph_temperature_compensated"])

    def test_provisional_mode_can_be_disabled_without_deleting_buffers(self):
        db=FakeDb({})
        with self.app.test_request_context(
            "/api/sensors/calibration/ph-provisional",method="POST",
            json={"enabled":False,"neutral_voltage":2.40}), \
             patch.object(api,"_admin"), \
             patch.object(api,"_db",return_value=db):
            result=api.save_ph_provisional().get_json()
        self.assertTrue(result["ok"])
        self.assertTrue(db.committed)
        sql,_=db.queries[-1]
        self.assertNotIn("ph401_voltage=",sql)
        self.assertIn("ph_provisional_enabled=",sql)

    def test_reject_enable_without_saved_slope(self):
        db=FakeDb({"ph401_voltage":None,"ph686_voltage":None,
                   "ph401_reference":None,"ph686_reference":None})
        with self.app.test_request_context(
            "/api/sensors/calibration/ph-provisional",method="POST",
            json={"enabled":True,"neutral_voltage":2.4}), \
             patch.object(api,"_admin"), \
             patch.object(api,"_db",return_value=db):
            response,status=api.save_ph_provisional()
        self.assertEqual(status,400)
        self.assertFalse(db.committed)

    def test_old_pH_history_hidden_without_deleting_values(self):
        now=datetime(2026,11,14,12,0,0)
        rows=[{"Datetime":now-timedelta(minutes=2),"ph":13.7},
              {"Datetime":now+timedelta(minutes=2),"ph":6.6}]
        mask_pre_provisional_ph(rows,True,now)
        self.assertIsNone(rows[0]["ph"])
        self.assertEqual(rows[1]["ph"],6.6)

    def test_migration_opt_in_and_fresh_buffers_reset_it(self):
        mig=(ROOT/"deploy/sql/ph_provisional_neutral_migration.sql").read_text()
        api_code=(ROOT/"sensor_calibration_api.py").read_text()
        collector=(ROOT/"tds_collector.py").read_text()
        dashboard=(ROOT/"templates/dashboard.html").read_text()
        self.assertIn("ph_provisional_enabled=1",mig)
        self.assertIn("ph_provisional_started_at=NOW()",mig)
        self.assertIn("ph_provisional_enabled=0",api_code)
        self.assertIn("provisional_ph_neutral_anchor(",collector)
        self.assertIn("unverified estimate",dashboard)

    def test_ui_explicitly_labels_provisional_and_has_disable_control(self):
        html=(ROOT/"templates/options.html").read_text()
        js=(ROOT/"static/sensor-calibration.js").read_text()
        for ident in ("sensor-ph-provisional-enabled",
                      "sensor-ph-provisional-neutral",
                      "sensor-save-ph-provisional"):
            self.assertIn('id="'+ident+'"',html)
        self.assertIn("api('/ph-provisional', {enabled, neutral_voltage})",js)
        self.assertIn("UNVERIFIED",html)
        self.assertIn("unverified",js)


if __name__=="__main__":
    unittest.main()
