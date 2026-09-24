BEGIN;

CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE public.booking_waivers
  ADD COLUMN IF NOT EXISTS token_digest text;

CREATE TABLE IF NOT EXISTS public.booking_participants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES public.operators(id),
  booking_id uuid NOT NULL REFERENCES public.bookings(id) ON DELETE CASCADE,
  sequence integer NOT NULL CHECK (sequence > 0),
  first_name text NOT NULL,
  last_name text NOT NULL,
  email text,
  phone text,
  date_of_birth date,
  is_minor boolean NOT NULL DEFAULT false,
  guardian_name text,
  emergency_contact jsonb,
  operational_notes text,
  status varchar(30) NOT NULL DEFAULT 'active' CHECK (status IN ('active','cancelled','no_show')),
  source varchar(30) NOT NULL DEFAULT 'checkout' CHECK (source IN ('checkout','operator','import')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (booking_id, sequence)
);

CREATE TABLE IF NOT EXISTS public.booking_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES public.operators(id),
  booking_id uuid NOT NULL REFERENCES public.bookings(id) ON DELETE CASCADE,
  order_id uuid REFERENCES public.booking_orders(id),
  event_type varchar(60) NOT NULL,
  from_status varchar(30),
  to_status varchar(30),
  actor_type varchar(30) NOT NULL DEFAULT 'system',
  actor_id uuid,
  reason text,
  payload jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.payment_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES public.operators(id),
  payment_id uuid NOT NULL REFERENCES public.payments(id) ON DELETE CASCADE,
  provider_event_id text NOT NULL UNIQUE,
  event_type varchar(80) NOT NULL,
  provider_status varchar(40),
  amount_minor bigint CHECK (amount_minor IS NULL OR amount_minor >= 0),
  currency varchar(3),
  payload_hash varchar(128),
  payload jsonb,
  occurred_at timestamptz NOT NULL,
  processed_at timestamptz,
  reconciliation_status varchar(30) NOT NULL DEFAULT 'observed'
);

CREATE INDEX IF NOT EXISTS ix_booking_participants_booking_sequence ON public.booking_participants(booking_id, sequence);
CREATE INDEX IF NOT EXISTS ix_booking_participants_operator_status ON public.booking_participants(operator_id, status);
CREATE INDEX IF NOT EXISTS ix_booking_events_booking_time ON public.booking_events(booking_id, occurred_at);
CREATE INDEX IF NOT EXISTS ix_payment_events_payment_time ON public.payment_events(payment_id, occurred_at);
CREATE INDEX IF NOT EXISTS ix_bookings_hold_expiry ON public.bookings(operator_id, hold_expires_at) WHERE status = 'pending_payment' AND hold_expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_bookings_calendar_time_status ON public.bookings(calendar_id, start_at, status);
CREATE INDEX IF NOT EXISTS ix_booking_orders_operator_status_created ON public.booking_orders(operator_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_payment_intent_requests_unknown ON public.payment_intent_requests(status, provider_unknown_at) WHERE status = 'provider_unknown';
CREATE INDEX IF NOT EXISTS ix_public_credentials_order_purpose ON public.public_access_credentials(order_id, purpose, revoked_at, expires_at);
CREATE INDEX IF NOT EXISTS ix_public_credentials_booking_purpose ON public.public_access_credentials(booking_id, purpose, revoked_at, expires_at);
CREATE INDEX IF NOT EXISTS ix_outbox_ready ON public.outbox_jobs(status, next_attempt_at, created_at) WHERE status IN ('pending','failed');
CREATE UNIQUE INDEX IF NOT EXISTS ux_calendar_pushed_slots_calendar_start ON public.calendar_pushed_slots(calendar_id, start_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_active_calendar_slug_per_operator ON public.calendars(operator_id, slug) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_active_category_slug_per_operator ON public.calendar_categories(operator_id, slug) WHERE deleted_at IS NULL;

DO $$ BEGIN
  ALTER TABLE public.bookings ADD CONSTRAINT bookings_time_order CHECK (start_at < end_at) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE public.calendar_blocks ADD CONSTRAINT calendar_blocks_time_order CHECK (start_at < end_at) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE public.public_access_credentials ADD CONSTRAINT public_credentials_one_target CHECK (num_nonnulls(order_id, booking_id) = 1) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE public.public_access_credentials ADD CONSTRAINT public_credentials_expiry_order CHECK (expires_at > issued_at) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE public.booking_orders ADD CONSTRAINT booking_orders_total_integrity CHECK (customer_total_minor = subtotal_minor + platform_fee_and_taxes_minor) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

ALTER TABLE public.staff_assignments ADD COLUMN IF NOT EXISTS assignment_range tstzrange GENERATED ALWAYS AS (tstzrange(start_at, end_at, '[)'::text)) STORED;
DO $$ BEGIN
  ALTER TABLE public.staff_assignments ADD CONSTRAINT staff_assignments_no_overlap EXCLUDE USING gist (operator_id WITH =, staff_id WITH =, assignment_range WITH &&) WHERE (end_at > start_at);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE OR REPLACE FUNCTION public.prevent_booking_event_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'booking_events are append-only';
END; $$;
DROP TRIGGER IF EXISTS booking_events_append_only ON public.booking_events;
CREATE TRIGGER booking_events_append_only BEFORE UPDATE OR DELETE ON public.booking_events FOR EACH ROW EXECUTE FUNCTION public.prevent_booking_event_mutation();

CREATE OR REPLACE FUNCTION public.prevent_payment_event_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'payment_events are append-only';
END; $$;
DROP TRIGGER IF EXISTS payment_events_append_only ON public.payment_events;
CREATE TRIGGER payment_events_append_only BEFORE UPDATE OR DELETE ON public.payment_events FOR EACH ROW EXECUTE FUNCTION public.prevent_payment_event_mutation();

COMMIT;
