"""Run a per-day SQL builder over every day not yet in an incremental table (dbt python models)."""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Callable
from datetime import date, timedelta

from lookedup.settings import DATA_DIR

log = logging.getLogger(__name__)

STAGING = DATA_DIR / "warehouse" / "staging"


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def pending_days(session, this, is_incremental: bool, start: date, end: date) -> list[date]:
    """Days in [start, end] that the existing incremental table does not contain yet."""
    done: set[date] = set()
    if is_incremental:
        done = {r[0] for r in session.sql(f"select distinct day from {this}").fetchall()}
    return [d for d in days_between(start, end) if d not in done]


def run_by_day(session, days: list[date], sql_for_day: Callable[[date], str], name: str):
    """Write sql_for_day(d) for each day to its own Parquet file and return one relation over them.

    Writing day by day keeps memory flat (accumulating ~23 M rows in a temp table ran out of
    memory); dbt then streams the files into the incremental table.
    """
    out_dir = STAGING / name
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    files = []
    for d in days:
        t0 = time.monotonic()
        f = out_dir / f"day={d:%Y-%m-%d}.parquet"
        session.execute(f"copy ({sql_for_day(d)}) to '{f}' (format parquet, compression zstd)")
        files.append(f)
        log.info("%s: %s in %.1fs", name, d, time.monotonic() - t0)
    if not files:  # nothing to do: an empty relation with the right columns
        return session.sql(f"select * from ({sql_for_day(date(2000, 1, 1))}) limit 0")
    paths = ", ".join(f"'{f}'" for f in files)
    return session.sql(f"select * from read_parquet([{paths}])")


def prepare_event_inputs(dbt, session, suffix: str) -> tuple[str, str]:
    """Views shared by the event marts: non-automated spikes, and scored rows of spiking QIDs.

    Returns (spikes_view, scored_table) names for lookedup.analytics.events.build_events.
    """
    dbt.ref("int_spikes").create_view(f"_spikes_{suffix}", replace=True)
    dbt.ref("int_baselines").create_view(f"_baselines_{suffix}", replace=True)
    session.execute(f"create or replace temp view _ok_{suffix} as select * from _spikes_{suffix} where not is_automated")
    session.execute(f"""create or replace temp table _scored_{suffix} as
        select b.ts_hour_start, b.lang, b.views, b.baseline_median, k.qid
        from _baselines_{suffix} b
        join (select distinct lang, title, qid from _ok_{suffix} where qid is not null) k using (lang, title)""")
    return f"_ok_{suffix}", f"_scored_{suffix}"
