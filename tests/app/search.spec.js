// The search field above the event cards, from fixtures.
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');

test('typing narrows the cards to matching events', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.fill('#card-search', 'pillay');
  await expect(page.locator('#cards .card')).toHaveCount(1);
  await expect(page.locator('#cards .card')).toHaveAttribute('data-qid', 'Q242078');
  await page.fill('#card-search', '');
  expect(await page.locator('#cards .card').count()).toBeGreaterThan(1);
  expect(page.errors).toEqual([]);
});
