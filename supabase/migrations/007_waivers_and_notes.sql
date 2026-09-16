-- 007: booking waivers, internal booking notes, and the staff "removed from a
-- slot" email job.

ALTER TABLE operator_settings
  ADD COLUMN waiver_title text,
  ADD COLUMN waiver_website text,
  ADD COLUMN waiver_text text,
  ADD COLUMN waiver_opt_in_label text;

-- One waiver per booking, signed once by the lead participant or guardian for
-- everyone in the booking. Signing snapshots the exact text that was agreed to.
CREATE TABLE booking_waivers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  booking_id uuid NOT NULL REFERENCES bookings(id),
  token text NOT NULL,
  status text NOT NULL DEFAULT 'pending',
  signed_at timestamptz,
  signer_ip text,
  signer_user_agent text,
  waiver_title text,
  waiver_text text,
  activity_name text,
  activity_start_at timestamptz,
  details jsonb,
  signature_png text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_booking_waivers_booking_id UNIQUE (booking_id),
  CONSTRAINT uq_booking_waivers_token UNIQUE (token),
  CONSTRAINT ck_booking_waivers_status_valid CHECK (status IN ('pending', 'signed')),
  CONSTRAINT ck_booking_waivers_signed_complete CHECK (
    status <> 'signed' OR (signed_at IS NOT NULL AND waiver_text IS NOT NULL
      AND details IS NOT NULL AND signature_png IS NOT NULL)
  )
);

CREATE INDEX ix_booking_waivers_operator_id ON booking_waivers(operator_id);

-- Internal notes on a booking, visible only to the operator's team.
CREATE TABLE booking_notes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  booking_id uuid NOT NULL REFERENCES bookings(id),
  author_user_id uuid REFERENCES app_users(id),
  author_name text,
  body text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_booking_notes_body_length CHECK (char_length(body) BETWEEN 1 AND 5000)
);

CREATE INDEX ix_booking_notes_booking_created ON booking_notes(booking_id, created_at);

-- Both tables carry operator_id, which must match the booking's operator.
CREATE OR REPLACE FUNCTION enforce_booking_child_tenant()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM bookings b WHERE b.id = NEW.booking_id AND b.operator_id = NEW.operator_id
  ) THEN
    RAISE EXCEPTION 'booking and % row must belong to the same operator', TG_TABLE_NAME;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_booking_waiver_tenant
BEFORE INSERT OR UPDATE ON booking_waivers
FOR EACH ROW EXECUTE FUNCTION enforce_booking_child_tenant();

CREATE TRIGGER trg_booking_note_tenant
BEFORE INSERT OR UPDATE ON booking_notes
FOR EACH ROW EXECUTE FUNCTION enforce_booking_child_tenant();

-- A signed waiver is a legal record: it can never be changed or deleted.
CREATE OR REPLACE FUNCTION prevent_signed_waiver_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status = 'signed' THEN
    RAISE EXCEPTION 'signed waivers are locked';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_booking_waiver_lock
BEFORE UPDATE OR DELETE ON booking_waivers
FOR EACH ROW EXECUTE FUNCTION prevent_signed_waiver_change();

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['booking_waivers','booking_notes'] LOOP
    EXECUTE format(
      'CREATE TRIGGER trg_%I_updated_at BEFORE UPDATE ON %I '
      'FOR EACH ROW EXECUTE FUNCTION set_updated_at()', table_name, table_name
    );
  END LOOP;
END;
$$;

-- Allow the staff "removed from a slot" email job (full list, replaces 006's).
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
    'ghl_staff_unassigned_email'
  ));
