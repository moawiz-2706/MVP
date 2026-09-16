-- 008: additive production hardening.
-- This migration preserves existing public status values and adds separate
-- reconciliation/projection state so existing clients remain compatible.

ALTER TABLE ghl_installations
  ADD COLUMN IF NOT EXISTS authz_version integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS generation integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS lifecycle_status text NOT NULL DEFAULT 'active',
  ADD COLUMN IF NOT EXISTS granted_scopes jsonb,
  ADD COLUMN IF NOT EXISTS last_verified_at timestamptz;

ALTER TABLE booking_orders
  ADD COLUMN IF NOT EXISTS checkout_key varchar(160),
  ADD COLUMN IF NOT EXISTS checkout_request_hash varchar(128);

CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_orders_operator_checkout_key
  ON booking_orders(operator_id, checkout_key) WHERE checkout_key IS NOT NULL;

ALTER TABLE booking_waivers
  ADD COLUMN IF NOT EXISTS public_expires_at timestamptz;

UPDATE booking_waivers
SET public_expires_at = COALESCE(public_expires_at, created_at + interval '30 days')
WHERE public_expires_at IS NULL AND status = 'pending';

ALTER TABLE payments
  ADD COLUMN IF NOT EXISTS reconciliation_status varchar(30),
  ADD COLUMN IF NOT EXISTS observed_amount_minor bigint,
  ADD COLUMN IF NOT EXISTS observed_amount_received_minor bigint,
  ADD COLUMN IF NOT EXISTS observed_currency varchar(3),
  ADD COLUMN IF NOT EXISTS stripe_livemode boolean,
  ADD COLUMN IF NOT EXISTS stripe_account_id text,
  ADD COLUMN IF NOT EXISTS provider_unknown_at timestamptz;

ALTER TABLE stripe_webhook_events
  ADD COLUMN IF NOT EXISTS payload jsonb,
  ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 0;

ALTER TABLE outbox_jobs DROP CONSTRAINT IF EXISTS outbox_jobs_status_check;
ALTER TABLE outbox_jobs DROP CONSTRAINT IF EXISTS outbox_jobs_status_valid;
ALTER TABLE outbox_jobs
  ADD CONSTRAINT outbox_jobs_status_check CHECK (status IN ('pending','processing','completed','failed','dead'));

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
    'ghl_sync_appointment',
    'ghl_cancel_appointment'
  ));

ALTER TABLE outbox_jobs
  ADD COLUMN IF NOT EXISTS lease_owner varchar(100),
  ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz,
  ADD COLUMN IF NOT EXISTS fencing_token integer NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS ix_outbox_jobs_lease ON outbox_jobs(status, lease_expires_at);

CREATE TABLE IF NOT EXISTS payment_intent_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  payment_id uuid NOT NULL UNIQUE REFERENCES payments(id),
  checkout_key varchar(160) NOT NULL,
  request_hash varchar(128) NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  amount_minor bigint NOT NULL CHECK (amount_minor >= 0),
  currency varchar(3) NOT NULL,
  request_payload jsonb NOT NULL,
  status varchar(30) NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','processing','succeeded','provider_unknown','failed','quarantined')),
  stripe_payment_intent_id text UNIQUE,
  last_error text,
  provider_unknown_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_payment_intent_requests_checkout UNIQUE(operator_id, checkout_key)
);

CREATE TABLE IF NOT EXISTS booking_financial_allocations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  booking_id uuid NOT NULL UNIQUE REFERENCES bookings(id),
  payment_id uuid NOT NULL REFERENCES payments(id),
  subtotal_minor bigint NOT NULL CHECK (subtotal_minor >= 0),
  customer_refund_minor bigint NOT NULL CHECK (customer_refund_minor >= 0),
  operator_recovery_minor bigint NOT NULL CHECK (operator_recovery_minor >= 0),
  allocation_version integer NOT NULL DEFAULT 1,
  source_snapshot jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payment_refund_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  payment_id uuid NOT NULL REFERENCES payments(id),
  scope_key text NOT NULL,
  amount_minor bigint NOT NULL CHECK (amount_minor >= 0),
  currency varchar(3) NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  stripe_refund_id text UNIQUE,
  status varchar(30) NOT NULL DEFAULT 'requested'
    CHECK (status IN ('requested','pending','succeeded','failed','canceled','requires_action')),
  failure_reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_payment_refund_attempt_scope UNIQUE(payment_id, scope_key)
);

