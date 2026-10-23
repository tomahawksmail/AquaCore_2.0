"use strict";
(() => {
  const colors = {temp: '#5eead4', ph: '#8fa8ff', tds: '#ffc48b'};
  let current = '24h';
  const message = document.getElementById('chart-message');
  const grid = document.getElementById('chart-grid');
  if (!grid) return;

  const svgNS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs, parent, content) {
    const n = document.createElementNS(svgNS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, String(v)));
    if (content !== undefined) n.textContent = content;
    if (parent) parent.appendChild(n);
    return n;
  }
  function dateLabel(iso, period) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16);
    return period === '24h' ? d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',hour12:false}) :
      d.toLocaleDateString([], {month:'short',day:'numeric'});
  }
  function draw(field, points, period, limits = {}) {
    const target = document.querySelector(`[data-field="${field}"]`);
    target.replaceChildren();
    const rows = points.filter(p => p.time);
    const valid = rows.filter(p => typeof p[field] === 'number' && Number.isFinite(p[field]));
    if (!valid.length) {
      const empty = document.createElement('p'); empty.className = 'dim';
      empty.textContent = 'No measurements in this period.'; target.appendChild(empty); return;
    }
    const W=Math.max(560,Math.round(target.getBoundingClientRect().width||560)),H=222,L=49,R=14,T=16,B=34;
    const times=rows.map(p=>new Date(p.time).getTime());
    let t0=Math.min(...times), t1=Math.max(...times);
    if(t0===t1){t0-=3600000;t1+=3600000;}
    const values=valid.map(p=>p[field]);
    let low=Math.min(...values), high=Math.max(...values);
    const pad=Math.max((high-low)*0.13, field==='ph'?0.08:field==='temp'?0.3:5);
    low-=pad;high+=pad;
    const minLimit = field === 'temp' ? limits.min_temp : field === 'ph' ? limits.min_ph : limits.min_tds;
    const maxLimit = field === 'temp' ? limits.max_temp : field === 'ph' ? limits.max_ph : limits.max_tds;
    const hasMin = typeof minLimit === 'number' && Number.isFinite(minLimit);
    const hasMax = typeof maxLimit === 'number' && Number.isFinite(maxLimit);
    // Invalid configurations are not presented as safe ranges.
    const validRange = hasMin && hasMax && minLimit < maxLimit;
    const validCap = field === 'tds' && !hasMin && hasMax && maxLimit >= 0;
    if (validRange || validCap) {
      if (validRange) low = Math.min(low, minLimit - pad * .3);
      high = Math.max(high, maxLimit + pad * .3);
      if (validCap) low = Math.min(low, maxLimit - pad * 1.5);
    }
    // Temperature uses fixed 5°C ticks; all readings and reference limits remain visible.
    if (field === 'temp') {
      low = Math.floor(low / 5) * 5;
      high = Math.ceil(high / 5) * 5;
      if (high <= low) high = low + 5;
    }
    const x=t => L+(t-t0)/(t1-t0)*(W-L-R);
    const y=v => T+(high-v)/(high-low)*(H-T-B);
    const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,class:'chart-svg',role:'img', 'aria-label':`${field} history chart; ${valid.length} available intervals`},target);
    // Draw reference band behind grid lines and sensor data.
    if (validRange) {
      el('rect', {x:L, y:y(maxLimit), width:W-L-R, height:y(minLimit)-y(maxLimit), class:'acceptable-zone'}, svg);
    } else if (validCap) {
      el('rect', {x:L, y:y(maxLimit), width:W-L-R, height:y(low)-y(maxLimit), class:'acceptable-zone'}, svg);
    }
    function limitLine(value, caption) {
      const py=y(value);
      el('line',{x1:L,y1:py,x2:W-R,y2:py,class:'limit-line'},svg);
      el('text',{x:W-R-5,y:Math.max(T+12,py-5),'text-anchor':'end',class:'limit-label'},svg,caption);
    }
    if (validRange) {
      limitLine(minLimit, 'MIN ' + minLimit);
      limitLine(maxLimit, 'MAX ' + maxLimit);
    } else if (validCap) limitLine(maxLimit, 'MAX ' + maxLimit + ' ppm');
    const ticks = field === 'temp'
      ? Array.from({length:Math.round((high-low)/5)+1},(_,i)=>low+i*5)
      : Array.from({length:4},(_,i)=>low+(high-low)*i/3);
    for (const val of ticks) {
      const py=y(val);
      el('line',{x1:L,y1:py,x2:W-R,y2:py,class:'chart-gridline'},svg);
      el('text',{x:L-8,y:py+4,'text-anchor':'end'},svg,field==='temp'?String(val):val.toFixed(field==='ph'?2:1));
    }
    if (period === '24h') {
      // Labels only at exact local clock hours, never at arbitrary sample minutes.
      // Avoid overcrowding long time ranges by skipping whole hours.
      const hourMs=3600000;
      const first=Math.ceil(t0/hourMs)*hourMs;
      const last=Math.floor(t1/hourMs)*hourMs;
      const available=Math.max(0,Math.floor((last-first)/hourMs)+1);
      const stride=Math.max(1,Math.ceil(available/6));
      for(let ms=first;ms<=last;ms+=stride*hourMs){
        const dt=new Date(ms);
        const label=String(dt.getHours()).padStart(2,'0')+':00';
        el('text',{x:x(ms),y:H-7,'text-anchor':'middle'},svg,label);
      }
    } else {
      [0,.5,1].forEach(f=>{
        const d=new Date(t0+(t1-t0)*f).toISOString();
        el('text',{x:L+(W-L-R)*f,y:H-7,'text-anchor':f===0?'start':f===1?'middle':'end'},svg,dateLabel(d,period));
      });
    }
    // Break paths for missing measurements or unusually long time gaps.
    const diffs=times.slice(1).map((t,i)=>t-times[i]).filter(v=>v>0);
    diffs.sort((a,b)=>a-b); const interval=diffs[Math.floor(diffs.length/2)] || 3600000;
    let segments=[], seg=[], previous=null;
    for(const p of rows){
      const t=new Date(p.time).getTime();
      if(typeof p[field]!=='number'|| !Number.isFinite(p[field]) || (previous!==null && t-previous>interval*2.5)) {
        if(seg.length) segments.push(seg);seg=[];
      }
      if(typeof p[field]==='number' && Number.isFinite(p[field])) seg.push([x(t),y(p[field])]);
      previous=t;
    }
    if(seg.length) segments.push(seg);
    for(const s of segments){
      el('path',{d:s.map((p,i)=>`${i?'L':'M'} ${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' '),class:'line',stroke:colors[field]},svg);
      if(s.length===1) el('circle',{cx:s[0][0],cy:s[0][1],r:3,fill:colors[field]},svg);
    }
    const tooltip=document.createElement('div'); tooltip.className='chart-tooltip';
    tooltip.textContent=`${valid.length} time intervals`;
    target.appendChild(tooltip);
    const dot=el('circle',{cx:0,cy:0,r:5,fill:colors[field],class:'tipdot',visibility:'hidden'},svg);
    // Transparent overlay owns pointer handling; SVG is responsive via viewBox.
    const hit=el('rect',{x:L,y:T,width:W-L-R,height:H-T-B,class:'hit'},svg);
    hit.addEventListener('pointermove',e=>{
      const bounds=svg.getBoundingClientRect(), px=(e.clientX-bounds.left)/bounds.width*W;
      const nearest=valid.reduce((a,b)=>Math.abs(x(new Date(a.time).getTime())-px)<Math.abs(x(new Date(b.time).getTime())-px)?a:b);
      dot.setAttribute('cx',x(new Date(nearest.time).getTime()));dot.setAttribute('cy',y(nearest[field]));dot.setAttribute('visibility','visible');
      tooltip.textContent=`${dateLabel(nearest.time,period)} · ${nearest[field]} ${field==='temp'?'°C':field==='tds'?'ppm':''} (${nearest.samples} samples)`;
    });
    hit.addEventListener('pointerleave',()=>{dot.setAttribute('visibility','hidden');tooltip.textContent=`${valid.length} time intervals`;});
  }
  async function load(period){
    current=period;message.hidden=false;message.textContent='Loading measurements…';grid.hidden=true;
    document.querySelectorAll('.range-btn').forEach(b=>{b.classList.toggle('selected',b.dataset.period===period);b.setAttribute('aria-pressed',String(b.dataset.period===period));});
    try {
      const response=await fetch('/api/history?period='+encodeURIComponent(period),{cache:'no-store'});
      if(!response.ok) throw new Error('Request failed ('+response.status+')');
      const data=await response.json();
      if(current!==period)return;
      if(!data.points.length){message.textContent='No saved measurements for this period.';return;}
      for(const field of ['temp','ph','tds'])draw(field,data.points,period,data.limits || {});
      message.hidden=true;grid.hidden=false;
    }catch(e){message.textContent='History unavailable: '+e.message;}
  }
  document.querySelectorAll('.range-btn').forEach(b=>b.addEventListener('click',()=>load(b.dataset.period)));
  load(current);
  setInterval(()=>{if(!document.hidden)load(current)},60000);
})();
