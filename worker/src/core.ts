// Live layer core (ADR 0032): pure functions, no I/O, so vitest can exercise them. Rules come from
// config/live.yml (src/rules.json), the same file the Python reference implementation (live/) reads.
//
// The Worker polls recentchanges every few minutes, so edits are kept per article in 5-minute slots. A slot holds
// the edit count and a 64-bit bitmap of salted editor hashes, as two 32-bit numbers (an irreversible sketch, never
// a user id); distinct editors over a window are estimated from the OR of the bitmaps (linear counting).

import RULES from './rules.json';
import LANGUAGES from './languages.json';
import GROUP_FILE from './groups.json';

export { RULES, LANGUAGES };

export const SLOT_S = 300;
const WIN = (m: number) => m * 60;
const MAINTENANCE = new RegExp(RULES.maintenance_patterns.join('|'), 'i');
const REVERT_TAGS = new Set<string>(RULES.revert_tags);

export interface RC { title: string; timestamp: string; user?: string; type: string; comment?: string; tags?: string[]; bot?: boolean; minor?: boolean }
/** [slot start (epoch s), edits, bitmap high 32 bits, bitmap low 32 bits]: compact for KV and cheap to parse. */
export type Slot = [number, number, number, number];
export interface Article { sl: Slot[]; c?: number; cb?: [number, number]; ce?: number; lb?: number }   // created, its bits, its edits, last burst
/** Per-group summary row (ADR 0033): what /health, /stats.json and /live.json need, never the full state. */
export interface Summary {
  pa: number; gp: Record<string, number>; gs: State['groupStats']; cs: number | null; lp: number;
  counts: Record<string, [number, number, number, number]>;   // recent bursters: edits 10/30/60 min, editors 30 min
}
export interface Burst { lang: string; title: string; ts: number; kind: 'window' | 'new'; edits_30m: number; editors_30m: number; qid: string | null }
export interface Item { labels: Record<string, string>; desc: Record<string, string> }
export interface State {
  version: 6;
  articles: Record<string, Article>;          // "lang|title"
  bursts: Burst[];
  hour: number | null;
  medians: Record<string, number[]>;                     // lang -> hourly medians (last 7 days)
  lastPoll: Record<string, number>;                      // lang -> newest edit time processed
  polledAt: number | null;                               // last poll of any group
  groupPolledAt: Record<string, number>;                 // per cron group (ADR 0032 fallback: wikis split in two)
  groupStats: Record<string, { fetched: number; kept: number; seconds: number; languages: string[] }>;
  coveredSince: number | null;
  qids: Record<string, string | null>;                   // "lang|title" -> QID
  items: Record<string, Item>;
  liveSeen: Record<string, string>;                      // "qid|ts" -> hour key (a week of live-event counts)
  touched?: Set<number>;                                 // slot starts written by this poll (not persisted)
  counts?: Record<string, [number, number, number, number]>;   // read path: counts from the summaries
}

export function emptyState(): State {
  return { version: 6, articles: {}, bursts: [], hour: null, medians: {}, lastPoll: {}, polledAt: null,
    groupPolledAt: {}, groupStats: {}, coveredSince: null, qids: {}, items: {}, liveSeen: {} };
}

// ------------------------------------------------------------------ filters

export function isMaintenance(comment?: string): boolean {
  return !!comment && MAINTENANCE.test(comment);
}

/** The pre-registered filter for API recentchanges rows (rcshow=!bot already excludes flagged bots). */
export function counted(rc: RC): boolean {
  if (rc.bot) return false;
  if (rc.type !== 'edit' && rc.type !== 'new') return false;
  if ((rc.tags || []).some((t) => REVERT_TAGS.has(t))) return false;
  return !isMaintenance(rc.comment);
}

// ------------------------------------------------------------------ editor sketch

function fnv(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h;
}

