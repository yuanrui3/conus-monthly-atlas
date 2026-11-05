// A hosting service may already have decoded a gzip file via Content-Encoding.
// Inspect the returned bytes, so both ordinary static hosts and such CDNs work.
export async function readAtlasJSON(path, options = {}) {
  const r = await fetch(path, options);
  if (!r.ok) throw new Error(`Data request failed (HTTP ${r.status})`);
  if (!/\.gz(?:[?#]|$)/i.test(String(path))) return r.json();
  const bytes = new Uint8Array(await r.arrayBuffer());
  if (bytes[0] === 0x1f && bytes[1] === 0x8b) {
    if (typeof DecompressionStream !== 'function') throw new Error('This browser cannot decode the compressed monthly data.');
    const decoded = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
    return new Response(decoded).json();
  }
  return JSON.parse(new TextDecoder().decode(bytes));
}
