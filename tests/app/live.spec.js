// Phase 5: the "Right now" strip (live, asleep, unreachable) and "Most likely to spread next".
const { test, expect } = require('./fixtures');

const ready = (page) => page.waitForSelector('html[data-ready="true"]');
const LIVE = 'https://looked-up-live.abdellahsbaisbai.workers.dev/live.json*';

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

/** Serve a fresh live feed with these events, bursts and gap. */
async function feed(page, { events = [], bursts = [], gap = 0 } = {}) {
  const now = Date.now();
  await page.route(LIVE, (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ schema_version: 1, generated_at: new Date(now).toISOString(), status: { gap_minutes: gap },
      events, single_language_bursts: bursts }) }));
}

test('quiet: no two-language rush, so the busiest single-language edits are listed', async ({ page }) => {
  await feed(page, { bursts: [
    { lang: 'es', title: 'Partido_Pueblo', first_burst: new Date(Date.now() - 8 * 60e3).toISOString() },
    { lang: 'de', title: 'Berlin', first_burst: new Date(Date.now() - 20 * 60e3).toISOString() }] });
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#live-state')).toHaveText('No article is being rushed in two languages right now.');
  const items = page.locator('#live-list li');
  await expect(items).toHaveCount(2);
  await expect(items.first()).toContainText('Partido Pueblo');
  await expect(items.first()).toContainText('Spanish · first burst');
});

const liveEvent = (i) => ({ qid: `Q${i}`, labels: { en: `Event ${i}` }, desc: {}, first_burst: new Date(Date.now() - 5 * 60e3).toISOString(),
  languages: [{ lang: 'en' }, { lang: 'fr' }] });

test('a partial view of the last minutes is flagged under the live events', async ({ page }) => {
  await feed(page, { events: [liveEvent(1)], gap: 12 });
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#live-list li')).toHaveCount(1);
  await expect(page.locator('#live-state')).toHaveText('Partial view: the last 12 minutes are still filling in.');
});

test('at most four live events are listed', async ({ page }) => {
  await feed(page, { events: [1, 2, 3, 4, 5, 6].map(liveEvent) });
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#live-list li')).toHaveCount(4);
  await expect(page.locator('#live-list li').last()).toContainText('Event 4');
  await expect(page.locator('#live-state')).toHaveText('');
});

test('a fresh feed with an hour-long gap still rests', async ({ page }) => {
  await feed(page, { events: [liveEvent(1)], gap: 60 });
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#right-now')).toHaveClass(/is-resting/);
  await expect(page.locator('#live-list li')).toHaveCount(0);
});

test('?live= reads another workers.dev host', async ({ page }) => {
  const other = 'https://staging.example.workers.dev/live.json';
  await page.route(`${other}*`, (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ schema_version: 1, generated_at: new Date().toISOString(), status: { gap_minutes: 0 },
      events: [liveEvent(7)], single_language_bursts: [] }) }));
  await page.goto(`./?live=${encodeURIComponent(other)}`);
  await ready(page);
  await expect(page.locator('#live-list li').first()).toContainText('Event 7');
});

test('?live= on another domain falls back to the default Worker', async ({ page }) => {
  const asked = [];
  page.on('request', (r) => asked.push(r.url()));
  await page.goto(`./?live=${encodeURIComponent('https://evil.example/live.json')}`);
  await ready(page);
  await expect(page.locator('#live-list li').first()).toContainText('Saïdou Simporé');
  expect(asked.some((u) => u.startsWith('https://evil.example'))).toBe(false);
});

test('a live event name links the article where it burst first', async ({ page }) => {
  await page.goto('./');
  await ready(page);
  const link = page.locator('#live-list li').first().locator('strong a');
  await expect(link).toHaveAttribute('href', `https://fr.wikipedia.org/wiki/${encodeURIComponent('Saïdou_Simporé')}`);
  await expect(link).toHaveAttribute('rel', 'noopener');
});

test('a quiet feed links each single-language burst', async ({ page }) => {
  await feed(page, { bursts: [{ lang: 'es', title: 'Partido_Pueblo', first_burst: new Date().toISOString() }] });
  await page.goto('./');
  await ready(page);
  await expect(page.locator('#live-list li strong a')).toHaveAttribute('href', 'https://es.wikipedia.org/wiki/Partido_Pueblo');
  await expect(page.locator('#live-list li strong a')).toHaveText('Partido Pueblo');
});
