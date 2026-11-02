-- Passport staff synchronization and availability schema patch
--
-- Run this file in the Supabase SQL Editor using a database role that can alter
-- tables and create indexes/triggers. It assumes the base Passport schema already
-- exists (including operators, calendars, staff, outbox_jobs, and set_updated_at()).
-- The statements are intentionally idempotent so the bundle can be safely rerun.

BEGIN;

-- 012: Link local staff records to existing GHL users.
ALTER TABLE public.staff
  ADD COLUMN IF NOT EXISTS ghl_user_id text,
  ADD COLUMN IF NOT EXISTS ghl_user_sync_status text NOT NULL DEFAULT 'not_requested',
  ADD COLUMN IF NOT EXISTS ghl_user_last_error text,
  ADD COLUMN IF NOT EXISTS ghl_permissions_verified_at timestamptz;

CREATE UNIQUE INDEX IF NOT EXISTS uq_staff_operator_ghl_user
  ON public.staff(operator_id, ghl_user_id)
  WHERE ghl_user_id IS NOT NULL;

ALTER TABLE public.outbox_jobs DROP CONSTRAINT IF EXISTS job_type_valid;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.outbox_jobs'::regclass
      AND conname = 'job_type_valid'
  ) THEN
    ALTER TABLE public.outbox_jobs
      ADD CONSTRAINT job_type_valid CHECK (
        job_type IN (
          'stripe_create_transfer','ghl_upsert_contact','ghl_send_confirmation_email',
          'ghl_booking_reminder','ghl_upsert_staff_contact','ghl_sync_staff_user',
          'ghl_staff_assigned_email','ghl_staff_reminder','ghl_staff_unassigned_email',
          'stripe_create_refund','stripe_create_transfer_reversal',
          'stripe_reconcile_payment_intent','ghl_sync_calendar','ghl_delete_calendar',
          'ghl_sync_appointment','ghl_cancel_appointment'
        )
      );
  END IF;
END $$;

-- 013: Passport-owned custom role used for booking eligibility.
ALTER TABLE public.staff
  ADD COLUMN IF NOT EXISTS custom_role text;

CREATE INDEX IF NOT EXISTS ix_staff_operator_custom_role
  ON public.staff(operator_id, custom_role)
  WHERE deleted_at IS NULL;

-- 014: Cached GHL schedule metadata.
ALTER TABLE public.staff
  ADD COLUMN IF NOT EXISTS availability_time_zone text,
  ADD COLUMN IF NOT EXISTS availability_sync_status text NOT NULL DEFAULT 'not_requested',
  ADD COLUMN IF NOT EXISTS availability_last_error text,
  ADD COLUMN IF NOT EXISTS availability_last_synced_at timestamptz;

-- 015: Calendar staff pools and concrete rolling availability windows.
ALTER TABLE public.calendars
  ADD COLUMN IF NOT EXISTS required_staff_roles jsonb NOT NULL DEFAULT '["Captain"]'::jsonb;

CREATE TABLE IF NOT EXISTS public.staff_availability_windows (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  staff_id uuid NOT NULL REFERENCES public.staff(id) ON DELETE CASCADE,
  start_at timestamptz NOT NULL,
  end_at timestamptz NOT NULL,
  source_schedule_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.staff_availability_windows'::regclass
      AND conname = 'ck_staff_availability_windows_time_order'
  ) THEN
    ALTER TABLE public.staff_availability_windows
      ADD CONSTRAINT ck_staff_availability_windows_time_order CHECK (start_at < end_at);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.staff_availability_windows'::regclass
      AND conname = 'uq_staff_availability_windows_staff_interval'
  ) THEN
    ALTER TABLE public.staff_availability_windows
      ADD CONSTRAINT uq_staff_availability_windows_staff_interval
      UNIQUE (staff_id, start_at, end_at);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_staff_availability_windows_staff_interval
  ON public.staff_availability_windows(staff_id, start_at, end_at);

DROP TRIGGER IF EXISTS trg_staff_availability_windows_updated_at
  ON public.staff_availability_windows;
CREATE TRIGGER trg_staff_availability_windows_updated_at
  BEFORE UPDATE ON public.staff_availability_windows
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- 016: Repair blank operator time zones so the booking link cannot pass an
-- empty value to browser Intl.DateTimeFormat.
UPDATE public.operators
SET time_zone = 'UTC'
WHERE time_zone IS NULL OR btrim(time_zone) = '';

ALTER TABLE public.operators
  ALTER COLUMN time_zone SET DEFAULT 'UTC';

ALTER TABLE public.operators
  DROP CONSTRAINT IF EXISTS ck_operators_time_zone_nonblank;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.operators'::regclass
      AND conname = 'ck_operators_time_zone_nonblank'
  ) THEN
    ALTER TABLE public.operators
      ADD CONSTRAINT ck_operators_time_zone_nonblank CHECK (btrim(time_zone) <> '');
  END IF;
END $$;

COMMIT;

-- Verification queries. Run separately after the transaction if desired:
-- SELECT column_name FROM information_schema.columns
-- WHERE table_schema = 'public' AND table_name = 'staff'
-- ORDER BY ordinal_position;
-- SELECT column_name FROM information_schema.columns
-- WHERE table_schema = 'public' AND table_name = 'calendars'
--   AND column_name = 'required_staff_roles';
-- SELECT to_regclass('public.staff_availability_windows');
-- SELECT count(*) AS blank_operator_timezones
-- FROM public.operators
-- WHERE time_zone IS NULL OR btrim(time_zone) = '';
-- SELECT conname FROM pg_constraint
-- WHERE conrelid = 'public.outbox_jobs'::regclass
--   AND conname = 'job_type_valid';
