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
