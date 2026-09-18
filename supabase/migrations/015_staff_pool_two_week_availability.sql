-- Calendar-specific required Passport staff pools. Existing calendars remain
-- Captain-only unless the owner selects additional pools in the calendar editor.
ALTER TABLE calendars
  ADD COLUMN IF NOT EXISTS required_staff_roles jsonb NOT NULL DEFAULT '["Captain"]'::jsonb;

-- Concrete availability intervals expanded from the GHL user schedules for the
-- rolling next-14-day window. Rows are replaced on every synchronization.
CREATE TABLE IF NOT EXISTS staff_availability_windows (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  staff_id uuid NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
  start_at timestamptz NOT NULL,
  end_at timestamptz NOT NULL,
  source_schedule_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_staff_availability_windows_time_order CHECK (start_at < end_at),
  CONSTRAINT uq_staff_availability_windows_staff_interval UNIQUE (staff_id, start_at, end_at)
);

CREATE INDEX IF NOT EXISTS ix_staff_availability_windows_staff_interval
  ON staff_availability_windows (staff_id, start_at, end_at);

DROP TRIGGER IF EXISTS trg_staff_availability_windows_updated_at ON staff_availability_windows;
CREATE TRIGGER trg_staff_availability_windows_updated_at
  BEFORE UPDATE ON staff_availability_windows
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
