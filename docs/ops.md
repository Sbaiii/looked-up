# Operations

How Looked Up runs, where things live, and what to do when something breaks.

## Where things live

| What | Where | Notes |
|---|---|---|
| Lake (source of truth) | Hugging Face dataset [`Sbaiiiiii/looked-up`](https://huggingface.co/datasets/Sbaiiiiii/looked-up) | day files, manifest, sitelinks, spikes, events, `latest.json` |
| Local data | `LOOKEDUP_DATA_DIR`, default **`~/looked-up-data`** (outside iCloud, ADR 0016) | `lake/` (mirror via `cli sync`), `warehouse/lookedup.duckdb`, `eval/`, `baselines/`, `tmp/duckdb/` |
| DuckDB spill | `~/looked-up-data/tmp/duckdb`, **capped at 20 GiB** (`LOOKEDUP_DUCKDB_MAX_TEMP`) | applies to every connection, including the dbt profile |
| Python env | `.venv` → `.venv.nosync` (iCloud does not sync `*.nosync`) | recreate with `python3.12 -m venv .venv.nosync && .venv/bin/pip install -e ".[dev,warehouse]"` |
| Production baselines | GitHub Actions cache, key `baselines-YYYY-MM-DD` (ADR 0018) | never uploaded to the Hub |

> The repository itself still sits in `~/Desktop`, which iCloud may evict. Moving it to e.g. `~/Projects/looked-up`
> is recommended. After moving, recreate `.venv.nosync`.

To move an old in-repo `data/` directory: `python -m lookedup.cli relocate-data` (use `--skip raw` for regenerable
caches). Re-create the lake mirror with `python -m lookedup.cli sync --from 2026-07-09`.

## Workflows

| Workflow | Trigger | Does |
|---|---|---|
| `hourly.yml` | cron **`17 * * * *`**, `workflow_dispatch`, and dispatched by `trigger.yml` | ingest missing hours of the last **7 days** (≤ 12/run), restore baselines from the cache, score (≤ 12 hours/run), save recomputed baselines on a cache miss, then `cli app-export` (`data/app/`, ADR 0022) |
| `trigger.yml` | `repository_dispatch` type `hourly-tick` | dispatches `hourly.yml`; the second path for when GitHub drops scheduled runs (ADR 0017) |
| `daily.yml` | cron `30 3 * * *`, `workflow_dispatch` (`retrain` input) | build today's baselines from the previous 28 day files, save them to the Actions cache; **Mondays: retrain the forecast models** (`cli forecast-retrain`, ADR 0029) |
| `wikidata-monthly.yml` | cron `30 6 8 * *` | rebuild `data/wikidata/sitelinks.parquet` |
| `pages.yml` | push to `app/**`, `workflow_dispatch` | deploy `app/` to GitHub Pages ([sbaiii.github.io/looked-up](https://sbaiii.github.io/looked-up/)); data is read from the Hub at runtime, so hourly updates need no redeploy |
| `hub-maintenance.yml` | cron `41 4 2 * *`, `workflow_dispatch` | **squash the dataset repo's history** (`cli hub --squash`) and report storage |
| `backfill.yml` | manual | parallel resumable backfill from `pageview_complete` |
| `tests.yml` | push, PR | pytest |

All workflows have `contents: read`; pipelines write only to the Hub. When `HF_TOKEN` is missing, the scheduled jobs
skip with a warning.

## External pinger (cron-job.org)

GitHub ran the old `:45` schedule only twice in ≈ 10 hours, so an external free pinger gives a second, independent
trigger. Pick **one** of the two options. **Option B is recommended** because its token can't touch code.

### 1. Create a fine-grained personal access token

GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**:

- **Token name:** `looked-up-pinger`
- **Expiration:** 90 days, or up to 1 year (set a reminder to rotate it)
- **Resource owner:** `Sbaiii`
- **Repository access:** *Only select repositories* → `Sbaiii/looked-up`
- **Repository permissions:**
  - Option A (`repository_dispatch` → `trigger.yml`): **Contents: Read and write** (required by the
    `POST /repos/{owner}/{repo}/dispatches` endpoint). Metadata: Read is added automatically.
  - Option B (direct `workflow_dispatch` of `hourly.yml`): **Actions: Read and write** only. Metadata: Read is added
    automatically.
- Generate and copy the token (`github_pat_…`). It is shown once.

Contents write would also let the token push to the repository, which is why Option B is preferred.

### 2. Create the cron job

[cron-job.org](https://cron-job.org) → sign up (free) → **Create cronjob**:

- **Title:** `looked-up hourly`
- **URL:**
  - Option A: `https://api.github.com/repos/Sbaiii/looked-up/dispatches`
  - Option B: `https://api.github.com/repos/Sbaiii/looked-up/actions/workflows/hourly.yml/dispatches`
- **Execution schedule:** every hour at minute **40**. That is offset from GitHub's own `:17`, so the two paths
  rarely overlap.
- **Advanced → Request method:** `POST`
- **Advanced → Headers:**
  - `Accept: application/vnd.github+json`
  - `Authorization: Bearer github_pat_…`
  - `X-GitHub-Api-Version: 2022-11-28`
  - `Content-Type: application/json`
  - `User-Agent: looked-up-pinger`
- **Advanced → Request body:**
  - Option A: `{"event_type": "hourly-tick"}`
  - Option B: `{"ref": "main"}`
- Save, then **Test run**. Expect **HTTP 204 No Content**.
- Check the Actions tab:
  - Option A: an `external trigger` run, followed by an `hourly ingest` run (event `workflow_dispatch`);
  - Option B: an `hourly ingest` run directly.

Duplicates are harmless: the hourly job is idempotent, and its concurrency group queues overlapping runs.

## Baselines and Hub storage

- Baselines: about 9.9 M slots and 128 MB per day, built in about 5 minutes on a runner. They live only in the
  Actions cache. A cache miss costs one recomputation inside the hourly job (newest missing day only).
- Hub storage, 2026-10-09:
  - **4,962,899,645 bytes before** (101 commits).
  - After removing `data/baselines/` and one `super_squash_history`: **1 commit**, all 104 files intact.
    The first hourly run afterwards added 2 commits (ingest, score) and no baselines.
  - Read again 2026-10-09 07:00 UTC: 4,971,796,434 bytes, not yet recounted after the squash.
  - The storage figure updates up to 36 h after a squash. Read it with
    `python -m lookedup.cli hub` (no flags just reports storage).
- **Risk of squashing:** the dataset repo's history is rewritten into one commit. Old revisions and links pinned to
  commit hashes stop working, and it can't be undone. Current data is untouched.

## Local disk (2026-10-09, `df -h /Users`)

| When | Used | Free |
|---|---:|---:|
| Before ADR 0016 (2026-10-08 21:23 UTC, lake and spill inside the repo) | 395 GiB | 30 GiB |
| After moving to `~/looked-up-data`, spill capped (2026-10-09 07:00 UTC, lake mirror re-sync in progress) | 372 GiB | 51 GiB |

The old in-repo `data/raw` (regenerable caches) and `.venv.icloud-old` are leftovers that can be deleted by hand.

## Runbook

| Symptom | Check | Fix |
|---|---|---|
| No new hours on the Hub | Actions → `hourly ingest` runs in the last hours | `gh workflow run hourly.yml`; set up or check the pinger |
| `latest.json` stale | `data/scoring_state.json`, and the hourly log for "no baselines" | `gh workflow run daily.yml` (rebuilds and caches baselines) |
| Local reads time out | `stat -f %b <file>` = 0 means an iCloud-evicted file | keep data in `~/looked-up-data`; move the repo out of `~/Desktop` |
| Disk filling during a DuckDB run | `du -sh ~/looked-up-data/tmp/duckdb` | capped at 20 GiB by design; lower `LOOKEDUP_DUCKDB_MAX_TEMP` if needed |
| App shows stale data | `data/app/today.json` `generated_at` on the Hub; the hourly log's "Export app data" step | `gh workflow run hourly.yml`; full rebuild: `python -m lookedup.cli app-export --backfill --upload` (needs the warehouse and a lake mirror) |
| Forecasts missing in the app | `data/models/models.json` on the Hub; the hourly log for "forecasts failed" | `gh workflow run daily.yml -f retrain=true`; the export never fails because of forecasts |
| Hub storage growing | `python -m lookedup.cli hub` | `gh workflow run hub-maintenance.yml` |
