-- Per-guest waivers for staff bookings. Additive and safe to re-run.
-- Apply BEFORE deploying code that expects these columns (readiness marker 049).
--
-- 1. booking_orders.waiver_mode: 'party' (one adult signs for everyone; the
--    default and the only mode for public and affiliate checkouts) or
--    'per_guest' (staff chose a separate waiver for every guest).
-- 2. booking_waivers.guest_number: which guest a waiver is for (1..units).
--    A party waiver is guest 1. One waiver per (booking, guest) replaces the
--    old one-waiver-per-booking rule; existing rows become guest 1.
--
-- Rollback (deploy the previous code first; only safe while no booking has
-- more than one waiver):
--   ALTER TABLE public.booking_waivers DROP CONSTRAINT IF EXISTS uq_booking_waivers_booking_guest;
--   ALTER TABLE public.booking_waivers ADD CONSTRAINT uq_booking_waivers_booking_id UNIQUE (booking_id);
--   ALTER TABLE public.booking_waivers DROP COLUMN IF EXISTS guest_number;
--   ALTER TABLE public.booking_orders DROP COLUMN IF EXISTS waiver_mode;
--   DELETE FROM public.passport_schema_version WHERE version = '049_per_guest_waivers';

BEGIN;

ALTER TABLE public.booking_orders
  ADD COLUMN IF NOT EXISTS waiver_mode text NOT NULL DEFAULT 'party';
ALTER TABLE public.booking_orders DROP CONSTRAINT IF EXISTS booking_orders_waiver_mode_check;
ALTER TABLE public.booking_orders
  ADD CONSTRAINT booking_orders_waiver_mode_check CHECK (waiver_mode IN ('party', 'per_guest'));

ALTER TABLE public.booking_waivers
  ADD COLUMN IF NOT EXISTS guest_number integer NOT NULL DEFAULT 1;
ALTER TABLE public.booking_waivers DROP CONSTRAINT IF EXISTS booking_waivers_guest_number_check;
ALTER TABLE public.booking_waivers
  ADD CONSTRAINT booking_waivers_guest_number_check CHECK (guest_number >= 1);
ALTER TABLE public.booking_waivers DROP CONSTRAINT IF EXISTS uq_booking_waivers_booking_id;
ALTER TABLE public.booking_waivers DROP CONSTRAINT IF EXISTS booking_waivers_booking_id_key;
ALTER TABLE public.booking_waivers DROP CONSTRAINT IF EXISTS uq_booking_waivers_booking_guest;
ALTER TABLE public.booking_waivers
  ADD CONSTRAINT uq_booking_waivers_booking_guest UNIQUE (booking_id, guest_number);

INSERT INTO public.passport_schema_version(version)
VALUES ('049_per_guest_waivers')
ON CONFLICT (version) DO NOTHING;

COMMIT;