CREATE TABLE IF NOT EXISTS transfer_reversal_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  transfer_id uuid NOT NULL REFERENCES stripe_transfers(id),
  scope_key text NOT NULL,
  amount_minor bigint NOT NULL CHECK (amount_minor >= 0),
  idempotency_key text NOT NULL UNIQUE,
  stripe_reversal_id text UNIQUE,
  status varchar(30) NOT NULL DEFAULT 'requested'
    CHECK (status IN ('requested','pending','succeeded','failed','blocked','not_transferred')),
  failure_reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_transfer_reversal_attempt_scope UNIQUE(transfer_id, scope_key)
);

CREATE TABLE IF NOT EXISTS public_access_credentials (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  order_id uuid REFERENCES booking_orders(id),
  booking_id uuid REFERENCES bookings(id),
  token_digest varchar(128) NOT NULL UNIQUE,
  purpose varchar(30) NOT NULL
    CHECK (purpose IN ('order_status','waiver_sign','waiver_view','waiver_view_sensitive')),
  issued_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  last_used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT public_access_resource_check CHECK (order_id IS NOT NULL OR booking_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS ghl_oauth_states (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  state_digest varchar(128) NOT NULL UNIQUE,
  flow varchar(30) NOT NULL DEFAULT 'app_start',
  expected_location_id text,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ghl_webhook_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider_event_id text NOT NULL UNIQUE,
  event_type text NOT NULL,
  location_id text,
  payload_hash varchar(128) NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'received',
  payload jsonb,
  processed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ghl_calendar_mappings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  calendar_id uuid NOT NULL REFERENCES calendars(id),
  ghl_calendar_id text UNIQUE,
  desired_revision integer NOT NULL DEFAULT 1,
  applied_revision integer NOT NULL DEFAULT 0,
  status varchar(30) NOT NULL DEFAULT 'pending',
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_ghl_calendar_mapping UNIQUE(operator_id, calendar_id)
);

CREATE TABLE IF NOT EXISTS ghl_appointment_mappings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  booking_id uuid NOT NULL REFERENCES bookings(id),
  ghl_calendar_mapping_id uuid NOT NULL REFERENCES ghl_calendar_mappings(id),
  ghl_event_id text UNIQUE,
  desired_revision integer NOT NULL DEFAULT 1,
  applied_revision integer NOT NULL DEFAULT 0,
  status varchar(30) NOT NULL DEFAULT 'pending',
  payload_hash varchar(128),
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_ghl_appointment_mapping UNIQUE(operator_id, booking_id)
);

CREATE TABLE IF NOT EXISTS public_rate_limit_buckets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bucket_key text NOT NULL UNIQUE,
  window_start timestamptz NOT NULL,
  request_count integer NOT NULL DEFAULT 0 CHECK (request_count >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_public_access_credentials_expiry
  ON public_access_credentials(expires_at, revoked_at);
CREATE INDEX IF NOT EXISTS ix_ghl_webhook_events_location
  ON ghl_webhook_events(location_id, created_at);
CREATE INDEX IF NOT EXISTS ix_ghl_appointment_mappings_status
  ON ghl_appointment_mappings(status, updated_at);

CREATE OR REPLACE FUNCTION enforce_payment_child_tenant()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM payments p WHERE p.id = NEW.payment_id AND p.operator_id = NEW.operator_id
  ) THEN
    RAISE EXCEPTION 'payment child row must belong to the same operator';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_booking_financial_allocation_tenant ON booking_financial_allocations;
CREATE TRIGGER trg_booking_financial_allocation_tenant
BEFORE INSERT OR UPDATE ON booking_financial_allocations
FOR EACH ROW EXECUTE FUNCTION enforce_payment_child_tenant();

DROP TRIGGER IF EXISTS trg_payment_refund_attempt_tenant ON payment_refund_attempts;
CREATE TRIGGER trg_payment_refund_attempt_tenant
BEFORE INSERT OR UPDATE ON payment_refund_attempts
FOR EACH ROW EXECUTE FUNCTION enforce_payment_child_tenant();

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'payment_intent_requests','booking_financial_allocations','payment_refund_attempts',
    'transfer_reversal_attempts','public_access_credentials','ghl_oauth_states',
    'ghl_calendar_mappings','ghl_appointment_mappings','public_rate_limit_buckets'
  ] LOOP
    EXECUTE format(
      'DROP TRIGGER IF EXISTS trg_%I_updated_at ON %I', table_name, table_name
    );
    EXECUTE format(
      'CREATE TRIGGER trg_%I_updated_at BEFORE UPDATE ON %I '
      'FOR EACH ROW EXECUTE FUNCTION set_updated_at()', table_name, table_name
    );
  END LOOP;
END;
$$;

UPDATE booking_orders SET checkout_key = 'legacy:' || id::text
WHERE checkout_key IS NULL;

COMMIT;

-- Required application settings for the new paths are documented in
-- backend/.env.example. Existing installations continue using the old contact
-- and email scopes until they explicitly reauthorize calendar projection.
