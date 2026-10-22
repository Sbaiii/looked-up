// The category chips above the event cards, from fixtures.
const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');
const today = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'today.json'), 'utf8'));
const counts = today.events.reduce((c, e) => ({ ...c, [e.category]: (c[e.category] || 0) + 1 }), {});

test('one chip per category of the day, with its count, after "All categories"', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  const chips = page.locator('#cat-filters button');
  await expect(chips.first()).toHaveText(`All categories · ${today.events.length}`);
  await expect(chips.first()).toHaveAttribute('aria-checked', 'true');
  await expect(chips).toHaveCount(1 + Object.keys(counts).length);
  const shown = await chips.evaluateAll((bs) => bs.slice(1).map((b) => Number(b.textContent.split(' · ')[1])));
  expect(shown).toEqual([...shown].sort((a, b) => b - a));
  expect(page.errors).toEqual([]);
});
