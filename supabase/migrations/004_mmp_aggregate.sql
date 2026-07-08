-- Athlete-level MMP aggregation tables (Supabase / Postgres).
-- Run after core athlete/activity schema from SUPABASE_HANDOFF.md.

create table if not exists activity_mmp_points (
    id uuid primary key default gen_random_uuid(),
    athlete_id uuid not null,
    activity_id uuid not null,
    activity_file_id uuid,
    duration_s integer not null check (duration_s > 0),
    power_w numeric not null check (power_w > 0),
    activity_date date not null,
    created_at timestamptz not null default now(),
    unique (activity_id, duration_s)
);

create index if not exists idx_activity_mmp_points_athlete
    on activity_mmp_points (athlete_id);

create index if not exists idx_activity_mmp_points_athlete_activity
    on activity_mmp_points (athlete_id, activity_id);

create table if not exists athlete_mmp_aggregate (
    id uuid primary key default gen_random_uuid(),
    athlete_id uuid not null unique,
    mmp_curve_json jsonb not null default '[]'::jsonb,
    coverage_score numeric not null default 0,
    confidence_tier text not null default 'low',
    mmp_status text not null default 'collecting'
        check (mmp_status in ('collecting', 'provisional', 'published')),
    n_activities_included integer not null default 0,
    n_key_durations_covered integer not null default 0,
    updated_at timestamptz not null default now(),
    created_at timestamptz not null default now()
);

create index if not exists idx_athlete_mmp_aggregate_status
    on athlete_mmp_aggregate (mmp_status);

comment on table activity_mmp_points is
    'Per-activity MMP duration/power points extracted from ride bundles.';
comment on table athlete_mmp_aggregate is
    'Rolling best-power MMP curve per athlete with exposure status for frontend.';
comment on column athlete_mmp_aggregate.mmp_curve_json is
    'Array of {duration_s, power_w, source_activity_id, source_file_id, activity_date}.';
