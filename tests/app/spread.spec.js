// The spread table: the selected event's languages as rows, the readable twin of the map.
const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');
const today = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'today.json'), 'utf8'));
const byQid = Object.fromEntries(today.events.map((e) => [e.qid, e]));

test('one row per language of the selected event, earliest first', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.click('#cards .card[data-qid="Q804"] .card__title button');
  await page.click('#spread summary');
  const ev = byQid.Q804;
  const rows = page.locator('#spread-rows tr');
  await expect(rows).toHaveCount(ev.langs.length);
  const lags = await rows.evaluateAll((rs) => rs.map((r) => Number(r.cells[2].textContent.replace(/[^\d]/g, ''))));
  expect(lags).toEqual([...lags].sort((a, b) => a - b));
  expect(page.errors).toEqual([]);
});

test('selecting another card refills the table and its caption', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.click('#cards .card[data-qid="Q804"] .card__title button');
  await expect(page.locator('#spread-caption')).toContainText('Panama');
  await page.click('#cards .card[data-qid="Q242078"] .card__title button');
  await expect(page.locator('#spread-caption')).toHaveText('Navi Pillay: languages in the order they spiked');
  await expect(page.locator('#spread-rows tr')).toHaveCount(byQid.Q242078.langs.length);
});

test('row contents: language, first spike hour, +lag, peak surprise, extra views', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.click('#cards .card[data-qid="Q242078"] .card__title button');
  await page.click('#spread summary');
  const de = byQid.Q242078.langs.find((r) => r.lang === 'de');
  const row = page.locator('#spread-rows tr', { hasText: 'German' });
  await expect(row.locator('td')).toHaveText(['09:00', `+${de.lag} h`, '1,886.4', de.excess.toLocaleString('en-GB')]);
});

test('headings and caption follow the interface language', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.click('[data-ui-lang="es"]');
  await expect(page.locator('#spread summary')).toHaveText('La difusión en una tabla');
  await expect(page.locator('#spread thead th')).toHaveText(['Idioma', 'Primer pico (UTC)', 'Tras el primero', 'Sorpresa máxima', 'Visitas de más']);
  await expect(page.locator('#spread-caption')).toContainText('los idiomas en el orden de su pico');
});
