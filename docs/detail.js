'use strict';
import {resolveWaterRelease} from './environment_source_loader.js';
import {CanvasDetailMap} from './detail_canvas.js';
import {loadLandcoverDetailConfig,landcoverTileURL,queryLandcoverClass} from './landcover_detail_loader.js';
import {loadBridgePoints,bridgesInBounds,bridgeFeatureCollection,loadBridgeRecord} from './bridges.js';
import {loadWaterData,currentWaterMonth,waterMonthName,stationFeatureCollection,stationMarkup,escapeHtml} from './water.js';
const $=id=>document.getElementById(id),defaultInspector=$('detail-feature-content').innerHTML;
const examples=[
 {label:'La Crosse, Wisconsin · land cover and river islands',lon:-91.25,lat:43.81,zoom:13},
 {label:'Pittsburgh, Pennsylvania · rivers',lon:-80.006,lat:40.443,zoom:13},
 {label:'Portland, Oregon · Willamette River',lon:-122.672,lat:45.522,zoom:13},
 {label:'Lafayette, Indiana · Wabash River',lon:-86.899,lat:40.42,zoom:13},
 {label:'Chattahoochee River, Georgia · forest and water',lon:-84.448,lat:33.9,zoom:13}
];
let map,resolved,landcoverConfig,bridgeData,waterData,pendingTarget,selectedStation,initPromise,generation=0,selectionVersion=0,localBridgeCount=0,sourceErrors=[];
let gaugeToken=0,gaugePending=false,gaugeFailed=false,desiredGauge=null;
const supplied=value=>value==null||value===''?'Not supplied':String(value);
function message(text=''){$('detail-input-message').textContent=text;}
function sourceError(label,error){
 const note=label+': '+(error.message||String(error));if(!sourceErrors.includes(note))sourceErrors.push(note);if(sourceErrors.length>3)sourceErrors=sourceErrors.slice(-3);$('detail-error-title').textContent='Some source data could not load';$('detail-error-message').textContent=sourceErrors.join(' ')+' Missing source data do not establish an absence of features.';$('detail-error').hidden=false;
}
function applyTarget(target){
 if(!target)return;++selectionVersion;selectedStation=null;desiredGauge=target.stationId||null;clearHighlights();$('detail-feature-content').innerHTML=defaultInspector;pendingTarget=target;$('detail-lat').value=Number(target.lat).toFixed(5);$('detail-lon').value=Number(target.lon).toFixed(5);message(target.name?'Viewing '+target.name+'.':'');
 if(map){map.jumpTo({center:[target.lon,target.lat],zoom:Math.max(12,Math.min(19,target.zoom||13))});if(target.stationId&&waterData){const station=waterData.stations.find(s=>s.id===target.stationId);if(station)inspectStation(station);}}
}
function updateZoomNote(){if(map)$('detail-zoom-note').textContent='Display zoom '+map.getZoom().toFixed(1)+(landcoverConfig?' · land-cover source '+landcoverConfig.nativeResolutionMeters+' m':' · land-cover source checking')+(resolved?' · dated water geometry':'');}
function updateLayerVisibility(){
 if(!map)return;
 for(const [input,layers]of[['detail-show-landcover',['land-cover']],['detail-show-water',['water-areas','water-lines']],['detail-show-bridges',['bridge-records','bridge-selected']],['detail-show-stations',['flow-gauges','flow-selected']]])for(const id of layers)if(map.getLayer(id))map.setLayoutProperty(id,'visibility',$(input).checked?'visible':'none');
 updateZoomNote();updateDrawnStatus();
}
function clearHighlights(){for(const id of ['bridge-selected','flow-selected'])if(map?.getLayer(id))map.setFilter(id,['==',['get',id==='bridge-selected'?'key':'id'],'__none__']);}
async function inspectBridge(feature){
 const token=++selectionVersion;selectedStation=null;desiredGauge=null;clearHighlights();const p=feature.properties;
 map.setFilter('bridge-selected',['==',['get','key'],p.key]);
 $('detail-feature-content').innerHTML='<p class="eyebrow">FHWA BRIDGE INVENTORY</p><h2>Loading the source record…</h2><p class="secondary">Recorded position in '+escapeHtml(p.state)+'.</p>';
 try{
  const record=await loadBridgeRecord(p.state,Number(p.index));if(token!==selectionVersion)return;
  const rows=[['Inventory identifier',record.id],['Facility carried (reported)',record.carried],['Feature crossed (reported)',record.below],['Location description (reported)',record.location],['Source state',record.state],['Recorded latitude',Number(record.lat).toFixed(5)+'°'],['Recorded longitude',Number(record.lon).toFixed(5)+'°']];
  $('detail-feature-content').innerHTML='<p class="eyebrow">FHWA BRIDGE INVENTORY · SOURCE RECORD</p><h2 class="feature-title">'+escapeHtml(record.carried||'Bridge inventory record')+'</h2><span class="feature-badge bridge-badge">Location only · suitability unverified</span><dl class="attribute-list">'+rows.map(([name,value])=>'<div><dt>'+escapeHtml(name)+'</dt><dd>'+escapeHtml(supplied(value))+'</dd></div>').join('')+'</dl><p class="feature-caveat">A reported crossed feature may be water, a road, railway or another feature. A point does not trace the bridge or verify its alignment with a water outline. Present condition and usable passage are unverified.</p><p class="feature-caveat">Inventory snapshot: '+escapeHtml(record.snapshotDate||bridgeData?.source.snapshotDate||'2025')+'. Coordinates retain source precision and varying survey accuracy; additional display decimals do not imply additional accuracy.</p><a class="text-link" href="'+escapeHtml(record.sourceUrl||bridgeData?.source.url||'https://www.fhwa.dot.gov/bridge/nbi/nbi_data_2025.cfm')+'" target="_blank" rel="noopener noreferrer">Official inventory source ↗</a>';
 }catch(error){if(token!==selectionVersion)return;$('detail-feature-content').innerHTML='<p class="eyebrow">RECORD UNAVAILABLE</p><h2>The detail record could not load.</h2><p class="secondary">'+escapeHtml(error.message)+'</p><p class="feature-caveat">The point remains a location from the national snapshot. No further attributes can be established from this failure.</p>';}
}
async function inspectLandcover(point){
 if(!landcoverConfig?.featureInfo?.enabled)return;
 const token=++selectionVersion;selectedStation=null;desiredGauge=null;clearHighlights();
 const lon=point.lon,lat=point.lat;
 $('detail-feature-content').innerHTML='<p class="eyebrow">USGS LOCAL LAND-COVER QUERY</p><h2>Querying the local class…</h2><p class="secondary">The raw source query is independent of the overview and display colors.</p>';
 try{
  const result=await queryLandcoverClass(landcoverConfig,lon,lat);if(token!==selectionVersion)return;const category=result.category;
  $('detail-feature-content').innerHTML='<p class="eyebrow">USGS 2025 · LOCAL SOURCE CLASS</p><h2 class="feature-title">'+escapeHtml(category?.label||'No source class returned')+'</h2>'+(category?'<span class="local-class-badge"><i style="background:'+escapeHtml(category.color)+'"></i>Source class '+escapeHtml(result.value)+'</span>':'')+'<dl class="attribute-list"><div><dt>Source year</dt><dd>2025</dd></div><div><dt>Underlying source cells</dt><dd>'+escapeHtml(landcoverConfig.nativeResolutionMeters)+' m</dd></div><div><dt>Local query support</dt><dd>Approximately '+escapeHtml(result.queryGroundResolutionMeters)+' m ground pixels</dd></div><div><dt>Selected latitude</dt><dd>'+lat.toFixed(5)+'°</dd></div><div><dt>Selected longitude</dt><dd>'+lon.toFixed(5)+'°</dd></div></dl><p class="feature-caveat">'+escapeHtml(category?.description?.replace(/\bNovember\b/g,'seasonal')||'The source returned no known class at this location. Empty coverage stays unknown.')+'</p><p class="feature-caveat">This is a raw class query at local support, independent of the coarser national overview. The imagery and query are reprojected and resampled from the 30 m source. Neither describes every object within a cell or establishes exact boundaries, tree spacing, understory, seasonal foliage or ground condition.</p><a class="text-link" href="'+escapeHtml(result.sourceUrl)+'" target="_blank" rel="noopener noreferrer">View raw USGS class response ↗</a>';
 }catch(error){if(token!==selectionVersion)return;$('detail-feature-content').innerHTML='<p class="eyebrow">LOCAL CLASS QUERY UNAVAILABLE</p><h2>The class could not be verified.</h2><p class="secondary">'+escapeHtml(error.message)+'</p><p class="feature-caveat">Available imagery and other sources remain on the map. The class is not inferred from display colors or the coarse overview.</p>';}
}
async function addLandcover(token){
 const config=await loadLandcoverDetailConfig();if(token!==generation||!map)return;landcoverConfig=config;
 map.addSource('local-landcover',{type:'raster',minzoom:0,maxzoom:config.wms.maxNativeZoom,_tileURL:(z,x,y)=>landcoverTileURL(config,z,x,y)});
 const before=['water-areas','water-lines','bridge-records','flow-gauges'].find(id=>map.getLayer(id));
 map.addLayer({id:'land-cover',type:'raster',source:'local-landcover',paint:{'raster-opacity':Number($('detail-landcover-opacity').value)/100}},before);
 $('detail-landcover-legend').innerHTML=config.classes.map(c=>'<span><i style="background:'+escapeHtml(c.color)+'"></i>'+escapeHtml(c.label)+'</span>').join('');
 $('detail-landcover-source').textContent='USGS Annual NLCD · 2025 · '+config.nativeResolutionMeters+' m source; imagery reprojected and resampled';
 $('detail-loading').hidden=true;updateLayerVisibility();
}
function inspectWater(feature){
 ++selectionVersion;selectedStation=null;desiredGauge=null;clearHighlights();const p=feature.properties||{},rows=[['Source class',p.class],['Source subtype',p.subtype],['Intermittent flag',p.is_intermittent],['Salt-water flag',p.is_salt],['Source identifier',p.id]];
 $('detail-feature-content').innerHTML='<p class="eyebrow">MAPPED WATER · SOURCE ATTRIBUTES</p><h2 class="feature-title">'+escapeHtml(p['@name']||p.name||'Water feature')+'</h2><dl class="attribute-list">'+rows.map(([label,value])=>'<div><dt>'+escapeHtml(label)+'</dt><dd>'+escapeHtml(supplied(value))+'</dd></div>').join('')+'</dl><p class="feature-caveat">This is source geometry, not an observation of monthly water level. A mapped outline or line supplies no depth, velocity, flood stage, bank condition, ice thickness, potability or crossing assessment.</p><p class="feature-caveat">Overture release '+escapeHtml(resolved?.release||'unknown')+'. Observation dates and positional accuracy may differ among contributing records.</p><details class="source-raw"><summary>View supplied attributes</summary><pre>'+escapeHtml(JSON.stringify(p,null,2))+'</pre></details>';
}
function inspectStation(station){++selectionVersion;selectedStation=station;desiredGauge=station.id;clearHighlights();if(map.getLayer('flow-selected'))map.setFilter('flow-selected',['==',['get','id'],station.id]);$('detail-feature-content').innerHTML=stationMarkup(station);}
function updateBridgeViewport(){
 if(!map||!bridgeData)return;
 const records=bridgesInBounds(bridgeData,map.getBounds()),data=bridgeFeatureCollection(records);localBridgeCount=records.length;
 if(map.getSource('bridge-records'))map.getSource('bridge-records').setData(data);
 else{
  map.addSource('bridge-records',{type:'geojson',data});
  map.addLayer({id:'bridge-records',type:'circle',source:'bridge-records',paint:{'circle-color':'#a16a29','circle-radius':5.5,'circle-stroke-color':'#fffbee','circle-stroke-width':1.5}});
  map.addLayer({id:'bridge-selected',type:'circle',source:'bridge-records',filter:['==',['get','key'],'__none__'],paint:{'circle-color':'rgba(0,0,0,0)','circle-radius':10,'circle-stroke-color':'#694419','circle-stroke-width':2}});
 }
 updateLayerVisibility();updateDrawnStatus();
}
function updateDrawnStatus(){
 const parts=[];
 if(landcoverConfig){const status=map?.getSourceStatus('local-landcover');if(!$('detail-show-landcover').checked)parts.push('land-cover imagery hidden');else if(status?.failed)parts.push(status.failed+' land-cover tile request(s) failed');else if(status?.pending)parts.push('land-cover imagery loading ('+status.ready+'/'+status.visible+' tiles ready)');else if(status?.ready)parts.push('land-cover imagery drawn · 30 m source');}
 if(map&&$('detail-show-stations').checked)parts.push(waterMonthName()+(waterData?' gauge records loaded':gaugeFailed?' gauge records unavailable':' gauge records loading'));
 if(bridgeData)parts.push(new Intl.NumberFormat('en-US').format(localBridgeCount)+' bridge records in the viewport');
 if(resolved&&map?.getLayer('water-areas')){const features=map.queryRenderedFeatures({layers:['water-areas','water-lines']});parts.push(features.length?'water geometry drawn':'no water geometry currently drawn; coverage is not proof of absence');}
 $('detail-tile-status').textContent=parts.join(' · ')||'Source requests are in progress.';
}
async function addWater(token){
 const source=await resolveWaterRelease();if(token!==generation||!map)return;resolved=source;const water=source.water;
 $('detail-loading').hidden=true;map.addSource('reference-water',{type:'vector',url:'pmtiles://'+water.url,minzoom:water.header.minZoom,maxzoom:water.header.maxZoom,_archive:water.archive});
 const before=map.getLayer('bridge-records')?'bridge-records':map.getLayer('flow-gauges')?'flow-gauges':undefined;
 map.addLayer({id:'water-areas',type:'fill',source:'reference-water','source-layer':'water',filter:['==',['geometry-type'],'Polygon'],paint:{'fill-color':'#9dc9d6','fill-opacity':.9}},before);
 map.addLayer({id:'water-lines',type:'line',source:'reference-water','source-layer':'water',filter:['==',['geometry-type'],'LineString'],paint:{'line-color':'#679dad','line-width':['interpolate',['linear'],['zoom'],12,1.3,16,2.4,19,4]}},before);
 $('detail-release-note').textContent='Overture water '+source.release+' · '+source.mode+(source.warnings.length?' · '+source.warnings.join(' '):'');updateLayerVisibility();
}
async function addBridges(token){
 const source=await loadBridgePoints();if(token!==generation||!map)return;bridgeData=source;$('detail-loading').hidden=true;
 $('detail-bridge-source').textContent='FHWA bridge inventory · '+(source.source.snapshotDate||'2025')+' · recorded points, variable positional accuracy';updateBridgeViewport();
}
async function addGauges(token){
 const attempt=++gaugeToken,month=currentWaterMonth();gaugePending=true;gaugeFailed=false;
 try{
  const data=await loadWaterData();if(attempt!==gaugeToken||token!==generation||!map||month!==currentWaterMonth())return;
  waterData=data;$('detail-loading').hidden=true;
  const fc=stationFeatureCollection(data);
  if(map.getSource('flow-gauges'))map.getSource('flow-gauges').setData(fc);
  else{
   map.addSource('flow-gauges',{type:'geojson',data:fc});
   map.addLayer({id:'flow-gauges',type:'circle',source:'flow-gauges',paint:{'circle-color':['case',['get','completeBaseline'],'#367f83','#bd9456'],'circle-radius':5,'circle-stroke-color':'#fffef4','circle-stroke-width':1.1}});
   map.addLayer({id:'flow-selected',type:'circle',source:'flow-gauges',filter:['==',['get','id'],'__none__'],paint:{'circle-radius':10,'circle-color':'rgba(0,0,0,0)','circle-stroke-color':'#214f43','circle-stroke-width':2}});
  }
  if(desiredGauge){const station=data.stations.find(s=>s.id===desiredGauge);if(station)inspectStation(station);else{desiredGauge=null;selectedStation=null;$('detail-feature-content').innerHTML=defaultInspector+'<p class="feature-caveat">No record for the selected gauge in '+waterMonthName(month)+'.</p>';}}
  updateLayerVisibility();
 }catch(e){if(attempt===gaugeToken&&token===generation&&month===currentWaterMonth()){gaugeFailed=true;sourceError('Streamflow gauges ('+waterMonthName(month)+')',e);if(desiredGauge)$('detail-feature-content').innerHTML=defaultInspector+'<p class="feature-caveat">Monthly gauge lookup unavailable.</p>';}}
 finally{if(attempt===gaugeToken){gaugePending=false;updateDrawnStatus();}}
}
document.addEventListener('atlas:month',()=>{
 ++gaugeToken;waterData=null;selectedStation=null;gaugePending=false;gaugeFailed=false;
 if(!map)return;
 if(map.getSource('flow-gauges'))map.getSource('flow-gauges').setData({type:'FeatureCollection',features:[]});
 if(map.getLayer('flow-selected'))map.setFilter('flow-selected',['==',['get','id'],'__none__']);
 if(desiredGauge)$('detail-feature-content').innerHTML='<p class="eyebrow">USGS gauge</p><p>Checking '+waterMonthName()+' records…</p>';
 sourceErrors=sourceErrors.filter(x=>!x.startsWith('Streamflow gauges ('));$('detail-error').hidden=!sourceErrors.length;
 if(sourceErrors.length)$('detail-error-message').textContent=sourceErrors.join(' ');
 if(!$('view-detail').hidden)addGauges(generation);
});
function wireMap(){
 const layers=()=>['bridge-records','flow-gauges','water-areas','water-lines'].filter(id=>map.getLayer(id));
 map.on('mousemove',event=>{map.getCanvas().style.cursor=map.queryRenderedFeatures(event.point,{layers:layers()}).length?'pointer':landcoverConfig?.featureInfo?.enabled&&$('detail-show-landcover').checked?'crosshair':'';});
 map.on('click',event=>{
  const features=map.queryRenderedFeatures(event.point,{layers:layers()}),bridge=features.find(f=>f.layer.id==='bridge-records');
  if(bridge){inspectBridge(bridge);return;}
  const gauge=features.find(f=>f.layer.id==='flow-gauges');if(gauge){const station=waterData?.stations.find(s=>s.id===gauge.properties.id);if(station)inspectStation(station);return;}
  const water=features.find(f=>f.layer.id==='water-areas'||f.layer.id==='water-lines');if(water){inspectWater(water);return;}if($('detail-show-landcover').checked)inspectLandcover(map.unproject(event.point));
 });
 map.on('zoom',updateZoomNote);
 map.on('moveend',()=>{const center=map.getCenter();$('detail-lat').value=center.lat.toFixed(5);$('detail-lon').value=center.lng.toFixed(5);updateBridgeViewport();});
 map.on('idle',updateDrawnStatus);map.on('sourcedata',updateDrawnStatus);
 map.on('error',event=>sourceError(event.sourceId==='local-landcover'?'Land-cover image tile':'Water tile',event.error||new Error('A source request failed.')));
}
async function initDetail(force=false){
 if(initPromise&&!force)return initPromise;if(map&&!force){map.resize();updateBridgeViewport();return;}
 const token=++generation;if(map)map.remove();map=null;resolved=null;landcoverConfig=null;bridgeData=null;waterData=null;selectedStation=null;sourceErrors=[];++selectionVersion;
 $('detail-error').hidden=true;$('detail-loading').hidden=false;
 const target=pendingTarget||(window.NovemberAtlas?.selection?{...window.NovemberAtlas.selection,zoom:13}:examples[0]);
 map=new CanvasDetailMap({container:'detail-map',center:[target.lon,target.lat],zoom:target.zoom||13,minZoom:12,maxZoom:19,maxBounds:[[-126,24],[-66,50]]});wireMap();applyTarget(target);
 initPromise=(async()=>{
  const labels=['Land-cover source','Water geometry','Bridge inventory','Streamflow gauges'];
  const results=await Promise.allSettled([addLandcover(token),addWater(token),addBridges(token),addGauges(token)]);
  if(token!==generation)return;
  results.forEach((result,i)=>{if(result.status==='rejected'){sourceError(labels[i],result.reason);if(i===0)$('detail-landcover-source').textContent='Land-cover source unavailable';if(i===1)$('detail-release-note').textContent='Water source unavailable';if(i===2)$('detail-bridge-source').textContent='Bridge snapshot unavailable';}});
  $('detail-loading').hidden=true;map.resize();updateBridgeViewport();updateZoomNote();initPromise=null;
 })();return initPromise;
}
$('detail-example').innerHTML='<option value="">Choose an example…</option>'+examples.map((e,i)=>'<option value="'+i+'">'+escapeHtml(e.label)+'</option>').join('');
$('detail-example').addEventListener('change',event=>{if(event.target.value==='')return;const target=examples[Number(event.target.value)];if(target)applyTarget({...target,name:target.label});});
$('detail-coordinate-form').addEventListener('submit',event=>{event.preventDefault();const lat=Number($('detail-lat').value),lon=Number($('detail-lon').value);if(!Number.isFinite(lat)||!Number.isFinite(lon)||lat<24||lat>50||lon< -126||lon> -66){message('Use latitude 24–50 and longitude −126 to −66 for this contiguous-US study window.');return;}$('detail-example').value='';applyTarget({lat,lon,zoom:13});});
$('detail-regional-context').addEventListener('click',()=>{if(!map)return;const c=map.getCenter();document.dispatchEvent(new CustomEvent('atlas:regional-context',{detail:{lon:c.lng,lat:c.lat}}));});
$('detail-use-overview').addEventListener('click',()=>{const selected=window.NovemberAtlas?.selection;if(selected){$('detail-example').value='';applyTarget({...selected,zoom:13});}});
for(const id of ['detail-show-landcover','detail-show-water','detail-show-bridges','detail-show-stations'])$(id).addEventListener('change',updateLayerVisibility);
$('detail-retry').addEventListener('click',()=>initDetail(true));
$('detail-landcover-opacity').addEventListener('input',event=>{const value=Number(event.target.value);$('detail-opacity-value').value=value+'%';$('detail-opacity-value').textContent=value+'%';if(map?.getLayer('land-cover'))map.setPaintProperty('land-cover','raster-opacity',value/100);});
$('overview-landcover-detail').addEventListener('click',()=>{const selected=window.NovemberAtlas?.selection;if(selected)document.dispatchEvent(new CustomEvent('atlas:open-detail',{detail:{...selected,zoom:13}}));});
document.addEventListener('atlas:selection',event=>{$('detail-use-overview').disabled=!event.detail;});
document.addEventListener('atlas:open-detail',event=>{if(event.detail){pendingTarget={...event.detail,zoom:13};if(map)applyTarget(pendingTarget);}initDetail();});
document.addEventListener('atlas:view',event=>{if(event.detail.view==='detail'){initDetail();if(map&&!waterData&&!gaugePending&&!gaugeFailed)addGauges(generation);requestAnimationFrame(()=>{map?.resize();updateBridgeViewport();});}});
document.addEventListener('atlas:units',()=>{if(selectedStation)$('detail-feature-content').innerHTML=stationMarkup(selectedStation);});
new ResizeObserver(()=>{if(map&&!$('view-detail').hidden){map.resize();updateBridgeViewport();}}).observe($('detail-map'));
