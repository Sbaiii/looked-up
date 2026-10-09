"""DuckDB connections configured for batch jobs (no progress bar in logs)."""

from __future__ import annotations

import duckdb


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    return con


def arrow(rel):
    """Fetch a relation as an Arrow table (``to_arrow_table`` since DuckDB 1.4, older name before)."""
    fetch = getattr(rel, "to_arrow_table", None) or rel.fetch_arrow_table
    return fetch()
