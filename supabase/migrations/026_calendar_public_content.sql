BEGIN;

-- FareHarbor-style public item content. URLs are intentionally stored rather than
-- binaries so the application can use Supabase Storage, a CDN, or an existing
-- media host without coupling booking logic to a provider.
ALTER TABLE public.calendars
  ADD COLUMN IF NOT EXISTS headline text,
  ADD COLUMN IF NOT EXISTS booking_instructions text,
  ADD COLUMN IF NOT EXISTS hero_image_url text,
  ADD COLUMN IF NOT EXISTS gallery_image_urls jsonb NOT NULL DEFAULT '[]'::jsonb;

UPDATE public.calendars
SET gallery_image_urls = '[]'::jsonb
WHERE gallery_image_urls IS NULL;

COMMIT;
