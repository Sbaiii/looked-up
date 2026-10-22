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
