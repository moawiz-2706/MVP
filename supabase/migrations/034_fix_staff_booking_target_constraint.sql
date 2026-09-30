BEGIN;

-- Migration 021 created this constraint before staff-scoped credentials existed.
-- A staff booking link has staff_id and intentionally has no order_id or
-- booking_id, so the legacy two-column rule rejects it with HTTP 409.
ALTER TABLE public_access_credentials
  DROP CONSTRAINT IF EXISTS public_credentials_one_target;
ALTER TABLE public_access_credentials
  ADD CONSTRAINT public_credentials_one_target CHECK (
    num_nonnulls(order_id, booking_id, staff_id) = 1
  ) NOT VALID;

INSERT INTO passport_schema_version(version)
VALUES ('034_fix_staff_booking_target_constraint')
ON CONFLICT (version) DO NOTHING;

COMMIT;
