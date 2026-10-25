// The Hub data client (app/js/data.js) with fetch stubbed, run with `npm run test:unit`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { gzipSync } from 'node:zlib';

let n = 0;
/** A fresh copy of data.js for a page at ``search``, with ``win`` as window. */
async function load(search = '', win = globalThis) {
  globalThis.location = { search };
  globalThis.window = win;
  return import(`../../../app/js/data.js?copy=${++n}`);
}

const gz = (obj) => new Response(gzipSync(JSON.stringify(obj)));
const HUB = 'https://huggingface.co/datasets/Sbaiiiiii/looked-up/resolve/main/data/app/';

test('today.json is fetched as its .gz twin and inflated', async (t) => {
  const urls = [];
  t.mock.method(globalThis, 'fetch', async (url) => { urls.push(url); return gz({ date: '2026-08-17' }); });
  const data = await load();
  assert.deepEqual(await data.today(), { date: '2026-08-17' });
  assert.deepEqual(urls, [`${HUB}today.json.gz`]);
});

test('get memoises successes and forgets failures', async (t) => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => (++calls === 1 ? new Response('down', { status: 503 }) : gz({ ok: calls })));
  const data = await load();
  await assert.rejects(data.stats(), /503 stats.json.gz/);
  assert.deepEqual(await data.stats(), { ok: 2 });
  assert.deepEqual(await data.stats(), { ok: 2 });
  assert.equal(calls, 2);
});

test('the ?data= override accepts a relative folder and refuses anything else', async () => {
  assert.equal((await load('?data=fixtures/app/')).BASE, 'fixtures/app/');
  assert.equal((await load('?data=../secrets/')).BASE, HUB);
  assert.equal((await load('?data=https://evil.example/')).BASE, HUB);
  assert.equal((await load('?data=fixtures/app')).BASE, HUB);                 // must end with a slash
  assert.equal((await load('')).BASE, HUB);
});

test('without DecompressionStream the plain JSON is fetched', async (t) => {
  const urls = [];
  t.mock.method(globalThis, 'fetch', async (url) => { urls.push(url); return Response.json({ plain: true }); });
  const data = await load('', {});
  assert.deepEqual(await data.get('stats.json'), { plain: true });
  assert.deepEqual(urls, [`${HUB}stats.json`]);
  t.mock.method(globalThis, 'fetch', async () => new Response('', { status: 404 }));
  await assert.rejects(data.get('days/2026-01-01.json'), /404 days\/2026-01-01.json$/);
});

/** A window with DecompressionStream and an in-memory Cache API. */
function withCaches() {
  const store = new Map();
  const opened = [];
  const cache = {
    match: async (url) => (store.has(url) ? new Response(store.get(url)) : undefined),
    put: async (url, res) => { store.set(url, await res.text()); },
  };
  return { win: { DecompressionStream, caches: { open: async (name) => { opened.push(name); return cache; } } }, store, opened };
}

test('an old day is cached, then served from the cache by a later page', async (t) => {
  const { win, store, opened } = withCaches();
  globalThis.caches = win.caches;
  t.after(() => { delete globalThis.caches; });
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; return gz({ date: '2026-07-19' }); });
  assert.deepEqual(await (await load('', win)).dayFile('2026-07-19'), { date: '2026-07-19' });
  assert.ok(store.has(`${HUB}days/2026-07-19.json`) && opened.includes('lookedup-days-v1'));
  assert.deepEqual(await (await load('', win)).dayFile('2026-07-19'), { date: '2026-07-19' });   // a new page, same cache
  assert.equal(calls, 1);
});

test('a day from yesterday is fetched but never cached', async (t) => {
  const { win, store } = withCaches();
  globalThis.caches = win.caches;
  t.after(() => { delete globalThis.caches; });
  t.mock.method(globalThis, 'fetch', async () => gz({ fresh: true }));
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  assert.deepEqual(await (await load('', win)).dayFile(yesterday), { fresh: true });
  assert.equal(store.size, 0);
});

test('today and stats fetch their own files', async (t) => {
  const urls = [];
  t.mock.method(globalThis, 'fetch', async (url) => { urls.push(url); return gz({ ok: 1 }); });
  const data = await load();
  await data.today();
  await data.stats();
  assert.deepEqual(urls, [`${HUB}today.json.gz`, `${HUB}stats.json.gz`]);
});

test('two simultaneous requests for one file share a single fetch', async (t) => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; return gz({ n: calls }); });
  const data = await load();
  const [a, b] = await Promise.all([data.get('stats.json'), data.get('stats.json')]);
  assert.deepEqual(a, b);
  assert.equal(calls, 1);
});
