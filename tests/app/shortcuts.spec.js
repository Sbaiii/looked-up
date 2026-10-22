// Keyboard shortcuts on the day view, from fixtures.
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');

test('the left and right arrows step through days', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await page.locator('body').press('ArrowLeft');
  await expect(page).toHaveURL(/#\/day\/2026-08-16$/);
  await page.locator('body').press('ArrowRight');
  await expect(page).toHaveURL(/#\/day\/2026-08-17$/);
  expect(page.errors).toEqual([]);
});
