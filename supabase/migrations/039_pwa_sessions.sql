-- Passport Staff PWA: revocable device sessions with rotating refresh nonces.
-- Raw refresh JWTs and nonces are never persisted; only a SHA-256 nonce digest is stored.

CREATE TABLE IF NOT EXISTS public.pwa_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  app_user_id uuid NOT NULL REFERENCES public.app_users(id) ON DELETE CASCADE,
  operator_id uuid NOT NULL REFERENCES public.operators(id) ON DELETE CASCADE,
  ghl_location_id text NOT NULL,
  refresh_nonce_digest varchar(128) NOT NULL,
  expires_at timestamptz NOT NULL,
  last_used_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_pwa_sessions_refresh_nonce_digest UNIQUE (refresh_nonce_digest)
);

CREATE INDEX IF NOT EXISTS ix_pwa_sessions_active_expiry
  ON public.pwa_sessions (operator_id, app_user_id, expires_at)
  WHERE revoked_at IS NULL;

CREATE OR REPLACE FUNCTION public.touch_pwa_sessions_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_pwa_sessions_updated_at ON public.pwa_sessions;
CREATE TRIGGER trg_pwa_sessions_updated_at
BEFORE UPDATE ON public.pwa_sessions
FOR EACH ROW EXECUTE FUNCTION public.touch_pwa_sessions_updated_at();

INSERT INTO public.passport_schema_version (version)
VALUES ('039_pwa_sessions')
ON CONFLICT (version) DO NOTHING;
