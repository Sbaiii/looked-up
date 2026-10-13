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


def test_adr_index_lists_every_record():
    index = (ROOT / "docs" / "adr" / "README.md").read_text()
    for p in sorted((ROOT / "docs" / "adr").glob("0*.md")):
        assert f"]({p.name})" in index, f"{p.name} missing from docs/adr/README.md"


def test_config_readme_covers_every_file():
    readme = (ROOT / "config" / "README.md").read_text()
    for p in sorted((ROOT / "config").iterdir()):
        if p.name != "README.md" and p.is_file():
            assert f"`{p.name}`" in readme, f"{p.name} missing from config/README.md"


def test_analysis_readme_covers_every_output():
    readme = (ROOT / "docs" / "analysis" / "README.md").read_text()
    for p in sorted((ROOT / "docs" / "analysis").iterdir()):
        if p.name != "README.md" and p.is_file():
            assert p.name in readme, f"{p.name} missing from docs/analysis/README.md"


def test_schema_and_model_files_match():
    import yaml

    schema = {m["name"] for m in yaml.safe_load((ROOT / "warehouse" / "models" / "schema.yml").read_text())["models"]}
    files = {p.stem for p in (ROOT / "warehouse" / "models").rglob("*") if p.suffix in (".sql", ".py")}
    assert schema == files, schema ^ files


def test_readme_relative_links_exist():
    text = (ROOT / "README.md").read_text()
    for target in re.findall(r"\]\(((?!https?://|#)[^)\s]+)\)", text):
        assert (ROOT / target.split("#")[0]).exists(), f"README links to missing {target}"


def test_spike_readme_lists_every_script():
    readme = (ROOT / "spike" / "README.md").read_text()
    for p in sorted((ROOT / "spike").glob("q*.py")):
        assert f"`{p.name}`" in readme, f"{p.name} missing from spike/README.md"


def test_live_rules_have_one_source():
    import yaml

    live = yaml.safe_load((ROOT / "config" / "live.yml").read_text())
    worker = json.loads((ROOT / "worker" / "src" / "rules.json").read_text())
    assert worker["live_event_window_minutes"] == live["live_event_window_minutes"]
    assert worker["burst"] == live["burst"]
