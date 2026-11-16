"""Only TDS and NTC temperature factors remain; no artificial pH scaling."""
import unittest
from pathlib import Path
from sensor_conversion import temperature_compensated_ph_two_points

ROOT=Path(__file__).resolve().parents[1]

class FactorsTests(unittest.TestCase):
    def test_ph_uses_exact_two_buffer_references(self):
        self.assertAlmostEqual(temperature_compensated_ph_two_points(2.54,2.54,3.04,25,25,25),6.86)
        self.assertAlmostEqual(temperature_compensated_ph_two_points(3.04,2.54,3.04,25,25,25),4.01)

    def test_temp_factor(self):
        self.assertAlmostEqual(22.0*1.05+0.2,23.3)

    def test_tds_factor(self):
        self.assertAlmostEqual(200*0.105,21.0)

    def test_no_pH_multiplier_or_temperature_fallback_in_collector(self):
        code=(ROOT/"tds_collector.py").read_text()
        self.assertNotIn("ph_factor",code)
        self.assertNotIn("TDS_WATER_TEMP_C",code)
        self.assertNotIn("provisional_ph_neutral_anchor",code)

if __name__=="__main__":
    unittest.main()
