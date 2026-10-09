-- Typed hourly views with calendar fields and mobile share.
-- QIDs are attached at the (lang, title) level downstream (int_spikes, dim_entities), not per row:
-- joining 57 M sitelinks to ~1.1 B rows cost ~1,000x (ADR 0013).
select
    ts_hour_start,
    cast(ts_hour_start as date) as day,
    cast(hour(ts_hour_start) as integer) as hour_of_day,
    (isodow(ts_hour_start) - 1) in ({{ var('weekend_days') | join(', ') }}) as is_weekend,
    lang,
    title,
    views_desktop,
    views_mobile,
    views_desktop + views_mobile as views,
    views_mobile / (views_desktop + views_mobile)::double as mobile_share
from {{ source('lake', 'hourly') }}
where cast(ts_hour_start as date) between date '{{ var("period_start") }}' and date '{{ var("period_end") }}'
