# Wikidata join coverage

Share of retained hourly views whose `(lang, title)` matches a row of `data/wikidata/sitelinks.parquet`
(57.2 M sitelinks for the 30 active languages, built from the 2026-10-03 `wb_items_per_site` dump).
Regenerate with `python -m lookedup.cli coverage --hours 24 --out docs/wikidata_coverage.md`.

Hours: 2026-10-07 07:00 to 2026-10-07 11:00 UTC (4 hours), retained article rows (views_desktop + views_mobile, >= 5 per hour).

| Lang | Views | Matched to a QID | Coverage |
|---|---|---|---|
| en | 16,206,434 | 15,969,990 | 98.5 % |
| ja | 3,599,529 | 3,568,953 | 99.2 % |
| de | 1,952,206 | 1,936,245 | 99.2 % |
| fr | 1,557,996 | 1,540,619 | 98.9 % |
| ru | 1,461,122 | 1,442,888 | 98.8 % |
| it | 820,249 | 807,702 | 98.5 % |
| zh | 770,521 | 745,685 | 96.8 % |
| es | 579,405 | 573,595 | 99.0 % |
| fa | 441,948 | 422,689 | 95.6 % |
| pl | 356,260 | 354,423 | 99.5 % |
| tr | 212,196 | 209,315 | 98.6 % |
| ar | 164,149 | 161,955 | 98.7 % |
| pt | 151,509 | 147,962 | 97.7 % |
| nl | 148,143 | 143,272 | 96.7 % |
| id | 140,570 | 136,220 | 96.9 % |
| ko | 95,274 | 91,345 | 95.9 % |
| sv | 93,762 | 92,949 | 99.1 % |
| cs | 88,906 | 88,394 | 99.4 % |
| vi | 82,556 | 79,498 | 96.3 % |
| he | 70,874 | 61,880 | 87.3 % |
| fi | 59,455 | 58,900 | 99.1 % |
| th | 58,673 | 57,523 | 98.0 % |
| uk | 58,475 | 57,183 | 97.8 % |
| hu | 47,899 | 47,256 | 98.7 % |
| el | 36,826 | 36,641 | 99.5 % |
| hi | 35,822 | 35,672 | 99.6 % |
| ro | 31,320 | 30,783 | 98.3 % |
| sr | 16,993 | 16,185 | 95.2 % |
| bg | 16,397 | 16,147 | 98.5 % |
| no | 14,974 | 14,784 | 98.7 % |
| **all** | 29,370,443 | 28,946,653 | 98.6 % |

## Reading it

- Coverage is **98.6 %** overall, much higher than the 93–95 % measured in Phase 0. The difference is that
  `Special:Search`, other namespace pages and the main page are now removed before the join (ADR 0006/0007).
- What remains unmatched is mostly **redirects** (pageviews count the requested title, not the target), **articles
  created after the dump**, and a few title variants.
- **he (87.3 %)** is the outlier. It deserves a look in Phase 2: likely redirects or spelling variants that are
  heavily linked from outside.
- This sample covers 4 hours (07:00–11:00 UTC, 7 Oct), so it is biased toward languages awake at that time.
  Re-run on 24 h once the lake is live.
