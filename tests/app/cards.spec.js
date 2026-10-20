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
