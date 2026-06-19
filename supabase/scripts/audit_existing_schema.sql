-- =============================================================================
-- AUDIT — Esegui nel SQL Editor di Supabase (progetto esistente)
-- https://supabase.com/dashboard/project/xdqvjqqwywuguuhsehxm/sql
-- =============================================================================
-- Copia l'output e condividilo per il confronto con Backend V5.
-- =============================================================================

-- 1) Tutte le tabelle public (nome, RLS, righe stimate)
select
  c.relname as table_name,
  c.reltuples::bigint as estimated_rows,
  c.relrowsecurity as rls_enabled
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relkind = 'r'
order by c.relname;

-- 2) Colonne per ogni tabella public
select
  table_name,
  column_name,
  data_type,
  udt_name,
  is_nullable,
  column_default
from information_schema.columns
where table_schema = 'public'
order by table_name, ordinal_position;

-- 3) Foreign keys
select
  tc.table_name,
  kcu.column_name,
  ccu.table_name as foreign_table,
  ccu.column_name as foreign_column
from information_schema.table_constraints tc
join information_schema.key_column_usage kcu
  on tc.constraint_name = kcu.constraint_name
join information_schema.constraint_column_usage ccu
  on ccu.constraint_name = tc.constraint_name
where tc.constraint_type = 'FOREIGN KEY'
  and tc.table_schema = 'public'
order by tc.table_name;

-- 4) Policy RLS attive
select
  schemaname,
  tablename,
  policyname,
  permissive,
  roles,
  cmd,
  qual,
  with_check
from pg_policies
where schemaname = 'public'
order by tablename, policyname;

-- 5) Funzioni custom in public (trigger, helper JWT, ecc.)
select
  p.proname as function_name,
  pg_get_function_identity_arguments(p.oid) as args
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public'
order by p.proname;

-- 6) Trigger su auth.users o tabelle public
select
  event_object_schema,
  event_object_table,
  trigger_name,
  action_timing,
  event_manipulation
from information_schema.triggers
where event_object_schema in ('public', 'auth')
order by event_object_table, trigger_name;

-- 7) Enum types
select
  t.typname as enum_name,
  e.enumlabel as enum_value
from pg_type t
join pg_enum e on t.oid = e.enumtypid
join pg_namespace n on n.oid = t.typnamespace
where n.nspname = 'public'
order by t.typname, e.enumsortorder;

-- 8) Indici JSONB (utili per activities / twin_states)
select
  tablename,
  indexname,
  indexdef
from pg_indexes
where schemaname = 'public'
  and (indexdef ilike '%jsonb%' or indexdef ilike '%gin%')
order by tablename;

-- 9) Storage buckets (se usati per FIT)
select id, name, public, file_size_limit, allowed_mime_types
from storage.buckets
order by name;

-- 10) Checklist rapida — tabelle attese da Backend V5
select unnest(array[
  'profiles',
  'coaches',
  'teams',
  'athletes',
  'twin_states',
  'activities',
  'validation_events',
  'workout_templates',
  'workout_assignments',
  'processing_jobs'
]) as expected_table,
exists (
  select 1
  from information_schema.tables t
  where t.table_schema = 'public'
    and t.table_name = expected_table
) as exists_in_db;
