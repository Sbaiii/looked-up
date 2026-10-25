// The card filters and orders (app/js/filters.js), run with `npm run test:unit`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SORTS, categoryCounts, fold, matches, visible } from '../../../app/js/filters.js';

const ev = (qid, o = {}) => ({ qid, tier: 'noticed', category: 'other', breadth: 2, excess: 100, spread_h: 1,
  start: '2026-08-17T02:00Z', labels: { en: qid }, desc: {}, langs: [{ lang: 'en' }], ...o });

test('fold removes accents and case, and copes with missing text', () => {
  assert.equal(fold('São Paulo'), 'sao paulo');
  assert.equal(fold('ÉCOLE Ñandú'), 'ecole nandu');
  assert.equal(fold(null), '');
  assert.equal(fold(42), '42');
});

test('matches looks at every label, every description and the QID', () => {
  const e = ev('Q90', { labels: { en: 'Paris', ru: 'Париж' }, desc: { fr: 'capitale de la France' } });
  assert.ok(matches(e, fold('PARIS')) && matches(e, fold('париж')) && matches(e, fold('capitale')));
  assert.ok(matches(e, 'q90') && matches(e, ''));
  assert.ok(!matches(e, 'lyon'));
});

test('visible applies the tier floor, the category and the language together', () => {
  const evs = [ev('Q1', { tier: 'planetary', category: 'death', langs: [{ lang: 'ja' }] }),
    ev('Q2', { tier: 'international', category: 'death' }), ev('Q3', { category: 'sports', langs: [{ lang: 'ja' }] })];
  const ids = (f) => visible(evs, f).map((e) => e.qid);
  assert.deepEqual(ids({ tier: 'noticed' }), ['Q1', 'Q2', 'Q3']);
  assert.deepEqual(ids({ tier: 'international' }), ['Q1', 'Q2']);
  assert.deepEqual(ids({ tier: 'noticed', category: 'death' }), ['Q1', 'Q2']);
  assert.deepEqual(ids({ tier: 'noticed', lang: 'ja' }), ['Q1', 'Q3']);
  assert.deepEqual(ids({ tier: 'international', category: 'death', lang: 'ja' }), ['Q1']);
  assert.deepEqual(visible(null, {}), []);
});

test('orders: views, fastest (wider first on ties), latest, earliest; the input is left alone', () => {
  const evs = [ev('A', { excess: 5, spread_h: 2, breadth: 3, start: '2026-08-17T05:00Z' }),
    ev('B', { excess: 9, spread_h: 1, breadth: 2, start: '2026-08-17T01:00Z' }),
    ev('C', { excess: 1, spread_h: 1, breadth: 6, start: '2026-08-17T09:00Z' })];
  const ids = (sort) => visible(evs, { sort }).map((e) => e.qid);
  assert.deepEqual(ids('widest'), ['A', 'B', 'C']);
  assert.deepEqual(ids('views'), ['B', 'A', 'C']);
  assert.deepEqual(ids('fastest'), ['C', 'B', 'A']);
  assert.deepEqual(ids('latest'), ['C', 'A', 'B']);
  assert.deepEqual(ids('earliest'), ['B', 'A', 'C']);
  assert.deepEqual(evs.map((e) => e.qid), ['A', 'B', 'C']);
  assert.equal(SORTS.widest, null);
});

test('categoryCounts counts per category, missing ones as other', () => {
  assert.deepEqual(categoryCounts([ev('1', { category: 'death' }), ev('2', { category: 'death' }), ev('3', { category: null })]),
    { death: 2, other: 1 });
  assert.deepEqual(categoryCounts(undefined), {});
});

test('sortSpread sorts language rows by any column, ties by lag then code', async () => {
  const { sortSpread } = await import('../../../app/js/filters.js');
  const rows = [{ lang: 'fr', first: '2026-08-17T03:00Z', lag: 1, surprise: 20, excess: 50 },
    { lang: 'en', first: '2026-08-17T02:00Z', lag: 0, surprise: 90, excess: 900 },
    { lang: 'de', first: '2026-08-17T03:00Z', lag: 1, surprise: 40, excess: 50 }];
  const by = (k, d) => sortSpread(rows, k, d).map((r) => r.lang);
  assert.deepEqual(by('lag'), ['en', 'de', 'fr']);
  assert.deepEqual(by('surprise'), ['en', 'de', 'fr']);              // largest first by default
  assert.deepEqual(by('surprise', 'asc'), ['fr', 'de', 'en']);
  assert.deepEqual(by('excess'), ['en', 'de', 'fr']);                // tie at 50: lag, then code
  assert.deepEqual(by('lang'), ['de', 'en', 'fr']);
  assert.deepEqual(by('first', 'desc'), ['de', 'fr', 'en']);
  assert.deepEqual(rows.map((r) => r.lang), ['fr', 'en', 'de']);    // input untouched
});

