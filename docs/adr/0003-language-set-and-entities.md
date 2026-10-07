# 0003 — Top-50 Wikipedias, unified through Wikidata sitelinks

- Status: accepted; the top-50 language set is superseded by ADR 0006 (30 languages, human article views)
- Date: 2026-10-07
- Evidence: [feasibility §1, §4](../feasibility.md)

## Context

376 Wikipedias appear in a single hour. Raw view ranking is polluted by automated polling of
`Special:RecentChanges` on small wikis. Cross-language comparison needs one ID per topic.

## Decision

- **Language set:** the top 50 Wikipedias by *article* views (titles without a namespace prefix), held as
  configuration and re-ranked weekly over 7 days. The initial set covers 99.3 % of article views:
  `en ja de ru fr es it zh pl pt fa nl ar tr sv ko cs id he fi uk vi no hu th el sr ro da bg hr ca hi simple sk bn ms et ta ur lt az sl sh te zh-yue arz ka hy lv`.
- **Entity key:** Wikidata QID from the monthly `wb_items_per_site` dump, joined on (site, title) with spaces
  turned into underscores and `zh-yue` into `zh_yuewiki`. Add redirect resolution, plus an API / `page-create` fallback for pages newer
  than the dump.

## Consequences

- ≈ 95 % of article views get a QID. The rest is mostly search pages, files, redirects and very new articles.
- Breaking events often have no QID for hours in most languages. Detection must also watch related existing
  entities (place, person, team).
- `simple` and `sh` are in the set by traffic; whether they count as separate communities is still open.
