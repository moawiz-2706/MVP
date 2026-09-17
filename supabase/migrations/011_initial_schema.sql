-- Keep deleted calendars for historical references while allowing their
-- public slug to be reused by a new active calendar.
ALTER TABLE calendars
  DROP CONSTRAINT IF EXISTS calendars_operator_id_slug_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_calendars_active_slug
  ON calendars (operator_id, slug)
  WHERE deleted_at IS NULL;
