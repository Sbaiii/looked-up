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
