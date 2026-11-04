"use strict";
(() => {
  const doseBtn=document.getElementById('fertilizer-dose-now');
    const testBtn=document.getElementById('fertilizer-calibrate-start');
  const saveBtn=document.getElementById('fertilizer-calibrate-save');
  const measuredInput=document.getElementById('fertilizer-measured-ml');
  const rateLabel=document.getElementById('fertilizer-calibration-rate');
  const status=document.getElementById('fertilizer-dose-status');
  if (!doseBtn || !testBtn || !saveBtn || !measuredInput || !status) return;

  // Jinja renders current flow rate; this UI never assumes an uncalibrated pump.
  let calibrated=rateLabel.textContent.includes('Calibrated:');
  let busy=false, queued=false;
  const mlInput=document.getElementById('fertilizer-ml');
  const refresh=()=>{
    const ml=Number(mlInput.dataset.saved ?? mlInput.value);
    doseBtn.disabled=busy||queued||mlInput.disabled||!calibrated||
      !Number.isFinite(ml)||ml<=0||ml>100;
    testBtn.disabled=busy||testBtn.dataset.readonly==='true';
    saveBtn.disabled=busy||saveBtn.dataset.readonly==='true';
  };
  const api=async path=>{
    const response=await fetch(path,{
      method:'POST',credentials:'same-origin',
      headers:{'X-CSRF-Token':window.AQUACORE_CSRF,'Content-Type':'application/json'},
      body:path.endsWith('/finish')?JSON.stringify({measured_ml:measuredInput.value}):'{}'
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.error||'HTTP '+response.status);
    return data;
  };
  document.addEventListener('aquacore:setting-saved',event=>{
    if(event.detail?.field==='fertilizer_dose_ml')queueMicrotask(refresh);
  });
  doseBtn.addEventListener('click',async()=>{
    if(doseBtn.disabled)return;
    const ml=Number(mlInput.dataset.saved ?? mlInput.value);
    if(!window.confirm('Dose '+ml+' ml now? This is EXTRA fertilizer in addition to the daily schedule.'))return;
    busy=true;refresh();
    status.textContent='Queuing manual fertilizer dose…';
    try{
      const result=await api('/api/fertilizer/dose');
      queued=true;
      status.textContent='Dose requested ('+result.duration_seconds+
        ' seconds of pump runtime). Check relay log to confirm.';
    }catch(err){status.textContent='Dose failed: '+err.message;}
    finally{busy=false;refresh();}
  });
  testBtn.addEventListener('click',async()=>{
    if(testBtn.disabled)return;
    if(!window.confirm('Confirm the fertilizer tube empties into a measuring cup, NOT the aquarium. Run pump for 10 seconds?'))return;
    busy=true;refresh();
    status.textContent='Queuing 10-second calibration test…';
    try{
      await api('/api/fertilizer/calibration/start');
      status.textContent='Calibration requested. Wait for the full 10-second pump run, then measure and enter collected ml. Check relay log.';
    }catch(err){status.textContent='Calibration test failed: '+err.message;}
    finally{busy=false;refresh();}
  });
  saveBtn.addEventListener('click',async()=>{
    if(saveBtn.disabled)return;
    if(!measuredInput.checkValidity()||!measuredInput.value){
      measuredInput.reportValidity();return;
    }
    if(!window.confirm('Save calibration using '+measuredInput.value+' ml collected during a 10-second run?'))return;
    busy=true;refresh();
    try{
      const result=await api('/api/fertilizer/calibration/finish');
      calibrated=true;
      rateLabel.textContent='Calibrated: '+result.ml_per_second.toFixed(3)+' ml/sec';
      status.textContent='Calibration saved. Verify the calculated dose with a separate measuring-cup test.';
    }catch(err){status.textContent='Calibration not saved: '+err.message;}
    finally{busy=false;refresh();}
  });
  refresh();
})();
