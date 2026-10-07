"""Lake storage: Parquet files, the manifest, and the Hugging Face / local backends (D5).

Layout (identical locally and on the Hub)::

    data/hourly/year=YYYY/month=MM/day=DD/hour=HH.parquet
    data/wikidata/sitelinks.parquet
    data/manifest.json

The manifest lists every hour present. Writers commit data files and the updated
manifest in ONE commit, with optimistic concurrency on the Hub (``parent_commit``):
if someone else committed in between, we re-read the manifest, merge, and retry.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

import pyarrow as pa
import pyarrow.parquet as pq

from lookedup.dumps import utcnow
from lookedup.settings import HF_REPO_ID, LOCAL_LAKE_DIR, MANIFEST_PATH

log = logging.getLogger(__name__)

SOURCES = ("hourly_dump", "pageview_complete")


def hour_path(ts: datetime) -> str:
    """Repo-relative path of the Parquet file for the hour starting at ``ts``."""
    return f"data/hourly/year={ts:%Y}/month={ts:%m}/day={ts:%d}/hour={ts:%H}.parquet"


def write_parquet(table: pa.Table, path: Path) -> int:
    """Write ``table`` as zstd Parquet; returns the file size in bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd", compression_level=9, row_group_size=500_000)
    return path.stat().st_size


def _key(ts: datetime) -> str:
    return f"{ts:%Y-%m-%dT%H:00:00Z}"


def _parse_key(key: str) -> datetime:
    return datetime.strptime(key, "%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Manifest:
    """Every hour present in the lake: path, row count, bytes, source, ingestion time."""

    hours: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def from_json(cls, text: str | None) -> Manifest:
        if not text:
            return cls()
        return cls(hours=dict(json.loads(text).get("hours", {})))

    def to_json(self) -> str:
        doc = {
            "schema_version": 1,
            "updated_at": f"{utcnow():%Y-%m-%dT%H:%M:%SZ}",
            "hour_count": len(self.hours),
            "hours": dict(sorted(self.hours.items())),
        }
        return json.dumps(doc, indent=1) + "\n"

    def present(self) -> set[datetime]:
        return {_parse_key(k) for k in self.hours}

    def has(self, ts: datetime) -> bool:
        return _key(ts) in self.hours

    def add(self, ts: datetime, rows: int, size: int, source: str, ingested_at: datetime | None = None) -> None:
        if source not in SOURCES:
            raise ValueError(f"unknown source {source!r}")
        self.hours[_key(ts)] = {
            "path": hour_path(ts), "rows": rows, "bytes": size, "source": source,
            "ingested_at": f"{(ingested_at or utcnow()):%Y-%m-%dT%H:%M:%SZ}",
        }

    def merge(self, entries: dict[str, dict]) -> None:
        """Apply new entries on top of this manifest (new entries win)."""
        self.hours.update(entries)


def expected_hours(now: datetime, window_hours: int) -> list[datetime]:
    """Hour starts in the last ``window_hours`` whose hour has fully ended by ``now``."""
    last = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    return [last - timedelta(hours=i) for i in range(window_hours)][::-1]


def missing_hours(manifest: Manifest, expected: list[datetime]) -> list[datetime]:
    """Expected hours not yet in the manifest, oldest first."""
    present = manifest.present()
    return sorted(ts for ts in expected if ts not in present)


class Store(Protocol):
    def read_manifest(self) -> Manifest: ...
    def commit(self, files: dict[str, Path], entries: dict[str, dict], message: str) -> None: ...
    def fetch(self, repo_path: str, dest_dir: Path) -> Path | None: ...


class LocalStore:
    """A directory with the same layout as the Hub repo (offline runs, tests)."""

    def __init__(self, root: Path = LOCAL_LAKE_DIR) -> None:
        self.root = Path(root)

    def read_manifest(self) -> Manifest:
        p = self.root / MANIFEST_PATH
        return Manifest.from_json(p.read_text() if p.exists() else None)

    def commit(self, files: dict[str, Path], entries: dict[str, dict], message: str) -> None:
        for repo_path, src in files.items():
            dst = self.root / repo_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            if Path(src).resolve() != dst.resolve():
                shutil.copyfile(src, dst)
        m = self.read_manifest()
        m.merge(entries)
        (self.root / MANIFEST_PATH).parent.mkdir(parents=True, exist_ok=True)
        (self.root / MANIFEST_PATH).write_text(m.to_json())
        log.info("local commit: %s (%d files)", message, len(files))

    def fetch(self, repo_path: str, dest_dir: Path) -> Path | None:
        p = self.root / repo_path
        return p if p.exists() else None


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
            self.api.create_repo(repo_id, repo_type="dataset", private=False, exist_ok=True)

    def _head(self) -> str:
        return self.api.dataset_info(self.repo_id).sha

    def _manifest_at(self, revision: str) -> Manifest:
        from huggingface_hub import hf_hub_download
        from huggingface_hub.utils import EntryNotFoundError

        try:
            p = hf_hub_download(self.repo_id, MANIFEST_PATH, repo_type="dataset", revision=revision,
                                token=self.token)
        except EntryNotFoundError:
            return Manifest()
        return Manifest.from_json(Path(p).read_text())

    def read_manifest(self) -> Manifest:
        return self._manifest_at(self._head())

    def commit(self, files: dict[str, Path], entries: dict[str, dict], message: str, retries: int = 5) -> None:
        from huggingface_hub import CommitOperationAdd
        from huggingface_hub.utils import HfHubHTTPError

        if not self.token:
            raise RuntimeError("HF token missing: set HF_TOKEN or run `huggingface-cli login`")
        for attempt in range(retries):
            head = self._head()
            manifest = self._manifest_at(head)
            manifest.merge(entries)
            ops = [CommitOperationAdd(path_in_repo=p, path_or_fileobj=str(src)) for p, src in files.items()]
            ops.append(CommitOperationAdd(path_in_repo=MANIFEST_PATH, path_or_fileobj=manifest.to_json().encode()))
            try:
                info = self.api.create_commit(self.repo_id, operations=ops, commit_message=message,
                                              repo_type="dataset", parent_commit=head)
                log.info("hf commit %s: %s (%d files)", info.oid[:8], message, len(files))
                return
            except HfHubHTTPError as e:
                status = getattr(e.response, "status_code", None)
                if status in (409, 412) and attempt < retries - 1:
                    log.warning("hf commit raced with another writer (HTTP %s), retrying", status)
                    time.sleep(2 * (attempt + 1))
                    continue
                raise

    def fetch(self, repo_path: str, dest_dir: Path) -> Path | None:
        from huggingface_hub import hf_hub_download
        from huggingface_hub.utils import EntryNotFoundError

        try:
            return Path(hf_hub_download(self.repo_id, repo_path, repo_type="dataset", token=self.token,
                                        local_dir=dest_dir))
        except EntryNotFoundError:
            return None


def open_store(local: bool = False) -> Store:
    """Hub store by default; ``local=True`` (or no token) writes to data/lake/ instead."""
    if local:
        return LocalStore()
    return HFStore(create=True)
