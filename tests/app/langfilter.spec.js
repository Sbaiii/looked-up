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

test('the chip shows the language, and ✕ removes the filter', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await page.selectOption('#lang-select', 'ja');
  await page.click('#lang-filter');
  await expect(page.locator('#lang-chip')).toBeVisible();
  await expect(page.locator('#lang-chip-text')).toHaveText('Spiking in Japanese');
  await page.click('#lang-chip-clear');
  await expect(page.locator('#lang-chip')).toBeHidden();
  await expect(page.locator('#cards .card')).toHaveCount(12);
});

test('chip text and clear label follow the interface language', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await page.selectOption('#lang-select', 'ja');
  await page.click('#lang-filter');
  await page.click('[data-ui-lang="fr"]');
  await expect(page.locator('#lang-chip-text')).toHaveText('En pic en japonais');
  await expect(page.locator('#lang-chip-clear')).toHaveAttribute('aria-label', 'Retirer le filtre de langue');
});

test('language and tier filters together, kept on the next day', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await page.selectOption('#lang-select', 'en');
  await page.click('#lang-filter');
  await page.click('[data-tier="international"]');
  const want = inLang('en').filter((e) => e.tier !== 'noticed').length;
  await expect(page.locator('#cards .card')).toHaveCount(Math.min(want, 12));
  await page.locator('body').press('ArrowLeft');
  await expect(page.locator('#lang-chip-text')).toHaveText('Spiking in English');
});

test('Clear filters also removes the language filter', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await page.selectOption('#lang-select', 'ja');
  await page.click('#lang-filter');
  await page.locator('#clear-filters').click();
  await expect(page.locator('#lang-chip')).toBeHidden();
  await expect(page.locator('#cards .card')).toHaveCount(12);
});
