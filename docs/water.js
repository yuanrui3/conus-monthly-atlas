'use strict';
import {readAtlasJSON} from './month_data.js';
const $ = id => document.getElementById(id);
export function escapeHtml(value) { return String(value == null ? '' : value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
export function currentUnits() { return window.NovemberAtlas?.units || 'metric'; }
export function flowUnit(units=currentUnits()) { return units==='us'?'ft³/s':'m³/s'; }
export function flowValue(value,units=currentUnits()) { if(value==null||!Number.isFinite(Number(value)))return 'No data';const n=Number(value)*(units==='us'?35.31466672148859:1);return new Intl.NumberFormat('en-US',{maximumSignificantDigits:3}).format(n); }
const monthNames=['January','February','March','April','May','June','July','August','September','October','November','December'];
export const currentWaterMonth=()=>window.NovemberAtlas?.month || 11;
export const waterMonthName=(m=currentWaterMonth())=>monthNames[m-1];
const years=Array.from({length:20},(_,i)=>2006+i), factor=0.028316846592;
function prepareMonth(d,month){
 if(d?.schemaVersion!==2||d.metadata?.month!==month||d.metadata?.baseline?.startYear!==2006||d.metadata?.baseline?.endYear!==2025||d.metadata?.years?.some((y,i)=>y!==years[i])||d.metadata?.years?.length!==20||!Array.isArray(d.stations))throw Error('The monthly station dataset or baseline could not be verified.');
 let complete=0;
 for(const s of d.stations){
  const vs=s.annualMeansCfs;
  if(!Array.isArray(vs)||vs.length!==20||vs.some(v=>v!==null&&!Number.isFinite(v)))throw Error('Invalid annual discharge values.');
  const a=vs.map(v=>v===null?null:v*factor),valid=a.filter(Number.isFinite).sort((x,y)=>x-y),n=valid.length;
  if(!n)throw Error('A station has no published values for this month.');
  const mean=valid.reduce((x,y)=>x+y,0)/n,half=Math.floor(n/2);
  Object.assign(s,{month,years,annualMeansM3s:a,validYears:n,expectedYears:20,completeBaseline:n===20,meanDischargeM3s:mean,medianDischargeM3s:n%2?valid[half]:(valid[half-1]+valid[half])/2,sdDischargeM3s:n<2?null:Math.sqrt(valid.reduce((v,x)=>v+(x-mean)**2,0)/n),sourceUrl:'https://waterdata.usgs.gov/monitoring-location/'+encodeURIComponent(s.id)+'/'});
  if(n===20)complete++;
 }
 const c=d.metadata.coverage;if(c?.publishedStations!==d.stations.length||c.completeBaselineStations!==complete||c.partialBaselineStations!==d.stations.length-complete)throw Error('Station counts do not match the published month.');
 return d;
}
let waterRequest=null;
export function loadWaterData(retry=false){
 const month=currentWaterMonth();
 if(!retry&&waterRequest?.month===month)return waterRequest.promise;
 waterRequest?.controller.abort();const req={month,controller:new AbortController()};waterRequest=req;
 req.promise=readAtlasJSON('data/water_months/'+String(month).padStart(2,'0')+'.json.gz',{signal:req.controller.signal}).then(d=>prepareMonth(d,month)).catch(e=>{if(waterRequest===req)waterRequest=null;throw e;});
 return req.promise;
}
export function stationFeatureCollection(data) { return {type:'FeatureCollection',features:data.stations.filter(s=>Number.isFinite(s.lon)&&Number.isFinite(s.lat)).map(s=>({type:'Feature',id:s.id,geometry:{type:'Point',coordinates:[s.lon,s.lat]},properties:{id:s.id,name:s.name,state:s.state,completeBaseline:s.completeBaseline===true,validYears:s.validYears,meanDischargeM3s:s.meanDischargeM3s}}))}; }
function annualChart(s,units) {
 const m=waterMonthName(s.month),vals=s.annualMeansM3s||[],years=s.years||[];if(!vals.length)return '';
 const valid=vals.filter(v=>v!=null&&Number.isFinite(v)),low=Math.min(0,...valid),high=Math.max(0,...valid);let span=high-low;if(!span)span=1;const top=high+span*.1,bottom=low-span*.08,y=v=>80-(v-bottom)/(top-bottom)*80,zero=y(0),step=260/Math.max(vals.length,1);
 const bars=vals.map((v,i)=>{const x=i*step+1.5;if(v==null||!Number.isFinite(v))return '<path d="M'+(x+step*.35).toFixed(2)+' 72v7" stroke="#b3bfa5" stroke-width="1" stroke-dasharray="2 2"><title>'+escapeHtml(years[i])+': missing</title></path>';const yy=y(v),h=Math.max(1,Math.abs(zero-yy));return '<rect x="'+x.toFixed(2)+'" y="'+Math.min(yy,zero).toFixed(2)+'" width="'+Math.max(2,step-3).toFixed(2)+'" height="'+h.toFixed(2)+'" fill="'+(v<0?'#9a81a3':'#5a9180')+'"><title>'+escapeHtml(years[i])+': '+escapeHtml(flowValue(v,units)+' '+flowUnit(units))+'</title></rect>';}).join('');
 return '<figure class="annual-chart"><figcaption>Annual '+m+' mean discharge</figcaption><svg viewBox="0 0 260 84" role="img" aria-label="Bar chart of available annual '+m+' mean discharge; the full values are in the table below."><line x1="0" x2="260" y1="'+zero.toFixed(2)+'" y2="'+zero.toFixed(2)+'" stroke="#c9d6be" stroke-width=".7"/>'+bars+'</svg><div class="chart-years"><span>'+escapeHtml(years[0]||2006)+'</span><span>'+escapeHtml(years[years.length-1]||2025)+'</span></div><p>Each bar is one annual '+m+' mean. Gaps are missing years; negative net flow remains negative.</p></figure>';
}
export function stationMarkup(s,{units=currentUnits(),includeLocalLink=false}={}) {
 const m=waterMonthName(s.month),full=s.completeBaseline===true,count=s.validYears||0,expected=s.expectedYears||20,id=escapeHtml(s.id),source=escapeHtml(s.sourceUrl||'https://waterdata.usgs.gov/');
 const rows=(s.years||[]).map((yr,i)=>'<tr><td>'+escapeHtml(yr)+'</td><td>'+escapeHtml(flowValue((s.annualMeansM3s||[])[i],units))+'</td></tr>').join('');
 return '<p class="eyebrow">USGS GAUGE · '+escapeHtml(s.state||'SOURCE LOCATION')+'</p><h2 class="station-title">'+escapeHtml(s.name)+'</h2><p class="station-id">'+id+'</p><span class="station-coverage'+(full?'':' partial')+'">'+(full?'Complete baseline · ':'Partial baseline · ')+count+' / '+expected+' years · '+m+'</span><div class="station-primary"><span>Mean '+m+' discharge</span><strong>'+escapeHtml(flowValue(s.meanDischargeM3s,units))+'<small>'+flowUnit(units)+'</small></strong></div><div class="station-stats"><div><span>Median annual '+m+' mean</span><strong>'+escapeHtml(flowValue(s.medianDischargeM3s,units))+'<small>'+flowUnit(units)+'</small></strong></div><div><span>Between-year SD</span><strong>'+escapeHtml(flowValue(s.sdDischargeM3s,units))+(s.sdDischargeM3s==null?'':'<small>'+flowUnit(units)+'</small>')+'</strong></div></div><p class="station-note">'+(full?'All 20 annual '+m+' means are included.':'This estimate uses '+count+' available '+m+' means. Missing years were not filled or treated as zero.')+' These are monthly-mean summaries, not daily extremes or a present-day forecast.</p>'+annualChart(s,units)+'<p class="station-note">Discharge alone does not establish depth, velocity, ice state, water quality or accessibility. Zero net flow does not mean there is no water.</p><p class="station-note coordinate-note">Source gauge coordinates: '+escapeHtml(Number(s.lat).toFixed(4))+'°, '+escapeHtml(Number(s.lon).toFixed(4))+'°. Source datum and survey accuracy vary; these are not building-scale position estimates.</p><a class="station-source-link" href="'+source+'" target="_blank" rel="noopener noreferrer">View the USGS station record ↗</a>'+(includeLocalLink?'<button class="secondary-button station-local-link" data-station-detail="'+id+'">Open local context ↗</button>':'')+'<details class="station-years"><summary>Annual values and missing years</summary><table><thead><tr><th>Year</th><th>Mean discharge ('+flowUnit(units)+')</th></tr></thead><tbody>'+rows+'</tbody></table></details>';
}
let nationalData=null,points=new Map(),selected=null,desiredId=null,ready=false,initializing=null,nationalToken=0,boundariesPromise=null;
const emptyInspector=$('water-inspector-content').innerHTML;
const W=1200,H=740,wm={z:1,x:0,y:0},stage=$('water-map-stage'),svg=$('water-map-svg');
function projectionFor(geo) {
 const R=Math.PI/180,a=29.5*R,b=45.5*R,n=(Math.sin(a)+Math.sin(b))/2,C=Math.cos(a)**2+2*n*Math.sin(a),r0=Math.sqrt(C-2*n*Math.sin(23*R))/n;
 const raw=(lon,lat)=>{const r=Math.sqrt(C-2*n*Math.sin(lat*R))/n,t=n*(lon+96)*R;return[r*Math.sin(t),r0-r*Math.cos(t)];};
 let minx=Infinity,maxx=-Infinity,miny=Infinity,maxy=-Infinity;
 const rings=g=>g.type==='Polygon'?g.coordinates:g.type==='MultiPolygon'?g.coordinates.flat():[];
 geo.features.forEach(f=>rings(f.geometry).forEach(r=>r.forEach(c=>{const p=raw(c[0],c[1]);minx=Math.min(minx,p[0]);maxx=Math.max(maxx,p[0]);miny=Math.min(miny,p[1]);maxy=Math.max(maxy,p[1]);})));
 const scale=Math.min((W-100)/(maxx-minx),(H-120)/(maxy-miny)),tx=(W-scale*(minx+maxx))/2,ty=(H+scale*(miny+maxy))/2-7;
 const project=(lon,lat)=>{const p=raw(lon,lat);return[tx+p[0]*scale,ty-p[1]*scale];};
 return {project,path:g=>rings(g).map(r=>r.map((c,i)=>{const p=project(c[0],c[1]);return(i?'L':'M')+p[0].toFixed(2)+','+p[1].toFixed(2);}).join('')+'Z').join('')};
}
function updateTransform() { wm.z=Math.max(1,Math.min(14,wm.z));wm.x=Math.max(W*(1-wm.z)-40,Math.min(40,wm.x));wm.y=Math.max(H*(1-wm.z)-30,Math.min(30,wm.y));if(wm.z===1)wm.x=wm.y=0;$('water-map-transform').setAttribute('transform','translate('+wm.x+' '+wm.y+') scale('+wm.z+')');$('water-selected-point').setAttribute('r',9/wm.z);$('water-selected-point').setAttribute('stroke-width',2/wm.z);$('water-station-points').style.setProperty('--gauge-radius',String(3/Math.sqrt(wm.z))+'px'); }
function zoom(factor,p=[W/2,H/2]) {const next=Math.max(1,Math.min(14,wm.z*factor)),ratio=next/wm.z;wm.x=p[0]-(p[0]-wm.x)*ratio;wm.y=p[1]-(p[1]-wm.y)*ratio;wm.z=next;updateTransform();$('water-tooltip').hidden=true;}
function mapPoint(e) {const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;const m=svg.getScreenCTM();if(!m)return[0,0];const q=p.matrixTransform(m.inverse());return[q.x,q.y];}
function filteredStations() {return !nationalData?[]:$('water-complete-only').checked?nationalData.stations.filter(s=>s.completeBaseline===true):nationalData.stations;}
function drawStations() {const list=filteredStations();$('water-station-points').innerHTML=list.map(s=>{const p=points.get(s.id);return p?'<circle class="gauge-point" data-station="'+escapeHtml(s.id)+'" cx="'+p[0].toFixed(2)+'" cy="'+p[1].toFixed(2)+'" r="3" style="r:var(--gauge-radius,3)" fill="'+(s.completeBaseline?'#398583':'#bc9455')+'" fill-opacity=".84" stroke="#f6faed" stroke-width=".45" vector-effect="non-scaling-stroke"/>':'';}).join('');$('water-visible-count').textContent=new Intl.NumberFormat('en-US').format(list.length)+' station markers';updateTransform();}
function selectStation(id,focus=false) {
 const s=nationalData?.stations.find(x=>x.id===id);if(!s)return;desiredId=s.id;selected=s;const p=points.get(id);if(p){$('water-selected-point').setAttribute('cx',p[0]);$('water-selected-point').setAttribute('cy',p[1]);$('water-selected-point').setAttribute('visibility','visible');if(focus){wm.z=4.5;wm.x=W/2-p[0]*wm.z;wm.y=H/2-p[1]*wm.z;}updateTransform();}
 $('water-inspector-content').innerHTML=stationMarkup(s,{includeLocalLink:true});$('water-search-results').hidden=true;$('water-search').value='';$('announcer').textContent=s.name+': '+flowValue(s.meanDischargeM3s)+' '+flowUnit()+', '+s.validYears+' of 20 '+waterMonthName(s.month)+' values.';
}
function showSearch() {if(!nationalData)return;const q=$('water-search').value.trim().toLowerCase(),box=$('water-search-results');if(q.length<2){box.hidden=true;return;}const list=filteredStations().filter(s=>(s.id+' '+s.name+' '+s.state).toLowerCase().includes(q)).slice(0,12);box.innerHTML=list.length?list.map(s=>'<button data-gauge-result="'+escapeHtml(s.id)+'"><strong>'+escapeHtml(s.name)+'</strong><small>'+escapeHtml(s.id)+' · '+escapeHtml(s.state)+' · '+s.validYears+'/20 years</small></button>').join(''):'<p>No matching station in this dataset and filter.</p>';box.hidden=false;}
function fillMethod() {
 const m=nationalData.metadata,c=m.coverage||{},fmt=v=>new Intl.NumberFormat('en-US').format(v||0),complete=nationalData.stations.filter(s=>s.completeBaseline).length;
 $('water-station-count').textContent=fmt(nationalData.stations.length);$('water-full-count').textContent=fmt(c.completeBaselineStations??complete);$('water-partial-count').textContent=fmt(c.partialBaselineStations??(nationalData.stations.length-complete));
 $('water-coverage-note').textContent=fmt(nationalData.stations.length)+' stations with usable '+waterMonthName()+' records; station coverage is not continuous water coverage.';
 const selection=typeof m.selectionRule==='string'?m.selectionRule:JSON.stringify(m.selectionRule||{});
 $('water-method-content').innerHTML='<p>'+escapeHtml(m.description||'USGS monthly means, summarized at each gauge.')+'</p><p><strong>Selection:</strong> '+escapeHtml(selection)+'</p><ul>'+(m.method||[]).map(t=>'<li>'+escapeHtml(t)+'</li>').join('')+'</ul><p><strong>Limits:</strong> '+escapeHtml((m.limitations||[]).join(' '))+'</p><div class="method-links"><a href="'+escapeHtml(m.source.documentationUrl)+'" target="_blank" rel="noopener noreferrer">USGS source documentation ↗</a><a href="data/water_months_manifest.json" download>Download provenance ↗</a><a href="data/water_months_validation.json" download>Download data checks ↗</a></div>';
}
function clearNational(){
 nationalToken++;nationalData=null;selected=null;ready=false;initializing=null;points.clear();
 $('water-station-points').replaceChildren();$('water-selected-point').setAttribute('visibility','hidden');$('water-search-results').hidden=true;$('water-tooltip').hidden=true;
 $('water-inspector-content').innerHTML=emptyInspector;$('water-method-content').textContent='Load this month’s records to inspect methods and coverage.';
 for(const id of ['water-station-count','water-full-count','water-partial-count'])$(id).textContent='—';
 $('water-visible-count').textContent='No records displayed';$('water-coverage-note').textContent='Coverage follows available approved monthly records.';
 $('water-error').hidden=true;$('water-loading').hidden=false;
}
async function initNational(retry=false) {
 if(ready&&!retry)return;if(initializing&&!retry)return initializing;
 const token=++nationalToken,month=currentWaterMonth();$('water-loading').hidden=false;$('water-error').hidden=true;
 if(!boundariesPromise)boundariesPromise=fetch('data/states.geojson').then(r=>{if(!r.ok)throw new Error('Reference boundaries could not load.');return r.json();}).then(g=>{const p=projectionFor(g);$('water-state-shapes').innerHTML=g.features.map(f=>'<path d="'+p.path(f.geometry)+'" fill="#e5ecdb" stroke="#bacbb0" stroke-width=".75" vector-effect="non-scaling-stroke" fill-rule="evenodd"/>').join('');return p;}).catch(e=>{boundariesPromise=null;throw e;});
 initializing=(async()=>{try{
  const [d,projection]=await Promise.all([loadWaterData(retry),boundariesPromise]);if(token!==nationalToken||month!==currentWaterMonth())return;
  nationalData=d;points.clear();d.stations.forEach(s=>{if(Number.isFinite(s.lon)&&Number.isFinite(s.lat))points.set(s.id,projection.project(s.lon,s.lat));});
  drawStations();fillMethod();ready=true;$('water-loading').hidden=true;
  if(desiredId){const keep=d.stations.find(s=>s.id===desiredId);if(keep&&(!$('water-complete-only').checked||keep.completeBaseline))selectStation(keep.id);else{desiredId=null;$('water-inspector-content').innerHTML=emptyInspector+'<p class="station-note">The previous gauge has no record for this month and filter.</p>';}}
  if($('water-search').value.trim())showSearch();
 }catch(e){if(token!==nationalToken||month!==currentWaterMonth())return;$('water-loading').hidden=true;$('water-error').hidden=false;$('water-error-message').textContent=waterMonthName(month)+' records unavailable: '+e.message;}finally{if(token===nationalToken)initializing=null;}})();return initializing;
}
document.addEventListener('atlas:month',()=>{
 if(waterRequest&&waterRequest.month!==currentWaterMonth()){waterRequest.controller.abort();waterRequest=null;}
 clearNational();if(!$('view-water').hidden)initNational();
});
let drag=null;
stage.addEventListener('pointerdown',e=>{if(e.target.closest('button'))return;stage.focus({preventScroll:true});const p=mapPoint(e);drag={id:e.pointerId,p,x:wm.x,y:wm.y,moved:false,station:e.target.closest('[data-station]')?.dataset.station};stage.setPointerCapture(e.pointerId);});
stage.addEventListener('pointermove',e=>{if(drag){const p=mapPoint(e),dx=p[0]-drag.p[0],dy=p[1]-drag.p[1];if(Math.abs(dx)+Math.abs(dy)>5)drag.moved=true;if(drag.moved){stage.classList.add('dragging');wm.x=drag.x+dx;wm.y=drag.y+dy;updateTransform();$('water-tooltip').hidden=true;}return;}const id=e.target.closest('[data-station]')?.dataset.station,s=id&&nationalData?.stations.find(x=>x.id===id);if(!s){$('water-tooltip').hidden=true;return;}const tip=$('water-tooltip');tip.innerHTML=escapeHtml(s.name)+'<strong>'+escapeHtml(flowValue(s.meanDischargeM3s)+' '+flowUnit())+'</strong><small>'+s.validYears+'/20 years · '+waterMonthName(s.month)+' · '+(s.completeBaseline?'complete':'partial')+'</small>';tip.hidden=false;const r=stage.getBoundingClientRect();tip.style.left=Math.max(8,Math.min(r.width-tip.offsetWidth-8,e.clientX-r.left+12))+'px';tip.style.top=Math.max(8,Math.min(r.height-tip.offsetHeight-8,e.clientY-r.top-75))+'px';});
stage.addEventListener('pointerup',e=>{if(!drag)return;const d=drag;drag=null;stage.classList.remove('dragging');if(stage.hasPointerCapture(e.pointerId))stage.releasePointerCapture(e.pointerId);if(!d.moved&&d.station)selectStation(d.station);});
stage.addEventListener('pointercancel',()=>{drag=null;stage.classList.remove('dragging');});stage.addEventListener('pointerleave',()=>{$('water-tooltip').hidden=true;});stage.addEventListener('wheel',e=>{e.preventDefault();zoom(Math.exp(-Math.max(-150,Math.min(150,e.deltaY))*.002),mapPoint(e));},{passive:false});
stage.addEventListener('keydown',e=>{if(e.target!==stage)return;let handled=true;if(e.key==='+'||e.key==='=')zoom(1.4);else if(e.key==='-')zoom(1/1.4);else if(e.key==='Home'){wm.z=1;wm.x=wm.y=0;}else if(e.key==='ArrowLeft')wm.x+=55;else if(e.key==='ArrowRight')wm.x-=55;else if(e.key==='ArrowUp')wm.y+=55;else if(e.key==='ArrowDown')wm.y-=55;else handled=false;if(handled){e.preventDefault();updateTransform();}});
$('water-search').addEventListener('input',showSearch);$('water-search').addEventListener('keydown',e=>{if(e.key==='Escape')$('water-search-results').hidden=true;});$('water-search-results').addEventListener('click',e=>{const b=e.target.closest('[data-gauge-result]');if(b)selectStation(b.dataset.gaugeResult,true);});
$('water-complete-only').addEventListener('change',()=>{if(!ready)return;drawStations();showSearch();if(selected&&!selected.completeBaseline&&$('water-complete-only').checked){$('water-selected-point').setAttribute('visibility','hidden');}else if(selected){$('water-selected-point').setAttribute('visibility','visible');}});
$('water-zoom-in').addEventListener('click',()=>zoom(1.5));$('water-zoom-out').addEventListener('click',()=>zoom(1/1.5));$('water-zoom-reset').addEventListener('click',()=>{wm.z=1;wm.x=wm.y=0;updateTransform();});$('water-retry').addEventListener('click',()=>initNational(true));
$('water-inspector-content').addEventListener('click',e=>{const b=e.target.closest('[data-station-detail]');if(!b)return;const s=nationalData?.stations.find(x=>x.id===b.dataset.stationDetail);if(s)document.dispatchEvent(new CustomEvent('atlas:open-detail',{detail:{lat:s.lat,lon:s.lon,name:s.name,zoom:14,stationId:s.id}}));});
document.addEventListener('atlas:view',e=>{if(e.detail.view==='water')initNational();});document.addEventListener('atlas:units',()=>{if(selected)$('water-inspector-content').innerHTML=stationMarkup(selected,{includeLocalLink:true});$('water-tooltip').hidden=true;});
