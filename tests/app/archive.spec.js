// Archive days: a URL naming a day older than the slider's 90-day window loads that day file straight from the Hub
// and shows it with an "archive" tag, while the slider keeps its window. The case study links to three such days.
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');
const STATS = path.join(__dirname, 'fixtures', 'stats.json');

/** Serve stats.json with a window that starts after every case-study day, so all three are archive days. */
async function laterWindow(page) {
  const stats = JSON.parse(fs.readFileSync(STATS, 'utf8'));
  const row = stats.timeline[stats.timeline.length - 1];
  stats.timeline = [{ ...row, day: '2026-09-30' }, { ...row, day: '2026-10-01' }];
  stats.first_day = '2026-09-30';
  stats.last_day = '2026-10-01';
  const body = JSON.stringify(stats);
  await page.route('https://huggingface.co/datasets/Sbaiiiiii/looked-up/resolve/main/data/app/stats.json*', (route) => {
    const gz = route.request().url().endsWith('.gz');
    return route.fulfill({ status: 200, headers: { 'access-control-allow-origin': '*' },
      contentType: gz ? 'application/gzip' : 'application/json', body: gz ? zlib.gzipSync(body) : body });
  });
}

test('a day older than the window is fetched directly and tagged as archive', async ({ page }) => {
  await page.goto('./#/day/2026-07-19/event/Q182063');       // the fixture window is 16 and 17 Aug, plus today
  await ready(page);
  await expect(page.locator('#day-archive')).toBeVisible();
  await expect(page.locator('#day-archive')).toHaveText('Archive');
  await expect(page.locator('.card.is-selected')).toContainText('Nicolás Otamendi');
  await expect(page.locator('#bars rect')).toHaveCount(3);     // the slider keeps its window
  await expect(page.locator('#bars rect.is-on')).toHaveCount(0);
  await page.click('[data-ui-lang="fr"]');
  await expect(page.locator('#day-archive')).toHaveText('Archives');
  expect(page.errors).toEqual([]);
});

for (const [hash, name] of [
  ['#/day/2026-08-17/event/Q171571', 'Hayden Panettiere'],
  ['#/day/2026-07-19/event/Q182063', 'Nicolás Otamendi'],
  ['#/day/2026-07-27/event/Q125970', 'Keigo Higashino'],
]) {
  test(`the case study link ${hash} keeps working outside the window`, async ({ page }) => {
    await laterWindow(page);
    await page.goto(`./${hash}`);
    await ready(page);
    await expect(page.locator('#day-archive')).toBeVisible();
    await expect(page.locator('.card.is-selected')).toContainText(name);
    expect(page.url()).toContain(hash);
    expect(page.errors).toEqual([]);
  });
}

test('the arrows leave an archive day for the window, and the tag goes away', async ({ page }) => {
  await page.goto('./#/day/2026-07-27');
  await ready(page);
  await expect(page.locator('#day-archive')).toBeVisible();
  await page.click('#next-day');
  await expect(page.locator('#day-archive')).toBeHidden();
  await expect(page).toHaveURL(/#\/day\/2026-08-16$/);
  await expect(page.locator('#bars rect.is-on')).toHaveCount(1);
});

test('an old day without a file falls back to the latest day', async ({ page }) => {
  await page.goto('./#/day/2026-06-01');
  await ready(page);
  await expect(page.locator('#day-archive')).toBeHidden();
  await expect(page.locator('#bars rect').last()).toHaveClass('is-on');
});

test('the archive tag is translated in every interface language', async ({ page }) => {
  await page.goto('./#/day/2026-07-27');
  await ready(page);
  await expect(page.locator('#day-archive')).toHaveText('Archive');
  await page.click('[data-ui-lang="es"]');
  await expect(page.locator('#day-archive')).toHaveText('Archivo');
  await expect(page.locator('#day-archive')).toBeVisible();
});

test('copy link on an archive day copies that day', async ({ page, context, browserName }) => {
  test.skip(browserName !== 'chromium', 'clipboard permissions are Chromium-only here');
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('./#/day/2026-07-27');
  await ready(page);
  await page.click('#copy-day');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/#\/day\/2026-07-27$/);
});

test('an archive event link titles the page', async ({ page }) => {
  await page.goto('./#/day/2026-07-19/event/Q182063');
  await ready(page);
  await expect(page).toHaveTitle('Nicolás Otamendi, 19 July · Looked Up');
});
