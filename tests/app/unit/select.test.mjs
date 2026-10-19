// F1 hero rule (ADR 0024), run with `npm run test:unit`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { pick, pickDay, pickHero, rank } from '../../../app/js/select.js';

const fx = JSON.parse(readFileSync(new URL('./hero-fixtures.json', import.meta.url)));
const now = Date.parse(fx.now);

test('ranks by excess views, then breadth; single-language events never rank', () => {
  assert.deepEqual(rank(fx.busy_day).map((e) => e.qid), ['Q8', 'Q7', 'Q6']);
  assert.ok(!rank(fx.quiet_day).some((e) => e.qid === 'Q3'));
});

test('a quiet day has no qualifying hero in 24 h', () => {
  assert.equal(pick(fx.quiet_day), null);
  assert.equal(pickDay(fx.quiet_day).qid, 'Q2');     // the day view still selects its top event
});

test('widens to 48 h, then to the week', async () => {
  const windows = { 24: fx.quiet_day, 48: [...fx.quiet_day, ...fx.yesterday], 168: [...fx.quiet_day, ...fx.yesterday, ...fx.last_week] };
  const r = await pickHero(async (h) => windows[h], now);
  assert.deepEqual([r.event.qid, r.hours], ['Q4', 48]);        // international tier qualifies
  const noYesterday = { 24: fx.quiet_day, 48: fx.quiet_day, 168: [...fx.quiet_day, ...fx.last_week] };
  const w = await pickHero(async (h) => noYesterday[h], now);
  assert.deepEqual([w.event.qid, w.hours], ['Q5', 168]);       // >= 100,000 excess views qualifies
  const none = await pickHero(async () => fx.quiet_day, now);
  assert.deepEqual([none.event, none.hours], [null, 24]);
});

test('a busy day picks the biggest qualifying event at once', async () => {
  const r = await pickHero(async () => fx.busy_day, now);
  assert.deepEqual([r.event.qid, r.hours], ['Q8', 24]);
});

test('qualifies on excess views or a strong tier', async () => {
  const { qualifies, HERO_MIN_EXCESS } = await import('../../../app/js/select.js');
  assert.ok(qualifies({ excess: HERO_MIN_EXCESS, tier: 'noticed' }));
  assert.ok(qualifies({ excess: 0, tier: 'international' }) && qualifies({ excess: 0, tier: 'planetary' }));
  assert.ok(!qualifies({ excess: HERO_MIN_EXCESS - 1, tier: 'noticed' }));
});

test('ties break on breadth, then id', () => {
  const e = (id, excess, breadth) => ({ id, excess, breadth, class: 'multi_language' });
  assert.deepEqual(rank([e('b', 10, 2), e('a', 10, 2), e('c', 10, 5)]).map((x) => x.id), ['c', 'a', 'b']);
  assert.deepEqual(rank(null), []);
});

test('events older than the window are ignored', async () => {
  const now = Date.parse('2026-08-17T12:00:00Z');
  const old = { id: 'x', qid: 'Q1', excess: 1e6, breadth: 9, tier: 'international', class: 'multi_language', start: '2026-08-10T00:00:00Z' };
  const r = await pickHero(async () => [old], now);
  assert.deepEqual([r.event, r.hours], [null, 24]);
});

test('windows are requested in order and the search stops at the first hero', async () => {
  const { WINDOWS } = await import('../../../app/js/select.js');
  const asked = [];
  const windows = { 24: fx.quiet_day, 48: [...fx.quiet_day, ...fx.yesterday] };
  await pickHero((h) => { asked.push(h); return windows[h] || []; }, now);      // a plain (non-async) callback works too
  assert.deepEqual(asked, [24, 48]);
  asked.length = 0;
  await pickHero((h) => { asked.push(h); return []; }, now);
  assert.deepEqual(asked, WINDOWS);
});

test('pickDay and pick return null on an empty or missing day', () => {
  assert.equal(pickDay([]), null);
  assert.equal(pickDay(undefined), null);
  assert.equal(pick(null), null);
});
