-- FareHarbor → Passport catalogue import v2 (2026-11-03). Supersedes batch 1.
--
-- Source: read-only review of the Punta Gorda Adventures FareHarbor account
-- (item prices, resource requirements and every future availability through
-- 2027-12-31). Mapping and decisions: docs/integrations/fareharbor/CATALOG_MAPPING.md
--
-- REQUIRES migration 044_rate_duration_and_limits (per-rate length, per-booking
-- range and per-departure cap). Run 044 first.
--
-- Creates or updates (matched by slug / name, so re-running is safe):
--   Resources   all 7 FareHarbor resources
--   Calendars   The Oasis BYOB Sunset Cruise – Public       (date ranges, 2 h)
--               Tropical Tides Scenic Day Cruise – Public     (date ranges, 1.5 h)
--               The Oasis Tiki Boat – Private Cruise           (daily, 2–8 h options)
--               The Oasis Tiki Boat Public Holiday Canal Cruise (exact 79 departures)
--               The Oasis Tiki Boat – Private Christmas Canal Cruise (Dec 2026, 2–8 h)
--               Escape Room "Quest for the Fountain of Youth"  (daily, group tiers)
--   All boat calendars share The Oasis Tiki Seats (30): a public guest takes
--   1 seat, a private charter all 30 for its chosen length.
--
-- SAFETY
--   * Calendars are created INACTIVE and not publicly bookable; review them in
--     Passport → Calendars and switch them on. Nothing is sold and no HighLevel
--     calendar is created until then.
--   * A calendar that already has bookings is never reconfigured by this script.
--   * Nothing is deleted except this script's own schedule rows on calendars
--     without bookings (so re-running replaces them cleanly).
--   * Staff are not required before sale (owner decision 2026-11-02);
--     required_staff_roles only names the role offered when assigning crew.

BEGIN;

CREATE OR REPLACE FUNCTION pg_temp.fh_calendar(
  p_operator uuid, p_category uuid, p_location uuid, p_name text, p_slug text, p_headline text,
  p_description text, p_duration int, p_interval int, p_max_units int, p_max_party int,
  p_roles jsonb, p_mode text
) RETURNS uuid LANGUAGE plpgsql AS $fn$
DECLARE v_id uuid;
BEGIN
  SELECT id INTO v_id FROM public.calendars
  WHERE operator_id = p_operator AND slug = p_slug AND deleted_at IS NULL;
  IF v_id IS NULL THEN
    INSERT INTO public.calendars (
      operator_id, calendar_category_id, departure_location_id, name, slug, headline, description,
      is_active, public_booking_enabled, duration_minutes, slot_interval_minutes, max_units_per_booking,
      maximum_party_size, base_price_minor, currency, availability_mode, required_staff_roles,
      public_booking_mode, tax_bps)
    VALUES (p_operator, p_category, p_location, p_name, p_slug, p_headline, p_description,
      false, false, p_duration, p_interval, p_max_units, p_max_party, 0, 'usd', p_mode, p_roles,
      'online', 700)
    RETURNING id INTO v_id;
  ELSIF NOT EXISTS (SELECT 1 FROM public.bookings WHERE calendar_id = v_id) THEN
    UPDATE public.calendars SET calendar_category_id = p_category, departure_location_id = p_location,
      name = p_name, headline = p_headline, description = p_description, duration_minutes = p_duration,
      slot_interval_minutes = p_interval, availability_mode = p_mode, max_units_per_booking = p_max_units,
      maximum_party_size = p_max_party, required_staff_roles = p_roles, updated_at = now()
    WHERE id = v_id;
    -- Replace this script's schedule rows; they are regenerated below.
    DELETE FROM public.calendar_date_hours WHERE calendar_id = v_id;
    DELETE FROM public.calendar_pushed_slots WHERE calendar_id = v_id;
  END IF;
  RETURN v_id;
END $fn$;

