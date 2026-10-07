# looked-up

**What is humanity paying attention to, right now?** Looked Up reads Wikipedia's public
traffic across 300+ language editions — every pageview, published hourly, and every edit, as a
live stream — to detect attention spikes as they form, often before the news cycle catches up.
Articles are unified across languages through Wikidata, so "Lisbon", "Lisboa" and "リスボン"
count as one thing. The goal: a live globe of attention, comparisons between language
communities, a forecast of tomorrow's attention, and a daily briefing that begins
*"Today the world looked up…"*. Built with Python, DuckDB, dbt and Parquet on free
infrastructure only.

## Status

**Phase 0 — feasibility.** Nothing here is the product yet. The `spike/` scripts measure the
data sources (size, latency, structure, cost) and test whether pageview spikes really line up
with real-world events. Results and the GO / NO-GO call are in
[`docs/feasibility.md`](docs/feasibility.md).

## Running the spike

Requires Python 3.12 and ~10 GB of free disk (downloads land in the git-ignored `data/`).

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python spike/q1_hourly_dumps.py        # hourly dumps: size, lag, DuckDB, Parquet
.venv/bin/python spike/q1b_compaction.py         # per-hour vs compacted Parquet
.venv/bin/python spike/q1d_pageview_complete.py  # daily pageview_complete files
.venv/bin/python spike/q1c_language_set.py       # language ranking over a full day (after q5)
.venv/bin/python spike/q2_rest_api.py            # REST API: top, per-article, per-country
.venv/bin/python spike/q3_edit_stream.py         # 60 s of the live edit stream
.venv/bin/python spike/q4_wikidata.py [--full]   # Wikidata sitelinks (API + 1.9 GB dump)
.venv/bin/python spike/q4b_join_coverage.py      # share of pageviews that map to a QID
.venv/bin/python spike/q5a_current_events.py     # candidate events from Portal:Current events
.venv/bin/python spike/q5_spike_test.py          # do spikes match real events? (~6 GB download)
.venv/bin/python spike/q5b_analyse.py            # detectors and per-language delays
.venv/bin/python spike/q5c_edit_lead.py          # how fast editors reacted
.venv/bin/python spike/q6_hourly_job.py --fresh  # end-to-end hourly job timing
.venv/bin/python spike/q6b_storage_tiers.py      # yearly storage per retention tier
.venv/bin/python spike/q6c_full_day_compaction.py # one real day, 24 hours -> 1 file
```

Run `q1_hourly_dumps.py` first; later scripts reuse its downloads and its language list.
Every request identifies itself with a descriptive User-Agent, as Wikimedia requires.

Data: Wikimedia pageviews and Wikidata, CC0.
