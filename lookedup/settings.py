"""Project-wide constants. Everything tunable lives here or in config/."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
LANGUAGES_FILE = CONFIG_DIR / "languages.yml"
DATASET_CARD = ROOT / "dataset" / "README.md"
NAMESPACES_FILE = CONFIG_DIR / "namespaces.json"

# Local working directories (git-ignored). Raw dumps are transient.
# Data lives OUTSIDE the repository (ADR 0016): the repo sits in ~/Desktop, which iCloud evicts.
# Override with LOOKEDUP_DATA_DIR (CI runners use their default home directory).
DATA_DIR = Path(os.environ.get("LOOKEDUP_DATA_DIR", Path.home() / "looked-up-data")).expanduser()
LEGACY_DATA_DIR = ROOT / "data"  # pre-ADR 0016 location; `cli relocate-data` moves it to DATA_DIR

# Production baselines (ADR 0018): a local directory persisted by GitHub Actions' cache, never the lake.
BASELINES_DIR = Path(os.environ.get("LOOKEDUP_BASELINES_DIR", DATA_DIR / "baselines")).expanduser()

# DuckDB spill: every connection writes temp files here and may never use more than this (ADR 0016).
DUCKDB_TEMP_DIR = Path(os.environ.get("LOOKEDUP_DUCKDB_TEMP_DIR", DATA_DIR / "tmp" / "duckdb")).expanduser()
DUCKDB_MAX_TEMP = os.environ.get("LOOKEDUP_DUCKDB_MAX_TEMP", "20GiB")
RAW_DIR = DATA_DIR / "raw"
LOCAL_LAKE_DIR = DATA_DIR / "lake"

USER_AGENT = "looked-up/0.1 (https://github.com/Sbaiii/looked-up; abdellahsbaisbai@gmail.com)"

DUMPS_BASE = "https://dumps.wikimedia.org/other/pageviews"
PVC_BASE = "https://dumps.wikimedia.org/other/pageview_complete"
REST_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
SITELINKS_DUMP = "https://dumps.wikimedia.org/wikidatawiki/latest/wikidatawiki-latest-wb_items_per_site.sql.gz"

HF_REPO_ID = os.environ.get("LOOKEDUP_HF_REPO", "Sbaiiiiii/looked-up")
MANIFEST_PATH = "data/manifest.json"
SITELINKS_PATH = "data/wikidata/sitelinks.parquet"

# D4: keep an hourly row when views_desktop + views_mobile >= MIN_VIEWS.
MIN_VIEWS = 5
# D6 / ADR 0017: self-healing window and per-run cap. GitHub drops many scheduled runs
# (2 scheduled runs in ~8 h observed), so each run looks back 7 days and catches up 12 hours.
WINDOW_HOURS = 7 * 24
MAX_HOURS_PER_RUN = 12
