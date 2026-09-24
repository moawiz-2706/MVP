BEGIN;

ALTER TABLE calendars
  ADD COLUMN IF NOT EXISTS public_booking_mode text NOT NULL DEFAULT 'online',
  ADD COLUMN IF NOT EXISTS booking_cutoff_minutes integer,
  ADD COLUMN IF NOT EXISTS call_to_book_phone text;
ALTER TABLE calendars
  DROP CONSTRAINT IF EXISTS ck_calendars_public_booking_mode,
  DROP CONSTRAINT IF EXISTS ck_calendars_booking_cutoff;
ALTER TABLE calendars
  ADD CONSTRAINT ck_calendars_public_booking_mode
    CHECK (public_booking_mode IN ('online','call_to_book','closed')),
  ADD CONSTRAINT ck_calendars_booking_cutoff
    CHECK (booking_cutoff_minutes IS NULL OR booking_cutoff_minutes >= 0);

COMMIT;
