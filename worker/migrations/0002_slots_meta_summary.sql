-- ADR 0033, final round: per-slot window rows instead of one large row per group, a small meta row per group and
-- a summary row per group for the read path. A run reads its meta and the last 70 minutes of slots, and writes only
-- the slots it touched, its meta and its summary.
CREATE TABLE IF NOT EXISTS slots (
  g    INTEGER NOT NULL,
  s    INTEGER NOT NULL,          -- slot start (epoch seconds, multiple of 300)
  data TEXT    NOT NULL,          -- {"k": [article keys], "v": [edits, bitsHigh, bitsLow, ...]}
  PRIMARY KEY (g, s)
);

CREATE TABLE IF NOT EXISTS group_meta (
  g         INTEGER PRIMARY KEY,
  polled_at INTEGER NOT NULL,
  data      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS summary (
  g         INTEGER PRIMARY KEY,
  polled_at INTEGER NOT NULL,
  data      TEXT    NOT NULL
);

DROP TABLE IF EXISTS group_state;
