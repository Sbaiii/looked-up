# Tests

| Where | What | Run |
|---|---|---|
| `tests/test_*.py` | The Python pipeline: parsing, storage, scoring, events, evaluation, forecasts, app export | `.venv/bin/pytest` |
| `tests/live/` | The Python reference implementation of the live layer | `.venv/bin/pytest tests/live` |
| `tests/app/*.spec.js` | The web app in a browser (desktop and phone), with the Hub data mocked from `tests/app/fixtures/` | `npx playwright test` |
| `tests/app/unit/` | The app's pure modules (briefing, hero selection, colour scale, map projection, translations and formats, the Hub data client, card filters and orders, keyboard shortcuts, CSV downloads) | `npm run test:unit` |
| `worker/test/` | The Cloudflare Worker (rules, encoding, storage) in miniflare | `cd worker && npm test` |

- `tests/fixtures/` holds small real samples (a dump excerpt, a Current events page, a minute of recent changes).
  `make_fixtures.py` rebuilds them.
- No test needs the network or a Hugging Face token, except `tests/app/hub-cors.spec.js`, which checks that the
  live Hub still serves the app's data with CORS (skip it with `OFFLINE=1`).
- `test_no_git_in_pipeline.py` keeps every pipeline from committing to this repository.
- `test_cli.py` checks that every documented command is registered and passes its options through, with the work
  functions replaced by fakes; `test_figures.py` renders every results figure into a temp folder.
- `test_retrain.py` runs the weekly retrain end to end on a tiny warehouse; `tests/app/panels.spec.js` covers the
  panels around the day view, including the interface language a first visit picks from the browser;
  `tests/app/cards.spec.js` the event cards and the hero (sparklines, Wikipedia links, the URL guard, sharing).
- The day tools each have a spec: `search`, `sort`, `categories`, `langfilter`, `spread`, `download`, `datepick` and
  `shortcuts` (ADR 0035).
- `test_agreement.py`, `test_run.py` and the end-to-end tests in `test_run_v2_helpers.py` and
  `test_forecast_train.py` run each evaluation on synthetic data, with the ground truths and warehouse faked.
- Network calls (Wikimedia, Wikidata, the Hub) are always replaced by small fakes in the unit tests.
- `test_repo_consistency.py` keeps the docs in step with the code: the ADR, config, analysis and spike indexes,
  the README links, the schema against the model files, the three app translations and the two copies of the live rules.
  It also checks the code against itself across languages: the social card against the app (hero rule, colour
  scale, ramp), the app's data URL against the export, one User-Agent everywhere, and the ops command and workflow
  references against the command line and `.github/workflows/`.
- `test_readme_scorecard.py` keeps every number in the README scorecard and the phase results pages equal to the
  committed results in `docs/analysis/`, verdicts and headline counts included.
