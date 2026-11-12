"""Three-buffer pH and temperature table regression tests; no hardware needed."""
import unittest
from pathlib import Path

from sensor_conversion import (buffer_reference_ph, calibrated_ph_three_points,
                               validate_ph_three_points)

ROOT = Path(__file__).resolve().parents[1]

class ThreeBufferTests(unittest.TestCase):
    def test_25_degree_nominal_reference(self):
        for kind, expected in (("ph401",4.01),("ph686",6.86),("ph918",9.18)):
            with self.subTest(kind=kind):
                self.assertAlmostEqual(buffer_reference_ph(kind,25),expected)

    def test_room_22_5_degree_expected_reference(self):
        self.assertAlmostEqual(buffer_reference_ph("ph401",22.5),4.005)
        self.assertAlmostEqual(buffer_reference_ph("ph686",22.5),6.87)
        self.assertAlmostEqual(buffer_reference_ph("ph918",22.5),9.20)

    def test_curve_hits_each_buffer(self):
        p = [buffer_reference_ph(name,22.5) for name in ("ph401","ph686","ph918")]
        for volts, expected in ((3.0,p[0]),(2.5,p[1]),(2.1,p[2])):
            self.assertAlmostEqual(calibrated_ph_three_points(volts,3.0,2.5,2.1,*p),expected,places=5)

    def test_interpolation_at_middle(self):
        p = [buffer_reference_ph(name,25) for name in ("ph401","ph686","ph918")]
        self.assertAlmostEqual(calibrated_ph_three_points(2.75,3.0,2.5,2.1,*p),
                               (4.01+6.86)/2)
        self.assertAlmostEqual(calibrated_ph_three_points(2.3,3.0,2.5,2.1,*p),
                               (6.86+9.18)/2)
        # Also support modules with inverted voltage-to-pH polarity.
        self.assertAlmostEqual(calibrated_ph_three_points(1.8,1.0,1.5,2.1,*p),
                               6.86+(9.18-6.86)*(1.8-1.5)/(2.1-1.5))

    def test_reject_crossed_or_flat_voltage(self):
        for vals in ((3.0,2.5,2.9),(3.0,3.0,2.5),(0,2.5,2.1),
                     (3.0,2.99,2.1)):
            with self.subTest(vals=vals), self.assertRaises(ValueError):
                validate_ph_three_points(*vals,4.01,6.86,9.18)

    def test_reject_invalid_temperature_and_unknown_buffer(self):
        for temp in (-1,51,float("nan")):
            with self.subTest(temp=temp),self.assertRaises(ValueError):
                buffer_reference_ph("ph686",temp)
        with self.assertRaises(ValueError):
            buffer_reference_ph("ph700",22)

    def test_collector_reads_three_buffer_model(self):
        code = (ROOT / "tds_collector.py").read_text()
        self.assertIn("calibrated_ph_three_points",code)
        self.assertIn("'ph918_reference'",code)
        self.assertIn("has_three or (v7 is not None",code)

    def test_ui_has_three_tabs_capture_buttons_and_half_second_poll(self):
        html=(ROOT/"templates/options.html").read_text()
        js=(ROOT/"static/sensor-calibration.js").read_text()
        for name in ("tds","temp","ph"):
            self.assertIn('id="sensor-tab-'+name+'"',html)
            self.assertIn('id="sensor-panel-'+name+'"',html)
        for name in ("ph918","ph401","ph686"):
            self.assertIn('id="sensor-capture-'+name+'"',html)
            self.assertIn('id="sensor-voltage-'+name+'"',html)
        self.assertIn('id="sensor-ph-liquid-temp"',html)
        self.assertIn("temperature_c:temp",js)
        self.assertIn("setInterval(refreshLive, 500)",js)

    def test_migration_and_fresh_install_schema(self):
        m=(ROOT/"deploy/sql/ph_three_buffer_migration.sql").read_text()
        fresh=(ROOT/"deploy/sql/sensor_calibration.sql").read_text()
        for name in ("ph401","ph686","ph918"):
            for suffix in ("_voltage","_reference","_temp_c"):
                self.assertIn(name+suffix,m)
                self.assertIn(name+suffix,fresh)

if __name__ == "__main__":
    unittest.main()