CREATE OR REPLACE FUNCTION pg_temp.fh_rate(
  p_operator uuid, p_calendar uuid, p_type text, p_plural text, p_note text, p_seats int,
  p_price int, p_resource uuid, p_seats_used int, p_active boolean, p_key text,
  p_duration int, p_min int, p_max int, p_cap int
) RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE v_type uuid; v_rate uuid;
BEGIN
  IF EXISTS (SELECT 1 FROM public.bookings WHERE calendar_id = p_calendar) THEN
    RETURN;  -- never reprice a calendar that is already selling
  END IF;
  INSERT INTO public.customer_types (operator_id, name, plural_name, note, seat_count, external_provider, external_id, is_active)
  SELECT p_operator, p_type, p_plural, p_note, p_seats, 'fareharbor', p_key, true
  WHERE NOT EXISTS (SELECT 1 FROM public.customer_types
                    WHERE operator_id = p_operator AND name = p_type AND deleted_at IS NULL);
  SELECT id INTO v_type FROM public.customer_types
  WHERE operator_id = p_operator AND name = p_type AND deleted_at IS NULL;

  INSERT INTO public.calendar_rates (operator_id, calendar_id, customer_type_id, name_snapshot, note_snapshot,
    price_minor, booking_fee_bps, tax_bps, is_tax_inclusive, is_fee_inclusive, external_provider, external_id,
    is_active, duration_minutes, min_units_per_booking, max_units_per_booking, max_units_per_departure)
  VALUES (p_operator, p_calendar, v_type, p_type, p_note, p_price, 0, 700, false, false, 'fareharbor', p_key,
    p_active, p_duration, p_min, p_max, p_cap)
  ON CONFLICT (calendar_id, customer_type_id) DO UPDATE SET
    price_minor = EXCLUDED.price_minor, note_snapshot = EXCLUDED.note_snapshot, tax_bps = 700,
    is_active = EXCLUDED.is_active, deleted_at = NULL, duration_minutes = EXCLUDED.duration_minutes,
    min_units_per_booking = EXCLUDED.min_units_per_booking, max_units_per_booking = EXCLUDED.max_units_per_booking,
    max_units_per_departure = EXCLUDED.max_units_per_departure, external_id = EXCLUDED.external_id,
    updated_at = now()
  RETURNING id INTO v_rate;

  DELETE FROM public.calendar_rate_resources WHERE rate_id = v_rate;
  IF p_resource IS NOT NULL THEN
    INSERT INTO public.calendar_rate_resources (rate_id, resource_id, quantity_per_unit)
    VALUES (v_rate, p_resource, p_seats_used);
  END IF;
END $fn$;

CREATE OR REPLACE FUNCTION pg_temp.fh_policy(p_operator uuid, p_calendar uuid) RETURNS void LANGUAGE sql AS $fn$
  -- Account default: full refund when cancelled more than 48 hours before start.
  INSERT INTO public.calendar_booking_policies (operator_id, calendar_id, version, cancellation_cutoff_minutes,
                                                cancellation_fee_bps, weather_refund_mode, active)
  VALUES (p_operator, p_calendar, 1, 2880, 0, 'full_refund', true)
  ON CONFLICT (calendar_id, version) DO NOTHING;
$fn$;

DO $$
DECLARE
  tz constant text := 'America/New_York';
  v_operator uuid; v_location uuid; v_seats uuid;
  c_public uuid; c_private uuid; c_experience uuid;
  v_sunset uuid; v_tropical uuid; v_private uuid; v_canal uuid; v_xmas uuid; v_escape uuid;
  r record;
