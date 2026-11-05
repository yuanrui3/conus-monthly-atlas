// Independent snow-on-land and surface-water-ice climatologies. The base map stays intact.
import {readAtlasJSON} from './month_data.js';
const monthNames=['January','February','March','April','May','June','July','August','September','October','November','December'];
const sources={
  snow:{title:'Snow on land',source:'USNIC IMS',url:'data/seasonal_snow.json.gz',colors:['transparent','#c7b9ee','#9a80cd','#7252ae','#472776'],unit:'snow-cover frequency'},
  ice:{title:'Great Lakes ice',source:'NOAA GLERL',url:'data/seasonal_ice.json.gz',colors:['#e8f5f3','#a7dddd','#63bdc6','#258897','#085b6d'],unit:'surface ice concentration'}
};
const percent=v=>v===0?'0%':v>0&&v<.1?'<0.1%':Number(v.toFixed(1)).toLocaleString('en-US')+'%';
const valid=v=>Number.isFinite(v)&&v>=0&&v<=100;
const bin=v=>v===0?0:v<=25?1:v<=50?2:v<=75?3:4;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const lakes=['Lake Superior','Lake Michigan','Lake Huron','Lake Erie','Lake Ontario','Lake Saint Clair'];
const nameKey=v=>String(v||'').toLowerCase().replace(/[^a-z]/g,'').replace(/^lake/,'').replace('saint','st');

