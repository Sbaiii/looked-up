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


def test_app_reads_where_the_export_writes():
    from lookedup.app_export import APP_PREFIX
    from lookedup.settings import HF_REPO_ID

    js = (ROOT / "app" / "js" / "data.js").read_text(encoding="utf-8")
    base = re.search(r"DEFAULT_BASE = '([^']+)'", js).group(1)
    assert base == f"https://huggingface.co/datasets/{HF_REPO_ID}/resolve/main/{APP_PREFIX}/"


def test_browser_fixtures_mock_the_app_data_url():
    base = re.search(r"DEFAULT_BASE = '([^']+)'", (ROOT / "app" / "js" / "data.js").read_text(encoding="utf-8")).group(1)
    assert f"page.route('{base}**'" in (ROOT / "tests" / "app" / "fixtures.js").read_text(encoding="utf-8")


def test_live_strip_points_at_the_deployed_worker():
    name = re.search(r'^name = "([^"]+)"', (ROOT / "worker" / "wrangler.toml").read_text(encoding="utf-8"), re.MULTILINE).group(1)
    url = re.search(r"const DEFAULT = '([^']+)'", (ROOT / "app" / "js" / "live.js").read_text(encoding="utf-8")).group(1)
    assert url.startswith(f"https://{name}.") and url.endswith(".workers.dev/live.json")


def test_card_spread_phrase_matches_the_app():
    from lookedup import og

    within = json.loads((ROOT / "app" / "i18n" / "en.json").read_text(encoding="utf-8"))["within"]
    assert og.within(0) == within["zero"]
    assert og.within(1) == within["one"].format(n=1) and og.within(6) == within["other"].format(n=6)


def test_every_category_has_a_label():
    from lookedup.analytics.config import load

    raw = load().raw
    possible = set(raw["categories"]) | set(raw["occupations"]) | {"death", "human", "other"}
    for code in ("en", "fr", "es"):
        labels = json.loads((ROOT / "app" / "i18n" / f"{code}.json").read_text(encoding="utf-8"))["event"]["category"]
        assert possible <= set(labels), (code, possible - set(labels))


def test_every_tier_has_a_label_and_help():
    from lookedup.analytics.config import load

    tiers = {name for name, _ in load().product_event.tiers}
    for code in ("en", "fr", "es"):
        d = json.loads((ROOT / "app" / "i18n" / f"{code}.json").read_text(encoding="utf-8"))
        assert tiers <= set(d["tier"]) and tiers <= set(d["tier_help"]), code


def test_every_language_is_on_the_map():
    from lookedup.languages import active_codes

    geo = json.loads((ROOT / "app" / "data" / "language_geo.json").read_text(encoding="utf-8"))
    for code in active_codes():
        assert geo["languages"].get(code), code
        assert code in geo["anchors"], code


def test_interface_languages_match_the_translation_files():
    js = (ROOT / "app" / "js" / "i18n.js").read_text(encoding="utf-8")
    ui = set(re.findall(r"'(\w\w)'", re.search(r"UI_LANGS = \[(.*?)\]", js).group(1)))
    assert ui == {p.stem for p in (ROOT / "app" / "i18n").glob("*.json")}
    html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
    assert ui == set(re.findall(r'data-ui-lang="(\w\w)"', html))


