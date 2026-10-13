"""HTTP service (Space mode): GET /live.json, /stats.json, /bursts.json, /health. CORS for every origin,
responses cached 15 s."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from lookedup_live.engine import Engine
from lookedup_live.stream import consume, resolver_loop

logging.basicConfig(level=logging.INFO)
STATE = Path(os.environ.get("LIVE_STATE_DIR", "/tmp/looked-up-live"))
CACHE_S = 15

engine = Engine(STATE)
stop = threading.Event()
_cache: dict[str, tuple[float, dict]] = {}

app = FastAPI(title="Looked Up live", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


def cached(name: str, build) -> JSONResponse:
    """Serve ``build()`` as JSON, rebuilt at most every CACHE_S seconds, with a matching Cache-Control header."""
    now = time.time()
    hit = _cache.get(name)
    if not hit or now - hit[0] > CACHE_S:
        hit = _cache[name] = (now, build())
    return JSONResponse(hit[1], headers={"Cache-Control": f"public, max-age={CACHE_S}"})


def _snapshots() -> None:
    """Snapshot the engine every 5 minutes until shutdown."""
    while not stop.wait(300):
        engine.snapshot(STATE / "state.json.gz")


@app.on_event("startup")
def start() -> None:
    """Restore the last snapshot, then start the stream consumer, the QID resolver and the snapshot loop."""
    engine.restore(STATE / "state.json.gz")
    for target in (lambda: consume(engine, stop), lambda: resolver_loop(engine, stop), _snapshots):
        threading.Thread(target=target, daemon=True).start()


@app.on_event("shutdown")
def shutdown() -> None:
    """Stop the background threads and write a final snapshot."""
    stop.set()
    engine.snapshot(STATE / "state.json.gz")


@app.get("/live.json")
def live():
    """GET /live.json: live events and the top single-language bursts."""
    return cached("live", engine.live)


@app.get("/stats.json")
def stats():
    """GET /stats.json: hourly counts of bursts and live events."""
    return cached("stats", engine.stats)


@app.get("/bursts.json")
def bursts(hours: int = 72):
    """GET /bursts.json: every burst of the last ``hours`` (at most 72)."""
    return cached(f"bursts{hours}", lambda: {"bursts": engine.bursts_since(time.time() - min(hours, 72) * 3600)})


@app.get("/health")
def health():
    """GET /health: connection state, the last event time and the coverage gap."""
    s = engine.status()
    return {"ok": True, "connected": s["connected"], "last_event_at": s["last_event_at"], "gap_minutes": s["gap_minutes"]}
