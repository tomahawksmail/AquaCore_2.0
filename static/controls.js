"use strict";
function showState(field, data) {
  const el=document.getElementById('state-'+field);
  if(!el) return;
  const label=data.mode==='Manual' ? 'Manual until '+(data.until?.slice(11,16)||'?') :
    'Scheduled · '+(data.enabled?'ON':'OFF');
  el.textContent=label;
}
document.querySelectorAll('input[data-field]').forEach(input=>{
  input.addEventListener('change',async()=>{
    const desired=input.checked, field=input.dataset.field, row=input.closest('.control-row');
    input.disabled=true;row.dataset.pending='true';
    const label=document.getElementById('state-'+field);
    label.textContent='Saving…';
    try {
      const r=await fetch('/api/equipment/'+encodeURIComponent(field),{method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json','X-CSRF-Token':window.AQUACORE_CSRF},
        body:JSON.stringify({enabled:desired})});
      if(!r.ok){let msg='HTTP '+r.status;try{const err=await r.json();msg=err.error||err.description||msg;}catch{}throw new Error(msg)}
      const d=await r.json();input.checked=d.enabled;showState(field,d);
    }catch(err){input.checked=!desired;label.textContent='Not saved: '+err.message;console.error(err)}
    finally{row.dataset.pending='false';if(input.dataset.readonly!=='true')input.disabled=false}
  });
});
async function refreshEquipment(){
  try{const r=await fetch('/api/equipment',{cache:'no-store',credentials:'same-origin'});if(!r.ok)return;
    const data=await r.json();document.querySelectorAll('input[data-field]').forEach(input=>{
      if(input.closest('.control-row').dataset.pending==='true')return;
      const d=data[input.dataset.field];if(!d)return;input.checked=d.enabled;showState(input.dataset.field,d);
    });
  }catch(err){console.warn('Equipment refresh failed',err)}
}
setInterval(refreshEquipment,15000);
