/* Badin Lake: guidebook grades and optional matched public trail lines. */
const guide = document.getElementById('trail-guide');
const originalMap = 'https://www.fs.usda.gov/media/241208';
const guideData = new URL('./data/badin_trails.json', import.meta.url);
const profiles = {
  bronco: {
    label: 'Ford Bronco Badlands',
    trim: '2025 · U.S. four-door Bronco Badlands',
    description: 'Ford lists Bilstein position-sensitive shocks and a disconnecting front stabilizer bar for this Badlands trim.',
    url: 'https://www.fromtheroad.ford.com/content/dam/fordmediasite/us/en/library/2025/order-guides/2025_Ford_Bronco_Order_Guide.pdf',
    source: 'Ford order guide'
  },
  u8: {
    label: 'YANGWANG U8 Premium',
    trim: 'Premium Edition · 2023 China launch specification',
    description: 'BYD describes four independently controlled drive motors and the DiSus-P hydraulic body-control system. This profile does not establish U.S. vehicle eligibility.',
    url: 'https://www.byd.com/us/news-list/BYD-Launched-the-U8-Premium-Edition-Under-Its-High-End-Sub-Brand-Yangwang.html',
    source: 'BYD launch specification'
  }
};
const labels = ['', 'Easy', 'Moderate', 'Difficult', 'Extremely Difficult'];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const safeURL = (raw, fallback = '') => {
  if (!raw) return fallback;
  try {
    const u = new URL(raw, document.baseURI);
    return /^https?:$/.test(u.protocol) ? u.href : fallback;
  } catch { return fallback; }
};
const link = (href, label, cls = '') => '<a class="'+cls+'" href="'+esc(href)+'" target="_blank" rel="noopener noreferrer">'+esc(label)+' <span aria-hidden="true">↗</span></a>';
const miles = t => t.miles != null && Number.isFinite(Number(t.miles)) ? Number(t.miles).toLocaleString('en-US', {maximumFractionDigits:2})+' mi' : 'Not listed';
const gradeBadge = g => '<span class="tg-badge tg-g'+g+'" aria-label="Grade '+g+'">'+g+'</span>';
const linesFor = g => {
  const lines = g?.type === 'LineString' ? [g.coordinates] : g?.type === 'MultiLineString' ? g.coordinates : [];
  return Array.isArray(lines) ? lines.filter(l => Array.isArray(l) && l.length > 1 && l.every(p => Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]) && Math.abs(p[0])<=180 && Math.abs(p[1])<=90)) : [];
};
function routePaths(trails) {
  const items = trails.map(t => ({t, lines:linesFor(t.geometry)})).filter(i => i.lines.length);
  if (!items.length) return [];
  let west=Infinity,east=-Infinity,south=Infinity,north=-Infinity;
  items.forEach(i => i.lines.forEach(l => l.forEach(([x,y]) => {
    west=Math.min(west,x);east=Math.max(east,x);north=Math.max(north,y);south=Math.min(south,y);
  })));
  const cosLat=Math.cos((south+north)/2*Math.PI/180), w=560, h=330, pad=26;
  const scale=Math.min((w-2*pad)/Math.max(1e-9,(east-west)*cosLat),(h-2*pad)/Math.max(1e-9,north-south));
  function project([x,y]) {return [(w/2+(x-(west+east)/2)*cosLat*scale).toFixed(2),(h/2+((south+north)/2-y)*scale).toFixed(2)].join(',');}
  return items.map(({t,lines}) => ({...t, d:lines.map(line => line.map((xy,n) => (n?'L':'M')+project(xy)).join('')).join('')}));
}
function start(data) {
  const trails = data.trails.filter(t => t?.name && t.id != null && [1,2,3,4].includes(Number(t.grade))).map(t => ({...t,id:String(t.id),grade:Number(t.grade)})).sort((a,b) => a.grade-b.grade || a.name.localeCompare(b.name));
  if (!trails.length) throw new Error('No guide records');
  const mapUrl=safeURL(data.sourceUrl, originalMap), geometryUrl=safeURL(data.geometrySourceUrl), imgUrl=safeURL(data.mapImageUrl||data.sourceMapImage), seasonUrl=safeURL(data.seasonOrderUrl);
  const paths=routePaths(trails);
  let selected=trails[0], vehicle='bronco';
  guide.innerHTML = `
    <div class="tg-head">
      <div><p class="tg-kicker">Civilian 4×4 trail guide · North Carolina</p>
      <h2>Badin Lake motorized trails</h2><p class="tg-intro">Explore the Uwharrie National Forest trails marked for full-size vehicles. Select a trail to see its Forest Service difficulty rating.</p></div>
      <span class="tg-count"><b>${trails.length}</b> published trails</span>
    </div>
    <div class="tg-grid">
      <section class="tg-mapbox tg-box" aria-labelledby="tg-map-heading">
        <header class="tg-maphead"><div><p class="tg-kicker">Uwharrie National Forest</p><h3 id="tg-map-heading">Badin Lake trail map</h3></div>${link(mapUrl,'Official map','tg-official')}</header>
        <div class="tg-mapstage"></div>
        <div class="tg-legend" aria-label="Atlas grade key">${labels.slice(1).map((v,i) => '<span>'+gradeBadge(i+1)+' '+esc(v)+'</span>').join('')}</div>
        <div class="tg-selection" aria-live="polite"></div>
      </section>
      <section class="tg-listbox tg-box" aria-labelledby="tg-list-heading">
        <header><p class="tg-kicker">Trail register</p><h3 id="tg-list-heading">Trails by difficulty</h3></header>
        <div class="tg-list"><div class="tg-colhead" aria-hidden="true"><span>Trail / official rating</span><span>Length</span></div></div>
      </section>
    </div>
    <section class="tg-profiles tg-box" aria-labelledby="tg-profile-heading">
      <div><p class="tg-kicker">Vehicle reference</p><h3 id="tg-profile-heading">Choose a vehicle profile</h3><div class="tg-toggle" role="group" aria-label="Civilian vehicle profile">${Object.entries(profiles).map(([id,p])=>'<button type="button" data-vehicle="'+id+'">'+p.label+'</button>').join('')}</div></div>
      <div class="tg-profile-details" aria-live="polite"></div>
    </section>
    <p class="tg-notes" id="tg-season" aria-live="polite"></p><div class="tg-notes"><strong>How to read the grades.</strong> The atlas numbers 1–4 represent the Forest Service’s four ordered labels. The same grade applies to both profiles; the sources do not establish a vehicle-specific or monthly adjustment. The published trail rating does not confirm present conditions or whether a trail is open. ${seasonUrl?link(seasonUrl,'Forest Service seasonal order'):''}</div>`;
  const list = guide.querySelector('.tg-list'), mapstage = guide.querySelector('.tg-mapstage');
  list.insertAdjacentHTML('beforeend', trails.map(t=>`<button class="tg-row" type="button" data-select="${esc(t.id)}">${gradeBadge(t.grade)}<span><strong>${esc(t.name)}</strong><small>${esc(t.officialRating || labels[t.grade])}</small></span><span class="tg-mi">${esc(miles(t))}</span></button>`).join(''));
  if (paths.length) {
    mapstage.innerHTML=`<svg class="tg-svg" viewBox="0 0 560 330" role="img" aria-labelledby="tg-svg-title tg-svg-desc"><title id="tg-svg-title">Verified Badin Lake trail lines</title><desc id="tg-svg-desc">North at top. Choose a trail in the register to highlight it.</desc><g class="tg-base"></g><g class="tg-emphasis" pointer-events="none"></g><g fill="currentColor" aria-hidden="true"><path d="M536 44 L531 55 L536 52 L541 55 Z"/><text x="536" y="38" text-anchor="middle" font-size="13">N</text></g></svg><p class="tg-mapcaption">Verified linework for ${paths.length} of ${trails.length} trails.${geometryUrl?' '+link(geometryUrl,'Geometry source'):''}</p>`;
    const base=guide.querySelector('.tg-base');
    base.innerHTML=paths.map(p=>`<path class="tg-route tg-g${p.grade}" data-map-select="${esc(p.id)}" d="${p.d}"><title>${esc(p.name)} · ${esc(p.officialRating || labels[p.grade])}</title></path>`).join('');
  } else if (imgUrl) {
    mapstage.innerHTML=`<a class="tg-mapimage" href="${esc(mapUrl)}" target="_blank" rel="noopener noreferrer"><img src="${esc(imgUrl)}" alt="Forest Service map of Badin Lake recreation area. Open the official PDF to enlarge."></a><p class="tg-mapcaption">Forest Service map. Use the trail name and number below to locate the route.</p>`;
    mapstage.querySelector('img').addEventListener('error',showOriginal,{once:true});
  } else showOriginal();
  function showOriginal(){
    mapstage.innerHTML=`<div class="tg-original"><p class="tg-kicker">Forest Service map sheet</p><h3>Badin Lake Recreation Area</h3><p>Find trail numbers, junctions and trailheads on the original map. Use the register to compare published trail grades and lengths.</p>${link(mapUrl,'Open the Forest Service map (PDF)','tg-cta')}</div>`;
  }
  function updateSeason() {
    const n=Number(window.NovemberAtlas?.month)||11, m=window.NovemberAtlas?.monthName||'November';
    const note=n<=3?'The Forest Service’s recurring winter closure covers this entire month.':n===12?'The standing winter closure starts December 15; the first 14 days are outside that recurring closure.':'This month falls outside the standing December 15–March 31 closure.';
    guide.querySelector('#tg-season').innerHTML='<strong>'+esc(m)+' · seasonal access</strong> '+esc(note)+' Check current Forest Service notices before a trip. '+(seasonUrl?link(seasonUrl,'Seasonal order'):'');
  }
  updateSeason();document.addEventListener('atlas:month',updateSeason);
  let sample=null;
  function refreshClimate(){
    const box=guide.querySelector('.tg-climate');
    if(!box || !sample)return;
    const [lon,lat]=sample, coord=Math.abs(lat).toFixed(3)+'°'+(lat<0?'S':'N')+', '+Math.abs(lon).toFixed(3)+'°'+(lon<0?'W':'E');
    const info=window.NovemberAtlas?.readClimate?.(lon,lat);
    const selectedMonth=window.NovemberAtlas?.monthName||'Selected month';
    const txt=!info||info.status==='loading'?'Loading climate context…':info.status==='error'?selectedMonth+' climate source unavailable.':'Mean air temperature: '+(info.temperature??'unavailable')+' · Mean monthly precipitation: '+(info.precipitation??'unavailable')+'.';
    box.innerHTML='<strong>'+esc(selectedMonth)+' at one trail point · 2006–2025</strong> · '+coord+'<br>'+esc(txt)+'<br><button type="button" data-inspect>Inspect land &amp; water at this point <span aria-hidden="true">→</span></button>';
  }
  document.addEventListener('atlas:month',refreshClimate);
  document.addEventListener('atlas:climate-ready',refreshClimate);
  document.addEventListener('atlas:units',refreshClimate);
  function chooseTrail(id){
    selected=trails.find(t=>t.id===id)||trails[0];
    list.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.select===selected.id)));
    const hit=paths.find(p=>p.id===selected.id);
    const emphasis=guide.querySelector('.tg-emphasis');
    if(emphasis) emphasis.innerHTML=hit?`<path class="tg-halo" d="${hit.d}"/><path class="tg-chosen tg-g${hit.grade}" d="${hit.d}"/>`:'';
    const note=selected.geometryNote || (!hit?' No verified line is available for this selection.':'');
    const firstLine=hit?linesFor(selected.geometry)[0]:null;
    sample=firstLine?firstLine[Math.floor((firstLine.length-1)/2)].slice(0,2):null;
    guide.querySelector('.tg-selection').innerHTML=`<div><p class="tg-kicker">Selected trail · No. ${esc(selected.id)}</p><h3>${esc(selected.name)}</h3></div><p class="tg-readout">${gradeBadge(selected.grade)} <strong>${esc(selected.officialRating||labels[selected.grade])}</strong> <span>·</span> ${esc(miles(selected))}</p><p class="tg-mapfoot">${link(mapUrl,'View the official trail map')} ${esc(note)}</p>${sample?'<p class="tg-climate"></p>':''}`;
    refreshClimate();
  }
  function chooseVehicle(id){
    vehicle=profiles[id]?id:'bronco';const p=profiles[vehicle];
    guide.querySelectorAll('[data-vehicle]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.vehicle===vehicle)));
    guide.querySelector('.tg-profile-details').innerHTML=`<strong>${esc(p.trim)}</strong><p>${esc(p.description)}</p>${link(p.url,p.source)}`;
    document.dispatchEvent(new CustomEvent('atlas:civilian-vehicle',{detail:{label:p.label,id:vehicle}}));
  }
  guide.addEventListener('click',e=>{
    const t=e.target.closest('[data-select],[data-map-select]'), v=e.target.closest('[data-vehicle]');
    if(t) chooseTrail(t.dataset.select??t.dataset.mapSelect);
    if(v) chooseVehicle(v.dataset.vehicle);
    if(e.target.closest('[data-inspect]') && sample) document.dispatchEvent(new CustomEvent('atlas:open-detail',{detail:{lon:sample[0],lat:sample[1],name:selected.name+' · trail sample'}}));
  });
  chooseTrail(selected.id); chooseVehicle(vehicle);
}
if(guide) {
  guide.innerHTML='<p class="tg-notes" role="status">Loading the Forest Service trail register…</p>';
  fetch(guideData).then(r=>{if(!r.ok)throw new Error(String(r.status));return r.json()}).then(start).catch(()=>{
    guide.innerHTML='<div class="tg-box tg-original" role="status"><h2>Badin Lake trail guide</h2><p>The trail register could not be loaded. The original Forest Service map includes the trail names, distances and ratings.</p>'+link(originalMap,'Open the official map (PDF)','tg-cta')+'</div>';
  });
}
