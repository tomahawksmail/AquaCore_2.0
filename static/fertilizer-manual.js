"use strict";
(() => {
  // Momentary switches: unlike lighting toggles, these request one pulse,
  // then return to OFF; a queued request is not proof GPIO actually energized.
  const doseSwitch = document.getElementById('fertilizer-dose-now');
  const testSwitch = document.getElementById('fertilizer-calibrate-start');
  const saveBtn = document.getElementById('fertilizer-calibrate-save');
  const mlInput = document.getElementById('fertilizer-ml');
  const timeInput = document.getElementById('fertilizer-time');
  const measuredInput = document.getElementById('fertilizer-measured-ml');
  const rateLabel = document.getElementById('fertilizer-calibration-rate');
  const doseLabel = document.getElementById('fertilizer-dose-state');
  const status = document.getElementById('fertilizer-dose-status');
  if (![doseSwitch, testSwitch, saveBtn, mlInput, timeInput,
        measuredInput, rateLabel, doseLabel, status].every(Boolean)) return;

  const readonly = testSwitch.disabled && saveBtn.disabled;
  let calibrated = rateLabel.textContent.includes('Calibrated:');
  let busy = false;
  let cooldownUntil = 0;
  let cooldownTimer;

  function updateUI() {
    const ml = Number(mlInput.dataset.saved ?? mlInput.value);
    const hasDose = Number.isFinite(ml) && ml > 0 && ml <= 100;
    const time = timeInput.dataset.saved ?? timeInput.value;
    doseLabel.textContent = calibrated && hasDose ?
      'Scheduled · ' + (time || '--:--') + ' · ' + ml + ' ml' : 'Scheduled · OFF';
    const locked = busy || Date.now() < cooldownUntil;
    doseSwitch.disabled = readonly || locked || mlInput.disabled || !calibrated || !hasDose;
    testSwitch.disabled = readonly || locked;
    saveBtn.disabled = readonly || busy || !measuredInput.value || !measuredInput.checkValidity();
  }

  async function api(path, payload = {}) {
    const response = await fetch(path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': window.AQUACORE_CSRF
      },
      body: JSON.stringify(payload)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'HTTP ' + response.status);
    return data;
  }

  function lockForCooldown() {
    cooldownUntil = Date.now() + 120000;
    clearTimeout(cooldownTimer);
    cooldownTimer = setTimeout(updateUI, 120100);
  }

  async function momentaryRequest(toggle, kind) {
    if (!toggle.checked) return;
    const ml = Number(mlInput.dataset.saved ?? mlInput.value);
    const prompt = kind === 'dose'
      ? 'Dispense an EXTRA ' + ml + ' ml of fertilizer now?'
      : 'Place the pump outlet into a measuring cup OUTSIDE the aquarium. Run a 10-second test?';
    if (!window.confirm(prompt)) {
      toggle.checked = false;
      return;
    }
    busy = true;
    updateUI();
    status.textContent = kind === 'dose'
      ? 'Requesting manual dose…' : 'Requesting calibration test…';
    try {
      const result = await api(kind === 'dose'
        ? '/api/fertilizer/dose' : '/api/fertilizer/calibration/start');
      lockForCooldown();
      status.textContent = kind === 'dose'
        ? 'Dose queued (' + result.duration_seconds + ' seconds). Verify relay logs.'
        : '10-second test queued. After pump stops, measure the collected ml, enter it and press Save.';
    } catch (error) {
      status.textContent = 'Pump request failed: ' + error.message;
    } finally {
      // One-shot actions, not persistent ON/OFF modes.
      toggle.checked = false;
      busy = false;
      updateUI();
    }
  }

  doseSwitch.addEventListener('change', () => momentaryRequest(doseSwitch, 'dose'));
  testSwitch.addEventListener('change', () => momentaryRequest(testSwitch, 'calibration'));
  measuredInput.addEventListener('input', updateUI);
  document.addEventListener('aquacore:setting-saved', event => {
    if (['fertilizer_time', 'fertilizer_dose_ml'].includes(event.detail?.field)) {
      queueMicrotask(updateUI);
    }
  });

  saveBtn.addEventListener('click', async () => {
    if (saveBtn.disabled) return;
    if (!measuredInput.checkValidity()) {
      measuredInput.reportValidity();
      return;
    }
    if (!window.confirm('Save pump calibration based on ' +
          measuredInput.value + ' ml collected during the 10-second test?')) return;
    busy = true;
    updateUI();
    try {
      const result = await api('/api/fertilizer/calibration/finish', {
        measured_ml: measuredInput.value
      });
      calibrated = true;
      rateLabel.textContent = 'Calibrated: ' + Number(result.ml_per_second).toFixed(3) + ' ml/sec';
      status.textContent = 'Calibration saved. Verify the dose with a separate water test.';
    } catch (error) {
      status.textContent = 'Calibration not saved: ' + error.message;
    } finally {
      busy = false;
      updateUI();
    }
  });
  updateUI();
})();
