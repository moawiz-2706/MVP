-- Passport Staff Operations PWA: one-time OAuth callback handoffs.
-- The browser receives only this short-lived opaque code; the Passport JWT is
-- issued by /pwa-auth/exchange and is never placed in a URL.

CREATE TABLE IF NOT EXISTS public.pwa_auth_handoffs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code_digest varchar(128) NOT NULL UNIQUE,
  app_user_id uuid NOT NULL REFERENCES public.app_users(id) ON DELETE CASCADE,
  operator_id uuid NOT NULL REFERENCES public.operators(id) ON DELETE CASCADE,
  ghl_location_id text NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_pwa_auth_handoffs_expires
  ON public.pwa_auth_handoffs (expires_at);

CREATE INDEX IF NOT EXISTS ix_pwa_auth_handoffs_operator
  ON public.pwa_auth_handoffs (operator_id, app_user_id);

CREATE OR REPLACE FUNCTION public.touch_pwa_auth_handoffs_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_pwa_auth_handoffs_updated_at ON public.pwa_auth_handoffs;
CREATE TRIGGER trg_pwa_auth_handoffs_updated_at
BEFORE UPDATE ON public.pwa_auth_handoffs
FOR EACH ROW EXECUTE FUNCTION public.touch_pwa_auth_handoffs_updated_at();

INSERT INTO public.passport_schema_version (version)
VALUES ('037_pwa_auth_handoffs')
ON CONFLICT (version) DO NOTHING;
