-- HighLevel "Passport Bookings" custom object records (custom_objects.passport_bookings).
-- Additive and safe to re-run. Apply BEFORE setting GHL_BOOKING_RECORD_SYNC_ENABLED=true;
-- with the flag off (the default) nothing reads or writes this table.
--
-- 1. ghl_booking_records: the HighLevel record id for each Passport order, and
--    whether it is linked to the customer's contact ("Customer Booking").
-- 2. Outbox job type 'ghl_sync_booking_record'.
--
-- Rollback (set GHL_BOOKING_RECORD_SYNC_ENABLED=false and deploy first):
--   DROP TABLE IF EXISTS public.ghl_booking_records;
--   (re-apply the job type list from 045_marketplace_workflow_trigger.sql)
--   DELETE FROM public.passport_schema_version WHERE version = '048_ghl_booking_records';

BEGIN;

CREATE TABLE IF NOT EXISTS public.ghl_booking_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES public.operators(id),
  booking_order_id uuid NOT NULL REFERENCES public.booking_orders(id),
  ghl_record_id text,
  ghl_contact_id text,
  contact_linked boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'pending',
  last_error text,
  synced_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ghl_booking_records_status_valid CHECK (status IN ('pending', 'synced', 'failed')),
  CONSTRAINT uq_ghl_booking_records_order UNIQUE (booking_order_id)
);
CREATE INDEX IF NOT EXISTS ix_ghl_booking_records_operator_status
  ON public.ghl_booking_records (operator_id, status);

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
    'ghl_cancel_appointment',
    'ghl_workflow_trigger',
    'ghl_sync_booking_record'
  ));

ALTER TABLE public.ghl_booking_records ENABLE ROW LEVEL SECURITY;

INSERT INTO public.passport_schema_version(version)
VALUES ('048_ghl_booking_records')
ON CONFLICT (version) DO NOTHING;

COMMIT;
