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

test('letters and arrows typed in the search stay in the search', async ({ page }) => {
  await page.goto('./#/day/2026-08-16');
  await ready(page);
  await page.locator('#card-search').focus();
  await page.keyboard.type('t');
  await page.keyboard.press('ArrowLeft');
  await expect(page).toHaveURL(/#\/day\/2026-08-16$/);
  await expect(page.locator('#card-search')).toHaveValue('t');
});

test('search and tier filter work together, and the search stays when the day changes', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await page.fill('#card-search', 'pillay');
  await page.click('[data-tier="international"]');
  await expect(page.locator('#cards .card')).toHaveCount(1);              // Pillay is planetary, so still shown
  await page.click('[data-tier="planetary"]');
  await expect(page.locator('#cards .card')).toHaveCount(1);
  await page.click('#prev-day');
  await expect(page.locator('#card-search')).toHaveValue('pillay');
  await expect(page.locator('#cards .card, #cards .empty')).not.toHaveCount(0);
});

test('the placeholder follows the interface language', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#card-search')).toHaveAttribute('placeholder', 'Name, description or Q-number');
  await page.click('[data-ui-lang="es"]');
  await expect(page.locator('#card-search')).toHaveAttribute('placeholder', 'Nombre, descripción o número Q');
});

test('opening an event the search hides clears the search', async ({ page }) => {
  await page.goto('./#/day/2026-08-17/event/Q171571');
  await ready(page);
  await page.evaluate(() => { history.pushState(null, '', '#/day/2026-08-16'); history.pushState(null, '', '#/day/2026-08-17/event/Q171571'); });
  await page.fill('#card-search', 'zzzz');
  await page.goBack();
  await page.goForward();
  await expect(page.locator('.card.is-selected')).toContainText('Hayden Panettiere');
  await expect(page.locator('#card-search')).toHaveValue('');
});
