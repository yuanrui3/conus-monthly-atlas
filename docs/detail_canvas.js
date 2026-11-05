'use strict';
import {decodeTile} from './vendor/vector_tile.mjs';
const R=Math.PI/180;
function world(lon,lat){const p=Math.max(-85.05112878,Math.min(85.05112878,lat))*R;return[(lon+180)/360,(1-Math.log(Math.tan(p)+1/Math.cos(p))/Math.PI)/2];}
function geographic(x,y){return[x*360-180,Math.atan(Math.sinh(Math.PI*(1-2*y)))/R];}
function clamp(x,a,b){return Math.max(a,Math.min(b,x));}
function kind(t){return t.startsWith('Multi')?t.slice(5):t;}
function evaluate(e,p,z,type){
 if(!Array.isArray(e))return e;if(typeof e[0]!=='string')return e;const op=e[0],ev=x=>evaluate(x,p,z,type);
 if(op==='literal')return e[1];if(op==='get')return p[e[1]];if(op==='zoom')return z;if(op==='geometry-type')return kind(type);
 if(op==='coalesce'){for(let i=1;i<e.length;i++){const v=ev(e[i]);if(v!=null)return v;}return null;}
 if(op==='==')return ev(e[1])===ev(e[2]);if(op==='!=')return ev(e[1])!==ev(e[2]);if(op==='!')return !ev(e[1]);
 if(op==='any')return e.slice(1).some(ev);if(op==='all')return e.slice(1).every(ev);if(op==='in'){const a=ev(e[2]);return Array.isArray(a)&&a.includes(ev(e[1]));}
 if(op==='case'){for(let i=1;i<e.length-1;i+=2)if(ev(e[i]))return ev(e[i+1]);return ev(e[e.length-1]);}
 if(op==='interpolate'){const v=Number(ev(e[2]));if(v<=e[3])return ev(e[4]);for(let i=5;i<e.length;i+=2){if(v<=e[i]){const a=Number(ev(e[i-1])),b=Number(ev(e[i+1]));return a+(b-a)*(v-e[i-2])/(e[i]-e[i-2]);}}return ev(e[e.length-1]);}
 return null;
}
function prepare(feature){
 let minx=Infinity,maxx=-Infinity,miny=Infinity,maxy=-Infinity;
 function convert(c){if(typeof c[0]==='number'){const p=world(c[0],c[1]);minx=Math.min(minx,p[0]);maxx=Math.max(maxx,p[0]);miny=Math.min(miny,p[1]);maxy=Math.max(maxy,p[1]);return p;}return c.map(convert);}
 const coordinates=convert(feature.geometry.coordinates),props={...feature.properties};delete props.__sourceLayer;
 return {...feature,properties:props,_world:coordinates,_bbox:[minx,miny,maxx,maxy],_pathRevision:-1,_path:null};
}
function intersects(a,b){return a[0]<=b[2]&&a[2]>=b[0]&&a[1]<=b[3]&&a[3]>=b[1];}
export class CanvasDetailMap {
 constructor(options={}){
  this.__canvasFallback=true;this._container=typeof options.container==='string'?document.getElementById(options.container):options.container;if(!this._container)throw new Error('Local map container is missing.');
  this._center=options.center||[-105.078,40.58];this._zoom=options.zoom||16;this._minZoom=Math.max(12,options.minZoom||12);this._maxZoom=options.maxZoom||19;this._bounds=options.maxBounds||[[-126,24],[-66,50]];this._events=new Map();this._sources=new Map();this._layers=[];this._rendered=[];this._queue=[];this._active=0;this._revision=0;this._removed=false;this._frame=0;
  this._canvas=document.createElement('canvas');this._canvas.className='local-canvas';this._canvas.tabIndex=0;this._canvas.setAttribute('aria-label','Local two-dimensional map. Drag to pan, scroll or use plus and minus to zoom. Click land cover, a water feature, bridge record or gauge to inspect.');this._container.appendChild(this._canvas);this._ctx=this._canvas.getContext('2d');if(!this._ctx)throw new Error('Canvas2D is unavailable.');this._hit=document.createElement('canvas').getContext('2d');
  this._controls=document.createElement('div');this._controls.className='canvas-local-controls';for(const [label,delta]of[['Zoom in',1],['Zoom out',-1]]){const b=document.createElement('button');b.type='button';b.textContent=delta>0?'+':'−';b.setAttribute('aria-label',label);b.title=label;b.addEventListener('click',()=>this._zoomAt(this._zoom+delta,{x:this._width/2,y:this._height/2}));this._controls.appendChild(b);}this._container.appendChild(this._controls);
  this._attribution=document.createElement('div');this._attribution.className='canvas-local-attribution';this._attribution.innerHTML='<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a> · <a href="https://docs.overturemaps.org/attribution/" target="_blank" rel="noopener noreferrer">© Overture Maps Foundation</a> · <a href="https://www.usgs.gov/data/annual-national-land-cover-database-nlcd-collection-1-products-ver-12-june-2026" target="_blank" rel="noopener noreferrer">USGS Annual NLCD 2025</a>';this._container.appendChild(this._attribution);
  this.touchZoomRotate={disableRotation:()=>{}};this._bind();this.resize();queueMicrotask(()=>{this._emit('load',{});this._schedule();});
 }
 on(name,fn){if(!this._events.has(name))this._events.set(name,new Set());this._events.get(name).add(fn);return this;}
 once(name,fn){const wrapped=e=>{this._events.get(name)?.delete(wrapped);fn(e);};return this.on(name,wrapped);}
 _emit(name,e){if(this._removed)return;for(const fn of [...(this._events.get(name)||[])]){try{fn(e);}catch(err){console.error('Canvas map event:',err);}}}
 isStyleLoaded(){return true;}
 addControl(){return this;}
 getCanvas(){return this._canvas;}
 getZoom(){return this._zoom;}
 getCenter(){return {lng:this._center[0],lon:this._center[0],lat:this._center[1]};}
 getContainer(){return this._container;}
 unproject(point){const center=world(...this._center),scale=512*2**this._zoom,p=geographic(center[0]+(point.x-this._width/2)/scale,center[1]+(point.y-this._height/2)/scale);return {lon:p[0],lat:p[1]};}
 getBounds(){const center=world(...this._center),scale=512*2**this._zoom,dx=(this._width||1)/2/scale,dy=(this._height||1)/2/scale;const sw=geographic(center[0]-dx,center[1]+dy),ne=geographic(center[0]+dx,center[1]-dy);return [sw[0],sw[1],ne[0],ne[1]];}
 addSource(id,definition){
  const src={id,def:definition,cache:new Map(),visible:new Set(),data:null,active:0};
  if(definition.type==='geojson')src.data=(definition.data?.features||[]).map(prepare);
  else if(definition.type==='raster'){if(typeof definition._tileURL!=='function')throw new Error('Raster source needs a tile URL builder.');}
  else if(!definition._archive)throw new Error('The 2D renderer requires the validated PMTiles archive for '+id+'.');
  src.setData=data=>{src.data=(data?.features||[]).map(prepare);this._schedule();return src;};this._sources.set(id,src);this._schedule();return this;
 }
 getSource(id){return this._sources.get(id);}
 getSourceStatus(id){const src=this._sources.get(id);if(!src)return null;const entries=[...src.visible].map(key=>src.cache.get(key));return {visible:entries.length,ready:entries.filter(e=>e?.status==='ready').length,pending:entries.filter(e=>e?.status==='queued'||e?.status==='loading').length,failed:entries.filter(e=>e?.status==='error').length};}
 addLayer(layer,before){const i=before?this._layers.findIndex(l=>l.id===before):-1;if(i>=0)this._layers.splice(i,0,{...layer});else this._layers.push({...layer});this._schedule();return this;}
 getLayer(id){return this._layers.find(l=>l.id===id);}
 setLayoutProperty(id,key,value){const l=this.getLayer(id);if(l){l.layout={...(l.layout||{}),[key]:value};this._schedule();}return this;}
 setPaintProperty(id,key,value){const l=this.getLayer(id);if(l){l.paint={...(l.paint||{}),[key]:value};this._schedule();}return this;}
 setFilter(id,filter){const l=this.getLayer(id);if(l){l.filter=filter;this._schedule();}return this;}
 _isVisible(l){return l.layout?.visibility!=='none'&&this._zoom>=(l.minzoom??0)&&this._zoom<(l.maxzoom??99);}
 resize(){if(this._removed)return this;const r=this._container.getBoundingClientRect();this._width=Math.max(1,r.width);this._height=Math.max(1,r.height);this._dpr=Math.min(2,window.devicePixelRatio||1);this._canvas.width=Math.round(this._width*this._dpr);this._canvas.height=Math.round(this._height*this._dpr);this._schedule();return this;}
 jumpTo(opts){if(opts.center)this._center=[Number(opts.center[0]),Number(opts.center[1])];const old=this._zoom;if(opts.zoom!=null)this._zoom=clamp(Number(opts.zoom),this._minZoom,this._maxZoom);this._constrain();this._schedule();if(old!==this._zoom)this._emit('zoom',{});this._emit('moveend',{});return this;}
 _constrain(){this._center[0]=clamp(this._center[0],this._bounds[0][0],this._bounds[1][0]);this._center[1]=clamp(this._center[1],this._bounds[0][1],this._bounds[1][1]);}
 _zoomAt(next,point){const oldScale=512*2**this._zoom,c=world(...this._center),wx=c[0]+(point.x-this._width/2)/oldScale,wy=c[1]+(point.y-this._height/2)/oldScale;this._zoom=clamp(next,this._minZoom,this._maxZoom);const scale=512*2**this._zoom;this._center=geographic(wx-(point.x-this._width/2)/scale,wy-(point.y-this._height/2)/scale);this._constrain();this._schedule();this._emit('zoom',{});this._emit('moveend',{});}
 _point(e){const r=this._canvas.getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top};}
 _bind(){
  let drag=null;this._canvas.addEventListener('pointerdown',e=>{if(e.button!==0&&e.pointerType==='mouse')return;this._canvas.focus({preventScroll:true});drag={point:this._point(e),center:world(...this._center),moved:false};this._canvas.setPointerCapture(e.pointerId);});
  this._canvas.addEventListener('pointermove',e=>{const p=this._point(e);if(drag){const dx=p.x-drag.point.x,dy=p.y-drag.point.y;if(Math.abs(dx)+Math.abs(dy)>3)drag.moved=true;if(drag.moved){const scale=512*2**this._zoom;this._center=geographic(drag.center[0]-dx/scale,drag.center[1]-dy/scale);this._constrain();this._canvas.style.cursor='grabbing';this._schedule();}}else this._emit('mousemove',{point:p,originalEvent:e});});
  this._canvas.addEventListener('pointerup',e=>{if(!drag)return;const moved=drag.moved;drag=null;if(this._canvas.hasPointerCapture(e.pointerId))this._canvas.releasePointerCapture(e.pointerId);this._canvas.style.cursor='';if(moved)this._emit('moveend',{});else this._emit('click',{point:this._point(e),originalEvent:e});});
  this._canvas.addEventListener('pointercancel',()=>{drag=null;this._canvas.style.cursor='';});
  this._canvas.addEventListener('wheel',e=>{e.preventDefault();this._zoomAt(this._zoom-clamp(e.deltaY,-120,120)*.003,this._point(e));},{passive:false});
  this._canvas.addEventListener('keydown',e=>{let handled=true;if(e.key==='+'||e.key==='=')this._zoomAt(this._zoom+1,{x:this._width/2,y:this._height/2});else if(e.key==='-')this._zoomAt(this._zoom-1,{x:this._width/2,y:this._height/2});else{const shift=world(...this._center),s=512*2**this._zoom;if(e.key==='ArrowLeft')shift[0]-=80/s;else if(e.key==='ArrowRight')shift[0]+=80/s;else if(e.key==='ArrowUp')shift[1]-=80/s;else if(e.key==='ArrowDown')shift[1]+=80/s;else handled=false;if(handled)this.jumpTo({center:geographic(...shift)});}if(handled)e.preventDefault();});
 }
 _schedule(){if(this._removed||this._frame)return;this._frame=requestAnimationFrame(()=>{this._frame=0;this._draw();});}
 _ensureTiles(){
  for(const src of this._sources.values()){
   if(src.def.type!=='vector'&&src.def.type!=='raster')continue;const layers=this._layers.filter(l=>l.source===src.id&&this._isVisible(l));src.visible=new Set();if(!layers.length)continue;
   const z=clamp(Math.floor(this._zoom),src.def.minzoom??0,src.def.maxzoom??14),n=2**z,v=this._viewport;
   const x0=clamp(Math.floor(v[0]*n),0,n-1),x1=clamp(Math.floor(v[2]*n),0,n-1),y0=clamp(Math.floor(v[1]*n),0,n-1),y1=clamp(Math.floor(v[3]*n),0,n-1);const jobs=[];
   for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++)jobs.push({z,x,y,d:Math.abs((x+.5)/n-this._worldCenter[0])+Math.abs((y+.5)/n-this._worldCenter[1])});jobs.sort((a,b)=>a.d-b.d);
   for(const tile of jobs.slice(0,src.def.type==='raster'?16:12)){const key=tile.z+'/'+tile.x+'/'+tile.y;src.visible.add(key);let entry=src.cache.get(key);if(!entry){entry={key,...tile,status:'queued',features:[],last:performance.now(),bounds:[tile.x/n,tile.y/n,(tile.x+1)/n,(tile.y+1)/n],layers:[...new Set(layers.map(l=>l['source-layer']))]};src.cache.set(key,entry);this._queue.push({src,entry});}entry.last=performance.now();}
   const removable=[...src.cache.values()].filter(e=>!src.visible.has(e.key)&&e.status!=='loading').sort((a,b)=>a.last-b.last);while(src.cache.size>(src.def.type==='raster'?24:12)&&removable.length){const discarded=removable.shift();discarded.image?.close?.();src.cache.delete(discarded.key);}
  }
  this._drain();
 }
 async _rasterImage(src,entry){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);entry.controller=controller;
  try{
   const response=await fetch(src.def._tileURL(entry.z,entry.x,entry.y),{signal:controller.signal});
   if(!response.ok)throw new Error('Land-cover tile returned HTTP '+response.status+'.');
   const type=response.headers.get('content-type')||'';if(!type.startsWith('image/'))throw new Error('Land-cover service returned a non-image response.');
   const blob=await response.blob();
   if(typeof createImageBitmap==='function')return await createImageBitmap(blob);
   return await new Promise((resolve,reject)=>{const image=new Image(),url=URL.createObjectURL(blob);image.onload=()=>{URL.revokeObjectURL(url);resolve(image);};image.onerror=()=>{URL.revokeObjectURL(url);reject(new Error('The land-cover image could not decode.'));};image.src=url;});
  }catch(error){if(error.name==='AbortError')throw new Error('Land-cover tile request timed out.');throw error;}
  finally{clearTimeout(timer);entry.controller=null;}
 }
 _drain(){
  while(this._active<4&&this._queue.length){
   const index=this._queue.findIndex(({src})=>src.active<(src.def.type==='raster'?2:4));if(index<0)break;
   const {src,entry}=this._queue.splice(index,1)[0];if(!src.cache.has(entry.key)||entry.status!=='queued')continue;
   if(!src.visible.has(entry.key)){src.cache.delete(entry.key);continue;}entry.status='loading';this._active++;src.active++;
   (async()=>{let timer;try{
    if(src.def.type==='raster'){
     const image=await this._rasterImage(src,entry);if(this._removed){image.close?.();return;}entry.image=image;
    }else{
     const response=await Promise.race([src.def._archive.getZxy(entry.z,entry.x,entry.y),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('A local vector tile request timed out.')),20000);})]);if(this._removed)return;
     entry.features=response?decodeTile(response.data,entry.x,entry.y,entry.z,{layers:entry.layers}).features.map(prepare):[];
    }
    entry.status='ready';
   }catch(error){entry.status='error';entry.error=error;this._emit('error',{error,sourceId:src.id});}
   finally{clearTimeout(timer);this._active--;src.active--;this._emit('sourcedata',{sourceId:src.id});this._schedule();this._drain();}})();
  }
 }
 _screen(p){return[(p[0]-this._worldCenter[0])*this._scale+this._width/2,(p[1]-this._worldCenter[1])*this._scale+this._height/2];}
 _pathFor(f){
  if(f._pathRevision===this._revision)return f._path;const path=new Path2D(),coords=f._world,t=f.geometry.type;
  const line=(ring,closed)=>{ring.forEach((p,i)=>{const q=this._screen(p);if(i===0)path.moveTo(...q);else path.lineTo(...q);});if(closed)path.closePath();};
  if(t==='Polygon')coords.forEach(r=>line(r,true));else if(t==='MultiPolygon')coords.forEach(p=>p.forEach(r=>line(r,true)));else if(t==='LineString')line(coords,false);else if(t==='MultiLineString')coords.forEach(r=>line(r,false));f._path=path;f._pathRevision=this._revision;return path;
 }
 _drawFeature(f,l,clip){
  if(!intersects(f._bbox,this._viewport))return;if(l['source-layer']&&(f.sourceLayer||f.properties.__sourceLayer)!==l['source-layer'])return;const p=f.properties||{},type=f.geometry.type;if(l.filter&&!evaluate(l.filter,p,this._zoom,type))return;
  const c=this._ctx,paint=l.paint||{},value=(key,fallback)=>paint[key]===undefined?fallback:evaluate(paint[key],p,this._zoom,type);let path,point,radius=0;
  if(l.type==='fill'&&(type==='Polygon'||type==='MultiPolygon')){path=this._pathFor(f);c.globalAlpha=Number(value('fill-opacity',1));c.fillStyle=value('fill-color','#aeb5a0');c.fill(path,'evenodd');}
  else if(l.type==='line'&&type!=='Point'){path=this._pathFor(f);c.globalAlpha=Number(value('line-opacity',1));c.strokeStyle=value('line-color','#82917a');c.lineWidth=Math.max(.2,Number(value('line-width',1)));c.setLineDash(value('line-dasharray',[]));c.stroke(path);c.setLineDash([]);}
  else if(l.type==='circle'&&type==='Point'){point=this._screen(f._world);radius=Number(value('circle-radius',4));c.globalAlpha=Number(value('circle-opacity',1));c.beginPath();c.arc(point[0],point[1],radius,0,Math.PI*2);c.fillStyle=value('circle-color','#367f83');c.fill();const width=Number(value('circle-stroke-width',0));if(width){c.strokeStyle=value('circle-stroke-color','#fff');c.lineWidth=width;c.stroke();}}
  else return;
  this._rendered.push({feature:f,layer:l,path,point,radius,clip});c.globalAlpha=1;
 }
 _draw(){
  if(this._removed)return;this._revision++;this._worldCenter=world(...this._center);this._scale=512*2**this._zoom;this._viewport=[this._worldCenter[0]-this._width/2/this._scale,this._worldCenter[1]-this._height/2/this._scale,this._worldCenter[0]+this._width/2/this._scale,this._worldCenter[1]+this._height/2/this._scale];this._ensureTiles();
  const c=this._ctx;c.setTransform(this._dpr,0,0,this._dpr,0,0);c.globalAlpha=1;c.fillStyle='#eef1e5';c.fillRect(0,0,this._width,this._height);c.lineJoin='round';c.lineCap='round';this._rendered=[];
  for(const l of this._layers){if(!this._isVisible(l))continue;const src=this._sources.get(l.source);if(!src)continue;
   if(src.def.type==='geojson'){for(const f of src.data||[])this._drawFeature(f,l,null);continue;}
   for(const key of src.visible){const entry=src.cache.get(key);if(!entry||entry.status!=='ready')continue;const a=this._screen(entry.bounds.slice(0,2)),b=this._screen(entry.bounds.slice(2)),clip=[a[0],a[1],b[0],b[1]];c.save();
    if(src.def.type==='raster'){
     if(entry.image){c.globalAlpha=Number(l.paint?.['raster-opacity']??1);c.imageSmoothingEnabled=false;c.drawImage(entry.image,a[0],a[1],b[0]-a[0],b[1]-a[1]);}
    }else{c.beginPath();c.rect(a[0],a[1],b[0]-a[0],b[1]-a[1]);c.clip();for(const f of entry.features)this._drawFeature(f,l,clip);}
    c.restore();}
  }
  const pending=[...this._sources.values()].some(src=>[...src.visible].some(k=>['queued','loading'].includes(src.cache.get(k)?.status)));if(!pending)this._emit('idle',{});
 }
 queryRenderedFeatures(pointOrOptions,options){
  let point=pointOrOptions,opts=options||{};if(pointOrOptions&&pointOrOptions.layers&&!options){opts=pointOrOptions;point=null;}const x=point?.x??point?.[0],y=point?.y??point?.[1],hasPoint=Number.isFinite(x)&&Number.isFinite(y),out=[];
  for(let i=this._rendered.length-1;i>=0;i--){const r=this._rendered[i];if(opts.layers&&!opts.layers.includes(r.layer.id))continue;if(hasPoint){if(r.clip&&(x<r.clip[0]||x>r.clip[2]||y<r.clip[1]||y>r.clip[3]))continue;if(r.point){if(Math.hypot(x-r.point[0],y-r.point[1])>r.radius+2)continue;}else if(r.path){if(r.layer.type==='fill'){if(!this._hit.isPointInPath(r.path,x,y,'evenodd'))continue;}else{this._hit.lineWidth=5;if(!this._hit.isPointInStroke(r.path,x,y))continue;}}else continue;}
   const f=r.feature;out.push({type:'Feature',id:f.id,geometry:f.geometry,properties:f.properties,sourceLayer:f.sourceLayer,layer:r.layer,source:r.layer.source});
  }return out;
 }
 remove(){this._removed=true;if(this._frame)cancelAnimationFrame(this._frame);this._queue=[];for(const src of this._sources.values())for(const entry of src.cache.values()){entry.controller?.abort();entry.image?.close?.();}this._sources.clear();this._rendered=[];this._events.clear();this._canvas.remove();this._controls.remove();this._attribution.remove();return this;}
}
