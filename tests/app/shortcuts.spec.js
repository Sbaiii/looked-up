// Keyboard shortcuts on the day view, from fixtures.
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');

test('the left and right arrows step through days', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await page.locator('body').press('ArrowLeft');
  await expect(page).toHaveURL(/#\/day\/2026-08-16$/);
  await page.locator('body').press('ArrowRight');
  await expect(page).toHaveURL(/#\/day\/2026-08-17$/);
  expect(page.errors).toEqual([]);
});

test('arrows in a field or with a modifier key leave the day alone', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  const before = await page.locator('#day-out').textContent();
  await page.locator('#lang-select').focus();
  await page.keyboard.press('ArrowLeft');                     // moves the picker's option, not the day
  await page.locator('body').press('Alt+ArrowLeft');
  await page.locator('body').press('Control+ArrowRight');
  await expect(page.locator('#day-out')).toHaveText(before);
});

test('T goes back to today from a past day', async ({ page }) => {
  await page.goto('./#/day/2026-08-16');
  await ready(page);
  await page.locator('body').press('t');
  await expect(page).toHaveURL(/#\/today$/);
  await expect(page.locator('#day-out')).toHaveText('Today');
});

test('the keyboard help line: shown with a mouse, hidden on touch screens, translated', async ({ page, isMobile }) => {
  await page.goto('./');
  await ready(page);
  const help = page.locator('#keys-help');
  if (isMobile) { await expect(help).toBeHidden(); return; }
  await expect(help).toHaveText('Keys: ← → change the day · J K next and previous event · T today · / search');
  await page.click('[data-ui-lang="es"]');
  await expect(help).toHaveText('Teclado: ← → cambia de día · J K evento siguiente y anterior · T hoy · / buscar');
});

test('J selects the next card, K the previous one, and the URL names the event', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  const ids = await page.locator('#cards .card').evaluateAll((cs) => cs.map((c) => c.dataset.qid));
  const selected = () => page.locator('.card.is-selected').getAttribute('data-qid');
  const start = ids.indexOf(await selected());
  await page.locator('body').press('j');
  expect(await selected()).toBe(ids[start + 1]);
  await expect(page).toHaveURL(new RegExp(`#/day/2026-08-17/event/${ids[start + 1]}$`));
  await page.keyboard.press('k');                                    // focus is now on the card: keys still work
  expect(await selected()).toBe(ids[start]);
});

test('K on the first card and J on the last card stay put', async ({ page }) => {
  await page.goto('./#/day/2026-08-17');
  await ready(page);
  await page.click('#cards .card:first-child .card__title button');
  const first = await page.locator('#cards .card').first().getAttribute('data-qid');
  await page.keyboard.press('k');
  await expect(page.locator('.card.is-selected')).toHaveAttribute('data-qid', first);
  await page.click('#cards .card:last-child .card__title button');
  const last = await page.locator('#cards .card').last().getAttribute('data-qid');
  await page.keyboard.press('j');
  await expect(page.locator('.card.is-selected')).toHaveAttribute('data-qid', last);
});

test('J moves between the cards the search leaves', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.fill('#card-search', 'pillay');
  await page.locator('body').click({ position: { x: 1, y: 1 } });
  await page.keyboard.press('j');
  await expect(page.locator('.card.is-selected')).toHaveAttribute('data-qid', 'Q242078');
  await page.keyboard.press('j');
  await expect(page.locator('.card.is-selected')).toHaveAttribute('data-qid', 'Q242078');
});
