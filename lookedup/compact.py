"""One-off migration of a local lake from one file per hour to one file per day (ADR 0012).

    data/hourly/year=YYYY/month=MM/day=DD/hour=HH.parquet  ->  data/hourly/year=YYYY/month=MM/day=DD.parquet

Rows are sorted by (lang, title, ts_hour_start), zstd level 9, ~1M-row row groups. The
manifest keeps one entry per hour; only the paths change and a ``files`` section is added.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from lookedup.settings import MANIFEST_PATH
from lookedup.store import SORT_KEYS, Manifest, day_path, write_parquet

log = logging.getLogger(__name__)


def compact_local(root: Path) -> list[dict]:
    """Migrate every hour-per-file day directory under ``root``; returns per-day byte counts."""
    manifest_file = root / MANIFEST_PATH
    manifest = Manifest.from_json(manifest_file.read_text() if manifest_file.exists() else None)
    report = []
    for day_dir in sorted((root / "data" / "hourly").glob("year=*/month=*/day=*")):
        if not day_dir.is_dir():
            continue
        hour_files = sorted(day_dir.glob("hour=*.parquet"))
        if not hour_files:
            continue
        before = sum(f.stat().st_size for f in hour_files)
        table = pa.concat_tables([pq.read_table(f) for f in hour_files]).sort_by(SORT_KEYS)
        y, m, d = (int(part.split("=")[1]) for part in day_dir.parts[-3:])
        rel = day_path(datetime(y, m, d))
        tmp = root / (rel + ".tmp")
        after = write_parquet(table, tmp)
        tmp.rename(root / rel)
        shutil.rmtree(day_dir)
        for key, entry in manifest.hours.items():
            if key.startswith(f"{y:04d}-{m:02d}-{d:02d}T"):
                entry["path"] = rel
                entry.pop("bytes", None)
        manifest.set_file(rel, table.num_rows, after)
        report.append({"day": f"{y:04d}-{m:02d}-{d:02d}", "hours": len(hour_files), "rows": table.num_rows,
                       "bytes_hourly_files": before, "bytes_day_file": after,
                       "ratio": round(after / before, 3)})
        log.info("compacted %s: %d hour files, %d rows, %d -> %d bytes", rel, len(hour_files),
                 table.num_rows, before, after)
    manifest_file.write_text(manifest.to_json())
    return report
