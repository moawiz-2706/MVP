-- Allow the reminder and staff-notification job types in the outbox.
-- 001 declared the job_type CHECK inline, so Postgres named it
-- outbox_jobs_job_type_check; replace it with the full list.
ALTER TABLE outbox_jobs DROP CONSTRAINT IF EXISTS outbox_jobs_job_type_check;

ALTER TABLE outbox_jobs
  ADD CONSTRAINT outbox_jobs_job_type_check CHECK (job_type IN (
    'stripe_create_transfer',
    'ghl_upsert_contact',
    'ghl_send_confirmation_email',
    'ghl_booking_reminder',
    'ghl_upsert_staff_contact',
    'ghl_staff_assigned_email',
    'ghl_staff_reminder'
  ));
