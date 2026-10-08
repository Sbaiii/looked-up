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
DATA_DIR = Path(os.environ.get("LOOKEDUP_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
LOCAL_LAKE_DIR = DATA_DIR / "lake"

USER_AGENT = "looked-up/0.1 (https://github.com/Sbaiii/looked-up; abdellahsbaisbai@gmail.com)"

DUMPS_BASE = "https://dumps.wikimedia.org/other/pageviews"
PVC_BASE = "https://dumps.wikimedia.org/other/pageview_complete"
REST_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
SITELINKS_DUMP = "https://dumps.wikimedia.org/wikidatawiki/latest/wikidatawiki-latest-wb_items_per_site.sql.gz"

HF_REPO_ID = os.environ.get("LOOKEDUP_HF_REPO", "Sbaiii/looked-up")
MANIFEST_PATH = "data/manifest.json"
SITELINKS_PATH = "data/wikidata/sitelinks.parquet"

# D4: keep an hourly row when views_desktop + views_mobile >= MIN_VIEWS.
MIN_VIEWS = 5
# D6: self-healing window and per-run cap.
WINDOW_HOURS = 72
MAX_HOURS_PER_RUN = 6
