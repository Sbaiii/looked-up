# looked-up

**What the world pays attention to, hour by hour, across languages.** Looked Up reads Wikipedia's public
pageview dumps, published every hour for more than 300 language editions. It turns them into a small, clean lake
that shows how much attention each topic gets, in which language communities, how it spreads and how long it
lasts. Articles are unified across languages through Wikidata, so "Lisbon", "Lisboa" and "リスボン" are one topic.

Pageviews are the **attention measure**. Edits (the live EventStreams feed) are the **fast signal**: editors react
within minutes, while the hourly dumps arrive ≈ 2 h after each hour. Edits come in a later phase. See the
[feasibility study](docs/feasibility.md) for the measurements behind these choices.

Built with Python, DuckDB and Parquet on free infrastructure only: GitHub Actions for compute, Hugging Face for
storage. CC0 data in, open data out.

## Status

**Live, scoring hourly.** GitHub Actions adds each newly published hour of 30 Wikipedias to the public dataset
[`Sbaiiiiii/looked-up`](https://huggingface.co/datasets/Sbaiiiiii/looked-up). After each ingest it scores the hour
for **attention events**: one entity spiking in ≥ 3 languages within 6 hours against its own 28-day baseline. It
writes `data/latest.json` with the last 24 h of events. A daily job at 03:30 UTC refreshes the baselines. The lake
holds every hour since 9 Jul 2026.

**Phase 2, in one paragraph.** The definitions were pre-registered before any code
([prereg](docs/prereg_phase2.md)) and evaluated against Wikipedia's Current events portal
([results](docs/analysis/phase2_results.md)):

- 84 days, 11,127 events.
- **All four hypotheses failed or were inconclusive.** Recall of portal entries was 4.3 %, and spread was slower for
  deaths than for sports.
- The portal and reading attention measure different things. 25 of the 30 largest events the portal misses are
  real, mostly deaths, which the portal's daily pages don't list, and the World Cup final.
- The analytics code lives in [`lookedup/analytics`](lookedup/analytics) and the dbt warehouse in
  [`warehouse/`](warehouse) ([docs](docs/warehouse.md)).

- Data model, layout and querying: [docs/data_model.md](docs/data_model.md)
- Decisions: [docs/adr/](docs/adr/)
- Languages: [config/languages.yml](config/languages.yml) (ranked by human article views; `top_n` sets how many are ingested)

## Query the lake

```bash
pip install -e .
python -m lookedup.cli top --lang fr --hour 2026-10-06T14:00     # top 20 articles, desktop vs mobile
```

Or straight from DuckDB, with no install beyond `duckdb`:

```sql
INSTALL httpfs; LOAD httpfs;
SELECT lang, title, views_desktop, views_mobile
FROM 'hf://datasets/Sbaiiiiii/looked-up/data/hourly/year=2026/month=10/day=06.parquet'
WHERE ts_hour_start = TIMESTAMP '2026-10-06 14:00'
ORDER BY views_desktop + views_mobile DESC LIMIT 20;
```

## Running the pipeline

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                                              # tests (also run in CI)

huggingface-cli login                                         # or export HF_TOKEN=... (never commit it)
.venv/bin/python -m lookedup.cli hourly                       # ingest missing hours of the last 72 h
.venv/bin/python -m lookedup.backfill --from 2026-07-09 --to 2026-10-06   # resumable backfill
.venv/bin/python -m lookedup.cli validate -n 3                # backfill vs hourly dumps, must be identical
.venv/bin/python -m lookedup.cli wikidata                     # rebuild Wikidata sitelinks
.venv/bin/python -m lookedup.cli languages                    # re-rank languages over the last 7 days
.venv/bin/python -m lookedup.cli push                         # upload a local lake (data/lake/) + dataset card
.venv/bin/python -m lookedup.cli sync --from 2026-07-09       # mirror the lake locally (for the warehouse)
.venv/bin/python -m lookedup.cli warehouse build              # dbt build: spikes, events, tests
.venv/bin/python -m lookedup.cli evaluate                     # pre-registered Phase 2 evaluation
.venv/bin/python -m lookedup.cli baselines && .venv/bin/python -m lookedup.cli score   # production scoring
```

Add `--local` to write to `data/lake/` instead of Hugging Face. Workflows:
[`hourly.yml`](.github/workflows/hourly.yml) (every hour at :45: ingest, then score),
[`daily.yml`](.github/workflows/daily.yml) (baselines, 03:30 UTC),
[`wikidata-monthly.yml`](.github/workflows/wikidata-monthly.yml),
[`backfill.yml`](.github/workflows/backfill.yml) (manual, parallel date chunks) and
[`tests.yml`](.github/workflows/tests.yml). They need the `HF_TOKEN` repository secret; without it the scheduled jobs skip with a warning. Pipelines only
write to the lake on Hugging Face and never commit to this repository (enforced by `tests/test_no_git_in_pipeline.py`).

The Phase 0 scripts are still in [`spike/`](spike/) (see `docs/feasibility.md`).

Every request identifies itself with a descriptive User-Agent, as Wikimedia requires. Data: Wikimedia pageviews and
Wikidata, CC0.
