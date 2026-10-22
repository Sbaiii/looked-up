// The CSV builder behind the day download, run with `npm run test:unit`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { field, toCsv } from '../../../app/js/csv.js';

test('fields are quoted only when they need it, with quotes doubled', () => {
  assert.equal(field('Lisbon'), 'Lisbon');
  assert.equal(field('Paris, Texas'), '"Paris, Texas"');
  assert.equal(field('The "Boss"'), '"The ""Boss"""');
  assert.equal(field('two\nlines'), '"two\nlines"');
  assert.equal(field(null), '');
  assert.equal(field(0), '0');
});

test('toCsv writes the header, then one row per object, with CRLF line ends', () => {
  const csv = toCsv([{ a: 1, b: 'x,y' }, { a: 2 }], ['a', 'b']);
  assert.equal(csv, 'a,b\r\n1,"x,y"\r\n2,\r\n');
  assert.equal(toCsv([], ['a']), 'a\r\n');
});

test('dayRows lists multi-language events, then single-language ones, with names from the given functions', async () => {
  const { dayRows, DAY_COLUMNS } = await import('../../../app/js/csv.js');
  const ev = (qid, cls) => ({ qid, class: cls, tier: 'noticed', breadth: 2, lead: 'fr', start: '2026-08-17T02:00Z',
    spread_h: 1, excess: 900, category: 'sports', langs: [{ lang: 'fr' }, { lang: 'en' }],
    urls: { fr: `https://fr.wikipedia.org/wiki/${qid}` }, labels: { en: `L${qid}` } });
  const rows = dayRows({ events: [ev('Q1', 'multi_language')], single_language_events: [ev('Q2', 'single_language')] },
    '2026-08-17', { label: (e) => e.labels.en, desc: () => '' });
  assert.deepEqual(rows.map((r) => r.qid), ['Q1', 'Q2']);
  assert.equal(rows[0].languages, 'fr en');
  assert.equal(rows[0].wikipedia_url, 'https://fr.wikipedia.org/wiki/Q1');
  assert.equal(rows[1].label, 'LQ2');
  assert.deepEqual(Object.keys(rows[0]), DAY_COLUMNS);
});

test('non-Latin text passes through and carriage returns are quoted', () => {
  assert.equal(field('東京'), '東京');
  assert.equal(field('Пиллэй, Нави'), '"Пиллэй, Нави"');
  assert.equal(field('a\rb'), '"a\rb"');
});

test('an empty day gives no rows, and an event without a lead URL has a blank link', async () => {
  const { dayRows } = await import('../../../app/js/csv.js');
  const fns = { label: (e) => e.qid, desc: () => '' };
  assert.deepEqual(dayRows({}, '2026-08-17', fns), []);
  const [r] = dayRows({ events: [{ qid: 'Q1', lead: 'ja', urls: { en: 'https://en.wikipedia.org/wiki/X' } }] }, '2026-08-17', fns);
  assert.equal(r.wikipedia_url, '');
  assert.equal(r.languages, '');
});
