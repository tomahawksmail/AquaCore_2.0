/* AquaCore: operator-requested read-only sensor sampling and explicit calibration save. */
(() => {
  const modal = document.getElementById('sensor-calibration-dialog');
  const open = document.getElementById('sensor-open-calibration');
  if (!modal || !open) return;
  const status = document.getElementById('sensor-calibration-status');
  const csrf = window.AQUACORE_CSRF;
  const btn = (id) => document.getElementById(id);
  const setStatus = (message) => { status.textContent = message; };
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
  open.addEventListener('click', () => { setStatus(''); modal.showModal(); present(); });
  btn('sensor-calibration-close').addEventListener('click', () => modal.close());
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
