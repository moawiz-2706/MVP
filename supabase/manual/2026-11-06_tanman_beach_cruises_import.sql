-- FareHarbor (TanMan Charters FL) → Passport: beach cruises (2026-11-06)
--
-- Source: FareHarbor company "tanmanfl", read from the dashboard on 2026-11-06.
--   574255 Boca Grande Sandbar Cruise      daily 9:30 AM
--   575096 Cayo Costa State Park Cruise    daily 10:00 AM
--   575726 Cabbage Key Cruise              daily 10:00 AM
--   575940 Tanman Charters - Custom        private in FareHarbor, $0 → call to book
-- All four use Captain Patrick's Grady-White 255 (one boat, up to 6 guests),
-- depart Laishley Park Marina (120 Laishley Ct, Punta Gorda) and last up to
-- 5 hours. Prices (FareHarbor, 0% tax): 4 Hour Charter $700, 5 Hour Charter $800.
-- Cancellation: full refund up to 12 hours before; weather = full refund.
--
-- The three cruises share the one boat, so a booking on any of them blocks the
-- others at an overlapping time, exactly like the FareHarbor resource.
--
-- SAFETY
--   * Every calendar is created INACTIVE and not publicly bookable. In
--     FareHarbor every TanMan departure is currently CLOSED (FareHarbor closed
--     them on 26 Jun 2026), so nothing is sold until an admin reviews and
--     activates them in Passport → Calendars.
--   * Idempotent and additive: rows are matched by name/slug; re-running adds
--     nothing and no existing row is changed.
--   * Photos are not set here. Add them in Passport → Calendars → Edit →
--     Photos (paste the FareHarbor links listed at the end; Passport copies
--     each one into HighLevel Media Storage).
--
-- Rollback (only while nothing has been booked on them): delete the four
-- calendars in Passport → Calendars.

BEGIN;

DO $$
DECLARE
  v_operator uuid;
  v_location uuid;
  v_category uuid;
  v_boat uuid;
  v_cal uuid;
  v_ct uuid;
  v_rate uuid;
  c record;
  r record;
