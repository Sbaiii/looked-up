const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');

test('page loads without errors', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await expect(page.locator('h1')).toHaveText('Today the world looked up');
  await expect(page).toHaveTitle(/Looked Up/);
  expect(page.errors).toEqual([]);
});

test('today.json renders the hero, cards, languages and briefing', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#hero-label')).toHaveText('Zodiac');
  await expect(page.locator('#hero-counter')).toContainText('languages');
  await expect(page.locator('.card')).toHaveCount(6);
  await expect(page.locator('#brief-text')).toContainText('the world looked up');
  await expect(page.locator('#lang-select option')).toHaveCount(30);
});

test('a past day loads from its day file', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.locator('#day-slider').fill('1');
  await page.locator('#day-slider').dispatchEvent('input');
  await expect(page.locator('#brief-text')).toContainText('On 17 August the world looked up Hayden Panettiere: 28 languages');
  await expect(page.locator('.card').first()).toContainText('Hayden Panettiere');
});

test('language switch translates the page', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.click('[data-ui-lang="fr"]');
  await expect(page.locator('h1')).toHaveText("Aujourd'hui, le monde s'est intéressé à");
  await expect(page.locator('html')).toHaveAttribute('lang', 'fr');
  await page.click('[data-ui-lang="es"]');
  await expect(page.locator('h1')).toHaveText('Hoy el mundo se fijó en');
  await expect(page.locator('#brief-text')).toContainText('el mundo se fijó en');
  await page.reload();
  await ready(page);
  await expect(page.locator('h1')).toHaveText('Hoy el mundo se fijó en');   // remembered locally
});

test('keyboard reaches the controls with a visible focus', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.keyboard.press('Tab');
  await expect(page.locator('.skip')).toBeFocused();
  await page.focus('#day-slider');
  await page.keyboard.press('ArrowLeft');
  await expect(page.locator('#day-out')).not.toHaveText('Today');
});
