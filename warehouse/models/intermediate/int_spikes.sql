-- Article-hours passing R1 or R2 with surprise >= the lowest ablation threshold, with QID and
-- automation flag. `is_spike` applies the PRIMARY rule: R3 (>= r3_threshold) and (R1 or R2), not automated.
-- Unseen entities never satisfy R1 (enforced in int_baselines), so for them the rule is R3 and R2.
-- Automated rows are kept (is_automated) for the H3 audit and the separate automation ranking.
select
    b.candidate_id as spike_id,
    b.ts_hour_start,
    b.day,
    b.hour_of_day,
    b.lang,
    b.title,
    s.qid,
    coalesce('Q' || s.qid, b.lang || ':' || b.title) as entity_key,
    b.views,
    b.views_desktop,
    b.views_mobile,
    b.mobile_share,
    b.baseline_level,
    b.unseen,
    b.baseline_median,
    b.baseline_mad,
    b.views_yesterday,
    b.prev3_median,
    b.surprise,
    b.r1,
    b.r2,
    coalesce(f.is_automated, false) as is_automated,
    coalesce(f.is_low_mobile, false) as is_low_mobile,
    coalesce(f.is_flat, false) as is_flat,
    (b.surprise >= {{ var('r3_threshold') }} and not coalesce(f.is_automated, false)) as is_spike
from {{ ref('int_baselines') }} b
left join {{ ref('int_automation_flags') }} f
    on f.lang = b.lang and f.title = b.title and f.day = b.day
left join {{ ref('stg_sitelinks') }} s
    on s.lang = b.lang and s.title = b.title
where (b.r1 or b.r2) and b.surprise >= {{ var('min_r3_ablation') }}
