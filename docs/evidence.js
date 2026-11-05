// Present supplied environmental measurements and their source support.
// This component does not retrieve data, infer missing values, or calculate a score.
const STATUS = {
  available: { label: 'Available', className: 'available' },
  missing: { label: 'Unavailable', className: 'missing' },
  loading: { label: 'Loading', className: 'select' },
  select: { label: 'Choose a location', className: 'select' }
};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[character]));
}

function records(value) {
  return Array.isArray(value) ? value.filter(item => item && typeof item === 'object') : [];
}

function selectedPosition(point) {
  if (!point || !Number.isFinite(point.lon) || !Number.isFinite(point.lat)) return '';
  if (Math.abs(point.lon) > 180 || Math.abs(point.lat) > 90) return '';
  const latitude = Math.abs(point.lat).toFixed(3) + '° ' + (point.lat < 0 ? 'S' : 'N');
  const longitude = Math.abs(point.lon).toFixed(3) + '° ' + (point.lon < 0 ? 'W' : 'E');
  return latitude + ' · ' + longitude;
}

function fieldMarkup(field, index) {
  const status = Object.hasOwn(STATUS, field.status) ? STATUS[field.status] : STATUS.missing;
  const value = field.valueText == null || field.valueText === '' ? status.label : field.valueText;
  return '<article class="evidence-card" data-evidence-id="' + escapeHtml(field.id ?? ('field-' + index)) + '">' +
    '<div class="evidence-card-heading"><h3>' + escapeHtml(field.label || 'Environmental measurement') + '</h3>' +
    '<span class="evidence-status evidence-status-' + status.className + '">' + status.label + '</span></div>' +
    '<p class="evidence-value">' + escapeHtml(value) + '</p>' +
    '<dl class="evidence-source-meta">' +
    '<div><dt>Period</dt><dd>' + escapeHtml(field.period || 'Not supplied') + '</dd></div>' +
    '<div><dt>Spatial support</dt><dd>' + escapeHtml(field.support || 'Not supplied') + '</dd></div></dl>' +
    (field.note ? '<p class="evidence-note">' + escapeHtml(field.note) + '</p>' : '') + '</article>';
}

/**
 * Render an evidence summary from values supplied by the atlas.
 * The caller owns the location lookup, data availability and source interpretation.
 * An open/closed missing-conditions disclosure retains its state across updates.
 */
export function renderEvidenceCoverage(element, snapshot = {}) {
  if (!element || typeof element !== 'object' || !('innerHTML' in element)) {
    throw new TypeError('An evidence coverage container is required.');
  }
  snapshot = snapshot && typeof snapshot === 'object' ? snapshot : {};
  const fields = records(snapshot.fields), missing = records(snapshot.missing);
  const notes = Array.isArray(snapshot.inspectionNotes)
    ? snapshot.inspectionNotes.filter(note => note != null && note !== '') : [];
  const previousDisclosure = element.querySelector?.('.evidence-missing');
  const missingOpen = previousDisclosure ? previousDisclosure.open : true;
  const position = selectedPosition(snapshot.point);
  const location = snapshot.locationLabel || (position ? 'Selected map location' : 'Choose a place on the overview map');

  element.classList?.add('evidence-coverage');
  element.innerHTML = '<header class="evidence-heading"><div><p class="eyebrow">MEASUREMENTS &amp; SOURCE SUPPORT</p>' +
    '<h2>Environmental evidence coverage</h2></div>' +
    '<div class="evidence-location"><strong>' + escapeHtml(location) + '</strong>' +
    (position ? '<span>Selected map position · ' + escapeHtml(position) + '</span>' :
      '<span>Choose a location to check the available grid estimates.</span>') + '</div></header>' +
    '<div class="evidence-card-grid">' + fields.map(fieldMarkup).join('') + '</div>' +
    (missing.length ? '<details class="evidence-missing"' + (missingOpen ? ' open' : '') + '>' +
      '<summary>Conditions without measurements</summary><ul class="evidence-missing-grid">' +
      missing.map(item => '<li><div class="evidence-missing-heading"><strong>' + escapeHtml(item.label) +
        '</strong><span class="evidence-status evidence-status-missing">Not measured in this release</span></div>' +
        (item.detail ? '<p>' + escapeHtml(item.detail) + '</p>' : '') + '</li>').join('') + '</ul></details>' : '') +
    (notes.length ? '<aside class="evidence-inspection"><h3>Read alongside the map</h3><ul>' +
      notes.map(note => '<li>' + escapeHtml(note) + '</li>').join('') + '</ul></aside>' : '') +
    '<p class="evidence-scale-note">Finer map display does not increase the resolution of these measurements.</p>';
}
