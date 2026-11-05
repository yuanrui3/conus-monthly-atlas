'use strict';
import {renderEvidenceCoverage} from './evidence.js';
import {readAtlasJSON} from './month_data.js';
import {createSeasonalOverlays} from './seasonal_overlays.js';
(function () {
  const $ = id => document.getElementById(id);
  const W = 1200, H = 740, RAD = Math.PI / 180;
  const canvas = $('map-canvas'), stage = $('map-stage'), ctx = canvas.getContext('2d');
  const hit = document.createElement('canvas').getContext('2d');
  const view = { zoom: 1, x: 0, y: 0, units: 'metric', layer: 'landcover', selected: null, scenario: 'operating', water: 'unknown', tab: 'map' };
  const months=['January','February','March','April','May','June','July','August','September','October','November','December'];
  let month=11, climateStatus='loading', climateToken=0, controller=null;
  const name=()=>months[month-1], isClimate=id=>id!=='landcover'&&id!=='elevation'&&id!=='slope';
  const monthlyFile=n=>n===11?'data/climate.json':'data/climate_months/'+String(n).padStart(2,'0')+'.json.gz';
  const monthCache=new Map();
  const pendingText=()=>climateStatus==='error'?name()+' climate unavailable':name()+' climate loading…';
  window.NovemberAtlas={units:'metric',month,monthName:name(),selection:null,openView:tab=>switchView(tab)};
  let climate, elevation, landcover, boundary, features = [], hydroPaths = [], hydroMetadata, union, project, invert, viewport = { s: 1, x: 0, y: 0 }, activeBase;
  let slope=null, slopeState='idle';
  const slopePending=()=>slopeState==='error'?'Terrain slope unavailable. Select Terrain slope to retry.':'Loading terrain slope…';
  const caches = new Map(), cornerCache = new Map();
  const palette = {
    precip_mm: ['#edf0d4','#b7d7bc','#70b6a3','#337f7b','#174b5b'],
    temperature: ['#31566e','#dce9df','#d7bd6f','#a3543a'],
    slope: ['#eef2d8','#c6d6a6','#d8c48b','#c7935f','#aa623e','#773837'],
    elevation: ['#d5e7df','#e1e6bd','#c9ce9e','#b1ae7c','#9e8d67','#7c6a55']
  };
  const names = { landcover: 'Land cover & wetlands', precip_mm: 'Average precipitation', mean_temp_c: 'Mean temperature', max_temp_c: 'Mean daily high', min_temp_c: 'Mean daily low', elevation: 'Elevation context', slope:'Terrain slope' };
  const shortNames = { mean_temp_c: 'Mean temperature', min_temp_c: 'Mean daily low', max_temp_c: 'Mean daily high', precip_mm: 'Monthly total', elevation: 'Elevation context', slope:'Terrain slope' };
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function number(n, digits) { return new Intl.NumberFormat('en-US',{maximumFractionDigits: digits == null ? 1 : digits, minimumFractionDigits: 0}).format(n); }
  function converted(v, id) { if (id==='slope'||view.units === 'metric') return v; return id === 'precip_mm' ? v / 25.4 : id === 'elevation' ? v * 3.280839895 : v * 1.8 + 32; }
  function unit(id) { if(id==='landcover')return '';if(id==='slope')return '°';return id === 'precip_mm' ? (view.units === 'metric' ? 'mm' : 'in') : id === 'elevation' ? (view.units === 'metric' ? 'm' : 'ft') : (view.units === 'metric' ? '°C' : '°F'); }
  function valueText(v,id,digits) { if(id==='landcover')return landcover?.classes.find(c=>c.value===v)?.label||'No data';return v == null || !Number.isFinite(v) ? 'No data' : number(converted(v,id), digits == null ? (id === 'slope' ? 2 : id === 'elevation' ? 0 : 1) : digits); }
  function layerInfo(id) { if(id==='landcover')return {description:'2025 coarse service land-cover class. Local composition and native-pixel correspondence are unverified; small patches, narrow streams, tree spacing and understory are unresolved.'};if(id==='slope')return slope?.variables.slope; if (id === 'elevation') return elevation && elevation.variables.elevation; return climate && climate.layers.find(l => l.id === id); }
  function gridFor(id) { return id === 'slope' ? slope.grid : id === 'landcover' ? landcover.grid : id === 'elevation' ? elevation.grid : climate.grid; }
  function valuesFor(id) { return id === 'slope' ? slope.variables.slope.values : id === 'landcover' ? landcover.grid.values.landcover : id === 'elevation' ? elevation.variables.elevation.values : climate.grid.values[id]; }
  function domain(id) { return id === 'slope' ? [0,30] : id === 'precip_mm' ? [0,200] : id === 'elevation' ? [-500,4500] : [-35,45]; }
  function colors(id) { return palette[id] || palette.temperature; }
  function interpolateColor(stops,t) {
    t=Math.min(1,Math.max(0,t)); const q=t*(stops.length-1), i=Math.min(stops.length-2,Math.floor(q)), f=q-i;
    const a=stops[i].slice(1), b=stops[i+1].slice(1), rgb=[];
    for(let c=0;c<3;c++) rgb.push(Math.round(parseInt(a.slice(c*2,c*2+2),16)*(1-f)+parseInt(b.slice(c*2,c*2+2),16)*f));
    return 'rgb('+rgb.join(',')+')';
  }
  function eachRing(geometry,fn) {
    if (geometry.type==='Polygon') geometry.coordinates.forEach(fn);
    else if (geometry.type==='MultiPolygon') geometry.coordinates.forEach(p => p.forEach(fn));
  }
  function setupProjection() {
    const p1=29.5*RAD, p2=45.5*RAD, p0=23*RAD, l0=-96*RAD;
    const n=(Math.sin(p1)+Math.sin(p2))/2, C=Math.cos(p1)**2+2*n*Math.sin(p1), r0=Math.sqrt(C-2*n*Math.sin(p0))/n;
    function raw(lon,lat) { const r=Math.sqrt(C-2*n*Math.sin(lat*RAD))/n, t=n*(lon*RAD-l0); return [r*Math.sin(t),r0-r*Math.cos(t)]; }
    let x0=Infinity,x1=-Infinity,y0=Infinity,y1=-Infinity;
    boundary.features.forEach(f => eachRing(f.geometry,ring => ring.forEach(c => {const p=raw(c[0],c[1]);x0=Math.min(x0,p[0]);x1=Math.max(x1,p[0]);y0=Math.min(y0,p[1]);y1=Math.max(y1,p[1]);})));
    const scale=Math.min((W-98)/(x1-x0),(H-122)/(y1-y0)), tx=(W-scale*(x1+x0))/2, ty=(H+scale*(y1+y0))/2-7;
    project=(lon,lat)=>{const p=raw(lon,lat);return [tx+scale*p[0],ty-scale*p[1]];};
    invert=(x,y)=>{const rx=(x-tx)/scale, ry=(ty-y)/scale, r=Math.sqrt(rx*rx+(r0-ry)**2), t=Math.atan2(rx,r0-ry);return [(l0+t/n)/RAD,Math.asin(Math.max(-1,Math.min(1,(C-r*r*n*n)/(2*n))))/RAD];};
    union=new Path2D();
    features=boundary.features.map(f=>{
      const path=new Path2D(); let bx0=Infinity,bx1=-Infinity,by0=Infinity,by1=-Infinity,bestArea=0,label=null;
      eachRing(f.geometry,ring=>{
        const pts=ring.map(c=>project(c[0],c[1])); let a=0,cx=0,cy=0;
        pts.forEach((p,i)=>{if(i===0)path.moveTo(p[0],p[1]);else path.lineTo(p[0],p[1]);bx0=Math.min(bx0,p[0]);bx1=Math.max(bx1,p[0]);by0=Math.min(by0,p[1]);by1=Math.max(by1,p[1]);const q=pts[(i+1)%pts.length],cross=p[0]*q[1]-q[0]*p[1];a+=cross;cx+=(p[0]+q[0])*cross;cy+=(p[1]+q[1])*cross;});path.closePath();
        if(Math.abs(a)>bestArea){bestArea=Math.abs(a);label=Math.abs(a)>0.0001?[cx/(3*a),cy/(3*a)]:pts[0];}
      });
      union.addPath(path);
      return {path,name:f.properties.name||f.properties.NAME,abbr:f.properties.STUSPS||'',id:f.properties.GEOID||f.properties.STATEFP,bounds:[bx0,by0,bx1,by1],label:label||[(bx0+bx1)/2,(by0+by1)/2],area:bestArea/2};
    });
    features.slice().sort((a,b)=>a.name.localeCompare(b.name)).forEach(f=>{const o=document.createElement('option');o.value=f.id;o.textContent=f.name;$('state-select').appendChild(o);});
  }
  function findState(x,y) { return features.find(f=> x>=f.bounds[0]&&x<=f.bounds[2]&&y>=f.bounds[1]&&y<=f.bounds[3]&&hit.isPointInPath(f.path,x,y,'evenodd')); }
  function gridCorners(id) {
    const key=isClimate(id)?'climate':id; if(cornerCache.has(key)) return cornerCache.get(key);
    const g=gridFor(id), dx=g.lon[1]-g.lon[0],dy=g.lat[0]-g.lat[1], cols=g.width+1, points=new Float32Array(cols*(g.height+1)*2);
    for(let r=0;r<=g.height;r++)for(let c=0;c<=g.width;c++){const p=project(g.lon[0]-dx/2+c*dx,g.lat[0]+dy/2-r*dy),i=(r*cols+c)*2;points[i]=p[0];points[i+1]=p[1];}
    cornerCache.set(key,points);return points;
  }
  function buildBase(id) {
    if(caches.has(id))return caches.get(id);
    const buffer=document.createElement('canvas');buffer.width=W*1.5;buffer.height=H*1.5;const b=buffer.getContext('2d');b.scale(1.5,1.5);
    b.save();b.clip(union,'evenodd');b.fillStyle='#dfe7d4';b.fillRect(0,0,W,H);b.strokeStyle='#bfcdaf';b.lineWidth=.55;
    b.beginPath();for(let x=-H;x<W+H;x+=6){b.moveTo(x,0);b.lineTo(x+H,H);}b.stroke();if(id==='landcover'){b.restore();b.save();}
    const categorical=id==='landcover', g=gridFor(id),vals=valuesFor(id),p=gridCorners(id),cols=g.width+1,N=categorical?landcover.classes.length:144,paths=Array.from({length:N},()=>new Path2D()),range=domain(id),classIndex=new Map(categorical?landcover.classes.map((c,i)=>[c.value,i]):[]);
    const pathCounts=new Uint16Array(N);function flush(k){if(!pathCounts[k])return;b.fillStyle=categorical?landcover.classes[k].color:interpolateColor(colors(id),k/(N-1));b.fill(paths[k]);if(!categorical){b.strokeStyle=b.fillStyle;b.lineWidth=.18;b.stroke(paths[k]);}paths[k]=new Path2D();pathCounts[k]=0;}
    for(let r=0;r<g.height;r++)for(let c=0;c<g.width;c++){
      const v=vals[r*g.width+c];if(v==null||!Number.isFinite(v))continue;
      const k=categorical?classIndex.get(v):Math.round(Math.max(0,Math.min(1,(v-range[0])/(range[1]-range[0])))*(N-1));if(k==null)continue;
      const a=(r*cols+c)*2,d=((r+1)*cols+c)*2,q=paths[k];q.moveTo(p[a],p[a+1]);q.lineTo(p[a+2],p[a+3]);q.lineTo(p[d+2],p[d+3]);q.lineTo(p[d],p[d+1]);q.closePath();pathCounts[k]++;if(pathCounts[k]>=384)flush(k);
    }
    paths.forEach((p,i)=>flush(i));b.restore();caches.set(id,buffer);return buffer;
  }
  let perennialKeepClip=null,hydroFailed=false;
  function clippedPerennial(){
    if(perennialKeepClip||!landcover||!project)return perennialKeepClip;
    const g=landcover.grid,values=valuesFor('landcover'),points=gridCorners('landcover'),n=g.width+1;
    const path=new Path2D();path.rect(-W,-H,W*3,H*3);
    for(let i=0;i<values.length;i++)if(values[i]===12){
      const r=Math.floor(i/g.width),a=(i+r)*2,b=a+2,c=b+2*n,d=a+2*n;
      path.moveTo(points[a],points[a+1]);path.lineTo(points[b],points[b+1]);path.lineTo(points[c],points[c+1]);path.lineTo(points[d],points[d+1]);path.closePath();
    }
    perennialKeepClip=path;return path;
  }
  const seasonal=createSeasonalOverlays({controls:$('seasonal-controls'),readout:$('seasonal-readout'),
    getMap:()=>({w:W,h:H,project,hit,union,hydroPaths,hydroReady:!!hydroMetadata,hydroFailed,pixelScale:viewport.s*view.zoom,base:view.layer,month,selected:view.selected,selectedPerennial:view.selected&&lookup(view.selected.lon,view.selected.lat,'landcover').value===12,perennialClip:clippedPerennial}),
    redraw:()=>{if(project){updateInspector();render();}}
  });
  function resize() {
    const rect=stage.getBoundingClientRect();if(!rect.width||!rect.height)return;const dpr=Math.min(window.devicePixelRatio||1,2);
    canvas.width=Math.round(rect.width*dpr);canvas.height=Math.round(rect.height*dpr);
    const s=Math.min(rect.width/W,rect.height/H);viewport={s,x:(rect.width-W*s)/2,y:(rect.height-H*s)/2,dpr};render();
  }
  function render() {
    if(!project)return;
    ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.setTransform(viewport.dpr*viewport.s,0,0,viewport.dpr*viewport.s,viewport.dpr*viewport.x,viewport.dpr*viewport.y);
    ctx.translate(view.x,view.y);ctx.scale(view.zoom,view.zoom);if(activeBase)ctx.drawImage(activeBase,0,0,W,H);
    seasonal.drawSnow(ctx);drawHydro();
    ctx.lineWidth=.75/Math.sqrt(view.zoom);ctx.strokeStyle='rgba(255,255,247,.76)';features.forEach(f=>ctx.stroke(f.path));
    ctx.lineWidth=.45/Math.sqrt(view.zoom);ctx.strokeStyle='rgba(69,91,64,.4)';ctx.stroke(union);
    const font=10.5/Math.sqrt(view.zoom);ctx.font='600 '+font+'px ui-sans-serif,system-ui,sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';
    features.forEach(f=>{if(f.area*view.zoom*view.zoom<1000)return;ctx.lineWidth=2/view.zoom;ctx.strokeStyle='rgba(251,253,239,.65)';ctx.strokeText(f.abbr,f.label[0],f.label[1]);ctx.fillStyle='rgba(41,68,49,.72)';ctx.fillText(f.abbr,f.label[0],f.label[1]);});
    if(view.selected){const p=project(view.selected.lon,view.selected.lat);ctx.beginPath();ctx.arc(p[0],p[1],7/view.zoom,0,2*Math.PI);ctx.strokeStyle='#fffef6';ctx.lineWidth=4/view.zoom;ctx.stroke();ctx.strokeStyle='#223f35';ctx.lineWidth=1.6/view.zoom;ctx.stroke();ctx.beginPath();ctx.arc(p[0],p[1],2/view.zoom,0,2*Math.PI);ctx.fillStyle='#223f35';ctx.fill();}
  }
  function lookup(lon,lat,id) {
    if((id==='slope'&&!slope)||(isClimate(id)&&!climate)||(id==='landcover'&&!landcover)||(id==='elevation'&&!elevation))return {value:null,years:0};
    const g=gridFor(id),dx=g.lon[1]-g.lon[0],dy=g.lat[0]-g.lat[1],col=Math.round((lon-g.lon[0])/dx),row=Math.round((g.lat[0]-lat)/dy);
    if(col<0||row<0||col>=g.width||row>=g.height)return {value:null,years:0};const i=row*g.width+col;
    return {value:valuesFor(id)[i],years:g.validYears?.[id]?.[i]??null,sourceCells:g.sourceCellCount?.[i]??null,sd:g.interannualStdDev?.[id]?.[i]??null,lon:g.lon[col],lat:g.lat[row],index:i};
  }
  window.NovemberAtlas.readClimate=(lon,lat)=>{
    if(!climate)return {month,monthName:name(),status:climateStatus,temperature:null,precipitation:null};
    const read=id=>{if(!Number.isFinite(lon)||!Number.isFinite(lat))return null;const v=lookup(lon,lat,id);return Number.isFinite(v.value)&&v.years===20?valueText(v.value,id)+' '+unit(id):null;};
    return {month,monthName:name(),status:'ready',temperature:read('mean_temp_c'),precipitation:read('precip_mm')};
  };
  async function requestSlope(retry=false) {
    if(slope||slopeState==='loading'||(slopeState==='error'&&!retry))return;
    slopeState='loading';
    try{
      const d=await readAtlasJSON('data/regional_slope.json.gz'),g=d?.grid,l=d?.variables?.slope;
      if(!g||!l||g.width<2||g.height<2||g.lon?.length!==g.width||g.lat?.length!==g.height||g.lon[1]<=g.lon[0]||g.lat[1]>=g.lat[0]||l.values?.length!==g.width*g.height||!Number.isFinite(l.min)||!Number.isFinite(l.max)||l.min<0||l.max>90)throw Error('Slope grid or units could not be verified.');
      slope=d;slopeState='ready';
    }catch(e){slopeState='error';console.warn('Terrain slope:',e);}
    if(project){if(view.layer==='slope')setLayer('slope');else if(view.selected)updateInspector();}
  }
  function setLayer(id) {
    if(!project||!elevation||(id==='landcover'&&!landcover))return;view.layer=id;if(id==='slope'&&!slope)requestSlope();activeBase=(isClimate(id)&&!climate)||(id==='slope'&&!slope)?null:buildBase(id);updateLegend();updateInspector();render();
    document.querySelectorAll('[data-layer]').forEach(b=>{const on=b.dataset.layer===id;b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on));});
    $('tooltip').hidden=true;$('announcer').textContent=id==='slope'&&!slope?slopePending():names[id]+' layer displayed.';
  }
  function updateLegend() {
    const id=view.layer,categorical=id==='landcover';$('map-title').textContent=names[id];
    $('map-kicker').textContent=categorical?'LANDSCAPE SNAPSHOT · 2025':id==='slope'?'TERRAIN FORM · STATIC':id==='elevation'?'STATIC RELIEF · 2009 MODEL':name().toUpperCase()+' CLIMATOLOGY · 2006–2025';
    $('source-chip').innerHTML='<i class="dot"></i>'+(categorical?'USGS Annual NLCD':id==='slope'?'USGS 3DEP':id==='elevation'?'NOAA ETOPO1':'NOAA nClimGrid');
    $('legend-title').textContent=categorical?'Land-cover classes':id==='slope'?'Mean terrain slope':id==='elevation'?'Elevation above mean sea level':id==='precip_mm'?name()+' precipitation':names[id];
    $('legend-unit').textContent=categorical?'2025 categorical overview':unit(id)+(id==='precip_mm'?' / month':'');
    $('landcover-legend').hidden=!categorical;$('legend-gradient').hidden=categorical;$('legend-ticks').hidden=categorical;
    $('landcover-legend').closest('.legend-area').classList.toggle('categorical',categorical);
    if(categorical){
      $('landcover-legend').innerHTML=landcover.classes.map(c=>'<span><i style="background:'+esc(c.color)+'"></i>'+esc(c.label)+'</span>').join('');
      $('resolution-label').textContent='~4–7 km overview · 30 m source in local detail';
      $('map-footnote').textContent='Blue rivers and lakes are a separate generalized map layer. Open Land & water detail for finer USGS land cover with local water geometry.';
      return;
    }
    $('legend-gradient').style.background='linear-gradient(90deg,'+colors(id).join(',')+')';
    const ticks=id==='slope'?[0,6,12,18,24,30]:id==='precip_mm'?[0,50,100,150,200]:id==='elevation'?[-500,500,1500,2500,3500,4500]:[-35,-15,5,25,45];
    $('legend-ticks').innerHTML=ticks.map((t,i)=>'<span>'+(id==='slope'&&i===ticks.length-1?'≥':'')+(isClimate(id)&&(i===ticks.length-1||i===0&&id!=='precip_mm')?(i===0?'≤':'≥'):'')+esc(valueText(t,id,id==='elevation'?0:1))+'</span>').join('');
    $('resolution-label').textContent=id==='slope'?'0.05° overview · 500 m terrain samples':id==='elevation'?'0.1° sample spacing (~11 km)':'~9 km overview · ~5 km source';
    $('map-footnote').textContent=id==='slope'?(slope?'Cell means of terrain slope in degrees. Final color includes slopes ≥30°. Select a place for its numeric estimate.':slopePending()):id==='precip_mm'?'Color scale caps at '+valueText(200,id)+' '+unit(id)+'/month. Click for exact values.':id==='elevation'?'Sampled relief; local peaks, slope and coastal detail are unresolved.':'The color scale stays fixed across months; end colors include values beyond the labeled range. Select a location for its estimate.';
    if(isClimate(id)&&!climate)$('map-footnote').textContent=pendingText()+'.';
  }
  function updateLandcoverInspector(){
    if(!landcover)return;
    const node=$('location-landcover');
    if(!view.selected){node.innerHTML='<span class="eyebrow">LANDSCAPE CONTEXT · 2025</span><strong>Forest, wetland, grassland &amp; crops</strong><p>Pick a location to inspect the overview class, then open Land &amp; water detail for the finer 30 m source. Vegetation structure and seasonal state remain unknown.</p>';return;}
    const value=lookup(view.selected.lon,view.selected.lat,'landcover').value,category=landcover.classes.find(c=>c.value===value);
    node.innerHTML='<span class="eyebrow">SERVICE OVERVIEW CLASS · 2025</span><strong>'+(category?'<i style="background:'+esc(category.color)+'"></i>'+esc(category.label):'No source class')+'</strong><p>This overview has ~4–7 km spacing. Open local detail to retrieve finer land cover from the 30 m USGS source. A blue river line is separate cartographic context and can cross a cell with another land-cover category. '+esc(category?.description?.replace(/\bNovember\b/g,'seasonal')||'No source class is available here.')+'</p>';
  }
  function hydroPath(feature) {
    const geometry=feature.geometry, props=feature.properties||{}, path=new Path2D();let bounds=[Infinity,Infinity,-Infinity,-Infinity],bestLabel=null,bestSize=0;
    const isLake=props.kind==='lake',parts=isLake?(geometry.type==='Polygon'?[geometry.coordinates]:geometry.type==='MultiPolygon'?geometry.coordinates:[]):(geometry.type==='LineString'?[[geometry.coordinates]]:geometry.type==='MultiLineString'?[geometry.coordinates]:[]);
    for(const part of parts) for(let ringIndex=0;ringIndex<part.length;ringIndex++){
      const coords=part[ringIndex];if(!coords.length)continue;const points=coords.map(c=>project(c[0],c[1]));let size=0,cx=0,cy=0;
      points.forEach((p,i)=>{if(i===0)path.moveTo(p[0],p[1]);else path.lineTo(p[0],p[1]);bounds=[Math.min(bounds[0],p[0]),Math.min(bounds[1],p[1]),Math.max(bounds[2],p[0]),Math.max(bounds[3],p[1])];
        if(isLake){const q=points[(i+1)%points.length],cross=p[0]*q[1]-q[0]*p[1];size+=cross;cx+=(p[0]+q[0])*cross;cy+=(p[1]+q[1])*cross;}else if(i)size+=Math.hypot(p[0]-points[i-1][0],p[1]-points[i-1][1]);
      });
      if(isLake)path.closePath();
      if((!isLake||ringIndex===0)&&Math.abs(size)>bestSize){bestSize=Math.abs(size);bestLabel=isLake&&Math.abs(size)>.001?[cx/(3*size),cy/(3*size)]:points[Math.floor(points.length/2)];}
    }
    return {path,bounds,kind:props.kind,name:props.name||'',rank:Number.isFinite(props.scaleRank)?props.scaleRank:10,intermittent:/intermittent/i.test(props.featureClass||''),label:bestLabel,size:bestSize};
  }
  async function loadHydro(){
    const status=$('overview-water-status'),toggle=$('overview-show-water');
    try{
      const [data,metadata]=await Promise.all(['hydro_overview.geojson','hydro_overview_metadata.json'].map(async file=>{const response=await fetch('data/'+file);if(!response.ok)throw new Error('HTTP '+response.status+' for '+file);return response.json();}));
      if(data.type!=='FeatureCollection'||!Array.isArray(data.features))throw new Error('Incomplete water geometry');
      hydroMetadata=metadata;hydroPaths=data.features.filter(f=>f.geometry&&['river','lake'].includes(f.properties?.kind)).map(hydroPath);
      if(status)status.textContent='Natural Earth rivers & lakes · generalized 1:10 million map context';seasonal.refresh();updateInspector();render();
    }catch(error){hydroFailed=true;if(status)status.textContent='Water map unavailable: '+error.message;if(toggle)toggle.checked=false;seasonal.refresh();updateInspector();render();}
  }
  function drawHydro(){
    if(!hydroPaths.length||!$('overview-show-water')?.checked){seasonal.drawIce(ctx);return;}
    const pixel=1/(viewport.s*view.zoom),visible=hydroPaths.filter(f=>f.bounds[2]*view.zoom+view.x>=0&&f.bounds[0]*view.zoom+view.x<=W&&f.bounds[3]*view.zoom+view.y>=0&&f.bounds[1]*view.zoom+view.y<=H);
    ctx.save();ctx.lineJoin='round';ctx.lineCap='round';
    for(const f of visible)if(f.kind==='lake'){ctx.fillStyle='#9fc9e0';ctx.fill(f.path,'evenodd');ctx.lineWidth=.65*pixel;ctx.strokeStyle='#3d89af';ctx.stroke(f.path);}
    seasonal.drawIce(ctx);
    for(const f of visible)if(f.kind==='river'){
      ctx.setLineDash(f.intermittent?[4*pixel,3*pixel]:[]);ctx.lineWidth=(f.rank<=2?1.65:f.rank<=5?1.15:.8)*pixel;ctx.strokeStyle=f.rank<=2?'rgba(33,112,157,.95)':'rgba(48,126,165,.82)';ctx.stroke(f.path);
    }
    ctx.setLineDash([]);
    const labels=visible.filter(f=>f.name&&f.label&&(f.kind==='lake'?f.size*view.zoom*view.zoom>400:f.rank<=(view.zoom<2?2:5)&&f.size*view.zoom>90)).sort((a,b)=>a.rank-b.rank||b.size-a.size),usedNames=new Set(),boxes=[];
    ctx.font='italic '+(10*pixel)+'px ui-sans-serif,system-ui,sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';
    for(const f of labels){if(usedNames.has(f.name)||boxes.length>=24)continue;const [x,y]=f.label,sx=x*view.zoom+view.x,sy=y*view.zoom+view.y;if(sx<25||sx>W-25||sy<15||sy>H-15)continue;
      const width=ctx.measureText(f.name).width,box=[x-width/2-4*pixel,y-7*pixel,x+width/2+4*pixel,y+7*pixel];if(boxes.some(b=>box[0]<b[2]&&box[2]>b[0]&&box[1]<b[3]&&box[3]>b[1]))continue;
      boxes.push(box);usedNames.add(f.name);ctx.lineWidth=3*pixel;ctx.strokeStyle='rgba(246,250,241,.93)';ctx.strokeText(f.name,x,y);ctx.fillStyle='#246689';ctx.fillText(f.name,x,y);
    }
    ctx.restore();
  }
  $('overview-show-water')?.addEventListener('change',render);
  function metric(id,v,isRange) {
    let val;if(isRange){val=valueText(v[0],id,0)+'–'+valueText(v[1],id,0);}else val=valueText(v,id);
    return '<div class="metric'+(isRange?' range':'')+(id==='elevation'?' elevation-metric':'')+'"><span class="metric-label">'+esc(shortNames[id])+'</span><span class="metric-value">'+esc(val)+(v==null?'':'<small>'+esc(unit(id))+'</small>')+'</span></div>';
  }
  function updateEvidenceCoverage() {
    const selected=view.selected, point=selected?{lon:selected.lon,lat:selected.lat}:null;
    const sample=id=>point?lookup(point.lon,point.lat,id):null;
    const temperature=sample('mean_temp_c'),rain=sample('precip_mm'),relief=sample('elevation'),incline=sample('slope');
    const cover=landcover?sample('landcover'):null;
    const category=cover&&landcover.classes.find(item=>item.value===cover.value);
    const present=result=>result!=null&&Number.isFinite(result.value);
    const valueStatus=result=>!climate?climateStatus==='loading'?'loading':'missing':!point?'select':present(result)&&result.years===20?'available':'missing';
    const climateValue=(result,id)=>!climate?pendingText():!point?'Choose a map location':present(result)&&result.years===20?valueText(result.value,id)+' '+unit(id):'No complete-baseline estimate';
    const baselineNote=result=>!climate?'No value is displayed until the selected month’s data are available.':!point?'A selected cell is checked against its own valid-year record.':present(result)&&result.years===20?'All 20 years contribute to this '+name()+' estimate.':'A missing or incomplete estimate remains unknown.';
    renderEvidenceCoverage($('overview-evidence'),{
      locationLabel:selected?(selected.state?selected.state.name+' · selected overview cell':'Selected overview cell'):'Select a map location to check the available evidence',
      point,
      fields:[
        {id:'landcover',label:'Land cover',status:!landcover?'missing':!point?'select':category?'available':'missing',valueText:!landcover?'Source unavailable':!point?'Choose a map location':category?.label||'No overview class',period:'2025 landscape snapshot',support:'About 4–7 km overview spacing',note:'This panel reports the coarse overview class. The separate local view uses imagery from 30 m source cells.'},
        {id:'temperature',label:'Mean outdoor temperature',status:valueStatus(temperature),valueText:climateValue(temperature,'mean_temp_c'),period:name()+' 2006–2025',support:'About 9 km overview grid · about 5 km native',note:baselineNote(temperature)},
        {id:'precipitation',label:'Average '+name()+' precipitation',status:valueStatus(rain),valueText:climateValue(rain,'precip_mm'),period:name()+' 2006–2025',support:'About 9 km overview grid · about 5 km native',note:baselineNote(rain)+' This is precipitation, not a soil-moisture observation.'},
        {id:'elevation',label:'Elevation context',status:!point?'select':present(relief)?'available':'missing',valueText:!point?'Choose a map location':present(relief)?valueText(relief.value,'elevation')+' '+unit('elevation'):'No relief sample',period:'2009 relief model',support:'0.1° sample spacing · about 11 km north–south',note:'A sampled elevation supplies broad relief context. Local slope and roughness are unresolved; some coastal or lake-edge values may be bathymetry.'},
        {id:'slope',label:'Terrain slope',status:!point?'select':slopeState==='error'?'missing':!slope?'loading':present(incline)?'available':'missing',valueText:!point?'Choose a map location':!slope?slopePending():present(incline)?valueText(incline.value,'slope')+'°':'No terrain slope estimate',period:'Static terrain · USGS 3DEP',support:'0.05° overview · 500 m terrain samples',note:'Mean of Horn 3×3 slope angles from a 500 m elevation grid. Each overview cell is about 5.6 km north–south. Local gradients and roughness can vary within a cell.'},
        ...seasonal.evidenceFields()
      ],
      missing:[
        {label:'Soil condition',detail:'Soil properties, actual moisture and freeze state have not been loaded.'},
        {label:'Fine-scale terrain shape',detail:'The regional slope layer gives broad cell averages. Fine-scale grades and surface roughness are not resolved.'},
        {label:'Snow depth and ice thickness',detail:'Snow-cover frequency and Great Lakes surface ice concentration are separate map overlays. Snow depth, water equivalent and ice thickness are not measured here.'},
        {label:'Vegetation structure',detail:'Tree spacing, understory, vegetation height and seasonal crop condition have not been measured.'},
        {label:'Additional weather evidence',detail:'Storm events, humidity, wind and solar layers have not been loaded.'},
        {label:'Occupant measurements',detail:'Cabin conditions and actual drinking-water availability remain unmeasured; selectable scenarios are assumptions.'}
      ],
      inspectionNotes:[
        'Water geometry, bridge inventory points and gauge observations are inspected separately in Land & water detail. They do not provide a continuous local water-condition field.',
        'Developed land-cover categories show mixtures of constructed surfaces and vegetation. Individual building footprints and road or rail geometry are excluded.'
      ]
    });
  }
  function updateInspector() {
    if(!project)return;updateLandcoverInspector();seasonal.refresh();const ids=['mean_temp_c','precip_mm','max_temp_c','min_temp_c'];if(view.layer==='elevation'||view.layer==='slope')ids.unshift(view.layer);let description='';
    $('clear-selection').hidden=!view.selected;$('overview-to-detail').disabled=!view.selected;
    if(!view.selected){
      $('inspection-eyebrow').textContent='NATIONAL OVERVIEW';$('location-title').textContent='Explore a place';$('location-subtitle').textContent='Click a map cell or choose a state. Ranges below span the mapped cells of each source.';
      $('location-metrics').innerHTML=ids.map(id=>{const l=layerInfo(id);return l?metric(id,[l.min,l.max],true):metric(id,null,false);}).join('');
      $('location-coverage').textContent=climate?'✓ All 20 years in every displayed '+name()+' climate estimate.':pendingText()+'.';
      description='This is a custom 20-year baseline, not an official 30-year climate normal. Values describe outdoor conditions.';
      $('crew-location').textContent='No place selected';$('crew-location-note').textContent='Select a location on the map to bring its climate values here.';$('crew-values').innerHTML='';
    }else{
      const s=view.selected,selected=lookup(s.lon,s.lat,view.layer),hasClimate=lookup(s.lon,s.lat,'mean_temp_c');
      $('inspection-eyebrow').textContent='SELECTED GRID CELL';$('location-title').textContent=s.state?s.state.name:'Selected location';$('location-subtitle').textContent=number(s.lat,2)+'° N · '+number(Math.abs(s.lon),2)+'° W · values for this cell';
      $('location-metrics').innerHTML=ids.map(id=>metric(id,lookup(s.lon,s.lat,id).value,false)).join('');
      const ev=lookup(s.lon,s.lat,'elevation');
      if(view.layer==='landcover')$('location-coverage').textContent='Land cover: 2025 snapshot · coarse service class. Climate values below retain their own 20-year support.';else if(view.layer==='elevation')$('location-coverage').textContent='Elevation: '+valueText(ev.value,'elevation')+(ev.value==null?'':' '+unit('elevation'))+' · 2009 relief model.';
      else if(view.layer==='slope')$('location-coverage').textContent=slope?'Static terrain · average slope within a 0.05° cell.':slopePending();
      else $('location-coverage').textContent=hasClimate.value==null?'No full-baseline climate value at this location.':'✓ '+hasClimate.years+' / 20 years for '+name()+' · '+hasClimate.sourceCells+' source '+(hasClimate.sourceCells===1?'cell':'cells')+' in this overview cell.';
      const info=layerInfo(view.layer);description=info?.description||'';
      if(view.layer==='elevation')description+=' Grid-node samples; the outline mask can retain lake or coastal bathymetry.';
      if(selected.value!=null&&view.layer==='precip_mm'&&selected.sd!=null)description+=' Year-to-year standard deviation: '+valueText(selected.sd,'precip_mm')+' '+unit('precip_mm')+'. This describes variability between years for this month, not error.';
      $('crew-location').textContent=s.state?s.state.name:'Selected location';$('crew-location-note').textContent=number(s.lat,2)+'° N · '+number(Math.abs(s.lon),2)+'° W · '+name()+' 2006–2025';
      $('crew-values').innerHTML=['mean_temp_c','precip_mm'].map(id=>{const v=lookup(s.lon,s.lat,id).value;return '<div><span>'+esc(id==='precip_mm'?'Average '+name()+' total':'Mean outdoor temperature')+'</span><strong>'+esc(valueText(v,id))+(v==null?'':'<small>'+esc(unit(id))+'</small>')+'</strong></div>';}).join('');
    }
    if(!climate&&isClimate(view.layer))$('location-coverage').textContent=pendingText()+'.';
    $('location-description').textContent=description;
    updateEvidenceCoverage();
  }
  function selectAt(lon,lat,f) {
    if(!slope)requestSlope();view.selected={lon,lat,state:f||null};window.NovemberAtlas.selection={lon,lat,name:f?f.name:'Overview location'};document.dispatchEvent(new CustomEvent('atlas:selection',{detail:window.NovemberAtlas.selection}));$('state-select').value=f?f.id:'';updateInspector();render();$('announcer').textContent='Selected '+(f?f.name:'location')+'. '+names[view.layer]+': '+valueText(lookup(lon,lat,view.layer).value,view.layer)+' '+unit(view.layer)+'.';
  }
  function clearSelection() { view.selected=null;window.NovemberAtlas.selection=null;document.dispatchEvent(new CustomEvent('atlas:selection',{detail:null}));$('state-select').value='';updateInspector();render(); }
  function selectState(id) {
    const f=features.find(f=>f.id===id);if(!f){reset();clearSelection();return;}
    let p=f.label;if(!hit.isPointInPath(f.path,p[0],p[1],'evenodd')){p=[(f.bounds[0]+f.bounds[2])/2,(f.bounds[1]+f.bounds[3])/2];}
    const ll=invert(p[0],p[1]);selectAt(ll[0],ll[1],f);
    const z=Math.max(1.6,Math.min(5,W*.65/(f.bounds[2]-f.bounds[0]),H*.7/(f.bounds[3]-f.bounds[1])));view.zoom=z;view.x=W/2-p[0]*z;view.y=H/2-p[1]*z;constrain();render();
  }
  function constrain() { view.x=Math.max(W*(1-view.zoom)-60,Math.min(60,view.x));view.y=Math.max(H*(1-view.zoom)-45,Math.min(45,view.y));if(view.zoom===1){view.x=0;view.y=0;} }
  function zoom(factor,anchor) { const z=Math.max(1,Math.min(7,view.zoom*factor)),p=anchor||[W/2,H/2],ratio=z/view.zoom;view.x=p[0]-(p[0]-view.x)*ratio;view.y=p[1]-(p[1]-view.y)*ratio;view.zoom=z;constrain();$('tooltip').hidden=true;render(); }
  function reset() { view.zoom=1;view.x=0;view.y=0;render(); }
  function eventPoint(e) {const r=stage.getBoundingClientRect();return [(e.clientX-r.left-viewport.x)/viewport.s,(e.clientY-r.top-viewport.y)/viewport.s];}
  function mapPoint(p) {return [(p[0]-view.x)/view.zoom,(p[1]-view.y)/view.zoom];}
  function showTooltip(e) {
    if(!project)return;const p=mapPoint(eventPoint(e)),f=findState(p[0],p[1]),ll=invert(p[0],p[1]),v=lookup(ll[0],ll[1],view.layer);if(!f&&(view.layer!=='landcover'||v.value==null)&&!seasonal.canSelect(ll[0],ll[1])){$('tooltip').hidden=true;return;}
    $('tooltip').innerHTML=esc(f?f.name:'Mapped landscape / water')+'<strong>'+esc(valueText(v.value,view.layer))+(v.value==null?'':' '+esc(unit(view.layer)))+'</strong><small>'+esc(view.layer==='landcover'?'2025 coarse class · ~4–7 km service overview':view.layer==='slope'?(slope?'Mean slope · static 0.05° overview':slopePending()):view.layer==='elevation'?'2009 relief · sampled context':v.value==null?'No full-baseline estimate':'20-year '+name()+' average')+'</small>'+seasonal.hover(ll[0],ll[1]);
    const r=stage.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;$('tooltip').hidden=false;$('tooltip').style.left=Math.max(7,Math.min(r.width-$('tooltip').offsetWidth-8,x+14))+'px';$('tooltip').style.top=Math.max(7,Math.min(r.height-$('tooltip').offsetHeight-8,y-72))+'px';
  }
  let drag=null;
  stage.addEventListener('pointerdown',e=>{if(e.target.closest('button'))return;stage.focus({preventScroll:true});drag={x:e.clientX,y:e.clientY,vx:view.x,vy:view.y,moved:false,id:e.pointerId};stage.setPointerCapture(e.pointerId);});
  stage.addEventListener('pointermove',e=>{if(drag){const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>4)drag.moved=true;if(drag.moved){stage.classList.add('dragging');view.x=drag.vx+dx/viewport.s;view.y=drag.vy+dy/viewport.s;constrain();$('tooltip').hidden=true;render();}}else showTooltip(e);});
  stage.addEventListener('pointerup',e=>{if(!drag)return;const moved=drag.moved;drag=null;stage.classList.remove('dragging');if(stage.hasPointerCapture(e.pointerId))stage.releasePointerCapture(e.pointerId);if(!moved&&project){const p=mapPoint(eventPoint(e)),f=findState(p[0],p[1]);const ll=invert(p[0],p[1]);if(f||(view.layer==='landcover'&&lookup(ll[0],ll[1],'landcover').value!=null)||seasonal.canSelect(ll[0],ll[1]))selectAt(ll[0],ll[1],f);}});
  stage.addEventListener('pointercancel',()=>{drag=null;stage.classList.remove('dragging');});stage.addEventListener('pointerleave',()=>{$('tooltip').hidden=true;});
  stage.addEventListener('wheel',e=>{e.preventDefault();if(project)zoom(Math.exp(-Math.max(-150,Math.min(150,e.deltaY))*.002),eventPoint(e));},{passive:false});
  stage.addEventListener('keydown',e=>{if(e.target!==stage)return;let handled=true;if(e.key==='+'||e.key==='=')zoom(1.35);else if(e.key==='-')zoom(1/1.35);else if(e.key==='Home')reset();else if(e.key==='Escape')clearSelection();else if(e.key==='ArrowLeft')view.x+=50;else if(e.key==='ArrowRight')view.x-=50;else if(e.key==='ArrowUp')view.y+=50;else if(e.key==='ArrowDown')view.y-=50;else handled=false;if(handled){e.preventDefault();constrain();render();}});
  function switchView(tab) {view.tab=tab;document.querySelectorAll('.view').forEach(p=>p.hidden=p.id!=='view-'+tab);document.querySelectorAll('[data-view]').forEach(b=>{const on=b.dataset.view===tab;b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on));});if(tab==='map')requestAnimationFrame(resize);document.dispatchEvent(new CustomEvent('atlas:view',{detail:{view:tab}}));}
  function setUnits(u) {view.units=u;window.NovemberAtlas.units=u;document.dispatchEvent(new CustomEvent('atlas:units',{detail:{units:u}}));$('metric-units').classList.toggle('active',u==='metric');$('us-units').classList.toggle('active',u==='us');$('metric-units').setAttribute('aria-pressed',String(u==='metric'));$('us-units').setAttribute('aria-pressed',String(u==='us'));if(project){updateLegend();updateInspector();}$('tooltip').hidden=true;}
  const scenarios={
    operating:{title:'Working controls can leave residual heat.',text:'Assume the fitted climate-control system functions. Do not assume that a comfortable outdoor temperature produces a comfortable cabin, or that every compartment receives adequate cooling.',controls:'Active heating and cooling operate as configured; capacity and distribution are unverified.',ventilation:'Configuration and airflow are unspecified.',heat:'Vehicle, equipment, crew and solar heat remain relevant.',cold:'Working heating may matter during cold outdoor conditions.'},
    degraded:{title:'Specify the loss before quantifying its effect.',text:'A partial failure might affect capacity, airflow, distribution or another function. “Degraded” does not identify which function is lost, so this scenario retains that uncertainty.',controls:'Some performance is lost; the affected function and magnitude are unknown.',ventilation:'Do not assume ventilation fails or remains intact with cooling.',heat:'Residual internal and solar heat remain relevant.',cold:'Heating may also be impaired; its condition must be specified.'},
    unavailable:{title:'Plan for no active heating or cooling in the model.',text:'For this scenario, active climate control is unavailable. Heat produced inside the vehicle can still accumulate, and cold outdoor conditions may matter when active heating is absent.',controls:'Active heating and cooling are unavailable.',ventilation:'Treated separately; fan, hatch and airflow conditions are unspecified.',heat:'Internal heat and possible solar gain remain inputs; their magnitude is unknown.',cold:'Loss of heating is included, not just loss of cooling.'}
  };
  function setScenario(id) {view.scenario=id;const s=scenarios[id];document.querySelectorAll('[data-scenario]').forEach(b=>{const on=b.dataset.scenario===id;b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on));});$('scenario-detail').innerHTML='<h4>'+esc(s.title)+'</h4><p>'+esc(s.text)+'</p><dl class="assumptions"><dt>Active controls</dt><dd>'+esc(s.controls)+'</dd><dt>Ventilation</dt><dd>'+esc(s.ventilation)+'</dd><dt>Internal heat</dt><dd>'+esc(s.heat)+'</dd><dt>Cold conditions</dt><dd>'+esc(s.cold)+'</dd></dl><div class="assumption-note"><strong>Quantified result: unknown.</strong> These conditions are assumptions to retain in the project. Cabin temperature, comfort duration and failure probability require additional evidence.</div>';}
  const waterScenarios = {
    unknown: {
      title: 'Supply status is unverified.',
      carried: 'The carried inventory and its availability to the crew are unknown.',
      resupply: 'Availability, continuity and reliability of resupply are unknown.',
      quality: 'Water quality, storage condition and access to appropriate treatment are unverified.'
    },
    available: {
      title: 'Current availability is an assumption.',
      carried: 'Assume supplied drinking water is currently available. The amount, distribution and storage condition are not established.',
      resupply: 'Current availability does not establish the reliability or continuity of later resupply.',
      quality: 'Potability and any treatment arrangements still need supporting evidence.'
    },
    interrupted: {
      title: 'Resupply is assumed to be interrupted.',
      carried: 'Existing carried supplies remain unknown. An interruption does not establish that no water remains.',
      resupply: 'Assume resupply is interrupted. Its duration and restoration are unknown.',
      quality: 'The quality of remaining or alternative water and treatment availability remain unverified.'
    }
  };
  function setWaterScenario(id) {
    view.water=id;const s=waterScenarios[id];
    document.querySelectorAll('[data-water]').forEach(b=>{const on=b.dataset.water===id;b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on));});
    $('water-detail').innerHTML='<h4>'+esc(s.title)+'</h4><dl class="water-evidence"><div><dt>Carried drinking water</dt><dd>'+esc(s.carried)+'</dd></div><div><dt>Resupply reliability</dt><dd>'+esc(s.resupply)+'</dd></div><div><dt>Quality &amp; treatment</dt><dd>'+esc(s.quality)+'</dd></div></dl>';
  }
  function fillMethod() {
    const m=climate?.metadata;
    $('method-content').innerHTML=m?'<p><strong>'+name()+' 2006–2025, with 20 equally weighted years.</strong> This is a custom 20-year climatology, not an official 30-year climate normal.</p><p>'+esc(m.method.temporal)+'</p><p>'+esc(m.method.spatial)+'</p><p>'+esc(m.method.completeness)+'</p><p><strong>Resolution:</strong> '+esc(m.resolution.description)+'</p>':'<p>'+esc(pendingText())+'.</p>';
    const stateSource=boundary.metadata||{};
    $('source-content').innerHTML='<div class="source-item"><div class="source-label">TEMPERATURE &amp; PRECIPITATION</div><a href="'+esc(m?.source?.url||'https://www.drought.gov/data-maps-tools/gridded-climate-datasets-noaas-nclimgrid-monthly')+'" target="_blank" rel="noopener noreferrer">NOAA nClimGrid-Monthly ↗</a><p>Monthly station-based climate estimates, from 20 rasters for the selected calendar month. An area-weighted overview is derived from the source grid.</p><p class="source-date">Baseline: 2006–2025 '+(m?'· Accessed '+esc(m.source.accessedAt.slice(0,10)):'')+'</p></div><div class="source-item"><div class="source-label">ELEVATION CONTEXT</div><a href="'+esc(elevation.source.url)+'" target="_blank" rel="noopener noreferrer">NOAA ETOPO1 global relief ↗</a><p>2009 relief model sampled at 0.1° spacing. This is a static context layer; samples can retain lake and coastal bathymetry.</p><p class="source-date">Model vintage: 2009 · Accessed '+esc(elevation.source.accessedAt.slice(0,10))+'</p></div><div class="source-item"><div class="source-label">REFERENCE GEOGRAPHY</div><a href="https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_state_20m.zip" target="_blank" rel="noopener noreferrer">U.S. Census cartographic boundaries ↗</a><p>2025 generalized boundaries at 1:20 million scale, limited to the contiguous 48 states and DC.</p><p class="source-date">Landscape snapshot: 2025</p></div>';
    $('source-content').innerHTML+='<div class="source-item"><div class="source-label">TERRAIN SLOPE</div><a href="https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer" target="_blank" rel="noopener noreferrer">USGS 3D Elevation Program ↗</a><p>Elevations sampled on a 500 m Albers equal-area grid are converted to slope angles using the Horn 3×3 gradient. The overview displays their mean on a 0.05° grid in degrees, independently of the selected month. Mapped lake surfaces are excluded.</p></div>';
    $('source-content').innerHTML+='<div class="source-item"><div class="source-label">MONTHLY STREAMFLOW</div><a href="https://waterservices.usgs.gov/docs/statistics/statistics-details/" target="_blank" rel="noopener noreferrer">USGS monthly streamflow statistics ↗</a><p>Station records preserve complete and partial 2006–2025 baselines. Monthly mean discharge for the selected calendar month is summarized at each gauge, with source coverage and variability retained.</p></div><div class="source-item"><div class="source-label">LOCAL WATER GEOMETRY</div><a href="https://docs.overturemaps.org/getting-data/cloud-sources/" target="_blank" rel="noopener noreferrer">Overture Maps inspection tiles ↗</a><p>Land &amp; water detail validates a current base-water archive or clearly labeled dated fallback. Source precision and tile limits remain visible. Buildings and roads are excluded from the active scope.</p></div>';
    $('source-content').innerHTML+='<div class="source-item"><div class="source-label">LAND COVER &amp; WETLANDS</div><a href="https://www.usgs.gov/data/annual-national-land-cover-database-nlcd-collection-1-products-ver-12-june-2026" target="_blank" rel="noopener noreferrer">USGS Annual NLCD ↗</a><p>The national layer is a coarse 4–7 km overview. Land &amp; water detail requests local imagery from the same 2025 USGS product at its native 30 m source support, with mapped water above it. Reprojected image pixels and display zoom do not add source resolution. Vegetation height, understory and seasonal state need separate evidence.</p></div><div class="source-item"><div class="source-label">BRIDGE INVENTORY LOCATIONS</div><a href="https://www.fhwa.dot.gov/bridge/nbi/nbi_data_2025.cfm" target="_blank" rel="noopener noreferrer">FHWA 2025 National Bridge Inventory ↗</a><p>Land &amp; water detail shows individual inventory records at their reported coordinates, with feature names when supplied. A recorded bridge may cross water, a road or another feature. Current availability and crossing suitability are unverified.</p></div>';
    $('source-content').innerHTML+='<div class="source-item"><div class="source-label">NATIONAL RIVERS &amp; LAKES</div><a href="https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-rivers-lake-centerlines/" target="_blank" rel="noopener noreferrer">Natural Earth hydrography ↗</a><p>Generalized river lines and lake/reservoir polygons at 1:10 million cartographic scale, including the North America supplement. Blue line widths are symbols, not measured channel widths. Dashed lines preserve supplied intermittent-river classifications; no monthly flow presence is inferred.</p></div>';
    $('source-content').innerHTML+='<div class="source-item"><div class="source-label">SEASONAL SNOW &amp; LAKE ICE</div><p>Snow-cover frequency is a separate monthly land overlay. Surface ice concentration is a separate monthly overlay on the Great Lakes. Each has its own color scale, geographic coverage and observation support. The 2025 land-cover class for perennial ice/snow is preserved.</p></div>';
    $('cell-count').textContent=m?number(m.coverage.validGridCells,0):'—';
  }
  document.querySelectorAll('[data-layer]').forEach(b=>b.addEventListener('click',()=>{if(b.dataset.layer==='slope'&&slopeState==='error')requestSlope(true);setLayer(b.dataset.layer);}));
  document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>switchView(b.dataset.view)));
  document.querySelectorAll('[data-open]').forEach(b=>b.addEventListener('click',()=>switchView(b.dataset.open)));
  document.querySelectorAll('[data-scenario]').forEach(b=>b.addEventListener('click',()=>setScenario(b.dataset.scenario)));
  document.querySelectorAll('[data-water]').forEach(b=>b.addEventListener('click',()=>setWaterScenario(b.dataset.water)));
  $('state-select').addEventListener('change',e=>selectState(e.target.value));$('clear-selection').addEventListener('click',clearSelection);
  $('metric-units').addEventListener('click',()=>setUnits('metric'));$('us-units').addEventListener('click',()=>setUnits('us'));
  $('zoom-in').addEventListener('click',()=>zoom(1.4));$('zoom-out').addEventListener('click',()=>zoom(1/1.4));$('zoom-reset').addEventListener('click',reset);
  document.addEventListener('atlas:open-detail',()=>switchView('detail'));
  document.addEventListener('atlas:regional-context',e=>{
    const {lon,lat}=e.detail||{};if(!project||!Number.isFinite(lon)||!Number.isFinite(lat))return;
    switchView('map');if(landcover)setLayer('landcover');const pt=project(lon,lat);selectAt(lon,lat,findState(pt[0],pt[1]));
    view.zoom=3;view.x=W/2-pt[0]*view.zoom;view.y=H/2-pt[1]*view.zoom;constrain();
    for(const key of ['show-seasonal-snow','show-seasonal-ice']){const input=$(key);if(input&&!input.checked){input.checked=true;input.dispatchEvent(new Event('change',{bubbles:true}));}}
    render();
  });
  document.addEventListener('atlas:civilian-vehicle',event=>{if(event.detail?.label)$('cabin-vehicle-reference').textContent=event.detail.label;});
  $('overview-to-detail').addEventListener('click',()=>{if(window.NovemberAtlas.selection)document.dispatchEvent(new CustomEvent('atlas:open-detail',{detail:{...window.NovemberAtlas.selection,zoom:16}}));});
  new ResizeObserver(resize).observe(stage);setScenario('operating');setWaterScenario('unknown');
  function reflectMonth() {
    for(const el of document.querySelectorAll('[data-active-month-name]'))el.textContent=name();
    for(const el of document.querySelectorAll('[data-active-month-number]'))el.textContent=String(month).padStart(2,'0');
    const status=$('atlas-month-status');
    if(status){
      status.textContent=climateStatus==='ready'?name()+' climate ready.':pendingText()+'.';
      if(climateStatus==='error'){
        const retry=document.createElement('button');retry.type='button';retry.textContent='Retry';retry.className='text-button';retry.addEventListener('click',()=>selectMonth(month));status.append(' ',retry);
      }
    }
    for(const el of document.querySelectorAll('[data-climate-download]')){
      if(climateStatus==='ready'){const suffix=month===11?'.json':'.json.gz';el.href=monthlyFile(month);el.download='conus_climate_'+name().toLowerCase()+'_2006_2025'+suffix;el.removeAttribute('aria-disabled');el.title=name()+' data · '+(month===11?'JSON':'compressed JSON');const format=el.querySelector('span');if(format)format.textContent=(month===11?'JSON':'JSON.GZ')+' ↗';}
      else{el.removeAttribute('href');el.setAttribute('aria-disabled','true');el.title=pendingText();}
    }
    if(!project)return;
    fillMethod();setLayer(view.layer);
  }
  async function selectMonth(next) {
    next=Number(next);if(!Number.isInteger(next)||next<1||next>12)return;
    const token=++climateToken;
    if(controller)controller.abort();
    controller=new AbortController();
    month=next;climate=null;climateStatus='loading';
    Object.assign(window.NovemberAtlas,{month,monthName:name()});shortNames.precip_mm=name()+' total';
    for(const k of ['mean_temp_c','min_temp_c','max_temp_c','precip_mm'])caches.delete(k);
    cornerCache.delete('climate');
    $('tooltip').hidden=true;
    document.dispatchEvent(new CustomEvent('atlas:month',{detail:{month,name:name()}}));
    reflectMonth();
    try{
      const file=monthlyFile(next);
      let data=monthCache.get(next);
      if(!data)data=await readAtlasJSON(file,{signal:controller.signal});
      if(token!==climateToken)return;
      const p=data?.metadata?.period,g=data?.grid;
      if(p?.month!==next||p.startYear!==2006||p.endYear!==2025||p.expectedYears!==20||!Array.isArray(data.layers)||!g?.values)throw new Error('Unexpected monthly climate file or baseline');
      for(const id of ['mean_temp_c','min_temp_c','max_temp_c','precip_mm']){
        if(g.values[id]?.length!==g.width*g.height||g.validYears?.[id]?.length!==g.width*g.height||!data.layers.some(x=>x.id===id))throw new Error('Incomplete '+id+' grid');
      }
      monthCache.delete(next);monthCache.set(next,data);
      while(monthCache.size>2)monthCache.delete(monthCache.keys().next().value);
      climate=data;climateStatus='ready';
    }catch(error){
      if(token!==climateToken)return;
      climate=null;climateStatus='error';console.warn('Monthly climate:',error);
    }
    if(token!==climateToken)return;
    reflectMonth();document.dispatchEvent(new CustomEvent('atlas:climate-ready',{detail:{month,name:name(),status:climateStatus}}));
  }
  $('atlas-month').addEventListener('change',e=>selectMonth(e.target.value));
  async function load() {
    selectMonth($('atlas-month').value||11);
    try{
      [elevation,boundary]=await Promise.all(['elevation.json','states.geojson'].map(async f=>{const r=await fetch('data/'+f);if(!r.ok)throw new Error('Could not retrieve '+f+' ('+r.status+').');return r.json();}));
      try{const response=await fetch('data/landcover.json');if(!response.ok)throw new Error('HTTP '+response.status);landcover=await response.json();if(!landcover.grid?.values?.landcover||!landcover.classes?.length)throw new Error('Incomplete source');}
      catch(error){console.warn('Land cover:',error);view.layer='precip_mm';const button=document.querySelector('[data-layer="landcover"]');button.disabled=true;button.textContent='Land cover unavailable';button.title=error.message;$('location-landcover').textContent='Land-cover source could not load; no absence is inferred.';}
      setupProjection();reflectMonth();resize();$('loading').hidden=true;loadHydro();
    }catch(e){console.error(e);$('loading').hidden=true;$('map-error').hidden=false;$('error-message').textContent=e.message||'Please reload to try again.';}
  }
  load();
})();
