BEGIN;

ALTER TABLE payments
  ADD COLUMN IF NOT EXISTS payment_method varchar(20) NOT NULL DEFAULT 'card',
  ADD COLUMN IF NOT EXISTS stripe_customer_id text,
  ADD COLUMN IF NOT EXISTS stripe_invoice_item_id text,
  ADD COLUMN IF NOT EXISTS stripe_invoice_id text,
  ADD COLUMN IF NOT EXISTS stripe_invoice_url text,
  ADD COLUMN IF NOT EXISTS invoice_status varchar(30);

UPDATE payments
SET payment_method = 'none'
WHERE status = 'succeeded'
  AND customer_total_minor = 0
  AND payment_method = 'card';

ALTER TABLE payments DROP CONSTRAINT IF EXISTS payment_method_valid;
ALTER TABLE payments
  ADD CONSTRAINT payment_method_valid CHECK (payment_method IN ('card', 'invoice', 'none'));

CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_stripe_customer_id
  ON payments(stripe_customer_id)
  WHERE stripe_customer_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_stripe_invoice_item_id
  ON payments(stripe_invoice_item_id)
  WHERE stripe_invoice_item_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_stripe_invoice_id
  ON payments(stripe_invoice_id)
  WHERE stripe_invoice_id IS NOT NULL;

ALTER TABLE outbox_jobs DROP CONSTRAINT IF EXISTS outbox_jobs_job_type_check;
ALTER TABLE outbox_jobs DROP CONSTRAINT IF EXISTS job_type_valid;
ALTER TABLE outbox_jobs
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
    'stripe_create_transfer_reversal',
    'stripe_reconcile_payment_intent',
    'ghl_sync_staff_user',
    'ghl_sync_calendar',
    'ghl_delete_calendar',
    'ghl_sync_appointment',
    'ghl_cancel_appointment'
  ));

INSERT INTO passport_schema_version(version)
VALUES ('031_team_invoice_bookings')
ON CONFLICT (version) DO NOTHING;

COMMIT;
