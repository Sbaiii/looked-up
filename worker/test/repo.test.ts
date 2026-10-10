// The D1 repository layer and a full poll against a local D1 + KV (miniflare), with stubbed Wikipedia responses.
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { convertV4MiniflareOptions, Miniflare } from 'miniflare';
import { D1Repo, QidCache } from '../src/repo';
import { emptyState, type Burst } from '../src/core';

let mf: Miniflare;
let db: D1Database;
let kv: KVNamespace;
const T0 = 1_791_000_000;

beforeAll(async () => {
  mf = new Miniflare(convertV4MiniflareOptions({ modules: true, compatibilityDate: '2026-09-01',
    script: 'export default { fetch() { return new Response("ok") } }', d1Databases: ['DB'], kvNamespaces: ['LIVE'] }));
  db = (await mf.getD1Database('DB')) as unknown as D1Database;
  kv = (await mf.getKVNamespace('LIVE')) as unknown as KVNamespace;
  for (const f of ['0001_init.sql', '0002_slots_meta_summary.sql']) {
    const sql = readFileSync(new URL(`../migrations/${f}`, import.meta.url), 'utf8');
    for (const stmt of sql.replace(/--.*$/gm, '').split(';').map((x) => x.trim()).filter(Boolean)) await db.prepare(stmt).run();
  }
});

afterAll(async () => { await mf?.dispose(); });

const burst = (lang: string, ts: number, qid: string | null = null): Burst =>
  ({ lang, title: `T ${lang}`, ts, kind: 'window', edits_30m: 5, editors_30m: 3, qid });

describe('D1Repo', () => {
  it('saves touched slots, meta and summary in one batch, reads the window and drops old slots', async () => {
    const repo = new D1Repo(db);
    const base = { g: 4, now: T0, meta: '{"v":6}', summary: '{"pa":1}', bursts: [] as Burst[] };
    await repo.save({ ...base, slots: [{ s: T0 - 4200, data: 'old' }, { s: T0 - 300, data: 'a' }], dropBefore: 0 });
    let w = await repo.loadWindow(4, T0 - 3600);
    expect(w.meta).toBe('{"v":6}');
    expect(w.slots.map((r) => r.data)).toEqual(['a']);                      // the 70-min-old slot is outside the window
    const written = await repo.save({ ...base, now: T0 + 60, slots: [{ s: T0 - 300, data: 'b' }], dropBefore: T0 - 4200 + 1 });
    expect(written).toBe(4);                                                 // 1 slot + meta + summary + 1 deleted
    w = await repo.loadWindow(4, 0);
    expect(w.slots).toEqual([{ s: T0 - 300, data: 'b' }]);
    expect(await repo.summaries()).toEqual(['{"pa":1}']);
  });

  it('stores bursts, reads them by time and prunes the old ones', async () => {
    const repo = new D1Repo(db);
    await repo.addBursts([burst('en', T0 - 8 * 86400), burst('fr', T0 - 100, 'Q1'), burst('de', T0)]);
    expect((await repo.bursts(T0 - 3600)).map((b) => b.lang)).toEqual(['fr', 'de']);
    expect((await repo.bursts(T0 - 3600))[0].qid).toBe('Q1');
    expect(await repo.pruneBursts(T0 - 7 * 86400)).toBe(1);
    expect((await repo.bursts(0)).length).toBe(2);
  });

  it('counts pinger GETs per day', async () => {
    const repo = new D1Repo(db);
    await repo.ping('2026-10-10', T0, 'Mozilla/5.0 (compatible; cron-job.org; http://cron-job.org/abuse/)');
    await repo.ping('2026-10-10', T0 + 3600, 'Mozilla/5.0 (compatible; cron-job.org; http://cron-job.org/abuse/)');
    expect(await repo.pings('2026-10-10')).toMatchObject({ n: 2, last_at: T0 + 3600 });
  });

  it('caches QIDs and items in KV, including "no item"', async () => {
    const c = new QidCache(kv);
    await c.putQid('en', 'Comet', 'Q42'); await c.putQid('en', 'Nothing', null);
    expect(await c.get('en', 'Comet')).toBe('Q42');
    expect(await c.get('en', 'Nothing')).toBe('');
    expect(await c.get('en', 'Unknown')).toBeNull();
    await c.putItem('Q42', { labels: { en: 'Comet' }, desc: {} });
    expect((await c.item('Q42'))?.labels.en).toBe('Comet');
  });
});

