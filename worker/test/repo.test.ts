// The D1 repository layer and a full poll against a local D1 + KV (miniflare), with stubbed Wikipedia responses.
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { convertV4MiniflareOptions, Miniflare } from 'miniflare';
import { D1Repo, QidCache } from '../src/repo';
import { persisted, emptyState, type Burst } from '../src/core';

let mf: Miniflare;
let db: D1Database;
let kv: KVNamespace;
const T0 = 1_791_000_000;

beforeAll(async () => {
  mf = new Miniflare(convertV4MiniflareOptions({ modules: true, compatibilityDate: '2026-09-01',
    script: 'export default { fetch() { return new Response("ok") } }', d1Databases: ['DB'], kvNamespaces: ['LIVE'] }));
  db = (await mf.getD1Database('DB')) as unknown as D1Database;
  kv = (await mf.getKVNamespace('LIVE')) as unknown as KVNamespace;
  const sql = readFileSync(new URL('../migrations/0001_init.sql', import.meta.url), 'utf8');
  for (const stmt of sql.replace(/--.*$/gm, '').split(';').map((x) => x.trim()).filter(Boolean)) await db.prepare(stmt).run();
});

afterAll(async () => { await mf?.dispose(); });

const burst = (lang: string, ts: number, qid: string | null = null): Burst =>
  ({ lang, title: `T ${lang}`, ts, kind: 'window', edits_30m: 5, editors_30m: 3, qid });

describe('D1Repo', () => {
  it('upserts one row per group', async () => {
    const repo = new D1Repo(db);
    await repo.saveGroup({ g: 2, version: 5, polled_at: T0, state: '{"a":1}' });
    await repo.saveGroup({ g: 2, version: 5, polled_at: T0 + 60, state: '{"a":2}' });
    expect(await repo.loadGroup(2)).toEqual({ g: 2, version: 5, polled_at: T0 + 60, state: '{"a":2}' });
    expect(await repo.loadGroup(3)).toBeNull();
    expect((await repo.loadGroups()).map((r) => r.g)).toEqual([2]);
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
    expect(s2.bursts.map((b) => [b.lang, b.title, b.qid])).toEqual([[lang, 'Story', 'Q7']]);   // resumed from D1
    const row = await repo.loadGroup(1);
    expect(row!.state).not.toMatch(/alice|bob|carol|dave|erin|frank/);
    expect(JSON.parse(row!.state).bursts).toBeUndefined();
    const v = await view(env as any, T0 + 430, repo);
    expect(v.bursts.some((b) => b.title === 'Story' && b.qid === 'Q7')).toBe(true);
    expect(v.items.Q7.labels.en).toBe('Story');
    vi.unstubAllGlobals();
  });

  it('persisted() drops bursts, QIDs and items', () => {
    const s = emptyState();
    s.bursts.push(burst('en', T0));
    expect(Object.keys(persisted(s))).not.toContain('bursts');
  });
});
