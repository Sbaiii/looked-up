// The absolute colour scale (ADR 0025), run with `npm run test:unit`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MAX, MIN, TICKS, scale, tickLabel } from '../../../app/js/scale.js';

test('scale runs from the spike threshold to 5,000 on a log axis', () => {
  assert.equal(scale(MIN), 0);
  assert.equal(scale(0), 0);
  assert.equal(scale(undefined), 0);
  assert.equal(scale(MAX), 1);
  assert.equal(scale(MAX * 10), 1);
  assert.ok(Math.abs(scale(Math.sqrt(MIN * MAX)) - 0.5) < 1e-9);     // the geometric midpoint sits in the middle
});

test('tick labels', () => {
  assert.deepEqual([8, 50, 500, 1000, 5000].map(tickLabel), ['8', '50', '500', '1k', '5k+']);
});

test('legend ticks start at the floor, end at the top and rise along the scale', () => {
  assert.equal(TICKS[0], MIN);
  assert.equal(TICKS.at(-1), MAX);
  const pos = TICKS.map(scale);
  assert.deepEqual([pos[0], pos.at(-1)], [0, 1]);
  assert.ok(pos.every((p, i) => !i || p > pos[i - 1]));
});

test('scale rises strictly between the floor and the top', () => {
  const xs = [9, 20, 100, 1000, 4999].map(scale);
  assert.ok(xs.every((x, i) => x > 0 && x < 1 && (!i || x > xs[i - 1])));
});

test('negative, NaN and null surprises map to 0', () => {
  assert.equal(scale(-5), 0);
  assert.equal(scale(Number.NaN), 0);
  assert.equal(scale(null), 0);
});