export function gridCell(g,lon,lat){
  if(!g||!Number.isFinite(lon)||!Number.isFinite(lat))return -1;
  const col=Math.floor((lon-g.lon[0])/(g.lon[1]-g.lon[0])+.5),row=Math.floor((lat-g.lat[0])/(g.lat[1]-g.lat[0])+.5);
  return col<0||row<0||col>=g.width||row>=g.height?-1:row*g.width+col;
}
function validate(d,k){
  const checkMonths=xs=>Array.isArray(xs)&&xs.length===12&&new Set(xs.map(a=>a.month)).size===12&&xs.every(a=>Number.isInteger(a.month)&&a.month>=1&&a.month<=12);
  if(d?.grid){
    const g=d.grid;
    if(!Number.isInteger(g.width)||!Number.isInteger(g.height)||g.width<2||g.height<2||g.lon?.length!==g.width||g.lat?.length!==g.height||!g.lon.every((v,i)=>Number.isFinite(v)&&(!i||v>g.lon[i-1]))||!g.lat.every((v,i)=>Number.isFinite(v)&&(!i||v<g.lat[i-1]))||!checkMonths(d.months))throw Error('Grid or calendar could not be verified');
    if(k==='ice'&&g.lakeIds&&g.lakeIds.length!==g.width*g.height)throw Error('Lake mask could not be verified');
    if(d.months.some(m=>!Array.isArray(m.values)||m.values.length!==g.width*g.height||!m.values.every(v=>v===null||valid(v))))throw Error('Invalid monthly grid');
  }else if(k==='ice'&&Array.isArray(d?.lakes)&&d.lakes.length){
    if(d.lakes.some(l=>!l.name||!checkMonths(l.months)||l.months.some(m=>m.meanPercent!==null&&!valid(m.meanPercent))))throw Error('Invalid lake summaries');
  }else throw Error('No supported seasonal coverage');
  return d;
}
function makeCanvas(w,h,scale=1.5){const c=document.createElement('canvas');c.width=Math.ceil(w*scale);c.height=Math.ceil(h*scale);const x=c.getContext('2d');x.scale(scale,scale);return [c,x];}
function gridCorners(g,project){
  const n=g.width+1,arr=new Float32Array((g.height+1)*n*2),dx=g.lon[1]-g.lon[0],dy=g.lat[1]-g.lat[0];
  for(let r=0;r<=g.height;r++)for(let c=0;c<n;c++){const p=project(g.lon[0]+(c-.5)*dx,g.lat[0]+(r-.5)*dy),i=(r*n+c)*2;arr[i]=p[0];arr[i+1]=p[1];}
  return arr;
}
function markCell(path,p,n,i,r){const a=(i+r)*2,b=a+2,c=b+2*n,d=a+2*n;path.moveTo(p[a],p[a+1]);path.lineTo(p[b],p[b+1]);path.lineTo(p[c],p[c+1]);path.lineTo(p[d],p[d+1]);path.closePath();}
function hatch(c){const tile=document.createElement('canvas');tile.width=tile.height=7;const t=tile.getContext('2d');t.fillStyle='#eef0e6';t.fillRect(0,0,7,7);t.strokeStyle='#868b79';t.lineWidth=1.15;t.beginPath();t.moveTo(-1,1);t.lineTo(1,-1);t.moveTo(0,7);t.lineTo(7,0);t.moveTo(6,8);t.lineTo(8,6);t.stroke();return c.createPattern(tile,'repeat');}
function selectionAt(map,lon,lat){
  if(!map.project||!map.hydroReady)return {lake:null,land:false};
  const [x,y]=map.project(lon,lat),area=map.hydroPaths.find(f=>f.kind==='lake'&&x>=f.bounds[0]&&x<=f.bounds[2]&&y>=f.bounds[1]&&y<=f.bounds[3]&&map.hit.isPointInPath(f.path,x,y,'evenodd'));
  return {lake:area||null,land:!area&&map.hit.isPointInPath(map.union,x,y,'evenodd')};
}
function description(k,s){
  if(k==='snow')return s.data?.legendDescription||'Frequency of land classified as snow-covered in sampled USNIC IMS charts, 2006–2025. Native support is about 24 km. This is not snow depth.';
  return s.data?.legendDescription||(s.data?.grid?'Mean charted surface concentration on the Great Lakes and Lake Saint Clair; each included year needs observations on at least 80% of this month’s days, with at least 10 qualifying years. This does not measure ice thickness.':'Lake-wide mean surface ice concentration. A lake is shaded uniformly; the color does not locate its ice.');
}
export function createSeasonalOverlays({controls,readout,getMap,redraw}){
  let opacity=.75;
  const state=Object.fromEntries(Object.keys(sources).map(k=>[k,{active:false,phase:'idle',cache:new Map(),data:null}]));
  const api={drawSnow,drawIce,refresh,evidenceFields:()=>rows(false),hover:(lon,lat)=>{const map={...getMap(),selected:{lon,lat}},active=Object.keys(state).filter(k=>state[k].active);if(!active.length)return '';const area=selectionAt(map,lon,lat);return active.map(k=>{const row=summary(k,map,area);return '<small class="seas-tooltip-row">'+esc(row.label)+': '+esc(row.valueText)+'</small>';}).join('');},canSelect:(lon,lat)=>{if(!state.ice.active)return false;const area=selectionAt(getMap(),lon,lat);return !!area.lake&&lakes.includes(area.lake.name);}};
  if(!controls||!readout){return {drawSnow(){},drawIce(){},refresh(){},evidenceFields(){return[];},hover(){return '';},canSelect(){return false;}};}
  readout.hidden=true;
  controls.innerHTML='<fieldset class="seas-opts"><legend>Seasonal overlays</legend><div class="seas-controlrow"><div class="seas-toggles">'+Object.entries(sources).map(([k,o])=>'<label class="seas-toggle"><input id="show-seasonal-'+k+'" type="checkbox" data-seasonal="'+k+'"><i class="seas-chip seas-'+k+'"></i>'+esc(o.title)+'</label>').join('')+'</div><div class="seas-meta"><label class="seas-opacity" hidden>Overlay opacity <input id="seasonal-opacity" type="range" min="20" max="100" step="5" value="75"><output for="seasonal-opacity">75%</output></label><span class="seas-period">Monthly · 2006–2025</span></div></div><p class="seas-intro">Add seasonal conditions above the base map. Perennial ice/snow remains a land-cover class.</p><div class="seas-legends" aria-live="polite"></div></fieldset>';
  controls.addEventListener('input',e=>{if(e.target.id!=='seasonal-opacity')return;opacity=Number(e.target.value)/100;controls.querySelector('.seas-opacity output').textContent=e.target.value+'%';redraw();});
  controls.addEventListener('change',e=>{const k=e.target.dataset.seasonal;if(!state[k])return;state[k].active=e.target.checked;if(state[k].active&&['idle','error'].includes(state[k].phase))load(k);refresh();redraw();});
  controls.addEventListener('click',e=>{const k=e.target.closest('[data-seasonal-retry]')?.dataset.seasonalRetry;if(k&&state[k]&&state[k].phase==='error')load(k);});
  async function load(k){
    const s=state[k];if(s.phase==='loading')return;s.phase='loading';refresh();redraw();
    const control=new AbortController(),timer=setTimeout(()=>control.abort(),35000);
    try {s.data=validate(await readAtlasJSON(sources[k].url,{signal:control.signal}),k);s.phase='ready';}catch(error){s.phase='error';s.message=String(error?.message||'Request failed');}finally{clearTimeout(timer);}
    refresh();redraw();
  }
  function relevantLakes(map,s){const names=s.data?.lakes?.map(a=>nameKey(a.geometryName||a.name))||lakes.map(nameKey);return map.hydroPaths.filter(f=>f.kind==='lake'&&lakes.includes(f.name)&&names.includes(nameKey(f.name)));}
  function lakeInfo(s,lake){return s.data?.lakes?.find(o=>nameKey(o.geometryName||o.name)===nameKey(lake?.name));}
  function lakeMonth(s,lake,n){return s.data?.lakes?.find(o=>nameKey(o.geometryName||o.name)===nameKey(lake?.name))?.months?.find(m=>m.month===n);}
  function summary(k,map,area){
    const s=state[k],o=sources[k],p=map.selected;
    const info={id:'seasonal-'+k,label:o.title,status:'select',valueText:'Select a map location',period:monthNames[map.month-1]+' 2006–2025',support:k==='snow'?'USNIC IMS · 24 km source':s.data?.grid?'0.05° display grid · about 1.8 km source':'NOAA GLERL · whole lake',note:description(k,s)};
    if(s.phase!=='ready'||!map.hydroReady){const failed=s.phase==='error'||map.hydroFailed;return {...info,status:failed?'missing':'loading',valueText:failed?'Source unavailable':'Loading overlay…'};}
    if(!p)return info;
    if(k==='snow'&&!area?.land)return {...info,status:'missing',valueText:area?.lake?'Water · no land-snow reading':'Outside land coverage'};
    if(k==='ice'&&(!area?.lake||!relevantLakes(map,s).includes(area.lake)))return {...info,status:'missing',valueText:'Outside mapped ice coverage',note:'Ice coverage is limited to the mapped Great Lakes water bodies.'};
    let v,coverageNote='',reason='No qualifying estimate',noIceMessage='No qualifying chart average here for this month.';
    if(s.data.grid){
      const g=s.data.grid,m=s.data.months.find(a=>a.month===map.month),i=gridCell(g,p.lon,p.lat);
      const belongs=i>=0&&(k!=='ice'||!g.lakeIds||Number(g.lakeIds[i])===Number(lakeInfo(s,area.lake)?.id));v=belongs?m.values[i]:null;
      if(k==='ice')reason=m.chartDays===0?'No source chart dates':!belongs?'No matching water cell':'Insufficient chart coverage';
      if(k==='ice')noIceMessage=m.chartDays===0?'No source chart dates for this calendar month.':!belongs?'No matching source-water cell at this location.':'Insufficient qualifying chart coverage here for this month.';
      const n=m.validYears?.[i]??m.yearCounts?.[i]??(k==='snow'&&valid(v)&&s.data.minimumYears===20?20:null);if(belongs&&Number.isInteger(n))coverageNote=' '+n+' / 20 years represented.';
      const days=m.observationDays?.[i];if(k==='snow'&&belongs&&valid(v)&&Number.isInteger(days))coverageNote+=' '+days+' observed land days.';
    }else{const m=lakeMonth(s,area.lake,map.month);v=m?.meanPercent;const n=m?.validYears;if(Number.isInteger(n))coverageNote=' '+n+' / 20 years represented.';}
    if(!valid(v))return {...info,status:'missing',valueText:reason,note:(k==='ice'?noIceMessage:'No qualifying land-snow average here for this month.')+' Missing is not zero.'+coverageNote};
    return {...info,status:'available',coverageText:(k==='ice'&&area.lake?area.lake.name+(coverageNote?' · ':''):'')+coverageNote.trim(),valueText:percent(v)+(k==='snow'?' · snow frequency':' · ice concentration'),note:(k==='ice'&&!s.data.grid?area.lake.name+' · lake-wide average. ':k==='snow'&&map.selectedPerennial?'The underlying 2025 class is perennial ice/snow; it remains visible. ':'')+description(k,s)+coverageNote};
  }
  function rows(allowHidden=false){
    const map=getMap(),point=map.selected,area=point&&(state.snow.active||state.ice.active)?selectionAt(map,point.lon,point.lat):null;
    return Object.keys(state).filter(k=>state[k].active||allowHidden).map(k=>summary(k,map,area));
  }
  function refresh(){
    if(!controls)return;const map=getMap(),month=monthNames[map.month-1],legends=controls.querySelector('.seas-legends');
    const active=Object.keys(state).filter(k=>state[k].active);
    controls.querySelector('.seas-opacity').hidden=!active.length;
    const html=active.map(k=>{
      const s=state[k],o=sources[k],mn=s.data?.months?.find(x=>x.month===map.month);
      let text='';
      if(s.phase==='error'||map.hydroFailed)text='Source unavailable. No coverage is inferred.'+(s.phase==='error'?' <button type="button" data-seasonal-retry="'+k+'">Retry</button>':'');
      else if(s.phase!=='ready'||!map.hydroReady)text='Loading '+esc(o.title.toLowerCase())+'…';
      else {
        text='<div class="seas-scale">'+o.colors.map((c,i)=>'<span><i class="'+(i===0&&k==='snow'?'seas-transparent':'')+'" style="--seas-color:'+c+'"></i>'+['0','&gt;0–25','&gt;25–50','&gt;50–75','&gt;75–100'][i]+'%</span>').join('')+'<span><i class="seas-nodata"></i>No estimate</span></div><p>'+esc(description(k,s))+'</p>';
        if(k==='ice'&&((mn&&mn.values.every(v=>v===null))||(!s.data.grid&&s.data.lakes.every(l=>!valid(l.months.find(m=>m.month===map.month)?.meanPercent)))))text+='<strong class="seas-gap">'+(mn?.chartDays===0?'No source chart dates for '+month+'.':'Insufficient chart coverage for '+month+'.')+' Hatched water has no estimate.</strong>';
      }
      return '<div class="seas-key '+k+'"><div class="seas-key-title">'+esc(month)+' '+esc(o.unit)+' <small>'+esc(o.source)+'</small></div>'+text+'</div>';
    }).join('');
    if(legends.innerHTML!==html)legends.innerHTML=html;
    if(!map.selected||!active.length){readout.hidden=true;readout.textContent='';return;}
    readout.hidden=false;readout.innerHTML='<span class="eyebrow">SEASONAL OVERLAYS · '+esc(month.toUpperCase())+'</span>'+rows().map(r=>'<div><strong>'+esc(r.label)+'</strong><span>'+esc(r.valueText)+'</span>'+(r.coverageText?'<small>'+esc(r.coverageText)+'</small>':'')+'</div>').join('');
  }
  function buffer(k,map){
    const s=state[k],data=s.data;if(!data?.grid)return null;
    if(s.proj!==map.project||s.hydro!==map.hydroPaths){s.cache.clear();s.proj=map.project;s.hydro=map.hydroPaths;s.corners=gridCorners(data.grid,map.project);}
    if(s.cache.has(map.month))return s.cache.get(map.month);
    const g=data.grid,m=data.months.find(v=>v.month===map.month),n=g.width+1,[image,c]=makeCanvas(map.w,map.h);
    c.save();if(k==='snow')c.clip(map.union,'evenodd');
    const paths=Array.from({length:6},()=>new Path2D()),counts=new Uint16Array(6),shade=hatch(c);
    function flush(b){if(!counts[b])return;c.fillStyle=b===5?shade:sources[k].colors[b];c.fill(paths[b]);paths[b]=new Path2D();counts[b]=0;}
    function paint(onlyLakeId){
      for(let r=0;r<g.height;r++)for(let col=0;col<g.width;col++){
        const i=r*g.width+col,v=m.values[i];if(k==='snow'&&v===0||k==='ice'&&v===null||onlyLakeId!=null&&Number(g.lakeIds[i])!==Number(onlyLakeId))continue;
        const b=v===null?5:bin(v);markCell(paths[b],s.corners,n,i,r);if(++counts[b]>=256)flush(b);
      }
      for(let b=0;b<6;b++)flush(b);
    }
    if(k==='ice'&&g.lakeIds){for(const lake of relevantLakes(map,s)){
      const info=lakeInfo(s,lake);if(info?.id==null)continue;c.save();c.clip(lake.path,'evenodd');paint(info.id);c.restore();
    }}else paint(null);
    c.restore();
    if(k==='snow'){
      c.save();c.globalCompositeOperation='destination-out';c.fillStyle='#000';for(const lake of map.hydroPaths)if(lake.kind==='lake')c.fill(lake.path,'evenodd');c.restore();
    }
    s.cache.set(map.month,image);while(s.cache.size>2)s.cache.delete(s.cache.keys().next().value);
    return image;
  }
  function drawable(k,map){return state[k].active&&state[k].phase==='ready'&&map.project&&map.hydroReady;}
  function drawSnow(ctx){
    const map=getMap();if(!drawable('snow',map))return;
    const image=buffer('snow',map);if(!image)return;ctx.save();
    if(map.base==='landcover'&&map.perennialClip)ctx.clip(map.perennialClip(),'evenodd');
    ctx.globalAlpha=opacity;ctx.imageSmoothingEnabled=false;ctx.drawImage(image,0,0,map.w,map.h);ctx.restore();
  }
  function drawIce(ctx){
    const map=getMap();if(!drawable('ice',map))return;
    const s=state.ice,grid=s.data.grid,image=grid?buffer('ice',map):null;
    const key='ice-composite-'+map.month;let composite=s.cache.get(key);
    const shapes=relevantLakes(map,s);
    if(!composite){
      const [canvas,layer]=makeCanvas(map.w,map.h);layer.fillStyle=hatch(layer);
      for(const lake of shapes){
        const v=grid?null:lakeMonth(s,lake,map.month)?.meanPercent;
        layer.fillStyle=valid(v)?sources.ice.colors[bin(v)]:hatch(layer);layer.fill(lake.path,'evenodd');
      }
      if(image){layer.imageSmoothingEnabled=false;layer.drawImage(image,0,0,map.w,map.h);}
      composite=canvas;s.cache.set(key,composite);while(s.cache.size>4)s.cache.delete(s.cache.keys().next().value);
    }
    ctx.save();ctx.setLineDash([]);ctx.globalAlpha=opacity;ctx.imageSmoothingEnabled=false;ctx.drawImage(composite,0,0,map.w,map.h);
    ctx.lineWidth=.8/Math.max(.1,map.pixelScale);ctx.strokeStyle='#287a85';for(const lake of shapes)ctx.stroke(lake.path);ctx.restore();
  }
  return api;
}
