// Live check (network): a browser page on another origin can read the app data from the Hugging Face Hub.
const { test, expect } = require('@playwright/test');

test.skip(!!process.env.OFFLINE, 'offline');

test('the Hub serves data/app with CORS to a browser', async ({ page }) => {
  await page.goto('./');
  const res = await page.evaluate(async () => {
    const base = 'https://huggingface.co/datasets/Sbaiiiiii/looked-up/resolve/main/data/app/';
    const r = await fetch(`${base}stats.json.gz`);
    const json = JSON.parse(await new Response(r.body.pipeThrough(new DecompressionStream('gzip'))).text());
    const plain = await (await fetch(`${base}today.json`)).json();
    return { ok: r.ok, schema: json.schema_version, kind: json.kind, today: plain.kind };
  });
  expect(res).toEqual({ ok: true, schema: 1, kind: 'stats', today: 'today' });
});
