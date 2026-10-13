# Glossary

The terms the code, the results and the app use, with where each is defined.

| Term | Meaning | Defined in |
|---|---|---|
| **Article-hour** | One article's views in one UTC hour, desktop and mobile apart; kept from 5 views | ADR 0005, ADR 0007 |
| **Baseline** | An article's usual views for that hour: same weekday type, else same hour, else the language prior | prereg Phase 2 §2 |
| **Surprise (R3)** | Robust score of an hour against its baseline: excess over the median, scaled by the MAD plus a Poisson term | prereg Phase 2 §2 |
| **R1, R2** | Day-over-day and hour-over-hour spike rules; a candidate passes one of them | prereg Phase 2 §2 |
| **Spike** | A candidate hour with surprise at or above the threshold (8) that is not flagged as automated | prereg Phase 2 §2 |
| **Automation filter** | Flags an article-day with a very low mobile share or an almost flat hourly series | prereg Phase 2 §2, H3 |
| **Attention event** | One Wikidata item spiking in several languages within a 6 hour window; 3 languages in the evaluations, 2 in the product | ADR 0013, ADR 0021 |
| **Start hour** | First spike of the earliest window that holds enough languages | ADR 0013 |
| **Breadth** | Languages spiking within 24 h of the start | ADR 0021 |
| **Tier** | noticed (2+ languages), international (5+), planetary (20+) | ADR 0021 |
| **Lead language** | The first language to spike | prereg Phase 2 |
| **Excess views** | Views above baseline, summed over languages for 24 h from the start | prereg Phase 2 |
| **Single-language event** | An event whose lead language holds at least 95 % of the excess views | ADR 0019 |
| **Hero** | The event the app leads with: most excess views, at least 100,000 of them or a strong tier | ADR 0024 |
| **t0, snapshot** | The detection hour (second language's first spike), and the features known at t0, t0 + 1 h and t0 + 3 h | prereg Phase 4 |
| **Edit burst** | 5 edits by 3 editors in 30 minutes above the wiki's baseline, or a new article with 5 edits by 2 editors | prereg Phase 5, ADR 0032 |
| **Live event** | One item bursting in 2 languages within 120 minutes (30 in the pre-registered rule) | ADR 0032 |
| **Lake** | The public Hugging Face dataset: one Parquet file per day, a manifest, and the derived tables | ADR 0008, ADR 0012 |
