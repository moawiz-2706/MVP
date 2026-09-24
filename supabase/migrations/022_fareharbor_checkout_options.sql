BEGIN;

ALTER TABLE public.booking_orders
  ADD COLUMN IF NOT EXISTS marketing_opt_in boolean NOT NULL DEFAULT false;

COMMIT;
