// Official USGS WMS imagery and raw class queries. No classifications are
// inferred from rendered colors, overview cells or neighboring features.
const HALF_WORLD = 20037508.342789244;
const RAD = Math.PI / 180;
let configPromise;

async function json(url, label) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) throw new Error(`${label} returned HTTP ${response.status}.`);
    return await response.json();
  } catch (error) {
    throw new Error(error.name === 'AbortError' ? `${label} timed out.` : error.message);
  } finally { clearTimeout(timer); }
}

export function loadLandcoverDetailConfig(retry = false) {
  if (retry) configPromise = null;
  if (!configPromise) configPromise = json('data/landcover_detail_source.json', 'Local land-cover source record').then(config => {
    if (!config.wms?.url || !config.wms.layer || !config.wms.time || !Array.isArray(config.classes)) throw new Error('The local land-cover source record is incomplete.');
    if (new URL(config.wms.url).protocol !== 'https:') throw new Error('The land-cover service must use HTTPS.');
    return config;
  }).catch(error => { configPromise = null; throw error; });
  return configPromise;
}

function parameters(config) {
  const w = config.wms;
  return {
    SERVICE: 'WMS', VERSION: w.version || '1.3.0', REQUEST: 'GetMap',
    LAYERS: w.layer, STYLES: w.style || 'raster', TIME: w.time,
    CRS: w.crs || 'EPSG:3857', FORMAT: w.format || 'image/png', TRANSPARENT: 'true'
  };
}

function urlWith(base, params) {
  const url = new URL(base);
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, String(value));
  return url.href;
}

export function landcoverTileURL(config, z, x, y) {
  const span = 2 * HALF_WORLD / 2 ** z;
  return urlWith(config.wms.url, {
    ...parameters(config), WIDTH: config.wms.tileSize || 256, HEIGHT: config.wms.tileSize || 256,
    BBOX: [-HALF_WORLD + x * span, HALF_WORLD - (y + 1) * span, -HALF_WORLD + (x + 1) * span, HALF_WORLD - y * span].join(',')
  });
}

export async function queryLandcoverClass(config, lon, lat) {
  const q = config.featureInfo;
  if (!q?.enabled) throw new Error('The source does not provide a verified local class-query service.');
  const width = q.queryWidth || 3, height = q.queryHeight || 3;
  const meters = q.queryGroundResolutionMeters || config.nativeResolutionMeters || 30;
  const mercatorScale = 1 / Math.cos(lat * RAD), x = lon / 180 * HALF_WORLD;
  const y = Math.log(Math.tan(Math.PI / 4 + lat * RAD / 2)) / Math.PI * HALF_WORLD;
  const dx = width * meters * mercatorScale / 2, dy = height * meters * mercatorScale / 2;
  const url = urlWith(q.url || config.wms.url, {
    ...parameters(config), REQUEST: q.request || 'GetFeatureInfo', QUERY_LAYERS: config.wms.layer,
    INFO_FORMAT: q.infoFormat || 'application/json', FEATURE_COUNT: 1,
    WIDTH: width, HEIGHT: height, I: q.queryI ?? 1, J: q.queryJ ?? 1,
    BBOX: [x - dx, y - dy, x + dx, y + dy].join(',')
  });
  const data = await json(url, 'USGS local land-cover class query');
  const raw = data.features?.[0]?.properties?.[q.valueProperty || 'PALETTE_INDEX'];
  const value = raw == null ? null : Number(raw);
  const noData = value == null || !Number.isFinite(value) || (q.noDataValues || [250]).includes(value);
  const category = noData ? null : config.classes.find(item => item.value === value);
  if (!noData && !category) throw new Error(`The source returned an unrecognized land-cover code (${raw}).`);
  return { value: category ? value : null, category, lon, lat, queryGroundResolutionMeters: meters, sourceUrl: url };
}
