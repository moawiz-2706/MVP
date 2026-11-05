-- Calendar video and the staff booking guest-details QR link.
-- Additive and safe to re-run. Apply BEFORE deploying the code that needs it
-- (readiness marker 050).
--
-- 1. calendars.video_url: an optional YouTube, Vimeo or video-file link shown
--    on the public booking page next to the photos.
-- 2. public_access_credentials purpose 'party_details': the QR code on a staff
--    booking's confirmation opens a waiver-only page for the whole party.
--
-- Rollback (deploy the previous code first):
--   ALTER TABLE public.calendars DROP COLUMN IF EXISTS video_url;
--   DELETE FROM public.public_access_credentials WHERE purpose = 'party_details';
--   (then re-add public_access_purpose_valid without 'party_details')
--   DELETE FROM public.passport_schema_version WHERE version = '050_calendar_video';

BEGIN;

ALTER TABLE public.calendars ADD COLUMN IF NOT EXISTS video_url text;

ALTER TABLE public.public_access_credentials
  DROP CONSTRAINT IF EXISTS public_access_purpose_valid;
ALTER TABLE public.public_access_credentials
  ADD CONSTRAINT public_access_purpose_valid CHECK (
    purpose IN ('order_status','waiver_sign','waiver_view','waiver_view_sensitive','staff_booking','party_details')
  );

INSERT INTO public.passport_schema_version(version)
VALUES ('050_calendar_video')
ON CONFLICT (version) DO NOTHING;

COMMIT;
