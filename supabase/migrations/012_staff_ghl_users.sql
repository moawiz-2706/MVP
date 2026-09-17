-- Existing GHL account users are imported and linked by GHL user ID.
-- Passport does not create remote users or store staff passwords.
ALTER TABLE staff
  ADD COLUMN IF NOT EXISTS ghl_user_id text,
  ADD COLUMN IF NOT EXISTS ghl_user_sync_status text NOT NULL DEFAULT 'not_requested',
  ADD COLUMN IF NOT EXISTS ghl_user_last_error text,
  ADD COLUMN IF NOT EXISTS ghl_permissions_verified_at timestamptz;

CREATE UNIQUE INDEX IF NOT EXISTS uq_staff_operator_ghl_user
  ON staff(operator_id, ghl_user_id)
  WHERE ghl_user_id IS NOT NULL;

ALTER TABLE outbox_jobs DROP CONSTRAINT IF EXISTS job_type_valid;
ALTER TABLE outbox_jobs ADD CONSTRAINT job_type_valid CHECK (
  job_type IN (
    'stripe_create_transfer','ghl_upsert_contact','ghl_send_confirmation_email',
    'ghl_booking_reminder','ghl_upsert_staff_contact','ghl_sync_staff_user',
    'ghl_staff_assigned_email','ghl_staff_reminder','ghl_staff_unassigned_email',
    'stripe_create_refund','stripe_create_transfer_reversal','stripe_reconcile_payment_intent',
    'ghl_sync_calendar','ghl_delete_calendar','ghl_sync_appointment','ghl_cancel_appointment'
  )
);
