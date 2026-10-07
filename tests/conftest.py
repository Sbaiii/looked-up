from __future__ import annotations

import json
from pathlib import Path

import pytest

from lookedup.parse import ArticleFilter

FIXTURES = Path(__file__).parent / "fixtures"
HOURLY_SAMPLE = FIXTURES / "pageviews-20260913-150000.sample"  # covers 14:00-15:00 UTC
PVC_SAMPLE = FIXTURES / "pageviews-20260913-user.sample"
LANGS = ["en", "fr", "de", "ja", "ar", "es"]


@pytest.fixture(scope="session")
def article_filter() -> ArticleFilter:
    data = json.loads((FIXTURES / "namespaces.json").read_text(encoding="utf-8"))
    return ArticleFilter(namespaces={l: v["namespaces"] for l, v in data.items()},
                         main_pages={l: v["main_page"] for l, v in data.items()})
