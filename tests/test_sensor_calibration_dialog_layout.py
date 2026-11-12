"""Regression checks for AquaCore's sensor calibration dialog layout.

Pure source checks, useful where a Chromium/browser test is not available.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CalibrationDialogLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "templates/options.html").read_text(encoding="utf8")
        cls.css = (ROOT / "static/style.css").read_text(encoding="utf8")
        cls.js = (ROOT / "static/sensor-calibration.js").read_text(encoding="utf8")
        cls.base = (ROOT / "templates/base.html").read_text(encoding="utf8")

    def test_unique_dom_ids(self):
        ids = re.findall(r'\bid="([^"]+)"', self.page)
        self.assertEqual(len(ids), len(set(ids)), "Duplicate IDs break event bindings")

    def test_three_tabs_and_independent_footer_save_actions(self):
        for name in ("tds", "temp", "ph"):
            self.assertIn('id="sensor-tab-' + name + '"', self.page)
            self.assertIn('id="sensor-panel-' + name + '"', self.page)
            self.assertIn('id="sensor-save-' + name + '"', self.page)
        self.assertIn("byId('sensor-save-' + tab).hidden = tab !== name", self.js)
        self.assertIn(".sensor-save-button[hidden] { display:none!important; }", self.css)
        self.assertIn('class="sensor-dialog-footer"', self.page)

    def test_ph_guided_capture_and_progress(self):
        for kind in ("ph401", "ph686", "ph918"):
            for prefix in ("sensor-capture-", "sensor-voltage-", "sensor-buffer-", "sensor-state-"):
                self.assertIn('id="' + prefix + kind + '"', self.page)
        self.assertIn('id="sensor-ph-liquid-temp"', self.page)
        self.assertIn('id="sensor-ph-progress-bar"', self.page)
        self.assertIn('id="sensor-confirm-buffers"', self.page)
        self.assertIn("byId('sensor-ph-progress-bar').value = count", self.js)
        self.assertIn("setCaptureBusy(true)", self.js)
        self.assertIn("setCaptureBusy(false)", self.js)

    def test_scrolling_is_vertical_inside_dialog_and_buttons_remain_visible(self):
        self.assertIn(".sensor-dialog-scroll { flex:1 1 auto;", self.css)
        self.assertIn("overflow-y:auto; overflow-x:hidden;", self.css)
        self.assertIn(".sensor-dialog-footer { flex:none;", self.css)
        self.assertIn(".sensor-dialog-shell { display:flex; flex-direction:column;", self.css)
        self.assertIn("grid-template-columns:minmax(0,1fr)", self.css)
        self.assertIn("@media(max-width:630px)", self.css)

    def test_only_ui_changes_and_refreshes_stylesheet_assets(self):
        self.assertIn("20261112-calibration-ux-v2", self.base)
        self.assertIn("20261112-calibration-ux-v2", self.page)
        self.assertIn("setInterval(refreshLive, 500)", self.js)
        self.assertIn("captured[name] = data", self.js)
        self.assertIn("await api('/save', {kind:'ph3', confirmed_buffers:true})", self.js)


if __name__ == "__main__":
    unittest.main()
