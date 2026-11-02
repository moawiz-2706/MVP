-- Phases 3-8 foundations. Additive and safe to re-run. Apply after 042 and
-- BEFORE deploying code that expects these columns (readiness marker 043).
--
-- 1. Booking attribution: who created a booking and through which path.
--    This is separate from staff_assignments (who operates the trip).
-- 2. Per-participant check-in with an audit of who checked them in.
-- 3. Outbox job type to cancel the Stripe PaymentIntent of an abandoned
--    card checkout once its hold has expired.
--
-- Rollback (deploy the previous code first):
--   ALTER TABLE public.booking_orders DROP COLUMN IF EXISTS created_by_user_id,
--     DROP COLUMN IF EXISTS created_by_staff_id, DROP COLUMN IF EXISTS booking_source;
--   ALTER TABLE public.booking_participants DROP COLUMN IF EXISTS checked_in_at,
--     DROP COLUMN IF EXISTS checked_in_by_user_id;
--   (re-apply the job type list from 040_booking_adjustment_refunds.sql)
--   DELETE FROM public.passport_schema_version WHERE version = '043_attribution_checkin_intent_cancel';

BEGIN;

ALTER TABLE public.booking_orders
  ADD COLUMN IF NOT EXISTS created_by_user_id uuid REFERENCES public.app_users(id),
  ADD COLUMN IF NOT EXISTS created_by_staff_id uuid REFERENCES public.staff(id),
  ADD COLUMN IF NOT EXISTS booking_source text;

ALTER TABLE public.booking_orders DROP CONSTRAINT IF EXISTS booking_orders_booking_source_check;
ALTER TABLE public.booking_orders
  ADD CONSTRAINT booking_orders_booking_source_check
  CHECK (booking_source IS NULL OR booking_source IN ('public', 'staff_link', 'pwa', 'desktop'));

CREATE INDEX IF NOT EXISTS ix_booking_orders_operator_created_by_user
  ON public.booking_orders (operator_id, created_by_user_id) WHERE created_by_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_booking_orders_operator_created_by_staff
  ON public.booking_orders (operator_id, created_by_staff_id) WHERE created_by_staff_id IS NOT NULL;

ALTER TABLE public.booking_participants
  ADD COLUMN IF NOT EXISTS checked_in_at timestamptz,
  ADD COLUMN IF NOT EXISTS checked_in_by_user_id uuid REFERENCES public.app_users(id);

ALTER TABLE public.outbox_jobs DROP CONSTRAINT IF EXISTS outbox_jobs_job_type_check;
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
    'stripe_cancel_payment_intent',
    'ghl_sync_staff_user',
    'ghl_sync_calendar',
    'ghl_delete_calendar',
    'ghl_sync_appointment',
    'ghl_cancel_appointment'
  ));

-- New tables/columns inherit nothing; keep RLS on (041) for any table added later.
ALTER TABLE public.booking_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.booking_participants ENABLE ROW LEVEL SECURITY;

INSERT INTO public.passport_schema_version(version)
VALUES ('043_attribution_checkin_intent_cancel')
ON CONFLICT (version) DO NOTHING;

COMMIT;
