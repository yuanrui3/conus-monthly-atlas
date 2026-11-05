import {PMTiles} from './vendor/pmtiles.mjs';

const TIMEOUT_MS = 10000;
const RELEASE_PATTERN = /^\d{4}-\d{2}-\d{2}\.\d+$/;
const CATALOG_URL = 'https://stac.overturemaps.org/catalog.json';
const TILE_TEMPLATE = 'https://overturemaps-extras-us-west-2.s3.us-west-2.amazonaws.com/tiles/{release}/{theme}.pmtiles';

function messageOf(error) {
  return error?.message || String(error);
}

async function withTimeout(promise, label) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} did not respond within 10 seconds.`)), TIMEOUT_MS);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function fetchJSON(url, label) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(url, {signal: controller.signal, cache: 'no-cache'});
    if (!response.ok) throw new Error(`${label} returned HTTP ${response.status}.`);
    return await response.json();
  } catch (error) {
    if (error?.name === 'AbortError') throw new Error(`${label} did not respond within 10 seconds.`);
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function validateRelease(release) {
  if (typeof release !== 'string' || !RELEASE_PATTERN.test(release)) {
    throw new Error('The source did not provide a valid dated release identifier.');
  }
  return release;
}

function archiveURL(config, release, theme, usePinned = false) {
  validateRelease(release);
  const template = config.discovery?.public_pmtiles_theme_template || TILE_TEMPLATE;
  const value = usePinned && theme === 'buildings'
    ? config.pinned?.pmtiles_url || config.pinned?.url
    : template.replaceAll('{release}', release).replaceAll('{theme}', theme);
  const url = new URL(value || TILE_TEMPLATE.replaceAll('{release}', release).replaceAll('{theme}', theme));
  if (url.protocol !== 'https:') throw new Error('The inspection archive must use HTTPS.');
  return url.href;
}

function pinIsExpired(config) {
  const expiration = Date.parse(config.pinned?.observed_expiration || '');
  return Number.isFinite(expiration) && Date.now() >= expiration;
}

async function validateArchive(url, layer, label, protocol) {
  const archive = new PMTiles(url);
  const [header, metadata] = await withTimeout(
    Promise.all([archive.getHeader(), archive.getMetadata()]), label,
  );
  if (header.tileType !== 1) throw new Error(`${label} is not an MVT vector archive.`);
  const layerMetadata = Array.isArray(metadata.vector_layers)
    ? metadata.vector_layers.find(item => item.id === layer)
    : null;
  if (!layerMetadata) throw new Error(`${label} no longer contains the expected “${layer}” layer.`);
  if (!Number.isInteger(header.minZoom) || !Number.isInteger(header.maxZoom) || header.maxZoom < header.minZoom) {
    throw new Error(`${label} has invalid zoom metadata.`);
  }
  protocol.add(archive);
  return {url, archive, header, metadata, layer, layerMetadata};
}

/** Load the atlas's checked source manifest, including dated fallback evidence. */
export async function loadBuildingConfig() {
  const config = await fetchJSON(new URL('./data/building_source.json', import.meta.url), 'Building source manifest');
  if (!config || typeof config !== 'object' || !config.pinned) {
    throw new Error('The building source manifest is incomplete.');
  }
  validateRelease(config.pinned.release);
  return config;
}

/**
 * Discover and validate the current public inspection release. Optional context
 * archives share that exact release. A failed service never means no buildings.
 * Timeout races bound UI waiting; PMTiles may finish its cached range reads later.
 */
export async function resolveBuildingRelease(config, protocol) {
  if (!protocol || typeof protocol.add !== 'function') throw new Error('The PMTiles protocol is not ready.');
  const warnings = [];
  let release;
  let building;
  let mode = 'current';
  let latestFailure;

  try {
    const catalog = await fetchJSON(config.discovery?.catalog_url || CATALOG_URL, 'Current Overture release catalog');
    release = validateRelease(catalog.latest);
    if (release === config.pinned?.release && pinIsExpired(config)) {
      throw new Error(`Release ${release} has passed its observed retention date.`);
    }
    building = await validateArchive(archiveURL(config, release, 'buildings'), 'building', 'Current building archive', protocol);
  } catch (error) {
    latestFailure = error;
  }

  if (!building) {
    const pinned = config.pinned;
    if (!pinned || pinIsExpired(config)) {
      const expiry = pinned?.observed_expiration ? ` Its checked fallback expired on ${pinned.observed_expiration.slice(0, 10)}.` : '';
      throw new Error(`Building inspection is unavailable: ${messageOf(latestFailure)}${expiry} This is a source-service failure; it does not show that buildings are absent.`);
    }
    release = validateRelease(pinned.release);
    try {
      building = await validateArchive(archiveURL(config, release, 'buildings', true), 'building', 'Dated building fallback', protocol);
    } catch (error) {
      throw new Error(`Building inspection is unavailable. Current release: ${messageOf(latestFailure)} Checked fallback ${release}: ${messageOf(error)} This does not show that buildings are absent.`);
    }
    mode = 'dated fallback';
    warnings.push(`The current release could not be verified (${messageOf(latestFailure)}). Showing checked release ${release}; it may be older than the latest source.`);
  }

  const references = {base: null, transportation: null};
  const referenceJobs = [
    {theme: 'base', layer: 'water', label: 'Water and bridge reference archive'},
    {theme: 'transportation', layer: 'segment', label: 'Road reference archive'},
  ];
  const referenceResults = await Promise.allSettled(referenceJobs.map(async job => validateArchive(
    archiveURL(config, release, job.theme), job.layer, job.label, protocol,
  )));
  referenceResults.forEach((result, index) => {
    const job = referenceJobs[index];
    if (result.status === 'fulfilled') references[job.theme] = result.value;
    else warnings.push(`${job.label} is unavailable: ${messageOf(result.reason)} Buildings remain available.`);
  });
  return {release, mode, building, references, warnings};
}