/** FNV-1a of salt + user folded to a bit index 0..63. The user name is never stored. */
export function editorBit(user: string | undefined, salt: string): number | null {
  return user ? fnv(salt + '\u0000' + user) % 64 : null;
}

export function setBit(bits: [number, number], bit: number): [number, number] {
  return bit < 32 ? [bits[0], (bits[1] | (1 << bit)) >>> 0] : [(bits[0] | (1 << (bit - 32))) >>> 0, bits[1]];
}

function pop32(x: number): number {
  x -= (x >>> 1) & 0x55555555;
  x = (x & 0x33333333) + ((x >>> 2) & 0x33333333);
  return (Math.imul((x + (x >>> 4)) & 0x0f0f0f0f, 0x01010101) >>> 24);
}

/** Linear-counting estimate of distinct editors from a 64-bit bitmap given as [high, low]. */
export function distinct(bits: [number, number]): number {
  const ones = pop32(bits[0]) + pop32(bits[1]);
  if (ones >= 64) return 64;
  return Math.round(-64 * Math.log(1 - ones / 64));
}

// ------------------------------------------------------------------ windows, baselines, bursts

export function windowEdits(a: Article, t: number, minutes: number): number {
  const lo = t - WIN(minutes);
  let n = 0;
  for (const sl of a.sl) if (sl[0] + SLOT_S > lo && sl[0] <= t) n += sl[1];
  return n;
}

export function windowCounts(a: Article, t: number, minutes: number): { edits: number; editors: number } {
  const lo = t - WIN(minutes);
  let edits = 0; let hi = 0; let low = 0;
  for (const sl of a.sl) if (sl[0] + SLOT_S > lo && sl[0] <= t) { edits += sl[1]; hi = (hi | sl[2]) >>> 0; low = (low | sl[3]) >>> 0; }
  return { edits, editors: distinct([hi, low]) };
}

export function baseline(state: State, lang: string): number {
  const m = state.medians[lang] || [];
  if (m.length < RULES.baseline.min_hours) return RULES.baseline.default;
  return median(m);
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const k = s.length >> 1;
  return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2;
}

/** Hourly baseline from the slots (ADR 0033): for each completed hour since the last roll whose slots are loaded,
 * the median edits per edited article, per wiki. Called once at the end of a poll. */
export function rollHours(state: State, now: number): void {
  const h = Math.floor(now / 3600);
  if (state.hour === null) { state.hour = h; return; }
  for (let hour = state.hour; hour < h; hour++) {
    const per: Record<string, number[]> = {};
    for (const [key, a] of Object.entries(state.articles)) {
      let n = 0;
      for (const sl of a.sl) if (Math.floor(sl[0] / 3600) === hour) n += sl[1];
      if (n) (per[key.slice(0, key.indexOf('|'))] ||= []).push(n);
    }
    for (const [lang, vals] of Object.entries(per)) {
      const m = (state.medians[lang] ||= []);
      m.push(median(vals));
      if (m.length > RULES.baseline.hours) m.splice(0, m.length - RULES.baseline.hours);
    }
  }
  state.hour = h;
}

