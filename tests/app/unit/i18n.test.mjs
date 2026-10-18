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

test('a missing key comes back as the key, and an unknown placeholder is kept', () => {
  i18n.use({ locale: 'en-GB', greet: 'hello {who}' }, 'en');
  assert.equal(i18n.t('no.such.key'), 'no.such.key');
  assert.equal(i18n.t('greet'), 'hello {who}');
  assert.equal(i18n.t('greet', { who: 'world' }), 'hello world');
});

test('French counts 0 and 1 as singular', () => {
  const fr = dict('fr');
  i18n.use({ locale: 'fr-FR', n: { one: '{n} langue', other: '{n} langues' } }, 'fr');
  assert.equal(i18n.t('n', { n: 0 }), '0 langue');
  assert.equal(i18n.t('n', { n: 1.5 }), '1.5 langue');
  assert.equal(i18n.t('n', { n: 2 }), '2 langues');
  assert.equal(fr.locale, 'fr-FR');
});

test('label falls back to English, the lead language, any label, then the QID', () => {
  i18n.use(dict('fr'), 'fr');
  assert.equal(i18n.label({ qid: 'Q1', labels: { fr: 'Paris', en: 'Paris (en)' } }), 'Paris');
  assert.equal(i18n.label({ qid: 'Q1', labels: { en: 'London', ja: 'ロンドン' }, lead: 'ja' }), 'London');
  assert.equal(i18n.label({ qid: 'Q1', labels: { ja: 'ロンドン', de: 'London' }, lead: 'ja' }), 'ロンドン');
  assert.equal(i18n.label({ qid: 'Q1', labels: { de: 'London' }, lead: 'ja' }), 'London');
  assert.equal(i18n.label({ qid: 'Q1' }), 'Q1');
});

test('desc uses the interface language, then English, then an empty string', () => {
  i18n.use(dict('es'), 'es');
  assert.equal(i18n.desc({ desc: { es: 'cantante', en: 'singer' } }), 'cantante');
  assert.equal(i18n.desc({ desc: { en: 'singer' } }), 'singer');
  assert.equal(i18n.desc({}), '');
});

test('day and hour format in UTC in the interface locale', () => {
  i18n.use(dict('en'), 'en');
  assert.equal(i18n.day('2026-08-17'), '17 August');
  assert.equal(i18n.hour('2026-08-17T23:00:00Z'), '23:00');
  i18n.use(dict('fr'), 'fr');
  assert.equal(i18n.day('2026-08-17'), '17 août');
  i18n.use(dict('es'), 'es');
  assert.equal(i18n.day('2026-08-17'), '17 de agosto');
});

test('num and pct follow the locale', () => {
  i18n.use(dict('en'), 'en');
  assert.equal(i18n.num(1234567), '1,234,567');
  assert.equal(i18n.pct(0.266), '27%');
  i18n.use(dict('fr'), 'fr');
  assert.equal(i18n.num(1234567).replace(/\s/g, ' '), '1 234 567');
  assert.match(i18n.pct(0.5), /^50\s%$/);
});

test('langNative adds the native name only when it differs', () => {
  i18n.use(dict('en'), 'en');
  assert.equal(i18n.langNative('en'), 'English');
  assert.equal(i18n.langNative('ja'), 'Japanese (日本語)');
  i18n.use(dict('fr'), 'fr');
  assert.equal(i18n.langNative('fr'), 'français');
});

test('initialLang prefers the stored choice, then a supported browser language, then English', (t) => {
  const store = {};
  globalThis.localStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; } };
  t.after(() => { delete globalThis.localStorage; });
  t.mock.getter(globalThis.navigator, 'languages', () => ['de-DE', 'es-MX', 'en-US']);
  assert.equal(i18n.initialLang(), 'es');
  store.lookedup_lang = 'fr';
  assert.equal(i18n.initialLang(), 'fr');
  store.lookedup_lang = 'xx';
  assert.equal(i18n.initialLang(), 'es');
});
