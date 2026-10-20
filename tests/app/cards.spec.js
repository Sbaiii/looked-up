// The event cards: sparkline, tier badge, Wikipedia links and the URL guard, from fixtures.
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');
const TODAY = path.join(__dirname, 'fixtures', 'today.json');

/** Serve today.json (and its .gz twin) after ``edit`` has changed the parsed fixture. */
async function serveToday(page, edit) {
  const today = JSON.parse(fs.readFileSync(TODAY, 'utf8'));
  edit(today);
  const body = JSON.stringify(today);
  await page.route('https://huggingface.co/datasets/Sbaiiiiii/looked-up/resolve/main/data/app/today.json*', (route) => {
    const gz = route.request().url().endsWith('.gz');
    return route.fulfill({ status: 200, headers: { 'access-control-allow-origin': '*' },
      contentType: gz ? 'application/gzip' : 'application/json', body: gz ? zlib.gzipSync(body) : body });
  });
}

test('each card has a sparkline labelled for screen readers', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  const spark = page.locator('#cards .card').first().locator('svg.spark');
  await expect(spark).toHaveAttribute('role', 'img');
  await expect(spark).toHaveAttribute('aria-label', /Views across all languages/);
  expect(await spark.locator('polyline').count()).toBeGreaterThan(0);
});

test('the tier badge title explains the tier', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  const badge = page.locator('#cards .card').first().locator('.badge--planetary');
  await expect(badge).toHaveAttribute('title', 'Spiking in 20 languages or more');
});

test('Wikipedia links: the lead language, then the interface language when it differs', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  const pillay = page.locator('#cards .card[data-qid="Q242078"] .card__links a');
  await expect(pillay).toHaveCount(1);
  await expect(pillay).toHaveAttribute('hreflang', 'en');
  const pt = page.locator('#cards .card[data-qid="Q804"] .card__links a');
  await expect(pt).toHaveCount(2);
  await expect(pt.nth(0)).toHaveAttribute('hreflang', 'pt');
  await expect(pt.nth(1)).toHaveAttribute('hreflang', 'en');
  await page.click('[data-ui-lang="fr"]');
  await expect(page.locator('#cards .card[data-qid="Q242078"] .card__links a')).toHaveCount(2);
  await expect(page.locator('#cards .card[data-qid="Q242078"] .card__links a').nth(1)).toHaveAttribute('hreflang', 'fr');
});

test('URLs that are not https are replaced by #', async ({ page }) => {
  await serveToday(page, (d) => { d.events[0].urls.en = 'javascript:alert(1)'; });
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#cards .card[data-qid="Q242078"] .card__links a').first()).toHaveAttribute('href', '#');
  expect(page.errors).toEqual([]);
});

test('unknown hours split the sparkline, and a card with no known hour draws no line', async ({ page }) => {
  await serveToday(page, (d) => {
    d.events[0].spark = [1, 2, 3, null, null, 4, 5, ...Array(41).fill(null)];
    d.events[1].spark = Array(48).fill(null);
  });
  await page.goto('./');
  await ready(page);
  await expect(page.locator(`#cards .card[data-qid="Q242078"] svg.spark polyline`)).toHaveCount(2);
  await expect(page.locator(`#cards .card[data-qid="Q804"] svg.spark polyline`)).toHaveCount(0);
});

test('no description, no description line', async ({ page }) => {
  await serveToday(page, (d) => { d.events[0].desc = {}; });
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#cards .card[data-qid="Q242078"] .card__desc')).toHaveCount(0);
});