describe('poll with D1 state', () => {
  it('persists the window state between polls, inserts bursts and keeps users out of storage', async () => {
    const { poll, view } = await import('../src/index');
    const { GROUPS } = await import('../src/core');
    const lang = GROUPS[1][0];
    let call = 0;
    const editors = ['alice', 'bob', 'carol', 'dave', 'erin', 'frank'];
    vi.stubGlobal('fetch', async (url: string) => {
      if (url.includes('wikidata')) {
        return new Response(JSON.stringify({ entities: { Q7: { labels: { en: { value: 'Story' } }, descriptions: {},
          sitelinks: { [`${lang}wiki`]: { title: 'Story' } } } } }));
      }
      if (!url.startsWith(`https://${lang}.`)) return new Response(JSON.stringify({ query: { recentchanges: [] } }));
      call += 1;
      const base = call === 1 ? 0 : 300;                                     // 3 edits per poll, 6 in 2 polls
      const rows = [0, 1, 2].map((i) => ({ title: 'Story', type: 'edit', user: editors[(call - 1) * 3 + i],
        timestamp: new Date((T0 + base + i * 30) * 1000).toISOString() }));
      return new Response(JSON.stringify({ query: { recentchanges: rows } }));
    });
    const env = { LIVE: kv, DB: db, SALT: 's' };
    const repo = new D1Repo(db);
    const s1 = await poll(env as any, T0 + 120, 1, repo);
    expect(s1.bursts.length).toBe(0);
    const s2 = await poll(env as any, T0 + 420, 1, repo);
    expect(s2.bursts.map((b) => [b.lang, b.title, b.qid])).toEqual([[lang, 'Story', 'Q7']]);   // resumed from D1 slots
    const w = await repo.loadWindow(1, 0);
    expect(w.slots.length).toBe(2);
    expect(JSON.stringify(w)).not.toMatch(/alice|bob|carol|dave|erin|frank/);
    const v = await view(env as any, T0 + 430, repo);
    expect(v.bursts.some((b) => b.title === 'Story' && b.qid === 'Q7')).toBe(true);
    expect(v.items.Q7.labels.en).toBe('Story');
    expect(v.counts![`${lang}|Story`][1]).toBe(6);                         // counts come from the summary row
    expect(v.articles).toEqual({});                                         // never the full states
    vi.unstubAllGlobals();
  });

  it('compact encoding is smaller than the v5 group blob for the same state', async () => {
    const { addEdit, encodeSlot, encodeMeta } = await import('../src/core');
    const st = emptyState();
    const sample = JSON.parse(readFileSync(new URL('./fixtures/en_recentchanges.json', import.meta.url), 'utf8')) as any[];
    for (const r of sample) addEdit(st, 'en', r, 's');
    const now = Math.max(...sample.map((r) => Date.parse(r.timestamp) / 1000));
    const v5 = JSON.stringify({ ...st, bursts: undefined, touched: undefined });   // the pre-change layout
    const rows = [...st.touched!].map((s0) => encodeSlot(st, s0));
    const meta = encodeMeta(st, now);
    const newest = rows[rows.length - 1].length + meta.length;              // what a steady run rewrites
    console.log(JSON.stringify({ articles: Object.keys(st.articles).length, v5_bytes: v5.length,
      slot_rows_bytes: rows.reduce((n, r) => n + r.length, 0), meta_bytes: meta.length, steady_write_bytes: newest }));
    expect(rows.reduce((n, r) => n + r.length, 0) + meta.length).toBeLessThan(v5.length);
    expect(newest).toBeLessThan(v5.length / 3);
  });

});
