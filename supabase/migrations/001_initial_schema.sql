BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TABLE operators (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ghl_location_id text NOT NULL UNIQUE,
  name text NOT NULL,
  slug text NOT NULL UNIQUE,
  time_zone text NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  public_booking_enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ghl_installations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL UNIQUE REFERENCES operators(id),
  location_id text NOT NULL UNIQUE,
  company_id text,
  installed_by_user_id text,
  access_token_encrypted text NOT NULL,
  refresh_token_encrypted text NOT NULL,
  access_token_expires_at timestamptz NOT NULL,
  is_installed boolean NOT NULL DEFAULT true,
  installed_at timestamptz NOT NULL DEFAULT now(),
  uninstalled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app_users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ghl_user_id text NOT NULL UNIQUE,
  email text,
  name text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE operator_users (
  operator_id uuid NOT NULL REFERENCES operators(id),
  user_id uuid NOT NULL REFERENCES app_users(id),
  ghl_role text,
  is_agency_owner boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (operator_id, user_id)
);

CREATE TABLE operator_settings (
  operator_id uuid PRIMARY KEY REFERENCES operators(id),
  confirmation_email_enabled boolean NOT NULL DEFAULT true,
  confirmation_email_from text,
  confirmation_email_subject text NOT NULL DEFAULT 'Booking Confirmation',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE departure_locations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  name text NOT NULL,
  address text NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE calendar_categories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  name text NOT NULL,
  display_color text,
  sort_order integer NOT NULL DEFAULT 0,
  is_active boolean NOT NULL DEFAULT true,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_calendar_categories_active_name
  ON calendar_categories (operator_id, lower(name)) WHERE deleted_at IS NULL;

CREATE TABLE calendars (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  calendar_category_id uuid REFERENCES calendar_categories(id),
  departure_location_id uuid REFERENCES departure_locations(id),
  name text NOT NULL,
  slug text NOT NULL,
  description text,
  is_active boolean NOT NULL DEFAULT true,
  public_booking_enabled boolean NOT NULL DEFAULT true,
  duration_minutes integer NOT NULL CHECK (duration_minutes > 0),
  slot_interval_minutes integer NOT NULL DEFAULT 30 CHECK (slot_interval_minutes > 0),
  max_units_per_booking integer CHECK (max_units_per_booking IS NULL OR max_units_per_booking > 0),
  base_price_minor bigint NOT NULL DEFAULT 0 CHECK (base_price_minor >= 0),
  currency text NOT NULL DEFAULT 'usd' CHECK (currency ~ '^[a-z]{3}$'),
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (operator_id, slug)
);

CREATE TABLE calendar_hours (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  calendar_id uuid NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
  day_of_week smallint NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
  start_time time NOT NULL,
  end_time time NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (start_time < end_time),
  UNIQUE (calendar_id, day_of_week, start_time, end_time)
);

CREATE TABLE calendar_blocks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  calendar_id uuid NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
  start_at timestamptz NOT NULL,
  end_at timestamptz NOT NULL,
  reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (start_at < end_at)
);

CREATE TABLE resources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  name text NOT NULL,
  quantity integer NOT NULL CHECK (quantity >= 0),
  is_active boolean NOT NULL DEFAULT true,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_resources_active_name
  ON resources (operator_id, lower(name)) WHERE deleted_at IS NULL;

CREATE TABLE calendar_resources (
  calendar_id uuid NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
  resource_id uuid NOT NULL REFERENCES resources(id),
  default_quantity_per_unit integer NOT NULL DEFAULT 1 CHECK (default_quantity_per_unit > 0),
  PRIMARY KEY (calendar_id, resource_id)
);

CREATE TABLE booking_orders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  public_reference text NOT NULL UNIQUE,
  customer_first_name text NOT NULL,
  customer_last_name text NOT NULL,
  customer_email text NOT NULL,
  customer_phone text,
  ghl_contact_id text,
  currency text NOT NULL DEFAULT 'usd' CHECK (currency ~ '^[a-z]{3}$'),
  subtotal_minor bigint NOT NULL CHECK (subtotal_minor >= 0),
  platform_fee_and_taxes_minor bigint NOT NULL CHECK (platform_fee_and_taxes_minor >= 0),
  customer_total_minor bigint NOT NULL CHECK (customer_total_minor >= 0),
  operator_transfer_minor bigint NOT NULL CHECK (operator_transfer_minor >= 0),
  platform_gross_retained_minor bigint NOT NULL CHECK (platform_gross_retained_minor >= 0),
  status text NOT NULL CHECK (status IN (
    'pending_payment','paid','confirmed','expired','cancelled',
    'partially_refunded','refunded','exception'
  )),
  ghl_contact_sync_status text NOT NULL DEFAULT 'pending'
    CHECK (ghl_contact_sync_status IN ('pending','synced','failed','disabled')),
  ghl_confirmation_email_status text NOT NULL DEFAULT 'pending'
    CHECK (ghl_confirmation_email_status IN ('pending','sent','failed','disabled')),
  ghl_conversation_id text,
  ghl_message_id text,
  ghl_email_message_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bookings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  booking_order_id uuid NOT NULL REFERENCES booking_orders(id),
  calendar_id uuid NOT NULL REFERENCES calendars(id),
  departure_location_id uuid REFERENCES departure_locations(id),
  start_at timestamptz NOT NULL,
  end_at timestamptz NOT NULL,
  units integer NOT NULL DEFAULT 1 CHECK (units > 0),
  base_price_minor bigint NOT NULL CHECK (base_price_minor >= 0),
  status text NOT NULL CHECK (status IN (
    'pending_payment','confirmed','cancelled','completed','no_show','failed'
  )),
  hold_expires_at timestamptz,
  calendar_name_snapshot text NOT NULL,
  departure_location_name_snapshot text,
  departure_location_address_snapshot text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (start_at < end_at),
  CHECK (status <> 'pending_payment' OR hold_expires_at IS NOT NULL)
);

