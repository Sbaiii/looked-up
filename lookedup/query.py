"""D10: query the lake with DuckDB, straight from Hugging Face (``hf://``) or a local copy.

    from lookedup.query import connect, top
    con = connect()
    con.sql("SELECT lang, sum(views_desktop + views_mobile) FROM hourly GROUP BY 1").show()
"""

from __future__ import annotations

import os
from datetime import datetime

import duckdb

from lookedup import db
from lookedup.settings import HF_REPO_ID, LOCAL_LAKE_DIR, SITELINKS_PATH
from lookedup.store import hour_path


def lake_root(local: bool = False) -> str:
    """``hf://datasets/<repo>`` (default) or the local lake directory."""
    if local or os.environ.get("LOOKEDUP_LOCAL_LAKE"):
        return str(LOCAL_LAKE_DIR)
    return f"hf://datasets/{HF_REPO_ID}"


def _base(root: str) -> duckdb.DuckDBPyConnection:
    con = db.connect()
    if root.startswith("hf://"):
        con.execute("INSTALL httpfs; LOAD httpfs;")
        token = os.environ.get("HF_TOKEN")
        if token:  # only needed for private repos or higher rate limits
            con.execute(f"CREATE SECRET hf (TYPE huggingface, TOKEN '{token}')")
    return con


def connect(local: bool = False) -> duckdb.DuckDBPyConnection:
    """DuckDB connection with views ``hourly`` (all hours) and ``sitelinks``."""
    root = lake_root(local)
    con = _base(root)
    con.execute(f"""CREATE VIEW hourly AS SELECT * FROM read_parquet('{root}/data/hourly/*/*/*/*.parquet',
                    hive_partitioning = false)""")
    con.execute(f"CREATE VIEW sitelinks AS SELECT * FROM read_parquet('{root}/{SITELINKS_PATH}')")
    return con


def top(lang: str, hour: datetime, n: int = 20, local: bool = False) -> duckdb.DuckDBPyRelation:
    """Top ``n`` articles of one language in one hour, with desktop, mobile and mobile share."""
    root = lake_root(local)
    con = _base(root)
    path = f"{root}/{hour_path(hour)}"
    return con.sql(f"""
        SELECT title, views_desktop, views_mobile, views_desktop + views_mobile AS views,
               round(100.0 * views_mobile / (views_desktop + views_mobile), 1) AS mobile_pct
        FROM read_parquet('{path}')
        WHERE lang = '{lang.replace("'", "''")}'
        ORDER BY views DESC, title
        LIMIT {int(n)}
    """)
