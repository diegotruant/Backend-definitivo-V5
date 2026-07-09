-- Post-migration smoke test for athlete MMP + metabolic profile + thresholds.
-- Run in Supabase SQL editor after applying migrations 004, 005, 006.
-- Replace :athlete_id with a real UUID before running section 3+.

-- =============================================================================
-- 1. Schema presence
-- =============================================================================
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in (
    'activity_mmp_points',
    'athlete_mmp_aggregate',
    'athlete_metabolic_profile_versions',
    'athlete_current_profile',
    'athlete_threshold_versions',
    'athlete_current_thresholds'
  )
order by table_name;
-- Expect 6 rows.

-- =============================================================================
-- 2. Index / constraint sanity
-- =============================================================================
select indexname, tablename
from pg_indexes
where schemaname = 'public'
  and tablename like 'athlete_%'
order by tablename, indexname;

-- =============================================================================
-- 3. Athlete MMP aggregate (replace athlete id)
-- =============================================================================
-- \set athlete_id '00000000-0000-0000-0000-000000000001'

select
    athlete_id,
    mmp_status,
    confidence_tier,
    coverage_score,
    n_activities_included,
    n_key_durations_covered,
    jsonb_array_length(mmp_curve_json) as curve_points,
    updated_at
from athlete_mmp_aggregate
where athlete_id = :'athlete_id';

-- =============================================================================
-- 4. Active metabolic profile (single is_active = true expected)
-- =============================================================================
select
    athlete_id,
    profile_version,
    profile_status,
    confidence_tier,
    map_power_w,
    mlss_power_w,
    vo2max_ml_kg_min,
    vlamax_mmol_l_s,
    is_active,
    creation_reason,
    calculated_at
from athlete_metabolic_profile_versions
where athlete_id = :'athlete_id'
order by profile_version desc;

select *
from athlete_current_profile
where athlete_id = :'athlete_id';

-- Invariant: at most one active profile version
select athlete_id, count(*) as active_count
from athlete_metabolic_profile_versions
where athlete_id = :'athlete_id' and is_active = true
group by athlete_id
having count(*) > 1;
-- Expect 0 rows.

-- =============================================================================
-- 5. Active thresholds
-- =============================================================================
select
    athlete_id,
    threshold_version,
    ftp_w,
    lthr_bpm,
    cp_w,
    source_type,
    is_active,
    creation_reason,
    calculated_at
from athlete_threshold_versions
where athlete_id = :'athlete_id'
order by threshold_version desc;

select *
from athlete_current_thresholds
where athlete_id = :'athlete_id';

-- =============================================================================
-- 6. MMP contribution audit (last 10 activity points)
-- =============================================================================
select
    activity_id,
    duration_s,
    power_w,
    activity_date,
    created_at
from activity_mmp_points
where athlete_id = :'athlete_id'
order by created_at desc
limit 20;

-- =============================================================================
-- 7. Readiness gate check (published → profile should exist)
-- =============================================================================
select
    a.athlete_id,
    a.mmp_status,
    p.profile_version,
    p.is_active as profile_active,
    t.threshold_version,
    t.ftp_w
from athlete_mmp_aggregate a
left join athlete_metabolic_profile_versions p
    on p.athlete_id = a.athlete_id and p.is_active = true
left join athlete_threshold_versions t
    on t.athlete_id = a.athlete_id and t.is_active = true
where a.mmp_status = 'published'
order by a.updated_at desc
limit 20;
-- Rows with mmp_status=published and null profile_version need more FITs or ingest rerun.
