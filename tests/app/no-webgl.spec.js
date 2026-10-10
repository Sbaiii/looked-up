// Low-end / no-WebGL fallback: the flat SVG map, never the globe.
const { test, expect } = require('./fixtures');

test.use({ launchOptions: { args: ['--disable-webgl', '--disable-webgl2', '--disable-3d-apis'] } });

test('the flat SVG map is used and the globe is not offered', async ({ page }) => {
  await page.goto('./');
  await page.waitForSelector('html[data-ready="true"]');
  await expect(page.locator('#viz svg path.country').first()).toBeAttached();
  await expect(page.locator('#viz-mode')).toBeHidden();
  await page.mouse.click(10, 300);                       // an interaction must not try to load the globe
  await page.waitForTimeout(1000);
  await expect(page.locator('#viz canvas')).toHaveCount(0);
  expect(page.errors).toEqual([]);
});

test('replay restarts the spread on the flat map', async ({ page }) => {
  await page.goto('./');
  await page.waitForSelector('html[data-ready="true"]');
  await page.waitForFunction(() => document.querySelectorAll('#viz .arc').length > 0, null, { timeout: 10000 });
  await page.click('#replay');
  const right = await page.evaluate(() => document.querySelectorAll('#viz .arc').length);
  expect(right).toBe(0);                                   // cleared at once
  await page.waitForFunction(() => document.querySelectorAll('#viz .arc').length > 0, null, { timeout: 10000 });
});
