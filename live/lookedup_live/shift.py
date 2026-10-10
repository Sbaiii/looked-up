"""Shift mode (ADR 0030): run the consumer for a fixed time (a GitHub Actions job) and publish live.json,
stats.json and the day's bursts to the lake every few minutes; hand the state over to the next shift
through the lake (state.json.gz, no user data) so the stream resumes with Last-Event-ID.

    python -m lookedup_live.shift --hours 5.75 --every 300
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from lookedup_live.engine import Engine
from lookedup_live.stream import consume, resolver_loop

log = logging.getLogger("lookedup_live.shift")
REPO = os.environ.get("LIVE_HF_REPO", "Sbaiiiiii/looked-up")
PREFIX = "data/live"


def _api():
    from huggingface_hub import HfApi
    return HfApi(token=os.environ.get("HF_TOKEN"))


def fetch_state(state_dir: Path) -> bool:
    from huggingface_hub import hf_hub_download
    try:
        for name in ("state.json.gz", "qids.json"):
            p = hf_hub_download(REPO, f"{PREFIX}/{name}", repo_type="dataset", token=os.environ.get("HF_TOKEN"))
            (state_dir / name).write_bytes(Path(p).read_bytes())
        return True
    except Exception as e:  # first shift, or state missing: cold start
        log.warning("no previous state: %s", e)
        return False


def publish(engine: Engine, state_dir: Path, final: bool = False) -> None:
    from huggingface_hub import CommitOperationAdd
    now = time.time()
    out = Path(tempfile.mkdtemp())
    (out / "live.json").write_text(json.dumps(engine.live(now), ensure_ascii=False, separators=(",", ":")))
    (out / "stats.json").write_text(json.dumps(engine.stats(now), ensure_ascii=False, separators=(",", ":")))
    day = datetime.fromtimestamp(now, timezone.utc).date()
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()
    ops = [CommitOperationAdd(f"{PREFIX}/live.json", str(out / "live.json")),
           CommitOperationAdd(f"{PREFIX}/stats.json", str(out / "stats.json"))]
    for d0 in (start - 86400, start):
        rows = [b for b in engine.bursts_since(d0) if b["ts"] < d0 + 86400]
        iso_day = datetime.fromtimestamp(d0, timezone.utc).strftime("%Y-%m-%d")
        f = out / f"{iso_day}.jsonl"
        f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        ops.append(CommitOperationAdd(f"{PREFIX}/bursts/{iso_day}.jsonl", str(f)))
    if final or int(now // 1800) != int((now - 300) // 1800):        # state at the end and every 30 min
        engine.snapshot(state_dir / "state.json.gz")
        ops += [CommitOperationAdd(f"{PREFIX}/state.json.gz", str(state_dir / "state.json.gz")),
                CommitOperationAdd(f"{PREFIX}/qids.json", str(state_dir / "qids.json"))]
    s = engine.status(now)
    _api().create_commit(REPO, repo_type="dataset", operations=ops,
                         commit_message=f"data: live layer, {len(engine.live(now)['events'])} live event(s), "
                                        f"{s['kept_per_s']} edits/s")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=float, default=5.75)
    p.add_argument("--every", type=int, default=300)
    p.add_argument("--state-dir", type=Path, default=Path(tempfile.mkdtemp()))
    p.add_argument("--no-publish", action="store_true")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    resumed = not a.no_publish and fetch_state(a.state_dir)
    engine = Engine(a.state_dir)                       # loads qids.json if the previous shift left one
    if resumed and engine.restore(a.state_dir / "state.json.gz"):
        log.info("resumed: last event %s", engine.status()["last_event_at"])
    stop = threading.Event()
    threads = [threading.Thread(target=consume, args=(engine, stop), daemon=True),
               threading.Thread(target=resolver_loop, args=(engine, stop), daemon=True)]
    for t in threads:
        t.start()
    end = time.time() + a.hours * 3600
    while time.time() < end:
        time.sleep(min(a.every, max(1, end - time.time())))
        s = engine.status()
        log.info("events/s %.1f kept/s %.2f langs %d bursts %d live %d gap %s", s["events_per_s"], s["kept_per_s"],
                 len(s["languages_seen"]), len(engine.detector.bursts), len(engine.live()["events"]), s["gap_minutes"])
        if not a.no_publish:
            try:
                publish(engine, a.state_dir)
            except Exception:
                log.exception("publish failed (will retry next round)")
    stop.set()
    engine.resolver.resolve_pending()
    engine.attach_qids()
    if not a.no_publish:
        publish(engine, a.state_dir, final=True)
    else:
        engine.snapshot(a.state_dir / "state.json.gz")


if __name__ == "__main__":
    main()
