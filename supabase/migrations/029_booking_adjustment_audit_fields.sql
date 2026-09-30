BEGIN;

ALTER TABLE booking_adjustments
  ADD COLUMN IF NOT EXISTS original_amount_minor bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS policy_version integer,
  ADD COLUMN IF NOT EXISTS stripe_reference text;

INSERT INTO passport_schema_version(version)
VALUES ('029_booking_adjustment_audit_fields')
ON CONFLICT (version) DO NOTHING;

COMMIT;
