// The search field above the event cards, from fixtures.
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');

test('typing narrows the cards to matching events', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.fill('#card-search', 'pillay');
  await expect(page.locator('#cards .card')).toHaveCount(1);
  await expect(page.locator('#cards .card')).toHaveAttribute('data-qid', 'Q242078');
  await page.fill('#card-search', '');
  expect(await page.locator('#cards .card').count()).toBeGreaterThan(1);
  expect(page.errors).toEqual([]);
});

test('accents, case and other languages', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.fill('#card-search', 'NAVANETHEM');                  // the French and German label of Navi Pillay
  await expect(page.locator('#cards .card[data-qid="Q242078"]')).toHaveCount(1);
  await page.fill('#card-search', 'нави');                         // the Russian label, in Cyrillic
  await expect(page.locator('#cards .card[data-qid="Q242078"]')).toHaveCount(1);
  await page.fill('#card-search', "droits de l'homme");                     // French description
  await expect(page.locator('#cards .card[data-qid="Q242078"]')).toHaveCount(1);
});

test('a Q-number finds the event', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.fill('#card-search', 'q804');
  await expect(page.locator('#cards .card')).toHaveCount(1);
  await expect(page.locator('#cards .card')).toHaveAttribute('data-qid', 'Q804');
});

test('no result: the empty line quotes the search, in the interface language', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.fill('#card-search', 'zzzz nothing');
  await expect(page.locator('#cards .empty')).toHaveText('No event on this day matches “zzzz nothing”.');
  await expect(page.locator('#more')).toBeHidden();
  await page.click('[data-ui-lang="fr"]');
  await expect(page.locator('#cards .empty')).toHaveText('Aucun événement de ce jour ne correspond à « zzzz nothing ».');
});

test('/ jumps to the search, Escape clears it and brings the cards back', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  const all = await page.locator('#cards .card').count();
  await page.locator('body').press('/');
  await expect(page.locator('#card-search')).toBeFocused();
  await page.keyboard.type('pillay');
  await expect(page.locator('#cards .card')).toHaveCount(1);
  await page.keyboard.press('Escape');
  await expect(page.locator('#card-search')).toHaveValue('');
  await expect(page.locator('#cards .card')).toHaveCount(all);
});
