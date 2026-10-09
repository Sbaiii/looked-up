// Copy the pinned front-end libraries from node_modules into app/ (no CDN at runtime, no build step).
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { centroid, featureKey, geomPath, W, H } from '../app/js/projection.js';

const require = createRequire(import.meta.url);

const files = [
  ['node_modules/globe.gl/dist/globe.gl.min.js', 'app/vendor/globe.gl.min.js'],
  ['node_modules/topojson-client/dist/topojson-client.min.js', 'app/vendor/topojson-client.min.js'],
  ['node_modules/world-atlas/countries-110m.json', 'app/data/countries-110m.json'],
];
mkdirSync('app/vendor', { recursive: true });
mkdirSync('app/data', { recursive: true });
for (const [from, to] of files) copyFileSync(from, to);

const pkg = (name) => JSON.parse(readFileSync(`node_modules/${name}/package.json`, 'utf8'));
const lines = ['globe.gl', 'topojson-client', 'world-atlas'].map((n) => `- ${n} ${pkg(n).version} (${pkg(n).license})`);
writeFileSync('app/vendor/VERSIONS.md',
  `# Vendored libraries\n\nCopied by \`npm run vendor\` from the versions pinned in package.json:\n\n${lines.join('\n')}\n`);
console.log(lines.join('\n'));

// Pre-projected flat map (app/data/world-2d.json): converting TopoJSON in the browser cost ~2 s of main
// thread on a throttled phone. The globe still converts countries-110m.json, but only when requested.
const topojson = require('topojson-client');
const topo = JSON.parse(readFileSync('app/data/countries-110m.json', 'utf8'));
const features = topojson.feature(topo, topo.objects.countries).features.filter((f) => f.id !== '010');
const world = { w: W, h: H, countries: features.map((f) => ({ k: featureKey(f), d: geomPath(f.geometry), c: centroid(f.geometry) })) };
writeFileSync('app/data/world-2d.json', JSON.stringify(world));
console.log(`world-2d.json: ${world.countries.length} countries`);
