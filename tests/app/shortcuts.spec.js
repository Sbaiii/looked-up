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

test('arrows in a field or with a modifier key leave the day alone', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  const before = await page.locator('#day-out').textContent();
  await page.locator('#lang-select').focus();
  await page.keyboard.press('ArrowLeft');                     // moves the picker's option, not the day
  await page.locator('body').press('Alt+ArrowLeft');
  await page.locator('body').press('Control+ArrowRight');
  await expect(page.locator('#day-out')).toHaveText(before);
});
