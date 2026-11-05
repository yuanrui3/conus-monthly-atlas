#!/usr/bin/env node
/**
 * Verify Overture's public inspection tiles with bounded HTTP range requests.
 * Requires Node 22+ and the repository's vendored PMTiles browser adapter.
 * This does not download an archive, infer building use, or rate suitability.
 * Usage: node scripts/building_source_probe.mjs [output-json]
 */
import {PMTiles} from '../docs/vendor/pmtiles.mjs';
import {writeFile} from 'node:fs/promises';

const CATALOG = 'https://stac.overturemaps.org/catalog.json';
const ORIGIN = process.env.ATLAS_PROBE_ORIGIN || 'http://localhost:8000';
const PUBLIC_S3 = 'https://overturemaps-extras-us-west-2.s3.us-west-2.amazonaws.com/tiles';
const responseHeaders = [];
const nativeFetch = globalThis.fetch;
globalThis.fetch = async (input, options = {}) => {
  const headers = new Headers(options.headers);
  headers.set('Origin', ORIGIN);
  const response = await nativeFetch(input, {...options, headers});
  responseHeaders.push({
    url: String(input), status: response.status, range: headers.get('Range'),
    cors: response.headers.get('access-control-allow-origin'),
    contentRange: response.headers.get('content-range'),
    acceptRanges: response.headers.get('accept-ranges'),
    expiration: response.headers.get('x-amz-expiration'),
  });
  return response;
};

// Minimal read-only protobuf inspection for MVT layer names and supplied values.
function readVarint(bytes, cursor) {
  let value = 0, factor = 1;
  while (cursor.index < bytes.length) {
    const byte = bytes[cursor.index++];
    value += (byte & 127) * factor;
    if (byte < 128) return value;
    factor *= 128;
  }
  throw new Error('Truncated protobuf varint');
}
function fields(bytes) {
  const cursor = {index: 0}, output = [];
  while (cursor.index < bytes.length) {
    const tag = readVarint(bytes, cursor), number = tag >> 3, wire = tag & 7;
    let value;
    if (wire === 0) value = readVarint(bytes, cursor);
    else if (wire === 1 || wire === 5) {
      const length = wire === 1 ? 8 : 4;
      value = bytes.subarray(cursor.index, cursor.index + length); cursor.index += length;
    } else if (wire === 2) {
      const length = readVarint(bytes, cursor);
      value = bytes.subarray(cursor.index, cursor.index + length); cursor.index += length;
    } else throw new Error(`Unsupported protobuf wire type ${wire}`);
    output.push({number, wire, value});
  }
  return output;
}
const decoder = new TextDecoder();
function scalar(bytes) {
  for (const {number, value} of fields(bytes)) {
    if (number === 1) return decoder.decode(value);
    if (number === 2) return new DataView(value.buffer, value.byteOffset, 4).getFloat32(0, true);
    if (number === 3) return new DataView(value.buffer, value.byteOffset, 8).getFloat64(0, true);
    if (number === 4 || number === 5) return value;
    if (number === 6) return value % 2 ? -(value + 1) / 2 : value / 2;
    if (number === 7) return Boolean(value);
  }
  return null;
}
function inspectMVT(buffer) {
  const output = [];
  for (const tileField of fields(new Uint8Array(buffer))) {
    if (tileField.number !== 3) continue;
    const parts = fields(tileField.value);
    const keys = parts.filter(f => f.number === 3).map(f => decoder.decode(f.value));
    const values = parts.filter(f => f.number === 4).map(f => scalar(f.value));
    const summary = {
      source_layer: decoder.decode(parts.find(f => f.number === 1).value),
      feature_count: 0, geometry_types: {}, fields: keys,
      subtypes: {}, classes: {}, geometry_sources: {},
    };
    for (const feature of parts.filter(f => f.number === 2)) {
      summary.feature_count++;
      const properties = {};
      for (const featureField of fields(feature.value)) {
        if (featureField.number === 3) {
          const type = featureField.value;
          summary.geometry_types[type] = (summary.geometry_types[type] || 0) + 1;
        }
        if (featureField.number === 2) {
          const cursor = {index: 0}, tags = [];
          while (cursor.index < featureField.value.length) tags.push(readVarint(featureField.value, cursor));
          for (let i = 0; i < tags.length; i += 2) properties[keys[tags[i]]] = values[tags[i + 1]];
        }
      }
      for (const [property, bucket] of [['subtype','subtypes'],['class','classes'],['@geometry_source','geometry_sources']]) {
        const value = properties[property] ?? 'unknown';
        summary[bucket][value] = (summary[bucket][value] || 0) + 1;
      }
    }
    output.push(summary);
  }
  return output;
}
function tileXY(lon, lat, z) {
  const n = 2 ** z;
  return {
    z, x: Math.floor((lon + 180) / 360 * n),
    y: Math.floor((1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * n),
  };
}

const catalogResponse = await fetch(CATALOG, {signal: AbortSignal.timeout(25000)});
if (!catalogResponse.ok) throw new Error(`STAC HTTP ${catalogResponse.status}`);
const catalog = await catalogResponse.json();
const release = catalog.latest;
if (!/^\d{4}-\d{2}-\d{2}\.\d+$/.test(release)) throw new Error('Invalid release identifier');
const result = {checked_at: new Date().toISOString(), release, themes: {}, examples: [], responses: responseHeaders};
const archives = new Map();
await Promise.all(['buildings', 'base', 'transportation'].map(async theme => {
  const url = `${PUBLIC_S3}/${release}/${theme}.pmtiles`;
  const archive = new PMTiles(url); archives.set(theme, archive);
  const [header, metadata] = await Promise.all([archive.getHeader(), archive.getMetadata()]);
  result.themes[theme] = {url, header, metadata};
}));

const examples = [
  {label: 'Denver, Colorado', lon: -104.99, lat: 39.74, zoom: 16},
  {label: 'Fort Collins, Colorado', lon: -105.078, lat: 40.58, zoom: 16},
  {label: 'Iowa City, Iowa', lon: -91.53, lat: 41.66, zoom: 16},
];
await Promise.all(examples.map(async example => {
  const tile = tileXY(example.lon, example.lat, 14);
  const payload = await archives.get('buildings').getZxy(tile.z, tile.x, tile.y, AbortSignal.timeout(25000));
  if (!payload) throw new Error(`No example tile: ${example.label}`);
  result.examples.push({...example, tile, decoded_bytes: payload.data.byteLength, layers: inspectMVT(payload.data)});
}));
// One context tile verifies actual roads and water layer usability, not just metadata.
for (const theme of ['base', 'transportation']) {
  const context = tileXY(-104.99, 39.74, Math.min(14, result.themes[theme].header.maxZoom));
  const payload = await archives.get(theme).getZxy(context.z, context.x, context.y, AbortSignal.timeout(25000));
  result.themes[theme].sample = payload ? {tile: context, decoded_bytes: payload.data.byteLength, layers: inspectMVT(payload.data)} : null;
}
if (process.argv[2]) await writeFile(process.argv[2], JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify({release, themes: Object.fromEntries(Object.entries(result.themes).map(([key,value]) => [key, value.metadata.vector_layers.map(layer => ({id:layer.id,minzoom:layer.minzoom,maxzoom:layer.maxzoom,fields:layer.fields}))])), examples: result.examples, responses: responseHeaders}, null, 2));
