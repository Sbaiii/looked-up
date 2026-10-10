// F4 gender-aware briefing in EN/FR/ES (ADR 0026), run with `npm run test:unit`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as i18n from '../../../app/js/i18n.js';
import { compose } from '../../../app/js/briefing.js';

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
