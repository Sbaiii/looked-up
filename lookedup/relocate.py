"""Move the old in-repo data/ directory to DATA_DIR (ADR 0016).

Files are copied one at a time, verified by size, then removed from the source. Reading a
file that iCloud has evicted ("dataless") makes macOS download it first, so the copy also
restores it; a timeout is retried. A README is left in the old directory pointing to the
new location.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

from lookedup.settings import DATA_DIR, LEGACY_DATA_DIR

log = logging.getLogger(__name__)

NOTE = """# Data moved

Looked Up data no longer lives inside the repository (ADR 0016: the repo is in ~/Desktop,
which iCloud evicts to free space). Everything that was here was moved to:

    {target}

Set LOOKEDUP_DATA_DIR to use another location. Re-create the lake mirror with
`python -m lookedup.cli sync --from 2026-07-09`.
"""


def _copy_with_retry(src: Path, dst: Path, retries: int = 5) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    for attempt in range(retries):
        try:
            shutil.copyfile(src, tmp)
            if tmp.stat().st_size != src.stat().st_size:
                raise OSError(f"size mismatch for {src}")
            os.replace(tmp, dst)
            shutil.copystat(src, dst)
            return
        except OSError as e:  # includes iCloud "Operation timed out" while restoring
            if attempt == retries - 1:
                raise
            log.warning("copy %s failed (%s), retry %d", src, e, attempt + 1)
            time.sleep(5 * (attempt + 1))


def relocate(source: Path = LEGACY_DATA_DIR, target: Path = DATA_DIR, skip: tuple[str, ...] = ()) -> dict:
    """Move every file under ``source`` to the same relative path under ``target``."""
    if source.resolve() == target.resolve():
        return {"moved": 0, "note": "source and target are the same"}
    target.mkdir(parents=True, exist_ok=True)
    moved = skipped = 0
    size = 0
    for src in sorted(p for p in source.rglob("*") if p.is_file()):
        rel = src.relative_to(source)
        if rel.name == "README.md" and rel.parent == Path("."):
            continue
        if any(str(rel).startswith(s) for s in skip):
            skipped += 1
            continue
        dst = target / rel
        if not (dst.exists() and dst.stat().st_size == src.stat().st_size):
            _copy_with_retry(src, dst)
        size += dst.stat().st_size
        src.unlink()
        moved += 1
        if moved % 25 == 0:
            log.info("moved %d files (%.1f GB)", moved, size / 1e9)
    for d in sorted((p for p in source.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    (source / "README.md").write_text(NOTE.format(target=target), encoding="utf-8")
    return {"moved": moved, "skipped": skipped, "bytes": size, "target": str(target)}
