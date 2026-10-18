// The panels around the day view: About, briefing, language lists, legend and the update line, from fixtures.
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');

test('About lists its lines and limits and links the dataset and repository', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  expect(await page.locator('#about-lines li').count()).toBeGreaterThan(1);
  expect(await page.locator('#about-limits li').count()).toBeGreaterThan(1);
  await expect(page.locator('#about-links a[href="https://huggingface.co/datasets/Sbaiiiiii/looked-up"]')).toHaveCount(1);
  await expect(page.locator('#about-links a[href="https://github.com/Sbaiii/looked-up"]')).toHaveCount(1);
  await page.click('[data-ui-lang="fr"]');
  await expect(page.locator('#about-links a')).toHaveCount(2);
  expect(page.errors).toEqual([]);
});

test('the briefing panel follows the shown day', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await expect(page.locator('#brief-date')).toHaveText('17 August');
  await expect(page.locator('#brief-text')).toContainText('the world looked up');
  expect(await page.locator('#brief-facts li').count()).toBeGreaterThan(0);
  await expect(page.locator('#day-brief')).toHaveText(await page.locator('#brief-text').textContent());
});

test('the legend shows the four ticks of the absolute scale', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#legend-ticks span')).toHaveText(['8', '50', '500', '5k+']);
});

test('the update line names the data time in UTC and in local time', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#updated')).toHaveText(/^Updated .+ UTC · .+ your time$/);
});

test('selecting a card updates the caption under the map', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  const first = page.locator('#cards .card').first();
  const name = (await first.locator('.card__title').textContent()).trim();
  await first.locator('.card__title button').click();
  await expect(page.locator('#viz-now')).toContainText(name);
  await expect(page.locator('#viz-now')).toContainText(/\d+ languages · led by /);
});

test('the language panel lists up to five events for the chosen language', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await page.selectOption('#lang-select', 'en');
  const items = page.locator('#lang-top li:not(.empty)');
  const n = await items.count();
  expect(n).toBeGreaterThan(0);
  expect(n).toBeLessThanOrEqual(5);
  const plus = await items.locator('small').allTextContents();
  expect(plus.every((s) => /\+/.test(s))).toBe(true);
});

test('a language without events on the day shows the empty line', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  const langs = await page.locator('#lang-select option').evaluateAll((os) => os.map((o) => o.value));
  for (const code of langs) {
    await page.selectOption('#lang-select', code);
    if (await page.locator('#lang-only li.empty').count()) {
      await expect(page.locator('#lang-only li.empty')).toHaveText('Nothing for this language on this day.');
      return;
    }
  }
  throw new Error('every language had single-language events in the fixture');
});

test('a data outage shows the error line instead of a blank hero', async ({ page }) => {
  await page.route('https://huggingface.co/datasets/Sbaiiiiii/looked-up/resolve/main/data/app/today.json*',
    (route) => route.fulfill({ status: 503, body: 'down' }));
  await page.goto('./');
  await expect(page.locator('#hero-label')).toHaveText('The data could not be loaded. Please try again later.');
  await expect(page.locator('#hero-label')).not.toHaveClass(/skeleton/);
});
