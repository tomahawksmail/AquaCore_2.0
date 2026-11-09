"""Regression checks for configurable CPU cooler thresholds (read-only)."""
import ast
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class CoolerThresholdTests(unittest.TestCase):
    def test_source_parses(self):
        for name in ("app.py","relay_controller.py"):
            ast.parse((ROOT/name).read_text(),filename=name)

    def test_hysteresis_logic(self):
        tree=ast.parse((ROOT/"relay_controller.py").read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
                and n.name=="desired_cooler_on")
        scope={"COOLER_ON_C":70.0,"COOLER_OFF_C":65.0}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),"cooler","exec"),scope)
        f=scope["desired_cooler_on"]
        self.assertTrue(f(71,None))
        self.assertFalse(f(65,True))
        self.assertTrue(f(68,True))
        self.assertFalse(f(68,False))
        self.assertTrue(f(64,None,63,58))
        self.assertFalse(f(58,True,63,58))

    def test_database_and_ui(self):
        relay=(ROOT/"relay_controller.py").read_text()
        web=(ROOT/"app.py").read_text()
        html=(ROOT/"templates/options.html").read_text()
        self.assertIn("load_cooler_thresholds",relay)
        self.assertIn("on-off < 3",relay)
        self.assertIn("cooler_fields=('cooler_on_c','cooler_off_c')",web)
        self.assertIn("on-off < Decimal('3')",web)
        for name in ("cooler_on_c","cooler_off_c"):
            self.assertIn('name="'+name+'"',html)

if __name__=="__main__":
    unittest.main()
