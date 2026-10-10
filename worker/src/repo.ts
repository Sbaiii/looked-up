// Storage for the live layer (ADR 0033): D1 holds the per-group window state (articles, editor sketches,
// baselines, poll positions), the bursts and the pinger counter; KV holds only the QID cache and cached responses.

import type { Burst, Item } from './core';

export interface GroupRow { g: number; version: number; polled_at: number; state: string }

export interface Repo {
  loadGroup(g: number): Promise<GroupRow | null>;
  loadGroups(): Promise<GroupRow[]>;
  saveGroup(row: GroupRow): Promise<void>;
  addBursts(bursts: Burst[]): Promise<void>;
  bursts(since: number): Promise<Burst[]>;
  pruneBursts(before: number): Promise<number>;
  ping(day: string, at: number, ua: string): Promise<void>;
  pings(day: string): Promise<{ n: number; last_at: number; last_ua: string | null } | null>;
}

export class D1Repo implements Repo {
  constructor(private db: D1Database) {}

  async loadGroup(g: number): Promise<GroupRow | null> {
    return this.db.prepare('SELECT g, version, polled_at, state FROM group_state WHERE g = ?').bind(g).first<GroupRow>();
  }

  async loadGroups(): Promise<GroupRow[]> {
    return (await this.db.prepare('SELECT g, version, polled_at, state FROM group_state ORDER BY g').all<GroupRow>()).results;
  }

  async saveGroup(r: GroupRow): Promise<void> {
    await this.db.prepare(`INSERT INTO group_state (g, version, polled_at, state) VALUES (?, ?, ?, ?)
      ON CONFLICT (g) DO UPDATE SET version = excluded.version, polled_at = excluded.polled_at, state = excluded.state`)
      .bind(r.g, r.version, r.polled_at, r.state).run();
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
