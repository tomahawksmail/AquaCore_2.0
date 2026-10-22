"use strict";
(() => {
  const fields=['RAM_percent','cpu_thermal_cur','disk_usage_percent','RAM_available'];
  const colors={RAM_percent:'#5eead4',cpu_thermal_cur:'#f6ad72',disk_usage_percent:'#97aeff',RAM_available:'#70d1fb'};
  function draw(el,values,color) {
    const data=values.map(v=>v==null?null:Number(v));
    const valid=data.filter(v=>Number.isFinite(v));
    if(!valid.length){el.textContent='No stored readings';return;}
    const w=720,h=190,left=44,right=12,top=13,bottom=27,innerW=w-left-right,innerH=h-top-bottom;
    let min=Math.min(...valid),max=Math.max(...valid);
    const spread=Math.max(1,(max-min)*.12);
    min-=spread;max+=spread;
    const px=i=>left+(data.length===1?innerW/2:i*innerW/(data.length-1));
    const py=v=>top+(max-v)/(max-min)*innerH;
    const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
    let path='',open=false;
    data.forEach((v,i)=>{if(v==null||!Number.isFinite(v)){open=false;return}path+=(open?' L ':' M ')+px(i).toFixed(1)+' '+py(v).toFixed(1);open=true;});
    const grid=[0,.5,1].map(f=>{const y=top+f*innerH;const tick=(max-f*(max-min)).toFixed(1);return '<line x1="'+left+'" y1="'+y+'" x2="'+(w-right)+'" y2="'+y+'" stroke="#28485a" stroke-width="1"/><text x="'+(left-9)+'" y="'+(y+4)+'" text-anchor="end" fill="#86b1c4" font-size="12">'+esc(tick)+'</text>';}).join('');
    el.innerHTML='<svg viewBox="0 0 '+w+' '+h+'" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'+grid+'<path d="'+path+'" fill="none" stroke="'+color+'" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/><text x="'+left+'" y="'+(h-4)+'" fill="#86b1c4" font-size="12">Older</text><text x="'+(w-right)+'" y="'+(h-4)+'" text-anchor="end" fill="#86b1c4" font-size="12">Latest</text></svg>';
  }
  async function refresh(){
    try{
      const response=await fetch('/api/system/history',{cache:'no-store',credentials:'same-origin'});
      if(!response.ok)throw Error('HTTP '+response.status);
      const data=await response.json();
      for(const field of fields){
        const panel=document.querySelector('[data-system-field="'+field+'"]');
        const value=document.getElementById('system-value-'+field);
        if(!panel||!value)continue;
        const readings=(data.points||[]).map(p=>p[field]);
        draw(panel,readings,colors[field]);
        const valid=readings.filter(v=>v!==null&&v!==undefined&&Number.isFinite(Number(v)));
        const current=valid.at(-1);
        const units={RAM_percent:'%',cpu_thermal_cur:'°C',disk_usage_percent:'%',RAM_available:'MB'};
        const precision=field==='RAM_available'?0:1;
        const out=current===undefined?'—':Number(current).toFixed(precision);
        value.textContent=out+' ';
        const unit=document.createElement('span');unit.textContent=units[field];value.appendChild(unit);
      }
    }catch(err){console.warn('System metrics refresh failed',err);
      document.querySelectorAll('[data-system-field]').forEach(el=>{if(!el.querySelector('svg'))el.textContent='History temporarily unavailable';});}
  }
  refresh();
  setInterval(()=>{if(!document.hidden)refresh()},60000);
})();
