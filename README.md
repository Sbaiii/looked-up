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

**Ready to go live, waiting for the `HF_TOKEN` secret.** The pipeline is built and tested, and a local lake (1–7 Oct)
is migrated to the final daily layout. Once the token is set, GitHub Actions adds each new hour of 30 Wikipedias to
the public dataset [`Sbaiii/looked-up`](https://huggingface.co/datasets/Sbaiii/looked-up), and a parallel
backfill fills the previous 90 days. No analytics yet: spike detection, comparisons and the daily briefing come next.

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
FROM 'hf://datasets/Sbaiii/looked-up/data/hourly/year=2026/month=10/day=06.parquet'
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
```

Add `--local` to write to `data/lake/` instead of Hugging Face. Workflows:
[`hourly.yml`](.github/workflows/hourly.yml) (every hour at :45),
[`wikidata-monthly.yml`](.github/workflows/wikidata-monthly.yml),
[`backfill.yml`](.github/workflows/backfill.yml) (manual, parallel date chunks) and
[`tests.yml`](.github/workflows/tests.yml). They need the `HF_TOKEN` repository secret; without it the scheduled jobs skip with a warning. Pipelines only
write to the lake on Hugging Face and never commit to this repository (enforced by `tests/test_no_git_in_pipeline.py`).

The Phase 0 scripts are still in [`spike/`](spike/) (see `docs/feasibility.md`).

Every request identifies itself with a descriptive User-Agent, as Wikimedia requires. Data: Wikimedia pageviews and
Wikidata, CC0.
