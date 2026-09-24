BEGIN;

ALTER TABLE public.resources
  ADD COLUMN IF NOT EXISTS resource_type text NOT NULL DEFAULT 'equipment',
  ADD COLUMN IF NOT EXISTS capacity_limit integer,
  ADD COLUMN IF NOT EXISTS notes text;

ALTER TABLE public.resources
  DROP CONSTRAINT IF EXISTS resources_capacity_limit_nonnegative;

ALTER TABLE public.resources
  ADD CONSTRAINT resources_capacity_limit_nonnegative
  CHECK (capacity_limit IS NULL OR capacity_limit >= 0);

COMMIT;
