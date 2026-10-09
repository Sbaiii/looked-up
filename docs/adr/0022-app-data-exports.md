# 0022 — App data exports on the Hub (data/app/)

- Status: accepted
- Date: 2026-10-09

## Context

The web app (Phase 3) is static, so it needs small, ready-made JSON files. Two hosting options were considered:
serve them from the Hugging Face dataset, or copy them into the GitHub Pages deployment on every hourly run.

## Decision

- **Files**, written by `lookedup/app_export.py` under `data/app/`, each with `schema_version: 1`:
  - `today.json`: events that started in the last 24 h.
  - `days/YYYY-MM-DD.json`: one UTC day.
  - `stats.json`: per-day summaries for the last 90 days, totals, per-language totals and lead shares, tier counts,
    and a timeline of event counts per start hour.
- **Events are product events** (ADR 0021). A day or today file holds:
  - the top **200** multi-language events by breadth;
  - each language's top **5** events (for the per-language panel);
  - the top **10** single-language events per lead language (the "only here" lists).
- **Each event carries:**
  - tier, breadth, lead language, category, excess views, peak surprise and spread;
  - labels in every one of our languages that has an article, with a Wikipedia URL per language and the Wikidata QID;
  - per-language rows: first spike hour, peak surprise, excess views and spread lag;
  - a 48-point sparkline of total views across languages, from 24 h before the start to 23 h after. Hours not
    yet ingested are `null`.
- Summaries count all events, not only the published ones.
- **Gzip twins.** The Hub serves files uncompressed: a day file is ≈ 590 KB of JSON but ≈ 135 KB gzipped. Every
  file is therefore also written as `*.json.gz`. The app fetches the twin and inflates it with `DecompressionStream`,
  falling back to the plain file. The `.json` files stay the readable contract for other users.
- **Hosting: the Hub, read directly by the browser.**
  - CORS was verified: `resolve/main/...` answers 307 then 200, both with `Access-Control-Allow-Origin` echoing the
    page origin.
  - A browser fetch from a test page is covered by the Playwright smoke tests.
  - No Pages fallback is needed.
- **Writers:**
  - The hourly job (`cli app-export`, after `score`) rebuilds today, the day files of yesterday and today, and
    `stats.json`, from the production spike files with product settings.
  - `cli app-export --backfill --upload` rebuilt every day: from the warehouse marts until 7 Oct, then from
    production spikes.

## Consequences

- One extra Hub commit per hourly run. The monthly squash (ADR 0018) keeps history bounded.
- **Coverage.** Day files start on 16 Jul 2026, when scoring starts after the 7-day baseline warm-up. On 9 Oct that
  gives 86 days, not 90. `stats.json` keeps a rolling 90 days.
- Live days use production approximations: excess views over spike rows only (ADR 0014), and categories from
  cached Wikidata claims.
