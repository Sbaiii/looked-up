"""Q2: Wikimedia pageviews REST API — top articles, per-article history, geography.

Usage: .venv/bin/python spike/q2_rest_api.py
Writes data/derived/q2_rest_api.json.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

from common import DERIVED, session

API = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
WD = "https://www.wikidata.org/w/api.php"


def get(url: str) -> tuple[int, dict | None, float, dict]:
    t0 = time.perf_counter()
    r = session.get(url, timeout=30)
    dt = time.perf_counter() - t0
    hdr = {k: v for k, v in r.headers.items() if "ratelimit" in k.lower() or k.lower() in ("cache-control", "age")}
    try:
        body = r.json()
    except ValueError:
        body = None
    time.sleep(0.3)  # polite: sequential + small pause
    return r.status_code, body, round(dt, 2), hdr


def main() -> None:
    res: dict = {}
    yday = datetime.now(timezone.utc) - timedelta(days=1)
    y, m, d = f"{yday:%Y}", f"{yday:%m}", f"{yday:%d}"

    # ---- 2a: top articles yesterday ----------------------------------------------
    res["top"] = {}
    for lang in ["en", "fr", "ja", "ar"]:
        code, body, dt, hdr = get(f"{API}/top/{lang}.wikipedia/all-access/{y}/{m}/{d}")
        if code == 200:
            arts = body["items"][0]["articles"]
            res["top"][lang] = {"status": code, "latency_s": dt, "n_articles": len(arts),
                                "top10": [(a["article"], a["views"]) for a in arts[:10]], "headers": hdr}
        else:
            res["top"][lang] = {"status": code, "body": body}
        print(lang, code, res["top"][lang].get("top10", body)[:5] if code == 200 else body)

    # ---- 2b: one article in 5 languages, last 90 days + earliest date -------------
    # Resolve the same entity's titles via Wikidata (Q90 = Paris).
    code, body, _, _ = get(f"{WD}?action=wbgetentities&ids=Q90&props=sitelinks&format=json")
    links = body["entities"]["Q90"]["sitelinks"]
    langs = ["en", "fr", "ja", "ar", "de"]
    titles = {l: links[f"{l}wiki"]["title"].replace(" ", "_") for l in langs}
    start = (yday - timedelta(days=89)).strftime("%Y%m%d")
    end = yday.strftime("%Y%m%d")
    res["per_article"] = {"entity": "Q90 (Paris)", "range": [start, end], "langs": {}}
    for l, t in titles.items():
        from urllib.parse import quote
        tq = quote(t, safe="")
        code, body, dt, _ = get(f"{API}/per-article/{l}.wikipedia/all-access/user/{tq}/daily/{start}/{end}")
        items = body.get("items", []) if code == 200 else []
        # earliest available: ask from 2015-01-01
        c2, b2, _, _ = get(f"{API}/per-article/{l}.wikipedia/all-access/user/{tq}/daily/20150101/20150801")
        first = b2["items"][0]["timestamp"] if c2 == 200 and b2.get("items") else None
        res["per_article"]["langs"][l] = {
            "title": t, "status": code, "days": len(items),
            "total_views_90d": sum(i["views"] for i in items),
            "first_day": items[0]["timestamp"] if items else None,
            "last_day": items[-1]["timestamp"] if items else None,
            "earliest_available": first,
        }
        print(l, res["per_article"]["langs"][l])
    # hourly granularity on per-article?
    code, body, _, _ = get(f"{API}/per-article/en.wikipedia/all-access/user/Paris/hourly/{end}00/{end}23")
    res["per_article_hourly"] = {"status": code, "detail": (body or {}).get("detail") or (body or {}).get("title")}

    # ---- 2c: geography --------------------------------------------------------------
    geo = {}
    last_month = (datetime.now(timezone.utc).replace(day=1) - timedelta(days=1))
    lm_y, lm_m = f"{last_month:%Y}", f"{last_month:%m}"
    code, body, _, _ = get(f"{API}/top-by-country/en.wikipedia/all-access/{lm_y}/{lm_m}")
    geo["top-by-country"] = {"url": f"top-by-country/en.wikipedia/all-access/{lm_y}/{lm_m}", "status": code,
                             "sample": body["items"][0]["countries"][:8] if code == 200 else body}
    for country in ["FR", "JP", "EG", "US"]:
        code, body, _, _ = get(f"{API}/top-per-country/{country}/all-access/{y}/{m}/{d}")
        geo[f"top-per-country/{country}"] = {
            "status": code,
            "n": len(body["items"][0]["articles"]) if code == 200 else None,
            "sample": body["items"][0]["articles"][:5] if code == 200 else body,
        }
    # how far back does top-per-country go?
    for probe in ["2021/01/01", "2021/02/09", "2022/01/01"]:
        code, _, _, _ = get(f"{API}/top-per-country/FR/all-access/{probe}")
        geo[f"top-per-country/FR earliest probe {probe}"] = code
    for probe in ["2020/06/01", "2020/12/31"]:
        code, _, _, _ = get(f"{API}/top-per-country/FR/all-access/{probe}")
        geo[f"top-per-country/FR earliest probe {probe}"] = code
    # which countries are served at all (protection list => 404)
    probe_countries = ["US", "GB", "IN", "DE", "FR", "JP", "BR", "MX", "ES", "IT", "RU", "UA", "TR", "IR",
                       "EG", "SA", "AE", "MA", "DZ", "NG", "KE", "ZA", "CN", "HK", "TW", "KR", "VN", "ID",
                       "PK", "BD", "IL", "PS", "SY", "IQ", "CU", "VE", "BY", "KP"]
    served = {}
    for c in probe_countries:
        code, _, _, _ = get(f"{API}/top-per-country/{c}/all-access/{y}/{m}/{d}")
        served[c] = code
    geo["countries_probe"] = served
    geo["countries_missing"] = [c for c, v in served.items() if v != 200]
    # same-day availability (today) for top-per-country and top
    today = datetime.now(timezone.utc)
    code, _, _, _ = get(f"{API}/top-per-country/FR/all-access/{today:%Y/%m/%d}")
    geo["top-per-country today"] = code
    code, _, _, _ = get(f"{API}/top/en.wikipedia/all-access/{today:%Y/%m/%d}")
    res["top_today_status"] = code
    res["geo"] = geo

    (DERIVED / "q2_rest_api.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(json.dumps(res["geo"], indent=1, ensure_ascii=False)[:4000])
    print("per-article hourly:", res["per_article_hourly"], "top today:", res["top_today_status"])


if __name__ == "__main__":
    main()
