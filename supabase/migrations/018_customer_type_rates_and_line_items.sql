BEGIN;

-- Passport-native booking parity for FareHarbor-style customer types.
-- Existing one-price calendars remain compatible; new rate rows are optional.
ALTER TABLE calendars
  ADD COLUMN IF NOT EXISTS minimum_party_size integer,
  ADD COLUMN IF NOT EXISTS maximum_party_size integer,
  ADD COLUMN IF NOT EXISTS booking_fee_bps integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tax_bps integer NOT NULL DEFAULT 0;
ALTER TABLE calendars
  DROP CONSTRAINT IF EXISTS ck_calendars_party_size_order,
  DROP CONSTRAINT IF EXISTS ck_calendars_booking_fee_bps,
  DROP CONSTRAINT IF EXISTS ck_calendars_tax_bps;
ALTER TABLE calendars
  ADD CONSTRAINT ck_calendars_party_size_order
    CHECK (minimum_party_size IS NULL OR maximum_party_size IS NULL OR minimum_party_size <= maximum_party_size),
  ADD CONSTRAINT ck_calendars_booking_fee_bps CHECK (booking_fee_bps BETWEEN 0 AND 10000),
  ADD CONSTRAINT ck_calendars_tax_bps CHECK (tax_bps BETWEEN 0 AND 10000);

CREATE TABLE IF NOT EXISTS customer_types (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  name text NOT NULL,
  plural_name text NOT NULL,
  note text,
  seat_count integer NOT NULL DEFAULT 1 CHECK (seat_count > 0),
  external_provider text,
  external_id text,
  is_active boolean NOT NULL DEFAULT true,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_types_active_name
  ON customer_types(operator_id, lower(name)) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_types_external
  ON customer_types(operator_id, external_provider, external_id)
  WHERE external_provider IS NOT NULL AND external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS calendar_rates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  calendar_id uuid NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
  customer_type_id uuid NOT NULL REFERENCES customer_types(id),
  name_snapshot text NOT NULL,
  note_snapshot text,
  price_minor bigint NOT NULL CHECK (price_minor >= 0),
  booking_fee_bps integer NOT NULL DEFAULT 0 CHECK (booking_fee_bps BETWEEN 0 AND 10000),
  tax_bps integer NOT NULL DEFAULT 0 CHECK (tax_bps BETWEEN 0 AND 10000),
  is_tax_inclusive boolean NOT NULL DEFAULT false,
  is_fee_inclusive boolean NOT NULL DEFAULT false,
  external_provider text,
  external_id text,
  is_active boolean NOT NULL DEFAULT true,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(calendar_id, customer_type_id)
);
CREATE INDEX IF NOT EXISTS ix_calendar_rates_operator_calendar
  ON calendar_rates(operator_id, calendar_id, is_active)
  WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_calendar_rates_external
  ON calendar_rates(operator_id, external_provider, external_id)
  WHERE external_provider IS NOT NULL AND external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS calendar_rate_resources (
  rate_id uuid NOT NULL REFERENCES calendar_rates(id) ON DELETE CASCADE,
  resource_id uuid NOT NULL REFERENCES resources(id),
  quantity_per_unit integer NOT NULL DEFAULT 1 CHECK (quantity_per_unit > 0),
  PRIMARY KEY(rate_id, resource_id)
);
CREATE INDEX IF NOT EXISTS ix_calendar_rate_resources_resource
  ON calendar_rate_resources(resource_id, rate_id);

ALTER TABLE bookings
  ADD COLUMN IF NOT EXISTS rate_id uuid REFERENCES calendar_rates(id),
  ADD COLUMN IF NOT EXISTS customer_type_name_snapshot text,
  ADD COLUMN IF NOT EXISTS seat_count integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS line_subtotal_minor bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS booking_fee_minor bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tax_minor bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS line_total_minor bigint NOT NULL DEFAULT 0;
ALTER TABLE bookings
  DROP CONSTRAINT IF EXISTS ck_bookings_seat_count,
  DROP CONSTRAINT IF EXISTS ck_bookings_line_money;
ALTER TABLE bookings
  ADD CONSTRAINT ck_bookings_seat_count CHECK (seat_count > 0),
  ADD CONSTRAINT ck_bookings_line_money CHECK (
    line_subtotal_minor >= 0 AND booking_fee_minor >= 0 AND tax_minor >= 0 AND line_total_minor >= 0
  );
CREATE INDEX IF NOT EXISTS ix_bookings_rate_id ON bookings(rate_id);

CREATE TABLE IF NOT EXISTS booking_line_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id uuid NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  rate_id uuid REFERENCES calendar_rates(id),
  customer_type_name_snapshot text NOT NULL,
  note_snapshot text,
  quantity integer NOT NULL CHECK (quantity > 0),
  seat_count_snapshot integer NOT NULL CHECK (seat_count_snapshot > 0),
  unit_price_minor bigint NOT NULL CHECK (unit_price_minor >= 0),
  line_subtotal_minor bigint NOT NULL CHECK (line_subtotal_minor >= 0),
  booking_fee_minor bigint NOT NULL DEFAULT 0 CHECK (booking_fee_minor >= 0),
  tax_minor bigint NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
  line_total_minor bigint NOT NULL CHECK (line_total_minor >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(booking_id)
);
CREATE INDEX IF NOT EXISTS ix_booking_line_items_rate ON booking_line_items(rate_id);

-- Keep compact join tables tenant-safe through the owning rows.
CREATE OR REPLACE FUNCTION enforce_calendar_rate_tenant()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM calendars c JOIN customer_types ct ON ct.id = NEW.customer_type_id
    WHERE c.id = NEW.calendar_id
      AND c.operator_id = NEW.operator_id
      AND ct.operator_id = NEW.operator_id
  ) THEN
    RAISE EXCEPTION 'calendar, customer type, and rate must share an operator';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_calendar_rate_tenant ON calendar_rates;
CREATE TRIGGER trg_calendar_rate_tenant
BEFORE INSERT OR UPDATE ON calendar_rates
FOR EACH ROW EXECUTE FUNCTION enforce_calendar_rate_tenant();

CREATE OR REPLACE FUNCTION enforce_calendar_rate_resource_tenant()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM calendar_rates cr JOIN resources r ON r.id = NEW.resource_id
    WHERE cr.id = NEW.rate_id AND cr.operator_id = r.operator_id
  ) THEN
    RAISE EXCEPTION 'rate and resource must belong to the same operator';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_calendar_rate_resource_tenant ON calendar_rate_resources;
CREATE TRIGGER trg_calendar_rate_resource_tenant
BEFORE INSERT OR UPDATE ON calendar_rate_resources
FOR EACH ROW EXECUTE FUNCTION enforce_calendar_rate_resource_tenant();

DROP TRIGGER IF EXISTS trg_customer_types_updated_at ON customer_types;
CREATE TRIGGER trg_customer_types_updated_at BEFORE UPDATE ON customer_types
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_calendar_rates_updated_at ON calendar_rates;
CREATE TRIGGER trg_calendar_rates_updated_at BEFORE UPDATE ON calendar_rates
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_booking_line_items_updated_at ON booking_line_items;
CREATE TRIGGER trg_booking_line_items_updated_at BEFORE UPDATE ON booking_line_items
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;

-- Rollback note: remove rate rows and booking line items only after any migrated
-- records have been archived. Existing legacy calendar/booking fields remain valid.
