import { PMTiles } from './vendor/pmtiles.mjs';
const RELEASE = /^\d{4}-\d{2}-\d{2}\.\d+$/;
const TEMPLATE = 'https://overturemaps-extras-us-west-2.s3.us-west-2.amazonaws.com/tiles/{release}/base.pmtiles';
async function json(url, label) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(url, { signal: controller.signal, cache: 'no-cache' });
    if (!response.ok) throw new Error(`${label} returned HTTP ${response.status}.`);
    return await response.json();
  } catch (error) { throw new Error(error.name === 'AbortError' ? `${label} timed out.` : error.message); }
  finally { clearTimeout(timer); }
}
async function archiveFor(release) {
  if (!RELEASE.test(release)) throw new Error('No valid dated Overture release was supplied.');
  const url = TEMPLATE.replace('{release}', release), archive = new PMTiles(url);
  let timer;
  try {
    const [header, metadata] = await Promise.race([
      Promise.all([archive.getHeader(), archive.getMetadata()]),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Water archive validation timed out.')), 10000); })
    ]);
    const layerMetadata = metadata.vector_layers?.find(layer => layer.id === 'water');
    if (header.tileType !== 1 || !layerMetadata) throw new Error('The archive does not contain the expected vector water layer.');
    return { url, archive, header, metadata, layer: 'water', layerMetadata };
  } finally { clearTimeout(timer); }
}
// Reads retained source provenance, then opens only the base-water archive.
// No building or transportation archive is requested.
export async function resolveWaterRelease() {
  const config = await json(new URL('./data/building_source.json', import.meta.url), 'Overture source record');
  let failure;
  try {
    const catalog = await json(config.discovery?.catalog_url || 'https://stac.overturemaps.org/catalog.json', 'Overture release catalog');
    const release = catalog.latest;
    if (release === config.pinned?.release && Date.now() >= Date.parse(config.pinned?.observed_expiration || '')) throw new Error('The latest listed release has passed its checked retention date.');
    return { release, mode: 'current release verified', water: await archiveFor(release), warnings: [] };
  } catch (error) { failure = error.message; }
  const pin = config.pinned, expiry = Date.parse(pin?.observed_expiration || '');
  if (!pin || !Number.isFinite(expiry) || Date.now() >= expiry) throw new Error(`Water geometry unavailable: ${failure} No unexpired checked fallback is available.`);
  try { return { release: pin.release, mode: 'dated fallback verified', water: await archiveFor(pin.release), warnings: [`Current release could not be verified: ${failure}`] }; }
  catch (error) { throw new Error(`Water geometry unavailable. Current release: ${failure} Dated fallback: ${error.message}`); }
}
