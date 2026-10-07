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
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

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
    print(json.dumps(res, indent=1))
    if not all(r["identical"] for r in res):
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
        open_store(a.local).commit({SITELINKS_PATH: out}, Manifest().hours,
                                   f"data: refresh Wikidata sitelinks ({sum(counts.values()):,} rows)")


def cmd_coverage(a):
    from lookedup.query import lake_root
    from lookedup.settings import SITELINKS_PATH
    from lookedup.store import hour_path, open_store
    from lookedup.wikidata import join_coverage

    store = open_store(a.local)
    present = sorted(store.read_manifest().present())[-a.hours:]
    with tempfile.TemporaryDirectory() as tmp:
        for ts in present:
            store.fetch(hour_path(ts), Path(tmp))
        sl = store.fetch(SITELINKS_PATH, Path(tmp)) or f"{lake_root(a.local)}/{SITELINKS_PATH}"
        rows = join_coverage(f"{tmp}/data/hourly/*/*/*/*.parquet", str(sl))
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
    from lookedup.store import HFStore, LocalStore

    local, hf = LocalStore(), HFStore(create=True)
    entries = local.read_manifest().hours
    remote = hf.read_manifest().hours
    todo = {k: v for k, v in entries.items() if k not in remote}
    keys = sorted(todo)
    for i in range(0, len(keys), a.batch):
        chunk = {k: todo[k] for k in keys[i:i + a.batch]}
        files = {v["path"]: local.root / v["path"] for v in chunk.values()}
        hf.commit(files, chunk, f"data: upload {len(chunk)} hour(s) {keys[i]}..{keys[min(i + a.batch, len(keys)) - 1]}")
    log.info("pushed %d hour(s)", len(keys))


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
    sp.add_argument("--window", type=int, default=72)
    sp.add_argument("--max-hours", type=int, default=6)
    sp = add("backfill", cmd_backfill)
    sp.add_argument("--from", dest="start", required=True)
    sp.add_argument("--to", dest="end", required=True)
    sp.add_argument("--oldest-first", action="store_true")
    sp.add_argument("--keep-raw", action="store_true")
    sp = add("validate", cmd_validate)
    sp.add_argument("-n", type=int, default=3)
    sp.add_argument("--seed", type=int)
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
    sp.add_argument("--batch", type=int, default=48)

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    a.fn(a)


if __name__ == "__main__":
    main()