BEGIN
  SELECT id INTO v_operator FROM public.operators WHERE slug = 'punta-gorda-adventures';
  IF v_operator IS NULL THEN RAISE EXCEPTION 'Operator punta-gorda-adventures not found'; END IF;

  -- Resources
  FOR r IN SELECT * FROM (VALUES
      ('Motor Yacht 55ft', 1, 'vessel'), ('SV Sea Dancer Seats', 6, 'seat'), ('S/V Courageous Seats', 6, 'seat'),
      ('The Oasis Tiki Seats', 30, 'seat'), ('37ft Hunter', 1, 'vessel'), ('41ft Morgan', 1, 'vessel'),
      ('Carver 52ft MY', 1, 'vessel')) AS t(name, quantity, kind)
  LOOP
    INSERT INTO public.resources (operator_id, name, quantity, resource_type, notes, is_active)
    SELECT v_operator, r.name, r.quantity, r.kind, 'Imported from FareHarbor resources.', true
    WHERE NOT EXISTS (SELECT 1 FROM public.resources
                      WHERE operator_id = v_operator AND name = r.name AND deleted_at IS NULL);
  END LOOP;
  SELECT id INTO v_seats FROM public.resources
  WHERE operator_id = v_operator AND name = 'The Oasis Tiki Seats' AND deleted_at IS NULL;

  -- Location
  INSERT INTO public.departure_locations (operator_id, name, address, is_active)
  SELECT v_operator, 'Laishley Park Marina Public Dock', '120 Laishley Ct, Punta Gorda, FL 33950', true
  WHERE NOT EXISTS (SELECT 1 FROM public.departure_locations
                    WHERE operator_id = v_operator AND name = 'Laishley Park Marina Public Dock' AND deleted_at IS NULL);
  SELECT id INTO v_location FROM public.departure_locations
  WHERE operator_id = v_operator AND name = 'Laishley Park Marina Public Dock' AND deleted_at IS NULL;

  -- Categories (display grouping only)
  FOR r IN SELECT * FROM (VALUES ('Public Cruises', 'public-cruises', '#1b7f6c', 10),
                                 ('Private Charters', 'private-charters', '#3b6fd8', 20),
                                 ('Experiences', 'experiences', '#b8742a', 30)) AS t(name, slug, color, sort)
  LOOP
    INSERT INTO public.calendar_categories (operator_id, name, slug, display_color, sort_order)
    SELECT v_operator, r.name, r.slug, r.color, r.sort
    WHERE NOT EXISTS (SELECT 1 FROM public.calendar_categories
                      WHERE operator_id = v_operator AND slug = r.slug AND deleted_at IS NULL);
  END LOOP;
  SELECT id INTO c_public FROM public.calendar_categories WHERE operator_id = v_operator AND slug = 'public-cruises' AND deleted_at IS NULL;
  SELECT id INTO c_private FROM public.calendar_categories WHERE operator_id = v_operator AND slug = 'private-charters' AND deleted_at IS NULL;
  SELECT id INTO c_experience FROM public.calendar_categories WHERE operator_id = v_operator AND slug = 'experiences' AND deleted_at IS NULL;

  -- Batch 1 named the private calendar "...-2h"; it now carries all lengths.
  UPDATE public.calendars c SET slug = 'oasis-private-cruise'
  WHERE c.operator_id = v_operator AND c.slug = 'oasis-private-cruise-2h' AND c.deleted_at IS NULL
    AND NOT EXISTS (SELECT 1 FROM public.bookings b WHERE b.calendar_id = c.id)
    AND NOT EXISTS (SELECT 1 FROM public.calendars o WHERE o.operator_id = v_operator AND o.slug = 'oasis-private-cruise' AND o.deleted_at IS NULL);

  -------------------------------------------------------------------------------
  -- "The Oasis" BYOB Sunset Cruise – Public (FareHarbor 502154), 2 hours
  --   2026-11-02..30: 4:30 PM · 2026-12-01..2027-12-31: 5:15 PM and 7:45 PM
  v_sunset := pg_temp.fh_calendar(v_operator, c_public, v_location, '"The Oasis" BYOB Sunset Cruise - Public',
    'oasis-sunset-cruise-public', 'Dolphin Sightings - Island Tunes - Private Restroom - Punta Gorda''s #1 Attraction',
    'Come aboard Charlotte Harbor''s #1 sunset cruise. Watch dolphins swim alongside while you sip your favorite BYOB drinks. Enjoy stunning Florida sunsets with luxury seating. Private restroom on board. Children under 6 must wear a life jacket at all times.',
    120, 150, 30, 30, '["Captain"]'::jsonb, 'date_wise');
  IF NOT EXISTS (SELECT 1 FROM public.calendar_date_hours WHERE calendar_id = v_sunset) THEN
    INSERT INTO public.calendar_date_hours (calendar_id, start_date, end_date, start_time, end_time) VALUES
      (v_sunset, '2026-11-02', '2026-11-30', '16:30', '18:30'),
      (v_sunset, '2026-12-01', '2027-12-31', '17:15', '21:45');
  END IF;
  PERFORM pg_temp.fh_rate(v_operator, v_sunset, 'Adult (13+)', 'Adults', 'Ages 13+', 1, 5900, v_seats, 1, true, '502154:adult', NULL, NULL, NULL, NULL);
  PERFORM pg_temp.fh_rate(v_operator, v_sunset, 'Child (12 and under)', 'Children', 'Ages 12 and under', 1, 3500, v_seats, 1, true, '502154:child', NULL, NULL, NULL, 10);
  PERFORM pg_temp.fh_rate(v_operator, v_sunset, 'Adult (December only)', 'Adults (December)', 'December pricing, ages 13+', 1, 6900, v_seats, 1, false, '502154:adult-december', NULL, NULL, NULL, NULL);
  PERFORM pg_temp.fh_rate(v_operator, v_sunset, 'Child (December only)', 'Children (December)', 'December pricing, ages 12 and under', 1, 4500, v_seats, 1, false, '502154:child-december', NULL, NULL, NULL, 10);
  PERFORM pg_temp.fh_policy(v_operator, v_sunset);

  -------------------------------------------------------------------------------
  -- Tropical Tides Scenic Day Cruise – Public (529145), 1.5 hours
  --   2026-11-02..30: 2:30 PM · 2026-12-01..2027-12-31: 1:00 PM and 3:00 PM (not 2026-12-25)
  v_tropical := pg_temp.fh_calendar(v_operator, c_public, v_location, 'Tropical Tides Scenic Day Cruise - Public',
    'tropical-tides-scenic-day-cruise', 'All Ages • 1.5 Hour Cruise',
    'A scenic daytime cruise on The Oasis Tiki Boat for all ages. Any passenger under 6 years old must wear a life jacket at all times while on board.',
    90, 120, 30, 30, '["Captain"]'::jsonb, 'date_wise');
  IF NOT EXISTS (SELECT 1 FROM public.calendar_date_hours WHERE calendar_id = v_tropical) THEN
    INSERT INTO public.calendar_date_hours (calendar_id, start_date, end_date, start_time, end_time) VALUES
      (v_tropical, '2026-11-02', '2026-11-30', '14:30', '16:00'),
      (v_tropical, '2026-12-01', '2026-12-24', '13:00', '16:30'),
      (v_tropical, '2026-12-26', '2027-12-31', '13:00', '16:30');
  END IF;
  PERFORM pg_temp.fh_rate(v_operator, v_tropical, 'Adult (13+)', 'Adults', 'Ages 13+', 1, 4900, v_seats, 1, true, '529145:adult', NULL, NULL, 30, NULL);
  PERFORM pg_temp.fh_rate(v_operator, v_tropical, 'Child (12 and under)', 'Children', 'Ages 12 and under', 1, 3500, v_seats, 1, true, '529145:child', NULL, NULL, 30, NULL);
  PERFORM pg_temp.fh_policy(v_operator, v_tropical);

  -------------------------------------------------------------------------------
  -- The Oasis Tiki Boat – Private Cruise (508627): daily 10:00, 12:30, 3:00, 5:30, 8:00
  --   Each length holds all 30 Oasis seats from the start for that length.
  v_private := pg_temp.fh_calendar(v_operator, c_private, v_location, 'The Oasis Tiki Boat - Private Cruise',
    'oasis-private-cruise', 'Your Own Boat For Up To 30 Of Your Crew',
    'Private charter of The Oasis Tiki Boat for up to 30 guests. Choose 2 to 8 hours. Split parties are not allowed.',
    120, 150, 1, 30, '["Captain"]'::jsonb, 'day_wise');
  DELETE FROM public.calendar_hours h WHERE h.calendar_id = v_private
    AND NOT EXISTS (SELECT 1 FROM public.bookings b WHERE b.calendar_id = v_private);
  INSERT INTO public.calendar_hours (calendar_id, day_of_week, start_time, end_time)
  SELECT v_private, d, '10:00', '22:00' FROM generate_series(0, 6) AS d
  ON CONFLICT (calendar_id, day_of_week, start_time, end_time) DO NOTHING;
  FOR r IN SELECT * FROM (VALUES (2, 160000), (3, 200000), (4, 235000), (5, 265000), (6, 290000), (7, 310000), (8, 325000)) AS t(hours, price)
  LOOP
    PERFORM pg_temp.fh_rate(v_operator, v_private, format('Private Oasis %s Hour', r.hours), format('Private Oasis %s Hour', r.hours),
      format('Whole boat for %s hours, up to 30 guests', r.hours), 1, r.price, v_seats, 30, true,
      format('508627:private-%sh', r.hours), r.hours * 60, NULL, 1, NULL);
  END LOOP;
  PERFORM pg_temp.fh_policy(v_operator, v_private);

  -------------------------------------------------------------------------------
  -- The Oasis Tiki Boat Public Holiday Canal Cruise (577774), 2 hours, exact departures
  v_canal := pg_temp.fh_calendar(v_operator, c_public, v_location, 'The Oasis Tiki Boat Public Holiday Canal Cruise',
    'oasis-holiday-canal-cruise', 'All Ages • 2 Hour Cruise',
    'Cruise the Punta Gorda canals to see the holiday lights on The Oasis Tiki Boat.',
    120, 120, 30, 30, '["Captain"]'::jsonb, 'pushed');
  INSERT INTO public.calendar_pushed_slots (calendar_id, start_at)
  SELECT v_canal, (s.local_start::timestamp AT TIME ZONE tz)
  FROM unnest(ARRAY[
    '2026-11-29 17:30',
    '2026-12-01 17:15','2026-12-01 19:45','2026-12-02 17:15','2026-12-02 19:45','2026-12-03 17:15','2026-12-03 19:45',
    '2026-12-04 17:15','2026-12-04 19:45','2026-12-04 22:15','2026-12-05 17:15','2026-12-05 19:45','2026-12-05 22:15',
    '2026-12-06 17:15','2026-12-06 19:45','2026-12-06 22:15','2026-12-07 17:15','2026-12-07 19:45',
    '2026-12-08 16:30','2026-12-08 19:45','2026-12-09 16:30','2026-12-09 19:45','2026-12-10 17:15','2026-12-10 19:45',
    '2026-12-11 17:15','2026-12-11 19:45','2026-12-11 21:30','2026-12-11 22:15',
    '2026-12-12 17:15','2026-12-12 19:45','2026-12-12 22:15','2026-12-12 22:30',
    '2026-12-13 17:15','2026-12-13 19:45','2026-12-13 22:15','2026-12-14 16:30','2026-12-14 19:00',
    '2026-12-15 17:15','2026-12-15 19:45','2026-12-16 17:15','2026-12-16 19:45','2026-12-17 17:15','2026-12-17 19:45',
    '2026-12-18 17:15','2026-12-18 19:45','2026-12-18 22:15','2026-12-19 17:15','2026-12-19 19:45','2026-12-19 22:15',
    '2026-12-20 17:15','2026-12-20 19:45','2026-12-20 22:15','2026-12-21 17:15','2026-12-21 19:45',
    '2026-12-22 17:15','2026-12-22 19:45','2026-12-23 17:15','2026-12-24 17:15','2026-12-24 19:45',
    '2026-12-25 17:15','2026-12-25 19:45','2026-12-25 22:30','2026-12-26 17:15','2026-12-26 19:45','2026-12-26 22:15','2026-12-26 22:30',
    '2026-12-27 17:15','2026-12-27 19:45','2026-12-27 22:15','2026-12-28 17:15','2026-12-28 19:45',
    '2026-12-29 17:15','2026-12-29 19:45','2026-12-30 17:15','2026-12-30 19:45','2026-12-30 22:30',
    '2026-12-31 17:15','2026-12-31 19:45','2026-12-31 22:15'
  ]) AS s(local_start)
  ON CONFLICT (calendar_id, start_at) DO NOTHING;
  PERFORM pg_temp.fh_rate(v_operator, v_canal, 'Adult (13+) Holiday', 'Adults', 'Ages 13+', 1, 6900, v_seats, 1, true, '577774:adult', NULL, NULL, 30, NULL);
  PERFORM pg_temp.fh_rate(v_operator, v_canal, 'Child (12 and under) Holiday', 'Children', 'Ages 12 and under', 1, 4500, v_seats, 1, true, '577774:child', NULL, NULL, 30, NULL);
  PERFORM pg_temp.fh_policy(v_operator, v_canal);

  -------------------------------------------------------------------------------
  -- The Oasis Tiki Boat – Private Christmas Canal Cruise (576786), Dec 2026,
  --   5:15 PM and 7:45 PM (55 of FareHarbor's 61 departures; see mapping doc).
  --   FareHarbor's 7-hour option uses 1 seat (a FareHarbor setup error); all
  --   lengths use the whole boat here.
  v_xmas := pg_temp.fh_calendar(v_operator, c_private, v_location, 'The Oasis Tiki Boat - Private Christmas Canal Cruise',
    'oasis-private-christmas-canal-cruise', 'Your Own Boat For Up To 30 Of Your Crew',
    'Private holiday-lights canal charter on The Oasis Tiki Boat for up to 30 guests. Choose 2 to 8 hours.',
    120, 150, 1, 30, '["Captain"]'::jsonb, 'date_wise');
  IF NOT EXISTS (SELECT 1 FROM public.calendar_date_hours WHERE calendar_id = v_xmas) THEN
    INSERT INTO public.calendar_date_hours (calendar_id, start_date, end_date, start_time, end_time)
    VALUES (v_xmas, '2026-12-01', '2026-12-31', '17:15', '21:45');
  END IF;
  FOR r IN SELECT * FROM (VALUES (2, 160000), (3, 180000), (4, 200000), (5, 225000), (6, 252000), (7, 280000), (8, 300000)) AS t(hours, price)
  LOOP
    PERFORM pg_temp.fh_rate(v_operator, v_xmas, format('Private Christmas Canal %s Hour', r.hours), format('Private Christmas Canal %s Hour', r.hours),
      format('Whole boat for %s hours, up to 30 guests', r.hours), 1, r.price, v_seats, 30, true,
      format('576786:private-%sh', r.hours), r.hours * 60, NULL, 1, NULL);
  END LOOP;
  PERFORM pg_temp.fh_policy(v_operator, v_xmas);

  -------------------------------------------------------------------------------
  -- Escape Room "Quest for the Fountain of Youth" (508393): daily 9, 11, 1, 3, 5, 7; 90 min.
  --   Outdoor game, no shared inventory; price per player depends on group size.
  v_escape := pg_temp.fh_calendar(v_operator, c_experience, v_location, 'Escape Room "Quest for the Fountain of Youth" outdoor game',
    'escape-room-fountain-of-youth', 'Outdoor adventure game along the Punta Gorda waterfront',
    'An outdoor escape game along the waterfront from Laishley Park to Gilchrist Park, about 1 mile long. Price per player depends on the size of your group.',
    90, 120, 7, 7, '["Guide"]'::jsonb, 'day_wise');
  INSERT INTO public.calendar_hours (calendar_id, day_of_week, start_time, end_time)
  SELECT v_escape, d, '09:00', '20:30' FROM generate_series(0, 6) AS d
  ON CONFLICT (calendar_id, day_of_week, start_time, end_time) DO NOTHING;
  PERFORM pg_temp.fh_rate(v_operator, v_escape, '1 - 2 Players', '1 - 2 Players', 'Price per player for groups of 1 or 2', 1, 2900, NULL, NULL, true, '508393:1-2', NULL, 1, 2, NULL);
  PERFORM pg_temp.fh_rate(v_operator, v_escape, '3 Players', '3 Players', 'Price per player for a group of 3', 1, 2500, NULL, NULL, true, '508393:3', NULL, 3, 3, NULL);
  PERFORM pg_temp.fh_rate(v_operator, v_escape, '4 - 7 Players', '4 - 7 Players', 'Price per player for groups of 4 to 7', 1, 2200, NULL, NULL, true, '508393:4-7', NULL, 4, 7, NULL);
  PERFORM pg_temp.fh_policy(v_operator, v_escape);

  -------------------------------------------------------------------------------
  -- FareHarbor closures and holidays
  INSERT INTO public.calendar_blocks (calendar_id, start_at, end_at, reason)
  SELECT b.calendar_id, b.s::timestamp AT TIME ZONE tz, b.e::timestamp AT TIME ZONE tz, b.reason
  FROM (VALUES
    (v_sunset,   '2026-11-29 00:00', '2026-11-30 00:00', 'Closed in FareHarbor'),
    (v_tropical, '2026-12-25 00:00', '2026-12-26 00:00', 'Christmas Day: no Tropical Tides departures in FareHarbor')
  ) AS b(calendar_id, s, e, reason)
  WHERE NOT EXISTS (SELECT 1 FROM public.calendar_blocks x
                    WHERE x.calendar_id = b.calendar_id AND x.start_at = (b.s::timestamp AT TIME ZONE tz));
END $$;

COMMIT;

-- VERIFY
-- select c.name, c.availability_mode, c.is_active, count(r.id) rates
--   from calendars c left join calendar_rates r on r.calendar_id = c.id and r.deleted_at is null
--  where c.operator_id = (select id from operators where slug = 'punta-gorda-adventures')
--  group by 1, 2, 3 order by 1;