/** Count one edit; return a Burst when it makes the article burst (same rules as live/lookedup_live/bursts.py). */
export function addEdit(state: State, lang: string, rc: RC, salt: string, ts?: number): Burst | null {
  const t = ts ?? Date.parse(rc.timestamp) / 1000;
  const key = `${lang}|${rc.title}`;
  const a = (state.articles[key] ||= { sl: [] });
  const s0 = t - (t % SLOT_S);
  const lastSlot = a.sl[a.sl.length - 1];
  let slot = lastSlot && lastSlot[0] === s0 ? lastSlot : a.sl.find((x) => x[0] === s0);   // rows arrive in time order
  if (!slot) {
    slot = [s0, 0, 0, 0];
    if (!lastSlot || lastSlot[0] < s0) a.sl.push(slot); else { a.sl.push(slot); a.sl.sort((x, y) => x[0] - y[0]); }
  }
  (state.touched ||= new Set()).add(s0);           // this slot's row is rewritten at the end of the poll
  slot[1] += 1;
  const bit = editorBit(rc.user, salt);
  if (bit !== null) [slot[2], slot[3]] = setBit([slot[2], slot[3]], bit);
  if (rc.type === 'new') { a.c = t; a.ce = 0; a.cb = [0, 0]; }
  if (a.c !== undefined && t - a.c <= WIN(RULES.new_article.window_minutes)) {
    a.ce = (a.ce || 0) + 1;
    if (bit !== null) a.cb = setBit(a.cb || [0, 0], bit);
  }
  if (a.lb !== undefined && t - a.lb < RULES.cooldown_hours * 3600) return null;
  let kind: Burst['kind'] | null = null;
  let w = { edits: windowEdits(a, t, RULES.burst.window_minutes), editors: 0 };
  // editors only matter once the edit count qualifies: most articles never get there, so skip the sketch work
  if (w.edits >= RULES.burst.edits && 2 * w.edits >= RULES.burst.ratio * baseline(state, lang)) {
    w = windowCounts(a, t, RULES.burst.window_minutes);
    if (w.editors >= RULES.burst.editors) kind = 'window';
  }
  if (!kind && a.c !== undefined && t - a.c <= WIN(RULES.new_article.window_minutes)
      && (a.ce || 0) >= RULES.new_article.edits && distinct(a.cb || [0, 0]) >= RULES.new_article.editors) {
    kind = 'new';                          // ADR 0032: >= 2 distinct editors
    if (!w.editors) w = windowCounts(a, t, RULES.burst.window_minutes);
  }
  if (!kind) return null;
  a.lb = t;
  const b: Burst = { lang, title: rc.title, ts: t, kind, edits_30m: w.edits, editors_30m: w.editors, qid: state.qids[key] ?? null };
  state.bursts.push(b);
  return b;
}

export function gc(state: State, now: number): void {
  for (const [k, a] of Object.entries(state.articles)) {
    a.sl = a.sl.filter((x) => x[0] + SLOT_S > now - WINDOW_LOAD_S);
    const cooled = a.lb === undefined || now - a.lb > RULES.cooldown_hours * 3600;
    const fresh = a.c !== undefined && now - a.c <= WIN(RULES.new_article.window_minutes);
    if (!a.sl.length && cooled && !fresh) delete state.articles[k];
  }
  state.bursts = state.bursts.filter((b) => b.ts >= now - RULES.keep_bursts_hours * 3600);
  const keep = new Set(state.bursts.map((b) => b.qid).filter(Boolean));
  for (const q of Object.keys(state.items)) if (!keep.has(q)) delete state.items[q];
  const burstKeys = new Set(state.bursts.map((b) => `${b.lang}|${b.title}`));
  for (const k of Object.keys(state.qids)) if (!burstKeys.has(k)) delete state.qids[k];
}

// ------------------------------------------------------------------ cron groups (CPU budget, ADR 0032)

/** Six poll groups (ADR 0033): English alone, the other 29 wikis balanced by measured edits per 5 minutes
 * (src/groups.json). One group runs per minute, so each wiki is polled every 6 minutes. */
export const GROUPS: string[][] = GROUP_FILE.groups;
export const GROUP_COUNT = GROUPS.length;

// ------------------------------------------------------------------ compact storage (ADR 0033)

export const WINDOW_LOAD_S = 70 * 60;            // slots loaded per poll: 60 min of windows + the previous full hour

/** One slot row: article keys written once, then a flat array [edits, bitsHigh, bitsLow] per key. */
export function encodeSlot(state: State, s0: number): string {
  const k: string[] = [];
  const v: number[] = [];
  for (const [key, a] of Object.entries(state.articles)) {
    const sl = a.sl.find((x) => x[0] === s0);
    if (sl) { k.push(key); v.push(sl[1], sl[2], sl[3]); }
  }
  return JSON.stringify({ k, v });
}

