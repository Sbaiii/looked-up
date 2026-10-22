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

test('chip labels are translated', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.click('[data-ui-lang="fr"]');
  await expect(page.locator('#cat-filters button').first()).toHaveText(`Toutes les catégories · ${today.events.length}`);
  if (counts.human) await expect(page.locator('#cat-filters [data-category="human"]')).toHaveText(`Personne · ${counts.human}`);
});

test('a category chip filters the cards', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  const [cat, n] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  await page.click(`#cat-filters [data-category="${cat}"]`);
  await expect(page.locator(`#cat-filters [data-category="${cat}"]`)).toHaveAttribute('aria-checked', 'true');
  await expect(page.locator('#cards .card')).toHaveCount(Math.min(n, 12));
  const shown = await page.locator('#cards .card').evaluateAll((cs) => cs.map((c) => c.dataset.qid));
  const byQid = Object.fromEntries(today.events.map((e) => [e.qid, e.category]));
  expect(shown.every((q) => byQid[q] === cat)).toBe(true);
  await page.click('#cat-filters [data-category=""]');
  await expect(page.locator('#cards .card')).toHaveCount(Math.min(today.events.length, 12));
});

test('a category the new day does not have resets to all', async ({ page }) => {
  await page.goto('./#/day/2026-08-16');
  await ready(page);
  await page.click('#cat-filters [data-category="human"]');
  await expect(page.locator('#cards .card')).toHaveCount(2);
  await page.click('#next-day');                                  // 17 Aug has no "human" event
  await expect(page.locator('#cat-filters [data-category=""]')).toHaveAttribute('aria-checked', 'true');
  await expect(page.locator('#cards .card')).toHaveCount(12);
});
