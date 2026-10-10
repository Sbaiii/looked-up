// Storage for the live layer (ADR 0033): D1 holds the per-group window state (articles, editor sketches,
// baselines, poll positions), the bursts and the pinger counter; KV holds only the QID cache and cached responses.

import type { Burst, Item } from './core';

export interface SlotRow { s: number; data: string }
export interface Window { meta: string | null; slots: SlotRow[] }
export interface Save { g: number; now: number; meta: string; summary: string; slots: SlotRow[]; bursts: Burst[]; dropBefore: number }

export interface Repo {
  loadWindow(g: number, since: number): Promise<Window>;
  save(w: Save): Promise<number>;                     // returns D1 rows written (incl. deleted slots)
  summaries(): Promise<string[]>;
  addBursts(bursts: Burst[]): Promise<void>;
  bursts(since: number): Promise<Burst[]>;
  pruneBursts(before: number): Promise<number>;
  ping(day: string, at: number, ua: string): Promise<void>;
  pings(day: string): Promise<{ n: number; last_at: number; last_ua: string | null } | null>;
}

export class D1Repo implements Repo {
  constructor(private db: D1Database) {}

  async loadWindow(g: number, since: number): Promise<Window> {
    const [meta, slots] = await this.db.batch([
      this.db.prepare('SELECT data FROM group_meta WHERE g = ?').bind(g),
      this.db.prepare('SELECT s, data FROM slots WHERE g = ? AND s >= ? ORDER BY s').bind(g, since),
    ]);
    return { meta: (meta.results[0] as { data: string } | undefined)?.data ?? null, slots: slots.results as SlotRow[] };
  }

  /** One batch: touched slots, meta, summary, new bursts, and the slots that left the window. */
  async save(w: Save): Promise<number> {
    const slot = this.db.prepare(`INSERT INTO slots (g, s, data) VALUES (?, ?, ?)
      ON CONFLICT (g, s) DO UPDATE SET data = excluded.data`);
    const burst = this.db.prepare('INSERT INTO bursts (lang, title, ts, kind, edits_30m, editors_30m, qid) VALUES (?, ?, ?, ?, ?, ?, ?)');
    const res = await this.db.batch([
      ...w.slots.map((r) => slot.bind(w.g, r.s, r.data)),
      this.db.prepare(`INSERT INTO group_meta (g, polled_at, data) VALUES (?, ?, ?)
        ON CONFLICT (g) DO UPDATE SET polled_at = excluded.polled_at, data = excluded.data`).bind(w.g, w.now, w.meta),
      this.db.prepare(`INSERT INTO summary (g, polled_at, data) VALUES (?, ?, ?)
        ON CONFLICT (g) DO UPDATE SET polled_at = excluded.polled_at, data = excluded.data`).bind(w.g, w.now, w.summary),
      ...w.bursts.map((b) => burst.bind(b.lang, b.title, b.ts, b.kind, b.edits_30m, b.editors_30m, b.qid)),
      this.db.prepare('DELETE FROM slots WHERE g = ? AND s < ?').bind(w.g, w.dropBefore),
    ]);
    return res.reduce((n, r) => n + (r.meta.changes ?? 0), 0);
  }

  async summaries(): Promise<string[]> {
    return (await this.db.prepare('SELECT data FROM summary ORDER BY g').all<{ data: string }>()).results.map((r) => r.data);
  }

  async addBursts(bursts: Burst[]): Promise<void> {
    if (!bursts.length) return;
    const stmt = this.db.prepare('INSERT INTO bursts (lang, title, ts, kind, edits_30m, editors_30m, qid) VALUES (?, ?, ?, ?, ?, ?, ?)');
    await this.db.batch(bursts.map((b) => stmt.bind(b.lang, b.title, b.ts, b.kind, b.edits_30m, b.editors_30m, b.qid)));
  }

  async bursts(since: number): Promise<Burst[]> {
    return (await this.db.prepare('SELECT lang, title, ts, kind, edits_30m, editors_30m, qid FROM bursts WHERE ts >= ? ORDER BY ts')
      .bind(since).all<Burst>()).results;
  }

  async pruneBursts(before: number): Promise<number> {
    return (await this.db.prepare('DELETE FROM bursts WHERE ts < ?').bind(before).run()).meta.changes ?? 0;
  }

  async ping(day: string, at: number, ua: string): Promise<void> {
    await this.db.prepare(`INSERT INTO pings (day, n, last_at, last_ua) VALUES (?, 1, ?, ?)
      ON CONFLICT (day) DO UPDATE SET n = n + 1, last_at = excluded.last_at, last_ua = excluded.last_ua`)
      .bind(day, at, ua.slice(0, 120)).run();
  }

  async pings(day: string) {
    return this.db.prepare('SELECT n, last_at, last_ua FROM pings WHERE day = ?').bind(day).first<{ n: number; last_at: number; last_ua: string | null }>();
  }
}

/** QID cache in KV: "q:<lang>|<title>" -> QID or "" (no item), "i:<QID>" -> labels and descriptions. */
export class QidCache {
  constructor(private kv: KVNamespace) {}
  get(lang: string, title: string): Promise<string | null> { return this.kv.get(`q:${lang}|${title}`); }
  putQid(lang: string, title: string, qid: string | null): Promise<void> { return this.kv.put(`q:${lang}|${title}`, qid ?? '', { expirationTtl: 30 * 86400 }); }
  item(qid: string): Promise<Item | null> { return this.kv.get<Item>(`i:${qid}`, 'json'); }
  putItem(qid: string, item: Item): Promise<void> { return this.kv.put(`i:${qid}`, JSON.stringify(item), { expirationTtl: 30 * 86400 }); }
}
