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

test('the hero label links the interface-language article when there is one', async ({ page }) => {
  await serveToday(page, (d) => { for (const e of d.events) e.excess = e.qid === 'Q804' ? 9e6 : 1000; });
  await page.goto('./');
  await ready(page);
  const link = page.locator('#hero-label a');
  await expect(link).toHaveAttribute('href', /^https:\/\/en\.wikipedia\.org\//);
  await page.click('[data-ui-lang="fr"]');
  await expect(link).toHaveAttribute('href', /^https:\/\/fr\.wikipedia\.org\//);
});

test('hero counter and subtitle', async ({ page }) => {
  await serveToday(page, (d) => { for (const e of d.events) e.excess = e.qid === 'Q804' ? 9e6 : 1000; });
  await page.goto('./');
  await ready(page);
  const ev = JSON.parse(fs.readFileSync(TODAY, 'utf8')).events.find((e) => e.qid === 'Q804');
  await expect(page.locator('#hero-counter')).toHaveText(new RegExp(`^${ev.breadth} languages in `));
  await expect(page.locator('#hero-sub')).toContainText('International');
  await expect(page.locator('#hero-sub')).toContainText('led by');
  await expect(page.locator('#hero-sub')).toContainText('9 million more views');
});

test('no open forecast, no "Most likely to spread next"', async ({ page }) => {
  await serveToday(page, (d) => { for (const e of d.events) delete e.forecast; });
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#next')).toBeHidden();
  await expect(page.locator('.card__forecast')).toHaveCount(0);
  await expect(page.locator('#forecast-note')).toBeHidden();
});

test('"Most likely to spread next" ranks open events by chance, three at most', async ({ page }) => {
  await serveToday(page, (d) => {
    const start = new Date(Date.parse(d.generated_at) - 3600e3).toISOString().slice(0, 13) + ':00Z';
    d.events.slice(0, 5).forEach((e, i) => { e.start = start; e.forecast = { p_international: [0.1, 0.9, 0.4, 0.7, 0.2][i] }; });
    for (const e of d.events.slice(5)) delete e.forecast;
  });
  await page.goto('./');
  await ready(page);
  const items = page.locator('#next-list li');
  await expect(items).toHaveCount(3);
  await expect(items.nth(0)).toContainText('90% chance');
  await expect(items.nth(1)).toContainText('70% chance');
  await expect(items.nth(2)).toContainText('40% chance');
});

test('cards without a description or a forecast never print "null"', async ({ page }) => {
  await serveToday(page, (d) => { d.events[0].desc = {}; delete d.events[0].forecast; });
  await page.goto('./');
  await ready(page);
  for (const text of await page.locator('#cards .card').allTextContents()) expect(text).not.toContain('null');
  const nodes = await page.locator('#cards .card').evaluateAll((cards) => cards.flatMap((c) => [...c.childNodes])
    .filter((n) => n.nodeType === Node.TEXT_NODE && n.textContent.trim()).map((n) => n.textContent));
  expect(nodes).toEqual([]);
});

test('where the browser can share, a Share button sends the event title and link', async ({ page }) => {
  await page.addInitScript(() => { window.__shared = []; navigator.share = async (d) => { window.__shared.push(d); }; });
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await page.locator('#cards .card[data-qid="Q171571"] .card__links button', { hasText: 'Share' }).click();
  const [d] = await page.evaluate(() => window.__shared);
  expect(d.title).toBe('Hayden Panettiere');
  expect(d.url).toMatch(/#\/day\/2026-08-17\/event\/Q171571$/);
});

test('without a share sheet, cards have no Share button', async ({ page }) => {
  await page.addInitScript(() => { delete Navigator.prototype.share; });
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#cards .card__links button', { hasText: 'Share' })).toHaveCount(0);
});