CREATE TABLE booking_resources (
  booking_id uuid NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  resource_id uuid NOT NULL REFERENCES resources(id),
  quantity integer NOT NULL CHECK (quantity > 0),
  PRIMARY KEY (booking_id, resource_id)
);

CREATE TABLE stripe_connections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL UNIQUE REFERENCES operators(id),
  stripe_account_id text NOT NULL UNIQUE,
  account_type text,
  country text,
  details_submitted boolean NOT NULL DEFAULT false,
  payouts_enabled boolean NOT NULL DEFAULT false,
  charges_enabled boolean NOT NULL DEFAULT false,
  transfers_capability_status text,
  onboarding_complete boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE payments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  booking_order_id uuid NOT NULL UNIQUE REFERENCES booking_orders(id),
  stripe_payment_intent_id text UNIQUE,
  stripe_charge_id text UNIQUE,
  stripe_balance_transaction_id text,
  currency text NOT NULL CHECK (currency ~ '^[a-z]{3}$'),
  subtotal_minor bigint NOT NULL CHECK (subtotal_minor >= 0),
  platform_fee_and_taxes_minor bigint NOT NULL CHECK (platform_fee_and_taxes_minor >= 0),
  customer_total_minor bigint NOT NULL CHECK (customer_total_minor >= 0),
  operator_transfer_minor bigint NOT NULL CHECK (operator_transfer_minor >= 0),
  platform_gross_retained_minor bigint NOT NULL CHECK (platform_gross_retained_minor >= 0),
  stripe_fee_minor bigint,
  platform_net_minor bigint,
  status text NOT NULL CHECK (status IN (
    'requires_payment','processing','succeeded','failed','partially_refunded','refunded'
  )),
  paid_at timestamptz,
  refunded_minor bigint NOT NULL DEFAULT 0 CHECK (refunded_minor >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE stripe_transfers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  payment_id uuid NOT NULL UNIQUE REFERENCES payments(id),
  stripe_transfer_id text UNIQUE,
  stripe_connected_account_id text NOT NULL,
  stripe_source_transaction_id text NOT NULL CHECK (stripe_source_transaction_id LIKE 'ch\_%'),
  transfer_group text,
  amount_minor bigint NOT NULL CHECK (amount_minor >= 0),
  currency text NOT NULL CHECK (currency ~ '^[a-z]{3}$'),
  status text NOT NULL CHECK (status IN (
    'pending','created','failed','partially_reversed','reversed'
  )),
  reversed_minor bigint NOT NULL DEFAULT 0 CHECK (reversed_minor >= 0),
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (reversed_minor <= amount_minor)
);

CREATE TABLE stripe_webhook_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  stripe_event_id text NOT NULL UNIQUE,
  event_type text NOT NULL,
  status text NOT NULL CHECK (status IN ('processing','processed','failed')),
  processed_at timestamptz,
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE outbox_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  booking_order_id uuid REFERENCES booking_orders(id),
  job_type text NOT NULL CHECK (job_type IN (
    'stripe_create_transfer','ghl_upsert_contact','ghl_send_confirmation_email'
  )),
  idempotency_key text NOT NULL UNIQUE,
  payload jsonb,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','processing','completed','failed')),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  next_attempt_at timestamptz,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_operator_users_user_id ON operator_users(user_id);
