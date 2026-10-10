# 0026 — Wikidata descriptions and gender in the exports

- Status: accepted (adds fields to ADR 0022's schema; `schema_version` stays 1 because the change is additive)
- Date: 2026-10-10

## Context

A bare label like "Zodiac" or "Pac" doesn't tell readers what the event is. The v1 death sentence used "their" for
everyone, and its French and Spanish versions avoided gender agreement altogether.

## Decision

- **Fetch** each entity's Wikidata **description** (in our 30 languages) and **P21** (sex or gender) through the
  Query Service, 400 QIDs per batch.
  - They are cached in `entity_text.parquet` and joined into `dim_entities` (`descriptions_json`, `gender`).
  - The hourly job fetches only new QIDs.
- **Gender mapping:**
  - female or trans woman → `female`;
  - male or trans man → `male`;
  - any other value (e.g. non-binary) → `other`;
  - no P21 → none.
- **Exports stay small:**
  - `desc` only in the app's UI languages (en, fr, es), truncated to 80 characters with "…";
  - `gender` only when known.
  - The app shows the description in the viewer's language, falling back to English: under the hero label, on cards,
    and with the briefing.
- **Briefing death sentences (EN / FR / ES):**

  | P21 | Sentence |
  |---|---|
  | female | "after the news of her death" / "tout juste disparue" / "recién fallecida" |
  | male | "after the news of his death" / "tout juste disparu" / "recién fallecido" |
  | other, unknown | pronoun-free: "after the news of Dolly Parton's death" / "après l'annonce du décès de Dolly Parton" / "tras la noticia de la muerte de Dolly Parton" |

  All nine cases are covered by `tests/app/unit/briefing.test.mjs`.

## Consequences

- Descriptions are Wikidata's own text, which is sometimes missing or terse. The label stands alone then.
- Gender is used only to choose a grammatical form. It is never displayed.
