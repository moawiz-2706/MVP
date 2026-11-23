-- Connected-account payout split. Additive and safe to re-run.
-- Apply BEFORE deploying the code that needs it (readiness marker 052).
--
-- 1. operator_settings.payout_share_bps: the share of each included product's
--    ticket price (subtotal) transferred to the Stripe connected account,
--    in basis points (8000 = 80%). Booking fees and taxes always stay in the
--    main (platform) account.
-- 2. calendars.payout_included: whether a calendar's bookings are part of
--    the split. Excluded calendars keep 100% in the main account and do not
--    need a verified connected account to take payments.
--
-- Rollback (deploy the previous code first):
--   ALTER TABLE public.calendars DROP COLUMN IF EXISTS payout_included;
--   ALTER TABLE public.operator_settings DROP COLUMN IF EXISTS payout_share_bps;
--   DELETE FROM public.passport_schema_version WHERE version = '052_payout_split';

BEGIN;

ALTER TABLE public.operator_settings
  ADD COLUMN IF NOT EXISTS payout_share_bps integer NOT NULL DEFAULT 8000;
ALTER TABLE public.operator_settings
  DROP CONSTRAINT IF EXISTS operator_settings_payout_share_bps_check;
ALTER TABLE public.operator_settings
  ADD CONSTRAINT operator_settings_payout_share_bps_check
  CHECK (payout_share_bps BETWEEN 0 AND 10000);

ALTER TABLE public.calendars
  ADD COLUMN IF NOT EXISTS payout_included boolean NOT NULL DEFAULT true;

INSERT INTO public.passport_schema_version(version)
VALUES ('052_payout_split')
ON CONFLICT (version) DO NOTHING;

COMMIT;
