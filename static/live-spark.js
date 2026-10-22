"use strict";
(()=>{
 const colors={temp:'#5eead4',ph:'#93aaff',tds:'#ffc48b'};
 function render(target,raw,color){
   const values=raw.map(x=>x==null||!Number.isFinite(Number(x))?null:Number(x));
   const finite=values.filter(v=>v!==null);
   if(!finite.length){target.textContent='No readings yet';return;}
   const W=1000,H=125,B=124,min=Math.min(...finite),max=Math.max(...finite),pad=Math.max((max-min)*.2,.1);
   const xx=i=>values.length>1?i*W/(values.length-1):W/2;
   const yy=v=>10+(max+pad-v)/(max-min+2*pad)*93;
   let seg=[],segments=[];
   values.forEach((v,i)=>{if(v===null){if(seg.length)segments.push(seg);seg=[]}else seg.push([xx(i),yy(v)])});
   if(seg.length)segments.push(seg);
   const f=p=>p[0].toFixed(2)+' '+p[1].toFixed(2);
   let content='';
   for(const part of segments){
      const line='M '+part.map(f).join(' L ');
      const first=part[0],last=part[part.length-1];
      content+='<path d="'+line+' L '+last[0].toFixed(2)+' '+B+' L '+first[0].toFixed(2)+' '+B+' Z" fill="'+color+'" opacity=".14"/><path d="'+line+'" fill="none" stroke="'+color+'" stroke-width="1.1" vector-effect="non-scaling-stroke" stroke-linecap="round" stroke-linejoin="round"/>';
   }
   target.innerHTML='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" aria-hidden="true">'+content+'</svg>';
 }
 async function refresh(){
  try{
   const response=await fetch('/api/history?period=24h',{cache:'no-store',credentials:'same-origin'});
   if(!response.ok)throw new Error('HTTP '+response.status);
   const body=await response.json();
   for(const [field,color] of Object.entries(colors)){
     const target=document.querySelector('[data-live-field="'+field+'"]');
     if(target)render(target,(body.points||[]).map(p=>p[field]),color);
   }
  }catch(e){console.warn('Live trends unavailable',e);document.querySelectorAll('[data-live-field]').forEach(el=>{if(!el.querySelector('svg'))el.textContent='Trend unavailable'})}
 }
 refresh();setInterval(()=>{if(!document.hidden)refresh()},60000);
})();
