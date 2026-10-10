import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
import { addEdit, counted, distinct, emptyState, isMaintenance, LANGUAGES, liveEvents, livePayload, RULES,
  statsPayload, countLive, windowCounts, type Burst, type RC } from '../src/core';

const T0 = 1_791_000_000;
const SALT = 'test-salt';
const rc = (title: string, dt: number, user: string, type = 'edit', extra: Partial<RC> = {}): RC =>
  ({ title, timestamp: new Date((T0 + dt) * 1000).toISOString(), user, type, ...extra });

describe('shared rules', () => {
  it('rules.json matches config/live.yml and languages match the Python package', () => {
    const yml = parse(readFileSync(new URL('../../config/live.yml', import.meta.url), 'utf8'));
    expect(RULES).toEqual(yml);
    const py = JSON.parse(readFileSync(new URL('../../live/lookedup_live/languages.json', import.meta.url), 'utf8'));
    expect(LANGUAGES).toEqual(py);
    expect(RULES.new_article.editors).toBe(2);
    expect(RULES.live_event_window_minutes).toBe(120);
  });
});

describe('filters', () => {
  it('drops bots, other types, reverts and maintenance comments', () => {
    expect(counted(rc('X', 0, 'a'))).toBe(true);
    expect(counted(rc('X', 0, 'a', 'categorize'))).toBe(false);
    expect(counted(rc('X', 0, 'a', 'edit', { bot: true }))).toBe(false);
    expect(counted(rc('X', 0, 'a', 'edit', { tags: ['mw-reverted'] }))).toBe(false);
    for (const c of ['Reverted edits by X', 'Undid revision 123', 'rv vandalism', 'fix typo', 'using AWB', '{{Orphan}}']) {
      expect(isMaintenance(c), c).toBe(true);
    }
    expect(isMaintenance('Added death date and source')).toBe(false);
  });
});

describe('editor sketch', () => {
  it('estimates small distinct counts and never stores names', () => {
    const s = emptyState();
    for (const [dt, u] of [[0, 'alice'], [60, 'bob'], [120, 'alice'], [180, 'carol']] as const) addEdit(s, 'en', rc('X', dt, u), SALT);
    const w = windowCounts(s.articles['en|X'], T0 + 180, 30);
    expect(w.edits).toBe(4);
    expect(w.editors).toBe(3);
    expect(JSON.stringify(s)).not.toMatch(/alice|bob|carol/);
    expect(distinct([0, 3])).toBe(2);
    expect(distinct([1, 0])).toBe(1);
  });
});

describe('burst rule', () => {
  it('needs 5 edits by 3 editors in 30 minutes, then cools down', () => {
    const s = emptyState();
    const out = ['a', 'a', 'b', 'b', 'b'].map((u, i) => addEdit(s, 'en', rc('X', 60 * i, u), SALT));
    expect(out.every((b) => b === null)).toBe(true);
    const b = addEdit(s, 'en', rc('X', 360, 'c'), SALT);
    expect(b?.kind).toBe('window');
    expect(b?.edits_30m).toBe(6);
    expect(addEdit(s, 'en', rc('X', 400, 'd'), SALT)).toBeNull();
  });

  it('a busy wiki baseline raises the bar', () => {
    const s = emptyState();
    s.medians.en = Array(30).fill(4);
    const out = 'abcdefghijklmnop'.split('').map((u, i) => addEdit(s, 'en', rc('X', 60 * i, u), SALT));
    expect(out.findIndex((b) => b !== null)).toBe(15);
  });

  it('new-article bursts need two distinct editors (ADR 0032)', () => {
    const s = emptyState();
    addEdit(s, 'fr', rc('Solo', 0, 'a', 'new'), SALT);
    for (let i = 1; i < 6; i++) expect(addEdit(s, 'fr', rc('Solo', 600 * i, 'a'), SALT)).toBeNull();
    addEdit(s, 'fr', rc('Duo', 0, 'a', 'new'), SALT);
    const res = ['a', 'b', 'a', 'b'].map((u, i) => addEdit(s, 'fr', rc('Duo', 600 * (i + 1), u), SALT));
    expect(res[3]?.kind).toBe('new');
  });
});

