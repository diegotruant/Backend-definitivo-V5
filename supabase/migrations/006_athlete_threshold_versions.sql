-- Athlete-level versioned training thresholds (phase 4).
-- FTP / LTHR / CP derived from published MMP or coach override.

create table if not exists athlete_threshold_versions (
    id uuid primary key default gen_random_uuid(),
    athlete_id uuid not null,
    threshold_version int not null,
    ftp_w double precision,
    lthr_bpm double precision,
    cp_w double precision,
    w_prime_j double precision,
    map_power_w double precision,
    mlss_power_w double precision,
    source_type varchar(32) not null default 'mmp_estimate'
        check (source_type in ('mmp_estimate', 'coach_override', 'lab_test')),
    source_mmp_status varchar(32),
    source_metabolic_profile_version int,
    is_active boolean not null default false,
    creation_reason varchar(64),
    calculated_at timestamptz not null default now(),
    valid_from_date date not null default current_date,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (athlete_id, threshold_version)
);

create index if not exists idx_athlete_threshold_versions_athlete_id
    on athlete_threshold_versions (athlete_id);

create index if not exists idx_athlete_threshold_versions_active
    on athlete_threshold_versions (athlete_id, is_active)
    where is_active = true;

create table if not exists athlete_current_thresholds (
    athlete_id uuid primary key,
    active_threshold_id uuid references athlete_threshold_versions(id) on delete set null,
    threshold_version int,
    ftp_w double precision,
    lthr_bpm double precision,
    cp_w double precision,
    updated_at timestamptz not null default now()
);

comment on table athlete_threshold_versions is
    'Immutable athlete threshold versions (FTP/LTHR/CP) from published MMP or coach override.';
comment on table athlete_current_thresholds is
    'Fast lookup of active training thresholds per athlete.';
