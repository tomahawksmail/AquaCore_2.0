"use strict";
(() => {
  const config={RAM_percent:['%',1,'#57dccc'],disk_usage_percent:['%',1,'#90a9ff'],RAM_available:['MB',0,'#76cdfa']};
  function plot(el,series,points,{fixedMax=null,unit='',format=null}={}){
    const W=1000,H=185,L=62,R=16,T=12,B=154;
    const numbers=series.flatMap(item=>points.map(p=>item.get(p))).filter(v=>v!=null&&Number.isFinite(Number(v))).map(Number);
    if(!numbers.length){el.textContent='No history yet';return;}
    let lo=fixedMax===100?0:Math.min(...numbers),hi=fixedMax===100?100:Math.max(...numbers);
    if(fixedMax!==100){
      const gap=Math.max((hi-lo)*.13,hi===lo?Math.max(1,Math.abs(hi)*.03):.1);
      lo=Math.max(0,lo-gap);hi+=gap;
    }
    const steps=fixedMax===100?25:Math.pow(10,Math.floor(Math.log10(Math.max(.001,(hi-lo)/4))));
    const tickStep=fixedMax===100?25:([1,2,2.5,5,10].map(n=>n*steps).find(n=>(hi-lo)/n<=5)||steps*10);
    lo=fixedMax===100?0:Math.floor(lo/tickStep)*tickStep;
    hi=fixedMax===100?100:Math.ceil(hi/tickStep)*tickStep;
    if(hi<=lo)hi=lo+tickStep;
    const x=i=>L+(points.length===1?(W-L-R)/2:i*(W-L-R)/(points.length-1));
    const y=v=>B-(Number(v)-lo)/(hi-lo)*(B-T);
    const txt=v=>format?format(v):(tickStep<1?Number(v.toFixed(2)).toString():Math.round(v).toString());
    let svg='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" aria-hidden="true">';
    const ticks=Math.min(12,Math.round((hi-lo)/tickStep));
    for(let k=0;k<=ticks;k++){
      const value=lo+k*tickStep,py=y(value);
      svg+='<line x1="'+L+'" y1="'+py+'" x2="'+(W-R)+'" y2="'+py+'" stroke="#2a4758" stroke-width=".8"/>';
      svg+='<text x="'+(L-8)+'" y="'+(py+4)+'" text-anchor="end" fill="#9cbdcf" font-size="12">'+txt(value)+'</text>';
    }
    // Horizontal positions represent successive measurements, oldest to latest.
    [[0,'Older'],[1,'Latest']].forEach(([f,label])=>{
      svg+='<text x="'+(L+f*(W-L-R))+'" y="'+(H-6)+'" text-anchor="'+(f?'end':'start')+'" fill="#86acbe" font-size="12">'+label+'</text>';
    });
    for(const item of series){
      let sections=[],section=[];
      points.forEach((p,k)=>{
        const v=item.get(p);
        if(v==null||!Number.isFinite(Number(v))){if(section.length)sections.push(section);section=[];}
        else section.push([x(k),y(v)]);
      });
      if(section.length)sections.push(section);
      for(const part of sections){
        svg+='<path d="M '+part.map(t=>t[0].toFixed(1)+' '+t[1].toFixed(1)).join(' L ')+'" fill="none" stroke="'+item.color+'" stroke-width="1.2" vector-effect="non-scaling-stroke"/>';
      }
      const last=sections.at(-1)?.at(-1);
      if(last)svg+='<circle cx="'+last[0]+'" cy="'+last[1]+'" r="3.2" fill="'+item.color+'" stroke="#102335" stroke-width="1.2"/>';
    }
    el.innerHTML=svg+'</svg>';
  }
  function draw(el,raw,color){
    plot(el,[{color,get:p=>p.value}],raw.map(value=>({value})));
  }
  const coreColors=['#5eead4','#8fa8ff','#ffc48b','#76cdfa'];
  function coreChart(el,points){
    plot(el,[0,1,2,3].map(n=>({color:coreColors[n],get:p=>p['cpus_percent_'+n]})),points,{fixedMax:100});
  }
  const ramSeries=[
    ['RAM_available','Available','#5eead4'],['RAM_percent','Usage %','#f7ad75'],
    ['RAM_used','Used','#8fa8ff'],['RAM_free','Free','#76cdfa'],
    ['RAM_active','Active','#f4d35e'],['RAM_inactive','Inactive','#ce93d8'],
    ['RAM_buffers','Buffers','#6cd2a1'],['RAM_cached','Cached','#ef9e80'],
    ['RAM_shared','Shared','#c3d5e8'],['RAM_slab','Slab','#e2abcb']
  ];
  function drawRamBreakdown(el,points){
    const series=ramSeries.map(([field,label,color])=>({
      color,get:p=>field==='RAM_percent'
        ? (p.RAM_percent==null||p.RAM_total==null?null:Number(p.RAM_total)*Number(p.RAM_percent)/100)
        : p[field]
    }));
    plot(el,series,points);
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
      if(freqValue){
        const latest=points.map(p=>p.scpufreq_cur).filter(v=>v!=null&&Number.isFinite(Number(v))).at(-1);
        if(freqValue){freqValue.textContent=latest==null?'—':String(Math.round(latest));const unit=document.createElement('small');unit.textContent='MHz';freqValue.append(unit);}
      }
      const ramTotalChart=document.getElementById('ram-total-chart');
      const ramTotalValue=document.getElementById('ram-total-value');
      if(ramTotalValue){
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
      const tempChart=document.getElementById('cpu-temp-chart');
      if(tempChart)draw(tempChart,points.map(p=>p.cpu_thermal_cur),'#f7ad75');
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
