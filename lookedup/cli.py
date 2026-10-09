"""Command line entry point: ``python -m lookedup.cli <command>``.

Commands:
  hourly        run the hourly ingestion job (D6)
  backfill      backfill days from pageview_complete (D7), same as ``python -m lookedup.backfill``
  validate      compare random backfilled hours with the hourly-dump path
  languages     rank languages over 7 full days and write config/languages.yml (D3)
  wikidata      build and upload data/wikidata/sitelinks.parquet (D8)
  coverage      Wikidata join coverage per language over recent hours
  top           top articles of one language in one hour (D10 smoke test)
  verify-hour   check 'filename = end of hour' against the REST API
  push          upload a local lake (data/lake/) to Hugging Face
  compact       migrate a local lake from hourly files to daily files (one-off)
  card          upload dataset/README.md as the Hugging Face dataset card
  relocate-data move the old in-repo data/ directory to LOOKEDUP_DATA_DIR (default ~/looked-up-data)
  sync          download day files, manifest and sitelinks from Hugging Face into data/lake/
  baselines     build the day's production baselines into LOOKEDUP_BASELINES_DIR (daily, never uploaded)
  hub           Hub maintenance: --drop-prefix PATH, --squash (rewrites dataset history), storage report
  score         score ingested hours into spikes, events and data/latest.json (hourly)
  ground-truth  build data/eval/current_events.parquet from Portal:Current events (Phase 2 evaluation)
  evaluate      run the pre-registered Phase 2 evaluation (writes docs/analysis/)
  evaluate-v2   run the pre-registered Phase 2b evaluation against deaths, earthquakes and matches
  warehouse     run dbt on the warehouse (e.g. `warehouse build`), thresholds from config/analytics.yml
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

from lookedup.settings import MAX_HOURS_PER_RUN, WINDOW_HOURS

log = logging.getLogger("lookedup")


def _hour(s: str) -> datetime:
    """'2026-10-06T14:00' or '2026-10-06 14' -> naive UTC hour start."""
    s = s.replace("Z", "").replace(" ", "T")
    dt = datetime.fromisoformat(s if ":" in s or len(s) > 13 else s + ":00")
    return dt.replace(minute=0, second=0, microsecond=0, tzinfo=None)


def cmd_hourly(a):
    from lookedup import hourly
    from lookedup.store import open_store

    n = hourly.run(open_store(a.local), window_hours=a.window, max_hours=a.max_hours)
    log.info("hourly run finished: %d hour(s) ingested", n)


def cmd_backfill(a):
    from lookedup.backfill import main

    argv = ["--from", a.start, "--to", a.end] + (["--local"] if a.local else []) + \
        (["--oldest-first"] if a.oldest_first else []) + (["--keep-raw"] if a.keep_raw else [])
    main(argv)


def cmd_validate(a):
    from lookedup.backfill import validate
    from lookedup.store import open_store

    res = validate(open_store(a.local), n=a.n, seed=a.seed)
    print(json.dumps(res, indent=1, default=str, ensure_ascii=False))
    # pageview_complete under-counts a few mobile views on missing pages/redirects (ADR 0010):
    # fail only when more than 0.01 % of rows differ
    if any(r["matching_rows_pct"] < a.min_match for r in res):
        sys.exit(1)


def cmd_languages(a):
    from lookedup import languages

    days = languages.last_full_days(7, date.fromisoformat(a.today) if a.today else None)
    ranking = languages.rank_languages(days, keep_raw=a.keep_raw)
    languages.write_config(ranking, days, top_n=a.top_n)
    for r in ranking[: a.top_n]:
        print(f"{r['rank']:>3} {r['code']:<8} human={r['human_views_7d']:>12,} "
              f"mobile={r['mobile_share']} automated={r['automated_share']} raw_rank={r['raw_rank']}")


def cmd_wikidata(a):
    from lookedup.languages import active_codes
    from lookedup.settings import DATA_DIR, SITELINKS_PATH
    from lookedup.store import Manifest, open_store
    from lookedup.wikidata import build_sitelinks

    out = DATA_DIR / "build" / "sitelinks.parquet"
    counts = build_sitelinks(active_codes(), out)
    print(json.dumps(counts, indent=1))
    if not a.no_upload:
        open_store(a.local).commit({SITELINKS_PATH: out}, Manifest(),
                                   f"data: refresh Wikidata sitelinks ({sum(counts.values()):,} rows)")


def cmd_coverage(a):
    from lookedup.query import lake_root
    from lookedup.settings import SITELINKS_PATH
    from lookedup.store import day_path, open_store
    from lookedup.wikidata import join_coverage

    store = open_store(a.local)
    present = sorted(store.read_manifest().present())[-a.hours:]
    with tempfile.TemporaryDirectory() as tmp:
        paths = sorted({str(store.fetch(day_path(ts), Path(tmp))) for ts in present})
        sl = store.fetch(SITELINKS_PATH, Path(tmp)) or f"{lake_root(a.local)}/{SITELINKS_PATH}"
        rows = join_coverage(paths, str(sl), since=present[0], until=present[-1])
    lines = ["| Lang | Views | Matched to a QID | Coverage |", "|---|---|---|---|"]
    lines += [f"| {l} | {v:,} | {m:,} | {p} % |" for l, v, m, p in rows]
    tot_v, tot_m = sum(r[1] for r in rows), sum(r[2] for r in rows)
    lines.append(f"| **all** | {tot_v:,} | {tot_m:,} | {round(100 * tot_m / tot_v, 1)} % |")
    header = (f"Hours: {present[0]:%Y-%m-%d %H:00} to {present[-1]:%Y-%m-%d %H:00} UTC ({len(present)} hours), "
              "retained article rows (views_desktop + views_mobile, >= 5 per hour).")
    text = header + "\n\n" + "\n".join(lines) + "\n"
    print(text)
    if a.out:
        Path(a.out).write_text(text)


def cmd_top(a):
    from lookedup.query import top

    top(a.lang, _hour(a.hour), n=a.n, local=a.local).show(max_width=200)


def cmd_verify_hour(a):
    from lookedup.hourly import verify_alignment

    with tempfile.TemporaryDirectory() as tmp:
        print(json.dumps(verify_alignment(_hour(a.hour), Path(tmp)), indent=1))


def cmd_push(a):
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    from lookedup.settings import SITELINKS_PATH
    from lookedup.store import HFStore, LocalStore, Manifest, write_hours

    local, hf = LocalStore(), HFStore(create=True)
    entries = local.read_manifest().hours
    remote = hf.read_manifest().hours
    todo = sorted(k for k in entries if k not in remote)
    by_day: dict[str, list[str]] = {}
    for k in todo:
        by_day.setdefault(entries[k]["path"], []).append(k)
    days = sorted(by_day)
    for i in range(0, len(days), a.batch):
        tables = {}
        for path in days[i:i + a.batch]:
            day = pq.read_table(local.root / path)
            for k in by_day[path]:
                ts = datetime.strptime(k, "%Y-%m-%dT%H:%M:%SZ")
                hour = day.filter(pc.equal(day["ts_hour_start"], pa.scalar(ts, pa.timestamp("us"))))
                tables[ts] = (hour, entries[k]["source"])
        written = write_hours(hf, tables, f"data: upload {len(tables)} hour(s) {min(tables):%Y-%m-%dT%H}.."
                                          f"{max(tables):%Y-%m-%dT%H}Z from a local lake")
        log.info("pushed %d hour(s) (%d/%d days)", len(written), min(i + a.batch, len(days)), len(days))
    sitelinks = local.root / SITELINKS_PATH
    if sitelinks.exists() and not hf.api.file_exists(hf.repo_id, SITELINKS_PATH, repo_type="dataset"):
        hf.commit({SITELINKS_PATH: sitelinks}, Manifest(), "data: add Wikidata sitelinks from a local lake")
        log.info("pushed %s (%d bytes)", SITELINKS_PATH, sitelinks.stat().st_size)
    cmd_card(a)


def cmd_card(a):
    from lookedup.settings import DATASET_CARD
    from lookedup.store import HFStore

    HFStore(create=True).upload_card(DATASET_CARD)
    log.info("dataset card uploaded from %s", DATASET_CARD)


def cmd_relocate_data(a):
    from lookedup.relocate import relocate

    print(json.dumps(relocate(skip=tuple(a.skip)), indent=1))


def cmd_sync(a):
    from lookedup.store import HFStore, LocalStore, sync_to_local

    res = sync_to_local(HFStore(), LocalStore(), datetime.fromisoformat(a.start),
                        include_sitelinks=not a.no_sitelinks)
    print(json.dumps(res, indent=1))


def cmd_baselines(a):
    from lookedup.dumps import utcnow
    from lookedup.scorer import build_baselines
    from lookedup.store import open_store

    day = date.fromisoformat(a.day) if a.day else utcnow().date()
    print(json.dumps(build_baselines(open_store(a.local), day), indent=1))  # local only (ADR 0018)


def cmd_hub(a):
    from lookedup.store import HFStore

    hf = HFStore(create=True)
    before = hf.used_storage()
    res = {"used_storage_before": before}
    if a.drop_prefix:
        res["deleted"] = hf.delete_prefix(a.drop_prefix, f"data: remove {a.drop_prefix} (moved off the Hub, ADR 0018)")
    if a.squash:
        hf.squash_history("data: squash history (monthly maintenance, ADR 0018)")
        res["squashed"] = True
    res["used_storage_after"] = hf.used_storage()
    print(json.dumps(res, indent=1))


def cmd_score(a):
    from lookedup.scorer import score
    from lookedup.store import open_store

    hours = [_hour(a.hour)] if a.hour else None
    print(json.dumps(score(open_store(a.local), max_hours=a.max_hours, hours=hours), indent=1))


def cmd_ground_truth(a):
    from lookedup.analytics.config import load
    from lookedup.evaluation.ground_truth import build
    from lookedup.settings import DATA_DIR, LOCAL_LAKE_DIR, SITELINKS_PATH

    cfg = load()
    res = build(cfg.period_start, cfg.period_end, LOCAL_LAKE_DIR / SITELINKS_PATH,
                DATA_DIR / "warehouse" / "entity_claims.parquet", DATA_DIR / "eval" / "current_events.parquet", cfg)
    print(json.dumps(res, indent=1))


def cmd_evaluate(a):
    from lookedup.evaluation import run

    if a.audit_sample:
        print(run.audit_sample(), "units written to docs/analysis/h3_sample.csv")
    elif a.audit_score:
        print(json.dumps(run.audit_score(), indent=1))
    else:
        print(json.dumps(run.evaluate(), indent=1, default=str))


def cmd_evaluate_v2(a):
    from lookedup.evaluation import run_v2

    print(json.dumps(run_v2.evaluate(refresh=a.refresh), indent=1, default=str))


def cmd_warehouse(a):
    from lookedup.warehouse import run

    if not run(a.dbt_args or ["build"], hf=a.hf):
        sys.exit(1)


def cmd_compact(a):
    from lookedup.compact import compact_local
    from lookedup.settings import LOCAL_LAKE_DIR

    report = compact_local(LOCAL_LAKE_DIR)
    print(json.dumps(report, indent=1))
    full = [r for r in report if r["hours"] == 24]
    if full:
        before = sum(r["bytes_hourly_files"] for r in full) / len(full)
        after = sum(r["bytes_day_file"] for r in full) / len(full)
        print(f"full days: {len(full)}; mean bytes/day {before:,.0f} -> {after:,.0f} "
              f"({after / before:.2f}x); {after * 365 / 1e9:.1f} GB/year")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m lookedup.cli", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, local=True):
        sp = sub.add_parser(name)
        sp.set_defaults(fn=fn)
        if local:
            sp.add_argument("--local", action="store_true", help="use data/lake/ instead of Hugging Face")
        return sp

    sp = add("hourly", cmd_hourly)
    sp.add_argument("--window", type=int, default=WINDOW_HOURS)
    sp.add_argument("--max-hours", type=int, default=MAX_HOURS_PER_RUN)
    sp = add("backfill", cmd_backfill)
    sp.add_argument("--from", dest="start", required=True)
    sp.add_argument("--to", dest="end", required=True)
    sp.add_argument("--oldest-first", action="store_true")
    sp.add_argument("--keep-raw", action="store_true")
    sp = add("validate", cmd_validate)
    sp.add_argument("-n", type=int, default=3)
    sp.add_argument("--seed", type=int)
    sp.add_argument("--min-match", type=float, default=99.99, help="minimum %% of identical rows")
    sp = add("languages", cmd_languages, local=False)
    sp.add_argument("--top-n", type=int, default=30)
    sp.add_argument("--today", help="pretend today is this date (YYYY-MM-DD)")
    sp.add_argument("--keep-raw", action="store_true")
    sp = add("wikidata", cmd_wikidata)
    sp.add_argument("--no-upload", action="store_true")
    sp = add("coverage", cmd_coverage)
    sp.add_argument("--hours", type=int, default=24)
    sp.add_argument("--out")
    sp = add("top", cmd_top)
    sp.add_argument("--lang", required=True)
    sp.add_argument("--hour", required=True, help="hour start in UTC, e.g. 2026-10-06T14:00")
    sp.add_argument("-n", type=int, default=20)
    sp = add("verify-hour", cmd_verify_hour, local=False)
    sp.add_argument("--hour", required=True)
    sp = add("push", cmd_push, local=False)
    sp.add_argument("--batch", type=int, default=3, help="days per Hub commit")
    add("compact", cmd_compact, local=False)
    add("card", cmd_card, local=False)
    sp = add("baselines", cmd_baselines)
    sp.add_argument("--day", help="UTC day to build baselines for (default: today)")
    sp = add("hub", cmd_hub, local=False)
    sp.add_argument("--drop-prefix", help="delete every Hub file under this prefix")
    sp.add_argument("--squash", action="store_true", help="super-squash the dataset history (irreversible)")
    sp = add("score", cmd_score)
    sp.add_argument("--hour", help="score exactly this hour start (UTC), e.g. 2026-10-08T14:00")
    sp.add_argument("--max-hours", type=int, default=MAX_HOURS_PER_RUN)
    add("ground-truth", cmd_ground_truth, local=False)
    sp = add("evaluate", cmd_evaluate, local=False)
    sp.add_argument("--audit-sample", action="store_true")
    sp.add_argument("--audit-score", action="store_true")
    sp = add("evaluate-v2", cmd_evaluate_v2, local=False)
    sp.add_argument("--refresh", action="store_true", help="refetch the ground truths")
    sp = add("warehouse", cmd_warehouse, local=False)
    sp.add_argument("--hf", action="store_true", help="read the lake from hf:// instead of data/lake/")
    sp.add_argument("dbt_args", nargs=argparse.REMAINDER, help="dbt command and flags (default: build)")
    sp = add("relocate-data", cmd_relocate_data, local=False)
    sp.add_argument("--skip", action="append", default=[], help="relative path prefix to leave behind")
    sp = add("sync", cmd_sync, local=False)
    sp.add_argument("--from", dest="start", required=True, help="first day to mirror (YYYY-MM-DD)")
    sp.add_argument("--no-sitelinks", action="store_true")

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    a.fn(a)


if __name__ == "__main__":
    main()
