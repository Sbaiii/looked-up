# 0025 — Absolute colour scale on the map and globe

- Status: accepted (supersedes the colour rule in ADR 0023; the language-to-country mapping stands)
- Date: 2026-10-10

## Context

v1 coloured each language relative to the event's own maximum, as a share of excess views. Every event therefore
had a fully saturated language, so a four-language blip looked as bright as a planetary event.

## Decision

- **Colour by each language's peak surprise (R3) on one fixed scale for every event.** The scale is logarithmic,
  from the spike threshold **8** to **5,000+**: `v = ln(s / 8) / ln(5000 / 8)`, clamped to [0, 1].
- **Legend:** "less / more", with ticks at 8, 50, 500 and 5k+, and the caption "peak surprise in each language,
  same scale for every event".
- **Countries** with no spike in any of their languages stay neutral. A country with several languages takes the
  max (ADR 0023).
- **Why not 0 to 50.** In the 84-day batch, the median per-language surprise is 79 for noticed events, 109 for
  international and 124 for planetary, and the 90th percentile is 424 to 719.
  - A scale capped at 50 would saturate most spikes of every tier, which is the opposite of the intent.
  - On the 8–5,000 scale, the median noticed spike sits at ≈ 0.36. The median languages of the two planetary
    events of August sit at ≈ 0.95: Dolly Parton (3,439) and Hayden Panettiere (3,849).
- **Where it lives:** `app/js/scale.js`, mirrored in `lookedup/og.py` so the social cards match the app.

## Consequences

- Surprise is per-language and baseline-relative, so small wikis with near-zero baselines can still blaze on modest
  traffic. That is the same caveat as the lead language (Phase 2 limitations).
