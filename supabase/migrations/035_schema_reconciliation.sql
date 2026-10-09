BEGIN;

-- 035: reconcile the waiver token-digest column that was added by the
-- production-hardening migrations but was not previously populated or used by
-- the ORM/service lookup path.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE public.booking_waivers
  ADD COLUMN IF NOT EXISTS token_digest text;

UPDATE public.booking_waivers
SET token_digest = encode(digest(token, 'sha256'), 'hex')
WHERE token_digest IS NULL;

ALTER TABLE public.booking_waivers
  ALTER COLUMN token_digest SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_waivers_token_digest
  ON public.booking_waivers(token_digest);

INSERT INTO public.passport_schema_version(version)
VALUES ('035_schema_reconciliation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
