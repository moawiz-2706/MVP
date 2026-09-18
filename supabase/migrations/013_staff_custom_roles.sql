-- Passport-owned custom staff type used for local booking eligibility.
-- GHL identity, permissions, and profile fields remain managed by GHL.
ALTER TABLE staff
  ADD COLUMN IF NOT EXISTS custom_role text;

CREATE INDEX IF NOT EXISTS ix_staff_operator_custom_role
  ON staff(operator_id, custom_role)
  WHERE deleted_at IS NULL;
