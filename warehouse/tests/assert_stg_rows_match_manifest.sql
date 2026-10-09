-- For 3 pseudo-random days (fixed by hash), the number of rows per hour in stg_hourly must equal
-- the row count recorded in the lake manifest. Any returned row is a mismatch.
with days as (
    select distinct cast(ts_hour_start as date) as day
    from {{ ref('stg_manifest_hours') }}
    where cast(ts_hour_start as date) between date '{{ var("period_start") }}' and date '{{ var("period_end") }}'
    order by hash(day)
    limit 3
), manifest as (
    select m.ts_hour_start, m.rows
    from {{ ref('stg_manifest_hours') }} m join days d on cast(m.ts_hour_start as date) = d.day
), lake as (
    select h.ts_hour_start, count(*) as rows
    from {{ ref('stg_hourly') }} h join days d on h.day = d.day
    group by 1
)
select coalesce(m.ts_hour_start, l.ts_hour_start) as ts_hour_start, m.rows as manifest_rows, l.rows as lake_rows
from manifest m full outer join lake l using (ts_hour_start)
where m.rows is distinct from l.rows
