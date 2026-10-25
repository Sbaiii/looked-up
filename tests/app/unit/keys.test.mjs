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

test('nothing happens in a field or with Alt, Ctrl or Meta', () => {
  for (const key of ['ArrowLeft', 't', 'j', '/']) {
    assert.equal(keyAction({ key, inField: true }), null, key);
    assert.equal(keyAction({ key, altKey: true }), null, key);
    assert.equal(keyAction({ key, ctrlKey: true }), null, key);
    assert.equal(keyAction({ key, metaKey: true }), null, key);
  }
});

test('Escape in a non-empty search clears it, and does nothing elsewhere', () => {
  assert.equal(keyAction({ key: 'Escape', inField: true, inSearch: true }), 'clear-search');
  assert.equal(keyAction({ key: 'Escape', inField: true, inSearch: false }), null);
  assert.equal(keyAction({ key: 'Escape', inSearch: true, ctrlKey: true }), null);
});

test('J and K work in lower case only, T in both', () => {
  assert.equal(keyAction({ key: 'J' }), null);
  assert.equal(keyAction({ key: 'K' }), null);
  assert.equal(keyAction({ key: 'T' }), 'today');
});

test('ArrowUp, ArrowDown, Enter and Space have no shortcut', () => {
  for (const key of ['ArrowUp', 'ArrowDown', 'Enter', ' ', 'Tab']) assert.equal(keyAction({ key }), null, key);
});

test('Shift is not a blocking modifier', () => {
  assert.equal(keyAction({ key: '/', shiftKey: true }), 'search');
  assert.equal(keyAction({ key: 'T', shiftKey: true }), 'today');
});
