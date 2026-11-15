"""Temporary user-requested 2.40V ~= pH7 display is labeled UNVERIFIED."""
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

from flask import Flask

import sensor_calibration_api as api
from sensor_conversion import (provisional_ph_neutral_anchor,
                               provisional_reference_ph_slope,
                               buffer_reference_ph)
from app import mask_pre_provisional_ph

ROOT = Path(__file__).resolve().parents[1]
VOLTAGES_PH686 = (2.40, 2.47, 2.47, 2.47, 2.40, 2.49, 2.46)
VOLTAGES_PH400 = (3.05, 3.05, 3.06, 3.05, 3.06, 3.05, 3.05)


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
            2.40, 2.40), 7.0)

    def test_current_244638_volts_is_near_seven(self):
        value=provisional_ph_neutral_anchor(2.44638,2.40)
        self.assertAlmostEqual(value,6.779447,places=5)

    def test_reference_pairs_define_slope_without_stale_database_voltages(self):
        avg686=sum(VOLTAGES_PH686)/7
        avg400=sum(VOLTAGES_PH400)/7
        expected=(avg400-avg686)/(6.86-4.00)
        self.assertAlmostEqual(avg686,2.4514285714285715)
        self.assertAlmostEqual(avg400,3.052857142857143)
        self.assertAlmostEqual(provisional_reference_ph_slope(),expected)
        self.assertAlmostEqual(provisional_reference_ph_slope(),0.21028971028971)

    def test_reject_invalid_voltages_and_anchor(self):
        for volts in (0,4.096,float("nan")):
            with self.subTest(volts=volts), self.assertRaises(ValueError):
                provisional_ph_neutral_anchor(volts,2.4)
        for anchor in (1.99,3.01,float("nan")):
            with self.subTest(anchor=anchor), self.assertRaises(ValueError):
                provisional_ph_neutral_anchor(2.4,anchor)

    def test_other_buffer_family_temperature_chart_is_separate(self):
        self.assertAlmostEqual(buffer_reference_ph("ph400",25),4.01)
        self.assertAlmostEqual(buffer_reference_ph("ph700",25),7.00)
        self.assertAlmostEqual(buffer_reference_ph("ph1000",25),10.01)
        self.assertAlmostEqual(buffer_reference_ph("ph700",22.5),7.01)
        self.assertAlmostEqual(buffer_reference_ph("ph1000",15),10.12)
        self.assertAlmostEqual(buffer_reference_ph("ph686",25),6.86)
        self.assertAlmostEqual(buffer_reference_ph("ph918",25),9.18)
        with self.assertRaises(ValueError):
            buffer_reference_ph("ph1000",0)

    def test_enabled_live_preview_uses_provisional_not_saved_curve(self):
        settings={"ph_provisional_enabled":1,"ph_provisional_neutral_v":2.4,
                  "ph401_voltage":3.3875625,"ph686_voltage":3.0879375,
                  "ph401_reference":4.004,"ph686_reference":6.872,
                  "ph918_voltage":2.82625,"ph918_reference":9.204,
                  "ntc_enabled":0,"ntc_supply_v":3.3}
        with self.app.test_request_context("/api/sensors/calibration/live?channel=a0"), \
             patch.object(api,"_admin"), \
             patch.object(api,"_db",return_value=FakeDb(settings)), \
             patch.object(api,"adc_read",return_value=(12345,2.44638)), \
             patch.object(api.time,"sleep"):
            result=api.live().get_json()
        self.assertTrue(result["ph_provisional"])
        self.assertAlmostEqual(result["ph_raw"],6.779447,places=5)
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

    def test_photo_reference_mode_is_independent_of_stale_saved_buffers(self):
        # Only the external-reference estimate can be enabled without needing
        # the older three-buffer readings; none of those values is deleted.
        db=FakeDb({"ph401_voltage":None,"ph686_voltage":None})
        with self.app.test_request_context(
            "/api/sensors/calibration/ph-provisional",method="POST",
            json={"enabled":True,"neutral_voltage":2.4}), \
             patch.object(api,"_admin"), \
             patch.object(api,"_db",return_value=db):
            data=api.save_ph_provisional().get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(db.committed)
        self.assertNotIn("ph401_voltage=",db.queries[0][0])

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
