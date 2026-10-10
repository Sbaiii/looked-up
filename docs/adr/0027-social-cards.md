# 0027 — Social cards (Open Graph images)

- Status: accepted
- Date: 2026-10-10

## Decision

- **Per-day cards.** The hourly job renders a 1200×630 PNG per day with Pillow (`lookedup/og.py`):
  - the date, the day's lead event (ADR 0024) with its description, and "N languages in H hours";
  - a small flat map coloured like the app (ADR 0025).
  - They're written to `data/app/og/YYYY-MM-DD.png` on the Hub, for yesterday and today each hour. The backfill
    wrote every day.
- **Default card.** `app/assets/og.png` is the card for the site root, built with `python -m lookedup.og --default`.
- **Meta tags.** `index.html` carries Open Graph and Twitter tags pointing at the default card, so every shared URL
  previews.
- **Titles follow the view:** today, a day, an event on a day, or a language panel. Crawlers that don't run
  JavaScript see the default title.

## Not done (needs a server)

GitHub Pages is static, and `#/day/…` URLs are fragments that never reach a server. Choosing the per-day card for a
shared link therefore needs one of:

- a small edge function (e.g. a Cloudflare Worker), or a path-based URL that rewrites `og:image` to
  `…/data/app/og/<day>.png`;
- or prerendered `day/YYYY-MM-DD/index.html` stubs, published hourly, whose only job is the meta tags plus a
  redirect.

Both are left for later. The cards are already generated and hosted, so either option only needs to point at them.
