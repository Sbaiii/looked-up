"""Q3: sample the Wikimedia EventStreams (SSE) firehose.

recentchange for 60 s, page-create and revision-create for 20 s each.
Samples saved as JSONL in data/raw/stream/; summary in data/derived/q3_stream.json.

Usage: .venv/bin/python spike/q3_edit_stream.py
"""

from __future__ import annotations

import json
import time
from collections import Counter

import httpx

from common import DERIVED, HEADERS, RAW

BASE = "https://stream.wikimedia.org/v2/stream/"


def sample(stream: str, seconds: float) -> dict:
    out = RAW / "stream" / f"{stream}-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    events, errors = [], []
    t0 = time.monotonic()
    try:
        with httpx.stream("GET", BASE + stream, headers={**HEADERS, "Accept": "text/event-stream"},
                          timeout=httpx.Timeout(10.0, read=30.0)) as r:
            r.raise_for_status()
            data_lines: list[str] = []
            for line in r.iter_lines():
                if time.monotonic() - t0 >= seconds:
                    break
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                elif line == "" and data_lines:
                    try:
                        events.append(json.loads("\n".join(data_lines)))
                    except json.JSONDecodeError as e:
                        errors.append(str(e))
                    data_lines = []
    except httpx.HTTPError as e:
        return {"stream": stream, "error": repr(e)}
    elapsed = time.monotonic() - t0
    with open(out, "w") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    res = {"stream": stream, "seconds": round(elapsed, 1), "events": len(events),
           "events_per_s": round(len(events) / elapsed, 1), "parse_errors": len(errors),
           "file": str(out.relative_to(RAW.parent.parent)), "bytes": out.stat().st_size}
    if stream == "recentchange":
        res["top_wikis"] = Counter(e.get("wiki") for e in events).most_common(10)
        res["types"] = Counter(e.get("type") for e in events).most_common()
        res["bot_fraction"] = round(sum(bool(e.get("bot")) for e in events) / max(1, len(events)), 3)
        wp = [e for e in events if str(e.get("server_name", "")).endswith("wikipedia.org")]
        res["wikipedia_share"] = round(len(wp) / max(1, len(events)), 3)
        res["wikipedia_human_edits_per_s"] = round(
            sum(1 for e in wp if e.get("type") in ("edit", "new") and not e.get("bot")) / elapsed, 1)
        res["namespace0_share"] = round(sum(e.get("namespace") == 0 for e in events) / max(1, len(events)), 3)
        # how stale is an event when we receive it?
        lag = sorted(time.time() - e["timestamp"] for e in events if isinstance(e.get("timestamp"), int))
        if lag:
            res["delivery_lag_s"] = {"median": round(lag[len(lag) // 2], 1), "p95": round(lag[int(len(lag) * .95)], 1)}
    else:
        res["top_wikis"] = Counter(e.get("database") for e in events).most_common(5)
        res["sample_keys"] = sorted(events[0].keys()) if events else []
    return res


def main() -> None:
    results = [sample("recentchange", 60), sample("page-create", 20), sample("revision-create", 20)]
    (DERIVED / "q3_stream.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
