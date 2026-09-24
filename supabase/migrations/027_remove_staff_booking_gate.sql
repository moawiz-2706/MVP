BEGIN;

-- Staff remains synchronized from GHL for operational visibility, but it is no
-- longer a prerequisite for public availability or appointment creation.
ALTER TABLE public.calendars
  ALTER COLUMN required_staff_roles SET DEFAULT '[]'::jsonb;

UPDATE public.calendars
SET required_staff_roles = '[]'::jsonb
WHERE required_staff_roles IS NULL
   OR required_staff_roles <> '[]'::jsonb;

COMMIT;
