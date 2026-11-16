"""API integration: A1 water temperature drives two-buffer pH, never a fallback."""
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
import sensor_calibration_api as api
from sensor_conversion import temperature_compensated_ph_two_points

class FakeDB:
    def __init__(self,row):
        self.row=row;self.writes=[];self.committed=False
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def cursor(self):return self
    def execute(self,sql,params=None):self.writes.append((sql,params))
    def fetchone(self):return self.row
    def commit(self):self.committed=True

class PhA1Tests(unittest.TestCase):
    def setUp(self):
        self.flask=Flask(__name__)
        self.flask.secret_key="test-secret"
        self.config={"ntc_enabled":1,"ntc_supply_v":3.3,
                     "temp_factor":1.0,"temp_offset_c":0,
                     "temp_updated_at":"done","ph686_voltage":2.54,
                     "ph401_voltage":3.04,"ph686_temp_c":25,
                     "ph401_temp_c":25}
    def test_live_uses_a1(self):
        def adc(bus,address,ch):
            return (10000, 1.65 if ch==1 else 2.54)
        with self.flask.test_request_context("/api/sensors/calibration/live?channel=a0"), \
             patch.object(api,"_admin"), patch.object(api,"_db",return_value=FakeDB(self.config)), \
             patch.object(api,"adc_read",side_effect=adc), patch.object(api.time,"sleep"):
            result=api.live().get_json()
        self.assertTrue(result["ph_temperature_compensated"])
        self.assertAlmostEqual(result["ph_raw"],6.86)
        self.assertAlmostEqual(result["ph_temperature_c"],25)

    def test_disconnected_a1_keeps_raw_a0_but_no_ph(self):
        def adc(bus,address,ch):
            if ch==1:raise OSError("Disconnected")
            return (10000,2.54)
        with self.flask.test_request_context("/api/sensors/calibration/live?channel=a0"), \
             patch.object(api,"_admin"), patch.object(api,"_db",return_value=FakeDB(self.config)), \
             patch.object(api,"adc_read",side_effect=adc), patch.object(api.time,"sleep"):
            result=api.live().get_json()
        self.assertAlmostEqual(result["volts"]["a0"],2.54)
        self.assertIsNone(result["ph_raw"])
        self.assertFalse(result["ph_temperature_compensated"])

    def test_buffer_capture_uses_a1_if_same_buffer(self):
        calls=[]
        def sample(ch):
            calls.append(ch);return 1.65 if ch==1 else 2.54
        with self.flask.test_request_context("/api/sensors/calibration/sample",method="POST",
                json={"kind":"ph686","temperature_source":"ntc"}), \
             patch.object(api,"_admin"),patch.object(api,"_db",return_value=FakeDB(self.config)), \
             patch.object(api,"_sample",side_effect=sample):
            result=api.sample().get_json()
        self.assertEqual(calls,[1,0])
        self.assertAlmostEqual(result["reference_ph"],6.86)

    def test_two_buffer_capture_save(self):
        import time
        db=FakeDB(self.config)
        with self.flask.test_request_context("/api/sensors/calibration/save",method="POST",json={"kind":"ph2"}), \
             patch.object(api,"_admin"),patch.object(api,"_db",return_value=db):
            api.session["sensor_reference_ph686"]={"volts":2.54,"ts":time.time(),"temperature_c":25}
            api.session["sensor_reference_ph401"]={"volts":3.04,"ts":time.time(),"temperature_c":25}
            result=api.save().get_json()
        self.assertTrue(result["ok"])
        self.assertTrue(db.committed)
        self.assertIn("ph686_voltage=%s,ph401_voltage=%s",db.writes[0][0])
        self.assertEqual(db.writes[0][1],(2.54,3.04,25.0,25.0))

    def test_old_three_buffer_save_not_supported(self):
        with self.flask.test_request_context("/api/sensors/calibration/save",method="POST",json={"kind":"ph3"}), \
             patch.object(api,"_admin"):
            result, status=api.save()
        self.assertEqual(status,400)

if __name__=="__main__":
    unittest.main()
