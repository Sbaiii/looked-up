-- Live layer state in D1 (ADR 0033). One row per poll group holds that group's per-article windows and editor
-- sketches (a compact JSON blob: per-article rows would cost ~240k row writes a day, over the free 100k).
CREATE TABLE IF NOT EXISTS group_state (
  g         INTEGER PRIMARY KEY,
  version   INTEGER NOT NULL,
  polled_at INTEGER NOT NULL,
  state     TEXT    NOT NULL
);

-- One row per burst (no user data); kept 7 days for the hourly live-event counts of the week.
CREATE TABLE IF NOT EXISTS bursts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  lang        TEXT    NOT NULL,
  title       TEXT    NOT NULL,
  ts          INTEGER NOT NULL,
  kind        TEXT    NOT NULL,
  edits_30m   INTEGER NOT NULL,
  editors_30m INTEGER NOT NULL,
  qid         TEXT
);
CREATE INDEX IF NOT EXISTS bursts_ts ON bursts (ts);

-- Pinger check: GETs to /health per UTC day and the last user agent seen.
CREATE TABLE IF NOT EXISTS pings (
  day     TEXT PRIMARY KEY,
  n       INTEGER NOT NULL,
  last_at INTEGER NOT NULL,
  last_ua TEXT
);
