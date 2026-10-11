# Tests

| Where | What | Run |
|---|---|---|
| `tests/test_*.py` | The Python pipeline: parsing, storage, scoring, events, evaluation, forecasts, app export | `.venv/bin/pytest` |
| `tests/live/` | The Python reference implementation of the live layer | `.venv/bin/pytest tests/live` |
| `tests/app/*.spec.js` | The web app in a browser (desktop and phone), with the Hub data mocked from `tests/app/fixtures/` | `npx playwright test` |
| `tests/app/unit/` | The app's pure modules (briefing, hero selection) | `npm run test:unit` |
| `worker/test/` | The Cloudflare Worker (rules, encoding, storage) in miniflare | `cd worker && npm test` |

- `tests/fixtures/` holds small real samples (a dump excerpt, a Current events page, a minute of recent changes).
  `make_fixtures.py` rebuilds them.
- No test needs the network or a Hugging Face token, except `tests/app/hub-cors.spec.js`, which checks that the
  live Hub still serves the app's data with CORS (skip it with `OFFLINE=1`).
- `test_no_git_in_pipeline.py` keeps every pipeline from committing to this repository.
