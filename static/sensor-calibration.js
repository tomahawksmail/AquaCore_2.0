/* AquaCore: operator-requested read-only sensor sampling and explicit calibration save. */
(() => {
  const modal = document.getElementById('sensor-calibration-dialog');
  const open = document.getElementById('sensor-open-calibration');
  if (!modal || !open) return;
  const status = document.getElementById('sensor-calibration-status');
  const csrf = window.AQUACORE_CSRF;
  const btn = (id) => document.getElementById(id);
  const setStatus = (message) => { status.textContent = message; };
  const names = ['tds_factor','ph_factor','temp_factor'];
  let snapshot = null;
  let timer = null;
  let inFlight = false;
  const factorValues = () => {
    const data = {};
    for (const name of names) {
      const field = btn('sensor-factor-' + name);
      const v = Number(field.value);
      if (!field.value.trim() || !Number.isFinite(v)) return null;
      const limits = {tds_factor:[0.001,10],ph_factor:[0.5,1.5],temp_factor:[0.8,1.2]};
      if (v < limits[name][0] || v > limits[name][1]) return null;
      data[name] = v;
    }
    return data;
  };
  const preview = () => {
    if (!snapshot) return;
    const factors = factorValues();
    for (const ch of ['a0','a1','a3']) {
      btn('sensor-live-' + ch).textContent = 'A' + ch.slice(1) + ': ' +
        snapshot.volts[ch].toFixed(5) + ' V';
    }
    if (!factors) {
      for (const field of ['ph','temp','tds']) btn('sensor-live-' + field).textContent = 'Invalid K factor';
      return;
    }
    const temp = snapshot.temp_raw == null ? null :
      snapshot.temp_raw * factors.temp_factor + snapshot.temp_offset_c;
    btn('sensor-live-temp').textContent = temp == null ?
      (snapshot.ntc_enabled ? 'Unavailable: ' + (snapshot.temp_error || 'invalid NTC') : 'Not configured (NTC disabled)') :
      (temp >= -2 && temp <= 55 ? temp.toFixed(2) + ' °C (preview)' : 'Outside temperature range');
    const ph = snapshot.ph_raw == null ? null :
      7 + (snapshot.ph_raw - 7) * factors.ph_factor;
    btn('sensor-live-ph').textContent = ph == null ?
      'Unavailable: ' + (snapshot.ph_error || 'save pH 7/4 buffer calibration') :
      (ph >= 0 && ph <= 14 ? ph.toFixed(2) + ' pH (preview)' : 'Outside pH range');
    const tempForTds = temp != null && temp >= -2 && temp <= 55 ?
      temp : snapshot.fallback_temperature_c;
    const voltage = Math.max(0, snapshot.tds_voltage) /
      (1 + 0.02 * (tempForTds - 25));
    const base = Math.max(0, (133.42 * voltage ** 3 -
      255.86 * voltage ** 2 + 857.39 * voltage) * 0.5);
    btn('sensor-live-tds').textContent =
      (base * factors.tds_factor).toFixed(1) + ' ppm (preview, provisional)';
  };
  const refreshLive = async () => {
    if (inFlight || !modal.open) return;
    inFlight = true;
    try {
      snapshot = await api('/live');
      preview();
      btn('sensor-live-updated').textContent =
        'Read at ' + snapshot.captured_at + ' · Browser K changes are unsaved';
    } catch (error) {
      btn('sensor-live-updated').textContent = error.message;
    } finally { inFlight = false; }
  };
  for (const name of names) btn('sensor-factor-' + name).addEventListener('input', preview);
  const api = async (path, payload) => {
    const response = await fetch('/api/sensors/calibration' + path, {
      method: payload === undefined ? 'GET' : 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
      body: payload === undefined ? undefined : JSON.stringify(payload),
      cache: 'no-store'
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Calibration request failed');
    return data;
  };
  const present = async () => {
    try {
      const result = await api('');
      for (const name of ['tds_factor','ph_factor','temp_factor']) {
        btn('sensor-factor-' + name).value = Number(result[name] ?? 1).toString();
      }
      btn('sensor-existing').textContent =
        'Temperature offset: ' + Number(result.temp_offset_c || 0).toFixed(2) +
        '°C · pH: ' + (result.ph7_voltage != null && result.ph4_voltage != null ? 'calibrated' : 'not calibrated');
    } catch (error) { setStatus(error.message); }
  };
  open.addEventListener('click', () => {
    setStatus('');
    modal.showModal();
    snapshot = null;
    present().then(preview);
    refreshLive();
    timer = window.setInterval(refreshLive, 5000);
  });
  const stopLive = () => { if (timer != null) window.clearInterval(timer); timer = null; };
  modal.addEventListener('close', stopLive);
  btn('sensor-calibration-close').addEventListener('click', () => modal.close());
  btn('sensor-live-refresh').addEventListener('click', refreshLive);
  btn('sensor-save-factors').addEventListener('click', async () => {
    const button = btn('sensor-save-factors');
    try {
      const data = {};
      for (const name of ['tds_factor','ph_factor','temp_factor']) {
        const input = btn('sensor-factor-' + name);
        if (input.value.trim() === '') throw new Error(name + ' is required');
        data[name] = Number(input.value);
        if (!Number.isFinite(data[name])) throw new Error(name + ' must be finite');
      }
      button.disabled = true;
      await api('/factors', data);
      setStatus('Saved sensor multipliers. The collector will apply them on its next sample.');
      await present();
      preview();
    } catch (error) { setStatus(error.message); }
    finally { button.disabled = false; }
  });
  for (const kind of ['temp','ph7','ph4']) {
    btn('sensor-capture-' + kind).addEventListener('click', async () => {
      const button = btn('sensor-capture-' + kind);
      button.disabled = true;
      setStatus('Reading stable ' + kind + ' voltage…');
      try {
        const result = await api('/sample', {kind});
        btn('sensor-voltage-' + kind).textContent =
          result.voltage.toFixed(5) + ' V' +
          (result.temperature_uncalibrated == null ? '' : ' · ' + result.temperature_uncalibrated.toFixed(2) + '°C raw');
        setStatus('Captured ' + kind + '. Save calibration within 15 minutes.');
      } catch (error) { setStatus(error.message); }
      finally { button.disabled = false; }
    });
  }
  btn('sensor-save-temp').addEventListener('click', async () => {
    try {
      const reference_c = Number(btn('sensor-temp-reference').value);
      if (!btn('sensor-temp-reference').value || !Number.isFinite(reference_c)) throw new Error('Enter reference °C');
      const result = await api('/save', {kind:'temp', reference_c});
      setStatus('Saved temperature offset: ' + result.temp_offset_c.toFixed(3) + '°C');
      present();
    } catch (error) { setStatus(error.message); }
  });
  btn('sensor-save-ph').addEventListener('click', async () => {
    try {
      const confirmed_buffers = btn('sensor-confirm-buffers').checked;
      if (!confirmed_buffers) throw new Error('Certified pH 7.00 and pH 4.00 buffers are required');
      const result = await api('/save', {kind:'ph', confirmed_buffers});
      setStatus('Saved pH calibration: pH7 = ' + result.ph7_voltage.toFixed(5) +
        'V, pH4 = ' + result.ph4_voltage.toFixed(5) + 'V');
      present();
    } catch (error) { setStatus(error.message); }
  });
})();
