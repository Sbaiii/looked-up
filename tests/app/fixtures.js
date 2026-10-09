// Serve the Hub's data/app/ files from tests/app/fixtures (gzipped on the fly for the .gz twins),
// so smoke tests don't depend on the live dataset.
const { test: base, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');

const DIR = path.join(__dirname, 'fixtures');

const test = base.extend({
  page: async ({ page }, use) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    await page.route('https://huggingface.co/datasets/Sbaiiiiii/looked-up/resolve/main/data/app/**', (route) => {
      const name = route.request().url().split('/data/app/')[1];
      const gz = name.endsWith('.gz');
      const file = path.join(DIR, gz ? name.slice(0, -3) : name);
      if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: 'missing' });
      const body = fs.readFileSync(file);
      return route.fulfill({ status: 200, headers: { 'access-control-allow-origin': '*' },
        contentType: gz ? 'application/gzip' : 'application/json', body: gz ? zlib.gzipSync(body) : body });
    });
    page.errors = errors;
    await use(page);
  },
});

module.exports = { test, expect };