/** Group meta row: poll positions, baselines, coverage and the few per-article extras (creation, last burst). */
export function encodeMeta(state: State, now: number): string {
  const x: Record<string, number[]> = {};
  for (const [key, a] of Object.entries(state.articles)) {
    const fresh = a.c !== undefined && now - a.c <= WIN(RULES.new_article.window_minutes);
    const cooling = a.lb !== undefined && now - a.lb < RULES.cooldown_hours * 3600;
    if (fresh || cooling) x[key] = [a.c ?? -1, a.ce ?? 0, a.cb?.[0] ?? 0, a.cb?.[1] ?? 0, a.lb ?? -1];
  }
  return JSON.stringify({ v: state.version, h: state.hour, m: state.medians, lp: state.lastPoll, pa: state.polledAt,
    gp: state.groupPolledAt, gs: state.groupStats, cs: state.coveredSince, x });
}

/** Rebuild a group's working state from its meta row and slot rows (missing or outdated meta: a fresh state). */
export function decodeState(meta: string | null, slots: { s: number; data: string }[]): State {
  const st = emptyState();
  const m = meta ? JSON.parse(meta) : null;
  if (!m || m.v !== st.version) return st;
  Object.assign(st, { hour: m.h, medians: m.m, lastPoll: m.lp, polledAt: m.pa, groupPolledAt: m.gp, groupStats: m.gs, coveredSince: m.cs });
  for (const row of [...slots].sort((a, b) => a.s - b.s)) {
    const { k, v } = JSON.parse(row.data) as { k: string[]; v: number[] };
    for (let i = 0; i < k.length; i++) (st.articles[k[i]] ||= { sl: [] }).sl.push([row.s, v[3 * i], v[3 * i + 1], v[3 * i + 2]]);
  }
  for (const [key, e] of Object.entries(m.x as Record<string, number[]>)) {
    const a = (st.articles[key] ||= { sl: [] });
    if (e[0] >= 0) { a.c = e[0]; a.ce = e[1]; a.cb = [e[2], e[3]]; }
    if (e[4] >= 0) a.lb = e[4];
  }
  return st;
}

/** The group's summary row: status inputs plus 10/30/60-min counts of articles that burst in the last hour. */
export function summarize(state: State, now: number): Summary {
  const counts: Summary['counts'] = {};
  for (const [key, a] of Object.entries(state.articles)) {
    if (a.lb === undefined || now - a.lb > WIN(RULES.live_window_minutes)) continue;
    const w30 = windowCounts(a, now, 30);
    counts[key] = [windowEdits(a, now, 10), w30.edits, windowEdits(a, now, 60), w30.editors];
  }
  return { pa: state.polledAt ?? now, gp: state.groupPolledAt, gs: state.groupStats, cs: state.coveredSince,
    lp: Math.max(0, ...Object.values(state.lastPoll)), counts };
}

/** The read view from the summaries only (plus bursts and items added by the caller). */
export function fromSummaries(sums: Summary[]): State {
  const v = emptyState();
  v.counts = {};
  for (const s of sums) {                       // tolerant of partial rows (e.g. a group that has not polled yet)
    Object.assign(v.groupPolledAt, s.gp || {});
    Object.assign(v.groupStats, s.gs || {});
    Object.assign(v.counts, s.counts || {});
    if (s.pa) v.polledAt = Math.max(v.polledAt ?? 0, s.pa);
    if (s.cs != null) v.coveredSince = Math.max(v.coveredSince ?? 0, s.cs);
    if (s.lp) v.lastPoll[`g${Object.keys(s.gp || {})[0] ?? ''}`] = s.lp;
  }
  return v;
}

