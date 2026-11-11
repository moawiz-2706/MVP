-- Allow guests added by a signed waiver (booking_participants.source = 'waiver').
-- The waiver code records everyone named on a signed waiver with source
-- 'waiver', but the check constraint only allowed checkout/operator/import,
-- so every waiver signing failed (HTTP 500) when it saved the signer.
-- Additive and safe to re-run. No code change is needed to apply it.
--
-- Rollback (only while no row uses 'waiver'):
--   ALTER TABLE public.booking_participants DROP CONSTRAINT booking_participants_source_check;
--   ALTER TABLE public.booking_participants ADD CONSTRAINT booking_participants_source_check
--     CHECK (source IN ('checkout','operator','import'));

BEGIN;

ALTER TABLE public.booking_participants
  DROP CONSTRAINT IF EXISTS booking_participants_source_check;
ALTER TABLE public.booking_participants
  ADD CONSTRAINT booking_participants_source_check
  CHECK (source IN ('checkout', 'operator', 'import', 'waiver'));

INSERT INTO public.passport_schema_version(version)
VALUES ('051_participant_source_waiver')
ON CONFLICT (version) DO NOTHING;

COMMIT;
