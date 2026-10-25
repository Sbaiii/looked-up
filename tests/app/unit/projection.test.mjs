// The flat-map projection, run with `npm run test:unit`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { H, LAT_BOTTOM, LAT_TOP, W, centroid, featureKey, geomPath, polygons, project, ringPath } from '../../../app/js/projection.js';

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

test('centroid of a square is its centre, rounded to two decimals', () => {
  const square = { type: 'Polygon', coordinates: [[[10, 10], [20, 10], [20, 20], [10, 20], [10, 10]]] };
  assert.deepEqual(centroid(square), [15, 15]);
  const tri = { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [0, 1], [0, 0]]] };
  assert.deepEqual(centroid(tri), [0.33, 0.33]);
  assert.equal(centroid(null), null);
});

test('a multipolygon uses its largest outer ring', () => {
  const islands = { type: 'MultiPolygon', coordinates: [
    [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
    [[[40, 40], [50, 40], [50, 50], [40, 50], [40, 40]]],
  ] };
  assert.deepEqual(centroid(islands), [45, 45]);
});

test('a ring crossing the antimeridian is unwrapped before averaging', () => {
  const fiji = { type: 'Polygon', coordinates: [[[178, -18], [-178, -18], [-178, -16], [178, -16], [178, -18]]] };
  assert.deepEqual(centroid(fiji), [180, -17]);
  const east = { type: 'Polygon', coordinates: [[[179, 0], [-177, 0], [-177, 2], [179, 2], [179, 0]]] };
  assert.deepEqual(centroid(east), [-179, 1]);                          // past 180 it comes back as a western longitude
});

test('featureKey uses the ISO numeric id, then XKS for Kosovo, then the name', () => {
  assert.equal(featureKey({ id: '620', properties: { name: 'Portugal' } }), '620');
  assert.equal(featureKey({ properties: { name: 'Kosovo' } }), 'XKS');
  assert.equal(featureKey({ properties: { name: 'N. Cyprus' } }), 'N. Cyprus');
});

test('geomPath draws every ring of every part', () => {
  const ring = [[0, 0], [10, 0], [10, 10], [0, 0]];
  const multi = { type: 'MultiPolygon', coordinates: [[ring, ring], [ring]] };
  const d = geomPath(multi);
  assert.equal((d.match(/M/g) || []).length, 3);
  assert.equal((d.match(/Z/g) || []).length, 3);
  assert.equal(geomPath({ type: 'Point', coordinates: [0, 0] }), '');
});

test('lon 0 is the horizontal middle and latitude 0 sits inside the band', () => {
  const [x, y] = project([0, 0]);
  assert.equal(x, W / 2);
  assert.ok(y > 0 && y < H);
});

test('polygons ignores points, lines and missing geometry', () => {
  assert.deepEqual(polygons({ type: 'Point', coordinates: [0, 0] }), []);
  assert.deepEqual(polygons({ type: 'LineString', coordinates: [[0, 0], [1, 1]] }), []);
  assert.deepEqual(polygons(undefined), []);
});

test('ringPath is M, then L for each other point, then Z', () => {
  const d = ringPath([[0, 0], [10, 0], [10, 10]]);
  assert.match(d, /^M[\d.]+,[\d.]+(L[\d.]+,[\d.]+){2}Z$/);
});

test('geomPath draws holes as extra subpaths', () => {
  const outer = [[0, 0], [10, 0], [10, 10], [0, 0]];
  const hole = [[2, 2], [3, 2], [3, 3], [2, 2]];
  assert.equal((geomPath({ type: 'Polygon', coordinates: [outer, hole] }).match(/M/g) || []).length, 2);
});
