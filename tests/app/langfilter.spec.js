// The language filter: from the language panel to the day's cards, from fixtures.
const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');
const day = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'days', '2026-08-17.json'), 'utf8'));
const inLang = (l) => day.events.filter((e) => e.langs.some((r) => r.lang === l));

test('filtering by Japanese keeps only events with a Japanese spike', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await page.selectOption('#lang-select', 'ja');
  await page.click('#lang-filter');
  const want = inLang('ja').map((e) => e.qid).slice(0, 12);
  expect(await page.locator('#cards .card').evaluateAll((cs) => cs.map((c) => c.dataset.qid))).toEqual(want);
  expect(page.errors).toEqual([]);
});