CREATE INDEX ix_departure_locations_operator_id ON departure_locations(operator_id);
CREATE INDEX ix_calendar_categories_operator_id ON calendar_categories(operator_id);
CREATE INDEX ix_calendars_operator_id ON calendars(operator_id);
CREATE INDEX ix_calendars_category_id ON calendars(calendar_category_id);
CREATE INDEX ix_calendars_departure_location_id ON calendars(departure_location_id);
CREATE INDEX ix_calendar_hours_calendar_weekday ON calendar_hours(calendar_id, day_of_week);
CREATE INDEX ix_calendar_blocks_calendar_interval ON calendar_blocks(calendar_id, start_at, end_at);
CREATE INDEX ix_resources_operator_id ON resources(operator_id);
CREATE INDEX ix_calendar_resources_resource_id ON calendar_resources(resource_id);
CREATE INDEX ix_bookings_operator_interval ON bookings(operator_id, start_at, end_at);
CREATE INDEX ix_bookings_calendar_interval ON bookings(calendar_id, start_at, end_at);
CREATE INDEX ix_bookings_order_id ON bookings(booking_order_id);
CREATE INDEX ix_bookings_status ON bookings(status);
CREATE INDEX ix_bookings_hold_expiry ON bookings(hold_expires_at);
CREATE INDEX ix_booking_resources_resource_id ON booking_resources(resource_id);
CREATE INDEX ix_booking_orders_operator_created ON booking_orders(operator_id, created_at DESC);
CREATE INDEX ix_payments_operator_status ON payments(operator_id, status);
CREATE INDEX ix_outbox_jobs_ready ON outbox_jobs(status, next_attempt_at);

-- The supplied compact join-table schemas do not carry operator_id. These
-- triggers close the otherwise possible cross-tenant foreign-key gap.
CREATE OR REPLACE FUNCTION enforce_calendar_resource_tenant()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM calendars c JOIN resources r ON r.id = NEW.resource_id
    WHERE c.id = NEW.calendar_id AND c.operator_id = r.operator_id
  ) THEN
    RAISE EXCEPTION 'calendar and resource must belong to the same operator';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_calendar_resource_tenant
BEFORE INSERT OR UPDATE ON calendar_resources
FOR EACH ROW EXECUTE FUNCTION enforce_calendar_resource_tenant();

CREATE OR REPLACE FUNCTION enforce_booking_tenant()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM booking_orders bo JOIN calendars c ON c.id = NEW.calendar_id
    WHERE bo.id = NEW.booking_order_id
      AND bo.operator_id = NEW.operator_id
      AND c.operator_id = NEW.operator_id
  ) THEN
    RAISE EXCEPTION 'booking order, calendar, and booking must share an operator';
  END IF;
  IF NEW.departure_location_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM departure_locations dl
    WHERE dl.id = NEW.departure_location_id AND dl.operator_id = NEW.operator_id
  ) THEN
    RAISE EXCEPTION 'booking location must belong to the booking operator';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_booking_tenant
BEFORE INSERT OR UPDATE ON bookings
FOR EACH ROW EXECUTE FUNCTION enforce_booking_tenant();

CREATE OR REPLACE FUNCTION enforce_booking_resource_tenant()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM bookings b JOIN resources r ON r.id = NEW.resource_id
    WHERE b.id = NEW.booking_id AND b.operator_id = r.operator_id
  ) THEN
    RAISE EXCEPTION 'booking and resource must belong to the same operator';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_booking_resource_tenant
BEFORE INSERT OR UPDATE ON booking_resources
FOR EACH ROW EXECUTE FUNCTION enforce_booking_resource_tenant();

CREATE OR REPLACE FUNCTION enforce_financial_tenant()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_operator uuid;
BEGIN
  IF TG_TABLE_NAME = 'payments' THEN
    SELECT operator_id INTO expected_operator FROM booking_orders WHERE id = NEW.booking_order_id;
  ELSE
    SELECT operator_id INTO expected_operator FROM payments WHERE id = NEW.payment_id;
  END IF;
  IF expected_operator IS DISTINCT FROM NEW.operator_id THEN
    RAISE EXCEPTION 'financial record tenant mismatch';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_payment_tenant BEFORE INSERT OR UPDATE ON payments
FOR EACH ROW EXECUTE FUNCTION enforce_financial_tenant();
CREATE TRIGGER trg_transfer_tenant BEFORE INSERT OR UPDATE ON stripe_transfers
FOR EACH ROW EXECUTE FUNCTION enforce_financial_tenant();

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'operators','ghl_installations','app_users','operator_users','operator_settings',
    'departure_locations','calendar_categories','calendars','calendar_hours',
    'calendar_blocks','resources','booking_orders','bookings','stripe_connections',
    'payments','stripe_transfers','outbox_jobs'
  ] LOOP
    EXECUTE format(
      'CREATE TRIGGER trg_%I_updated_at BEFORE UPDATE ON %I '
      'FOR EACH ROW EXECUTE FUNCTION set_updated_at()', table_name, table_name
    );
  END LOOP;
END;
$$;

COMMIT;
