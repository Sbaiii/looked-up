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
