"""Lake storage: daily Parquet files, the manifest, and the Hugging Face / local backends.

Layout (identical locally and on the Hub), see ADR 0012::

    data/hourly/year=YYYY/month=MM/day=DD.parquet   all hours of one UTC day
    data/wikidata/sitelinks.parquet
    data/manifest.json

The manifest tracks HOURS (an hour is present iff it is in the manifest); a ``files``
section records the size of each day file. All writers go through :func:`write_hours`,
which merges new hours into the day file as of a given Hub revision and commits the
day files plus the manifest in ONE commit with ``parent_commit`` set. If another writer
committed meanwhile, the whole merge is redone on the new revision, so no rows are lost.
"""

from __future__ import annotations

import json
import logging
import os
import random
import shutil
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from lookedup.dumps import utcnow
from lookedup.settings import HF_REPO_ID, LOCAL_LAKE_DIR, MANIFEST_PATH, SITELINKS_PATH

log = logging.getLogger(__name__)

SOURCES = ("hourly_dump", "pageview_complete")
SORT_KEYS = [("lang", "ascending"), ("title", "ascending"), ("ts_hour_start", "ascending")]
ROW_GROUP_SIZE = 1_000_000


class StoreConflict(Exception):
    """Another writer committed after the revision we based our changes on."""


def day_path(ts: datetime) -> str:
    """Repo-relative path of the daily Parquet file holding the hour starting at ``ts``."""
    return f"data/hourly/year={ts:%Y}/month={ts:%m}/day={ts:%d}.parquet"


