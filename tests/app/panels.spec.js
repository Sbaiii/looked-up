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
