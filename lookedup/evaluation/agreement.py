"""Agreement between production scoring and the batch warehouse on held-out hours (ADR 0014)."""

from __future__ import annotations

from datetime import date

from lookedup import db
from lookedup.analytics.config import load
from lookedup.analytics.production import daily_baselines_sql, score_hour_sql
from lookedup.settings import LOCAL_LAKE_DIR


def production_vs_batch(warehouse_db, day: date, hours: list[int], lake_dir=LOCAL_LAKE_DIR) -> dict:
    cfg = load()
    con = db.connect()
    con.execute("SET memory_limit = '7GB'; SET preserve_insertion_order = false")
    con.execute(f"ATTACH '{warehouse_db}' AS wh (READ_ONLY)")
    # only the files needed: 28 lookback days for the baselines, plus the scored day
    from datetime import timedelta

    days = [day - timedelta(days=k) for k in range(cfg.baseline["lookback_days"], -1, -1)]
    files = ", ".join(f"'{lake_dir}/data/hourly/year={d:%Y}/month={d:%m}/day={d:%d}.parquet'" for d in days)
    con.execute(f"""CREATE VIEW src AS SELECT ts_hour_start, ts_hour_start::DATE AS day,
        hour(ts_hour_start)::INT AS hour_of_day, (isodow(ts_hour_start) - 1) IN (5, 6) AS is_weekend,
        lang, title, views_desktop, views_mobile, views_desktop + views_mobile AS views,
        views_mobile / (views_desktop + views_mobile)::DOUBLE AS mobile_share
        FROM read_parquet([{files}])""")
    hrs = ", ".join(str(h) for h in hours)
    s = cfg.spike
    con.execute(f"""CREATE TABLE cand_titles AS SELECT DISTINCT lang, title FROM src
                    WHERE day = DATE '{day}' AND hour_of_day IN ({hrs}) AND views >= {s.min_views}""")
    con.execute(f"CREATE TABLE bl AS {daily_baselines_sql('src', day, cfg, restrict='cand_titles')}")
    r3 = cfg.spike.r3_threshold
    # production sees only the previous day and the current day
    two = ", ".join(f"'{lake_dir}/data/hourly/year={d:%Y}/month={d:%m}/day={d:%d}.parquet'" for d in days[-2:])
    con.execute(f"""CREATE VIEW src2 AS SELECT ts_hour_start, ts_hour_start::DATE AS day,
        hour(ts_hour_start)::INT AS hour_of_day, (isodow(ts_hour_start) - 1) IN (5, 6) AS is_weekend,
        lang, title, views_desktop, views_mobile, views_desktop + views_mobile AS views,
        views_mobile / (views_desktop + views_mobile)::DOUBLE AS mobile_share FROM read_parquet([{two}])""")
    con.execute("CREATE TABLE prod (lang VARCHAR, title VARCHAR, ts_hour_start TIMESTAMP)")
    for h in hours:
        con.execute(f"""INSERT INTO prod SELECT lang, title, ts_hour_start FROM ({score_hour_sql('src2', 'bl', day, h, cfg)})
                        WHERE surprise >= {r3} AND (r1 OR r2) AND NOT coalesce(is_automated, false)""")
    con.execute(f"""CREATE TABLE batch AS SELECT lang, title, ts_hour_start FROM wh.main.int_spikes
                    WHERE day = DATE '{day}' AND hour_of_day IN ({hrs}) AND is_spike""")
    both = con.execute("SELECT count(*) FROM prod INNER JOIN batch USING (lang, title, ts_hour_start)").fetchone()[0]
    n_prod = con.execute("SELECT count(*) FROM prod").fetchone()[0]
    n_batch = con.execute("SELECT count(*) FROM batch").fetchone()[0]
    return {"day": str(day), "hours": hours, "batch_spikes": n_batch, "production_spikes": n_prod, "both": both,
            "share_of_batch_reproduced": both / n_batch if n_batch else None,
            "share_of_production_in_batch": both / n_prod if n_prod else None,
            "baseline_slots": con.execute("SELECT count(*) FROM bl WHERE title IS NOT NULL").fetchone()[0]}