BEGIN
  SELECT id INTO v_operator FROM public.operators WHERE slug = 'punta-gorda-adventures';
  IF v_operator IS NULL THEN
    RAISE EXCEPTION 'Operator punta-gorda-adventures not found';
  END IF;

  SELECT id INTO v_location FROM public.departure_locations
  WHERE operator_id = v_operator AND name = 'Laishley Park Marina Public Dock' AND deleted_at IS NULL;
  IF v_location IS NULL THEN
    RAISE EXCEPTION 'Departure location Laishley Park Marina Public Dock not found';
  END IF;

  INSERT INTO public.resources (operator_id, name, quantity, resource_type, notes, is_active)
  SELECT v_operator, 'Grady-White 255 (TanMan)', 1, 'vessel',
         'FareHarbor TanMan Charters resource "Grady-White 255"; Captain Patrick; up to 6 guests.', true
  WHERE NOT EXISTS (SELECT 1 FROM public.resources
                    WHERE operator_id = v_operator AND name = 'Grady-White 255 (TanMan)' AND deleted_at IS NULL);
  SELECT id INTO v_boat FROM public.resources
  WHERE operator_id = v_operator AND name = 'Grady-White 255 (TanMan)' AND deleted_at IS NULL;

  INSERT INTO public.calendar_categories (operator_id, name, slug, display_color, sort_order)
  SELECT v_operator, 'Beach Tours', 'beach-tours', '#d97706', 30
  WHERE NOT EXISTS (SELECT 1 FROM public.calendar_categories
                    WHERE operator_id = v_operator AND slug = 'beach-tours' AND deleted_at IS NULL);
  SELECT id INTO v_category FROM public.calendar_categories
  WHERE operator_id = v_operator AND slug = 'beach-tours' AND deleted_at IS NULL;

  FOR r IN SELECT * FROM (VALUES
      ('Beach Charter 4 Hour', 'Beach Charters 4 Hour', 'Whole boat for up to 6 guests, 4 hours', 'tanmanfl:4-hour-charter'),
      ('Beach Charter 5 Hour', 'Beach Charters 5 Hour', 'Whole boat for up to 6 guests, 5 hours', 'tanmanfl:5-hour-charter')
    ) AS t(name, plural, note, fh_key)
  LOOP
    INSERT INTO public.customer_types (operator_id, name, plural_name, note, seat_count, external_provider, external_id, is_active)
    SELECT v_operator, r.name, r.plural, r.note, 1, 'fareharbor', r.fh_key, true
    WHERE NOT EXISTS (SELECT 1 FROM public.customer_types
                      WHERE operator_id = v_operator AND name = r.name AND deleted_at IS NULL);
  END LOOP;

  FOR c IN SELECT * FROM (VALUES
      ('574255', 'Boca Grande Sandbar Cruise', 'boca-grande-sandbar-cruise', time '09:30', 'online', NULL,
       'Cruise the harbor, sand and snorkeling',
       E'Welcome aboard Captain Patrick''s Grady-White 255 Freedom (26 feet). Take in scenic coastal views as you relax on the way to the Boca Grande Sandbar. Chill under the shade or soak up the Florida sun at the bow; the boat is perfectly spacious for 6 guests.\n\nTrip details: a 45-minute boat ride through the scenic coastal waters of Charlotte Harbor to the Boca Grande Sandbar, one of Florida''s most beloved destinations and home to the annual H2O fest and the old railroad tracks.\n\nWhat you can do at the sandbar:\n- Wiggle your toes in the sand, soak up the sun and hunt for shells: sand dollars, conchs and exotic shells are abundant.\n- Snorkel in the aqua-blue Gulf water and see conch shells, lightning whelks, crabs and the occasional manatee or dolphin.\n- Have a photoshoot at the historic railroad tracks, built in 1907. Captain Patrick is great at capturing moments you''ll cherish for years.'),
      ('575096', 'Cayo Costa State Park Cruise', 'cayo-costa-state-park-cruise', time '10:00', 'online', NULL,
       'Sunshine, Sand, And Shelling',
       E'Encounter 9 miles of untouched white sandy beaches. Hang a shell on the famous "Shell Tree" while wiggling your toes in the sand. Find sand dollars and Florida fighting conch, to name a few. Sunning, shelling and beach walks are highly recommended. Guests disembark on the beach and enjoy the warm, welcoming island.\n\nCaptain Patrick is great at capturing magical moments for you to cherish for years to come.'),
      ('575726', 'Cabbage Key Cruise', 'cabbage-key-cruise', time '10:00', 'online', NULL,
       'Manatees, Gopher Tortoises, and a "Cheeseburger In Paradise"',
       E'Go back in time as we dock at the original boat house, circa 1939. Look out for manatees and gopher tortoises, which are often seen. Grab a hibiscus flower and feed the gopher tortoises (named after the Ninja Turtles) when available.\n\nFeel the warm atmosphere of the iconic restaurant with thousands of $1 bills on the ceiling and walls. Jimmy Buffett stayed here for a week in 1985, and Cabbage Key inspired his famous "Cheeseburger in Paradise".\n\nExplore the island''s gift shop, play cornhole or basketball, dive into Cabbage Key''s rich history and hike the rolling hills with breathtaking coastal views.'),
      ('575940', 'TanMan Charters - Custom', 'tanman-charters-custom', time '10:00', 'call_to_book', '(941) 336-3252',
       'Custom Charter: Cabbage Key, Cayo Costa, Boca Grande',
       E'Interested in snorkeling or shelling at Cayo Costa, lunch at Cabbage Key or a lazy day at the Boca Grande sandbar? Talk with Captain Patrick at (941) 336-3252 to customise your tour. Up to 5 hours, up to 6 guests.')
    ) AS t(fh_pk, name, slug, start_time, mode, phone, headline, description)
  LOOP
    INSERT INTO public.calendars (
      operator_id, calendar_category_id, departure_location_id, name, slug, headline, description,
      booking_instructions, is_active, public_booking_enabled, duration_minutes, slot_interval_minutes,
      max_units_per_booking, base_price_minor, currency, availability_mode, required_staff_roles,
      public_booking_mode, call_to_book_phone, tax_bps, booking_fee_bps, maximum_party_size,
      booking_cutoff_minutes
    )
    SELECT v_operator, v_category, v_location, c.name, c.slug, c.headline, c.description,
           'Meet Captain Patrick at Laishley Park Marina, 120 Laishley Ct, Punta Gorda, FL 33950. Bring sunscreen, towels and water.',
           false, false, 300, 300, 1, 70000, 'usd', 'day_wise', '[]'::jsonb,
           c.mode, c.phone, 0, 0, 6, 720
    WHERE NOT EXISTS (SELECT 1 FROM public.calendars
                      WHERE operator_id = v_operator AND slug = c.slug AND deleted_at IS NULL);
    SELECT id INTO v_cal FROM public.calendars
    WHERE operator_id = v_operator AND slug = c.slug AND deleted_at IS NULL;

    -- One departure a day: the window fits exactly one 5-hour start.
    INSERT INTO public.calendar_hours (calendar_id, day_of_week, start_time, end_time)
    SELECT v_cal, d, c.start_time, c.start_time + interval '5 hours' FROM generate_series(0, 6) AS d
    ON CONFLICT (calendar_id, day_of_week, start_time, end_time) DO NOTHING;

    -- Rates: the whole boat, 4 or 5 hours. The custom charter is quoted by phone.
    IF c.mode = 'online' THEN
      FOR r IN SELECT * FROM (VALUES
          ('Beach Charter 4 Hour', 70000, 240, 'tanmanfl:' || c.fh_pk || ':4-hour'),
          ('Beach Charter 5 Hour', 80000, 300, 'tanmanfl:' || c.fh_pk || ':5-hour')
        ) AS t(name, price, minutes, fh_key)
      LOOP
        SELECT id INTO v_ct FROM public.customer_types
        WHERE operator_id = v_operator AND name = r.name AND deleted_at IS NULL;
        INSERT INTO public.calendar_rates (operator_id, calendar_id, customer_type_id, name_snapshot, note_snapshot,
                                           price_minor, booking_fee_bps, tax_bps, is_tax_inclusive, is_fee_inclusive,
                                           external_provider, external_id, is_active, duration_minutes,
                                           max_units_per_booking)
        VALUES (v_operator, v_cal, v_ct, r.name, 'Whole boat for up to 6 guests', r.price, 0, 0, false, false,
                'fareharbor', r.fh_key, true, r.minutes, 1)
        ON CONFLICT (calendar_id, customer_type_id) DO NOTHING;
        SELECT id INTO v_rate FROM public.calendar_rates WHERE calendar_id = v_cal AND customer_type_id = v_ct;

        INSERT INTO public.calendar_rate_resources (rate_id, resource_id, quantity_per_unit)
        SELECT v_rate, v_boat, 1
        WHERE NOT EXISTS (SELECT 1 FROM public.calendar_rate_resources WHERE rate_id = v_rate AND resource_id = v_boat);
      END LOOP;
    END IF;

    -- FareHarbor's "Souls" question: how many people are coming (1-6).
    INSERT INTO public.booking_custom_field_definitions (operator_id, calendar_id, key, label, field_type, required, options, active)
    SELECT v_operator, v_cal, 'party_size', 'How many people will be in your party?', 'select', true,
           '["1","2","3","4","5","6"]'::jsonb, true
    WHERE NOT EXISTS (SELECT 1 FROM public.booking_custom_field_definitions
                      WHERE operator_id = v_operator AND calendar_id = v_cal AND key = 'party_size');

    -- Full refund up to 12 hours before; weather cancellations fully refunded.
    INSERT INTO public.calendar_booking_policies (operator_id, calendar_id, version, cancellation_cutoff_minutes,
                                                  cancellation_fee_bps, weather_refund_mode, active)
    VALUES (v_operator, v_cal, 1, 720, 0, 'full_refund', true)
    ON CONFLICT (calendar_id, version) DO NOTHING;
  END LOOP;