/** Merge the groups' states for reading (articles, bursts and caches are disjoint by wiki). */
export function merge(states: State[]): State {
  const m = emptyState();
  for (const s of states) {
    Object.assign(m.articles, s.articles);
    m.bursts.push(...s.bursts);
    Object.assign(m.medians, s.medians);
    Object.assign(m.lastPoll, s.lastPoll);
    Object.assign(m.groupPolledAt, s.groupPolledAt);
    Object.assign(m.groupStats, s.groupStats);
    Object.assign(m.qids, s.qids);
    Object.assign(m.items, s.items);
    if (s.polledAt !== null) m.polledAt = Math.max(m.polledAt ?? 0, s.polledAt);
    if (s.coveredSince !== null) m.coveredSince = Math.max(m.coveredSince ?? 0, s.coveredSince);
  }
  m.bursts.sort((a, b) => a.ts - b.ts);
  return m;
}

// ------------------------------------------------------------------ grouping and payloads

export interface LiveEvent { qid: string; ts: number; first_burst: number; languages: Record<string, Burst> }

/** A live event: the same QID bursting in >= 2 languages within the live-event window (120 min, ADR 0032). */
export function liveEvents(bursts: Burst[], windowS = WIN(RULES.live_event_window_minutes)): LiveEvent[] {
  const by = new Map<string, Burst[]>();
  for (const b of bursts) if (b.qid) (by.get(b.qid) || by.set(b.qid, []).get(b.qid)!).push(b);
  const out: LiveEvent[] = [];
  for (const [qid, bs] of by) {
    const first = new Map<string, Burst>();
    for (const b of [...bs].sort((x, y) => x.ts - y.ts)) if (!first.has(b.lang)) first.set(b.lang, b);
    const firsts = [...first.values()].sort((x, y) => x.ts - y.ts);
    for (let i = 1; i < firsts.length; i++) {
      if (firsts[i].ts - firsts[i - 1].ts <= windowS) {
        out.push({ qid, ts: firsts[i].ts, first_burst: firsts[0].ts, languages: Object.fromEntries(first) });
        break;
      }
    }
  }
  return out.sort((x, y) => y.ts - x.ts);
}

