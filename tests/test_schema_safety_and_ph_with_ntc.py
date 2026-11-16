"""Schema safety, no synthetic measurements, and collector A1 requirements."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import app
import tds_collector
from water_history import history_sql, serialize_history

ROOT=Path(__file__).resolve().parents[1]
UNUSED_METRICS=("scpufreq_min","scpufreq_max","cpu_thermal_high","cpu_thermal_crit",
                "gpu_thermal_cur","gpu_thermal_high","gpu_thermal_crit","ve_thermal_cur")
SENSOR_FIELDS=("ntc_enabled","ntc_supply_v","temp_offset_c","temp_updated_at",
               "tds_factor","temp_factor","ph686_voltage","ph401_voltage",
               "ph686_temp_c","ph401_temp_c","ph_updated_at")
OBSOLETE=("ph7_voltage","ph4_voltage","ph918_voltage","ph918_reference",
          "ph401_reference","ph686_reference","ph_factor","ph_provisional_enabled",
          "ph_provisional_neutral_v","ph_provisional_started_at")

class SchemaTests(unittest.TestCase):
    def test_both_fresh_schemas_are_complete(self):
        for name in ("clean_install.sql","aquacore_empty_bootstrap.sql"):
            sql=(ROOT/"deploy"/"sql"/name).read_text()
            section=sql.split("CREATE TABLE IF NOT EXISTS sensor_calibration (")[1].split(") ENGINE")[0]
            for field in SENSOR_FIELDS:
                self.assertIn(field+" ",section,(name,field))
            for field in OBSOLETE:
                self.assertNotIn(field+" ",section,(name,field))
            psutil=sql.split("CREATE TABLE IF NOT EXISTS `psutil` (")[1].split(") ENGINE")[0]
            for field in UNUSED_METRICS:
                self.assertNotIn("`"+field+"`",psutil)

    def test_migration_sets_exact_voltages_and_drops_obsolete(self):
        sql=(ROOT/"deploy/sql/ph_two_buffer_ntc_migration.sql").read_text()
        self.assertIn("`ph686_voltage`=2.54",sql)
        self.assertIn("`ph401_voltage`=3.04",sql)
        self.assertIn("`ph_updated_at`=NOW()",sql)
        for field in OBSOLETE:
            self.assertIn("DROP COLUMN IF EXISTS `"+field+"`",sql)

    def test_scheduler_does_not_create_zero_samples(self):
        text=(ROOT/"scheduler.py").read_text()
        self.assertNotIn("insert_missing_sensor_zeros",text)
        self.assertNotIn("insert_missing_system_zeros",text)

    def test_history_contract_is_same_for_both_chart_consumers(self):
        app_code=(ROOT/"app.py").read_text()
        tg=(ROOT/"telegram_bot.py").read_text()
        self.assertIn('history_sql(period)',app_code)
        self.assertIn('history_sql("24h")',tg)
        sql,params=history_sql("24h")
        self.assertIn("ROUND(AVG(CASE",sql)
        self.assertIn("ph_updated_at FROM sensor_calibration",sql)
        self.assertIn("ROUND(AVG(temp), 2)",sql)
        self.assertIn("ROUND(AVG(tds), 2)",sql)
        self.assertEqual(params,(288,288,1,288))
        self.assertEqual(serialize_history([{"time":datetime(2026,11,16),"temp":24,
            "ph":6.8,"tds":202,"samples":3}],{"min_ph":6.0}, "24h")["points"][0]["ph"],6.8)

    def test_live_stale_data_not_mislabeled(self):
        now=datetime(2026,11,16,12)
        row={"Datetime":now-timedelta(minutes=4),"temp":25,"ph":9.87,"tds":200}
        masked,stale=app.mask_stale_sensor_reading(row,current_time=now)
        self.assertTrue(stale)
        self.assertIsNone(masked["ph"])
        self.assertEqual(row["ph"],9.87)
        mask=app.mask_pre_calibration_ph([dict(row)],now)
        self.assertIsNone(mask[0]["ph"])

    def test_offline_collector_does_not_invent_water_temperature(self):
        config={"ntc_enabled":0,"ntc_supply_v":3.3,
                "ph686_voltage":2.54,"ph401_voltage":3.04,
                "ph686_temp_c":25,"ph401_temp_c":25}
        events=[]
        with patch.object(sys,"argv",["tds_collector.py","--once","--samples","1"]), \
             patch.object(tds_collector,"calibration_settings",return_value=config), \
             patch.object(tds_collector,"save_sample",side_effect=lambda *v:events.append(v)), \
             patch.object(tds_collector,"adc_read",side_effect=AssertionError("No sensor reads without A1")):
            self.assertEqual(tds_collector.main(),0)
        self.assertEqual(events,[(None,None,None)])

    def test_collector_temperature_compensates_neutral(self):
        config={"ntc_enabled":1,"ntc_supply_v":3.3,"temp_updated_at":"saved",
                "temp_factor":1.0,"temp_offset_c":0.0,"tds_factor":0.2626,
                "ph686_voltage":2.54,"ph401_voltage":3.04,
                "ph686_temp_c":25,"ph401_temp_c":25}
        events=[]
        def adc(_bus,_addr,ch):
            return (10000,1.65 if ch==1 else 1.0)
        with patch.object(sys,"argv",["tds_collector.py","--once","--samples","1"]), \
             patch.object(tds_collector,"calibration_settings",return_value=config), \
             patch.object(tds_collector,"median_ph_voltage",return_value=2.54), \
             patch.object(tds_collector,"save_sample",side_effect=lambda *v:events.append(v)), \
             patch.object(tds_collector,"adc_read",side_effect=adc), \
             patch.object(tds_collector.time,"sleep"):
            self.assertEqual(tds_collector.main(),0)
        ppm,temp,ph=events[0]
        self.assertGreater(ppm,0)
        self.assertAlmostEqual(temp,25)
        self.assertAlmostEqual(ph,6.86)

if __name__=="__main__":
    unittest.main()
