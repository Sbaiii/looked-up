// F4 gender-aware briefing in EN/FR/ES (ADR 0026), run with `npm run test:unit`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as i18n from '../../../app/js/i18n.js';
import { compose, leadEvent, leadKey } from '../../../app/js/briefing.js';

const dict = (code) => JSON.parse(readFileSync(new URL(`../../../app/i18n/${code}.json`, import.meta.url)));
const dolly = (gender) => ({
  id: 'Q180453@20260825T17', qid: 'Q180453', start: '2026-08-25T17:00Z', class: 'multi_language', tier: 'planetary',
  breadth: 29, lead: 'en', category: 'death', excess: 10452570, spread_h: 7, labels: { en: 'Dolly Parton' },
  desc: { en: 'American singer-songwriter and actress' }, ...(gender ? { gender } : {}), langs: [],
});
const day = (gender) => ({ events: [dolly(gender)] });

const expected = {
  en: {
    female: 'On 25 August the world looked up Dolly Parton after the news of her death: 29 languages in 7 hours, led by English; 10.5 million more views than usual.',
    male: 'On 25 August the world looked up Dolly Parton after the news of his death: 29 languages in 7 hours, led by English; 10.5 million more views than usual.',
    unknown: "On 25 August, after the news of Dolly Parton's death, attention spread to 29 languages in 7 hours, led by English; 10.5 million more views than usual.",
  },
  fr: {
    female: "Le 25 août, le monde s'est intéressé à Dolly Parton, tout juste disparue : 29 langues en 7 heures, d'abord en anglais ; 10,5 millions de consultations de plus que d'habitude.",
    male: "Le 25 août, le monde s'est intéressé à Dolly Parton, tout juste disparu : 29 langues en 7 heures, d'abord en anglais ; 10,5 millions de consultations de plus que d'habitude.",
    unknown: "Le 25 août, après l'annonce du décès de Dolly Parton, l'attention s'est propagée à 29 langues en 7 heures, d'abord en anglais ; 10,5 millions de consultations de plus que d'habitude.",
  },
  es: {
    female: 'El 25 de agosto el mundo se fijó en Dolly Parton, recién fallecida: 29 idiomas en 7 horas, primero en inglés; 10,5 millones de visitas más de lo habitual.',
    male: 'El 25 de agosto el mundo se fijó en Dolly Parton, recién fallecido: 29 idiomas en 7 horas, primero en inglés; 10,5 millones de visitas más de lo habitual.',
    unknown: 'El 25 de agosto, tras la noticia de la muerte de Dolly Parton, la atención se extendió a 29 idiomas en 7 horas, primero en inglés; 10,5 millones de visitas más de lo habitual.',
  },
};

for (const code of ['en', 'fr', 'es']) {
  for (const [gender, value] of [['female', 'female'], ['male', 'male'], ['unknown', null], ['non-binary', 'other']]) {
    test(`${code}: death sentence for ${gender}`, () => {
      i18n.use(dict(code), code);
      const want = expected[code][gender === 'non-binary' ? 'unknown' : gender];
      assert.equal(compose(day(value), '2026-08-25').text.replace(/ | /g, ' '), want);
    });
  }
}

test('the description is shown with the label, English as fallback', () => {
  i18n.use(dict('fr'), 'fr');
  assert.equal(compose(day('female'), '2026-08-25').about, 'Dolly Parton : American singer-songwriter and actress.');
});

test('a day without events is a quiet day', () => {
  i18n.use(dict('en'), 'en');
  const b = compose({ events: [] }, '2026-08-25');
  assert.equal(b.text, 'A quiet day: no event spread to two languages.');
  assert.deepEqual([b.facts, b.top], [[], null]);
});

test('excess views: millions from a million up, the exact number below', async () => {
  const { excessPhrase } = await import('../../../app/js/briefing.js');
  i18n.use(dict('en'), 'en');
  assert.equal(excessPhrase(10452570), '10.5 million more views than usual');
  assert.equal(excessPhrase(19371), '19,371 more views than usual');
});

test('facts: fastest wide event, widest, biggest not led by English', async () => {
  const { facts } = await import('../../../app/js/briefing.js');
  i18n.use(dict('en'), 'en');
  const ev = (qid, breadth, spread_h, lead, excess) => ({ id: `${qid}@x`, qid, class: 'multi_language', breadth, spread_h,
    lead, excess, labels: { en: qid }, langs: [] });
  const out = facts([ev('A', 29, 7, 'en', 9e6), ev('B', 6, 0, 'en', 1e5), ev('C', 5, 2, 'ja', 2e6)]);
  assert.deepEqual(out.map(([k, , e]) => [k, e.qid]), [['fastest', 'B'], ['widest', 'A'], ['non_english', 'C']]);
});

test('plural forms: zero, one and other', () => {
  i18n.use(dict('en'), 'en');
  assert.deepEqual([0, 1, 5].map(i18n.within), ['under an hour', '1 hour', '5 hours']);
  assert.equal(i18n.t('event.languages', { n: 1 }), '1 language');
  assert.equal(i18n.t('event.languages', { n: 29 }), '29 languages');
  assert.equal(i18n.t('no.such.key'), 'no.such.key');                 // a missing key shows itself, never blank
});

test('leadKey picks the death sentence by gender and the plain sentence otherwise', () => {
  assert.equal(leadKey({ category: 'sports' }), 'briefing.lead');
  assert.equal(leadKey({ category: 'sports', gender: 'female' }), 'briefing.lead');
  assert.equal(leadKey({ category: 'death', gender: 'female' }), 'briefing.lead_death_female');
  assert.equal(leadKey({ category: 'death', gender: 'male' }), 'briefing.lead_death_male');
  assert.equal(leadKey({ category: 'death', gender: 'other' }), 'briefing.lead_death_neutral');
  assert.equal(leadKey({ category: 'death' }), 'briefing.lead_death_neutral');
});