describe('grouping and payloads', () => {
  const mk = (lang: string, dt: number, qid: string | null, editors = 3, edits = 5): Burst =>
    ({ lang, title: `t-${lang}`, ts: T0 + dt, kind: 'window', edits_30m: edits, editors_30m: editors, qid });

  it('a live event needs two languages within 120 minutes', () => {
    const ev = liveEvents([mk('en', 0, 'Q1'), mk('fr', 1700, 'Q1'), mk('de', 0, 'Q2'), mk('es', 7000, 'Q2'),
      mk('ja', 0, 'Q3'), mk('ja', 100, 'Q3'), mk('pt', 0, 'Q4'), mk('pl', 7300, 'Q4')]);
    expect(ev.map((e) => e.qid).sort()).toEqual(['Q1', 'Q2']);
  });

  it('ranks single bursts by editors then edits, top 5, and counts live events per hour', () => {
    const s = emptyState();
    const now = T0 + 3600;
    s.bursts = [mk('en', 3000, null, 3, 9), mk('fr', 3100, null, 5, 5), mk('de', 3200, null, 3, 6), mk('it', 3300, null, 3, 5),
      mk('nl', 3310, null, 3, 5), mk('sv', 3320, null, 3, 5), mk('es', 3400, 'Q9'), mk('pt', 3500, 'Q9')];
    s.polledAt = now; s.groupPolledAt = { 0: now, 1: now }; s.coveredSince = now - 7200;
    const live = livePayload(s, now);
    expect(live.events.map((e) => e.qid)).toEqual(['Q9']);
    expect(live.single_language_bursts.map((b) => b.lang).slice(0, 3)).toEqual(['fr', 'en', 'de']);
    expect(live.single_language_bursts).toHaveLength(5);
    expect(live.status.gap_minutes).toBe(0);
    countLive(s, now);
    const st = statsPayload(s, now);
    expect(st.live_events_24h).toBe(1);
    expect(Object.values(st.live_events_per_hour_week).reduce((a, b) => a + b, 0)).toBe(1);
  });

  it('reports a gap when polling stopped (the host slept)', () => {
    const s = emptyState();
    s.polledAt = T0; s.groupPolledAt = { 0: T0, 1: T0 }; s.coveredSince = T0 - 7200;
    expect(livePayload(s, T0 + 3 * 3600).status.gap_minutes).toBe(60);
    expect(livePayload(emptyState(), T0).status.gap_minutes).toBe(60);
  });
});

describe('replay', () => {
  it('feeds the 60-second sample through the pipeline', () => {
    const lines = readFileSync(new URL('../../tests/fixtures/recentchange_60s.jsonl', import.meta.url), 'utf8').trim().split('\n');
    const s = emptyState();
    const wikis = new Map((LANGUAGES as string[]).map((l) => [`${l.replace(/-/g, '_')}wiki`, l]));
    let kept = 0;
    for (const line of lines) {
      const e = JSON.parse(line);
      const lang = wikis.get(e.wiki);
      if (!lang || e.namespace !== 0) continue;
      const row: RC = { title: e.title, timestamp: new Date(e.timestamp * 1000).toISOString(), user: e.user, type: e.type, comment: e.comment, bot: e.bot };
      if (!counted(row)) continue;
      kept++;
      addEdit(s, lang, row, SALT);
    }
    expect(lines.length).toBeGreaterThan(100);
    expect(kept).toBeGreaterThan(0);
    expect(kept).toBeLessThan(lines.length);
    const live = livePayload(s, JSON.parse(lines.at(-1)!).timestamp);
    expect(live.schema_version).toBe(1);
  });
});

describe('CPU budget (ADR 0032 fallback)', () => {
  it('six groups: English alone, 29 wikis balanced, one group per minute', async () => {
    const { groupAt } = await import('../src/index');
    const { GROUPS } = await import('../src/core');
    const at = (min: number) => groupAt(Date.UTC(2026, 9, 10, 12, min));
    expect([0, 1, 5, 6, 59].map(at)).toEqual([0, 1, 5, 0, 5]);
    expect(GROUPS.length).toBe(6);
    expect(GROUPS[0]).toEqual(['en']);
    expect(new Set(GROUPS.flat())).toEqual(new Set(LANGUAGES as string[]));
    expect(GROUPS.flat().length).toBe(30);
  });

  it('slot rows and the meta row round-trip the window state; the hourly baseline comes from the slots', async () => {
    const { encodeSlot, encodeMeta, decodeState, rollHours, SLOT_S } = await import('../src/core');
    const s = emptyState();
    const h0 = Math.floor(T0 / 3600) * 3600;
    // hour 1: article A 3 edits, B 1 edit -> median 2
    for (const [dt, u] of [[60, 'alice'], [120, 'bob'], [700, 'carol']] as const) addEdit(s, 'en', rc('A', h0 - T0 + dt, u), SALT);
    addEdit(s, 'en', rc('B', h0 - T0 + 900, 'dave', 'new'), SALT);
    s.hour = Math.floor(h0 / 3600);
    const rows = [...s.touched!].map((s0) => ({ s: s0, data: encodeSlot(s, s0) }));
    const back = decodeState(encodeMeta(s, h0 + 1000), rows);
    expect(back.articles['en|A'].sl.map((x) => x[1])).toEqual(s.articles['en|A'].sl.map((x) => x[1]));
    expect(back.articles['en|B'].c).toBe(h0 + 900);                          // creation kept in the meta extras
    expect(JSON.stringify(back)).not.toMatch(/alice|bob|carol|dave/);
    rollHours(back, h0 + 3600 + 60);
    expect(back.medians.en).toEqual([2]);
    expect(rows.every((r) => r.s % SLOT_S === 0)).toBe(true);
    expect(decodeState('{"v":5}', rows).articles).toEqual({});                // outdated meta: fresh state
  });

  it('a busy poll stays cheap: 1,300 edits processed quickly, compact state', () => {
    const s = emptyState();
    const t0 = performance.now();
    for (let i = 0; i < 1300; i++) addEdit(s, 'en', rc(`Page ${i % 900}`, i, `u${i % 400}`), SALT);
    const ms = performance.now() - t0;
    const bytes = JSON.stringify(s).length;
    expect(ms).toBeLessThan(50);              // local proxy; the Worker budget is checked with `worker-observe.yml`
    expect(bytes).toBeLessThan(120_000);
  });
});
