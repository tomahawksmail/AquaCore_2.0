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
    const times=points.map(p=>{
      if(!p.timestamp)return NaN;
      const ms=Date.parse(String(p.timestamp).replace(' ','T'));
      return Number.isFinite(ms)?ms:NaN;
    });
    const timed=times.length>1&&times.every(Number.isFinite)&&times.at(-1)>times[0];
    const x=i=>L+(timed?(times[i]-times[0])/(times.at(-1)-times[0])*(W-L-R):(points.length===1?(W-L-R)/2:i*(W-L-R)/(points.length-1)));

    const y=v=>B-(Number(v)-lo)/(hi-lo)*(B-T);
    const txt=v=>format?format(v):(tickStep<1?Number(v.toFixed(2)).toString():Math.round(v).toString());
    let svg='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" aria-hidden="true">';
    const ticks=Math.min(12,Math.round((hi-lo)/tickStep));
    for(let k=0;k<=ticks;k++){
      const value=lo+k*tickStep,py=y(value);
      svg+='<line x1="'+L+'" y1="'+py+'" x2="'+(W-R)+'" y2="'+py+'" stroke="#2a4758" stroke-width=".8"/>';
      svg+='<text x="'+(L-8)+'" y="'+(py+4)+'" text-anchor="end" fill="#9cbdcf" font-size="12">'+txt(value)+'</text>';
    }
    // Clock-time ticks at 3-hour boundaries, matched to actual measurement times.
    if(timed){
      const hour=60*60*1000,step=3*hour;
      const first=Math.ceil(times[0]/step)*step;
      for(let t=first;t<=times.at(-1);t+=step){
        const px=L+(t-times[0])/(times.at(-1)-times[0])*(W-L-R);
        const d=new Date(t);
        const label=String(d.getHours()).padStart(2,'0')+':00';
        svg+='<line x1="'+px+'" y1="'+T+'" x2="'+px+'" y2="'+B+'" stroke="#284354" stroke-width=".7"/>';
        svg+='<text x="'+px+'" y="'+(H-6)+'" text-anchor="middle" fill="#86acbe" font-size="12">'+label+'</text>';
      }
    }else{
      [[0,'Older'],[1,'Latest']].forEach(([f,label])=>{
        svg+='<text x="'+(L+f*(W-L-R))+'" y="'+(H-6)+'" text-anchor="'+(f?'end':'start')+'" fill="#86acbe" font-size="12">'+label+'</text>';
      });
    }
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
  function draw(el,points,field,color){
    plot(el,[{color,get:p=>p[field]}],points);
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
  const miniColors=['#5eead4','#8fa8ff','#ffc48b','#ce93d8'];
  function drawMiniSeries(el,points,fields){
    const W=360,H=76,P=4;
    let svg='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" aria-hidden="true">';
    for(const y of [19,38,57])svg+='<line x1="0" y1="'+y+'" x2="'+W+'" y2="'+y+'" stroke="#2a4758" stroke-width=".7"/>';
    let any=false;
    fields.forEach((field,index)=>{
      const values=points.map(p=>p[field]==null?null:Number(p[field]));
      const good=values.filter(v=>v!=null&&Number.isFinite(v));
      if(!good.length)return;
      any=true;
      const min=Math.min(...good),max=Math.max(...good),span=Math.max(1,max-min);
      const x=i=>points.length===1?W/2:i*W/(points.length-1);
      // Each counter has its own vertical scale: only compare trend shapes,
      // not relative magnitudes or percentages.
      const y=v=>H-P-((v-min)/span)*(H-2*P);
      let part=[];
      const emit=()=>{
        if(!part.length)return;
        svg+='<path d="M '+part.map(q=>q[0].toFixed(1)+' '+q[1].toFixed(1)).join(' L ')+'" fill="none" stroke="'+miniColors[index%miniColors.length]+'" stroke-width="1.15" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>';
        const last=part[part.length-1];
        svg+='<circle cx="'+last[0]+'" cy="'+last[1]+'" r="2.1" fill="'+miniColors[index%miniColors.length]+'"/>';
        part=[];
      };
      values.forEach((v,i)=>{if(v==null||!Number.isFinite(v))emit();else part.push([x(i),y(v)]);});
      emit();
    });
    if(!any){el.textContent='No history yet';return;}
    el.innerHTML=svg+'</svg>';
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
      if(tempChart)draw(tempChart,points,'cpu_thermal_cur','#f7ad75');
      const ddrValue=document.getElementById('ddr-temp-value');
      if(ddrValue){
        const latest=points.map(p=>p.ddr_thermal_cur).filter(v=>v!=null&&Number.isFinite(Number(v))).at(-1);
        ddrValue.textContent=latest==null?'—':String(Math.round(latest));
        const unit=document.createElement('small');unit.textContent='°C';ddrValue.append(unit);
      }
      const ddrChart=document.getElementById('ddr-temp-chart');
      if(ddrChart)draw(ddrChart,points,'ddr_thermal_cur','#ce93d8');
      for(const field of ['net_bytes_sent','net_bytes_recv','net_packets_sent','net_packets_recv','net_errin','net_errout','net_dropin','net_dropout']){
        const el=document.getElementById('network-'+field);
        if(!el)continue;
        const latest=points.map(p=>p[field]).filter(v=>v!=null&&Number.isFinite(Number(v))).at(-1);
        el.textContent=latest==null?'—':new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1}).format(Number(latest));
        if(latest!=null)el.title=Number(latest).toLocaleString('en-US');
      }
      const diskFields=['disk_read_count','disk_write_count','disk_read_bytes','disk_write_bytes','disk_read_time','disk_write_time','disk_busy_time','disk_usage_total','disk_usage_used','disk_usage_free','disk_usage_percent'];
      for(const field of diskFields){
        const el=document.getElementById('disk-'+field);
        if(!el)continue;
        const latest=points.map(p=>p[field]).filter(v=>v!=null&&Number.isFinite(Number(v))).at(-1);
        if(latest==null){el.textContent='—';el.removeAttribute('title');continue;}
        const n=Number(latest);
        const isBytes=field.includes('bytes')||field.startsWith('disk_usage_');
        const sizes=['B','KB','MB','GB','TB'];
        let display;
        if(field==='disk_usage_percent')display=n.toFixed(0)+'%';
        else if(isBytes){
          let scaled=n,index=0;
          while(scaled>=1024&&index<sizes.length-1){scaled/=1024;index++;}
          display=scaled.toFixed(scaled>=100?0:scaled>=10?1:2)+' '+sizes[index];
        }else display=new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1}).format(n);
        el.textContent=display;
        el.title=n.toLocaleString('en-US')+(isBytes?' bytes':field.endsWith('time')?' ms':'');
      }
      document.querySelectorAll('.system-mini-spark[data-mini-series]').forEach(el=>{
        const fields=el.dataset.miniSeries.split(',').filter(Boolean);
        drawMiniSeries(el,points,fields);
      });
      const cores=document.getElementById('cpu-cores-chart');
      if(cores){coreChart(cores,points);
        for(let n=0;n<4;n++){const val=points.map(p=>p['cpus_percent_'+n]).filter(v=>v!=null&&Number.isFinite(Number(v))).at(-1);const out=document.getElementById('core-value-'+n);if(out)out.textContent=(val==null?'—':Number(val).toFixed(0))+'%';}
      }
      for(const [field,[unit,precision,color]] of Object.entries(config)){
        const el=document.querySelector('[data-system-field="'+field+'"]'),value=document.getElementById('system-value-'+field);
        if(!el||!value)continue;
        const readings=(body.points||[]).map(p=>p[field]);
        draw(el,points,field,color);
        const latest=readings.filter(v=>v!=null&&Number.isFinite(Number(v))).at(-1);
        value.textContent=latest===undefined?'—':Number(latest).toFixed(precision);
        const suffix=document.createElement('small');suffix.textContent=unit;value.appendChild(suffix);
      }
    }catch(e){console.warn('System history failed',e);document.querySelectorAll('[data-system-field]').forEach(el=>{if(!el.querySelector('svg'))el.textContent='History unavailable';});}
  }
  refresh();setInterval(()=>{if(!document.hidden)refresh()},60000);
})();
