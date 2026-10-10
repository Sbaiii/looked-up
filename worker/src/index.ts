// Looked Up live layer on Cloudflare Workers (ADR 0032, storage ADR 0033).
//   Cron (every minute): minute m polls group m % 6 (en alone + 5 balanced groups), so each wiki is polled every
//                        6 minutes. A run loads its group's meta row and the last 70 minutes of slot rows from D1,
//                        applies the burst rules, resolves QIDs of new bursts (KV cache, then Wikidata), and writes
//                        back only the touched slots, its meta, its summary and the new bursts (one D1 batch).
//   HTTP: GET /live.json, /stats.json, /bursts.json, /health with CORS for every origin. Reads use the per-group
//         summary rows and the bursts table, never the full states; /live.json and /stats.json are also cached at
//         the edge (15 s) and in KV (5 min / 30 min).
// No user data is stored: editors become bits in a salted 64-bit sketch per 5-minute slot (core.ts).

import { addEdit, counted, countLive, decodeState, encodeMeta, encodeSlot, fromSummaries, gc, GROUP_COUNT, GROUPS, iso,
  livePayload, rollHours, statsPayload, status, summarize, WINDOW_LOAD_S, type Burst, type RC, type State, type Summary } from './core';
import { D1Repo, QidCache, type Repo } from './repo';

export interface Env { LIVE: KVNamespace; DB: D1Database; SALT?: string }

const UA = 'looked-up/0.1 (https://github.com/Sbaiii/looked-up; abdellahsbaisbai@gmail.com)';
const FIRST_LOOKBACK_S = 10 * 60;
const PAGES: Record<string, number> = { en: 3, de: 2, ja: 2, fr: 2, ru: 2, es: 2 };
const WIKIDATA_CALLS = 3;
const EDGE_CACHE_S = 15;
const KV_CACHE_S: Record<string, number> = { '/live.json': 300, '/stats.json': 1800 };
const KEEP_BURSTS_S = 7 * 86400;

/** Group polled at this scheduled minute: one group per minute, each every 5 minutes. */
export function groupAt(scheduledMs: number): number {
  return new Date(scheduledMs).getUTCMinutes() % GROUP_COUNT;
}

async function recentChanges(lang: string, since: number, pages: number): Promise<{ rows: RC[]; caughtUp: boolean }> {
  const api = `https://${lang}.wikipedia.org/w/api.php`;
  let params: Record<string, string> = {
    action: 'query', list: 'recentchanges', rcnamespace: '0', rcshow: '!bot', rctype: 'edit|new', rcdir: 'newer',
    rcprop: 'title|timestamp|user|comment|tags', rclimit: '500', rcstart: iso(since + 1)!, format: 'json', formatversion: '2',
  };
  const rows: RC[] = [];
  for (let i = 0; i < pages; i++) {
    const r = await fetch(`${api}?${new URLSearchParams(params)}`, { headers: { 'User-Agent': UA } });
    if (!r.ok) throw new Error(`${lang} ${r.status}`);
    const d = (await r.json()) as { query?: { recentchanges?: RC[] }; continue?: Record<string, string> };
    rows.push(...(d.query?.recentchanges || []));
    if (!d.continue) return { rows, caughtUp: true };
    params = { ...params, ...d.continue };
  }
  return { rows, caughtUp: false };
}

