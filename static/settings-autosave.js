"use strict";
(() => {
  const form=document.getElementById('settings-autosave-form');
  const status=document.getElementById('settings-save-status');
  if(!form||!status)return;
  form.addEventListener('submit',event=>event.preventDefault());
  const fields=[...form.querySelectorAll('input[name]:not([type="hidden"]):not([type="checkbox"])')];
  let pending=0;
  let hideTimer=null;
  const say=(message,state)=>{
    if(hideTimer!==null)clearTimeout(hideTimer);
    status.textContent=message;
    status.dataset.state=state;
    status.classList.add('is-visible');
    if(state==='saved'){
      hideTimer=setTimeout(()=>{
        status.classList.remove('is-visible');
        status.dataset.state='idle';
      },3000);
    }
  };
  for(const input of fields){
    input.dataset.saved=input.value;
    input.addEventListener('change',async()=>{
      if(input.disabled||input.value===input.dataset.saved)return;
      const field=input.name,value=input.value;
      if(!input.checkValidity()||!value.trim()){
        say('Invalid '+field.replaceAll('_',' ')+' — not saved','error');
        input.reportValidity();
        return;
      }
      const old=input.dataset.saved;
      input.disabled=true;
      pending++;
      say('Saving '+field.replaceAll('_',' ')+'…','saving');
      try{
        const response=await fetch('/api/options/field',{
          method:'POST',credentials:'same-origin',
          headers:{'Content-Type':'application/json','X-CSRF-Token':window.AQUACORE_CSRF},
          body:JSON.stringify({field,value})
        });
        const data=await response.json().catch(()=>({}));
        if(!response.ok)throw new Error(data.error||'HTTP '+response.status);
        input.dataset.saved=value;
        say('Saved '+field.replaceAll('_',' '),'saved');
      }catch(e){
        input.value=old;
        say('Not saved: '+e.message,'error');
      }finally{
        input.disabled=false;
        pending--;
      }
    });
  }
})();
