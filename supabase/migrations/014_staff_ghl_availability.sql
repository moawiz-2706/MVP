-- StaffHour remains Passport's cached copy of the schedule returned by GHL.
-- Passport never edits these values from the Staff page.
ALTER TABLE staff
  ADD COLUMN IF NOT EXISTS availability_time_zone text,
  ADD COLUMN IF NOT EXISTS availability_sync_status text NOT NULL DEFAULT 'not_requested',
  ADD COLUMN IF NOT EXISTS availability_last_error text,
  ADD COLUMN IF NOT EXISTS availability_last_synced_at timestamptz;
