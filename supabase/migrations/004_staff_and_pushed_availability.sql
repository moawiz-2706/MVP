-- 1) Push availability: a third, exclusive availability mode.
--    pushed -> only explicitly pushed start instants are bookable; the end is
--              start + calendars.duration_minutes and slot_interval_minutes is
--              ignored. Blocks and resource consumption apply unchanged.

ALTER TABLE calendars DROP CONSTRAINT IF EXISTS ck_calendars_availability_mode;
ALTER TABLE calendars
  ADD CONSTRAINT ck_calendars_availability_mode
  CHECK (availability_mode IN ('day_wise', 'date_wise', 'pushed'));

CREATE TABLE calendar_pushed_slots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  calendar_id uuid NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
  start_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_calendar_pushed_slots_calendar_id UNIQUE (calendar_id, start_at)
);

-- 2) Staff with their own weekly working hours, assigned to calendar time slots.

CREATE TABLE staff (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  name text NOT NULL,
  email text,
  phone text,
  is_active boolean NOT NULL DEFAULT true,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_staff_operator_id ON staff(operator_id);

-- Operator-local wall time, like calendar_hours. Several rows per weekday
-- give a split working day.
CREATE TABLE staff_hours (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  staff_id uuid NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
  day_of_week smallint NOT NULL,
  start_time time NOT NULL,
  end_time time NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_staff_hours_weekday_range CHECK (day_of_week BETWEEN 0 AND 6),
  CONSTRAINT ck_staff_hours_time_order CHECK (start_time < end_time),
  CONSTRAINT uq_staff_hours_staff_id UNIQUE (staff_id, day_of_week, start_time, end_time)
);

-- A staff member is busy for [start_at, end_at) of the slot they are assigned
-- to. Overlap is rejected in the service while the staff row is locked
-- FOR UPDATE, mirroring how resource inventory is serialized.
CREATE TABLE staff_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES operators(id),
  staff_id uuid NOT NULL REFERENCES staff(id),
  calendar_id uuid NOT NULL REFERENCES calendars(id),
  start_at timestamptz NOT NULL,
  end_at timestamptz NOT NULL,
  role text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_staff_assignments_time_order CHECK (start_at < end_at)
);

CREATE INDEX ix_staff_assignments_staff_interval ON staff_assignments(staff_id, start_at, end_at);
CREATE INDEX ix_staff_assignments_operator_interval ON staff_assignments(operator_id, start_at, end_at);

CREATE OR REPLACE FUNCTION enforce_staff_assignment_tenant()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM staff s JOIN calendars c ON c.id = NEW.calendar_id
    WHERE s.id = NEW.staff_id
      AND s.operator_id = NEW.operator_id
      AND c.operator_id = NEW.operator_id
  ) THEN
    RAISE EXCEPTION 'staff, calendar, and assignment must share an operator';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_staff_assignment_tenant
BEFORE INSERT OR UPDATE ON staff_assignments
FOR EACH ROW EXECUTE FUNCTION enforce_staff_assignment_tenant();

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'calendar_pushed_slots','staff','staff_hours','staff_assignments'
  ] LOOP
    EXECUTE format(
      'CREATE TRIGGER trg_%I_updated_at BEFORE UPDATE ON %I '
      'FOR EACH ROW EXECUTE FUNCTION set_updated_at()', table_name, table_name
    );
  END LOOP;
END;
$$;
