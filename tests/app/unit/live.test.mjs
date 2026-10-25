// The live strip's feed URL (app/js/live.js), run with `npm run test:unit`.
import { test } from 'node:test';
import assert from 'node:assert/strict';

let n = 0;
async function liveUrl(search) {
  globalThis.location = { search };
  return (await import(`../../../app/js/live.js?copy=${++n}`)).LIVE_URL;
}
const WORKER = 'https://looked-up-live.abdellahsbaisbai.workers.dev/live.json';

test('without ?live= the strip reads the deployed Worker', async () => {
  assert.equal(await liveUrl(''), WORKER);
});

test('?live= may name another workers.dev or hf.space feed', async () => {
  const w = 'https://staging.example.workers.dev/live.json';
  const s = 'https://someone-looked-up.hf.space/live.json';
  assert.equal(await liveUrl(`?live=${encodeURIComponent(w)}`), w);
  assert.equal(await liveUrl(`?live=${encodeURIComponent(s)}`), s);
});

test('anything else falls back to the Worker', async () => {
  for (const bad of ['https://evil.example/live.json', 'http://x.workers.dev/live.json', 'https://x.workers.dev/other.json',
    'https://x.workers.dev.evil.example/live.json', 'javascript:alert(1)']) {
    assert.equal(await liveUrl(`?live=${encodeURIComponent(bad)}`), WORKER, bad);
  }
});