def test_ops_reference_lists_every_command():
    from lookedup import cli

    documented = set(re.findall(r"^  ([a-z][a-z0-9-]+)\s", cli.__doc__, re.MULTILINE))
    ops = (ROOT / "docs" / "ops.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"lookedup\.cli ([a-z0-9-]+)", ops)) | ({"backfill"} if "lookedup.backfill" in ops else set())
    assert documented <= listed, sorted(documented - listed)


def test_one_user_agent_everywhere():
    from lookedup.settings import USER_AGENT

    copies = {
        "spike/common.py": r'^UA = "([^"]+)"',
        "live/lookedup_live/__init__.py": r'^USER_AGENT = "([^"]+)"',
        "worker/src/index.ts": r"^const UA = '([^']+)';",
    }
    for path, pattern in copies.items():
        assert re.search(pattern, (ROOT / path).read_text(encoding="utf-8"), re.MULTILINE).group(1) == USER_AGENT, path


def test_workflows_use_the_required_python():
    need = re.search(r'requires-python = ">=(\d+\.\d+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8")).group(1)
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for v in re.findall(r'python-version: "([\d.]+)"', wf.read_text(encoding="utf-8")):
            assert v == need, wf.name


def test_ops_workflow_table_lists_every_workflow():
    ops = (ROOT / "docs" / "ops.md").read_text(encoding="utf-8")
    section = ops[ops.index("## Workflows"):]
    section = section[:section.index("\n## ", 5)]
    rows = set(re.findall(r"^\| `([\w-]+\.yml)`", section, re.MULTILINE))
    assert {p.name for p in (ROOT / ".github" / "workflows").glob("*.yml")} <= rows


def test_documented_commands_exist():
    from lookedup import cli

    known = set(re.findall(r"^  ([a-z][a-z0-9-]+)\s", cli.__doc__, re.MULTILINE))
    for doc in ("README.md", "docs/ops.md", "tests/README.md"):
        used = set(re.findall(r"lookedup\.cli ([a-z][a-z0-9-]+)", (ROOT / doc).read_text(encoding="utf-8")))
        assert used <= known, (doc, sorted(used - known))


def test_documented_npm_scripts_exist():
    scripts = set(json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"])
    for doc in ("README.md", "docs/ops.md", "tests/README.md"):
        used = set(re.findall(r"npm run ([\w:-]+)", (ROOT / doc).read_text(encoding="utf-8")))
        assert used <= scripts, (doc, sorted(used - scripts))


def test_readme_language_claim_matches_the_ranking():
    import yaml

    doc = yaml.safe_load((ROOT / "config" / "languages.yml").read_text(encoding="utf-8"))
    last = doc["languages"][doc["top_n"] - 1]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"takes (\d+) language editions \(([\d.]+) % of human article views among the (\d+) largest", readme)
    assert int(m.group(1)) == doc["top_n"] and int(m.group(3)) == len(doc["languages"])
    assert float(m.group(2)) == round(100 * last["cumulative_share_of_candidates"], 1)


def test_dataset_card_language_table():
    import yaml

    doc = yaml.safe_load((ROOT / "config" / "languages.yml").read_text(encoding="utf-8"))
    card = (ROOT / "dataset" / "README.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (\d+) \| `([\w-]+)` \| ([^|]+) \| ([^|]+) \| ([\d.]+) M \| (\d+) % \|$", card, re.MULTILINE)
    assert len(rows) == doc["top_n"]
    for (rank, code, name, native, views, mobile), lang in zip(rows, doc["languages"], strict=False):
        assert (int(rank), code, name.strip(), native.strip()) == (lang["rank"], lang["code"], lang["name_en"], lang["name_native"])
        assert float(views) == round(lang["human_views_7d"] / 7 / 1e6, 1), code
        assert int(mobile) == round(100 * lang["mobile_share"]), code


def test_dataset_card_event_rule():
    from lookedup.analytics.config import load

    cfg = load()
    p, lookback = cfg.product_event, cfg.baseline["lookback_days"]
    card = " ".join((ROOT / "dataset" / "README.md").read_text(encoding="utf-8").split())
    assert (f"spiking in at least {p.min_languages} languages within {p.window_hours} hours, measured against its own "
            f"{lookback}-day baseline") in card
    tiers = dict(p.tiers)
    assert (f"noticed (≥ {tiers['noticed']} languages), international (≥ {tiers['international']}) or planetary "
            f"(≥ {tiers['planetary']})") in card
    assert f"The evaluated Phase 2 definition used ≥ {cfg.event.min_languages} languages" in card


def test_readme_tiers_and_baseline():
    from lookedup.analytics.config import load

    cfg = load()
    tiers = dict(cfg.product_event.tiers)
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    assert f"own {cfg.baseline['lookback_days']}-day baseline" in readme
    assert (f"Tiers: noticed ≥ {tiers['noticed']} languages, international ≥ {tiers['international']}, "
            f"planetary ≥ {tiers['planetary']}") in readme


def test_no_fetchone_in_the_package():
    """DuckDB 2.0 removed relation fetchone() and blocks a connection after a partly read execute() (ADR 0034)."""
    for base in ("lookedup", "live/lookedup_live"):
        for p in (ROOT / base).rglob("*.py"):
            assert ".fetchone()" not in p.read_text(encoding="utf-8"), p.relative_to(ROOT)


def test_app_imports_resolve():
    js = ROOT / "app" / "js"
    for f in js.glob("*.js"):
        for mod in re.findall(r"from '\./([\w-]+\.js)'", f.read_text(encoding="utf-8")):
            assert (js / mod).exists(), (f.name, mod)


def test_pure_app_modules_have_unit_tests():
    unit = " ".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests" / "app" / "unit").glob("*.mjs"))
    for name in ("briefing", "csv", "data", "filters", "i18n", "keys", "live", "projection", "scale", "select"):
        assert f"app/js/{name}.js" in unit, name
