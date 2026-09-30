BEGIN;

-- Migration 008 created the purpose check without an explicit name, so
-- PostgreSQL named it public_access_credentials_purpose_check. Migration 032
-- removed only the later named constraint, leaving this legacy check active on
-- databases that already existed when private staff links were deployed.
ALTER TABLE public_access_credentials
  DROP CONSTRAINT IF EXISTS public_access_credentials_purpose_check;
ALTER TABLE public_access_credentials
  DROP CONSTRAINT IF EXISTS public_access_purpose_valid;
ALTER TABLE public_access_credentials
  ADD CONSTRAINT public_access_purpose_valid CHECK (
    purpose IN ('order_status','waiver_sign','waiver_view','waiver_view_sensitive','staff_booking')
  );

INSERT INTO passport_schema_version(version)
VALUES ('033_fix_staff_booking_purpose_constraint')
ON CONFLICT (version) DO NOTHING;

COMMIT;
