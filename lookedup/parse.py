"""Parsing rules for pageview dumps: project codes, titles, namespaces, retention.

This module is the single source of truth for what counts as a Wikipedia article
row. ``transform`` applies the same rules in DuckDB for speed; tests check both agree.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from urllib.parse import unquote

from lookedup.settings import MIN_VIEWS

# Hourly dump project codes: "en" (desktop) and "en.m" (mobile web + apps).
_WIKIPEDIA_CODE = re.compile(r"^([a-z][a-z0-9-]*)(\.m)?$")

# Bare or ".m" codes that are not language Wikipedias.
NON_LANGUAGE_CODES = frozenset({
    "commons", "meta", "species", "incubator", "outreach", "wikimania", "wikidata",
    "foundation", "mediawiki", "wikisource", "wikitech", "login", "sources", "beta",
    "nostalgia", "strategy", "usability", "quality", "office", "ten", "test", "test2",
    "advisory", "donate", "api", "vote", "wikifunctions", "auth", "thankyou",
})

# Canonical (English) namespace names, applied to every language on top of the
# localised names from config/namespaces.json. Lower case, spaces not underscores.
CANONICAL_NAMESPACES = frozenset({
    "media", "special", "talk", "user", "user talk", "wikipedia", "wikipedia talk",
    "project", "project talk", "file", "file talk", "image", "image talk",
    "mediawiki", "mediawiki talk", "template", "template talk", "help", "help talk",
    "category", "category talk", "portal", "portal talk", "draft", "draft talk",
    "module", "module talk", "timedtext", "timedtext talk", "gadget", "gadget talk",
    "gadget definition", "gadget definition talk",
})  # wiki-specific aliases (WP:, WT:, ...) come from siteinfo, not from here

MAIN_PAGE_DEFAULT = "Main_Page"
INVALID_TITLES = frozenset({"-", ""})

_PVC_HOUR = re.compile(r"([A-X])(\d+)")
_PVC_MOBILE = {"mobile-web", "mobile-app"}


def parse_project(code: str) -> tuple[str, bool] | None:
    """Hourly dump project code -> (lang, is_mobile), or None if not a language Wikipedia.

    >>> parse_project("fr.m")
    ('fr', True)
    >>> parse_project("en.d") is None   # Wiktionary
    True
    """
    m = _WIKIPEDIA_CODE.match(code)
    if not m:
        return None
    lang = m.group(1)
    if lang in NON_LANGUAGE_CODES:
        return None
    return lang, m.group(2) is not None


def parse_pvc_project(wiki: str, access: str) -> tuple[str, bool] | None:
    """pageview_complete ``en.wikipedia`` + access type -> (lang, is_mobile).

    ``mobile-web`` and ``mobile-app`` are both mobile: the hourly dumps fold apps into
    ``xx.m`` (verified exact against the REST API, see feasibility §1).
    """
    lang, _, project = wiki.partition(".")
    if project != "wikipedia" or lang in NON_LANGUAGE_CODES:
        return None
    if access == "desktop":
        return lang, False
    if access in _PVC_MOBILE:
        return lang, True
    return None


def normalize_title(raw: str) -> str:
    """Canonical title: percent-decoding applied once, spaces -> underscores.

    Titles in the dumps are already decoded; a literal ``%`` is usually part of the
    title (``100%_Love``). Invalid escapes are kept as is, and a decode that would
    produce invalid UTF-8 falls back to the raw title.
    """
    title = raw
    if "%" in title:
        try:
            title = unquote(title, errors="strict")
        except UnicodeDecodeError:
            title = raw
    if " " in title:
        title = title.replace(" ", "_")
    return title


def namespace_prefix(title: str) -> str | None:
    """Lower-cased candidate namespace prefix (``Spécial:Recherche`` -> ``spécial``)."""
    head, sep, _ = title.partition(":")
    if not sep or not head:
        return None
    return head.replace("_", " ").strip().lower()


@dataclass
class ArticleFilter:
    """Decides whether a (lang, title) is an article (main namespace, not the main page).

    ``namespaces`` maps lang -> lower-cased namespace names/aliases (non-zero ns);
    ``main_pages`` maps lang -> main page title with underscores.
    """

    namespaces: Mapping[str, Iterable[str]] = field(default_factory=dict)
    main_pages: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._ns = {lang: frozenset(n.lower() for n in names) | CANONICAL_NAMESPACES
                    for lang, names in self.namespaces.items()}
        self._main = {lang: t.replace(" ", "_") for lang, t in self.main_pages.items()}

    def namespaces_for(self, lang: str) -> frozenset[str]:
        return self._ns.get(lang, CANONICAL_NAMESPACES)

    def excluded_titles(self, lang: str) -> frozenset[str]:
        main = self._main.get(lang)
        return frozenset({MAIN_PAGE_DEFAULT} | ({main} if main else set()))

    def is_article(self, lang: str, title: str) -> bool:
        if title in INVALID_TITLES or title in self.excluded_titles(lang):
            return False
        prefix = namespace_prefix(title)
        return prefix is None or prefix not in self.namespaces_for(lang)


def keep_row(views_desktop: int, views_mobile: int, min_views: int = MIN_VIEWS) -> bool:
    """D4 retention rule: keep an hourly row when desktop + mobile >= ``min_views``."""
    return views_desktop + views_mobile >= min_views


def parse_dump_line(line: str) -> tuple[str, str, int] | None:
    """``"en Main_Page 42 0"`` -> ("en", "Main_Page", 42). Malformed lines -> None."""
    parts = line.rstrip("\n").split(" ")
    if len(parts) != 4:
        return None
    project, title, views, _bytes = parts
    try:
        return project, title, int(views)
    except ValueError:
        return None


def parse_pvc_line(line: str) -> tuple[str, str, str, str] | None:
    """pageview_complete line -> (wiki, title, access, hourly_string).

    Rows normally have 6 columns (wiki title page_id access daily hourly); rows
    without a page id have 5 (known upstream issue), so we index from both ends.
    """
    parts = line.rstrip("\n").split(" ")
    if len(parts) not in (5, 6):
        return None
    return parts[0], parts[1], parts[-3], parts[-1]


def decode_pvc_hours(encoded: str) -> dict[int, int]:
    """``"A3C12"`` -> {0: 3, 2: 12} (letters A..X are hours 0..23)."""
    out: dict[int, int] = {}
    for letter, count in _PVC_HOUR.findall(encoded):
        hour = ord(letter) - 65
        out[hour] = out.get(hour, 0) + int(count)
    return out
