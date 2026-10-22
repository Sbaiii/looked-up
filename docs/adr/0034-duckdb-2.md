# 0034 — DuckDB 2.0: read single rows with `db.one`

- Status: accepted
- Date: 2026-10-22

## Context

DuckDB 2.0 was released while the package declared `duckdb>=1.1`, so CI and every workflow that installs fresh
picked it up. Two changes broke the code:

- relations (`con.sql(...)`) no longer have `fetchone()`;
- after `con.execute(...)`, the connection refuses other work until the result has been read to the end, so
  `con.execute(...).fetchone()` breaks as soon as the same connection runs another query.

The hourly job kept working (its path never read a single row), but CI failed and the Monday retrain, the
backfill export and the evaluations would have.

## Decision

- **`lookedup.db.one(con, sql, params)`** returns the first row or None and always reads the whole result. Every
  single-row read in the package and the tests goes through it; the spike scripts, which stay standalone, use
  `.fetchall()[0]` on aggregates.
- `tests/test_repo_consistency.py` refuses any `fetchone()` in `lookedup/` and `live/`.
- The package allows DuckDB 2.0 again. The `warehouse` extra keeps `duckdb<2` until dbt-duckdb has been checked
  against 2.0 with a real build.

## Consequences

- The full test suite passes on DuckDB 1.5 and 2.0.
- Reading every row of a single-row query costs nothing; queries that could return many rows already use
  `LIMIT 1` where only the first one matters.
