"""Run the dbt warehouse (warehouse/) in-process with the pre-registered analytics config.

    python -m lookedup.cli warehouse build              # dbt build, local lake mirror
    python -m lookedup.cli warehouse run --select int_spikes

Thresholds come from config/analytics.yml and are passed as dbt vars, so the warehouse
and the production scorer cannot drift apart. The lake defaults to the local mirror in
data/lake/ (see `cli sync`); ``--hf`` reads hf:// paths instead (slower).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime

from lookedup.analytics.config import load
from lookedup.languages import active_codes
from lookedup.settings import DATA_DIR, DUCKDB_MAX_TEMP, DUCKDB_TEMP_DIR, HF_REPO_ID, LOCAL_LAKE_DIR, ROOT

log = logging.getLogger(__name__)

WAREHOUSE_DIR = ROOT / "warehouse"
WAREHOUSE_DB = DATA_DIR / "warehouse" / "lookedup.duckdb"


def dbt_vars(lake_root: str) -> dict:
    cfg = load()
    return {
        "lake_root": lake_root,
        "period_start": f"{cfg.period_start:%Y-%m-%d}",
        "period_end": f"{cfg.period_end:%Y-%m-%d}",
        "weekend_days": cfg.baseline["weekend_days"],
        "r3_threshold": cfg.spike.r3_threshold,
        "min_r3_ablation": cfg.min_r3_ablation,
        "languages": active_codes(),
    }


def run(args: list[str], hf: bool = False) -> bool:
    """Invoke dbt with ``args`` (e.g. ["build"]). Returns True on success."""
    from dbt.cli.main import dbtRunner

    lake_root = f"hf://datasets/{HF_REPO_ID}" if hf else str(LOCAL_LAKE_DIR)
    WAREHOUSE_DB.parent.mkdir(parents=True, exist_ok=True)
    os.environ["LOOKEDUP_LAKE_ROOT"] = lake_root
    os.environ["LOOKEDUP_WAREHOUSE_DB"] = str(WAREHOUSE_DB)
    DUCKDB_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["LOOKEDUP_DUCKDB_TEMP_DIR"] = str(DUCKDB_TEMP_DIR)
    os.environ["LOOKEDUP_DUCKDB_MAX_TEMP"] = DUCKDB_MAX_TEMP
    full = args + ["--project-dir", str(WAREHOUSE_DIR), "--profiles-dir", str(WAREHOUSE_DIR),
                   "--vars", json.dumps(dbt_vars(lake_root))]
    log.info("dbt %s (lake: %s)", " ".join(args), lake_root)
    res = dbtRunner().invoke(full)
    if res.exception:
        raise res.exception
    return bool(res.success)


def refresh(end: date | None = None) -> dict:
    """Extend the local warehouse to ``end`` (default: yesterday UTC): mirror the new day files, then an incremental
    dbt build (int_* models are incremental by day; marts are rebuilt). Run weekly by hand (docs/ops.md)."""
    import time
    from datetime import timedelta

    from lookedup.dumps import utcnow
    from lookedup.store import HFStore, LocalStore, sync_to_local

    end = end or (utcnow().date() - timedelta(days=1))
    os.environ["LOOKEDUP_PERIOD_END"] = f"{end:%Y-%m-%d}"
    t0 = time.monotonic()
    synced = sync_to_local(HFStore(), LocalStore(), datetime.combine(end - timedelta(days=35), datetime.min.time()),
                           include_sitelinks=False)
    t1 = time.monotonic()
    ok = run(["build"])
    return {"period_end": f"{end:%Y-%m-%d}", "synced": synced, "sync_seconds": round(t1 - t0),
            "dbt_seconds": round(time.monotonic() - t1), "success": ok}
