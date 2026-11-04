"use strict";
(() => {
  // GPIO command status comes from the relay worker, not the HTTP queue response.
  // Manual ON/OFF is a bounded 30s maximum run; it never promises measured mL.
  const el = id => document.getElementById(id);
  const dialog=el('fertilizer-calibration-dialog');
  const openBtn=el('fertilizer-open-calibration');
  const closeBtn=el('fertilizer-dialog-close');
  const startBtn=el('fertilizer-calibrate-start');
  const saveBtn=el('fertilizer-calibrate-save');
  const secondsInput=el('fertilizer-calibration-seconds');
  const measuredInput=el('fertilizer-measured-ml');
  const rateLabel=el('fertilizer-calibration-rate');
  const message=el('fertilizer-dose-status');
  const progress=el('fertilizer-test-progress');
  const progressLabel=el('fertilizer-progress-label');
  const progressTime=el('fertilizer-progress-time');
  const meter=el('fertilizer-progress-meter');
  const manual=el('fertilizer-dose-now');
  const mlInput=el('fertilizer-ml');
  const timeInput=el('fertilizer-time');
  const doseLabel=el('fertilizer-dose-state');
  if (![dialog,openBtn,closeBtn,startBtn,saveBtn,secondsInput,measuredInput,
         rateLabel,message,progress,progressLabel,progressTime,meter,
         manual,mlInput,timeInput,doseLabel].every(Boolean)) return;

  const readonly=secondsInput.disabled;
  let calibrated=rateLabel.textContent.includes('Calibrated:');
  let busy=false, stopping=false;
  let activeId=null, activeKind='';
  let calibrationReady=false, runSeconds=10, elapsedBase=0, elapsedAt=0;
  let cooldownUntil=0, cooldownTimer=null, pollTimer=null, tickTimer=null;
  let notice='', noticeTimer=null, inFlight=false;

  const valueMl=()=>Number(mlInput.dataset.saved ?? mlInput.value);
  const doseValid=()=>Number.isFinite(valueMl()) && valueMl()>0 && valueMl()<=100;

  function setNotice(value) {
    notice=value;
    if(noticeTimer!==null)clearTimeout(noticeTimer);
    if(value)noticeTimer=setTimeout(()=>{notice='';updateUI();},7000);
    updateUI();
  }
  function updateUI() {
    const time=timeInput.dataset.saved ?? timeInput.value;
    const schedule=!calibrated?'Auto dose needs calibration · Manual pump available':
      !doseValid()?'Scheduled · OFF':
      'Scheduled · '+(time||'--:--')+' · '+valueMl()+' ml';
    doseLabel.textContent=notice || schedule;
    const manualActive=activeId!==null && activeKind==='manual';
    const cooling=Date.now()<cooldownUntil;
    manual.checked=manualActive && !stopping;
    // OFF must remain possible even during cooldown while the manual pump runs.
    manual.disabled=readonly || busy ||
      (!manualActive && (cooling || activeId!==null));
    manual.title=readonly?'Admin access required':
      manualActive?'Switch OFF to stop; automatic cutoff at 30 seconds':
      cooling?'Wait for the two-minute pump cooldown':
      'Manually run pump (uncalibrated volume, maximum 30 seconds)';
    secondsInput.disabled=readonly || busy ||
      (activeId!==null && activeKind==='calibration');
    startBtn.disabled=readonly || busy || activeId!==null || cooling ||
      !secondsInput.checkValidity() || !secondsInput.value;
    saveBtn.disabled=readonly || busy || !calibrationReady ||
      !measuredInput.value || !measuredInput.checkValidity();
  }
  function cooldown(seconds) {
    cooldownUntil=Date.now()+Math.max(0,seconds)*1000;
    if(cooldownTimer!==null)clearTimeout(cooldownTimer);
    cooldownTimer=setTimeout(updateUI,Math.max(0,seconds)*1000+150);
  }
  async function api(path,payload) {
    const response=await fetch(path,{
      method:payload===undefined?'GET':'POST',cache:'no-store',credentials:'same-origin',
      headers:payload===undefined?{}:{
        'Content-Type':'application/json',
        'X-CSRF-Token':window.AQUACORE_CSRF
      },
      body:payload===undefined?undefined:JSON.stringify(payload)
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.error || 'HTTP '+response.status);
    return data;
  }
  function showProgress(label,pct,seconds) {
    progress.hidden=false;
    progressLabel.textContent=label;
    if(pct===null) {
      meter.removeAttribute('value'); // Indeterminate while queued.
      progressTime.textContent='Waiting';
    }else{
      meter.value=Math.max(0,Math.min(100,pct));
      progressTime.textContent=Math.min(runSeconds,seconds).toFixed(1)+' / '+
        runSeconds.toFixed(0)+' s';
    }
  }
  function stopTick() {
    if(tickTimer!==null)clearInterval(tickTimer);
    tickTimer=null;
  }
  function tick() {
    const secs=elapsedBase+(performance.now()-elapsedAt)/1000;
    showProgress(secs>=runSeconds?'Waiting for relay OFF confirmation…':
      'Calibration running…',Math.min(99,100*secs/runSeconds),secs);
  }
  function startPolling() {
    if(pollTimer===null)pollTimer=setInterval(()=>readStatus(false),600);
  }
  function stopPolling() {
    if(pollTimer!==null)clearInterval(pollTimer);
    pollTimer=null;
    stopTick();
  }
  function finishActive() {
    activeId=null;
    activeKind='';
    stopping=false;
    stopPolling();
    updateUI();
  }

  async function readStatus(reconnect) {
    if(inFlight)return;
    inFlight=true;
    let data;
    try {
      data=await api('/api/fertilizer/status');
    }catch(error){
      if(activeId!==null || dialog.open){
        message.textContent='Cannot read relay status: '+error.message+
          '. Check aquacore-relays.service.';
      }
      inFlight=false;
      return;
    }
    inFlight=false;
    if(data.request_id>0 && data.request_age_seconds>=0 &&
       data.request_age_seconds<120)cooldown(120-data.request_age_seconds);

    if(reconnect && activeId===null) {
      if(data.kind==='manual' && ['queued','running','stop_requested'].includes(data.state)){
        activeId=data.request_id;
        activeKind='manual';
        stopping=data.state==='stop_requested';
      }else if(data.kind==='calibration' && data.request_age_seconds<=900){
        if(['queued','running'].includes(data.state)){
          activeId=data.request_id;activeKind='calibration';
        }else if(data.state==='completed' &&
                 data.calibration_saved_request_id!==data.request_id){
          calibrationReady=true;
        }
      }
    }
    if(activeId!==null && data.request_id!==activeId){
      message.textContent='Another pump request replaced this one.';
      calibrationReady=false;
      finishActive();
      return;
    }
    if(activeId===null && !reconnect)return;
    if(data.kind==='calibration'){
      runSeconds=Math.max(2,Number(data.duration_seconds)||10);
      if(activeId!==null || calibrationReady)
        secondsInput.value=String(runSeconds);
    }
    if(data.kind==='calibration' && data.state==='queued'){
      calibrationReady=false;
      stopTick();
      showProgress('Waiting for relay worker to start…',null,0);
      message.textContent='Request queued. If it expires, inspect the relay service logs.';
    }else if(data.kind==='calibration' && data.state==='running'){
      calibrationReady=false;
      elapsedBase=Math.max(0,Number(data.elapsed_seconds)||0);
      elapsedAt=performance.now();
      if(tickTimer===null)tickTimer=setInterval(tick,100);
      tick();
      message.textContent='Calibration is running. Keep the outlet in the measuring cup.';
    }else if(data.kind==='calibration' && data.state==='completed'){
      stopTick();
      showProgress('Test finished — measure the collected volume',100,runSeconds);
      calibrationReady=data.request_age_seconds<=900 &&
        data.calibration_saved_request_id!==data.request_id;
      message.textContent=calibrationReady
        ? 'Enter the collected ml and click Save calibration.'
        : 'This test was already saved or has expired. Start a new test.';
      if(activeKind==='calibration')finishActive();
    }else if(data.kind==='calibration' &&
             ['stale','skipped','interrupted','failed','unconfirmed'].includes(data.state)){
      stopTick();
      showProgress('Test '+data.state+' — pump completion not confirmed',0,0);
      calibrationReady=false;
      message.textContent='Calibration cannot be saved: relay worker did not confirm a finished test. Check its status and logs.';
      if(activeKind==='calibration')finishActive();
    }else if(data.kind==='manual' && ['queued','running','stop_requested'].includes(data.state)){
      stopping=data.state==='stop_requested';
      setNotice(stopping?'Manual pump stopping…':
        data.state==='queued'?'Manual pump queued…':'Manual pump ON (max 30s)');
    }else if(data.kind==='manual' &&
             ['completed','stopped','skipped','interrupted','failed','stale','unconfirmed'].includes(data.state)){
      setNotice(data.state==='completed'||data.state==='stopped' ?
        'Manual pump OFF' : 'Manual pump '+data.state+' — check relay logs');
      if(activeKind==='manual')finishActive();
    }
    updateUI();
    if(reconnect && activeId!==null)startPolling();
  }

  function openModal() {
    if(!dialog.open)dialog.showModal();
    if(activeId===null && !calibrationReady) {
      progress.hidden=true;
      message.textContent='Select the test duration. Measure liquid in a cup outside the aquarium.';
    }
    readStatus(true);
    updateUI();
  }
  openBtn.addEventListener('click',openModal);
  closeBtn.addEventListener('click',()=>dialog.close());
  secondsInput.addEventListener('input',updateUI);
  measuredInput.addEventListener('input',updateUI);

  startBtn.addEventListener('click',async()=>{
    if(startBtn.disabled)return;
    const secs=Number(secondsInput.value);
    if(!Number.isInteger(secs)||secs<2||secs>60){
      secondsInput.reportValidity();return;
    }
    if(!window.confirm('Pump outlet in a measuring cup OUTSIDE the aquarium? Run for '+secs+' seconds?'))return;
    busy=true;calibrationReady=false;progress.hidden=true;updateUI();
    try{
      const result=await api('/api/fertilizer/calibration/start',{duration_seconds:secs});
      activeId=result.request_id;
      activeKind='calibration';
      runSeconds=Number(result.duration_seconds);
      cooldown(120);
      showProgress('Waiting for relay worker to start…',null,0);
      message.textContent='Test queued. Progress starts after relay ON is recorded.';
      startPolling();
      readStatus(false);
    }catch(error){
      message.textContent='Test rejected: '+error.message;
    }finally{busy=false;updateUI();}
  });

  saveBtn.addEventListener('click',async()=>{
    if(saveBtn.disabled)return;
    if(!measuredInput.checkValidity()){measuredInput.reportValidity();return;}
    if(!window.confirm('Save '+measuredInput.value+' ml from the completed '+runSeconds+'-second test?'))return;
    busy=true;updateUI();
    try{
      const data=await api('/api/fertilizer/calibration/finish',{measured_ml:measuredInput.value});
      calibrated=true;calibrationReady=false;
      rateLabel.textContent='Calibrated: '+Number(data.ml_per_second).toFixed(3)+' ml/sec';
      message.textContent='Calibration saved ('+Number(data.ml_per_second).toFixed(3)+
        ' ml/sec). Verify delivery with a second water test.';
      progressLabel.textContent='Calibration saved';
    }catch(error){
      message.textContent='Cannot save calibration: '+error.message;
    }finally{busy=false;updateUI();}
  });

  manual.addEventListener('change',async()=>{
    if(readonly){manual.checked=false;return;}
    if(manual.checked){
      if(!window.confirm('Manually run the fertilizer pump? It will turn OFF when you switch it OFF, or after 30 seconds maximum. This does NOT measure ml. Use water first.')){
        manual.checked=false;return;
      }
      busy=true;updateUI();
      try{
        const data=await api('/api/fertilizer/manual/start',{});
        activeId=data.request_id;activeKind='manual';stopping=false;
        cooldown(120);
        setNotice('Manual pump queued…');
        startPolling();
        readStatus(false);
      }catch(error){
        setNotice('Manual pump rejected: '+error.message);
        manual.checked=false;
      }finally{busy=false;updateUI();}
    }else if(activeId!==null && activeKind==='manual'){
      stopping=true;busy=true;updateUI();
      try{
        await api('/api/fertilizer/manual/stop',{});
        setNotice('Manual pump OFF requested — awaiting relay confirmation…');
        readStatus(false);
      }catch(error){
        setNotice('OFF request failed: '+error.message+'; automatic cutoff remains 30s.');
      }finally{busy=false;updateUI();}
    }
  });

  document.addEventListener('aquacore:setting-saved',e=>{
    if(['fertilizer_time','fertilizer_dose_ml'].includes(e.detail?.field)){
      setTimeout(updateUI,0);
    }
  });
  document.addEventListener('aquacore:setting-settled',e=>{
    if(['fertilizer_time','fertilizer_dose_ml'].includes(e.detail?.field))
      setTimeout(updateUI,0);
  });
  updateUI();
  readStatus(true); // Restore an active manual run or pending calibration after reload.
})();
