BEGIN;

-- Explicit release marker used by the production readiness probe. The
-- migration history remains authoritative; this marker prevents a backend
-- release from silently connecting to a database that stopped before the
-- hardening baseline was applied.
CREATE TABLE IF NOT EXISTS passport_schema_version (
  version text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO passport_schema_version(version)
VALUES ('028_release_readiness')
ON CONFLICT (version) DO NOTHING;

COMMIT;
