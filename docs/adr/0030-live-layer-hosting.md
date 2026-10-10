# 0030 — Hosting the live layer without a paid Space

- Status: accepted (temporary; revisit if the budget changes)
- Date: 2026-10-10

## Context

The brief asked for a free Hugging Face Space (Docker SDK), `Sbaiiiiii/looked-up-live`. Creating it returned:

> 402 Payment Required: *Static Spaces are free for everyone, but hosting Gradio and Docker Spaces on free cpu-basic
> requires a PRO subscription.*

The budget is €0, and the other always-on free hosts need a card or a new account: Fly.io, Koyeb, Render (which also
sleeps after 15 minutes), Oracle Cloud and Cloud Run.

## Decision

- **The code stays deployable as a Space.**
  - `live/` is a self-contained FastAPI service with a `Dockerfile` (boots in about 1 s; 39 MB resident memory measured in
    the local run). It serves `/live.json`, `/stats.json`, `/bursts.json` and `/health`, with CORS for every origin
    and a 15-second cache.
  - `space.yml` pushes `live/` to the Space on every change. It only warns while the Space doesn't exist.
- **Until then it runs in GitHub Actions shifts** (`live.yml`, `lookedup_live.shift`):
  - Each job consumes the stream for 5 h 42 min.
  - Every 5 minutes it publishes `data/live/live.json`, `data/live/stats.json` and the day's bursts
    (`data/live/bursts/YYYY-MM-DD.jsonl`) to the lake.
  - Every 30 minutes, and at the end, it writes `data/live/state.json.gz` and `qids.json`.
  - **No user data:** counts and edit timestamps only.
  - **Continuity:**
    - The concurrency group `live-layer` keeps one shift running and one queued.
    - The hourly cron, and every hourly ingest run (which the external pinger keeps reliable), add a queued shift.
    - The next shift restores the state and resumes with `Last-Event-ID`, so no events are lost, only ≈ 1 minute of
      latency at the handover.
- **The app reads the lake files** (the Hub serves CORS) instead of the Space URL.
- **Being honest about gaps.** `status.gap_minutes` measures how much of the 60-minute window the stream didn't
  cover. The app also treats a `generated_at` older than 15 minutes as "resting" and shows a quiet line.

## Consequences

- **Latency.** The app sees the live layer up to 5 minutes late (the publish interval), plus the stream's own
  ≈ 30 s, instead of the 15 s of the Space cache. That is still about 3 hours ahead of pageviews.
- **Commits.** About 288 Hub commits a day go to the dataset. The monthly squash (ADR 0018) keeps history bounded.
- **Terms of use.** GitHub Actions minutes are free for public repositories, and the job is part of this project's
  data pipeline. Still, a near-continuous job leans on that policy. If GitHub objects, or a Space becomes
  affordable, switch:
  - create the Space, and `space.yml` deploys it;
  - point the pinger at `https://sbaiiiiii-looked-up-live.hf.space/health`;
  - disable `live.yml`.
- **Sleep.** A free Space (once on PRO) sleeps after 48 h without traffic, and its disk is not persistent. The
  hourly pinger keeps it awake, and the cold-start replay (`since` = 60 min ago) refills the window.
