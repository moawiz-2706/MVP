-- SUPERSEDED by 2026-11-03_fareharbor_catalog_import_v2.sql (run that instead; it
-- also upgrades databases where this batch already ran).
--
-- FareHarbor → Passport catalogue import, batch 1 (2026-11-03)
--
-- Source: MVP_FAREHARBOR_VISIBLE_INVENTORY_2026-11-03.csv, mapped in
-- docs/integrations/fareharbor/CATALOG_MAPPING.md. Only fully specified data
-- is imported:
--   * all 7 FareHarbor resources (boats and seat pools)
--   * the Laishley Park Marina departure location
--   * "The Oasis" BYOB Sunset Cruise – Public  (FareHarbor item 502154)
--   * The Oasis Tiki Boat – Private Cruise, 2 hours (FareHarbor item 508627)
-- Both calendars share The Oasis Tiki Seats (30): a public guest takes 1 seat,
-- a private charter takes all 30, so a charter blocks the overlapping public
-- departure exactly as in FareHarbor.
--
-- SAFETY
--   * Calendars are created INACTIVE and not publicly bookable. Nothing is
--     sold and no HighLevel calendar is created until an admin reviews and
--     activates them in Passport → Calendars.
--   * Idempotent: every row is matched by name/slug; re-running adds nothing.
--   * Additive only: no existing row is updated or deleted.
--   * Prices are in cents; 7% tax is added on top (FareHarbor shows tax extra).
--
-- CONFIRM BEFORE ACTIVATING (see CATALOG_MAPPING.md "Decisions"):
--   * Sunset cruise duration: set to 120 minutes as a placeholder.
--   * December-only rates are created INACTIVE (Passport rates have no
--     date range); switch them on for December and off afterwards.
--
-- Rollback (only while nothing has been booked on the new calendars):
--   delete the two calendars in Passport → Calendars (they are deleted
--   outright when they have no bookings).

BEGIN;

DO $$
DECLARE
  v_operator uuid;
  v_location uuid;
  v_public_cat uuid;
  v_private_cat uuid;
  v_oasis_seats uuid;
  v_sunset uuid;
  v_private2 uuid;
  v_ct uuid;
  v_rate uuid;
  r record;
