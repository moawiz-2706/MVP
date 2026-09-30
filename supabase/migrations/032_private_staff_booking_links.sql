BEGIN;

ALTER TABLE public_access_credentials
  ADD COLUMN IF NOT EXISTS staff_id uuid REFERENCES staff(id) ON DELETE CASCADE;

ALTER TABLE public_access_credentials
  DROP CONSTRAINT IF EXISTS public_access_purpose_valid;
ALTER TABLE public_access_credentials
  ADD CONSTRAINT public_access_purpose_valid CHECK (
    purpose IN ('order_status','waiver_sign','waiver_view','waiver_view_sensitive','staff_booking')
  );

ALTER TABLE public_access_credentials
  DROP CONSTRAINT IF EXISTS public_access_resource_check;
ALTER TABLE public_access_credentials
  ADD CONSTRAINT public_access_resource_check CHECK (
    order_id IS NOT NULL OR booking_id IS NOT NULL OR staff_id IS NOT NULL
  );

CREATE INDEX IF NOT EXISTS ix_public_access_credentials_staff
  ON public_access_credentials(staff_id, purpose, revoked_at, expires_at)
  WHERE staff_id IS NOT NULL;

INSERT INTO passport_schema_version(version)
VALUES ('032_private_staff_booking_links')
ON CONFLICT (version) DO NOTHING;

COMMIT;
