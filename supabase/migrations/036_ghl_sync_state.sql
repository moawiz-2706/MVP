BEGIN;

-- 036: durable audit state for synchronous GHL projection. These tables are
-- not a queue; they record the bounded synchronous attempts and the operator's
-- manual recovery state.
CREATE TABLE IF NOT EXISTS public.ghl_sync_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  booking_order_id uuid REFERENCES booking_orders(id),
  trigger_type varchar(40) NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'running',
  max_attempts integer NOT NULL DEFAULT 3,
  attempt_count integer NOT NULL DEFAULT 0,
  last_error_code varchar(80),
  last_error text,
  last_http_status integer,
  started_at timestamptz,
  completed_at timestamptz,
  resolved_at timestamptz,
  requested_by_user_id uuid REFERENCES app_users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ghl_sync_runs_trigger_type_valid CHECK (trigger_type IN (
    'booking_created','payment_confirmed','waiver_updated',
    'booking_updated','cancelled','manual_resync'
  )),
  CONSTRAINT ghl_sync_runs_status_valid CHECK (status IN (
    'running','succeeded','partial','failed','manual_review'
  )),
  CONSTRAINT ghl_sync_runs_max_attempts_valid CHECK (max_attempts BETWEEN 1 AND 3),
  CONSTRAINT ghl_sync_runs_attempt_count_nonnegative CHECK (attempt_count >= 0)
);

CREATE INDEX IF NOT EXISTS ix_ghl_sync_runs_operator_status_created
  ON public.ghl_sync_runs(operator_id, status, created_at);
CREATE INDEX IF NOT EXISTS ix_ghl_sync_runs_order_created
  ON public.ghl_sync_runs(booking_order_id, created_at);

CREATE TABLE IF NOT EXISTS public.ghl_sync_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES ghl_sync_runs(id) ON DELETE CASCADE,
  operator_id uuid NOT NULL REFERENCES operators(id),
  booking_order_id uuid REFERENCES booking_orders(id),
  booking_id uuid REFERENCES bookings(id),
  entity_type varchar(20) NOT NULL,
  operation varchar(20) NOT NULL,
  attempt_number integer NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'started',
  provider_http_status integer,
  error_code varchar(80),
  error_message text,
  payload_hash varchar(128),
  remote_id text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ghl_sync_attempts_entity_type_valid CHECK (
    entity_type IN ('contact','appointment','calendar','custom_fields')
  ),
  CONSTRAINT ghl_sync_attempts_operation_valid CHECK (
    operation IN ('upsert','create','update','cancel','reconcile')
  ),
  CONSTRAINT ghl_sync_attempts_status_valid CHECK (
    status IN ('started','succeeded','failed','unknown','manual_review')
  ),
  CONSTRAINT ghl_sync_attempts_attempt_number_valid CHECK (attempt_number BETWEEN 1 AND 3)
);

CREATE INDEX IF NOT EXISTS ix_ghl_sync_attempts_run_attempt
  ON public.ghl_sync_attempts(run_id, attempt_number);
CREATE INDEX IF NOT EXISTS ix_ghl_sync_attempts_operator_status_created
  ON public.ghl_sync_attempts(operator_id, status, created_at);
CREATE INDEX IF NOT EXISTS ix_ghl_sync_attempts_booking_entity_created
  ON public.ghl_sync_attempts(booking_id, entity_type, created_at);

ALTER TABLE public.ghl_calendar_mappings
  ADD COLUMN IF NOT EXISTS last_attempt_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_synced_at timestamptz,
  ADD COLUMN IF NOT EXISTS sync_attempt_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_error_code varchar(80),
  ADD COLUMN IF NOT EXISTS last_http_status integer,
  ADD COLUMN IF NOT EXISTS last_sync_trigger varchar(40);

ALTER TABLE public.ghl_appointment_mappings
  ADD COLUMN IF NOT EXISTS last_attempt_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_synced_at timestamptz,
  ADD COLUMN IF NOT EXISTS sync_attempt_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_error_code varchar(80),
  ADD COLUMN IF NOT EXISTS last_http_status integer,
  ADD COLUMN IF NOT EXISTS last_sync_trigger varchar(40);

ALTER TABLE public.customers
  ADD COLUMN IF NOT EXISTS ghl_contact_sync_status varchar(20) NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS ghl_contact_sync_attempt_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ghl_contact_last_synced_at timestamptz,
  ADD COLUMN IF NOT EXISTS ghl_contact_last_error text,
  ADD COLUMN IF NOT EXISTS ghl_contact_payload_hash varchar(128);

ALTER TABLE public.customers
  DROP CONSTRAINT IF EXISTS ghl_contact_sync_status_valid;
ALTER TABLE public.customers
  ADD CONSTRAINT ghl_contact_sync_status_valid CHECK (
    ghl_contact_sync_status IN ('pending','synced','failed','disabled')
  );

CREATE TABLE IF NOT EXISTS public.ghl_custom_field_mappings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  object_type varchar(20) NOT NULL,
  passport_key varchar(100) NOT NULL,
  ghl_field_id text,
  ghl_field_name text,
  data_type varchar(20) NOT NULL DEFAULT 'text',
  enabled boolean NOT NULL DEFAULT true,
  last_verified_at timestamptz,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_ghl_custom_fields_key UNIQUE (operator_id, object_type, passport_key),
  CONSTRAINT uq_ghl_custom_fields_remote UNIQUE (operator_id, object_type, ghl_field_id),
  CONSTRAINT ghl_custom_fields_object_type_valid CHECK (object_type IN ('contact','appointment')),
  CONSTRAINT ghl_custom_fields_data_type_valid CHECK (
    data_type IN ('text','number','date_time','boolean','url')
  )
);

CREATE INDEX IF NOT EXISTS ix_ghl_custom_field_mappings_operator
  ON public.ghl_custom_field_mappings(operator_id, object_type, enabled);

INSERT INTO public.passport_schema_version(version)
VALUES ('036_ghl_sync_state')
ON CONFLICT (version) DO NOTHING;

COMMIT;
