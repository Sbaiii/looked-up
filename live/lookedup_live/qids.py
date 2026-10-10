"""Lazy QID resolution for bursting titles only (Wikidata wbgetentities, sites + titles), with labels and
descriptions in the app languages. Cached in memory and on disk."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import requests

from lookedup_live import USER_AGENT

log = logging.getLogger(__name__)
API = "https://www.wikidata.org/w/api.php"
UI = ("en", "fr", "es")


class Resolver:
    def __init__(self, cache_file: Path | None = None) -> None:
        self.cache_file = cache_file
        self.qids: dict[str, str | None] = {}          # "lang|title" -> QID (None = no item)
        self.items: dict[str, dict] = {}               # QID -> {labels, desc}
        self.pending: set[tuple[str, str]] = set()
        self.lock = threading.Lock()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        if cache_file and cache_file.exists():
            try:
                d = json.loads(cache_file.read_text())
                self.qids, self.items = d.get("qids", {}), d.get("items", {})
            except ValueError:
                pass

    def get(self, lang: str, title: str) -> str | None:
        return self.qids.get(f"{lang}|{title}")

    def want(self, lang: str, title: str) -> None:
        if f"{lang}|{title}" not in self.qids:
            with self.lock:
                self.pending.add((lang, title))

    def resolve_pending(self) -> int:
        with self.lock:
            todo, self.pending = sorted(self.pending), set()
        by_lang: dict[str, list[str]] = {}
        for lang, title in todo:
            by_lang.setdefault(lang, []).append(title)
        n = 0
        for lang, titles in by_lang.items():
            for i in range(0, len(titles), 50):
                chunk = titles[i:i + 50]
                site = lang.replace("-", "_") + "wiki"
                try:
                    r = self.session.get(API, params={"action": "wbgetentities", "sites": site, "titles": "|".join(chunk),
                                                      "props": "labels|descriptions|sitelinks", "sitefilter": site,
                                                      "languages": "|".join(dict.fromkeys(UI + (lang,))),
                                                      "normalize": 1, "format": "json"}, timeout=30)
                    r.raise_for_status()
                    ents = r.json().get("entities", {})
                except (requests.RequestException, ValueError) as e:
                    log.warning("wikidata lookup failed: %s", e)
                    with self.lock:
                        self.pending |= {(lang, t) for t in chunk}
                    return n
                found = {}
                for key, e in ents.items():
                    if key.startswith("Q") and "missing" not in e:
                        t = e.get("sitelinks", {}).get(site, {}).get("title")
                        if t:
                            found[t] = key
                        self.items[key] = {"labels": {k: v["value"] for k, v in e.get("labels", {}).items()},
                                           "desc": {k: v["value"] for k, v in e.get("descriptions", {}).items()}}
                for t in chunk:
                    self.qids[f"{lang}|{t}"] = found.get(t) or found.get(t.replace("_", " "))
                    n += 1
                time.sleep(0.2)
        return n

    def save(self) -> None:
        if self.cache_file:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps({"qids": self.qids, "items": self.items}, ensure_ascii=False))
