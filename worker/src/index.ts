// Looked Up live layer on Cloudflare Workers (ADR 0032).
//   Cron (every 5 min): poll recentchanges of the 30 Wikipedias since the last poll, apply the burst rules,
//                       resolve QIDs of new bursts, save the state to KV (one write per poll: 288 a day, under the
//                       free tier's 1,000).
//   HTTP: GET /live.json, /stats.json, /bursts.json, /health with CORS for every origin, cached 15 s.
// No user data is stored: editors become bits in a salted 64-bit sketch per 5-minute slot (core.ts).

import { addEdit, countLive, emptyState, gc, iso, LANGUAGES, livePayload, statsPayload, status, counted, type RC, type State } from './core';

export interface Env { LIVE: KVNamespace; SALT?: string }

const UA = 'looked-up/0.1 (https://github.com/Sbaiii/looked-up; abdellahsbaisbai@gmail.com)';
const STATE_KEY = 'state-v1';
const FIRST_LOOKBACK_S = 30 * 60;
// subrequest budget (free plan: 50 per invocation): 30 wikis + extra pages for the busiest + up to 5 Wikidata calls
const PAGES: Record<string, number> = { en: 3, de: 2, ja: 2, fr: 2, ru: 2, es: 2 };
const WIKIDATA_CALLS = 5;
const CACHE_S = 15;

let cached: { at: number; state: State } | null = null;

async function load(env: Env): Promise<State> {
  const s = await env.LIVE.get<State>(STATE_KEY, 'json');
  return s && s.version === 1 ? s : emptyState();
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

async function resolveQids(state: State): Promise<void> {
  const todo = new Map<string, Set<string>>();
  for (const b of state.bursts) {
    const k = `${b.lang}|${b.title}`;
    if (b.qid === null && !(k in state.qids)) (todo.get(b.lang) || todo.set(b.lang, new Set()).get(b.lang)!).add(b.title);
  }
  let calls = 0;
  for (const [lang, titles] of todo) {
    if (calls++ >= WIKIDATA_CALLS) break;
    const site = `${lang.replace(/-/g, '_')}wiki`;
    const chunk = [...titles].slice(0, 50);
    const q = new URLSearchParams({ action: 'wbgetentities', sites: site, titles: chunk.join('|'), props: 'labels|descriptions|sitelinks',
      sitefilter: site, languages: [...new Set(['en', 'fr', 'es', lang])].join('|'), normalize: '1', format: 'json' });
    const r = await fetch(`https://www.wikidata.org/w/api.php?${q}`, { headers: { 'User-Agent': UA } });
    if (!r.ok) continue;
    const d = (await r.json()) as { entities?: Record<string, any> };
    const found = new Map<string, string>();
    for (const [key, e] of Object.entries(d.entities || {})) {
      if (!key.startsWith('Q') || 'missing' in e) continue;
      const t = e.sitelinks?.[site]?.title;
      if (t) found.set(t, key);
      state.items[key] = {
        labels: Object.fromEntries(Object.entries(e.labels || {}).map(([k, v]: [string, any]) => [k, v.value])),
        desc: Object.fromEntries(Object.entries(e.descriptions || {}).map(([k, v]: [string, any]) => [k, v.value])),
      };
    }
    for (const t of chunk) state.qids[`${lang}|${t}`] = found.get(t) || found.get(t.replace(/_/g, ' ')) || null;
  }
  for (const b of state.bursts) if (b.qid === null) b.qid = state.qids[`${b.lang}|${b.title}`] ?? null;
}

export async function poll(env: Env, now: number): Promise<State> {
  const state = await load(env);
  const salt = `${env.SALT || 'looked-up'}|${iso(now)!.slice(0, 10)}`;     // rotates daily
  const resumed = state.polledAt !== null && now - state.polledAt <= 900;
  let fetched = 0;
  let kept = 0;
  let earliest = now;
  const langs = new Set<string>();
  for (const lang of LANGUAGES as string[]) {
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
        addEdit(state, lang, rc, salt);
      }
      state.lastPoll[lang] = caughtUp ? Math.max(newest, now - 60) : newest;     // behind: resume where we stopped
    } catch {
      /* one wiki failing must not stop the others; it resumes from its lastPoll next time */
    }
  }
  if (!resumed) state.coveredSince = earliest;
  state.lastPollStats = { fetched, kept, seconds: resumed ? now - (state.polledAt as number) : FIRST_LOOKBACK_S, languages: [...langs].sort() };
  state.polledAt = now;
  await resolveQids(state);
  countLive(state, now);
  gc(state, now);
  const blob = JSON.stringify(state);
  await env.LIVE.put(STATE_KEY, blob);                                       // the only KV write of the poll
  cached = { at: now, state };
  // one line per poll for `wrangler tail` (docs/ops.md): no titles, no users
  console.log(JSON.stringify({ poll: iso(now), fetched, kept, languages: langs.size, bursts: state.bursts.length,
    articles: Object.keys(state.articles).length, state_bytes: blob.length, kv_writes: 1 }));
  return state;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: {
    'content-type': 'application/json; charset=utf-8', 'access-control-allow-origin': '*',
    'access-control-allow-methods': 'GET, OPTIONS', 'cache-control': `public, max-age=${CACHE_S}` } });
}

export default {
  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(poll(env, Math.floor(Date.now() / 1000)).then(() => undefined));
  },

  async fetch(req: Request, env: Env): Promise<Response> {
    if (req.method === 'OPTIONS') return json({}, 204);
    const now = Math.floor(Date.now() / 1000);
    if (!cached || now - cached.at > CACHE_S) cached = { at: now, state: await load(env) };
    const state = cached.state;
    const path = new URL(req.url).pathname;
    if (path === '/live.json') return json(livePayload(state, now));
    if (path === '/stats.json') return json(statsPayload(state, now));
    if (path === '/bursts.json') {
      const hours = Math.min(72, Number(new URL(req.url).searchParams.get('hours') || 72));
      return json({ bursts: state.bursts.filter((b) => b.ts >= now - hours * 3600) });
    }
    if (path === '/health' || path === '/') {
      const s = status(state, now);
      return json({ ok: true, connected: s.connected, last_poll_at: s.last_poll_at, gap_minutes: s.gap_minutes });
    }
    return json({ error: 'not found' }, 404);
  },
};