export const iso = (t: number | null) => (t === null ? null : new Date(t * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z'));
const hourKey = (t: number) => iso(t - (t % 3600))!.slice(0, 13);

export function status(state: State, now: number) {
  const window = WIN(RULES.live_window_minutes);
  const polls = Object.values(state.groupPolledAt);
  const oldest = polls.length ? Math.min(...polls) : null;      // every group must keep polling
  let gap = state.coveredSince === null ? 60 : Math.max(0, state.coveredSince - (now - window)) / 60;
  if (oldest !== null && now - oldest > 600) gap = Math.max(gap, Math.min(60, (now - oldest) / 60));
  const stats = Object.values(state.groupStats);
  const rate = (k: 'fetched' | 'kept') => Math.round(stats.reduce((n, g) => n + (g.seconds ? g[k] / g.seconds : 0), 0) * 100) / 100;
  return {
    host: 'cloudflare-worker', mode: 'poll', poll_minutes: GROUP_COUNT, cron_groups: polls.length,
    connected: oldest !== null && now - oldest <= 600,
    last_poll_at: iso(state.polledAt), last_event_at: iso(Math.max(0, ...Object.values(state.lastPoll)) || null),
    events_per_s: rate('fetched'), kept_per_s: rate('kept'),
    languages_seen: [...new Set(stats.flatMap((g) => g.languages))].sort(),
    covered_since: iso(state.coveredSince), gap_minutes: Math.round(gap),
  };
}

function counts(state: State, lang: string, title: string, now: number) {
  const c = state.counts?.[`${lang}|${title}`];
  if (c) return { edits_10m: c[0], edits_30m: c[1], edits_60m: c[2], editors_30m: c[3] };
  const a = state.articles[`${lang}|${title}`];
  if (!a) return { edits_10m: 0, edits_30m: 0, edits_60m: 0, editors_30m: 0 };
  const w30 = windowCounts(a, now, 30);
  return { edits_10m: windowCounts(a, now, 10).edits, edits_30m: w30.edits, edits_60m: windowCounts(a, now, 60).edits, editors_30m: w30.editors };
}

const UI = ['en', 'fr', 'es'];

export function livePayload(state: State, now: number) {
  const recent = state.bursts.filter((b) => b.ts > now - WIN(RULES.live_window_minutes));
  const events = liveEvents(recent).map((ev) => {
    const langs = Object.keys(ev.languages).sort((a, b) => ev.languages[a].ts - ev.languages[b].ts);
    const item = state.items[ev.qid] || { labels: {}, desc: {} };
    const labels: Record<string, string> = Object.fromEntries(Object.entries(item.labels).filter(([k]) => UI.includes(k) || langs.includes(k)));
    for (const l of langs) labels[l] ||= ev.languages[l].title.replace(/_/g, ' ');
    const desc = Object.fromEntries(Object.entries(item.desc).filter(([k]) => UI.includes(k)).map(([k, v]) => [k, v.slice(0, 80)]));
    return {
      qid: ev.qid, first_burst: iso(ev.first_burst), live_since: iso(ev.ts),
      minutes_since_first_burst: Math.round((now - ev.first_burst) / 60), breadth: langs.length, labels, desc,
      languages: langs.map((l) => ({ lang: l, title: ev.languages[l].title, first_burst: iso(ev.languages[l].ts), ...counts(state, l, ev.languages[l].title, now) })),
    };
  });
  const liveQids = new Set(events.map((e) => e.qid));
  // ADR 0032: rank single-language bursts by distinct editors, then edits; show the top 5
  const singles = recent.filter((b) => !b.qid || !liveQids.has(b.qid))
    .sort((a, b) => b.editors_30m - a.editors_30m || b.edits_30m - a.edits_30m || b.ts - a.ts)
    .slice(0, RULES.single_bursts_shown)
    .map((b) => ({ lang: b.lang, title: b.title, qid: b.qid, first_burst: iso(b.ts), kind: b.kind,
      editors_at_burst: b.editors_30m, edits_at_burst: b.edits_30m, ...counts(state, b.lang, b.title, now) }));
  return { schema_version: 1, generated_at: iso(now), window_minutes: RULES.live_window_minutes, status: status(state, now), events, single_language_bursts: singles };
}

export function countLive(state: State, now: number): void {
  for (const e of liveEvents(state.bursts)) state.liveSeen[`${e.qid}|${e.ts}`] ||= hourKey(e.ts);
  const cutoff = hourKey(now - RULES.hourly_counts_hours * 3600);
  for (const [k, h] of Object.entries(state.liveSeen)) if (h < cutoff) delete state.liveSeen[k];
}

export function statsPayload(state: State, now: number) {
  const day = state.bursts.filter((b) => b.ts > now - 86400);
  const tally = (keys: string[]) => keys.reduce<Record<string, number>>((m, k) => ((m[k] = (m[k] || 0) + 1), m), {});
  const dayCut = hourKey(now - 86400);
  const week = tally(Object.values(state.liveSeen));
  const live24 = Object.fromEntries(Object.entries(week).filter(([h]) => h >= dayCut));
  const perLang = Object.entries(tally(day.map((b) => b.lang))).sort((a, b) => b[1] - a[1]);
  return {
    schema_version: 1, generated_at: iso(now), status: status(state, now),
    bursts_per_hour: Object.fromEntries(Object.entries(tally(day.map((b) => hourKey(b.ts)))).sort()),
    live_events_per_hour: Object.fromEntries(Object.entries(live24).sort()),
    live_events_per_hour_week: Object.fromEntries(Object.entries(week).sort()),
    bursts_per_language: Object.fromEntries(perLang), bursts_24h: day.length,
    live_events_24h: Object.values(live24).reduce((a, b) => a + b, 0),
  };
}
