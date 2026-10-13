// The flat-map projection, run with `npm run test:unit`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { H, LAT_BOTTOM, LAT_TOP, W, polygons, project, ringPath } from '../../../app/js/projection.js';

test('equirectangular corners, latitude clamped to the cropped band', () => {
  assert.deepEqual(project([-180, LAT_TOP]), [0, 0]);
  assert.deepEqual(project([180, LAT_BOTTOM]), [W, H]);
  assert.deepEqual(project([0, 90]), project([0, LAT_TOP]));          // the Arctic is cropped
  assert.deepEqual(project([0, -90]), project([0, LAT_BOTTOM]));       // so is Antarctica
});

test('polygons of a geometry', () => {
  const ring = [[0, 0], [1, 0], [1, 1], [0, 0]];
  assert.deepEqual(polygons({ type: 'Polygon', coordinates: [ring] }), [[ring]]);
  assert.deepEqual(polygons({ type: 'MultiPolygon', coordinates: [[ring], [ring]] }), [[ring], [ring]]);
  assert.deepEqual(polygons({ type: 'Point', coordinates: [0, 0] }), []);
  assert.deepEqual(polygons(null), []);
});

test('a ring crossing the antimeridian stays on the right edge', () => {
  const fiji = [[179, -17], [-179, -17], [-179, -18], [179, -18], [179, -17]];
  const xs = [...ringPath(fiji).matchAll(/[ML](-?[\d.]+),/g)].map((m) => Number(m[1]));
  assert.ok(Math.min(...xs) > W * 0.99, 'no point jumps to the left edge');
  assert.ok(ringPath([[0, 0], [1, 0], [1, 1]]).endsWith('Z'));
});
