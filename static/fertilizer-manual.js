"use strict";
(() => {
  // One-shot switches: never claim a pump is running until the relay worker
  // confirms that it issued the GPIO ON command.
  const byId = id => document.getElementById(id);
  const doseSwitch = byId('fertilizer-dose-now');
  const testSwitch = byId('fertilizer-calibrate-start');
  const saveBtn = byId('fertilizer-calibrate-save');
  const mlInput = byId('fertilizer-ml');
  const timeInput = byId('fertilizer-time');
  const measuredInput = byId('fertilizer-measured-ml');
  const rateLabel = byId('fertilizer-calibration-rate');
  const doseLabel = byId('fertilizer-dose-state');
  const help = byId('fertilizer-manual-help');
  const status = byId('fertilizer-dose-status');
  const wrapper = byId('fertilizer-test-progress');
  const meter = byId('fertilizer-progress-meter');
  const progressLabel = byId('fertilizer-progress-label');
  const progressTime = byId('fertilizer-progress-time');
  if (![doseSwitch,testSwitch,saveBtn,mlInput,timeInput,measuredInput,
        rateLabel,doseLabel,help,status,wrapper,meter,
        progressLabel,progressTime].every(Boolean)) return;

  const readonly = testSwitch.disabled && saveBtn.disabled;
  let calibrated = rateLabel.textContent.includes('Calibrated:');
  let busy = false;
  let coolingUntil = 0;
  let calibrationReady = false;
  let activeRequestId = null;
  let activeKind = '';
  let pollTimer = null;
  let ticker = null;
  let runStartPerf = 0;
  let runElapsed = 0;
  let runDuration = 10;

  const validSavedDose = () => {
    const ml = Number(mlInput.dataset.saved ?? mlInput.value);
    return Number.isFinite(ml) && ml > 0 && ml <= 100;
  };

  function updateUI() {
    const ml = Number(mlInput.dataset.saved ?? mlInput.value);
    const time = timeInput.dataset.saved ?? timeInput.value;
    doseLabel.textContent = calibrated && validSavedDose()
      ? 'Scheduled · ' + (time || '--:--') + ' · ' + ml + ' ml'
      : 'Scheduled · OFF';

    const cooling = Date.now() < coolingUntil;
    const locked = busy || cooling || activeRequestId !== null;
    doseSwitch.disabled = readonly || locked || mlInput.disabled || !calibrated || !validSavedDose();
    testSwitch.disabled = readonly || locked;
    saveBtn.disabled = readonly || busy || !calibrationReady ||
      !measuredInput.value || !measuredInput.checkValidity();

    if (readonly) {
      help.textContent = 'Manual dose requires administrator access.';
    } else if (!calibrated) {
      help.textContent = 'Manual dose disabled — first run the 10-second test, measure the liquid, and save calibration.';
    } else if (!validSavedDose()) {
      help.textContent = 'Manual dose disabled — save a dose greater than 0 ml.';
    } else if (activeRequestId !== null) {
      help.textContent = 'Pump request in progress. Manual dosing is temporarily unavailable.';
    } else if (cooling) {
      help.textContent = 'Pump cooldown — wait two minutes between manual requests.';
    } else {
      help.textContent = 'Manual dose ready — uses the saved ' + ml + ' ml amount.';
    }
  }

  function showProgress(label, percentage, seconds, running) {
    wrapper.hidden = false;
    progressLabel.textContent = label;
    if (percentage === null) {
      meter.removeAttribute('value'); // Indeterminate while queued (not yet running).
      progressTime.textContent = 'Waiting';
    } else {
      meter.value = Math.min(100,Math.max(0,percentage));
      progressTime.textContent = seconds.toFixed(1) + ' / ' + runDuration.toFixed(0) + ' s';
    }
    wrapper.dataset.state = running ? 'running' : 'waiting';
  }

  function tick() {
    const elapsed = Math.max(0,runElapsed + (performance.now()-runStartPerf)/1000);
    const pct = Math.min(99, elapsed/runDuration*100);
    showProgress(elapsed >= runDuration ? 'Pump stop confirmation pending…' : 'Calibration pump running…',
                 pct,Math.min(runDuration,elapsed),true);
  }

  function stopTicker() {
    if (ticker !== null) clearInterval(ticker);
    ticker = null;
  }

  function stopPolling() {
    if (pollTimer !== null) clearInterval(pollTimer);
    pollTimer = null;
    stopTicker();
  }

  async function api(path,payload) {
    const response = await fetch(path,{
      method: payload === undefined ? 'GET' : 'POST',
      credentials:'same-origin',
      cache:'no-store',
      headers: payload === undefined ? {} : {
        'Content-Type':'application/json',
        'X-CSRF-Token':window.AQUACORE_CSRF
      },
      body: payload === undefined ? undefined : JSON.stringify(payload)
    });
    const data = await response.json().catch(()=>({}));
    if (!response.ok) throw new Error(data.error || 'HTTP ' + response.status);
    return data;
  }

  function beginCooldown() {
    coolingUntil = Date.now()+120000;
    setTimeout(updateUI,120100);
  }

  function finishRequest(message,isError) {
    stopPolling();
    activeRequestId = null;
    activeKind = '';
    doseSwitch.checked = false;
    testSwitch.checked = false;
    if (message) status.textContent = message;
    updateUI();
  }

  async function pollStatus(onlyInitial=false) {
    let result;
    try {
      result = await api('/api/fertilizer/status');
    } catch (error) {
      if (!onlyInitial) {
        progressLabel.textContent = 'Status unavailable — check relay logs';
        status.textContent = 'Unable to check pump status: ' + error.message;
      }
      return;
    }
    // On refresh, reconnect only to a current calibration request.
    if (onlyInitial && activeRequestId === null) {
      if (result.kind !== 'calibration' ||
          !['queued','running','completed'].includes(result.state) ||
          result.request_age_seconds > 900) return;
      activeRequestId = result.state === 'completed' ? null : result.request_id;
      activeKind = 'calibration';
    } else if (activeRequestId !== null && result.request_id !== activeRequestId) {
      finishRequest('Another pump request replaced the previous request.');
      return;
    }

    runDuration = Math.max(0.25,Number(result.duration_seconds)||10);
    if (result.kind === 'calibration' && result.state === 'queued') {
      showProgress('Waiting for relay worker to start…',null,0,false);
      calibrationReady = false;
    } else if (result.kind === 'calibration' && result.state === 'running') {
      runElapsed = Math.max(0,Number(result.elapsed_seconds)||0);
      runStartPerf = performance.now();
      if (ticker === null) ticker = setInterval(tick,100);
      tick();
      calibrationReady = false;
    } else if (result.kind === 'calibration' && result.state === 'completed') {
      stopTicker();
      showProgress('10-second test finished — measure the collected liquid',100,runDuration,false);
      wrapper.dataset.state='complete';
      calibrationReady = result.request_age_seconds <= 900 &&
        result.calibration_saved_request_id !== result.request_id;
      finishRequest('Calibration test completed by relay worker. Enter the collected ml and Save.');
    } else if (result.state === 'completed') {
      finishRequest('Manual dose finished (GPIO OFF command recorded).');
    } else if (['skipped','stale','interrupted','failed','unconfirmed'].includes(result.state)) {
      stopTicker();
      if (result.kind==='calibration') {
        wrapper.hidden=false;
        meter.value=0;
        progressTime.textContent='Not completed';
        progressLabel.textContent='Calibration test ' + result.state + ' — not valid';
      }
      calibrationReady=false;
      finishRequest('Pump request ' + result.state + '. No calibration can be saved; inspect relay logs.');
    } else if (activeRequestId !== null && result.kind === 'dose' && result.state === 'running') {
      status.textContent = 'Manual dosing: relay worker issued pump ON command.';
    }
    if (activeRequestId !== null) updateUI();
    if (onlyInitial && activeRequestId !== null) startPolling();
  }

  function startPolling() {
    if (pollTimer === null) pollTimer = setInterval(()=>pollStatus(),700);
    pollStatus();
  }

  async function momentaryRequest(toggle,kind) {
    if (!toggle.checked) return;
    const ml = Number(mlInput.dataset.saved ?? mlInput.value);
    const prompt = kind==='dose'
      ? 'Dispense an EXTRA ' + ml + ' ml of fertilizer now?'
      : 'Direct the pump outlet into a measuring cup OUTSIDE the aquarium. Run a 10-second calibration test?';
    if (!window.confirm(prompt)) {
      toggle.checked=false;
      return;
    }
    busy=true;
    updateUI();
    status.textContent = 'Submitting ' + kind + ' request…';
    try {
      const result = await api(kind==='dose'
        ? '/api/fertilizer/dose'
        : '/api/fertilizer/calibration/start',{});
      activeRequestId=result.request_id;
      activeKind=kind;
      calibrationReady=false;
      beginCooldown();
      if (kind==='calibration') {
        runDuration=10;
        showProgress('Request queued — waiting for relay worker…',null,0,false);
      }
      startPolling();
      status.textContent = (kind==='calibration' ? '10-second calibration test' : 'Manual dose') +
        ' queued. Relay status will update automatically.';
    } catch (error) {
      status.textContent = 'Pump request not accepted: ' + error.message;
    } finally {
      // Timed pulse switch resets to OFF; progress remains visible below.
      toggle.checked=false;
      busy=false;
      updateUI();
    }
  }

  doseSwitch.addEventListener('change',()=>momentaryRequest(doseSwitch,'dose'));
  testSwitch.addEventListener('change',()=>momentaryRequest(testSwitch,'calibration'));
  measuredInput.addEventListener('input',updateUI);
  document.addEventListener('aquacore:setting-saved',event=>{
    if (['fertilizer_time','fertilizer_dose_ml'].includes(event.detail?.field)) {
      setTimeout(updateUI,0);
    }
  });
  document.addEventListener('aquacore:setting-settled',event=>{
    if (['fertilizer_time','fertilizer_dose_ml'].includes(event.detail?.field)) updateUI();
  });

  saveBtn.addEventListener('click',async()=>{
    if (saveBtn.disabled) return;
    if (!measuredInput.checkValidity()) {
      measuredInput.reportValidity();
      return;
    }
    if (!window.confirm('Save pump calibration using ' + measuredInput.value +
          ' ml measured during the completed 10-second test?')) return;
    busy=true;
    updateUI();
    try {
      const result=await api('/api/fertilizer/calibration/finish',{
        measured_ml:measuredInput.value
      });
      calibrated=true;
      calibrationReady=false;
      rateLabel.textContent='Calibrated: ' + Number(result.ml_per_second).toFixed(3) + ' ml/sec';
      status.textContent='Calibration saved. Verify measured ml with a second test.';
    } catch (error) {
      status.textContent='Calibration not saved: ' + error.message;
    } finally {
      busy=false;
      updateUI();
    }
  });
  updateUI();
  pollStatus(true);
})();
