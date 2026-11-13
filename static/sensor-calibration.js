/* AquaCore three-tab sensor calibration; only explicit Save writes to MariaDB. */
"use strict";
(() => {
  const modal = document.getElementById('sensor-calibration-dialog');
  const open = document.getElementById('sensor-open-calibration');
  if (!modal || !open) return;
  const byId = id => document.getElementById(id);
  const status = byId('sensor-calibration-status');
  const existing = byId('sensor-existing');
  const bufferNames = ['ph918', 'ph401', 'ph686'];
  const bufferLabels = {ph918:'9.18', ph401:'4.01', ph686:'6.86'};
  const tabs = ['tds', 'temp', 'ph'];
  let timer = null, inFlight = false, captureBusy = false;
  let snapshot = null, settings = null, activeTab = 'tds';
  let captured = {};
  // Only smooth the *pH estimate*, never the raw A0 voltage required for
  // observing probe stabilization or capturing reference buffers.
  const livePhWindow = [];
  const median = values => {
    const sorted = [...values].sort((a, b) => a - b);
    const center = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[center] :
      (sorted[center - 1] + sorted[center]) / 2;
  };
  const setStatus = (message, state = 'idle') => {
    status.textContent = message;
    status.dataset.state = state;
  };
  let temperatureCaptured = false;
  const updateTempSave = () => {
    const input = byId('sensor-temp-reference');
    byId('sensor-save-temp').disabled = captureBusy || !temperatureCaptured ||
      !input.value.trim() || !input.checkValidity();
  };
  const autoBufferTemp = byId('sensor-ph-auto-temperature');
  const manualBufferTemp = byId('sensor-ph-liquid-temp');
  const syncBufferTemperatureMode = () => {
    manualBufferTemp.disabled = autoBufferTemp.checked;
    manualBufferTemp.required = !autoBufferTemp.checked;
  };
  autoBufferTemp.addEventListener('change', syncBufferTemperatureMode);
  syncBufferTemperatureMode();

  const api = async (path, payload) => {
    // Live requests must never leave the dialog stuck displaying "Reading…".
    // If Gunicorn, MariaDB or an I²C lock stalls, abort the preview and show
    // a useful error. Reference captures and writes retain their normal flow.
    const isLive = path.startsWith('/live');
    const controller = isLive ? new AbortController() : null;
    const deadline = isLive ? window.setTimeout(() => controller.abort(), 5000) : null;
    try {
      const response = await fetch('/api/sensors/calibration' + path, {
        method: payload === undefined ? 'GET' : 'POST',
        credentials: 'same-origin', cache: 'no-store',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': window.AQUACORE_CSRF},
        body: payload === undefined ? undefined : JSON.stringify(payload),
        signal: controller?.signal
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.error || 'HTTP ' + response.status);
      return body;
    } catch (error) {
      if (error.name === 'AbortError' && isLive)
        throw new Error('Live API timeout after 5 seconds. Check web-service log, database and ADS1115 lock.');
      throw error;
    } finally {
      if (deadline !== null) window.clearTimeout(deadline);
    }
  };

  const selectTab = name => {
    if (!tabs.includes(name)) return;
    const changed = activeTab !== name;
    activeTab = name;
    if (changed) {
      snapshot = null;
      livePhWindow.length = 0;
      const channel = {tds:'a3', temp:'a1', ph:'a0'}[name];
      byId('sensor-live-' + channel).textContent = 'Reading…';
      byId('sensor-voltage-error-' + channel).textContent = '';
    }
    for (const tab of tabs) {
      const selected = tab === name;
      const tabEl = byId('sensor-tab-' + tab);
      tabEl.classList.toggle('is-active', selected);
      tabEl.setAttribute('aria-selected', String(selected));
      tabEl.tabIndex = selected ? 0 : -1;
      byId('sensor-panel-' + tab).hidden = !selected;
    }
    for (const tab of tabs) {
      byId('sensor-save-' + tab).hidden = tab !== name;
    }
    const scroller = modal.querySelector('.sensor-dialog-scroll');
    if (scroller) scroller.scrollTop = 0;
    setStatus(tab === 'ph' ? 'Start with pH 6.86, then 4.01 and 9.18.' :
      tab === 'temp' ? 'Capture A1, then enter your glass thermometer reading.' :
      'View the live TDS estimate and adjust the factor if needed.');
    render();
    if (changed && modal.open) refreshLive();
  };

  for (const name of tabs) {
    const tab = byId('sensor-tab-' + name);
    tab.addEventListener('click', () => selectTab(name));
    tab.addEventListener('keydown', event => {
      if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const current = tabs.indexOf(name);
      const next = event.key === 'Home' ? 0 :
        event.key === 'End' ? tabs.length - 1 :
        (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      selectTab(tabs[next]);
      byId('sensor-tab-' + tabs[next]).focus();
    });
  }

  const setCaptureBusy = busy => {
    captureBusy = busy;
    for (const name of bufferNames) byId('sensor-capture-' + name).disabled = busy;
    byId('sensor-capture-temp').disabled = busy;
    updatePhSave();
    updateTempSave();
  };

  const updatePhSave = () => {
    const count = bufferNames.filter(name => Boolean(captured[name])).length;
    byId('sensor-ph-progress').textContent = count + ' of 3 captured';
    byId('sensor-ph-progress-bar').value = count;
    for (const name of bufferNames) {
      byId('sensor-buffer-' + name).classList.toggle('is-captured', Boolean(captured[name]));
      byId('sensor-state-' + name).textContent = captured[name] ? '✓ Captured' : 'Not captured';
    }
    byId('sensor-save-ph').disabled = captureBusy || count !== 3;
  };

  const render = () => {
    if (!snapshot) return;
    const volts = snapshot.volts || {};
    const valid = value => value !== null && value !== undefined &&
      Number.isFinite(Number(value));
    for (const channel of ['a0', 'a1', 'a3']) {
      const value = volts[channel];
      const el = byId('sensor-live-' + channel);
      el.textContent = valid(value) ? Number(value).toFixed(5) + ' V' :
        (snapshot.voltage_errors?.[channel] ? 'Read failed' : '— V');
      const error = snapshot.voltage_errors?.[channel] || '';
      el.title = error;
      byId('sensor-voltage-error-' + channel).textContent = error;
    }
    const tempFactor = Number(settings?.temp_factor ?? 1);
    const calibratedTemp = snapshot.temp_raw == null ? null :
      snapshot.temp_raw * tempFactor + Number(settings?.temp_offset_c ?? snapshot.temp_offset_c ?? 0);
    byId('sensor-live-temp').textContent = calibratedTemp == null ||
      !Number.isFinite(calibratedTemp) ?
      (snapshot.ntc_enabled ? 'A1 unavailable' : 'NTC disabled') :
      calibratedTemp.toFixed(2) + ' °C';

    const ph = livePhWindow.length ? median(livePhWindow) : null;
    byId('sensor-live-ph').textContent = ph == null || !Number.isFinite(ph) ?
      'Not calibrated' : ph.toFixed(2) + ' pH';
    if (activeTab === 'ph') {
      const a1Ready = Boolean(snapshot.ntc_enabled && settings?.temp_updated_at &&
        snapshot.ph_temperature_c != null && Number.isFinite(Number(snapshot.ph_temperature_c)));
      autoBufferTemp.disabled = !a1Ready;
      if (!a1Ready && autoBufferTemp.checked) {
        autoBufferTemp.checked = false;
        syncBufferTemperatureMode();
      }
      const t = a1Ready ? Number(snapshot.ph_temperature_c).toFixed(2) + '°C' : null;
      byId('sensor-ph-ntc-status').textContent = a1Ready ?
        ('A1 ready: ' + t + '. Select A1 only when BOTH probes are in this buffer.') :
        ('A1 not ready: ' + (snapshot.ph_temperature_note || 'calibrate A1 first') +
         '. Enter the buffer temperature manually.');
      byId('sensor-ph-atc-status').textContent =
        snapshot.ph_temperature_compensated ?
          ('Live pH: electrode-slope compensation ON at ' + t + ' (A1).') :
          ('Live pH: uncompensated electrode slope. ' +
           (snapshot.ph_temperature_note || 'Enable and calibrate A1 to activate.'));
    }

    const factorField = byId('sensor-factor-tds_factor');
    const factor = factorField.value.trim() ? Number(factorField.value) : NaN;
    const tdsTemp = calibratedTemp != null && Number.isFinite(calibratedTemp) ?
      calibratedTemp : snapshot.fallback_temperature_c;
    if (!valid(volts.a3)) {
      byId('sensor-live-tds').textContent = 'TDS voltage unavailable';
    } else {
      const normalized = Math.max(0, Number(volts.a3)) / (1 + 0.02 * (tdsTemp - 25));
      const base = Math.max(0, (133.42 * normalized ** 3 -
        255.86 * normalized ** 2 + 857.39 * normalized) * 0.5);
      byId('sensor-live-tds').textContent =
        Number.isFinite(factor) && factor >= 0.001 && factor <= 10 ?
          (base * factor).toFixed(1) + ' ppm (estimate)' : 'Enter valid TDS multiplier';
    }
  };

  const refreshLive = async () => {
    // Explicitly opened calibration windows should always request a preview,
    // even if the browser temporarily considers the page hidden.
    if (!modal.open || inFlight || captureBusy) return;
    inFlight = true;
    const requestedTab = activeTab;
    const activeChannel = {ph:'a0', temp:'a1', tds:'a3'}[requestedTab];
    try {
      const result = await api('/live?channel=' + activeChannel);
      if (!modal.open || requestedTab !== activeTab) return; // stale tab response
      snapshot = result;
      if (activeChannel === 'a0') {
        const rawPh = Number(result.ph_raw);
        const factor = Number(settings?.ph_factor ?? 1);
        const ph = result.ph_raw == null ? NaN : 7 + (rawPh - 7) * factor;
        if (Number.isFinite(ph) && ph >= 0 && ph <= 14) {
          livePhWindow.push(ph);
          if (livePhWindow.length > 5) livePhWindow.shift();
        } else {
          livePhWindow.length = 0;
        }
      }
      render();
      const errors = snapshot.voltage_errors || {};
      const activeError = errors[activeChannel];
      const dbWarning = snapshot.calibration_db_error ? ' · Calibration DB unavailable' : '';
      byId('sensor-live-updated').textContent = activeError ?
        ('Live ' + activeChannel.toUpperCase() + ' unavailable: ' + activeError + dbWarning) :
        ('Live ' + activeChannel.toUpperCase() + ' voltage · updated ' +
          new Date().toLocaleTimeString() + ' · 0.5 s polling' + dbWarning);
    } catch (error) {
      if (!modal.open || requestedTab !== activeTab) return;
      snapshot = null;
      if (activeChannel === 'a0') livePhWindow.length = 0;
      byId('sensor-live-' + activeChannel).textContent = 'Read failed';
      byId('sensor-voltage-error-' + activeChannel).textContent = error.message;
      byId('sensor-live-updated').textContent =
        'Live ' + activeChannel.toUpperCase() + ' request failed: ' + error.message;
    } finally {
      inFlight = false;
    }
  };

  const describeCapture = (name, record) => {
    const measured = Number(record.voltage);
    const temp = Number(record.temperature_c);
    const ref = Number(record.reference_ph);
    return measured.toFixed(5) + ' V · ' + temp.toFixed(1) +
      '°C (expected pH ' + ref.toFixed(3) + ')';
  };

  const present = async () => {
    settings = await api('');
    byId('sensor-factor-tds_factor').value =
      Number(settings.tds_factor ?? 0.2626).toString();
    const calibrated3 = bufferNames.every(name => settings[name + '_voltage'] != null);
    const legacy = settings.ph7_voltage != null && settings.ph4_voltage != null;
    existing.textContent = 'pH: ' + (calibrated3 ? 'three-buffer calibrated' :
      legacy ? 'legacy 7.00/4.00 calibrated' : 'not calibrated') +
      ' · Temperature offset: ' + Number(settings.temp_offset_c ?? 0).toFixed(2) +
      ' °C · TDS factor: ' + Number(settings.tds_factor ?? 0.2626);
    for (const name of bufferNames) {
      if (captured[name]) continue;
      const volts = settings[name + '_voltage'];
      const temp = settings[name + '_temp_c'];
      byId('sensor-voltage-' + name).textContent = volts == null ?
        'Not captured · — V' :
        'Previously saved: ' + Number(volts).toFixed(5) + ' V' +
        (temp == null ? '' : ' · ' + Number(temp).toFixed(1) + '°C');
    }
    render();
  };

  // A dialog may open through the UI, keyboard, or another caller. Keep the
  // live loop tied to the dialog's open attribute, not the calibration form
  // initialization. A capture UI error must never prevent voltage polling.
  const syncLivePolling = () => {
    if (modal.open) {
      if (timer === null) {
        timer = window.setInterval(refreshLive, 500);
        void refreshLive();
      }
    } else if (timer !== null) {
      window.clearInterval(timer);
      timer = null;
      snapshot = null;
      livePhWindow.length = 0;
    }
  };
  const dialogObserver = new MutationObserver(syncLivePolling);
  dialogObserver.observe(modal, {attributes:true, attributeFilter:['open']});

  open.addEventListener('click', async () => {
    // Start the live loop before touching any of the optional capture widgets.
    if (!modal.open) modal.showModal();
    syncLivePolling();
    try {
      setStatus('');
      captured = {};
      temperatureCaptured = false;
      livePhWindow.length = 0;
      autoBufferTemp.checked = false;
      syncBufferTemperatureMode();
      for (const name of bufferNames) {
        byId('sensor-voltage-' + name).textContent = '— V · waiting for capture';
      }
      byId('sensor-voltage-temp').textContent = 'No reading captured';
      updatePhSave();
      updateTempSave();
      selectTab('tds');
      byId('sensor-live-updated').textContent = 'Connecting to live ADC (A3)…';
      await present();
    } catch (error) {
      setStatus('Calibration controls could not initialize: ' + error.message, 'error');
      // Live voltage polling is intentionally independent and continues.
    }
  });
  modal.addEventListener('close', syncLivePolling);
  byId('sensor-calibration-close').addEventListener('click', () => modal.close());
  byId('sensor-factor-tds_factor').addEventListener('input', render);
  byId('sensor-temp-reference').addEventListener('input', updateTempSave);

  byId('sensor-save-tds').addEventListener('click', async () => {
    const input = byId('sensor-factor-tds_factor');
    const value = Number(input.value);
    if (!input.value.trim() || !Number.isFinite(value) || value < 0.001 || value > 10) {
      input.reportValidity();
      setStatus('Enter a TDS multiplier between 0.001 and 10.');
      return;
    }
    const save = byId('sensor-save-tds');
    save.disabled = true;
    try {
      await api('/factors', {tds_factor: value});
      setStatus('TDS multiplier saved: ' + value + '. New collector samples use this value.', 'saved');
      await present().catch(error => {
        setStatus('Saved, but details could not be refreshed: ' + error.message, 'saved');
      });
    } catch (error) { setStatus('TDS not saved: ' + error.message, 'error'); }
    finally { save.disabled = false; }
  });

  byId('sensor-capture-temp').addEventListener('click', async () => {
    const button = byId('sensor-capture-temp');
    temperatureCaptured = false;
    setCaptureBusy(true);
    setStatus('Capturing stable A1 thermistor voltage…', 'saving');
    try {
      const sample = await api('/sample', {kind:'temp'});
      byId('sensor-voltage-temp').textContent = sample.voltage.toFixed(5) +
        ' V · raw ' + sample.temperature_uncalibrated.toFixed(2) + '°C';
      temperatureCaptured = true;
      setStatus('A1 captured. Enter the glass thermometer temperature, then Save.', 'saved');
    } catch (error) { setStatus('Temperature capture failed: ' + error.message, 'error'); }
    finally { setCaptureBusy(false); refreshLive(); }
  });

  byId('sensor-save-temp').addEventListener('click', async () => {
    const input = byId('sensor-temp-reference');
    const value = Number(input.value);
    if (!input.value.trim() || !Number.isFinite(value) || value < 5 || value > 40) {
      input.reportValidity();
      setStatus('Enter a glass thermometer reference between 5 and 40 °C.');
      return;
    }
    const button = byId('sensor-save-temp'); button.disabled = true;
    try {
      const result = await api('/save', {kind:'temp', reference_c:value});
      temperatureCaptured = false;
      setStatus('Temperature calibration saved · offset ' +
        result.temp_offset_c.toFixed(3) + ' °C.', 'saved');
      await present().catch(error => {
        setStatus('Saved, but details could not be refreshed: ' + error.message, 'saved');
      });
    } catch (error) { setStatus('Temperature not saved: ' + error.message, 'error'); }
    finally { updateTempSave(); }
  });

  for (const name of bufferNames) {
    const button = byId('sensor-capture-' + name);
    button.addEventListener('click', async () => {
      const field = manualBufferTemp;
      const ntc = autoBufferTemp.checked;
      const temp = Number(field.value);
      if (!ntc && (!field.value.trim() || !Number.isFinite(temp) || temp < 0 || temp > 50)) {
        field.reportValidity();
        setStatus('Enter the actual temperature of the buffer solution.');
        return;
      }
      const payload = ntc ?
        {kind:name, temperature_source:'ntc'} :
        {kind:name, temperature_source:'manual', temperature_c:temp};
      setCaptureBusy(true);
      setStatus('Capturing pH ' + bufferLabels[name] + (ntc ?
        ' using calibrated A1 in the same buffer…' :
        ' at ' + temp.toFixed(1) + '°C (manual reference)…'), 'saving');
      try {
        const data = await api('/sample', payload);
        captured[name] = data;
        byId('sensor-voltage-' + name).textContent = describeCapture(name, data) +
          ' · ' + (data.temperature_source === 'ntc' ? 'A1 NTC' : 'manual temperature');
        setStatus('Captured pH ' + bufferLabels[name] + ' at ' +
          Number(data.temperature_c).toFixed(2) + '°C (' +
          (data.temperature_source === 'ntc' ? 'A1' : 'manual') +
          '). Rinse the electrode before the next buffer.', 'saved');
      } catch (error) {
        delete captured[name];
        setStatus('pH ' + bufferLabels[name] + ' capture failed: ' + error.message, 'error');
      } finally {
        setCaptureBusy(false); refreshLive();
      }
    });
  }

  byId('sensor-save-ph').addEventListener('click', async () => {
    if (bufferNames.some(name => !captured[name])) {
      setStatus('Capture all three buffers before saving.');
      return;
    }
    const button = byId('sensor-save-ph'); button.disabled = true;
    setCaptureBusy(true);
    setStatus('Saving three-point pH calibration…', 'saving');
    try {
      const data = await api('/save', {kind:'ph3'});
      captured = {};
      livePhWindow.length = 0;
      setStatus('pH calibration saved: ' +
        '4.01 = ' + data.ph401_voltage.toFixed(5) + ' V; ' +
        '6.86 = ' + data.ph686_voltage.toFixed(5) + ' V; ' +
        '9.18 = ' + data.ph918_voltage.toFixed(5) +
        ' V. The collector will use the new curve on its next sample.', 'saved');
      await present().catch(error => {
        setStatus('Saved, but details could not be refreshed: ' + error.message, 'saved');
      });
      await refreshLive();
    } catch (error) {
      setStatus('pH calibration NOT saved: ' + error.message, 'error');
    } finally {
      setCaptureBusy(false);
    }
  });
})();
