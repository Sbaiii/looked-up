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
