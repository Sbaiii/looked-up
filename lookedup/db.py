"""DuckDB connections configured for batch jobs (no progress bar in logs)."""

from __future__ import annotations

import duckdb


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    return con
