-- DDTraining Workout System V1 schema draft for PostgreSQL / Supabase.
-- Use UUID generation according to your Supabase setup, e.g. gen_random_uuid().

create table if not exists workout_templates (
    id uuid primary key default gen_random_uuid(),
    owner_type text not null default 'system', -- system | coach | team
    owner_id uuid,
    title text not null,
    description text,
    discipline text not null default 'cycling',
    goal text,
    difficulty text,
    tags text[] not null default '{}',
    steps_json jsonb not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists workout_template_versions (
    id uuid primary key default gen_random_uuid(),
    template_id uuid not null references workout_templates(id) on delete cascade,
    version integer not null,
    title text not null,
    steps_json jsonb not null,
    change_note text,
    created_by uuid,
    created_at timestamptz not null default now(),
    unique(template_id, version)
);

create table if not exists workout_prescriptions (
    id uuid primary key default gen_random_uuid(),
    template_id uuid references workout_templates(id) on delete set null,
    athlete_id uuid not null,
    coach_id uuid,
    title text not null,
    resolved_steps_json jsonb not null,
    athlete_profile_snapshot_json jsonb,
    feasibility_result_json jsonb,
    created_at timestamptz not null default now()
);

create table if not exists workout_assignments (
    id uuid primary key default gen_random_uuid(),
    prescription_id uuid not null references workout_prescriptions(id) on delete cascade,
    athlete_id uuid not null,
    coach_id uuid,
    scheduled_date date not null,
    planned_start_time time,
    status text not null default 'assigned',
    execution_mode text not null default 'outdoor_or_indoor',
    priority text,
    notes_for_athlete text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists workout_executions (
    id uuid primary key default gen_random_uuid(),
    assignment_id uuid not null references workout_assignments(id) on delete cascade,
    activity_id uuid,
    fit_file_url text,
    source text not null default 'fit_upload', -- outdoor_headunit | indoor_app | fit_upload
    started_at timestamptz,
    completed_at timestamptz,
    parsed_summary_json jsonb,
    created_at timestamptz not null default now()
);

create table if not exists workout_compliance_results (
    id uuid primary key default gen_random_uuid(),
    assignment_id uuid not null references workout_assignments(id) on delete cascade,
    execution_id uuid references workout_executions(id) on delete cascade,
    compliance_score numeric,
    confidence_score numeric,
    classification text,
    validity text,
    summary_json jsonb,
    discrepancies_json jsonb not null default '[]'::jsonb,
    matched_steps_json jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_workout_assignments_athlete_date
    on workout_assignments(athlete_id, scheduled_date);

create index if not exists idx_workout_compliance_assignment
    on workout_compliance_results(assignment_id);
