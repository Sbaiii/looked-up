// Phase 5: the "Right now" strip (live, asleep, unreachable) and "Most likely to spread next".
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');
const LIVE = 'https://huggingface.co/datasets/Sbaiiiiii/looked-up/resolve/main/data/live/live.json*';

test('live: the strip lists live events with languages and minutes since the first burst', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  const items = page.locator('#live-list li');
  await expect(items).toHaveCount(2);
  await expect(items.first()).toContainText('Saïdou Simporé');
  await expect(items.first()).toContainText('Burkinabé politician');
  await expect(items.first()).toContainText('editing in French and English · first burst 12 min ago');
  await expect(page.locator('#right-now')).not.toHaveClass(/is-resting/);
  await expect(page.locator('#live-kicker')).toHaveText('Right now · editors are confirming');
  await expect(page.locator('#right-now')).toContainText('Readers usually get there first; editors follow within about two hours');
  await page.click('[data-ui-lang="fr"]');
  await expect(items.first()).toContainText('homme politique burkinabé');
  expect(page.errors).toEqual([]);
});

test('asleep: a stale feed shows one quiet line, never an error', async ({ page }) => {
  await page.route(LIVE, (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ schema_version: 1, generated_at: new Date(Date.now() - 3 * 3600e3).toISOString(),
      status: { gap_minutes: 60 }, events: [], single_language_bursts: [] }) }));
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#live-state')).toHaveText("The live layer is resting; editors' signals will be back shortly.");
  await expect(page.locator('#right-now')).toHaveClass(/is-resting/);
  await expect(page.locator('#live-list li')).toHaveCount(0);
});

test('unreachable: the strip rests quietly', async ({ page }) => {
  await page.route(LIVE, (route) => route.abort());
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#live-state')).toHaveText("The live layer is resting; editors' signals will be back shortly.");
});

test('most likely to spread next: top open events by forecast, whatever the threshold', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  const items = page.locator('#next-list li');
  await expect(items).toHaveCount(2);
  await expect(items.first()).toContainText('Avatar: Seven Havens');
  await expect(items.first()).toContainText('72% chance of going international');
  await expect(items.nth(1)).toContainText('20% chance of going international');
  await expect(page.locator('#next')).toContainText('Forecast, not a fact');
});

test('the About section states the H9 lead times', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await expect(page.locator('.about__live')).toContainText('a median 1 h 46 min after the first reading spike');
  await page.click('[data-ui-lang="es"]');
  await expect(page.locator('#live-kicker')).toHaveText('Ahora mismo · los editores están confirmando');
});
