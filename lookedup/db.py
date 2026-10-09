"""DuckDB connections configured for batch jobs: no progress bar, bounded spill (ADR 0016)."""

from __future__ import annotations

import duckdb

from lookedup.settings import DUCKDB_MAX_TEMP, DUCKDB_TEMP_DIR


def configure(con: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """Apply the project-wide limits to any connection (spill directory and size cap)."""
    DUCKDB_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    con.execute("SET enable_progress_bar = false")
    con.execute(f"SET temp_directory = '{DUCKDB_TEMP_DIR}'")
    con.execute(f"SET max_temp_directory_size = '{DUCKDB_MAX_TEMP}'")
    return con


def connect(database: str = ":memory:", read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return configure(duckdb.connect(database, read_only=read_only))


def arrow(rel):
    """Fetch a relation as an Arrow table (``to_arrow_table`` since DuckDB 1.4, older name before)."""
    fetch = getattr(rel, "to_arrow_table", None) or rel.fetch_arrow_table
    return fetch()
