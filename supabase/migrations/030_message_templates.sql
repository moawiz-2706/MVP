BEGIN;

CREATE TABLE IF NOT EXISTS message_templates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id) ON DELETE CASCADE,
  event_type varchar(80) NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  subject_template text NOT NULL,
  body_template text NOT NULL,
  updated_by_user_id uuid REFERENCES app_users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_message_templates_operator_event UNIQUE (operator_id, event_type),
  CONSTRAINT message_template_event_type_valid CHECK (event_type IN (
    'booking_confirmation','booking_cancellation','weather_cancellation',
    'booking_reschedule','booking_reminder_day_before','booking_reminder_same_day',
    'staff_assignment','staff_unassignment','staff_reminder_day_before','staff_reminder_same_day'
  )),
  CONSTRAINT message_template_subject_length CHECK (char_length(subject_template) BETWEEN 1 AND 240),
  CONSTRAINT message_template_body_length CHECK (char_length(body_template) BETWEEN 1 AND 20000)
);

CREATE INDEX IF NOT EXISTS ix_message_templates_operator ON message_templates(operator_id);

DROP TRIGGER IF EXISTS trg_message_templates_updated_at ON message_templates;
CREATE TRIGGER trg_message_templates_updated_at
BEFORE UPDATE ON message_templates
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE outbox_jobs DROP CONSTRAINT IF EXISTS outbox_jobs_job_type_check;
ALTER TABLE outbox_jobs DROP CONSTRAINT IF EXISTS job_type_valid;
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
    'ghl_sync_staff_user',
    'ghl_booking_cancellation_email',
    'ghl_booking_weather_email',
    'ghl_booking_reschedule_email',
    'stripe_create_refund',
    'stripe_create_transfer_reversal',
    'stripe_reconcile_payment_intent',
    'ghl_sync_calendar',
    'ghl_delete_calendar',
    'ghl_sync_appointment',
    'ghl_cancel_appointment'
  ));

INSERT INTO passport_schema_version(version)
VALUES ('030_message_templates')
ON CONFLICT (version) DO NOTHING;

COMMIT;
