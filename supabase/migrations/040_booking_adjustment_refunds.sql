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
