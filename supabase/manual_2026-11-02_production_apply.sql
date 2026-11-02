-- Production apply script — 2026-11-02 (owner-authorized)
-- Run once in Supabase → SQL Editor. Safe to re-run: every step is idempotent.
--
-- Part A applies the pending migrations in order: 038, 040, 041, 042.
--   They change no rows: they add indexes, widen a CHECK constraint, turn on
--   row level security, and add two nullable PWA session columns. Rollback
--   SQL is in each migration file. 042 is required by the next code deploy.
-- Part B voids the two test card payments whose success webhooks failed in
--   September. Nothing is deleted: the booking, order and payment rows stay
--   for audit with cancelled/failed status, and their HighLevel appointment is
--   queued for cancellation.

-- ===== Part A.1: 038_pwa_workspace_performance.sql =====
-- PWA workspace read-model performance indexes.
-- This migration is additive and safe to run after 037_pwa_auth_handoffs.sql.

BEGIN;

-- Serves the mobile dashboard's upcoming, pending-payment, and assignment-gap counts.
CREATE INDEX IF NOT EXISTS ix_bookings_operator_status_start
  ON public.bookings (operator_id, status, start_at);

-- Serves pending waiver counts without scanning all waiver records for an operator.
CREATE INDEX IF NOT EXISTS ix_booking_waivers_operator_status_booking
  ON public.booking_waivers (operator_id, status, booking_id);

-- Covers the correlated dashboard test for a fully covering staff assignment.
CREATE INDEX IF NOT EXISTS ix_staff_assignments_operator_calendar_interval
  ON public.staff_assignments (operator_id, calendar_id, start_at, end_at);

INSERT INTO public.passport_schema_version(version)
VALUES ('038_pwa_workspace_performance')
ON CONFLICT (version) DO NOTHING;

COMMIT;

-- ===== Part A.2: 040_booking_adjustment_refunds.sql =====
BEGIN;

ALTER TABLE public.outbox_jobs DROP CONSTRAINT IF EXISTS outbox_jobs_job_type_check;
ALTER TABLE public.outbox_jobs DROP CONSTRAINT IF EXISTS job_type_valid;
ALTER TABLE public.outbox_jobs
  ADD CONSTRAINT outbox_jobs_job_type_check CHECK (job_type IN (
    'stripe_create_transfer',
    'stripe_create_invoice',
    'ghl_upsert_contact',
    'ghl_send_confirmation_email',
    'ghl_booking_reminder',
    'ghl_upsert_staff_contact',
    'ghl_staff_assigned_email',
    'ghl_staff_reminder',
    'ghl_staff_unassigned_email',
    'ghl_booking_cancellation_email',
    'ghl_booking_weather_email',
    'ghl_booking_reschedule_email',
    'stripe_create_refund',
    'stripe_create_adjustment_refund',
    'stripe_create_transfer_reversal',
    'stripe_reconcile_payment_intent',
    'ghl_sync_staff_user',
    'ghl_sync_calendar',
    'ghl_delete_calendar',
    'ghl_sync_appointment',
    'ghl_cancel_appointment'
  ));

INSERT INTO public.passport_schema_version(version)
VALUES ('040_booking_adjustment_refunds')
ON CONFLICT (version) DO NOTHING;

COMMIT;

-- ===== Part A.3: 041_enable_row_level_security.sql =====
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

-- ===== Part A.4: 042_pwa_refresh_grace.sql =====
-- Staff PWA: brief grace window for the refresh nonce replaced by a rotation.
--
-- Two refreshes racing from one device (app resume plus a retried request,
-- two tabs) both present the same cookie. The first rotates the nonce; the
-- second used to be rejected and signed the staff member out. The replaced
-- digest is now kept with its rotation time and accepted for a short window,
-- without rotating again. Only SHA-256 digests are stored, as before.
--
-- Additive and safe to re-run. Apply after 041 and BEFORE deploying code
-- that expects these columns.
-- Rollback (deploy the previous code first):
--   ALTER TABLE public.pwa_sessions DROP COLUMN IF EXISTS previous_refresh_nonce_digest;
--   ALTER TABLE public.pwa_sessions DROP COLUMN IF EXISTS refresh_rotated_at;
--   DELETE FROM public.passport_schema_version WHERE version = '042_pwa_refresh_grace';

