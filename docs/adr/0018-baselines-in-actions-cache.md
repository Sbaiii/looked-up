# 0018 — Production baselines in the Actions cache; monthly Hub history squash

- Status: accepted; supersedes the baseline storage of ADR 0014
- Date: 2026-10-09

## Context

The daily baseline file (≈ 128 MB, 9.9 M slots) was committed to the Hub every day. The Hub keeps every version of
large files, so that alone would add ≈ 47 GB/year to the dataset repo's storage.

## Decision

- **Baselines never go to the Hub.** `cli baselines` writes `day=YYYY-MM-DD.parquet` into `LOOKEDUP_BASELINES_DIR`
  (default `~/looked-up-data/baselines`, last 3 days kept).
- `daily.yml` restores the Actions cache (`key: baselines-<date>`, `restore-keys: baselines-`), builds today's file
  and saves it under today's key.
- `hourly.yml` restores the same cache before scoring. **On a miss**, the scorer recomputes the newest missing day
  from the lake (at most one per run) and the workflow saves it to the cache. The hourly job never uploads baselines.
- The old `data/baselines/` file was deleted from the Hub.
- `hub-maintenance.yml` runs **monthly** and calls `HfApi.super_squash_history` (`cli hub --squash`), reporting
  storage before and after.

## Risks

- **Squashing rewrites the dataset repo's history into one commit.**
  - Old revisions and links pinned to old commit hashes stop working, and the operation is irreversible.
  - The current files (all day files, the manifest, sitelinks) are untouched.
  - Writers in flight hit a commit conflict and redo their merge (`write_hours`), so no data is lost.
- Hub storage figures update up to 36 h after a squash.
- Actions caches are evicted after 7 days without use, and the repo has a 10 GB cache budget. A cold cache just means
  one recomputation (≈ 5 min, 28 day-file downloads).

## Measured on 2026-10-09

- Hub `usedStorage` before: **4,962,899,645 bytes** (101 commits).
- After deleting the baseline file and squashing: 1 commit, 104 files intact. The storage figure was unchanged
  immediately; see docs/ops.md for the later reading.
