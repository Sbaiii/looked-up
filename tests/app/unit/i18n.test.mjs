// The i18n helpers without a browser: translation lookups, plurals and label fallbacks, run with `npm run test:unit`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as i18n from '../../../app/js/i18n.js';

const dict = (code) => JSON.parse(readFileSync(new URL(`../../../app/i18n/${code}.json`, import.meta.url)));

test('t picks the plural form, the zero form and fills placeholders', () => {
  i18n.use(dict('en'), 'en');
  assert.equal(i18n.t('event.languages', { n: 1 }), '1 language');
  assert.equal(i18n.t('event.languages', { n: 4 }), '4 languages');
  assert.equal(i18n.within(0), 'under an hour');
  assert.equal(i18n.within(2), '2 hours');
  assert.equal(i18n.t('hero.counter', { n: 3, within: i18n.within(1) }), '3 languages in 1 hour');
});