def write_parquet(table: pa.Table, path: Path) -> int:
    """Write ``table`` as zstd-9 Parquet with ~1M-row row groups; returns the file size."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd", compression_level=9, row_group_size=ROW_GROUP_SIZE)
    return path.stat().st_size


def merge_day(existing: pa.Table | None, new: list[pa.Table]) -> pa.Table:
    """Day table with the hours of ``new`` replacing those hours in ``existing``, sorted."""
    parts = [t for t in new if t.num_rows]
    hours = set()
    for t in new:
        hours.update(t["ts_hour_start"].unique().to_pylist())
    if existing is not None and existing.num_rows:
        keep = existing
        if hours:
            mask = pc.is_in(existing["ts_hour_start"], value_set=pa.array(sorted(hours), existing.schema.field("ts_hour_start").type))
            keep = existing.filter(pc.invert(mask))
        parts.insert(0, keep)
    if not parts:
        return new[0] if new else existing
    schema = parts[-1].schema
    return pa.concat_tables([p.cast(schema) for p in parts]).sort_by(SORT_KEYS)


def _key(ts: datetime) -> str:
    return f"{ts:%Y-%m-%dT%H:00:00Z}"


def _parse_key(key: str) -> datetime:
    return datetime.strptime(key, "%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Manifest:
    """Every hour present (path, rows, source, ingestion time) and every day file (rows, bytes)."""

    hours: dict[str, dict] = field(default_factory=dict)
    files: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def from_json(cls, text: str | None) -> Manifest:
        if not text:
            return cls()
        doc = json.loads(text)
        return cls(hours=dict(doc.get("hours", {})), files=dict(doc.get("files", {})))

    def to_json(self) -> str:
        doc = {
            "schema_version": 2,
            "updated_at": f"{utcnow():%Y-%m-%dT%H:%M:%SZ}",
            "hour_count": len(self.hours),
            "total_bytes": sum(f["bytes"] for f in self.files.values()),
            "files": dict(sorted(self.files.items())),
            "hours": dict(sorted(self.hours.items())),
        }
        return json.dumps(doc, indent=1) + "\n"

    def present(self) -> set[datetime]:
        return {_parse_key(k) for k in self.hours}

    def has(self, ts: datetime) -> bool:
        return _key(ts) in self.hours

    def add(self, ts: datetime, rows: int, source: str, ingested_at: datetime | None = None) -> None:
        if source not in SOURCES:
            raise ValueError(f"unknown source {source!r}")
        self.hours[_key(ts)] = {
            "path": day_path(ts), "rows": rows, "source": source,
            "ingested_at": f"{(ingested_at or utcnow()):%Y-%m-%dT%H:%M:%SZ}",
        }

    def set_file(self, path: str, rows: int, size: int) -> None:
        self.files[path] = {"rows": rows, "bytes": size, "updated_at": f"{utcnow():%Y-%m-%dT%H:%M:%SZ}"}

    def merge(self, other: Manifest) -> None:
        """Apply ``other`` on top of this manifest (its entries win)."""
        self.hours.update(other.hours)
        self.files.update(other.files)


def expected_hours(now: datetime, window_hours: int) -> list[datetime]:
    """Hour starts in the last ``window_hours`` whose hour has fully ended by ``now``."""
    last = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    return [last - timedelta(hours=i) for i in range(window_hours)][::-1]


def missing_hours(manifest: Manifest, expected: list[datetime]) -> list[datetime]:
    """Expected hours not yet in the manifest, oldest first."""
    present = manifest.present()
    return sorted(ts for ts in expected if ts not in present)


class Store(Protocol):
    def head(self) -> str | None: ...
    def read_manifest(self, revision: str | None = None) -> Manifest: ...
    def fetch(self, repo_path: str, dest_dir: Path, revision: str | None = None) -> Path | None: ...
    def commit(self, files: dict[str, Path], delta: Manifest, message: str, parent: str | None = None) -> None: ...


def write_hours(store: Store, tables: dict[datetime, tuple[pa.Table, str]], message: str,
                overwrite: bool = False, attempts: int = 10) -> list[datetime]:
    """Merge hourly tables into their day files and commit them with the manifest, atomically.

    ``tables`` maps hour start -> (table, source). Hours already in the manifest are skipped
    unless ``overwrite``. Returns the hours actually written.
    """
    for attempt in range(attempts):
        rev = store.head()
        manifest = store.read_manifest(rev)
        todo = {ts: v for ts, v in tables.items() if overwrite or not manifest.has(ts)}
        if not todo:
            return []
        by_day: dict[str, list[datetime]] = defaultdict(list)
        for ts in todo:
            by_day[day_path(ts)].append(ts)
        delta = Manifest()
        with tempfile.TemporaryDirectory() as tmp:
            files = {}
            for path, hours in sorted(by_day.items()):
                src = store.fetch(path, Path(tmp) / "in", rev) if path in manifest.files else None
                existing = pq.read_table(src) if src else None
                merged = merge_day(existing, [todo[ts][0] for ts in hours])
                out = Path(tmp) / "out" / path
                size = write_parquet(merged, out)
                files[path] = out
                delta.set_file(path, merged.num_rows, size)
                for ts in hours:
                    delta.add(ts, rows=todo[ts][0].num_rows, source=todo[ts][1])
            try:
                store.commit(files, delta, message, parent=rev)
                return sorted(todo)
            except StoreConflict:
                log.warning("lake changed while writing (attempt %d), merging again", attempt + 1)
                time.sleep(random.uniform(1, 4) * (attempt + 1))  # jitter: parallel backfill jobs
    raise RuntimeError(f"could not commit after {attempts} attempts: {message}")


class LocalStore:
    """A directory with the same layout as the Hub repo (offline runs, tests)."""

    def __init__(self, root: Path = LOCAL_LAKE_DIR) -> None:
        self.root = Path(root)

    def head(self) -> str | None:
        return None

    def read_manifest(self, revision: str | None = None) -> Manifest:
        p = self.root / MANIFEST_PATH
        return Manifest.from_json(p.read_text() if p.exists() else None)

    def fetch(self, repo_path: str, dest_dir: Path, revision: str | None = None) -> Path | None:
        p = self.root / repo_path
        return p if p.exists() else None

    def commit(self, files: dict[str, Path], delta: Manifest, message: str, parent: str | None = None) -> None:
        for repo_path, src in files.items():
            dst = self.root / repo_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            if Path(src).resolve() != dst.resolve():
                shutil.copyfile(src, dst)
        m = self.read_manifest()
        m.merge(delta)
        (self.root / MANIFEST_PATH).parent.mkdir(parents=True, exist_ok=True)
        (self.root / MANIFEST_PATH).write_text(m.to_json())
        log.info("local commit: %s (%d files)", message, len(files))


def hf_token() -> str | None:
    """HF_TOKEN env var, else the token saved by ``huggingface-cli login``."""
    from huggingface_hub import get_token

    return os.environ.get("HF_TOKEN") or get_token()


class HFStore:
    """The public Hugging Face dataset repo. Fails loudly on any upload error."""

    def __init__(self, repo_id: str = HF_REPO_ID, token: str | None = None, create: bool = False) -> None:
        from huggingface_hub import HfApi

        self.repo_id = repo_id
        self.token = token or hf_token()
        self.api = HfApi(token=self.token)
        if create:
            if not self.token:
                raise RuntimeError("HF token missing: set HF_TOKEN or run `huggingface-cli login`")
            # fine-grained tokens without "create repos" get 403 even with exist_ok, so check first
            if not self.api.repo_exists(repo_id, repo_type="dataset"):
                self.api.create_repo(repo_id, repo_type="dataset", private=False)

    def head(self) -> str:
        return self.api.dataset_info(self.repo_id).sha

    def used_storage(self) -> int:
        """Bytes the repo occupies on the Hub, including the history of large files."""
        return self.api.dataset_info(self.repo_id, expand=["usedStorage"]).used_storage

    def delete_prefix(self, prefix: str, message: str) -> list[str]:
        """Delete every file under ``prefix`` in one commit; returns the deleted paths."""
        from huggingface_hub import CommitOperationDelete

        paths = [p for p in self.api.list_repo_files(self.repo_id, repo_type="dataset") if p.startswith(prefix)]
        if paths:
            self.api.create_commit(self.repo_id, repo_type="dataset", commit_message=message,
                                   operations=[CommitOperationDelete(path_in_repo=p) for p in paths])
        return paths

    def squash_history(self, message: str) -> None:
        """Rewrite the repo history into a single commit (frees storage held by old file versions).

        Irreversible: earlier revisions become unreachable. Writers using an older parent commit get
        a conflict and redo their merge (write_hours), so nothing in flight is lost.
        """
        self.api.super_squash_history(self.repo_id, repo_type="dataset", commit_message=message)

    def upload_card(self, path: Path) -> None:
        """Upload the dataset card (the repo README) without touching data or manifest."""
        self.api.upload_file(path_or_fileobj=str(path), path_in_repo="README.md", repo_id=self.repo_id,
                             repo_type="dataset", commit_message="docs: update dataset card")

    def read_manifest(self, revision: str | None = None) -> Manifest:
        p = self.fetch(MANIFEST_PATH, None, revision or self.head())
        return Manifest.from_json(p.read_text() if p else None)

    def fetch(self, repo_path: str, dest_dir: Path | None, revision: str | None = None) -> Path | None:
        from huggingface_hub import hf_hub_download
        from huggingface_hub.utils import EntryNotFoundError

        try:
            return Path(hf_hub_download(self.repo_id, repo_path, repo_type="dataset", token=self.token,
                                        revision=revision, local_dir=dest_dir))
        except EntryNotFoundError:
            return None

    def commit(self, files: dict[str, Path], delta: Manifest, message: str, parent: str | None = None) -> None:
        """One Hub commit with the files and the merged manifest. Raises StoreConflict on a race."""
        from huggingface_hub import CommitOperationAdd
        from huggingface_hub.utils import HfHubHTTPError

        if not self.token:
            raise RuntimeError("HF token missing: set HF_TOKEN or run `huggingface-cli login`")
        base = parent or self.head()
        manifest = self.read_manifest(base)
        manifest.merge(delta)
        ops = [CommitOperationAdd(path_in_repo=p, path_or_fileobj=str(src)) for p, src in files.items()]
        ops.append(CommitOperationAdd(path_in_repo=MANIFEST_PATH, path_or_fileobj=manifest.to_json().encode()))
        try:
            info = self.api.create_commit(self.repo_id, operations=ops, commit_message=message,
                                          repo_type="dataset", parent_commit=base)
        except HfHubHTTPError as e:
            if getattr(e.response, "status_code", None) in (409, 412):
                raise StoreConflict(str(e)) from e
            raise
        log.info("hf commit %s: %s (%d files)", info.oid[:8], message, len(files))


def sync_to_local(hf: HFStore, local: LocalStore, since: datetime, include_sitelinks: bool = True) -> dict:
    """Mirror day files (from ``since``), the manifest and sitelinks from the Hub into the local lake.

    A file is downloaded only if it is missing locally or its size differs from the manifest.
    Returns counts of downloaded and skipped files.
    """
    from huggingface_hub import hf_hub_download

    rev = hf.head()
    manifest = hf.read_manifest(rev)
    wanted = sorted(p for p in manifest.files if _day_of(p) >= since.date())
    paths = wanted + ([SITELINKS_PATH] if include_sitelinks else [])
    done = skipped = 0
    for path in paths:
        dst = local.root / path
        expected = manifest.files.get(path, {}).get("bytes")
        if dst.exists() and (expected is None or dst.stat().st_size == expected):
            skipped += 1
            continue
        hf_hub_download(hf.repo_id, path, repo_type="dataset", revision=rev, token=hf.token,
                        local_dir=local.root, force_download=True)
        done += 1
        log.info("synced %s", path)
    (local.root / MANIFEST_PATH).parent.mkdir(parents=True, exist_ok=True)
    (local.root / MANIFEST_PATH).write_text(manifest.to_json())
    return {"downloaded": done, "up_to_date": skipped, "revision": rev, "hours": len(manifest.hours)}


def _day_of(path: str):
    """``data/hourly/year=2026/month=10/day=07.parquet`` -> date(2026, 10, 7)."""
    from datetime import date

    parts = dict(p.split("=") for p in path.removesuffix(".parquet").split("/") if "=" in p)
    return date(int(parts["year"]), int(parts["month"]), int(parts["day"]))


def open_store(local: bool = False) -> Store:
    """Hub store by default; ``local=True`` writes to data/lake/ instead."""
    if local:
        return LocalStore()
    return HFStore(create=True)
