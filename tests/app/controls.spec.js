// The day controls: tier filters, paging, the language panel and the theme, from fixtures.
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');

test('the tier filter narrows the cards to the chosen tier and up', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  const cards = page.locator('#cards .card');
  const all = await cards.count();
  await page.click('[data-tier="planetary"]');
  await expect(page.locator('[data-tier="planetary"]')).toHaveAttribute('aria-checked', 'true');
  await expect(page.locator('[data-tier="noticed"]')).toHaveAttribute('aria-checked', 'false');
  await expect(cards).toHaveCount(2);
  expect(all).toBeGreaterThan(2);
  await expect(page.locator('#cards .badge--planetary')).toHaveCount(2);
  expect(page.errors).toEqual([]);
});

test('cards come 12 at a time; Show more reveals the rest', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await expect(page.locator('#cards .card')).toHaveCount(12);
  await expect(page.locator('#more')).toBeVisible();
  await page.click('#more');
  await expect(page.locator('#cards .card')).toHaveCount(15);
  await expect(page.locator('#more')).toBeHidden();
});