/** QIDs for new bursts: KV cache first, then Wikidata (at most WIKIDATA_CALLS per run); writes only new entries. */
export async function resolveQids(bursts: Burst[], cache: QidCache, fetcher: typeof fetch = fetch): Promise<void> {
  const todo = new Map<string, Burst[]>();
  for (const b of bursts) {
    const hit = await cache.get(b.lang, b.title);
    if (hit !== null) { b.qid = hit || null; continue; }
    (todo.get(b.lang) || todo.set(b.lang, []).get(b.lang)!).push(b);
  }
  let calls = 0;
  for (const [lang, bs] of todo) {
    if (calls++ >= WIKIDATA_CALLS) break;
    const site = `${lang.replace(/-/g, '_')}wiki`;
    const titles = [...new Set(bs.map((b) => b.title))].slice(0, 50);
    const q = new URLSearchParams({ action: 'wbgetentities', sites: site, titles: titles.join('|'), props: 'labels|descriptions|sitelinks',
      sitefilter: site, languages: [...new Set(['en', 'fr', 'es', lang])].join('|'), normalize: '1', format: 'json' });
    const r = await fetcher(`https://www.wikidata.org/w/api.php?${q}`, { headers: { 'User-Agent': UA } });
    if (!r.ok) continue;
    const d = (await r.json()) as { entities?: Record<string, any> };
    const found = new Map<string, string>();
    for (const [key, e] of Object.entries(d.entities || {})) {
      if (!key.startsWith('Q') || 'missing' in e) continue;
      const t = e.sitelinks?.[site]?.title;
      if (t) found.set(t, key);
      await cache.putItem(key, {
        labels: Object.fromEntries(Object.entries(e.labels || {}).map(([k, v]: [string, any]) => [k, v.value])),
        desc: Object.fromEntries(Object.entries(e.descriptions || {}).map(([k, v]: [string, any]) => [k, v.value])),
      });
    }
    for (const t of titles) {
      const qid = found.get(t) || found.get(t.replace(/_/g, ' ')) || null;
      await cache.putQid(lang, t, qid);
      for (const b of bs) if (b.title === t) b.qid = qid;
    }
  }
}

export async function poll(env: Env, now: number, group: number, repo: Repo = new D1Repo(env.DB)): Promise<State> {
  const win = await repo.loadWindow(group, now - WINDOW_LOAD_S);
  const state = decodeState(win.meta, win.slots);
  const salt = `${env.SALT || 'looked-up'}|${iso(now)!.slice(0, 10)}`;     // rotates daily
  const g = String(group);
  const last = state.groupPolledAt[g];
  const resumed = last !== undefined && now - last <= 900;
  let fetched = 0;
  let kept = 0;
  let earliest = now;
  const langs = new Set<string>();
  for (const lang of GROUPS[group]) {
    const since = resumed && state.lastPoll[lang] ? state.lastPoll[lang] : now - FIRST_LOOKBACK_S;
    earliest = Math.min(earliest, since);
    try {
      const { rows, caughtUp } = await recentChanges(lang, since, PAGES[lang] || 1);
      fetched += rows.length;
      let newest = since;
      for (const rc of rows) {
        const t = Date.parse(rc.timestamp) / 1000;
        newest = Math.max(newest, t);
        if (!counted(rc)) continue;
        kept += 1;
        langs.add(lang);
        addEdit(state, lang, rc, salt, t);
      }
      state.lastPoll[lang] = caughtUp ? Math.max(newest, now - 60) : newest;     // behind: resume where we stopped
    } catch {
      /* one wiki failing must not stop the others; it resumes from its lastPoll next time */
    }
  }
  if (!resumed) state.coveredSince = Math.max(state.coveredSince ?? 0, earliest);
  state.groupStats = { [g]: { fetched, kept, seconds: resumed ? now - last : FIRST_LOOKBACK_S, languages: [...langs].sort() } };
  state.groupPolledAt = { [g]: now };
  state.polledAt = now;
  rollHours(state, now);
  const newBursts = state.bursts;
  if (newBursts.length) await resolveQids(newBursts, new QidCache(env.LIVE));
  const touched = [...(state.touched || [])].map((s0) => ({ s: s0, data: encodeSlot(state, s0) }));
  const summary = summarize(state, now);
  gc(state, now);
  const meta = encodeMeta(state, now);
  const written = await repo.save({ g: group, now, meta, summary: JSON.stringify(summary), slots: touched,
    bursts: newBursts, dropBefore: now - WINDOW_LOAD_S });
  let pruned = 0;
  if (group === 0 && new Date(now * 1000).getUTCMinutes() < GROUP_COUNT) pruned = await repo.pruneBursts(now - KEEP_BURSTS_S);
  // one line per poll for `wrangler tail` (docs/ops.md): no titles, no users
  console.log(JSON.stringify({ poll: iso(now), group, fetched, kept, languages: langs.size, new_bursts: newBursts.length,
    slots_read: win.slots.length, bytes_read: win.slots.reduce((n, r) => n + r.data.length, 0) + (win.meta?.length ?? 0),
    slots_written: touched.length, meta_bytes: meta.length, d1_rows_written: written + pruned }));
  return state;
}

