-- Allow the outbox worker to delete the matching HighLevel calendar after
-- a Passport calendar is deleted locally.
ALTER TABLE outbox_jobs DROP CONSTRAINT IF EXISTS outbox_jobs_job_type_check;

ALTER TABLE outbox_jobs
  ADD CONSTRAINT outbox_jobs_job_type_check CHECK (job_type IN (
    'stripe_create_transfer',
    'ghl_upsert_contact',
    'ghl_send_confirmation_email',
    'ghl_booking_reminder',
    'ghl_upsert_staff_contact',
    'ghl_staff_assigned_email',
    'ghl_staff_reminder',
    'ghl_staff_unassigned_email',
    'stripe_create_refund',
    'stripe_create_transfer_reversal',
    'stripe_reconcile_payment_intent',
    'ghl_sync_calendar',
    'ghl_delete_calendar',
    'ghl_sync_appointment',
    'ghl_cancel_appointment'
  ));
