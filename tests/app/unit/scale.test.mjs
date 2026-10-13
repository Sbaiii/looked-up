// The absolute colour scale (ADR 0025), run with `npm run test:unit`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MAX, MIN, scale, tickLabel } from '../../../app/js/scale.js';

test('scale runs from the spike threshold to 5,000 on a log axis', () => {
  assert.equal(scale(MIN), 0);
  assert.equal(scale(0), 0);
  assert.equal(scale(undefined), 0);
  assert.equal(scale(MAX), 1);
  assert.equal(scale(MAX * 10), 1);
  assert.ok(Math.abs(scale(Math.sqrt(MIN * MAX)) - 0.5) < 1e-9);     // the geometric midpoint sits in the middle
});
