// Phase 3b: hero rule (F1), descriptions (F3), shareable URLs (F6), phone nav (F8).
const { test, expect } = require('./fixtures');
const fs = require('node:fs');
const path = require('node:path');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');
const today = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'today.json'), 'utf8'));

test('F1: the hero is the qualifying event with the most excess views, not the widest', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await expect(page.locator('.card').first()).toContainText('Navi Pillay');
  await expect(page.locator('#hero-label')).toHaveText('Navi Pillay');
  await expect(page.locator('#hero-kicker')).toHaveText('fig. 00 · last 24 hours');
  await expect(page.locator('#hero-brief')).toContainText('the world looked up Navi Pillay');
});

test('F1: a quiet day widens the hero to 48 hours', async ({ page }) => {
  const quiet = { ...today, generated_at: '2026-08-18T12:00:00Z',
    events: today.events.filter((e) => e.excess < 30000 && e.tier === 'noticed').map((e) => ({ ...e, start: '2026-08-18T08:00Z' })) };
  await page.route('**/data/app/today.json*', (route) => route.fulfill({
    status: 200, contentType: 'application/gzip', body: require('node:zlib').gzipSync(JSON.stringify(quiet)) }));
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#hero-kicker')).toHaveText('fig. 00 · last 48 hours');
  await expect(page.locator('#hero-label')).toHaveText('Hayden Panettiere');
});

test('F3: descriptions appear under the hero label and on cards', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#hero-desc')).toHaveText('South African lawyer, judge, and human rights activist');
  await expect(page.locator('.card').first().locator('.card__desc')).toHaveText('South African lawyer, judge, and human rights activist');
  await page.click('[data-ui-lang="fr"]');
  await page.goto('./#/day/2026-08-17/event/Q171571');
  await ready(page);
  await expect(page.locator('.card.is-selected .card__desc')).toHaveText('actrice américaine');
  await expect(page.locator('#brief-about')).toContainText('Hayden Panettiere : actrice américaine');
});

test('F6: a direct event link opens the day, selects the event and titles the page', async ({ page }) => {
  await page.goto('./#/day/2026-08-17/event/Q171571');
  await ready(page);
  await expect(page.locator('#day-out')).toContainText('17');
  await expect(page.locator('.card.is-selected .card__title')).toHaveText('Hayden Panettiere');
  await expect(page).toHaveTitle('Hayden Panettiere, 17 August · Looked Up');
  await expect(page.locator('.card.is-selected')).toBeInViewport();
});

test('F6: back and forward move between days and language panels', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await page.click('#prev-day');
  await expect(page).toHaveURL(/#\/day\/2026-08-16$/);
  await page.selectOption('#lang-select', 'ja');
  await expect(page).toHaveURL(/#\/lang\/ja$/);
  await expect(page).toHaveTitle('What Japanese readers looked up · Looked Up');
  await page.goBack();
  await expect(page).toHaveURL(/#\/day\/2026-08-16$/);
  await page.goBack();
  await expect(page).toHaveURL(/#\/day\/2026-08-17$/);
  await expect(page.locator('#day-out')).toContainText('17');
  await page.goForward();
  await expect(page.locator('#day-out')).toContainText('16');
});

test('F6: copy link puts the event URL on the clipboard', async ({ page, context, browserName }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  const first = page.locator('.card').first();
  await first.locator('.linkbtn').click();
  await expect(first.locator('.linkbtn')).toHaveText('Link copied');
  const url = await page.evaluate(() => navigator.clipboard.readText());
  expect(url).toMatch(/#\/day\/2026-08-17\/event\/Q\d+$/);
  await page.click('#copy-day');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/#\/day\/2026-08-17$/);
});

test('F8: phones get a bottom nav; desktops keep the header nav', async ({ page, isMobile }) => {
  await page.goto('./');
  await ready(page);
  if (isMobile) {
    await expect(page.locator('.bottomnav')).toBeVisible();
    await expect(page.locator('.header .nav')).toBeHidden();
    await page.locator('.bottomnav a[href="#languages"]').click();
    await expect(page.locator('#langs-title')).toBeInViewport();
  } else {
    await expect(page.locator('.bottomnav')).toBeHidden();
    await expect(page.locator('.header .nav')).toBeVisible();
  }
});

test('F8: native language names only when they add something', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#hero-sub')).toContainText('led by English ·');
  await expect(page.locator('#hero-sub')).not.toContainText('(English)');
  const ja = await page.locator('#lang-select option[value="ja"]').textContent();
  expect(ja).toBe('Japanese (日本語)');
});