function json(body: unknown, status = 200, maxAge = EDGE_CACHE_S): Response {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status, headers: {
    'content-type': 'application/json; charset=utf-8', 'access-control-allow-origin': '*',
    'access-control-allow-methods': 'GET, OPTIONS', 'cache-control': `public, max-age=${maxAge}` } });
}

/** The read view: the per-group summary rows, the bursts of the last 7 days and the items of recent live QIDs. */
export async function view(env: Env, now: number, repo: Repo = new D1Repo(env.DB)): Promise<State> {
  const v = fromSummaries((await repo.summaries()).map((d) => JSON.parse(d) as Summary));
  v.bursts = await repo.bursts(now - KEEP_BURSTS_S);
  const cache = new QidCache(env.LIVE);
  const recent = new Set(v.bursts.filter((b) => b.qid && b.ts > now - 3600).map((b) => b.qid as string));
  for (const q of recent) { const it = await cache.item(q); if (it) v.items[q] = it; }
  countLive(v, now);
  return v;
}

async function cachedRender(path: string, env: Env, now: number): Promise<string> {
  const key = `resp:${path}`;
  const hit = await env.LIVE.getWithMetadata<{ at: number }>(key);
  if (hit.value && hit.metadata && now - hit.metadata.at < KV_CACHE_S[path]) return hit.value;
  const v = await view(env, now);
  const body = JSON.stringify(path === '/live.json' ? livePayload(v, now) : statsPayload(v, now));
  await env.LIVE.put(key, body, { metadata: { at: now } });                  // at most one write per TTL per path
  return body;
}

async function render(req: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const now = Math.floor(Date.now() / 1000);
  const url = new URL(req.url);
  const repo = new D1Repo(env.DB);
  if (url.pathname in KV_CACHE_S) return json(await cachedRender(url.pathname, env, now));
  if (url.pathname === '/bursts.json') {
    const hours = Math.min(72, Number(url.searchParams.get('hours') || 72));
    return json({ bursts: await repo.bursts(now - hours * 3600) });
  }
  if (url.pathname === '/health' || url.pathname === '/') {
    const ua = req.headers.get('user-agent') || '';
    const day = iso(now)!.slice(0, 10);
    if (/cron-job/i.test(ua)) ctx.waitUntil(repo.ping(day, now, ua));        // pinger check (ADR 0033)
    const v = fromSummaries((await repo.summaries()).map((d) => JSON.parse(d) as Summary));   // small rows only
    const s = status(v, now);
    const p = await repo.pings(day);
    return json({ ok: true, connected: s.connected, last_poll_at: s.last_poll_at, gap_minutes: s.gap_minutes,
      groups_polled: s.cron_groups, pinger_today: p ? { pings: p.n, last_at: iso(p.last_at), user_agent: p.last_ua } : null }, 200, 0);
  }
  return json({ error: 'not found' }, 404);
}

export default {
  async scheduled(event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(poll(env, Math.floor(Date.now() / 1000), groupAt(event.scheduledTime)).then(() => undefined));
  },

  async fetch(req: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (req.method === 'OPTIONS') return json({}, 204);
    const path = new URL(req.url).pathname;
    if (path in KV_CACHE_S) {                                                 // edge cache, then KV, then D1
      const cache = (caches as unknown as { default: Cache }).default;
      const hit = await cache.match(req);
      if (hit) return hit;
      const res = await render(req, env, ctx);
      ctx.waitUntil(cache.put(req, res.clone()));
      return res;
    }
    return render(req, env, ctx);
  },
};