BEGIN
  SELECT id INTO v_operator FROM public.operators WHERE slug = 'punta-gorda-adventures';
  IF v_operator IS NULL THEN
    RAISE EXCEPTION 'Operator punta-gorda-adventures not found';
  END IF;

  -- Resources (FareHarbor Settings → Resources)
  FOR r IN SELECT * FROM (VALUES
      ('Motor Yacht 55ft', 1, 'vessel', 'FareHarbor resource; max uses 1.'),
      ('SV Sea Dancer Seats', 6, 'seat', 'FareHarbor resource; max uses 6; restricted to same availability.'),
      ('S/V Courageous Seats', 6, 'seat', 'FareHarbor resource; max uses 6; restricted to same availability.'),
      ('The Oasis Tiki Seats', 30, 'seat', 'FareHarbor resource; max uses 30. Public guest = 1 seat; private charter = 30 seats.'),
      ('37ft Hunter', 1, 'vessel', 'FareHarbor resource; max uses 1.'),
      ('41ft Morgan', 1, 'vessel', 'FareHarbor resource; max uses 1.'),
      ('Carver 52ft MY', 1, 'vessel', 'FareHarbor resource; max uses 1.')
    ) AS t(name, quantity, kind, notes)
  LOOP
    INSERT INTO public.resources (operator_id, name, quantity, resource_type, notes, is_active)
    SELECT v_operator, r.name, r.quantity, r.kind, r.notes, true
    WHERE NOT EXISTS (
      SELECT 1 FROM public.resources
      WHERE operator_id = v_operator AND name = r.name AND deleted_at IS NULL
    );
  END LOOP;
  SELECT id INTO v_oasis_seats FROM public.resources
  WHERE operator_id = v_operator AND name = 'The Oasis Tiki Seats' AND deleted_at IS NULL;

  -- Departure location (FareHarbor location 94346)
  INSERT INTO public.departure_locations (operator_id, name, address, is_active)
  SELECT v_operator, 'Laishley Park Marina Public Dock', '120 Laishley Ct, Punta Gorda, FL 33950', true
  WHERE NOT EXISTS (
    SELECT 1 FROM public.departure_locations
    WHERE operator_id = v_operator AND name = 'Laishley Park Marina Public Dock' AND deleted_at IS NULL
  );
  SELECT id INTO v_location FROM public.departure_locations
  WHERE operator_id = v_operator AND name = 'Laishley Park Marina Public Dock' AND deleted_at IS NULL;

  -- Categories (display grouping only; inventory is the shared resource)
  INSERT INTO public.calendar_categories (operator_id, name, slug, display_color, sort_order)
  SELECT v_operator, 'Public Cruises', 'public-cruises', '#1b7f6c', 10
  WHERE NOT EXISTS (SELECT 1 FROM public.calendar_categories
                    WHERE operator_id = v_operator AND slug = 'public-cruises' AND deleted_at IS NULL);
  INSERT INTO public.calendar_categories (operator_id, name, slug, display_color, sort_order)
  SELECT v_operator, 'Private Charters', 'private-charters', '#3b6fd8', 20
  WHERE NOT EXISTS (SELECT 1 FROM public.calendar_categories
                    WHERE operator_id = v_operator AND slug = 'private-charters' AND deleted_at IS NULL);
  SELECT id INTO v_public_cat FROM public.calendar_categories
  WHERE operator_id = v_operator AND slug = 'public-cruises' AND deleted_at IS NULL;
  SELECT id INTO v_private_cat FROM public.calendar_categories
  WHERE operator_id = v_operator AND slug = 'private-charters' AND deleted_at IS NULL;

  -- Calendar: "The Oasis" BYOB Sunset Cruise – Public, daily 4:30 PM
  INSERT INTO public.calendars (
    operator_id, calendar_category_id, departure_location_id, name, slug, headline, description,
    is_active, public_booking_enabled, duration_minutes, slot_interval_minutes, max_units_per_booking,
    base_price_minor, currency, availability_mode, required_staff_roles, public_booking_mode,
    tax_bps, maximum_party_size
  )
  SELECT v_operator, v_public_cat, v_location, '"The Oasis" BYOB Sunset Cruise - Public', 'oasis-sunset-cruise-public',
         'Dolphin Sightings - Island Tunes - Private Restroom - Punta Gorda''s #1 Attraction',
         'Public BYOB sunset cruise on The Oasis Tiki Boat. Departs Laishley Park Marina Public Dock.',
         false, false, 120, 120, 30, 5900, 'usd', 'day_wise', '[]'::jsonb, 'online', 700, 30
  WHERE NOT EXISTS (SELECT 1 FROM public.calendars
                    WHERE operator_id = v_operator AND slug = 'oasis-sunset-cruise-public' AND deleted_at IS NULL);
  SELECT id INTO v_sunset FROM public.calendars
  WHERE operator_id = v_operator AND slug = 'oasis-sunset-cruise-public' AND deleted_at IS NULL;

  -- One 4:30 PM departure per day: the window fits exactly one start.
  INSERT INTO public.calendar_hours (calendar_id, day_of_week, start_time, end_time)
  SELECT v_sunset, d, time '16:30', time '18:30' FROM generate_series(0, 6) AS d
  ON CONFLICT (calendar_id, day_of_week, start_time, end_time) DO NOTHING;

  -- Calendar: The Oasis Tiki Boat – Private Cruise (2 hours)
  INSERT INTO public.calendars (
    operator_id, calendar_category_id, departure_location_id, name, slug, headline, description,
    is_active, public_booking_enabled, duration_minutes, slot_interval_minutes, max_units_per_booking,
    base_price_minor, currency, availability_mode, required_staff_roles, public_booking_mode,
    tax_bps, maximum_party_size
  )
  SELECT v_operator, v_private_cat, v_location, 'The Oasis Tiki Boat - Private Cruise (2 Hours)', 'oasis-private-cruise-2h',
         'Your Own Boat For Up To 30 Of Your Crew',
         'Private charter of The Oasis Tiki Boat for up to 30 guests. Split parties are not allowed.',
         false, false, 120, 150, 1, 160000, 'usd', 'day_wise', '[]'::jsonb, 'online', 700, 1
  WHERE NOT EXISTS (SELECT 1 FROM public.calendars
                    WHERE operator_id = v_operator AND slug = 'oasis-private-cruise-2h' AND deleted_at IS NULL);
  SELECT id INTO v_private2 FROM public.calendars
  WHERE operator_id = v_operator AND slug = 'oasis-private-cruise-2h' AND deleted_at IS NULL;

  -- 10:00, 12:30, 3:00, 5:30 and 8:00 PM: a 10:00–22:00 window stepped every 150 min.
  INSERT INTO public.calendar_hours (calendar_id, day_of_week, start_time, end_time)
  SELECT v_private2, d, time '10:00', time '22:00' FROM generate_series(0, 6) AS d
  ON CONFLICT (calendar_id, day_of_week, start_time, end_time) DO NOTHING;

  -- Customer types and rates. Each rate uses The Oasis Tiki Seats.
  FOR r IN SELECT * FROM (VALUES
      -- calendar, customer type, plural, note, seats, price (cents), seats used, active, FareHarbor rate key
      (v_sunset,   'Adult (13+)',              'Adults (13+)',              'Ages 13 and up',                 1,   5900,  1, true,  '502154:adult'),
      (v_sunset,   'Child (12 and under)',     'Children (12 and under)',   'Ages 12 and under',              1,   3500,  1, true,  '502154:child'),
      (v_sunset,   'Adult (December only)',    'Adults (December only)',    'December pricing, ages 13+',     1,   6900,  1, false, '502154:adult-december'),
      (v_sunset,   'Child (December only)',    'Children (December only)',  'December pricing, ages 12-',     1,   4500,  1, false, '502154:child-december'),
      (v_private2, 'Private Oasis 2 Hour',     'Private Oasis 2 Hour',      'Whole boat, up to 30 guests',    1, 160000, 30, true,  '508627:private-2h')
    ) AS t(calendar_id, name, plural, note, seats, price, seats_used, active, fh_key)
  LOOP
    INSERT INTO public.customer_types (operator_id, name, plural_name, note, seat_count, external_provider, external_id, is_active)
    SELECT v_operator, r.name, r.plural, r.note, r.seats, 'fareharbor', r.fh_key, true
    WHERE NOT EXISTS (SELECT 1 FROM public.customer_types
                      WHERE operator_id = v_operator AND name = r.name AND deleted_at IS NULL);
    SELECT id INTO v_ct FROM public.customer_types
    WHERE operator_id = v_operator AND name = r.name AND deleted_at IS NULL;

    INSERT INTO public.calendar_rates (operator_id, calendar_id, customer_type_id, name_snapshot, note_snapshot,
                                       price_minor, booking_fee_bps, tax_bps, is_tax_inclusive, is_fee_inclusive,
                                       external_provider, external_id, is_active)
    VALUES (v_operator, r.calendar_id, v_ct, r.name, r.note, r.price, 0, 700, false, false,
            'fareharbor', r.fh_key, r.active)
    ON CONFLICT (calendar_id, customer_type_id) DO NOTHING;
    SELECT id INTO v_rate FROM public.calendar_rates
    WHERE calendar_id = r.calendar_id AND customer_type_id = v_ct;

    INSERT INTO public.calendar_rate_resources (rate_id, resource_id, quantity_per_unit)
    SELECT v_rate, v_oasis_seats, r.seats_used
    WHERE NOT EXISTS (SELECT 1 FROM public.calendar_rate_resources
                      WHERE rate_id = v_rate AND resource_id = v_oasis_seats);
  END LOOP;

  -- Cancellation policy (FareHarbor account default): full refund when
  -- cancelled more than 48 hours before departure.
  INSERT INTO public.calendar_booking_policies (operator_id, calendar_id, version, cancellation_cutoff_minutes,
                                                cancellation_fee_bps, weather_refund_mode, active)
  SELECT v_operator, c, 1, 2880, 0, 'full_refund', true FROM unnest(ARRAY[v_sunset, v_private2]) AS c
  ON CONFLICT (calendar_id, version) DO NOTHING;
END $$;

COMMIT;

-- VERIFY
-- select name, is_active, duration_minutes from calendars where slug in ('oasis-sunset-cruise-public','oasis-private-cruise-2h');
-- select c.slug, r.name_snapshot, r.price_minor, r.is_active, rr.quantity_per_unit
--   from calendar_rates r join calendars c on c.id = r.calendar_id
--   join calendar_rate_resources rr on rr.rate_id = r.id
--  where c.slug like 'oasis-%' order by 1, 3;
