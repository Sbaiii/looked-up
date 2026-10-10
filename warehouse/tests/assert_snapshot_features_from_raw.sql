-- Leakage guard (prereg phase 4): recompute breadth_t and max_surprise_t straight from int_spikes for 50
-- random snapshots, using only rows at or before the snapshot time. Any row returned is a mismatch.
with s as (
    select * from {{ ref('fct_event_snapshots') }} order by hash(snapshot_id) limit 50
), raw as (
    select s.snapshot_id,
           count(distinct p.lang) filter (where p.surprise >= 8) as breadth_t,
           max(p.surprise) filter (where p.surprise >= 8) as max_surprise_t
    from s
    join {{ ref('int_spikes') }} p
      on p.qid = s.qid and not p.is_automated
     and p.ts_hour_start >= s.start_hour
     and p.ts_hour_start <= s.snapshot_ts
     and p.ts_hour_start < s.start_hour + interval 24 hour
    group by all
)
select s.snapshot_id, s.breadth_t, r.breadth_t as raw_breadth, s.max_surprise_t, r.max_surprise_t as raw_max
from s left join raw r using (snapshot_id)
where coalesce(r.breadth_t, 0) <> s.breadth_t
   or abs(coalesce(r.max_surprise_t, 0) - s.max_surprise_t) > 1e-9
   or s.snapshot_ts < s.t0
   or s.t0 < s.start_hour
