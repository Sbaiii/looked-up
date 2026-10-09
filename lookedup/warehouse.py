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

from lookedup.analytics.config import load
from lookedup.languages import active_codes
from lookedup.settings import DATA_DIR, HF_REPO_ID, LOCAL_LAKE_DIR, ROOT

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
    full = args + ["--project-dir", str(WAREHOUSE_DIR), "--profiles-dir", str(WAREHOUSE_DIR),
                   "--vars", json.dumps(dbt_vars(lake_root))]
    log.info("dbt %s (lake: %s)", " ".join(args), lake_root)
    res = dbtRunner().invoke(full)
    if res.exception:
        raise res.exception
    return bool(res.success)
