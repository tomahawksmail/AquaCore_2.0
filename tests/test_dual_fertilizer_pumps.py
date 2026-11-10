"""Lightweight dual-pump source checks; no live GPIO or MariaDB needed."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class DualPumpTests(unittest.TestCase):
    def test_python_syntax(self):
        for name in ("relay_controller.py","app.py","fertilizer_pump2_api.py"):
            with self.subTest(name=name):
                ast.parse((ROOT/name).read_text(encoding="utf8"), filename=name)
    def test_distinct_pins(self):
        text=(ROOT/"relay_controller.py").read_text(encoding="utf8")
        self.assertIn("PUMP_PIN = (23, 230)",text)
        self.assertIn("PUMP2_PIN = (19, 231)",text)
        # The two pump flags are assembled dynamically from their numbers.
        self.assertIn('f"PUMP{number}_ENABLED"',text)
        self.assertIn('default = "1" if number == 1 else "0"',text)
    def test_uv_co2_swapped_outputs(self):
        source=(ROOT/"relay_controller.py").read_text(encoding="utf8")
        tree=ast.parse(source)
        pin_assignment=next(node for node in tree.body
                            if isinstance(node,ast.Assign) and any(
                                isinstance(target,ast.Name) and target.id=="PIN_MAP"
                                for target in node.targets))
        pins=ast.literal_eval(pin_assignment.value)
        self.assertEqual(pins["co2_status"],(29,256))
        self.assertEqual(pins["UV_status"],(18,228))
        self.assertNotEqual(pins["co2_status"],pins["UV_status"])
        # Keep every other output unchanged.
        self.assertEqual(pins["o2_status"],(22,262))
        self.assertEqual(pins["MasterL_status"],(24,229))
        self.assertEqual(pins["Backlight_status"],(37,272))
        self.assertEqual(pins["PlantL_status"],(36,76))

    def test_safe_disabled_default(self):
        text=(ROOT/"deploy/sql/fertilizer_pump2_migration.sql").read_text(encoding="utf8")
        self.assertIn("fertilizer_dose_ml",text)
        self.assertIn("DEFAULT 0",text)
        self.assertIn("fertilizer_pump2_status",text)
    def test_isolated_api(self):
        text=(ROOT/"fertilizer_pump2_api.py").read_text(encoding="utf8")
        self.assertIn('url_prefix="/api/fertilizer/2"',text)
        self.assertNotIn("FROM options",text)
        self.assertNotIn("UPDATE options SET",text)
        self.assertIn("Pump 2 relay is disabled",text)
    def test_symmetric_enable_flags(self):
        worker=(ROOT/"relay_controller.py").read_text(encoding="utf8")
        web=(ROOT/"app.py").read_text(encoding="utf8")
        api2=(ROOT/"fertilizer_pump2_api.py").read_text(encoding="utf8")
        ui=(ROOT/"templates/options.html").read_text(encoding="utf8")
        self.assertIn('default = "1" if number == 1 else "0"', worker)
        self.assertIn('default = "1" if number == 1 else "0"', web)
        self.assertIn("if pump_enabled(1):", worker)
        self.assertIn("if pump_enabled(2):", worker)
        self.assertIn("args.apply and pump_enabled(1)", worker)
        self.assertIn("args.apply and pump_enabled(2)", worker)
        self.assertIn("if not pump_enabled(1):", web)
        self.assertIn("if not pump_enabled(2):", api2)
        self.assertIn("PUMP1_ENABLED=0", ui)
        self.assertIn("PUMP2_ENABLED=1", ui)

    def test_independent_ui(self):
        html=(ROOT/"templates/options.html").read_text(encoding="utf8")
        for ident in ("fertilizer-dose-now","fertilizer2-dose-now",
                      "fertilizer2-calibration-dialog","fertilizer2-scheduler-toggle"):
            self.assertIn('id="'+ident+'"',html)

if __name__=="__main__":
    unittest.main()
