// Data from the Hugging Face dataset (data/app/, ADR 0022). The Hub serves files uncompressed, so we
// fetch the gzipped twin and inflate it in the browser, falling back to the plain JSON.

const DEFAULT_BASE = 'https://huggingface.co/datasets/Sbaiiiiii/looked-up/resolve/main/data/app/';
// ?data=<relative path> serves a local copy (tests, previews); other origins are refused.
const override = new URLSearchParams(location.search).get('data');
export const BASE = override && /^[\w./-]+\/$/.test(override) && !override.includes('..') ? override : DEFAULT_BASE;
const memory = new Map();
const CACHE = 'lookedup-days-v1';

async function inflate(res) {
    const stream = res.body.pipeThrough(new DecompressionStream('gzip'));
    return JSON.parse(await new Response(stream).text());
}

async function fetchJSON(name, { immutable = false } = {}) {
    const url = BASE + name;
    let cache = null;
    if (immutable && 'caches' in window) {
        try {
            cache = await caches.open(CACHE);
            const hit = await cache.match(url);
            if (hit) return hit.json();
        } catch { cache = null; }
    }
    let data;
    if ('DecompressionStream' in window) {
        const res = await fetch(`${url}.gz`);
        if (!res.ok) throw new Error(`${res.status} ${name}.gz`);
        data = await inflate(res);
    } else {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`${res.status} ${name}`);
        data = await res.json();
    }
    if (cache) {
        try { await cache.put(url, new Response(JSON.stringify(data), { headers: { 'content-type': 'application/json' } })); } catch { /* quota */ }
    }
    return data;
}

/** Past days (two or more days old) never change, so they are kept in the Cache API. */
export function get(name, opts) {
    if (!memory.has(name)) {
        const p = fetchJSON(name, opts).catch((e) => { memory.delete(name); throw e; });
        memory.set(name, p);
    }
    return memory.get(name);
}

export const today = () => get('today.json');
export const stats = () => get('stats.json');
export function dayFile(iso) {
    const old = (Date.now() - Date.parse(`${iso}T00:00:00Z`)) / 86400000 > 2.2;
    return get(`days/${iso}.json`, { immutable: old });
}
