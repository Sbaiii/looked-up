// The "Go to a date" field, from fixtures (window: 16 and 17 Aug plus today; 19 and 27 Jul exist as archive days).
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');

test('a date in the window opens that day on the slider', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.fill('#day-pick', '2026-08-16');
  await page.locator('#day-pick').dispatchEvent('change');
  await expect(page).toHaveURL(/#\/day\/2026-08-16$/);
  await expect(page.locator('#bars rect.is-on')).toHaveCount(1);
  expect(page.errors).toEqual([]);
});

test('an older date opens as an archive day', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.fill('#day-pick', '2026-07-27');
  await page.locator('#day-pick').dispatchEvent('change');
  await expect(page).toHaveURL(/#\/day\/2026-07-27$/);
  await expect(page.locator('#day-archive')).toBeVisible();
});
