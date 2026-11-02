-- Per-rate booking rules, matching FareHarbor customer types.
--
-- duration_minutes          How long a booking of this rate holds its
--                           resources (e.g. private charter 2–8 hours on one
--                           calendar). NULL = the calendar's duration.
-- min_units_per_booking     Per-booking minimum/maximum quantity for this rate
-- max_units_per_booking     (e.g. escape room "4–7 players" priced per player).
-- max_units_per_departure   Cap for this rate across all bookings on one
--                           departure (e.g. at most 10 children per cruise).
--
-- All columns are nullable and default to NULL, so existing rates behave
-- exactly as before. Additive and safe to re-run. Apply after 043 and BEFORE
-- deploying code that expects these columns (readiness marker 044).
--
-- Rollback (deploy the previous code first):
--   ALTER TABLE public.calendar_rates DROP COLUMN IF EXISTS duration_minutes,
--     DROP COLUMN IF EXISTS min_units_per_booking, DROP COLUMN IF EXISTS max_units_per_booking,
--     DROP COLUMN IF EXISTS max_units_per_departure;
--   DELETE FROM public.passport_schema_version WHERE version = '044_rate_duration_and_limits';

BEGIN;

ALTER TABLE public.calendar_rates
  ADD COLUMN IF NOT EXISTS duration_minutes integer,
  ADD COLUMN IF NOT EXISTS min_units_per_booking integer,
  ADD COLUMN IF NOT EXISTS max_units_per_booking integer,
  ADD COLUMN IF NOT EXISTS max_units_per_departure integer;

ALTER TABLE public.calendar_rates DROP CONSTRAINT IF EXISTS calendar_rates_booking_rules_check;
ALTER TABLE public.calendar_rates ADD CONSTRAINT calendar_rates_booking_rules_check CHECK (
  (duration_minutes IS NULL OR duration_minutes BETWEEN 1 AND 1440)
  AND (min_units_per_booking IS NULL OR min_units_per_booking > 0)
  AND (max_units_per_booking IS NULL OR max_units_per_booking > 0)
  AND (max_units_per_departure IS NULL OR max_units_per_departure > 0)
  AND (min_units_per_booking IS NULL OR max_units_per_booking IS NULL
       OR min_units_per_booking <= max_units_per_booking)
);

-- Serves the per-departure cap lookup.
CREATE INDEX IF NOT EXISTS ix_bookings_calendar_rate_start
  ON public.bookings (calendar_id, rate_id, start_at)
  WHERE rate_id IS NOT NULL;

INSERT INTO public.passport_schema_version(version)
VALUES ('044_rate_duration_and_limits')
ON CONFLICT (version) DO NOTHING;

COMMIT;
