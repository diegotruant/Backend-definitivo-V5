-- =============================================================================
-- STEP 1 — Identità e multi-tenancy (BOZZA — da rivedere insieme)
-- =============================================================================
-- Obiettivo: collegare Supabase Auth a coach/atleti con isolamento RLS.
-- NON eseguire in produzione finché non approvato.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Tipi enum
-- ---------------------------------------------------------------------------

create type public.app_role as enum (
  'admin',           -- piattaforma (opzionale)
  'coach',
  'assistant_coach', -- opzionale fase 1
  'athlete'
);

create type public.athlete_status as enum (
  'active',
  'inactive',
  'archived'
);

-- ---------------------------------------------------------------------------
-- profiles — estensione di auth.users (pattern Supabase standard)
-- ---------------------------------------------------------------------------
-- Un record per ogni utente che fa login (coach o atleta).
-- Il ruolo primario guida la UX; i dettagli tenant stanno in coaches/athletes.

create table public.profiles (
  id            uuid primary key references auth.users (id) on delete cascade,
  role          public.app_role not null,
  display_name  text,
  email         text,  -- copia denormalizzata per comodità query
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

comment on table public.profiles is
  'Profilo applicativo collegato a auth.users. Un utente = un ruolo primario.';

-- ---------------------------------------------------------------------------
-- coaches — tenant root (1 coach = 1 pool atleti)
-- ---------------------------------------------------------------------------
-- Nel JWT backend il claim team_id punterà a coaches.id per compatibilità
-- con il modello "team" già presente in api/auth/principal.py.

create table public.coaches (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null unique references auth.users (id) on delete cascade,
  name          text not null,
  -- calibration_model jsonb  → spostato in step 3 (coach_calibration)
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

comment on table public.coaches is
  'Tenant coach. Ogni coach ha i propri atleti e non vede quelli altrui.';

create index idx_coaches_user_id on public.coaches (user_id);

-- ---------------------------------------------------------------------------
-- athletes — appartenenza a UN solo coach
-- ---------------------------------------------------------------------------

create table public.athletes (
  id                uuid primary key default gen_random_uuid(),
  coach_id          uuid not null references public.coaches (id) on delete restrict,
  user_id           uuid unique references auth.users (id) on delete set null,
  -- user_id nullable: atleta gestito solo dal coach senza login app

  display_name      text not null,
  status            public.athlete_status not null default 'active',

  -- Dati fisiologici base (input motori backend — non duplicare TwinState)
  weight_kg         numeric(5, 2),
  height_cm         numeric(5, 1),
  gender            text,  -- 'male' | 'female' | 'other' — allineare a backend
  birth_date        date,
  training_years    numeric(4, 1),
  discipline        text default 'cycling',  -- ENDURANCE, ROAD, TT, ...
  phenotype         text,  -- da snapshot o override coach

  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),

  constraint athletes_user_requires_active check (
    user_id is null or status = 'active'
  )
);

comment on table public.athletes is
  'Atleta di un coach. user_id valorizzato se ha login app (rulli).';

create index idx_athletes_coach_id on public.athletes (coach_id);
create index idx_athletes_user_id on public.athletes (user_id) where user_id is not null;
create index idx_athletes_coach_status on public.athletes (coach_id, status);

-- ---------------------------------------------------------------------------
-- Trigger updated_at
-- ---------------------------------------------------------------------------

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function public.set_updated_at();

create trigger coaches_set_updated_at
  before update on public.coaches
  for each row execute function public.set_updated_at();

create trigger athletes_set_updated_at
  before update on public.athletes
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Helper RLS — risolvono coach_id / athlete_id dal JWT
-- ---------------------------------------------------------------------------

create or replace function public.current_profile_role()
returns public.app_role
language sql
stable
security definer
set search_path = public
as $$
  select role from public.profiles where id = auth.uid();
$$;

create or replace function public.current_coach_id()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select id from public.coaches where user_id = auth.uid();
$$;

create or replace function public.current_athlete_id()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select id from public.athletes where user_id = auth.uid();
$$;

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------

alter table public.profiles enable row level security;
alter table public.coaches enable row level security;
alter table public.athletes enable row level security;

-- profiles: ognuno legge/aggiorna il proprio; admin legge tutto
create policy profiles_select_own on public.profiles
  for select using (id = auth.uid() or public.current_profile_role() = 'admin');

create policy profiles_update_own on public.profiles
  for update using (id = auth.uid());

-- coaches: il coach vede solo se stesso
create policy coaches_select_own on public.coaches
  for select using (user_id = auth.uid() or public.current_profile_role() = 'admin');

create policy coaches_update_own on public.coaches
  for update using (user_id = auth.uid());

-- athletes: coach vede i propri; atleta vede se stesso
create policy athletes_coach_all on public.athletes
  for all using (
    coach_id = public.current_coach_id()
    or public.current_profile_role() = 'admin'
  );

create policy athletes_self_select on public.athletes
  for select using (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- Auto-provisioning profilo al signup (opzionale — da confermare)
-- ---------------------------------------------------------------------------
-- Supabase Auth Hook o trigger: crea profiles + coaches/athletes in base al
-- metadata passato al signup (role, coach_id per invito atleta).

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_role public.app_role;
  v_coach_id uuid;
begin
  v_role := coalesce(
    (new.raw_user_meta_data->>'role')::public.app_role,
    'athlete'
  );

  insert into public.profiles (id, role, display_name, email)
  values (
    new.id,
    v_role,
    coalesce(new.raw_user_meta_data->>'display_name', new.email),
    new.email
  );

  if v_role = 'coach' then
    insert into public.coaches (user_id, name)
    values (
      new.id,
      coalesce(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1))
    );
  elsif v_role = 'athlete' then
    v_coach_id := (new.raw_user_meta_data->>'coach_id')::uuid;
    if v_coach_id is not null then
      insert into public.athletes (coach_id, user_id, display_name)
      values (
        v_coach_id,
        new.id,
        coalesce(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1))
      );
    end if;
    -- Se coach_id manca: il coach creerà l'atleta manualmente e collegherà user_id
  end if;

  return new;
end;
$$;

-- ATTENZIONE: decommentare solo dopo approvazione flusso signup
-- create trigger on_auth_user_created
--   after insert on auth.users
--   for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- JWT custom claims (da configurare in Supabase Dashboard → Auth → Hooks)
-- ---------------------------------------------------------------------------
-- Esempio payload da Custom Access Token Hook:
--
-- Coach:
-- {
--   "role": "coach",
--   "roles": ["coach"],
--   "team_id": "<coaches.id>",      ← backend legge team_id
--   "athlete_ids": ["uuid1", "uuid2"]
-- }
--
-- Atleta:
-- {
--   "role": "athlete",
--   "roles": ["athlete"],
--   "athlete_id": "<athletes.id>",
--   "team_id": "<coaches.id>"
-- }
