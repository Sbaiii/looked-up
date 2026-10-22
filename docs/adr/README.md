# Architecture decision records

One record per decision, numbered in the order they were taken. A later record that changes an earlier
decision says so in its status line; deviations from a pre-registration are recorded here, never edited into it.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-pageview-sources.md) | Pageview sources: hourly dumps live, pageview_complete for history | accepted |
| [0002](0002-storage-and-compute.md) | Storage on Hugging Face Datasets, compute on GitHub Actions | accepted |
| [0003](0003-language-set-and-entities.md) | Top-50 Wikipedias, unified through Wikidata sitelinks | accepted |
| [0004](0004-pitch-attention-hour-by-hour.md) | Pitch: what the world pays attention to, hour by hour, across languages | accepted |
| [0005](0005-separate-desktop-and-mobile-views.md) | Store desktop and mobile views as separate columns | accepted |
| [0006](0006-language-set-by-human-article-views.md) | Language set v1: 30 Wikipedias ranked by human article views | accepted |
| [0007](0007-retention-five-views-per-hour.md) | Retention: hourly article rows with at least 5 views | accepted |
| [0008](0008-lake-layout-and-schema.md) | Lake on Hugging Face: layout, schema, manifest, hour alignment | accepted |
| [0009](0009-hourly-job-idempotent-self-healing.md) | Hourly job on GitHub Actions: idempotent and self-healing | accepted |
| [0010](0010-backfill-from-pageview-complete.md) | Backfill 90 days from pageview_complete | accepted |
| [0011](0011-wikidata-sitelinks.md) | Wikidata sitelinks for the active languages, refreshed monthly | accepted |
| [0012](0012-one-parquet-file-per-day.md) | One Parquet file per day | accepted, supersedes the hourly files of ADR 0008 |
| [0013](0013-phase2-implementation-and-deviations.md) | Phase 2: implementation choices, interpretations and deviations | accepted |
| [0014](0014-production-scoring.md) | Production scoring: daily baselines, hourly spikes, events and latest.json | accepted |
| [0015](0015-attention-event-definitions.md) | Attention event definitions (Phase 2) | accepted |
| [0016](0016-data-outside-icloud.md) | Keep data outside the repository and iCloud; cap DuckDB spill | accepted |
| [0017](0017-hourly-trigger-reliability.md) | Hourly trigger reliability: uncommon cron minute, external trigger, wider catch-up | accepted |
| [0018](0018-baselines-in-actions-cache.md) | Production baselines in the Actions cache; monthly Hub history squash | accepted |
| [0019](0019-single-language-events.md) | Single-language events (no censoring) | accepted |
| [0020](0020-phase2b-deviations.md) | Phase 2b deviations and data issues | accepted |
| [0021](0021-product-tiers.md) | Product tiers by breadth (min two languages) | accepted |
| [0022](0022-app-data-exports.md) | App data exports on the Hub (data/app/) | accepted |
| [0023](0023-language-geography.md) | The globe is by language | accepted |
| [0024](0024-hero-selection.md) | Hero selection: excess views, a strength floor and widening windows | accepted |
| [0025](0025-absolute-colour-scale.md) | Absolute colour scale on the map and globe | accepted |
| [0026](0026-descriptions-and-gender.md) | Wikidata descriptions and gender in the exports | accepted |
| [0027](0027-social-cards.md) | Social cards (Open Graph images) | accepted |
| [0028](0028-phase4-design-choices.md) | Phase 4 design choices that differ from the brief | accepted, recorded with the pre-registration |
| [0029](0029-forecast-production.md) | Forecasts in production: training data, calibration and what is shown | accepted |
| [0030](0030-live-layer-hosting.md) | Hosting the live layer without a paid Space | superseded by ADR 0032 |
| [0031](0031-warehouse-refresh.md) | Refreshing the warehouse past the registered period | accepted |
| [0032](0032-live-layer-on-workers.md) | The live layer moves to a Cloudflare Worker, and its rules are tuned | accepted |
| [0033](0033-live-state-in-d1.md) | Live-layer state in D1, five poll groups | accepted, frozen |
| [0034](0034-duckdb-2.md) | DuckDB 2.0: read single rows with `db.one` | accepted |
