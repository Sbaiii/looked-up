// The order picker above the event cards, from fixtures.
const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');
const today = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'today.json'), 'utf8'));
const qids = (page) => page.locator('#cards .card').evaluateAll((cs) => cs.map((c) => c.dataset.qid));
const first12 = (sorted) => sorted.slice(0, 12).map((e) => e.qid);

test('most extra views first', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.selectOption('#card-sort', 'views');
  expect(await qids(page)).toEqual(first12([...today.events].sort((a, b) => b.excess - a.excess)));
  expect(page.errors).toEqual([]);
});

test('widest first is the file order and the default', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#card-sort')).toHaveValue('widest');
  expect(await qids(page)).toEqual(first12(today.events));
  await page.selectOption('#card-sort', 'views');
  await page.selectOption('#card-sort', 'widest');
  expect(await qids(page)).toEqual(first12(today.events));
});

test('latest and earliest first follow the start hour', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.selectOption('#card-sort', 'latest');
  const starts = () => page.locator('#cards .card').evaluateAll((cs) => cs.map((c) => c.dataset.qid));
  const byStart = Object.fromEntries(today.events.map((e) => [e.qid, Date.parse(e.start)]));
  let got = (await starts()).map((q) => byStart[q]);
  expect(got).toEqual([...got].sort((a, b) => b - a));
  await page.selectOption('#card-sort', 'earliest');
  got = (await starts()).map((q) => byStart[q]);
  expect(got).toEqual([...got].sort((a, b) => a - b));
});
