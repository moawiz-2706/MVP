BEGIN;

CREATE TABLE IF NOT EXISTS customers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  first_name text NOT NULL,
  last_name text NOT NULL,
  email text NOT NULL,
  normalized_email text NOT NULL,
  phone text,
  normalized_phone text,
  ghl_contact_id text,
  external_provider text,
  external_id text,
  notes text,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(operator_id, normalized_email)
);
CREATE INDEX IF NOT EXISTS ix_customers_operator_phone ON customers(operator_id, normalized_phone);

ALTER TABLE booking_orders ADD COLUMN IF NOT EXISTS customer_id uuid REFERENCES customers(id);
CREATE INDEX IF NOT EXISTS ix_booking_orders_customer ON booking_orders(customer_id);
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS booking_policy_version integer;

CREATE TABLE IF NOT EXISTS customer_notes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  operator_id uuid NOT NULL REFERENCES operators(id),
  author_user_id uuid REFERENCES app_users(id),
  author_name text,
  body text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS calendar_booking_policies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  calendar_id uuid NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
  version integer NOT NULL,
  cancellation_cutoff_minutes integer NOT NULL DEFAULT 0 CHECK (cancellation_cutoff_minutes >= 0),
  cancellation_fee_bps integer NOT NULL DEFAULT 0 CHECK (cancellation_fee_bps BETWEEN 0 AND 10000),
  weather_refund_mode text NOT NULL DEFAULT 'full_refund' CHECK (weather_refund_mode IN ('full_refund','credit','manual_review','no_refund')),
  reschedule_cutoff_minutes integer NOT NULL DEFAULT 0 CHECK (reschedule_cutoff_minutes >= 0),
  reschedule_fee_minor bigint NOT NULL DEFAULT 0 CHECK (reschedule_fee_minor >= 0),
  no_show_mode text NOT NULL DEFAULT 'forfeit' CHECK (no_show_mode IN ('forfeit','partial_refund','manual_review')),
  deposit_bps integer NOT NULL DEFAULT 0 CHECK (deposit_bps BETWEEN 0 AND 10000),
  requires_waiver boolean NOT NULL DEFAULT false,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(calendar_id, version)
);
CREATE INDEX IF NOT EXISTS ix_booking_policies_active ON calendar_booking_policies(operator_id, calendar_id, active);

CREATE TABLE IF NOT EXISTS booking_adjustments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  booking_id uuid NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  payment_id uuid REFERENCES payments(id),
  action text NOT NULL CHECK (action IN ('refund','charge','credit','manual_review','none')),
  amount_minor bigint NOT NULL DEFAULT 0 CHECK (amount_minor >= 0),
  currency varchar(3) NOT NULL DEFAULT 'usd',
  reason text NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'pending',
  metadata jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_booking_adjustments_booking ON booking_adjustments(booking_id, status);

CREATE TABLE IF NOT EXISTS booking_custom_field_definitions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  calendar_id uuid REFERENCES calendars(id) ON DELETE CASCADE,
  key varchar(80) NOT NULL,
  label text NOT NULL,
  field_type varchar(20) NOT NULL DEFAULT 'text',
  required boolean NOT NULL DEFAULT false,
  options jsonb,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(operator_id, calendar_id, key)
);
CREATE TABLE IF NOT EXISTS booking_custom_field_values (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id uuid NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  definition_id uuid NOT NULL REFERENCES booking_custom_field_definitions(id) ON DELETE CASCADE,
  value jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(booking_id, definition_id)
);

CREATE TABLE IF NOT EXISTS weather_closure_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  calendar_id uuid NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
  start_at timestamptz NOT NULL,
  end_at timestamptz NOT NULL,
  reason text NOT NULL,
  refund_mode text NOT NULL DEFAULT 'full_refund',
  created_by_user_id uuid REFERENCES app_users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (start_at < end_at)
);

CREATE TABLE IF NOT EXISTS migration_imports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  provider varchar(30) NOT NULL DEFAULT 'fareharbor',
  status varchar(30) NOT NULL DEFAULT 'staged',
  source_filename text,
  summary jsonb,
  blocking_errors integer NOT NULL DEFAULT 0,
  committed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS migration_import_rows (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  import_id uuid NOT NULL REFERENCES migration_imports(id) ON DELETE CASCADE,
  row_number integer NOT NULL,
  external_id text,
  payload jsonb NOT NULL,
  status varchar(30) NOT NULL DEFAULT 'staged',
  errors jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(import_id, row_number)
);

CREATE TABLE IF NOT EXISTS reconciliation_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  scope varchar(40) NOT NULL,
  status varchar(30) NOT NULL DEFAULT 'queued',
  summary jsonb,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
