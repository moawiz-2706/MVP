-- Staff PWA: brief grace window for the refresh nonce replaced by a rotation.
--
-- Two refreshes racing from one device (app resume plus a retried request,
-- two tabs) both present the same cookie. The first rotates the nonce; the
-- second used to be rejected and signed the staff member out. The replaced
-- digest is now kept with its rotation time: within a short window a racer gets
-- an access token without rotating again, and after it a device that lost the
-- rotation response recovers. Only SHA-256 digests are stored, as before.
--
-- Additive and safe to re-run. Apply after 041 and BEFORE deploying code
-- that expects these columns.
-- Rollback (deploy the previous code first):
--   ALTER TABLE public.pwa_sessions DROP COLUMN IF EXISTS previous_refresh_nonce_digest;
--   ALTER TABLE public.pwa_sessions DROP COLUMN IF EXISTS refresh_rotated_at;
--   DELETE FROM public.passport_schema_version WHERE version = '042_pwa_refresh_grace';

BEGIN;

ALTER TABLE public.pwa_sessions
  ADD COLUMN IF NOT EXISTS previous_refresh_nonce_digest varchar(128),
  ADD COLUMN IF NOT EXISTS refresh_rotated_at timestamptz;

INSERT INTO public.passport_schema_version(version)
VALUES ('042_pwa_refresh_grace')
ON CONFLICT (version) DO NOTHING;

COMMIT;
