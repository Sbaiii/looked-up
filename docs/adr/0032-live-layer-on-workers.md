# 0032 — The live layer moves to a Cloudflare Worker, and its rules are tuned

- Status: accepted; **supersedes ADR 0030**
- Date: 2026-10-10
- Relates to: [docs/prereg_phase5.md](../prereg_phase5.md), [phase 5 results](../analysis/phase5_results.md)

## Context

- **GitHub Actions is out.** ADR 0030 ran the live layer as chained, near-continuous GitHub Actions jobs. That
  conflicts with GitHub's Actions usage terms and puts the hourly pipeline, which runs in the same repository, at
  risk.
- **H9 changed the framing.** Readers come first and editors confirm: the median edit burst lands 1 h 46 min after
  the first reading spike.
- **The first hours showed noisy rules.** 47 of 58 bursts were single authors writing new pages, and no item burst
  in two languages within 30 minutes.

## Decision 1: stop the Actions worker

- `live.yml` is now `workflow_dispatch` only, with a comment pointing here.
- The hourly job no longer queues it.
- All live runs were cancelled. The last one stopped publishing at 11:11 UTC.
- The app already treats a `live.json` older than 15 minutes as "resting" (tested), so it shows one quiet line.

## Decision 2: host the live layer on a Cloudflare Worker

Tried in the order of the brief:

1. **Hugging Face Space, Gradio SDK: not available.** Creating `Sbaiiiiii/looked-up-live` returned **402 Payment
   Required**: *"hosting Gradio and Docker Spaces on free cpu-basic requires a PRO subscription"*. That is the same
   answer as Docker (ADR 0030). Only static Spaces are free, and they can't run a consumer.
2. **Cloudflare Worker: adopted** (`worker/`, TypeScript). The Python `live/` package stays as the reference
   implementation. Both read the rules from **`config/live.yml`**: the Worker through the generated
   `src/rules.json`, and a vitest test fails if the two drift.

How the Worker works, and why:

- **It polls instead of streaming.** Workers can't hold an SSE connection.
  - A Cron Trigger every 5 minutes calls `list=recentchanges` on each of the 30 Wikipedias:
    `rcnamespace=0`, `rcshow=!bot`, `rctype=edit|new`, `rcdir=newer`, starting from the last edit it processed.
  - Busy wikis get 2–3 pages, the rest 1. A wiki that falls behind resumes where it stopped, so no edits are skipped.
  - Subrequests stay ≤ 41 of the free plan's 50, with up to 5 Wikidata calls per poll for QIDs.
- **State lives in Workers KV, one write per poll.** That is 288 writes a day, under the free tier's 1,000. All
  payloads are computed at read time; responses carry CORS (`*`) and a 15-second cache.
- **Distinct editors without storing users.** A 30-minute window spans several polls, so something must carry over.
  - Each article keeps, per 5-minute slot, an edit count and a **64-bit bitmap**.
  - An editor sets bit `FNV-1a(salt ‖ day ‖ user) mod 64`. The salt is a random Worker secret.
  - Distinct editors over a window are estimated by linear counting on the OR of the bitmaps. The estimate is exact
    in practice for the small counts that matter (3–5).
  - User names are never stored or logged.
- **Precision.** Windows are measured in 5-minute slots. A burst can be timed up to 5 minutes early relative to the
  exact Python rule.
- **Status fields.**
  - `status.events_per_s` means *recentchanges rows fetched per second*, not raw stream events. `kept_per_s` is the
    edits that pass the filter.
  - `gap_minutes` reports any minutes not covered by polls, e.g. when the account's cron stopped.
- **Risk.** The free plan allows **10 ms of CPU per invocation**. A poll parses about 30 small JSON responses and
  usually stays under it. If Cloudflare reports "exceeded CPU", split the wikis across two cron triggers (each
  doing 15). That doubles KV writes to 576 a day, still under the cap.
- **Snapshots.** The hourly job commits nothing for the live layer any more. Once a day, `daily.yml` runs `cli
  live-snapshot`, which copies yesterday's bursts and the stats from the Worker to the lake for H10
  (`data/live/bursts/DAY.jsonl`, `data/live/daily/DAY-stats.json`).

## Measured after deploying, and the fallback applied (2026-10-10)

- **Worker:** `https://looked-up-live.abdellahsbaisbai.workers.dev`. `wrangler tail`
  (`.github/workflows/worker-observe.yml`) showed polls using **47–54 ms of CPU** (wall time about 3.3 s):
  - 769–1,299 rows fetched;
  - a 470–530 KB state blob.
  - `/live.json` requests used 9–10 ms.
- **That is over the free plan's 10 ms,** although Cloudflare still returned `ok`. So the following was applied:
  - **The fallback:** two cron triggers (`*/5` and `2-59/5`), each polling 15 wikis. That makes 576 KV writes a day.
  - **No BigInt:** editor bitmaps are two 32-bit numbers. Distinct editors are computed only once an article has
    enough edits to qualify, which most never reach.
  - **A compact state:** slots are arrays, hourly counts are keyed by short title hashes, and articles that never
    burst keep 30 min instead of 60.
  - **An edge cache** for `/live.json` and `/stats.json` (15 s), so most requests skip the KV read and the parse.

## Decision 3: tune the rules (`config/live.yml`)

| Rule | Before | Now | Why |
|---|---|---|---|
| New-article burst | ≥ 5 edits in 60 min | ≥ 5 edits **by ≥ 2 distinct editors** in 60 min | single-author page creation is not attention (47 of the first 58 bursts) |
| Live event | same QID in ≥ 2 languages within **30 min** | within **120 min** | H9: editors follow readers by up to ≈ 2 h, so one story's bursts spread over that span |
| Single-language bursts shown | 3, most recent first | **top 5 by distinct editors, then edits** | rank by how many people are confirming |
| Hourly live-event counts | 24 h | **7 days** (`live_events_per_hour_week`) | to judge the new rules after a week |

## The hypotheses keep their definitions

`config/live_prereg_phase5.yml` freezes the pre-registered rules: a 30-minute live window and no editor minimum
for new pages. `lookedup/live_analysis.py` applies them through `prereg_rules()` for the H9 backtest and the H10
scoring.

One unavoidable difference for H10: the Worker produces new-article bursts only with ≥ 2 editors. Single-author
new-page bursts therefore no longer reach the scoring. That narrows H10's units slightly, and the H10 report must
note it.

## Secrets needed (created by the owner)

- `CLOUDFLARE_API_TOKEN`: an API token with **Account › Workers Scripts › Edit** and **Account › Workers KV Storage ›
  Edit** on the one account.
- `CLOUDFLARE_ACCOUNT_ID`.
- Repository **variable** `LIVE_URL`: the Worker URL, for the daily snapshot.

`worker.yml` creates the KV namespace and the `SALT` secret on its first deploy.
