// The keyboard shortcut rules (app/js/keys.js), run with `npm run test:unit`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { keyAction } from '../../../app/js/keys.js';

test('each shortcut maps to its action', () => {
  const act = (key) => keyAction({ key });
  assert.deepEqual(['ArrowLeft', 'ArrowRight', 't', 'T', 'j', 'k', '/'].map(act),
    ['prev-day', 'next-day', 'today', 'today', 'next-event', 'prev-event', 'search']);
  assert.equal(act('x'), null);
  assert.equal(act('Escape'), null);
});