test('unknown tier or order fall back to everything, in file order', () => {
  const evs = [ev('A', { tier: 'planetary', excess: 1 }), ev('B', { excess: 9 })];
  assert.deepEqual(visible(evs, { tier: 'nonsense', sort: 'nonsense' }).map((e) => e.qid), ['A', 'B']);
});

test('an empty search keeps every event; a description in Japanese is searchable', () => {
  const evs = [ev('Q1', { desc: { ja: '日本の作家' } }), ev('Q2')];
  assert.equal(visible(evs, { query: '' }).length, 2);
  assert.deepEqual(visible(evs, { query: fold('作家') }).map((e) => e.qid), ['Q1']);
});

test('sortSpread copes with no rows and an unknown key', async () => {
  const { sortSpread } = await import('../../../app/js/filters.js');
  assert.deepEqual(sortSpread(undefined), []);
  const rows = [{ lang: 'fr', lag: 1 }, { lang: 'en', lag: 0 }];
  assert.deepEqual(sortSpread(rows, 'nonsense').map((r) => r.lang), ['en', 'fr']);
});

test('events without labels or descriptions are still found by QID and never break the search', () => {
  const bare = { qid: 'Q7', tier: 'noticed' };
  assert.ok(matches(bare, 'q7'));
  assert.ok(!matches(bare, 'paris'));
  assert.deepEqual(visible([bare], { query: 'q7' }).map((e) => e.qid), ['Q7']);
});

test('a partial word matches', () => {
  assert.ok(matches(ev('Q1', { labels: { en: 'Constantinople' } }), 'stanti'));
});

test('an event without a category is left out when a category is chosen', () => {
  const evs = [ev('A', { category: undefined }), ev('B', { category: 'death' })];
  assert.deepEqual(visible(evs, { category: 'death' }).map((e) => e.qid), ['B']);
});

test('zh does not match zh-yue', () => {
  const evs = [ev('A', { langs: [{ lang: 'zh-yue' }] }), ev('B', { langs: [{ lang: 'zh' }] })];
  assert.deepEqual(visible(evs, { lang: 'zh' }).map((e) => e.qid), ['B']);
});

test('folding handles Vietnamese and Polish letters', () => {
  assert.equal(fold('Hồ Chí Minh'), 'ho chi minh');
  assert.equal(fold('Łódź'), 'lodz');
});

test('equal starts keep the file order in time orders', () => {
  const evs = [ev('A'), ev('B'), ev('C')];
  assert.deepEqual(visible(evs, { sort: 'latest' }).map((e) => e.qid), ['A', 'B', 'C']);
  assert.deepEqual(visible(evs, { sort: 'earliest' }).map((e) => e.qid), ['A', 'B', 'C']);
});

test('ø, æ, þ, ß and dotless ı fold too', () => {
  assert.equal(fold('Øresund'), 'oresund');
  assert.equal(fold('Ærø'), 'aero');
  assert.equal(fold('Þingvellir'), 'thingvellir');
  assert.equal(fold('Straße'), 'strasse');
  assert.equal(fold('Diyarbakır'), 'diyarbakir');
});

test('"da nang" finds Đà Nẵng', () => {
  assert.ok(matches(ev('Q1', { labels: { vi: 'Đà Nẵng' } }), fold('da nang')));
});

test('equal extra views keep the file order', () => {
  const evs = [ev('A', { excess: 5 }), ev('B', { excess: 5 }), ev('C', { excess: 9 })];
  assert.deepEqual(visible(evs, { sort: 'views' }).map((e) => e.qid), ['C', 'A', 'B']);
});

test('international and up excludes noticed only', async () => {
  const { TIER_RANK } = await import('../../../app/js/filters.js');
  assert.ok(TIER_RANK.noticed < TIER_RANK.international && TIER_RANK.international < TIER_RANK.planetary);
});
