-- Existing installations may contain an empty operator timezone. That value
-- reaches browser Intl.DateTimeFormat and causes the public booking link to crash.
UPDATE operators
SET time_zone = 'UTC'
WHERE time_zone IS NULL OR btrim(time_zone) = '';

ALTER TABLE operators
  ALTER COLUMN time_zone SET DEFAULT 'UTC';

ALTER TABLE operators
  DROP CONSTRAINT IF EXISTS ck_operators_time_zone_nonblank;

ALTER TABLE operators
  ADD CONSTRAINT ck_operators_time_zone_nonblank
  CHECK (btrim(time_zone) <> '');
