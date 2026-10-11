# Phase 0 spike

Throwaway feasibility scripts, kept because [docs/feasibility.md](../docs/feasibility.md) quotes their measurements.
They are rough but run: `.venv/bin/python spike/<script>.py`. Every request uses the shared User-Agent in
`common.py`.

| Script | Question |
|---|---|
| `q1_hourly_dumps.py` | Hourly pageview dumps: size, shape, publication lag, DuckDB load, Parquet size |
| `q1b_compaction.py` | Does compacting several hours into one Parquet file shrink storage? |
| `q1c_language_set.py` | Which languages to keep, judged on a full day rather than one hour |
| `q1d_pageview_complete.py` | pageview_complete daily files: lag, size, granularity |
| `q2_rest_api.py` | The pageviews REST API: top articles, per-article history, geography |
| `q3_edit_stream.py` | A sample of the EventStreams edit firehose |
| `q4_wikidata.py` | Unifying articles across languages through Wikidata |
| `q4b_join_coverage.py` | What share of views joins onto a Wikidata item by (site, title)? |
| `q5_spike_test.py` | Do pageview spikes precede or match the news? |
| `q5a_current_events.py` | The last 60 Current events portal pages, grepped for candidate events |
| `q5b_analyse.py` | Detection analysis on the q5 hourly CSVs, without downloads |
| `q5c_edit_lead.py` | How fast editors react compared with the pageview dumps |
| `q6_hourly_job.py` | The full hourly job, timed end to end |
| `q6b_storage_tiers.py` | How small the stored lake can be: derived tiers per year |
| `q6c_full_day_compaction.py` | Compacting 24 hourly files into one day file, and its timing |
