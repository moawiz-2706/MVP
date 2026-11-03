-- Hotel partners (Sunseeker, Wyvern, Four Points, …) and the revenue split
-- on bookings they send. Additive and safe to re-run. Apply BEFORE deploying
-- code that expects these columns (readiness marker 047).
--
-- 1. booking_partners: a partner per operator, with its own split. Defaults
--    are 20% hotel commission and 30% PGA commission; the operator keeps the
--    rest (50%). A booking with no partner is "Direct" (operator keeps 100%).
-- 2. booking_orders gains the partner and its rates as they were when the
--    booking was made, so a later rate change never rewrites past bookings.
--    The amounts themselves are calculated from the order (gross = price
--    before tax, booking fee and gratuity, reduced proportionally by refunds,
--    zero once the order is cancelled, refunded or expired).
--
-- Rollback (deploy the previous code first):
--   ALTER TABLE public.booking_orders DROP COLUMN IF EXISTS partner_id,
--     DROP COLUMN IF EXISTS partner_name_snapshot,
--     DROP COLUMN IF EXISTS partner_hotel_bps, DROP COLUMN IF EXISTS partner_pga_bps;
--   DROP TABLE IF EXISTS public.booking_partners;
--   DELETE FROM public.passport_schema_version WHERE version = '047_booking_partners';

BEGIN;

CREATE TABLE IF NOT EXISTS public.booking_partners (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES public.operators(id),
  name text NOT NULL,
  code text NOT NULL,
  hotel_commission_bps integer NOT NULL DEFAULT 2000,
  pga_commission_bps integer NOT NULL DEFAULT 3000,
  is_active boolean NOT NULL DEFAULT true,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT booking_partners_code_format CHECK (code ~ '^[a-z0-9]+(?:[-_][a-z0-9]+)*$'),
  CONSTRAINT booking_partners_bps_range CHECK (
    hotel_commission_bps BETWEEN 0 AND 10000
    AND pga_commission_bps BETWEEN 0 AND 10000
    AND hotel_commission_bps + pga_commission_bps <= 10000
  ),
  CONSTRAINT uq_booking_partners_operator_code UNIQUE (operator_id, code)
);
CREATE INDEX IF NOT EXISTS ix_booking_partners_operator
  ON public.booking_partners (operator_id) WHERE deleted_at IS NULL;

ALTER TABLE public.booking_orders
  ADD COLUMN IF NOT EXISTS partner_id uuid REFERENCES public.booking_partners(id),
  ADD COLUMN IF NOT EXISTS partner_name_snapshot text,
  ADD COLUMN IF NOT EXISTS partner_hotel_bps integer,
  ADD COLUMN IF NOT EXISTS partner_pga_bps integer;
CREATE INDEX IF NOT EXISTS ix_booking_orders_operator_partner
  ON public.booking_orders (operator_id, partner_id) WHERE partner_id IS NOT NULL;

ALTER TABLE public.booking_partners ENABLE ROW LEVEL SECURITY;

INSERT INTO public.passport_schema_version(version)
VALUES ('047_booking_partners')
ON CONFLICT (version) DO NOTHING;

COMMIT;
