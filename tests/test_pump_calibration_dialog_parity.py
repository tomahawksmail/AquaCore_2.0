"""Pump 2 must mirror Pump 1's calibration UI without sharing relay state.

Source-level checks run in GitHub Actions without live pump or MariaDB.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "templates/options.html"
JS = ROOT / "static"


def calibration_dialog(html, pump):
    prefix = "fertilizer" if pump == 1 else "fertilizer2"
    result = re.search(
        rf'<dialog id="{prefix}-calibration-dialog".*?</dialog>',
        html, flags=re.S)
    if result is None:
        raise AssertionError(f"Missing pump {pump} calibration dialog")
    return result.group()


class CalibrationParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML.read_text(encoding="utf-8")
        cls.p1 = (JS / "fertilizer-manual.js").read_text(encoding="utf-8")
        cls.p2 = (JS / "fertilizer-manual2.js").read_text(encoding="utf-8")
        cls.css = (JS / "style.css").read_text(encoding="utf-8")

    def test_identical_dialog_structure_except_pump_names_and_settings(self):
        a = calibration_dialog(self.html, 1)
        b = calibration_dialog(self.html, 2)
        b = b.replace("fertilizer2", "fertilizer")
        b = b.replace("Pump 2 · Bottle B", "Pump 1 · Bottle A")
        self.assertEqual(a, b, "Pump 2 calibration must mirror Pump 1")
        for title in ("Pump 1 · Bottle A calibration",
                      "Pump 2 · Bottle B calibration"):
            self.assertIn(title, self.html)

    def test_two_step_workflow_and_controls_are_on_both(self):
        for pump in (1, 2):
            dialog = calibration_dialog(self.html, pump)
            prefix = "fertilizer" if pump == 1 else "fertilizer2"
            for label in ("Run a timed test", "Measure and save",
                          "Prime the pump", "Run test", "Save calibration",
                          "Collected volume (ml)", "Test duration (seconds)"):
                self.assertIn(label, dialog)
            for key in ("calibration-seconds", "measured-ml", "test-progress",
                        "progress-meter", "calibrate-start", "calibrate-save"):
                self.assertIn(f'id="{prefix}-{key}"', dialog)
        self.assertIn(".fertilizer-calibration-step", self.css)
        self.assertIn("@media(max-width:510px)", self.css)
        self.assertIn("20261118-pump-calibration-parity-v1", self.html)

    def test_logic_is_mirrored_but_endpoints_and_relay_states_are_distinct(self):
        p2 = (self.p2.replace("/api/fertilizer/2/", "/api/fertilizer/")
                     .replace("fertilizer2", "fertilizer")
                     .replace("PUMP2", "PUMP1")
                     .replace("Pump 2", "Pump 1"))
        self.assertEqual(self.p1, p2,
                         "Keep pump calibration and save behavior equivalent")
        self.assertIn("'/api/fertilizer/calibration/start'", self.p1)
        self.assertIn("'/api/fertilizer/2/calibration/start'", self.p2)
        self.assertIn("'/api/fertilizer/calibration/finish'", self.p1)
        self.assertIn("'/api/fertilizer/2/calibration/finish'", self.p2)
        self.assertIn("PUMP1_ENABLED=0", self.p1)
        self.assertIn("PUMP2_ENABLED=0", self.p2)
        self.assertIn("if(!window.confirm(", self.p1)
        self.assertIn("if(!window.confirm(", self.p2)


if __name__ == "__main__":
    unittest.main()
