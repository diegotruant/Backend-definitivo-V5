-- Athlete-level versioned metabolic profiles (phase 2).
-- Requires athletes table and athlete_mmp_aggregate from prior migrations.

create table if not exists athlete_metabolic_profile_versions (
    id uuid primary key default gen_random_uuid(),
    athlete_id uuid not null,
    profile_version int not null,
    vo2max_ml_kg_min double precision,
    vlamax_mmol_l_s double precision,
    mlss_power_w double precision,
    fatmax_power_w double precision,
    map_power_w double precision,
    apr_w double precision,
    phenotype_description text,
    phenotype_type varchar(64),
    confidence_score double precision not null default 0,
    confidence_tier varchar(32) not null default 'LOW',
    profile_status varchar(32) not null default 'provisional'
        check (profile_status in ('provisional', 'published')),
    is_active boolean not null default false,
    source_mmp_curve_json jsonb not null default '[]'::jsonb,
    source_mmp_status varchar(32),
    source_coverage_score double precision,
    n_activities_included int not null default 0,
    n_key_durations_covered int not null default 0,
    covered_duration_families jsonb not null default '{}'::jsonb,
    missing_duration_families jsonb not null default '[]'::jsonb,
    creation_reason varchar(64),
    calculated_at timestamptz not null default now(),
    valid_from_date date not null default current_date,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (athlete_id, profile_version)
);

create index if not exists idx_athlete_metabolic_profile_versions_athlete_id
    on athlete_metabolic_profile_versions (athlete_id);

create index if not exists idx_athlete_metabolic_profile_versions_active
    on athlete_metabolic_profile_versions (athlete_id, is_active)
    where is_active = true;

create index if not exists idx_athlete_metabolic_profile_versions_version
    on athlete_metabolic_profile_versions (athlete_id, profile_version desc);

create table if not exists athlete_current_profile (
    athlete_id uuid primary key,
    active_profile_id uuid references athlete_metabolic_profile_versions(id) on delete set null,
    profile_version int,
    profile_status varchar(32),
    confidence_score double precision,
    confidence_tier varchar(32),
    updated_at timestamptz not null default now()
);

comment on table athlete_metabolic_profile_versions is
    'Immutable athlete-level metabolic profile versions derived from published aggregate MMP.';
comment on table athlete_current_profile is
    'Fast lookup of active metabolic profile per athlete for frontend.';
