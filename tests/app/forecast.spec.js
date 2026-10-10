// Phase 4: forecast badges on open events and the FIG. 05 section, from fixtures.
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');

test('open events show Spreading, planetary chance and fade ETA only above the thresholds', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  const avatar = page.locator('.card', { hasText: 'Avatar: Seven Havens' });
  await expect(avatar.locator('.badge--spreading')).toHaveText('Spreading');
  await expect(avatar.locator('.card__forecast')).toContainText('72% chance of going international');
  await expect(avatar.locator('.card__forecast')).toContainText('likely to fade by ~14:00 UTC');
  await expect(avatar.locator('.badge--spreading')).toHaveAttribute('title', 'Forecast from a model trained on past events; backtested AUC 0.88.');
  const animals = page.locator('.card', { hasText: 'Animals' });
  await expect(animals.locator('.card__forecast')).toHaveText('35% chance of going planetary');
  await expect(animals.locator('.badge--spreading')).toHaveCount(0);
  await expect(page.locator('.card', { hasText: 'Kneecap' }).locator('.card__forecast')).toHaveCount(0);   // 20 %: nothing
  await expect(page.locator('.badge--spreading')).toHaveCount(1);
  await expect(page.locator('#forecast-note')).toHaveText('Forecast from a model trained on past events; backtested AUC 0.88.');
});

test('old days never show stale forecasts', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await expect(page.locator('.card').first()).toContainText('Hayden Panettiere');
  await expect(page.locator('.card__forecast')).toHaveCount(0);
  await expect(page.locator('#forecast-note')).toBeHidden();
});

test('FIG. 05 shows three backtest numbers, the calibration chart and the summary in each language', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#forecast')).toBeVisible();
  await expect(page.locator('#forecast-stats dt')).toHaveText(['0.88', '5.9×', '26%']);
  expect(await page.locator('#forecast-chart circle').count()).toBeGreaterThan(3);
  await expect(page.locator('#forecast-summary')).toContainText('AUC 0.88');
  await page.click('[data-ui-lang="fr"]');
  await expect(page.locator('#forecast-title')).toHaveText('Prévision');
  await expect(page.locator('#forecast-stats dt').first()).toHaveText('0,88');
  await page.click('[data-ui-lang="es"]');
  await expect(page.locator('.badge--spreading')).toHaveText('Expandiéndose');
});
