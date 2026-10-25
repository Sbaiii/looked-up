"""The DuckDB connection helpers."""
from __future__ import annotations

from lookedup import db


def test_one_returns_the_first_row_or_none_and_frees_the_connection():
    con = db.connect()
    con.execute("CREATE TABLE t AS SELECT * FROM range(5) r(i)")
    assert db.one(con, "SELECT i FROM t ORDER BY i") == (0,)
    assert db.one(con, "SELECT i FROM t WHERE i > ?", [2]) == (3,)
    assert db.one(con, "SELECT i FROM t WHERE i > 10") is None
    assert con.execute("SELECT count(*) FROM t").fetchall() == [(5,)]     # usable right after, even on DuckDB 2.0


def test_connect_sets_the_spill_directory():
    from lookedup.settings import DUCKDB_TEMP_DIR

    con = db.connect()
    assert db.one(con, "SELECT current_setting('temp_directory')")[0] == str(DUCKDB_TEMP_DIR)
