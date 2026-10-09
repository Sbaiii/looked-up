"""Hours listed in the lake manifest (used to reconcile stg_hourly with the manifest)."""

import json
from pathlib import Path

import pyarrow as pa


def model(dbt, session):
    dbt.config(materialized="table")
    root = dbt.config.get("lake_root")
    doc = json.loads(Path(root, "data", "manifest.json").read_text())
    rows = [{"ts_hour_start": k.replace("T", " ").rstrip("Z"), "rows": v["rows"], "source": v["source"],
             "path": v["path"]} for k, v in doc["hours"].items()]
    rel = session.from_arrow(pa.Table.from_pylist(rows))
    return rel.project("cast(ts_hour_start as timestamp) as ts_hour_start, rows, source, path")
