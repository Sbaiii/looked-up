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
