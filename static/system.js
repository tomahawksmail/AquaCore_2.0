"use strict";
(() => {
  const config={RAM_percent:['%',1,'#57dccc'],cpu_thermal_cur:['°C',1,'#f7ad75'],disk_usage_percent:['%',1,'#90a9ff'],RAM_available:['MB',0,'#76cdfa']};
  function draw(el,raw,color){
    const data=raw.map(v=>v==null||!Number.isFinite(Number(v))?null:Number(v));
    const valid=data.filter(v=>v!==null);
    if(!valid.length){el.textContent='No history yet';return;}
    const W=1000,H=150,B=149,low=Math.min(...valid),high=Math.max(...valid),pad=Math.max(1,(high-low)*.22);
    const x=i=>data.length===1?W/2:i*W/(data.length-1);
    const y=v=>14+(high+pad-v)/(high-low+2*pad)*104;
    let paths=[],segment=[];
    data.forEach((v,i)=>{if(v===null){if(segment.length){paths.push(segment);segment=[];}}else segment.push([x(i),y(v)]);});
    if(segment.length)paths.push(segment);
    const fixed=p=>p[0].toFixed(2)+' '+p[1].toFixed(2);
    const svg=paths.map(points=>{
      const line='M '+points.map(fixed).join(' L ');
      const first=points[0],last=points[points.length-1];
      const area=line+' L '+last[0].toFixed(2)+' '+B+' L '+first[0].toFixed(2)+' '+B+' Z';
      return '<path d="'+area+'" fill="'+color+'" opacity=".13"/><path d="'+line+'" fill="none" stroke="'+color+'" stroke-width="1.1" vector-effect="non-scaling-stroke" stroke-linecap="round" stroke-linejoin="round"/>';
    }).join('');
    el.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" aria-hidden="true">'+svg+'</svg>';
  }
  const coreColors=['#5eead4','#8fa8ff','#ffc48b','#76cdfa'];
  function coreChart(el,points){
    const fields=[0,1,2,3].map(i=>'cpus_percent_'+i);
    const W=1000,H=155,T=8,B=130;
    const x=i=>points.length<2?W/2:i*W/(points.length-1);
    const y=v=>T+(100-v)/100*(B-T);
    let svg='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" aria-hidden="true">';
    for(const v of [0,25,50,75,100])svg+='<line x1="0" x2="'+W+'" y1="'+y(v)+'" y2="'+y(v)+'" stroke="#2a4758" stroke-width=".7"/>';
    fields.forEach((field,n)=>{
      let segments=[],pointsNow=[];
      points.forEach((p,i)=>{
        const value=p[field];
        if(value==null||!Number.isFinite(Number(value))){if(pointsNow.length)segments.push(pointsNow);pointsNow=[];}
        else pointsNow.push([x(i),y(Math.max(0,Math.min(100,Number(value))))]);
      });
      if(pointsNow.length)segments.push(pointsNow);
      for(const segment of segments)svg+='<path d="M '+segment.map(v=>v[0].toFixed(1)+' '+v[1].toFixed(1)).join(' L ')+'" fill="none" stroke="'+coreColors[n]+'" stroke-width="1.2" vector-effect="non-scaling-stroke"/>';
    });
    el.innerHTML=svg+'</svg>';
  }
  const ramSeries=[
    ['RAM_available','Available','#5eead4'],['RAM_percent','Usage %','#f7ad75'],
    ['RAM_used','Used','#8fa8ff'],['RAM_free','Free','#76cdfa'],
    ['RAM_active','Active','#f4d35e'],['RAM_inactive','Inactive','#ce93d8'],
    ['RAM_buffers','Buffers','#6cd2a1'],['RAM_cached','Cached','#ef9e80'],
    ['RAM_shared','Shared','#c3d5e8'],['RAM_slab','Slab','#e2abcb']
  ];
  function drawRamBreakdown(el,points){
    if(!points.length){el.textContent='No history yet';return;}
    const W=1000,H=155,T=7,B=131;
    const total=Math.max(1,...points.map(p=>Number(p.RAM_total)||0));
    const values=ramSeries.flatMap(([field])=>points.map(p=>field==='RAM_percent'
      ? (p.RAM_percent==null||p.RAM_total==null?null:Number(p.RAM_total)*Number(p.RAM_percent)/100)
      : (p[field]==null?null:Number(p[field])))).filter(v=>v!=null&&Number.isFinite(v));
    if(!values.length){el.textContent='No RAM readings yet';return;}
    const ymax=Math.max(total,...values,1)*1.05;
    const x=i=>points.length<=1?W/2:i*W/(points.length-1);
    const y=v=>B-Math.max(0,v)/ymax*(B-T);
    let svg='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" aria-hidden="true">';
    for(const fraction of [0,.25,.5,.75,1]){
      const pos=B-fraction*(B-T);
      svg+='<line x1="0" y1="'+pos+'" x2="'+W+'" y2="'+pos+'" stroke="#2a4758" stroke-width=".7"/>';
    }
    ramSeries.forEach(([field,label,color])=>{
      let parts=[],segment=[];
      points.forEach((p,i)=>{
        const raw=field==='RAM_percent'
          ? (p.RAM_percent==null||p.RAM_total==null?null:Number(p.RAM_total)*Number(p.RAM_percent)/100)
          : p[field];
        const v=raw==null?NaN:Number(raw);
        if(!Number.isFinite(v)){if(segment.length)parts.push(segment);segment=[];}
        else segment.push([x(i),y(v)]);
      });
      if(segment.length)parts.push(segment);
      for(const part of parts){
        svg+='<path d="M '+part.map(v=>v[0].toFixed(1)+' '+v[1].toFixed(1)).join(' L ')+'" fill="none" stroke="'+color+'" stroke-width="1.1" vector-effect="non-scaling-stroke"/>';
      }
    });
    el.innerHTML=svg+'</svg>';
  }
  function updateRamLegend(points){
    const legend=document.getElementById('ram-breakdown-legend');
    if(!legend)return;
    legend.replaceChildren();
    for(const [field,label,color] of ramSeries){
      const latest=points.map(p=>p[field]).filter(v=>v!=null&&Number.isFinite(Number(v))).at(-1);
      const item=document.createElement('span');item.className='system-ram-key';
      const marker=document.createElement('i');marker.style.backgroundColor=color;item.append(marker);
      item.append(document.createTextNode(label+': '));
      const value=document.createElement('strong');
      value.textContent=latest==null?'—':(field==='RAM_percent'?Number(latest).toFixed(0)+'%':Math.round(latest)+' MB');
      item.append(value);legend.append(item);
    }
  }
  async function refresh(){
    try{
      const response=await fetch('/api/system/history',{cache:'no-store',credentials:'same-origin'});
      if(!response.ok)throw Error('HTTP '+response.status);
      const body=await response.json();
      const points=body.points||[];
      const freq=document.getElementById('cpu-freq-chart');
      const freqValue=document.getElementById('cpu-freq-value');
      if(freq){draw(freq,points.map(p=>p.scpufreq_cur),'#57dccc');
        const latest=points.map(p=>p.scpufreq_cur).filter(v=>v!=null&&Number.isFinite(Number(v))).at(-1);
        if(freqValue){freqValue.textContent=latest==null?'—':String(Math.round(latest));const unit=document.createElement('small');unit.textContent='MHz';freqValue.append(unit);}
      }
      const ramTotalChart=document.getElementById('ram-total-chart');
      const ramTotalValue=document.getElementById('ram-total-value');
      if(ramTotalChart){
        draw(ramTotalChart,points.map(p=>p.RAM_total),'#57dccc');
        const latest=points.map(p=>p.RAM_total).filter(v=>v!=null&&Number.isFinite(Number(v))).at(-1);
        if(ramTotalValue){ramTotalValue.textContent=latest==null?'—':String(Math.round(latest));const unit=document.createElement('small');unit.textContent='MB';ramTotalValue.append(unit);}
      }
      const ramChart=document.getElementById('ram-breakdown-chart');
      if(ramChart){drawRamBreakdown(ramChart,points);updateRamLegend(points);}
      const cpuTemp=document.getElementById('cpu-temp-value');
      if(cpuTemp){
        const temp=points.map(p=>p.cpu_thermal_cur).filter(v=>v!=null&&Number.isFinite(Number(v))).at(-1);
        cpuTemp.textContent=temp==null?'—':Number(temp).toFixed(0);
        const unit=document.createElement('small');unit.textContent='°C';cpuTemp.append(unit);
      }
      const cores=document.getElementById('cpu-cores-chart');
      if(cores){coreChart(cores,points);
        for(let n=0;n<4;n++){const val=points.map(p=>p['cpus_percent_'+n]).filter(v=>v!=null&&Number.isFinite(Number(v))).at(-1);const out=document.getElementById('core-value-'+n);if(out)out.textContent=(val==null?'—':Number(val).toFixed(0))+'%';}
      }
      for(const [field,[unit,precision,color]] of Object.entries(config)){
        const el=document.querySelector('[data-system-field="'+field+'"]'),value=document.getElementById('system-value-'+field);
        if(!el||!value)continue;
        const readings=(body.points||[]).map(p=>p[field]);
        draw(el,readings,color);
        const latest=readings.filter(v=>v!=null&&Number.isFinite(Number(v))).at(-1);
        value.textContent=latest===undefined?'—':Number(latest).toFixed(precision);
        const suffix=document.createElement('small');suffix.textContent=unit;value.appendChild(suffix);
      }
    }catch(e){console.warn('System history failed',e);document.querySelectorAll('[data-system-field]').forEach(el=>{if(!el.querySelector('svg'))el.textContent='History unavailable';});}
  }
  refresh();setInterval(()=>{if(!document.hidden)refresh()},60000);
})();