END $$;

COMMIT;

-- VERIFY
-- select c.name, c.is_active, c.public_booking_mode, r.name_snapshot, r.price_minor, r.duration_minutes
--   from calendars c left join calendar_rates r on r.calendar_id = c.id
--  where c.slug in ('boca-grande-sandbar-cruise','cayo-costa-state-park-cruise','cabbage-key-cruise','tanman-charters-custom')
--  order by 1, 5;

-- PHOTOS (FareHarbor links; paste each calendar's list into Calendars → Edit → Photos)
-- Boca Grande Sandbar Cruise:
--   https://cdn.filestackcontent.com/iQUAMLZ2SC6MQ4CZmvzQ https://cdn.filestackcontent.com/vpXve5R665zCZHJ6tzMQ
--   https://cdn.filestackcontent.com/EA1ascGXTSOvRiIVEeyA https://cdn.filestackcontent.com/pBOQnh4LT0GktjPpnKKm
--   https://cdn.filestackcontent.com/D915LO2kTuS1FZY1pQdD
-- Cayo Costa State Park Cruise:
--   https://cdn.filestackcontent.com/NbmCim8QQDe3QI75KpHw https://cdn.filestackcontent.com/lv8hsDmHSja2qGzHKat6
--   https://cdn.filestackcontent.com/05siDVOWQyaInQOFChu6 https://cdn.filestackcontent.com/ybLHOCqSJ2nHGsa8d5pg
--   https://cdn.filestackcontent.com/y26hR8njRJG20m2vRVSh https://cdn.filestackcontent.com/OJIfN7txSMGHOIGWDcRR
-- Cabbage Key Cruise:
--   https://cdn.filestackcontent.com/nc3D61EFQAqDulwKkTUG https://cdn.filestackcontent.com/SRiWEe5cTWyosOQLJwYl
--   https://cdn.filestackcontent.com/SwDYAOsTSHmlKUnm7Ojw https://cdn.filestackcontent.com/TH3AUqXTRxGJABqdxmBO
--   https://cdn.filestackcontent.com/QNpuTr5sTPmCbZApZhLt https://cdn.filestackcontent.com/VLkdXJxdQGp6QVs3memM
-- TanMan Charters - Custom:
--   https://cdn.filestackcontent.com/g6KGHKFSRMKFiwstMczQ https://cdn.filestackcontent.com/oumUElQT3u5kfNCs5EOB
--   https://cdn.filestackcontent.com/5oBynzSGWlTpu87l7XJw https://cdn.filestackcontent.com/GBOfoYVSoOgMlzBvUqew
--   https://cdn.filestackcontent.com/Ili89fiqSQKW1Vf0tNV0 https://cdn.filestackcontent.com/Q5k7ilQkQrmcNx45PZa0
