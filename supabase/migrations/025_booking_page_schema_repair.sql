BEGIN;

-- The current production database was created without migration 018 and 022.
-- These objects are required because the Booking page queries full Calendar,
-- Booking, and BookingOrder ORM rows, not only the legacy columns.

ALTER TABLE public.calendars
  ADD COLUMN IF NOT EXISTS minimum_party_size integer,
  ADD COLUMN IF NOT EXISTS maximum_party_size integer,
  ADD COLUMN IF NOT EXISTS booking_fee_bps integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tax_bps integer NOT NULL DEFAULT 0;

ALTER TABLE public.calendars
  DROP CONSTRAINT IF EXISTS ck_calendars_party_size_order,
  DROP CONSTRAINT IF EXISTS ck_calendars_booking_fee_bps,
  DROP CONSTRAINT IF EXISTS ck_calendars_tax_bps;

ALTER TABLE public.calendars
  ADD CONSTRAINT ck_calendars_party_size_order CHECK (
    minimum_party_size IS NULL OR maximum_party_size IS NULL
    OR minimum_party_size <= maximum_party_size
  ),
  ADD CONSTRAINT ck_calendars_booking_fee_bps CHECK (booking_fee_bps BETWEEN 0 AND 10000),
  ADD CONSTRAINT ck_calendars_tax_bps CHECK (tax_bps BETWEEN 0 AND 10000);

CREATE TABLE IF NOT EXISTS public.customer_types (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES public.operators(id),
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
  ON public.customer_types(operator_id, lower(name)) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_types_external
  ON public.customer_types(operator_id, external_provider, external_id)
  WHERE external_provider IS NOT NULL AND external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.calendar_rates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES public.operators(id),
  calendar_id uuid NOT NULL REFERENCES public.calendars(id) ON DELETE CASCADE,
  customer_type_id uuid NOT NULL REFERENCES public.customer_types(id),
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
  ON public.calendar_rates(operator_id, calendar_id, is_active)
  WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_calendar_rates_external
  ON public.calendar_rates(operator_id, external_provider, external_id)
  WHERE external_provider IS NOT NULL AND external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.calendar_rate_resources (
  rate_id uuid NOT NULL REFERENCES public.calendar_rates(id) ON DELETE CASCADE,
  resource_id uuid NOT NULL REFERENCES public.resources(id),
  quantity_per_unit integer NOT NULL DEFAULT 1 CHECK (quantity_per_unit > 0),
  PRIMARY KEY (rate_id, resource_id)
);
CREATE INDEX IF NOT EXISTS ix_calendar_rate_resources_resource
  ON public.calendar_rate_resources(resource_id, rate_id);

ALTER TABLE public.bookings
  ADD COLUMN IF NOT EXISTS rate_id uuid REFERENCES public.calendar_rates(id),
  ADD COLUMN IF NOT EXISTS customer_type_name_snapshot text,
  ADD COLUMN IF NOT EXISTS seat_count integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS line_subtotal_minor bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS booking_fee_minor bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tax_minor bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS line_total_minor bigint NOT NULL DEFAULT 0;

ALTER TABLE public.bookings
  DROP CONSTRAINT IF EXISTS ck_bookings_seat_count,
  DROP CONSTRAINT IF EXISTS ck_bookings_line_money;
ALTER TABLE public.bookings
  ADD CONSTRAINT ck_bookings_seat_count CHECK (seat_count > 0),
  ADD CONSTRAINT ck_bookings_line_money CHECK (
    line_subtotal_minor >= 0 AND booking_fee_minor >= 0
    AND tax_minor >= 0 AND line_total_minor >= 0
  );
CREATE INDEX IF NOT EXISTS ix_bookings_rate_id ON public.bookings(rate_id);

CREATE TABLE IF NOT EXISTS public.booking_line_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id uuid NOT NULL REFERENCES public.bookings(id) ON DELETE CASCADE,
  rate_id uuid REFERENCES public.calendar_rates(id),
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
CREATE INDEX IF NOT EXISTS ix_booking_line_items_rate ON public.booking_line_items(rate_id);

ALTER TABLE public.booking_orders
  ADD COLUMN IF NOT EXISTS marketing_opt_in boolean NOT NULL DEFAULT false;

COMMIT;
