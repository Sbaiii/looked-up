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