BEGIN;

ALTER TABLE public.pwa_sessions
  ADD COLUMN IF NOT EXISTS previous_refresh_nonce_digest varchar(128),
  ADD COLUMN IF NOT EXISTS refresh_rotated_at timestamptz;

INSERT INTO public.passport_schema_version(version)
VALUES ('042_pwa_refresh_grace')
ON CONFLICT (version) DO NOTHING;

COMMIT;

-- ===== Part B: void the two test payments =====
-- Payments 7151789c-… (booking on 2026-09-26) and c1bb4cc8-… (booking on
-- 2026-10-01, already cancelled). Owner confirmed both are test data.
BEGIN;

UPDATE public.bookings
SET status = 'cancelled', updated_at = now()
WHERE id = '7dd78628-9179-440e-8809-55ea56cf7db5' AND status = 'pending_payment';

INSERT INTO public.booking_events
  (operator_id, booking_id, order_id, event_type, from_status, to_status, actor_type, reason, occurred_at)
SELECT b.operator_id, b.id, b.booking_order_id, 'test_data_voided', 'pending_payment', 'cancelled',
       'system', 'Test booking voided by owner request (2026-11-02)', now()
FROM public.bookings b
WHERE b.id = '7dd78628-9179-440e-8809-55ea56cf7db5'
  AND NOT EXISTS (SELECT 1 FROM public.booking_events e
                  WHERE e.booking_id = b.id AND e.event_type = 'test_data_voided');

UPDATE public.booking_orders
SET status = 'cancelled', updated_at = now()
WHERE id IN ('49a45601-50bb-4391-9c24-8b225e55bd8d', 'f1ab35ca-042a-46f2-9811-02b0b55fb7f3')
  AND status IN ('pending_payment', 'cancelled');

UPDATE public.payments
SET status = 'failed', updated_at = now()
WHERE id IN ('7151789c-7469-4b16-8796-db787c1019fb', 'c1bb4cc8-028c-453d-a0f1-da6ca3add6e9')
  AND status = 'processing';

UPDATE public.stripe_webhook_events
SET error_message = '[voided as test data 2026-11-02] ' || coalesce(error_message, '')
WHERE id IN ('98e89a02-ded4-43f1-be7b-1f1a8887da6b', '009d21b2-a768-45ea-a8fd-48d70390e935')
  AND coalesce(error_message, '') NOT LIKE '[voided as test data%';

INSERT INTO public.outbox_jobs
  (operator_id, booking_order_id, job_type, idempotency_key, payload, status, attempt_count, next_attempt_at)
SELECT b.operator_id, b.booking_order_id, 'ghl_cancel_appointment',
       'booking:' || b.id || ':ghl_test_void_cancel',
       jsonb_build_object('booking_id', b.id::text, 'booking_order_id', b.booking_order_id::text, 'reason', 'test_data_voided'),
       'pending', 0, now()
FROM public.bookings b
WHERE b.id = '7dd78628-9179-440e-8809-55ea56cf7db5'
ON CONFLICT DO NOTHING;

COMMIT;

-- ===== Verify =====
-- select version from passport_schema_version order by 1;            -- includes 038, 040, 041, 042
-- select count(*) from pg_tables where schemaname='public' and not rowsecurity;   -- 0
-- select status from payments where id in ('7151789c-7469-4b16-8796-db787c1019fb','c1bb4cc8-028c-453d-a0f1-da6ca3add6e9');  -- failed, failed
