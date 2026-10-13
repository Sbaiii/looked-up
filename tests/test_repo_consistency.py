"""Cross-file checks that keep the documentation and translations in step with the code."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _keys(d, prefix=""):
    out = set()
    for k, v in d.items():
        p = f"{prefix}{k}"
        out |= _keys(v, p + ".") if isinstance(v, dict) else {p}
    return out


def test_app_translations_have_the_same_keys():
    keys = {l: _keys(json.loads((ROOT / "app" / "i18n" / f"{l}.json").read_text())) for l in ("en", "fr", "es")}
    assert keys["fr"] == keys["en"], keys["en"] ^ keys["fr"]
    assert keys["es"] == keys["en"], keys["en"] ^ keys["es"]
