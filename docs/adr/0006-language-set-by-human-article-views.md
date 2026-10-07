# 0006 — Language set v1: 30 Wikipedias ranked by human article views

- Status: accepted (project owner decision D3). Supersedes the "top 50" choice of ADR 0003.
- Date: 2026-10-08
- Evidence: [feasibility §1](../feasibility.md), `config/languages.yml`

## Context

Raw view rankings are polluted. Small wikis rank high because of automated polling of special pages, and `user`
traffic still contains bots.

## Decision

Rank Wikipedias by **human article views** over **7 full days** of `pageview_complete`. The ranking excludes:

- the main page (localised, from siteinfo), plus `Main_Page`;
- titles with a namespace prefix, using every localised name and alias from each wiki's siteinfo
  (Special, Wikipedia, Talk, File, User, Category, Template, Help, Portal, Draft, …);
- the `-` title;
- titles with > 1,000 views over the window and < 5 % mobile (automation heuristic).

The candidates are the top 60 wikis by raw views. `config/languages.yml` stores the full ranking with metadata
(code, English name, native name, approximate speakers from Wikidata P1098, view statistics) and `top_n: 30`.
Ingestion uses the first `top_n` entries.

## Consequences

- To extend to 50 languages, set `top_n: 50`. The namespaces of all 60 candidates are already in `config/namespaces.json`.
  Re-run `python -m lookedup.cli languages` to refresh the ranking.
- The automation heuristic is used **only for choosing languages**. Ingestion keeps such titles (they pass the
  namespace filter) because the separate desktop/mobile columns (ADR 0005) let analysis apply the heuristic later.
