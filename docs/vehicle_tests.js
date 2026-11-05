/* Public source records. All numerical outputs retain their published test metric. */
const host=document.getElementById('vehicle-test-register');
const html=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sourceLink=(url,title)=>{
  try { const u=new URL(url); if(u.protocol!=='https:')return html(title);
    return '<a href="'+html(u.href)+'" target="_blank" rel="noopener noreferrer">'+html(title)+' ↗</a>';
  } catch {return html(title);}
};
const dataPath='data/civilian_vehicle_tests.json',csvPath='data/civilian_vehicle_tests.csv';
const downloads='<div class="vt-downloads"><a href="'+csvPath+'" download>Download all records · CSV ↓</a><a href="'+dataPath+'" download>JSON ↓</a></div>';
function render(data) {
 const rows=Array.isArray(data.records)?data.records:[];if(!rows.length)throw Error('No source records');
 host.innerHTML='<div class="vt-head"><div><p class="eyebrow">Vehicle evidence</p><h2>What has been tested?</h2><p>Compare the original vehicles, conditions and measurements. Select a test to read its setup and limits.</p></div>'+downloads+'</div><div class="vt-toolbar"><label>Show records <select aria-label="Filter vehicle evidence"><option>All vehicles</option><option>Bronco</option><option>U8</option><option>Other 4×4s</option></select></label><span class="vt-count" role="status"></span></div><div class="vt-scroll"><table><caption class="sr-only">Published civilian vehicle observations and benchmarks</caption><thead><tr><th>Vehicle and trim</th><th>Test / conditions</th><th>Published result</th><th>Source</th></tr></thead><tbody></tbody></table></div><div class="vt-interpretation"><p><strong>Reading the evidence:</strong> Ford’s published articulation index rises from 500 to 620 with the bar disconnected (+120 points, or 24%). That percentage applies only to this index. The 2024 Sasquatch outing and braking test used a different Bronco from the 2025 reference configuration.</p><p><strong>Data access:</strong> The downloads contain source-reported results. No run-level GPS or CAN logs were located in these SUV reports. '+sourceLink(data.benchmark.url,'TartanDrive 2.0')+' offers separately collected off-road sensor data for studying measurement methods.</p></div>';
 const select=host.querySelector('select'),body=host.querySelector('tbody'),count=host.querySelector('.vt-count');
 function update(){
  const chosen=rows.filter(r=>select.value==='All vehicles'||r.group===select.value);
  count.textContent=chosen.length+' of '+rows.length+' records';
  body.innerHTML=chosen.map(r=>'<tr><td><b>'+html(r.model_year)+' '+html(r.model)+'</b><small>'+html(r.trim)+'</small></td><td><details><summary>'+html(r.metric)+'</summary><div class="vt-details"><p><b>Setup:</b> '+html(r.conditions)+'</p><p><b>Vehicle:</b> '+html(r.body)+'. '+html(r.tires)+'</p><p><b>Limit:</b> '+html(r.transfer_limit)+'</p><p><b>Raw data:</b> '+html(r.raw_logs)+'</p></div></details><small>'+html(r.evidence_type)+'</small></td><td class="vt-result">'+(Number.isFinite(r.numeric_value)?'<b>'+html(r.numeric_value)+' '+html(r.unit)+'</b>'+(r.reported_outcome?'<small>'+html(r.reported_outcome)+'</small>':''):html(r.reported_outcome))+'</td><td>'+sourceLink(r.source_url,r.source_publisher)+'<small>'+html(r.source_date)+'</small></td></tr>').join('');
 }
 select.addEventListener('change',update);update();
}
if(host){
 host.setAttribute('aria-label','Published civilian vehicle tests');
 host.innerHTML='<p role="status">Loading vehicle evidence…</p>';
 fetch(dataPath).then(r=>{if(!r.ok)throw Error(r.status);return r.json();}).then(render).catch(()=>{host.innerHTML='<h2>Published vehicle tests</h2><p>The source register could not be displayed.</p>'+downloads;});
}
