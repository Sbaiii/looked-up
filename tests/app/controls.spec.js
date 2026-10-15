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

test('choosing a language updates the panel and the URL', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await page.selectOption('#lang-select', 'ja');
  await expect(page).toHaveURL(/#\/lang\/ja$/);
  await expect(page.locator('#lang-select')).toHaveValue('ja');
  expect(page.errors).toEqual([]);
});

test('the theme toggle switches and is remembered', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  const theme = () => page.evaluate(() => document.documentElement.getAttribute('data-theme'));
  const before = await theme();
  await page.click('#theme');
  const after = await theme();
  expect(after).not.toBe(before);
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', after === 'light' ? '#ffffff' : '#08090b');
  await page.reload();
  await ready(page);
  expect(await theme()).toBe(after);
});

test('a language panel link titles the page', async ({ page }) => {
  await page.goto('./#/lang/ja');
  await ready(page);
  await expect(page).toHaveTitle(/^What .+ readers looked up · Looked Up$/);
  await expect(page.locator('#lang-select')).toHaveValue('ja');
});
