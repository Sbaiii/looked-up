# 0016 — Keep data outside the repository and iCloud; cap DuckDB spill

- Status: accepted
- Date: 2026-10-09

## Context

- The repository lives in `~/Desktop`, which macOS syncs to iCloud with "Optimise Mac Storage". On 2026-10-09:
  - **267 of 268** local lake files, the evaluation Parquet and **162 of 163** raw files were *dataless* (evicted).
  - Reads timed out while iCloud restored them.
- The same happened to files inside `.venv`: importing `huggingface_hub` timed out.
- One DuckDB run spilled **44 GB** to its temp directory and filled the disk, which made iCloud evict even more.

## Decision

- `LOOKEDUP_DATA_DIR` (default **`~/looked-up-data`**, outside iCloud) holds the lake mirror, the evaluation files,
  the warehouse DuckDB, baselines and scratch. `python -m lookedup.cli relocate-data` moves the old in-repo `data/`
  there, copying file by file with a size check, and leaves `data/README.md` pointing to the new place.
- **The lake mirror is re-synced from the Hub** (`cli sync`) rather than restored from iCloud: the Hub is the source
  of truth, and restoring 4.3 GB through iCloud timed out. Regenerable download caches (`data/raw/`, 6.5 GB evicted)
  were left behind.
- **Every DuckDB connection** (`lookedup.db.connect`, the dbt profile, the evaluation and the scorer) sets
  `temp_directory = $LOOKEDUP_DATA_DIR/tmp/duckdb` and `max_temp_directory_size = 20GiB`
  (`LOOKEDUP_DUCKDB_MAX_TEMP`). A runaway query now fails instead of filling the disk.
- The virtual environment is `.venv.nosync` (iCloud ignores `*.nosync`), with `.venv` as a symlink to it.

## Consequences

- Free disk went from 55 GiB before to the figure reported in docs/ops.md after the move.
- The repository itself is still in `~/Desktop`. **Recommended: move the repo out of iCloud too** (e.g. to
  `~/Projects/looked-up`). Git objects and sources could be evicted as well.
- CI runners use the default `~/looked-up-data`, so no workflow change was needed.
