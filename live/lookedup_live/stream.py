"""EventStreams recentchange consumer: one SSE connection, reconnect with exponential backoff, resume with
Last-Event-ID (no events lost across reconnects and restarts); a cold start replays the last hour (`since`)."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import requests

from lookedup_live import USER_AGENT

log = logging.getLogger(__name__)
URL = "https://stream.wikimedia.org/v2/stream/recentchange"
COLD_START_REPLAY = timedelta(minutes=60)


def parse_sse(lines: Iterator[str]) -> Iterator[tuple[str | None, str]]:
    """Yield (id, data) per SSE message."""
    ev_id, data = None, []
    for line in lines:
        if line == "":
            if data:
                yield ev_id, "\n".join(data)
            ev_id, data = None, []
        elif line.startswith(":"):
            continue
        else:
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "id":
                ev_id = value
            elif field == "data":
                data.append(value)


def consume(engine, stop: threading.Event, max_backoff: float = 60.0) -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/event-stream"})
    backoff = 1.0
    while not stop.is_set():
        headers, params = {}, {}
        if engine.last_event_id:
            headers["Last-Event-ID"] = engine.last_event_id
        else:
            params["since"] = (datetime.now(timezone.utc) - COLD_START_REPLAY).strftime("%Y-%m-%dT%H:%M:%SZ")
            engine.mark_gap()
        try:
            with session.get(URL, headers=headers, params=params, stream=True, timeout=(10, 60)) as r:
                r.raise_for_status()
                engine.connected, engine.connected_since = True, time.time()
                backoff = 1.0
                for ev_id, data in parse_sse(r.iter_lines(decode_unicode=True)):
                    if stop.is_set():
                        break
                    try:
                        engine.handle(json.loads(data), ev_id)
                    except ValueError:
                        continue
        except requests.RequestException as e:
            log.warning("stream error: %s (retry in %.0fs)", e, backoff)
        engine.connected = False
        if stop.wait(backoff):
            break
        backoff = min(max_backoff, backoff * 2)


def resolver_loop(engine, stop: threading.Event, every: float = 10.0) -> None:
    while not stop.wait(every):
        if engine.resolver.resolve_pending():
            engine.attach_qids()
        engine.detector.gc(time.time())
