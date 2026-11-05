// Shared, local FHWA inventory snapshot. Locations are records, not crossing assessments.
let pointsPromise, spatialIndex;
const statePromises = new Map();
async function json(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}.`);
  return response.json();
}
export function loadBridgePoints(retry = false) {
  if (retry) pointsPromise = null;
  if (!pointsPromise) pointsPromise = json('data/bridge_points.json').then(data => {
    if (!data.pointsByState || !data.source) throw new Error('The bridge location snapshot is incomplete.');
    return data;
  }).catch(error => { pointsPromise = null; throw error; });
  return pointsPromise;
}
export async function loadBridgeRecord(state, index) {
  if (!/^[A-Z]{2}$/.test(state)) throw new Error('Invalid source state code.');
  if (!statePromises.has(state)) statePromises.set(state, json(`data/bridge_${state}.json`).catch(error => { statePromises.delete(state); throw error; }));
  const data = await statePromises.get(state), row = data.records?.[index];
  if (!row) throw new Error('The requested inventory row is unavailable.');
  return { ...Object.fromEntries(data.fields.map((name, i) => [name, row[i]])), state, sourceUrl: data.sourceUrl, snapshotDate: data.snapshotDate };
}
function indexPoints(data) {
  if (spatialIndex?.data === data) return spatialIndex;
  const states = Object.keys(data.pointsByState), cells = new Map();
  states.forEach((state, s) => {
    const points = data.pointsByState[state];
    for (let i = 0; i < points.length; i += 2) {
      const key = `${Math.floor(points[i] * 2)},${Math.floor(points[i + 1] * 2)}`;
      let cell = cells.get(key); if (!cell) cells.set(key, cell = []);
      cell.push(s, i);
    }
  });
  return spatialIndex = { data, states, cells };
}
export function bridgesInBounds(data, bounds) {
  const { states, cells } = indexPoints(data), [west, south, east, north] = bounds, result = [];
  for (let x = Math.floor(west * 2); x <= Math.floor(east * 2); x++) for (let y = Math.floor(south * 2); y <= Math.floor(north * 2); y++) {
    const cell = cells.get(`${x},${y}`); if (!cell) continue;
    for (let j = 0; j < cell.length; j += 2) {
      const state = states[cell[j]], i = cell[j + 1], points = data.pointsByState[state], lon = points[i], lat = points[i + 1];
      if (lon >= west && lon <= east && lat >= south && lat <= north) result.push({ state, index: i / 2, lon, lat });
    }
  }
  return result;
}
export function bridgeFeatureCollection(records) {
  return { type: 'FeatureCollection', features: records.map(r => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [r.lon, r.lat] }, properties: { state: r.state, index: r.index, key: `${r.state}:${r.index}` } })) };
}
