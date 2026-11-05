const month = document.getElementById('atlas-month');
for (const button of document.querySelectorAll('[data-step-month]')) {
  button.addEventListener('click', () => {
    const step = Number(button.dataset.stepMonth);
    month.value = String((Number(month.value) - 1 + step + 12) % 12 + 1);
    month.dispatchEvent(new Event('change', {bubbles: true}));
  });
}

function setFlowDownload(n) {
  for (const a of document.querySelectorAll("[data-month-water-download]")) {
    const mm=String(n).padStart(2,"0"); a.href="data/water_months/"+mm+".json.gz"; a.download="conus_streamflow_"+mm+"_2006_2025.json.gz";
  }
}
document.addEventListener("atlas:month",e=>setFlowDownload(e.detail.month));
setFlowDownload(Number(month.value));
