"""Source-level regression checks for dosing confirmations and metric line trends."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class SaveAndChartTests(unittest.TestCase):
    def test_app_parses_and_excludes_invalid_history(self):
        app = (ROOT / "app.py").read_text(encoding="utf8")
        ast.parse(app)
        self.assertIn("SELECT * FROM psutil WHERE RAM_total > 0", app)
        self.assertIn("ORDER BY Id DESC LIMIT 1500", app)

    def test_calibration_closes_only_after_save(self):
        for path in ("fertilizer-manual.js", "fertilizer-manual2.js"):
            with self.subTest(path=path):
                content = (ROOT / "static" / path).read_text(encoding="utf8")
                success = content.index("calibrated=true;calibrationReady=false;")
                closed = content.index("dialog.close();", success)
                catch = content.index("}catch(error){", success)
                self.assertLess(success, closed)
                self.assertLess(closed, catch)
                self.assertIn("setNotice('Calibration saved", content[success:catch])

    def test_bottle_b_save_confirmation_persists(self):
        content = (ROOT / "static" / "fertilizer-weekly2.js").read_text(encoding="utf8")
        self.assertIn("Bottle B saved schedule: ", content)
        self.assertIn("Bottle B schedule saved: ", content)
        self.assertIn("Server did not confirm the selected weekdays", content)

    def test_system_charts_draw_lines_without_false_zero_samples(self):
        content = (ROOT / "static" / "system.js").read_text(encoding="utf8")
        self.assertIn("three-sample moving-average lines", content)
        self.assertIn('stroke-linejoin="round"', content)
        self.assertIn("times[k]-times[k-1]>20*60*1000", content)

if __name__ == "__main__":
    unittest.main()
