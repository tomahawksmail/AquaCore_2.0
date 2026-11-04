"use strict";
(() => {
  // The dialog displays relay-worker *command* status. It does not measure flow.
  // Manual dosing and calibration are one-shot requests, never latching switches.
  const id = name => document.getElementById(name);
  const openBtn=id('fertilizer-open-calibration');
  const dialog=id('fertilizer-calibration-dialog');
  const closeBtn=id('fertilizer-dialog-close');
  const testBtn=id('fertilizer-calibrate-start');
  const saveBtn=id('fertilizer-calibrate-save');
  const durationInput=id('fertilizer-calibration-seconds');
  const measuredInput=id('fertilizer-measured-ml');
  const rateLabel=id('fertilizer-calibration-rate');
  const status=id('fertilizer-dose-status');
  const progress=id('fertilizer-test-progress');
  const progressLabel=id('fertilizer-progress-label');
  const progressTime=id('fertilizer-progress-time');
  const meter=id('fertilizer-progress-meter');
  const manual=id('fertilizer-dose-now');
  const mlInput=id('fertilizer-ml');
  const timeInput=id('fertilizer-time');
  const doseLabel=id('fertilizer-dose-state');
  if (![openBtn,dialog,closeBtn,testBtn,saveBtn,durationInput,measuredInput,
        rateLabel,status,progress,progressLabel,progressTime,meter,
        manual,mlInput,timeInput,doseLabel].every(Boolean)) return;

  const readonly=durationInput.disabled;
  let calibrated=rateLabel.textContent.includes('Calibrated:');
  let busy=false;
  let cooldownUntil=0;
  let activeId=null;
  let activeKind=null;
  let completedAvailable=false;
  let pollInterval=null;
  let tickInterval=null;
  let progressStarted=0,progressElapsed=0,runSeconds=10;
  let doseMessage='';
  let lastResponse=null;

  function validDose() {
    const saved=Number(mlInput.dataset.saved ?? mlInput.value);
    return Number.isFinite(saved) && saved>0 && saved<=100;
  }
  function doseValue() {
    return Number(mlInput.dataset.saved ?? mlInput.value);
  }
  function updateControls() {
    const dose=doseValue();
    const time=timeInput.dataset.saved ?? timeInput.value;
    let label;
    if (!calibrated) label='Calibration required';
    else if (!validDose()) label='Scheduled · OFF';
    else label='Scheduled · ' + (time || '--:--') + ' · ' + dose + ' ml';
    doseLabel.textContent=doseMessage || label;
    const locked=busy || activeId !== null || Date.now()<cooldownUntil;
    manual.disabled=readonly || locked || mlInput.disabled || !calibrated || !validDose();
    if (manual.disabled) {
      manual.title=readonly?'Admin access required':
        !calibrated?'Save pump calibration first':
        !validDose()?'Set a nonzero daily dose in ml':
        Date.now()<cooldownUntil?'Wait for the 2-minute pump request cooldown':
        'Wait for the pump request to finish';
    } else manual.title='Dose ' + dose + ' ml now';
    testBtn.disabled=readonly || locked || !durationInput.checkValidity();
    durationInput.disabled=readonly || busy || activeId !== null;
    saveBtn.disabled=readonly || busy || !completedAvailable ||
      !measuredInput.value || !measuredInput.checkValidity();
  }
  function showMessage(message) {
    status.textContent=message;
  }
  function setDoseMessage(message) {
    doseMessage=message;
    updateControls();
  }
  async function request(path,payload) {
    const response=await fetch(path,{
      method:payload===undefined?'GET':'POST',
      credentials:'same-origin',cache:'no-store',
      headers:payload===undefined?{}:{
        'Content-Type':'application/json','X-CSRF-Token':window.AQUACORE_CSRF},
      body:payload===undefined?undefined:JSON.stringify(payload)
    });
    const result=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(result.error || 'HTTP ' + response.status);
    return result;
  }
  function haltTicker() {
    if(tickInterval!==null)clearInterval(tickInterval);
    tickInterval=null;
  }
  function haltPoll() {
    if(pollInterval!==null)clearInterval(pollInterval);
    pollInterval=null;
    haltTicker();
  }
  function drawProgress(message,value,elapsed) {
    progress.hidden=false;
    progressLabel.textContent=message;
    if(value===null){
      meter.removeAttribute('value'); // Queued does not imply pump ON.
      progressTime.textContent='Waiting';
    }else{
      meter.value=Math.max(0,Math.min(100,value));
      progressTime.textContent=Math.min(elapsed,runSeconds).toFixed(1)+' / '+runSeconds.toFixed(0)+' s';
    }
  }
  function tick() {
    const elapsed=Math.max(0,progressElapsed+(performance.now()-progressStarted)/1000);
    drawProgress(elapsed>=runSeconds?'Waiting for relay OFF confirmation…':
      'Test running…',Math.min(99,100*elapsed/runSeconds),elapsed);
  }
  function endRequest(message) {
    activeId=null;
    activeKind=null;
    manual.checked=false;
    haltPoll();
    if(message) showMessage(message);
    updateControls();
  }
  async function checkStatus(initial=false) {
    let data;
    try{
      data=await request('/api/fertilizer/status');
    }catch(error){
      if(!initial)showMessage('Pump status unavailable: '+error.message);
      return;
    }
    lastResponse=data;
    if(data.request_id>0 && data.request_age_seconds<120){
      cooldownUntil=Date.now()+Math.max(0,120-data.request_age_seconds)*1000;
    }
    // When opening after a refresh, show only an active or completed unsaved
    // calibration. Old stale/failed requests do not populate the dialog.
    if(initial && activeId===null){
      if(data.kind!=='calibration' || data.request_age_seconds>900)return;
      if(data.state==='completed' &&
         data.calibration_saved_request_id!==data.request_id){
        completedAvailable=true;
      }else if(['queued','running'].includes(data.state)){
        activeId=data.request_id;
        activeKind='calibration';
      }else return;
    }else if(activeId!==null && data.request_id!==activeId){
      completedAvailable=false;
      endRequest('Another pump request replaced this test.');
      return;
    }else if(activeId===null && !initial){
      return;
    }
    runSeconds=Math.max(2,Number(data.duration_seconds)||10);
    if(data.kind==='calibration')durationInput.value=String(runSeconds);
    if(data.state==='queued'){
      drawProgress('Request queued — waiting for relay worker…',null,0);
      completedAvailable=false;
    }else if(data.state==='running'){
      if(data.kind==='calibration'){
        progressElapsed=Math.max(0,Number(data.elapsed_seconds)||0);
        progressStarted=performance.now();
        if(tickInterval===null)tickInterval=setInterval(tick,100);
        tick();
      }else setDoseMessage('Manual pump running…');
    }else if(data.state==='completed'){
      haltTicker();
      if(data.kind==='calibration'){
        drawProgress('Test completed — measure collected volume',100,runSeconds);
        completedAvailable=data.request_age_seconds<=900 &&
          data.calibration_saved_request_id!==data.request_id;
        if(completedAvailable){
          showMessage('Enter the measured ml and press Save calibration.');
        }else showMessage('This calibration test was already saved or has expired.');
      }else setDoseMessage('Manual pump stopped; relay OFF command recorded.');
      endRequest(null);
    }else if(['stale','skipped','interrupted','failed','unconfirmed'].includes(data.state)){
      completedAvailable=false;
      haltTicker();
      if(data.kind==='calibration'){
        drawProgress('Test not completed ('+data.state+') — check relay service',0,0);
      }else setDoseMessage('Manual pump request '+data.state+'.');
      endRequest('Pump request '+data.state+'. Check the relay worker logs before retrying.');
    }
    updateControls();
    if(initial && activeId!==null)startPolling();
  }
  function startPolling() {
    if(pollInterval===null)pollInterval=setInterval(()=>checkStatus(),750);
    checkStatus();
  }
  function openDialog() {
    if(!dialog.open)dialog.showModal();
    if(activeId===null && !completedAvailable) {
      progress.hidden=true;
      showMessage('Choose test duration, collect water in a measuring cup, then save the measured volume.');
    }
    checkStatus(true);
    updateControls();
  }
  openBtn.addEventListener('click',openDialog);
  closeBtn.addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{ /* Closing never stops an active hardware pulse. */ });
  durationInput.addEventListener('input',updateControls);
  measuredInput.addEventListener('input',updateControls);

  testBtn.addEventListener('click',async()=>{
    if(testBtn.disabled)return;
    const seconds=Number(durationInput.value);
    if(!Number.isInteger(seconds)||seconds<2||seconds>60){
      durationInput.reportValidity();return;
    }
    if(!window.confirm('Direct the tube into a measuring cup OUTSIDE the aquarium. Run the pump for '+seconds+' seconds?'))return;
    busy=true;
    completedAvailable=false;
    progress.hidden=true;
    updateControls();
    try{
      const data=await request('/api/fertilizer/calibration/start',{duration_seconds:seconds});
      activeId=data.request_id;
      activeKind='calibration';
      runSeconds=data.duration_seconds;
      cooldownUntil=Date.now()+120000;
      drawProgress('Waiting for relay worker…',null,0);
      showMessage('Test queued. The progress bar starts only after the relay worker confirms GPIO ON.');
      startPolling();
    }catch(error){
      showMessage('Test request rejected: '+error.message);
    }finally{
      busy=false;
      updateControls();
    }
  });

  saveBtn.addEventListener('click',async()=>{
    if(saveBtn.disabled)return;
    if(!measuredInput.checkValidity()){measuredInput.reportValidity();return;}
    if(!window.confirm('Save calibration using '+measuredInput.value+' ml from the completed '+runSeconds+'-second test?'))return;
    busy=true;
    updateControls();
    try{
      const data=await request('/api/fertilizer/calibration/finish',{
        measured_ml:measuredInput.value
      });
      calibrated=true;
      completedAvailable=false;
      rateLabel.textContent='Calibrated: '+Number(data.ml_per_second).toFixed(3)+' ml/sec';
      showMessage('Calibration saved ('+Number(data.ml_per_second).toFixed(3)+
        ' ml/sec). Check a new test volume before connecting to the aquarium.');
    }catch(error){
      showMessage('Calibration not saved: '+error.message);
    }finally{
      busy=false;updateControls();
    }
  });

  manual.addEventListener('change',async()=>{
    if(!manual.checked)return;
    const dose=doseValue();
    if(!window.confirm('Dispense an EXTRA '+dose+' ml now? This does not replace the scheduled dose.')){
      manual.checked=false;return;
    }
    busy=true;updateControls();
    setDoseMessage('Requesting '+dose+' ml…');
    try{
      const data=await request('/api/fertilizer/dose',{});
      activeId=data.request_id;
      activeKind='dose';
      cooldownUntil=Date.now()+120000;
      setDoseMessage('Manual '+dose+' ml dose queued…');
      startPolling();
    }catch(error){
      setDoseMessage('Manual dose rejected: '+error.message);
    }finally{
      manual.checked=false;
      busy=false;
      updateControls();
    }
  });
  document.addEventListener('aquacore:setting-saved',event=>{
    if(['fertilizer_time','fertilizer_dose_ml'].includes(event.detail?.field)){
      doseMessage='';
      queueMicrotask(updateControls);
    }
  });
  document.addEventListener('aquacore:setting-settled',event=>{
    if(['fertilizer_time','fertilizer_dose_ml'].includes(event.detail?.field)){
      setTimeout(updateControls,0);
    }
  });
  updateControls();
})();
