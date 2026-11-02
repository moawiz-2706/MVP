-- Enable Row Level Security on every Passport table in the public schema.
--
-- Why: Supabase exposes the public schema through its Data API (PostgREST).
-- With RLS disabled, anyone holding the project's anon key could read and
-- write customers, waivers, payments, encrypted HighLevel tokens and sessions
-- directly, bypassing every Passport permission check.
--
-- Effect on Passport: none. The backend connects as the table owner
-- (`postgres`, BYPASSRLS), and the frontend never talks to Supabase directly.
-- No policies are created, so the anon and authenticated roles get no rows.
--
-- Safe to re-run. Apply after 040_booking_adjustment_refunds.sql.
--
-- Rollback (restores the previous exposure; only if something unexpected
-- depended on the Data API):
--   DO $$ DECLARE t record; BEGIN
--     FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
--       EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY', t.tablename);
--     END LOOP;
--   END $$;
--   DELETE FROM public.passport_schema_version WHERE version = '041_enable_row_level_security';

BEGIN;

DO $$
DECLARE
  t record;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
  END LOOP;
END $$;

INSERT INTO public.passport_schema_version(version)
VALUES ('041_enable_row_level_security')
ON CONFLICT (version) DO NOTHING;

COMMIT;
