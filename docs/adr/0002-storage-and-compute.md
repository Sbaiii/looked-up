# 0002 — Storage on Hugging Face Datasets, compute on GitHub Actions

- Status: accepted; retention refined by ADR 0007, layout by ADR 0008
- Date: 2026-10-07
- Evidence: [feasibility §6](../feasibility.md)

## Context

Budget is €0. Storing everything (top-50 Wikipedias, every row) costs ≈ 132–230 GB/year of Parquet. The hourly
job needs ≈ 3 s of processing plus a ≈ 55 MB download. Wikimedia keeps every raw hourly file since 2015 (CC0).

## Decision

- **Do not archive raw data.** Store a derived lake: one compacted Parquet per day sorted by
  (lang, title, hour), zstd 9, rows with ≥ 5 views/hour, plus daily rollups and spike tables (≈ 15–25 GB/year).
- **Host it as a public Hugging Face dataset**, uploaded once per day. DuckDB reads it with `hf://`.
- **Run jobs on GitHub Actions** (public repo, free runners): an hourly idempotent catch-up job at :20 and a daily
  compaction and upload job.

## Alternatives rejected

- Cloudflare R2 / Backblaze B2: a 10 GB ceiling (under one year), and R2 needs a payment method, so overage risk.
- GitHub Releases: a 2 GiB per-file blob store with no query path, and a ToS gray area for a data lake.

## Consequences

- HF public storage is "best-effort": stay well under ~50 GB, write a dataset card, keep R2 as a hot-window fallback.
- Cron runs can be late, dropped, or disabled after 60 days of inactivity. Jobs must catch up on missed hours.
- No always-on process, so the live edit stream is out of scope until a free host exists.
