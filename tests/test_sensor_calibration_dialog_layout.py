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
        self.assertNotIn('id="sensor-confirm-buffers"', self.page)
        self.assertNotIn('sensor-confirm-buffers', self.js)
        self.assertIn("count !== 3;", self.js)
        self.assertIn("byId('sensor-ph-progress-bar').value = count", self.js)
        self.assertIn("setCaptureBusy(true)", self.js)
        self.assertIn("setCaptureBusy(false)", self.js)

    def test_live_voltage_failure_is_channel_specific(self):
        api = (ROOT / "sensor_calibration_api.py").read_text(encoding="utf8")
        self.assertIn("voltage_errors=errors", api)
        self.assertIn("readings[key] = None", api)
        self.assertIn("readings[\"a0\"] is not None", api)
        self.assertIn("snapshot.voltage_errors?.[channel]", self.js)
        self.assertIn("api('/live?channel=' + activeChannel)", self.js)
        for channel in ("a0", "a1", "a3"):
            self.assertIn('id="sensor-voltage-error-' + channel + '"', self.page)
        self.assertIn("Read failed", self.js)
        self.assertIn("value !== null && value !== undefined", self.js)
        self.assertNotIn("confirmed_buffers", api[api.index('elif kind == "ph3"'):api.index('elif kind == "ph":')])

    def test_scrolling_is_vertical_inside_dialog_and_buttons_remain_visible(self):
        self.assertIn(".sensor-dialog-scroll { flex:1 1 auto;", self.css)
        self.assertIn("overflow-y:auto; overflow-x:hidden;", self.css)
        self.assertIn(".sensor-dialog-footer { flex:none;", self.css)
        self.assertIn(".sensor-dialog-shell { display:flex; flex-direction:column;", self.css)
        self.assertIn("grid-template-columns:minmax(0,1fr)", self.css)
        self.assertIn("@media(max-width:630px)", self.css)

    def test_only_ui_changes_and_refreshes_stylesheet_assets(self):
        self.assertIn("20261112-ntc-db-33v-v10", self.base)
        self.assertIn("20261112-ntc-db-5v-v9", self.page)
        self.assertIn('id="sensor-ph-auto-temperature"', self.page)
        self.assertIn('id="sensor-ph-atc-status"', self.page)
        self.assertIn('id="sensor-ph-ntc-status"', self.page)
        self.assertIn("syncBufferTemperatureMode()", self.js)
        self.assertIn("temperature_source:'ntc'", self.js)
        self.assertIn("temperature_source:'manual'", self.js)
        self.assertIn("new MutationObserver(syncLivePolling)", self.js)
        self.assertIn("attributeFilter:['open']", self.js)
        self.assertIn("modal.addEventListener('close', syncLivePolling)", self.js)
        self.assertIn("void refreshLive();", self.js)
        # The native dialog must be visible before any form widget reset.
        handler = self.js[self.js.index("open.addEventListener('click', async () => {"):]
        self.assertLess(handler.index("modal.showModal()"), handler.index("updatePhSave()"))
        # Poller must be started even if initialization fails.
        self.assertLess(handler.index("syncLivePolling()"), handler.index("try {"))
        self.assertIn("Calibration controls could not initialize", self.js)
        self.assertIn("new AbortController()", self.js)
        self.assertIn("timeout after 5 seconds", self.js)
        self.assertNotIn("|| document.hidden", self.js)
        self.assertIn("refreshLive();", self.js)
        self.assertIn("setInterval(refreshLive, 500)", self.js)
        self.assertIn("captured[name] = data", self.js)
        self.assertIn("await api('/save', {kind:'ph3'})", self.js)


if __name__ == "__main__":
    unittest.main()
