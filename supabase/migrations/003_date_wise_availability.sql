-- Calendars operate in exactly one availability mode:
--   day_wise  -> recurring weekly hours (calendar_hours)
--   date_wise -> explicit date ranges with their own time intervals
-- The inactive mode's rows are retained but ignored by the availability engine.

ALTER TABLE calendars
  ADD COLUMN availability_mode text NOT NULL DEFAULT 'day_wise';

ALTER TABLE calendars
  ADD CONSTRAINT ck_calendars_availability_mode
  CHECK (availability_mode IN ('day_wise', 'date_wise'));

-- One row per (date range, time interval). A range with several opening
-- intervals repeats the same start_date/end_date, mirroring calendar_hours.
CREATE TABLE calendar_date_hours (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  calendar_id uuid NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
  start_date date NOT NULL,
  end_date date NOT NULL,
  start_time time NOT NULL,
  end_time time NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_calendar_date_hours_date_order CHECK (start_date <= end_date),
  CONSTRAINT ck_calendar_date_hours_time_order CHECK (start_time < end_time)
);

CREATE INDEX ix_calendar_date_hours_calendar_range
  ON calendar_date_hours (calendar_id, start_date, end_date);
